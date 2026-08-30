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
from datetime import datetime, timezone

import requests

from config import SPORTS, ODDSPAPI_KEY, MAX_ODDSPAPI_CALLS_PER_RUN
from db import get_connection, init_db

BASE = "https://oddspapi.io/v4"


def _headers():
    if not ODDSPAPI_KEY:
        raise SystemExit("Set ODDSPAPI_KEY as an environment variable first. Get a free key at oddspapi.io")
    return {"Authorization": f"Bearer {ODDSPAPI_KEY}"}


def fetch_fixtures(sport_cfg, session):
    """Today's/upcoming fixtures for a sport+league."""
    resp = session.get(
        f"{BASE}/fixtures",
        params={"sport": sport_cfg["oddspapi_sport"], "league": sport_cfg["oddspapi_league"]},
        headers=_headers(),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("fixtures", [])


def fetch_odds_for_fixture(fixture_id, session):
    resp = session.get(
        f"{BASE}/odds",
        params={"fixtureId": fixture_id, "markets": "h2h,spreads"},
        headers=_headers(),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_historical_odds_for_fixture(fixture_id, session):
    resp = session.get(
        f"{BASE}/historical-odds",
        params={"fixtureId": fixture_id},
        headers=_headers(),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def _parse_and_store_snapshot(sport_key, fixture, odds_payload):
    """
    Normalizes OddsPapi's response into our odds_snapshots rows.
    NOTE: exact response shape can shift as the provider evolves their API —
    check response JSON against this parser if OddsPapi changes their schema,
    and adjust the key lookups below accordingly.
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
    for book_name, book_data in odds_payload.get("bookmakers", {}).items():
        for market_name, market in book_data.get("markets", {}).items():
            if market_name not in ("h2h", "spreads"):
                continue
            outcomes = market.get("outcomes", {})
            home_price = outcomes.get("home", {}).get("price")
            away_price = outcomes.get("away", {}).get("price")
            home_point = outcomes.get("home", {}).get("point")
            away_point = outcomes.get("away", {}).get("point")
            rows_odds.append((
                game_id, book_name, captured_at, market_name,
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
    fixtures = fetch_fixtures(sport_cfg, session)
    calls_used = 1
    total_odds_rows = 0
    for fixture in fixtures:
        if calls_used >= MAX_ODDSPAPI_CALLS_PER_RUN:
            print(f"  Hit MAX_ODDSPAPI_CALLS_PER_RUN ({MAX_ODDSPAPI_CALLS_PER_RUN}), stopping early to protect quota.")
            break
        try:
            odds_payload = fetch_odds_for_fixture(fixture["fixtureId"], session)
            calls_used += 1
            g, o = _parse_and_store_snapshot(sport_key, fixture, odds_payload)
            store(g, o)
            total_odds_rows += len(o)
        except requests.RequestException as e:
            print(f"  fixture {fixture.get('fixtureId')}: request failed ({e})")
        time.sleep(0.5)
    print(f"{sport_key}: {len(fixtures)} fixtures checked, {total_odds_rows} odds rows stored, {calls_used} API calls used.")


def run_historical_backfill(sport_key, max_fixtures=None):
    """
    Pulls whatever free historical odds OddsPapi has archived. Coverage depends
    on when their archive started, not on your season needs — check what comes
    back before assuming it's complete.
    """
    sport_cfg = SPORTS[sport_key]
    session = requests.Session()
    fixtures = fetch_fixtures(sport_cfg, session)
    if max_fixtures:
        fixtures = fixtures[:max_fixtures]
    calls_used = 1
    total_odds_rows = 0
    for fixture in fixtures:
        if calls_used >= MAX_ODDSPAPI_CALLS_PER_RUN:
            print(f"  Hit call budget, stopping early.")
            break
        try:
            hist_payload = fetch_historical_odds_for_fixture(fixture["fixtureId"], session)
            calls_used += 1
            g, o = _parse_and_store_snapshot(sport_key, fixture, hist_payload)
            store(g, o)
            total_odds_rows += len(o)
        except requests.RequestException as e:
            print(f"  fixture {fixture.get('fixtureId')}: request failed ({e})")
        time.sleep(0.5)
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
