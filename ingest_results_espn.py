"""
Pulls game schedules + final scores from ESPN's public scoreboard endpoints.
No API key needed, no rate limit that matters for this use case. This is what
lets us backfill full past seasons for MLB/WNBA right now, and NFL/NCAAF once
they kick off in a few weeks.

Usage:
    python ingest_results_espn.py --sport mlb --start 2025-03-20 --end 2025-11-01
    python ingest_results_espn.py --sport mlb --today
"""

import argparse
import time
from datetime import datetime, timedelta, timezone

import requests

from config import SPORTS
from db import get_connection, init_db

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"


def espn_scoreboard_url(sport_cfg, date_str):
    # date_str format: YYYYMMDD
    return (
        f"{ESPN_BASE}/{sport_cfg['espn_sport']}/{sport_cfg['espn_league']}"
        f"/scoreboard?dates={date_str}&limit=1000"
    )


def fetch_day(sport_key, sport_cfg, date_obj, session):
    date_str = date_obj.strftime("%Y%m%d")
    url = espn_scoreboard_url(sport_cfg, date_str)
    resp = session.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    events = data.get("events", [])

    rows_games = []
    rows_results = []
    for ev in events:
        game_id = f"{sport_key}_{ev['id']}"
        competitors = ev["competitions"][0]["competitors"]
        home = next(c for c in competitors if c["homeAway"] == "home")
        away = next(c for c in competitors if c["homeAway"] == "away")
        commence_time = ev.get("date")  # ISO8601 UTC already
        status = ev["status"]["type"]
        completed = 1 if status.get("completed") else 0

        rows_games.append((
            game_id, sport_key,
            home["team"]["displayName"], away["team"]["displayName"],
            commence_time, str(date_obj.year),
        ))

        if completed:
            home_score = int(home.get("score", 0) or 0)
            away_score = int(away.get("score", 0) or 0)
            rows_results.append((game_id, home_score, away_score, completed))

    return rows_games, rows_results


def store(rows_games, rows_results):
    conn = get_connection()
    conn.executemany(
        """INSERT INTO games (game_id, sport, home_team, away_team, commence_time, season)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(game_id) DO NOTHING""",
        rows_games,
    )
    conn.executemany(
        """INSERT INTO results (game_id, home_score, away_score, completed)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(game_id) DO UPDATE SET
               home_score=excluded.home_score,
               away_score=excluded.away_score,
               completed=excluded.completed""",
        rows_results,
    )
    conn.commit()
    conn.close()


def backfill(sport_key, start_date, end_date, sleep_sec=0.3):
    sport_cfg = SPORTS[sport_key]
    session = requests.Session()
    day = start_date
    total_games, total_results = 0, 0
    while day <= end_date:
        try:
            g, r = fetch_day(sport_key, sport_cfg, day, session)
            if g:
                store(g, r)
                total_games += len(g)
                total_results += len(r)
                print(f"  {day.date()}: {len(g)} games, {len(r)} finals")
        except requests.RequestException as e:
            print(f"  {day.date()}: request failed ({e}), skipping")
        day += timedelta(days=1)
        time.sleep(sleep_sec)  # be polite to ESPN's servers
    print(f"Done. {total_games} games, {total_results} completed results stored for {sport_key}.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport", required=True, choices=SPORTS.keys())
    parser.add_argument("--start", help="YYYY-MM-DD")
    parser.add_argument("--end", help="YYYY-MM-DD")
    parser.add_argument("--today", action="store_true", help="just pull today's slate")
    args = parser.parse_args()

    init_db()

    if args.today:
        today = datetime.now(timezone.utc)
        backfill(args.sport, today, today)
        return

    if not args.start:
        raise SystemExit("Provide --start (and optionally --end) or use --today")

    start = datetime.strptime(args.start, "%Y-%m-%d")
    end = datetime.strptime(args.end, "%Y-%m-%d") if args.end else datetime.now()
    backfill(args.sport, start, end)


if __name__ == "__main__":
    main()
