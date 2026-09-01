"""
ONE-TIME REPAIR. Old odds data from before switching to The Odds API is still
sitting in odds_snapshots, mixed in with new clean data. Since signal
calculations pick the earliest and latest snapshot for a game to detect
movement, that old data was getting used as a bogus "opening price" —
producing wildly inconsistent, untrustworthy signals even though the new
data itself (confirmed against real sportsbook odds) is accurate.

This wipes odds_snapshots entirely and resets signals/recommendations, so
everything rebuilds cleanly from The Odds API going forward.

Usage:
    python purge_stale_odds.py
"""

from db import get_connection, init_db


def run():
    conn = get_connection()

    n_odds = conn.execute("SELECT COUNT(*) c FROM odds_snapshots").fetchone()["c"]
    n_signals = conn.execute("SELECT COUNT(*) c FROM signals").fetchone()["c"]
    n_recs = conn.execute("SELECT COUNT(*) c FROM recommendations").fetchone()["c"]
    print(f"Purging {n_odds} odds_snapshots rows, {n_signals} signals, "
          f"{n_recs} recommendations built on the old mixed data...")

    conn.execute("DELETE FROM recommendations")
    conn.execute("DELETE FROM signals")
    conn.execute("DELETE FROM odds_snapshots")
    conn.commit()
    conn.close()

    print("\nDone. odds_snapshots is now empty — it will repopulate cleanly from "
          "The Odds API on the next ingestion run. Run signals.py after that to "
          "regenerate real, trustworthy signals from clean data only.")


if __name__ == "__main__":
    init_db()
    run()
