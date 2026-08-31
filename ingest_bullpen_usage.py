"""
Pulls bullpen (relief pitcher) usage per team per game from MLB's official,
free, no-key-required Stats API. Feeds the bullpen_usage table, which powers
the bullpen-fatigue signal in signals.py.

Run this daily for YESTERDAY's completed games (bullpen usage only matters
once a game is over) — that's what feeds today's fatigue check.

Usage:
    python ingest_bullpen_usage.py                  # yesterday's games
    python ingest_bullpen_usage.py --date 2026-08-29 # a specific date
"""

import argparse
from datetime import datetime, timedelta, timezone

import requests

from db import get_connection, init_db

BASE = "https://statsapi.mlb.com/api/v1"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; sports-edge-finder personal research bot)"}


def innings_pitched_to_float(ip_str):
    """MLB reports innings pitched like '5.2' meaning 5 and 2/3 innings —
    NOT 5.2 decimal. Converts to a true decimal (5.667)."""
    if ip_str is None:
        return 0.0
    whole, _, frac = str(ip_str).partition(".")
    whole = float(whole or 0)
    outs = int(frac or 0)
    return whole + outs / 3.0


def fetch_schedule(date_str):
    resp = requests.get(
        f"{BASE}/schedule",
        params={"sportId": 1, "date": date_str},
        headers=HEADERS, timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    games = []
    for date_block in data.get("dates", []):
        for g in date_block.get("games", []):
            if g.get("status", {}).get("detailedState") != "Final":
                continue
            games.append({
                "gamePk": g["gamePk"],
                "home_team": g["teams"]["home"]["team"]["name"],
                "away_team": g["teams"]["away"]["team"]["name"],
            })
    return games


def fetch_boxscore(game_pk):
    resp = requests.get(f"{BASE}/game/{game_pk}/boxscore", headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.json()


def compute_bullpen_usage(boxscore_side):
    """boxscore_side is boxscore['teams']['home'] or ['away'].
    Returns (relief_innings, relief_pitcher_count). The first pitcher listed
    in 'pitchers' is the starter; everyone else who actually pitched is relief."""
    pitcher_ids = boxscore_side.get("pitchers", [])
    if len(pitcher_ids) < 2:
        return 0.0, 0

    relief_ids = pitcher_ids[1:]
    players = boxscore_side.get("players", {})
    relief_innings = 0.0
    relief_count = 0
    for pid in relief_ids:
        player = players.get(f"ID{pid}")
        if not player:
            continue
        ip_str = player.get("stats", {}).get("pitching", {}).get("inningsPitched")
        if ip_str is None:
            continue
        relief_innings += innings_pitched_to_float(ip_str)
        relief_count += 1
    return round(relief_innings, 2), relief_count


def store_bullpen_usage(team, game_date, relief_innings, relief_count):
    conn = get_connection()
    captured_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO bullpen_usage (team, game_date, relief_innings, relief_pitcher_count, captured_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(team, game_date) DO UPDATE SET
               relief_innings=excluded.relief_innings,
               relief_pitcher_count=excluded.relief_pitcher_count,
               captured_at=excluded.captured_at""",
        (team, game_date, relief_innings, relief_count, captured_at),
    )
    conn.commit()
    conn.close()


def run(date_str):
    games = fetch_schedule(date_str)
    stored = 0
    for g in games:
        try:
            boxscore = fetch_boxscore(g["gamePk"])
        except requests.RequestException as e:
            print(f"  gamePk {g['gamePk']}: request failed ({e})")
            continue

        for side, team_name in (("home", g["home_team"]), ("away", g["away_team"])):
            innings, count = compute_bullpen_usage(boxscore["teams"][side])
            store_bullpen_usage(team_name, date_str, innings, count)
            stored += 1

    print(f"{date_str}: {len(games)} completed games processed, {stored} team-bullpen rows stored.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None, help="YYYY-MM-DD, defaults to yesterday")
    args = parser.parse_args()

    init_db()
    if args.date:
        date_str = args.date
    else:
        date_str = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    run(date_str)


if __name__ == "__main__":
    main()
