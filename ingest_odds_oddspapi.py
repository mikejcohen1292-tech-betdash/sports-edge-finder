"""
Pulls odds (moneyline + spread) from OddsPapi and stores snapshots.

IMPORTANT — free tier reality: OddsPapi's free key is capped around 250
requests/month. That's not enough to poll continuously across 4 sports, so
this script defaults to ONE efficient snapshot per sport per run.

Usage:
    python ingest_odds_oddspapi.py --sport mlb
    python ingest_odds_oddspapi.py --sport mlb --backfill-days 14

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
    time.sleep(2.5)
    sport_id = get_sport_id(sport_cfg["oddspapi_sport"], session)
    date_from = datetime.now(timezone.utc).date().isoformat()
    date_to = (datetime.now(timezone.utc).date() + timedelta(days=days_ahead)).isoformat()

    resp = session.get(
        f"{BASE}/fixtures",
        params={**_key_param(), "sportId": sport_id, "from": date_from, "to": date_to},
        timeout=15,
    )
    if resp.status_code == 404:
        print(f"  [warning] fixtures endpoint 404'd for sportId={sport_id}, treating as no fixtures today.")
        return []
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
    if a_point is None or b_point is None:
        return "moneyline"
    if abs(a_point + b_point) < 0.15:
        return "spread"
    if abs(a_point - b_point) < 0.15:
        return "total"
    return "unknown"


def resolve_game_id(conn, sport_key, home_name, away_name, start_time_iso):
    if not start_time_iso:
        return None
    date_str = start_time_iso[:10]
    candidates = conn.execute(
        "SELECT game_id, home_team, away_team FROM games WHERE sport = ? AND commence_time LIKE ?",
        (sport_key, date_str + "%"),
    ).fetchall()

    def names_match(a, b):
        a, b = (a or "").lower(), (b or "").lower()
        return bool(a) and bool(b) and (a in b or b in a)

    for g in candidates:
        if ((names_match(home_name, g["home_team"]) and names_match(away_name, g["away_team"])) or
                (names_match(home_name, g["away_team"]) and names_match(away_name, g["home_team"]))):
            return g["game_id"]
    return None


def _parse_and_store_snapshot(sport_key, fixture, odds_payload, conn):
    # CONFIRMED via cross-checking real sportsbook odds: OddsPapi lists the
    # visiting team first. participant1 = AWAY, participant2 = HOME — the
    # opposite of what this code originally assumed, which silently swapped
    # every home/away price this ingestion ever recorded.
    fixture_away = fixture.get("participant1Name", "Away")
    fixture_home = fixture.get("participant2Name", "Home")
    start_time = fixture.get("startTime")

    resolved_id = resolve_game_id(conn, sport_key, fixture_home, fixture_away, start_time)
    game_id = resolved_id or f"{sport_key}_{fixture['fixtureId']}"

    captured_at = datetime.now(timezone.utc).isoformat()
    rows_games = [(
        game_id, sport_key, fixture_home, fixture_away,
        start_time, str(datetime.now().year),
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

            # outcome index 0 = participant1 = AWAY, index 1 = participant2 = HOME
            (away_price, away_point) = _price(outcome_list[0])
            (home_price, home_point) = _price(outcome_list[1])
            market_label = _classify_market(home_point, away_point)
            if market_label == "unknown":
                continue

            rows_odds.append((
                game_id, book_name, captured_at, market_label,
                home_price, away_price, home_point, away_point,
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
    conn = get_connection()
    for fixture in fixtures:
        if calls_used >= MAX_ODDSPAPI_CALLS_PER_RUN:
            print(f"  Hit MAX_ODDSPAPI_CALLS_PER_RUN ({MAX_ODDSPAPI_CALLS_PER_RUN}), stopping early to protect quota.")
            break
        try:
            time.sleep(1.2)
            odds_payload = fetch_odds_for_fixture(fixture["fixtureId"], session)
            calls_used += 1
            g, o = _parse_and_store_snapshot(sport_key, fixture, odds_payload, conn)
            store(g, o)
            total_odds_rows += len(o)
        except requests.RequestException as e:
            print(f"  fixture {fixture.get('fixtureId')}: request failed ({e})")
    conn.close()
    print(f"{sport_key}: {len(fixtures)} fixtures checked, {total_odds_rows} odds rows stored, {calls_used} API calls used.")


def run_historical_backfill(sport_key, max_fixtures=None):
    sport_cfg = SPORTS[sport_key]
    session = requests.Session()
    fixtures = fetch_fixtures(sport_cfg, sport_key, session, days_ahead=1)
    if max_fixtures:
        fixtures = fixtures[:max_fixtures]
    calls_used = 1
    total_odds_rows = 0
    conn = get_connection()
    for fixture in fixtures:
        if calls_used >= MAX_ODDSPAPI_CALLS_PER_RUN:
            print(f"  Hit call budget, stopping early.")
            break
        try:
            time.sleep(1.2)
            hist_payload = fetch_historical_odds_for_fixture(fixture["fixtureId"], session)
            calls_used += 1
            g, o = _parse_and_store_snapshot(sport_key, fixture, hist_payload, conn)
            store(g, o)
            total_odds_rows += len(o)
        except requests.RequestException as e:
            print(f"  fixture {fixture.get('fixtureId')}: request failed ({e})")
    conn.close()
    print(f"{sport_key} historical: {total_odds_rows} odds rows stored, {calls_used} API calls used.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport", required=True, choices=SPORTS.keys())
    parser.add_argument("--backfill-days", type=int, default=0,
                         help="attempt to pull free historical odds instead of a live snapshot")
    args = parser.parse_args()

    init_db()
    try:
        if args.backfill_days:
            run_historical_backfill(args.sport)
        else:
            run_daily_snapshot(args.sport)
    except Exception as e:
        print(f"  [ERROR] {args.sport} odds ingestion failed, skipping for today: {e}")


if __name__ == "__main__":
    main()
