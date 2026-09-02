"""
The morning play list. Pulls today's signals, checks them against your
validated threshold, LOGS each qualifying game as an official recommendation
(so it can be tracked and graded later), and prints them - including the
real moneyline price and a suggested unit size, so a heavy favorite and a
live underdog don't look like the same bet.

Usage:
    python recommend.py
    python recommend.py --sport nfl
"""

import argparse
from datetime import datetime, timezone

from config import SPORTS, MIN_SIGNAL_STRENGTH_TO_RECOMMEND, eastern_today, to_eastern_date
from db import get_connection, init_db


def suggest_units(strength):
    if strength >= 0.9:
        return 3
    elif strength >= 0.75:
        return 2
    return 1


def american_odds_str(decimal_price):
    if not decimal_price:
        return "N/A"
    if decimal_price >= 2.0:
        american = (decimal_price - 1) * 100
    else:
        american = -100 / (decimal_price - 1)
    return f"{american:+.0f}"


def get_todays_qualifying_signals(sport_key=None, min_strength=None):
    min_strength = min_strength if min_strength is not None else MIN_SIGNAL_STRENGTH_TO_RECOMMEND
    conn = get_connection()

    today = eastern_today()
    query = """
        SELECT s.*, g.home_team, g.away_team, g.commence_time, g.sport as game_sport
        FROM signals s
        JOIN games g ON g.game_id = s.game_id
        LEFT JOIN results r ON r.game_id = s.game_id
        WHERE (r.completed IS NULL OR r.completed = 0)
          AND s.strength >= ?
    """
    params = [min_strength]
    if sport_key:
        query += " AND g.sport = ?"
        params.append(sport_key)
    query += " ORDER BY s.strength DESC"

    rows = conn.execute(query, params).fetchall()
    rows = [r for r in rows if to_eastern_date(r["commence_time"]) == today]
    conn.close()
    return rows


def log_recommendations(rows):
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()
    logged = 0
    updated = 0
    for r in rows:
        try:
            conn.execute(
                """INSERT INTO recommendations
                   (game_id, sport, signal_id, signal_type, favored_side, strength,
                    close_point, recommended_at, graded, outcome, odds_price)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, ?)""",
                (r["game_id"], r["game_sport"], r["id"], r["signal_type"],
                 r["favored_side"], r["strength"], r["close_point"], now, r["odds_price"]),
            )
            logged += 1
        except Exception:
            if r["odds_price"]:
                cur = conn.execute(
                    "UPDATE recommendations SET odds_price = ? WHERE game_id = ? AND signal_type = ? AND odds_price IS NULL",
                    (r["odds_price"], r["game_id"], r["signal_type"]),
                )
                if cur.rowcount:
                    updated += 1
    conn.commit()
    conn.close()
    if updated:
        print(f"(Also backfilled odds_price on {updated} existing recommendation(s).)")
    return logged


def print_recommendations(rows):
    if not rows:
        print("No games clear the bar today. That's a valid, correct output on plenty of")
        print("days - the system isn't supposed to manufacture a play when there isn't one.")
        return

    print(f"\n{'Sport':<7}{'Matchup':<38}{'Signal':<22}{'Side':<6}{'Odds':>7}{'Units':>7}{'Strength':>9}")
    print("-" * 100)
    for r in rows:
        matchup = f"{r['away_team']} @ {r['home_team']}"
        odds_str = american_odds_str(r["odds_price"])
        units = suggest_units(r["strength"])
        print(f"{r['game_sport']:<7}{matchup:<38}{r['signal_type']:<22}{r['favored_side']:<6}"
              f"{odds_str:>7}{units:>6}u{r['strength']:>9.2f}")
    print()
    print("Strength is relative confidence within the signal, not a win probability.")
    print("Units are a standard confidence-weighted sizing convention, not a proven-optimal size -")
    print("treat as a starting point, and cross-check backtest.py's win% before sizing anything.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport", default=None, choices=list(SPORTS.keys()) + [None])
    parser.add_argument("--min-strength", type=float, default=None)
    args = parser.parse_args()

    init_db()
    recs = get_todays_qualifying_signals(args.sport, args.min_strength)
    n_logged = log_recommendations(recs)
    print_recommendations(recs)
    print(f"\n({n_logged} new recommendations logged to the tracking table.)")
