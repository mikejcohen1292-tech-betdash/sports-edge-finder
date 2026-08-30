"""
The morning play list. Pulls today's odds, computes signals on them, and
ranks games against thresholds YOU validated in backtest.py — it never
invents a threshold, it uses whatever MIN_SIGNAL_STRENGTH_TO_RECOMMEND
(config.py) you set after seeing real backtest results.

This is meant to run once per morning, after ingest_odds_oddspapi.py has
pulled today's lines and signals.py has scored them.

Usage:
    python recommend.py
    python recommend.py --sport nfl
"""

import argparse
from datetime import datetime, timezone

from config import SPORTS, MIN_SIGNAL_STRENGTH_TO_RECOMMEND
from db import get_connection, init_db


def get_todays_recommendations(sport_key=None, min_strength=None):
    min_strength = min_strength if min_strength is not None else MIN_SIGNAL_STRENGTH_TO_RECOMMEND
    conn = get_connection()

    today = datetime.now(timezone.utc).date().isoformat()
    query = """
        SELECT s.*, g.home_team, g.away_team, g.commence_time, g.sport as game_sport
        FROM signals s
        JOIN games g ON g.game_id = s.game_id
        LEFT JOIN results r ON r.game_id = s.game_id
        WHERE r.completed IS NULL OR r.completed = 0
          AND s.strength >= ?
          AND date(g.commence_time) = ?
    """
    params = [min_strength, today]
    if sport_key:
        query += " AND g.sport = ?"
        params.append(sport_key)
    query += " ORDER BY s.strength DESC"

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return rows


def print_recommendations(rows):
    if not rows:
        print("No games clear the bar today. That's a valid, correct output on plenty of")
        print("days — the system isn't supposed to manufacture a play when there isn't one.")
        return

    print(f"\n{'Sport':<7}{'Matchup':<38}{'Signal':<22}{'Side':<6}{'Strength':>9}")
    print("-" * 84)
    for r in rows:
        matchup = f"{r['away_team']} @ {r['home_team']}"
        print(f"{r['game_sport']:<7}{matchup:<38}{r['signal_type']:<22}{r['favored_side']:<6}{r['strength']:>9.2f}")
    print()
    print("Strength is relative confidence within the signal, not a win probability.")
    print("Cross-check against backtest.py's win% for this signal type before betting size.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport", default=None, choices=list(SPORTS.keys()) + [None])
    parser.add_argument("--min-strength", type=float, default=None)
    args = parser.parse_args()

    init_db()
    recs = get_todays_recommendations(args.sport, args.min_strength)
    print_recommendations(recs)
