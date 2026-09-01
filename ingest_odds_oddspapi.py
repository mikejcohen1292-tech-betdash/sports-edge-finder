"""
Pulls odds (moneyline) from OddsPapi and stores snapshots.

IMPORTANT — free tier reality: OddsPapi's free key is capped around 250
requests/month. This script defaults to ONE efficient snapshot per sport per
run.

Only stores the specific market ID identified as the real full-game
moneyline (via fetch_market_catalog.py's catalog) — not every
similarly-shaped market, which was mixing first-5-innings, alternate lines,
and player props together.

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


EXCLUDE_PERIOD_SUBSTRINGS = [
    "1st5", "first5", "5inning", "half", "quarter", "period",
    "1sthalf", "2ndhalf", "1st", "2nd", "3rd", "4th", "set", "leg",
]

_MAIN_ML_CACHE = {}


def _main_moneyline_market_id(sport_id, conn):
    """The one specific market ID (from OddsPapi's own catalog, fetched by
    fetch_market_catalog.py) that represents the real full-game moneyline —
    not a first-5-innings or other sub-market that happens to look the same.
    Returns None if the catalog hasn't been fetched yet for this sport."""
    if sport_id in _MAIN_ML_CACHE:
        return _MAIN_ML_CACHE[sport_id]

    rows = conn.execute(
        "SELECT * FROM market_catalog WHERE sport_id = ? AND player_prop = 0", (sport_id,)
    ).fetchall()
    candidates = []
    for r in rows:
        market_type = (r["market_type"] or "").lower()
        market_name = (r["market_name"] or "").lower()
        period = (r["period"] or "").lower()
        if market_type not in ("moneyline", "1x2", "h2h"):
            continue
        if r["handicap"] not in (0, 0.0, None):
            continue
        if any(sub in period for sub in EXCLUDE_PERIOD_SUBSTRINGS):
            continue
        if any(sub in market_name for sub in EXCLUDE_PERIOD_SUBSTRINGS):
            continue
        candidates.append(r)

    if not candidates:
        _MAIN_ML_CACHE[sport_id] = None
        return None
    candidates.sort(key=lambda r: len(r["market_name"] or ""))
    result = candidates[0]["market_id"]
    _MAIN_ML_CACHE[sport_id] = result
    return result


def _parse_and_store_snapshot(sport_key, fixture, odds_payload, conn):
    """
    Only stores the ONE market ID identified as the real full-game moneyline
    (see _main_moneyline_market_id) — not every similarly-shaped market.
    """
    # CONFIRMED via cross-checking real sportsbook odds: OddsPapi lists the
    # visiting team first. participant1 = AWAY, participant2 = HOME.
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

    sport_id = SPORT_ID_MAP.get(SPORTS[sport_key]["oddspapi_sport"])
    main_ml_id = _main_moneyline_market_id(sport_id, conn) if sport_id else None

    rows_odds = []
    if main_ml_id is None:
        # Catalog not fetched yet for this sport — don't fall back to the old
        # guess-by-shape heuristic. Run fetch_market_catalog.py first.
        return rows_games, rows_odds

    bookmaker_odds = odds_payload.get("bookmakerOdds", {})
    for book_name, book_data in bookmaker_odds.items():
        markets = book_data.get("markets", {})
        market = markets.get(str(main_ml_id))
        if not market:
            continue

        outcomes = market.get("outcomes", {})
        outcome_list = list(outcomes.items())
        if len(outcome_list) < 2:
            continue

        def _price(o):
            players = o[1].get("players", {})
            p0 = players.get("0", {})
            return p0.get("price"), p0.get("line") or p0.get("point")

        (away_price, away_point) = _price(outcome_list[0])
        (home_price, home_point) = _price(outcome_list[1])

        rows_odds.append((
            game_id, book_name, captured_at, "moneyline",
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
