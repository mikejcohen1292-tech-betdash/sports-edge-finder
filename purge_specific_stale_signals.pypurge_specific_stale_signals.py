"""
ONE-TIME TARGETED CLEANUP. Two specific steam_spread signals (and their
recommendations) are leftover from the exact moment of the data
contamination bug — computed once, right at the purge boundary, and never
recomputed since because the underlying real data has been stable (no
actual movement) on every check since. Directly confirmed: the real
DraftKings price for these two games shows no 3-point swing — the
signal's claimed movement doesn't match reality.

Usage:
    python purge_specific_stale_signals.py
"""

from db import get_connection, init_db

STALE_SIGNAL_IDS = [206, 207]


def run():
    conn = get_connection()

    for sig_id in STALE_SIGNAL_IDS:
        sig = conn.execute("SELECT * FROM signals WHERE id = ?", (sig_id,)).fetchone()
        if not sig:
            print(f"  signal id {sig_id}: not found, skipping")
            continue
        print(f"  Removing signal id {sig_id}: {sig['game_id']} {sig['signal_type']} "
              f"(strength={sig['strength']}, open={sig['open_point']}, close={sig['close_point']})")

        recs = conn.execute("SELECT id FROM recommendations WHERE signal_id = ?", (sig_id,)).fetchall()
        for rec in recs:
            conn.execute("DELETE FROM recommendations WHERE id = ?", (rec["id"],))
            print(f"    also removed dependent recommendation id {rec['id']}")

        conn.execute("DELETE FROM signals WHERE id = ?", (sig_id,))

    conn.commit()
    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    init_db()
    run()
