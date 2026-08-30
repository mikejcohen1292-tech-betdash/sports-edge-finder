"""
Pulls odds (moneyline + spread) from OddsPapi and stores snapshots.

IMPORTANT — free tier reality: OddsPapi's free key is capped around 250
requests/month. That's not enough to poll continuously across 4 sports, so
this script defaults to ONE efficient snapshot per sport per run. Point cron
at this a few times a day (e.g. morning open, midday, close) rather than
polling every few minutes, or you'll burn the month's quota in a week.

Usage:
    python ingest_odds_oddspapi.py --sport mlb                 # today's live snapshot
    python ingest_odds_oddspapi.py --sport mlb --backfill-days 14  # free historical, if available

Set your key first:
    export ODDSPAPI_KEY=your_free_key_here
"""

import argparse
import time
from datetime import datetime, timedelta, timezone

import requests

from config import SPORTS, ODDSPAPI_KEY, MAX_ODDSPAPI_CALLS_PER_RUN
from db import get_connection, init_db

BASE = "https://api.oddspapi.io/v4"

SPORT_ID_MAP = {
    "baseball": 13,
    "basketball": 11,
    "american-football": 14,
}

LEAGUE_NAME_MATCH = {
    "mlb": ["mlb", "major league baseball"],
    "wnba": ["wnba"],
    "nfl": ["nfl"],
    "ncaaf": ["ncaa", "college football", "ncaaf"],
}


def _key_param():
    if not ODDSPAPI_KEY:
        raise SystemExit("Set ODDSPAPI_KEY as an environment variable first. Get a free key at oddspapi.io")
    return {"apiKey": ODDSPAPI_KEY}


def get_sport_id(sport_slug, session):
    if sport_slug in SPORT_ID_MAP:
        return SPORT_ID_MAP[sport_slug]
    raise RuntimeError(f"No known OddsPapi sportId for slug '{sport_slug}'. "
                        f"Known: {list(SPORT_ID_MAP.keys())}")


def fetch_fixtures(sport_cfg, league_key, session, days_ahead=1):
    """Fixtures for a sport, filtered to the target league by tournamentName, with
    fixtures that actually have odds posted (hasOdds=true) sorted first — otherwise
    we can easily spend our call budget on games nobody's priced yet."""
    time.sleep(2.5)
    sport_id = get_sport_id(sport_cfg["oddspapi_sport"], session)
    date_from = datetime.now(timezone.utc).date().isoformat()
    date_to = (datetime.now(timezone.utc).date() + timedelta(days=days_ahead)).isoformat()

    resp = session.get(
        f"{BASE}/fixtures",
        params={**_key_param(), "sportId": sport_id, "from": date_from, "to": date_to},
        timeout=15,
    )
    resp.raise_for_status()
    all_fixtures = resp.json()
    if isinstance(all_fixtures, dict):
        all_fixtures = all_fixtures.get("fixtures", [])

    needles = LEAGUE_NAME_MATCH.get(league_key, [league_key])
    matched = [
        f for f in all_fixtures
        if any(n in (f.get("tournamentName") or "").lower() for n in needles)
    ]
    matched.sort(key=lambda f: not f.get("hasOdds", False))
    return matched


