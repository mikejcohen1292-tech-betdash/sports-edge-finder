"""
ONE-TIME REPAIR for a real bug: OddsPapi lists the away team first
(participant1) and home team second (participant2), but the ingestion code
originally assumed the opposite — so every home_price/away_price pair
recorded so far has been swapped.

This script:
  1. Swaps home_price/away_price (and home_point/away_point) on every
     existing odds_snapshots row, so the data at rest is correct.
  2. Wipes signals and recommendations, since they were computed from the
     swapped data and can't be trusted.

After this runs, re-run signals.py to regenerate everything correctly.

Usage:
    python fix_home_away_swap.py
"""

from db import get_connection, init_db


def run():
    conn = get_connection()

    n_odds = conn.execute("SELECT COUNT(*) c FROM odds_snapshots").fetchone()["c"]
    print(f"Swapping home/away on {n_odds} odds_snapshots rows...")
    conn.execute("""
        UPDATE odds_snapshots
        SET home_price = away_price,
            away_price = home_price,
            home_point = away_point,
            away_point = home_point
    """)
    conn.commit()

    n_signals = conn.execute("SELECT COUNT(*) c FROM signals").fetchone()["c"]
    n_recs = conn.execute("SELECT COUNT(*) c FROM recommendations").fetchone()["c"]
    print(f"Clearing {n_signals} signals and {n_recs} recommendations computed from the bad data...")
    conn.execute("DELETE FROM signals")
    conn.execute("DELETE FROM recommendations")
    conn.commit()

    conn.close()
    print("\nDone. Run signals.py next to regenerate everything from the corrected data.")


if __name__ == "__main__":
    init_db()
    run()
