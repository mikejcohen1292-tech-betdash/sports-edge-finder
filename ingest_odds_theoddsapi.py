"""
Pulls moneyline AND point spread odds from The Odds API (the-odds-api.com).

Why this is simpler and more trustworthy than the old provider:
  - Team names are spelled out directly on every outcome (e.g. "Atlanta
    Braves"), matched against the event's own home_team/away_team fields.
    No more guessing whether "participant1" means home or away.
  - Markets have clean, documented keys ("h2h" for moneyline, "spreads" for
    point spread). No catalog of ambiguous numeric market IDs to sort through.
  - One API call returns the WHOLE day's games for a sport, across many
    real, well-known sportsbooks (DraftKings, FanDuel, BetMGM, etc.).

Free tier: 500 credits/month. Two markets x one region = 2 credits per call.
4 sports x 1 call/day x 2 credits x 30 days = 240 credits/month.

Usage:
    python ingest_odds_theoddsapi.py --sport mlb

Set your key first (free, no card required, from https://the-odds-api.com):
    export ODDS_API_KEY=your_free_key_here
"""

import argparse
from datetime import datetime, timezone

import requests

from config import SPORTS, ODDS_API_KEY, MAX_THEODDSAPI_CALLS_PER_RUN
from db import get_connection, init_db

BASE = "https://api.the-odds-api.com/v4"


def _require_key():
    if not ODDS_API_KEY:
        raise SystemExit("Set ODDS_API_KEY as an environment variable first. "
                          "Get a free key at https://the-odds-api.com")


def fetch_odds(sport_key, session):
    """Pulls both moneyline (h2h) and point spread markets in one call."""
    _require_key()
    theoddsapi_key = SPORTS[sport_key]["theoddsapi_key"]
    resp = session.get(
        f"{BASE}/sports/{theoddsapi_key}/odds/",
        params={
            "apiKey": ODDS_API_KEY,
            "regions": "us",
            "markets": "h2h,spreads",
            "oddsFormat": "decimal",
        },
        timeout=20,
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


MARKET_LABEL = {"h2h": "moneyline", "spreads": "spread"}


def parse_event(sport_key, event, conn):
    home_team = event.get("home_team")
    away_team = event.get("away_team")
    commence_time = event.get("commence_time")
    if not home_team or not away_team:
        return None, []

    resolved_id = resolve_game_id(conn, sport_key, home_team, away_team, commence_time)
    game_id = resolved_id or f"{sport_key}_{event['id']}"

    games_row = (game_id, sport_key, home_team, away_team, commence_time, str(datetime.now().year))

    captured_at = datetime.now(timezone.utc).isoformat()
    odds_rows = []
    for book in event.get("bookmakers", []):
        book_key = book.get("key", "unknown")
        for market in book.get("markets", []):
            market_label = MARKET_LABEL.get(market.get("key"))
            if not market_label:
                continue
            outcomes = market.get("outcomes", [])
            home_outcome = next((o for o in outcomes if o.get("name") == home_team), None)
            away_outcome = next((o for o in outcomes if o.get("name") == away_team), None)
            if not home_outcome or not away_outcome:
                continue
            home_price = home_outcome.get("price")
            away_price = away_outcome.get("price")
            home_point = home_outcome.get("point")
            away_point = away_outcome.get("point")
            if home_price is None or away_price is None:
                continue
            odds_rows.append((
                game_id, book_key, captured_at, market_label,
                home_price, away_price, home_point, away_point,
            ))

    return games_row, odds_rows


def store(games_row, odds_rows):
    conn = get_connection()
    if games_row:
        conn.execute(
            """INSERT INTO games (game_id, sport, home_team, away_team, commence_time, season)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(game_id) DO NOTHING""",
            games_row,
        )
    conn.executemany(
        """INSERT INTO odds_snapshots
           (game_id, book, captured_at, market, home_price, away_price, home_point, away_point)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        odds_rows,
    )
    conn.commit()
    conn.close()


def run(sport_key):
    session = requests.Session()
    events = fetch_odds(sport_key, session)
    conn = get_connection()

    total_games = 0
    total_odds_rows = 0
    for event in events:
        games_row, odds_rows = parse_event(sport_key, event, conn)
        if games_row is None:
            continue
        store(games_row, odds_rows)
        total_games += 1
        total_odds_rows += len(odds_rows)

    conn.close()
    print(f"{sport_key}: {len(events)} games returned, {total_games} processed, "
          f"{total_odds_rows} odds rows stored (1 API call used).")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport", required=True, choices=SPORTS.keys())
    args = parser.parse_args()

    init_db()
    try:
        run(args.sport)
    except Exception as e:
        print(f"  [ERROR] {args.sport} odds ingestion failed, skipping for today: {e}")


if __name__ == "__main__":
    main()