def fetch_odds_for_fixture(fixture_id, session):
    resp = session.get(
        f"{BASE}/odds",
        params={**_key_param(), "fixtureId": fixture_id},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_historical_odds_for_fixture(fixture_id, session):
    resp = session.get(
        f"{BASE}/historical-odds",
        params={**_key_param(), "fixtureId": fixture_id},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def _classify_market(a_point, b_point):
    """Identifies spread / total / moneyline from the actual price shape rather
    than OddsPapi's internal numeric market IDs, which aren't publicly documented
    per-sport and would otherwise be a guess. The pattern is reliable:
      - no point on either side           -> moneyline
      - points are opposite (~sum to 0)   -> spread  (e.g. -1.5 / +1.5)
      - points are equal (~same number)   -> total    (e.g. 8.5 / 8.5, over/under)
    """
    if a_point is None or b_point is None:
        return "moneyline"
    if abs(a_point + b_point) < 0.15:
        return "spread"
    if abs(a_point - b_point) < 0.15:
        return "total"
    return "unknown"


def _parse_and_store_snapshot(sport_key, fixture, odds_payload):
    """
    Normalizes OddsPapi's response into our odds_snapshots rows.

    OddsPapi nests odds under bookmakerOdds -> {book} -> markets -> {numeric
    market id} -> outcomes -> {numeric outcome id} -> players -> "0" -> price.
    We classify each market as spread/total/moneyline by its price SHAPE
    (see _classify_market) rather than trusting the numeric market ID, since
    that ID scheme isn't documented per-sport and would just be a guess.
    """
    game_id = f"{sport_key}_{fixture['fixtureId']}"
    captured_at = datetime.now(timezone.utc).isoformat()
    rows_games = [(
        game_id, sport_key,
        fixture.get("participant1Name", "Home"),
        fixture.get("participant2Name", "Away"),
        fixture.get("startTime"), str(datetime.now().year),
    )]

    rows_odds = []
    bookmaker_odds = odds_payload.get("bookmakerOdds", {})
    for book_name, book_data in bookmaker_odds.items():
        markets = book_data.get("markets", {})
        for market_id, market in markets.items():
            outcomes = market.get("outcomes", {})
            outcome_list = list(outcomes.items())
            if len(outcome_list) < 2:
                continue

            def _price(o):
                players = o[1].get("players", {})
                p0 = players.get("0", {})
                return p0.get("price"), p0.get("line") or p0.get("point")

            (a_price, a_point) = _price(outcome_list[0])
            (b_price, b_point) = _price(outcome_list[1])
            market_label = _classify_market(a_point, b_point)
            if market_label == "unknown":
                continue

            rows_odds.append((
                game_id, book_name, captured_at, market_label,
                a_price, b_price, a_point, b_point,
            ))
    return rows_games, rows_odds


def store(rows_games, rows_odds):
    conn = get_connection()
    conn.executemany(
        """INSERT INTO games (game_id, sport, home_team, away_team, commence_time, season)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(game_id) DO NOTHING""",
        rows_games,
    )
    conn.executemany(
        """INSERT INTO odds_snapshots
           (game_id, book, captured_at, market, home_price, away_price, home_point, away_point)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        rows_odds,
    )
    conn.commit()
    conn.close()


def run_daily_snapshot(sport_key):
    sport_cfg = SPORTS[sport_key]
    session = requests.Session()
    fixtures = fetch_fixtures(sport_cfg, sport_key, session)
    calls_used = 1
    total_odds_rows = 0
    for fixture in fixtures:
        if calls_used >= MAX_ODDSPAPI_CALLS_PER_RUN:
            print(f"  Hit MAX_ODDSPAPI_CALLS_PER_RUN ({MAX_ODDSPAPI_CALLS_PER_RUN}), stopping early to protect quota.")
            break
        try:
            time.sleep(1.2)
            odds_payload = fetch_odds_for_fixture(fixture["fixtureId"], session)
            calls_used += 1
            g, o = _parse_and_store_snapshot(sport_key, fixture, odds_payload)
            store(g, o)
            total_odds_rows += len(o)
        except requests.RequestException as e:
            print(f"  fixture {fixture.get('fixtureId')}: request failed ({e})")
    print(f"{sport_key}: {len(fixtures)} fixtures checked, {total_odds_rows} odds rows stored, {calls_used} API calls used.")


def run_historical_backfill(sport_key, max_fixtures=None):
    """
    Pulls whatever free historical odds OddsPapi has archived. Coverage depends
    on when their archive started, not on your season needs — check what comes
    back before assuming it's complete.
    """
    sport_cfg = SPORTS[sport_key]
    session = requests.Session()
    fixtures = fetch_fixtures(sport_cfg, sport_key, session, days_ahead=1)
    if max_fixtures:
        fixtures = fixtures[:max_fixtures]
    calls_used = 1
    total_odds_rows = 0
    for fixture in fixtures:
        if calls_used >= MAX_ODDSPAPI_CALLS_PER_RUN:
            print(f"  Hit call budget, stopping early.")
            break
        try:
            time.sleep(1.2)
            hist_payload = fetch_historical_odds_for_fixture(fixture["fixtureId"], session)
            calls_used += 1
            g, o = _parse_and_store_snapshot(sport_key, fixture, hist_payload)
            store(g, o)
            total_odds_rows += len(o)
        except requests.RequestException as e:
            print(f"  fixture {fixture.get('fixtureId')}: request failed ({e})")
    print(f"{sport_key} historical: {total_odds_rows} odds rows stored, {calls_used} API calls used.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport", required=True, choices=SPORTS.keys())
    parser.add_argument("--backfill-days", type=int, default=0,
                         help="attempt to pull free historical odds instead of a live snapshot")
    args = parser.parse_args()

    init_db()
    if args.backfill_days:
        run_historical_backfill(args.sport)
    else:
        run_daily_snapshot(args.sport)


if __name__ == "__main__":
    main()
