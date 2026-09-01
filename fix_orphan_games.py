"""
ONE-TIME REPAIR. Fixes games that were created before the ID-matching fix in
ingest_odds_oddspapi.py — games that got a separate, OddsPapi-only ID instead
of being matched to their real ESPN record, which meant results (and grading)
could never attach to them. This finds those orphans, matches them to the
correct ESPN game by team name + date, and re-points everything (odds,
signals, recommendations) to the correct id.

Safe to run more than once — already-fixed games are simply skipped the
second time.

Usage:
    python fix_orphan_games.py
"""

import re
from datetime import datetime

import requests

from db import get_connection, init_db
from ingest_results_espn import fetch_day, SPORTS


def looks_like_oddspapi_id(game_id):
    return bool(re.search(r"_id\d+$", game_id))


def names_match(a, b):
    a, b = (a or "").lower(), (b or "").lower()
    return bool(a) and bool(b) and (a in b or b in a)


def reconcile():
    conn = get_connection()
    all_games = conn.execute("SELECT * FROM games").fetchall()
    orphans = [g for g in all_games if looks_like_oddspapi_id(g["game_id"])]
    print(f"Found {len(orphans)} OddsPapi-only game(s) to check.")

    session = requests.Session()
    fixed = 0
    for g in orphans:
        sport_key = g["sport"]
        date_str = g["commence_time"][:10]
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue

        sport_cfg = SPORTS.get(sport_key)
        if not sport_cfg:
            continue

        try:
            espn_games, espn_results = fetch_day(sport_key, sport_cfg, date_obj, session)
        except requests.RequestException as e:
            print(f"  {g['game_id']}: ESPN fetch failed ({e})")
            continue

        match = None
        for eg in espn_games:
            eid, esport, ehome, eaway, ecommence, eseason = eg
            if ((names_match(g["home_team"], ehome) and names_match(g["away_team"], eaway)) or
                    (names_match(g["home_team"], eaway) and names_match(g["away_team"], ehome))):
                match = eg
                break

        if not match:
            print(f"  {g['game_id']} ({g['away_team']} @ {g['home_team']}, {date_str}): no ESPN match found yet")
            continue

        new_id = match[0]
        if new_id == g["game_id"]:
            continue

        conn.execute(
            """INSERT INTO games (game_id, sport, home_team, away_team, commence_time, season)
               VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(game_id) DO NOTHING""",
            match,
        )
        for r in espn_results:
            if r[0] == new_id:
                conn.execute(
                    """INSERT INTO results (game_id, home_score, away_score, completed)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(game_id) DO UPDATE SET
                           home_score=excluded.home_score,
                           away_score=excluded.away_score,
                           completed=excluded.completed""",
                    r,
                )

        for table in ("odds_snapshots", "signals", "public_betting"):
            conn.execute(f"UPDATE {table} SET game_id = ? WHERE game_id = ?", (new_id, g["game_id"]))

        recs = conn.execute("SELECT * FROM recommendations WHERE game_id = ?", (g["game_id"],)).fetchall()
        for rec in recs:
            try:
                conn.execute("UPDATE recommendations SET game_id = ? WHERE id = ?", (new_id, rec["id"]))
            except Exception as e:
                print(f"    recommendation {rec['id']}: could not repoint ({e})")

        conn.execute("DELETE FROM games WHERE game_id = ?", (g["game_id"],))
        conn.commit()
        fixed += 1
        print(f"  Merged {g['game_id']} -> {new_id}  ({g['away_team']} @ {g['home_team']}, {date_str})")

    conn.close()
    print(f"\nReconciled {fixed} of {len(orphans)} orphaned game(s).")


if __name__ == "__main__":
    init_db()
    reconcile()
