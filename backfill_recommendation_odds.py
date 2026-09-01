"""
ONE-TIME REPAIR. Some recommendations got logged before odds_price tracking
went live today, so they're missing the real price even though the game's
actual odds data exists. This looks up the latest known moneyline price for
each affected recommendation's game+side and fills it in.

Safe to run more than once — only touches rows where odds_price IS NULL.

Usage:
    python backfill_recommendation_odds.py
"""

from db import get_connection, init_db


def backfill():
    conn = get_connection()
    missing = conn.execute(
        "SELECT * FROM recommendations WHERE odds_price IS NULL"
    ).fetchall()
    print(f"Found {len(missing)} recommendation(s) missing odds_price.")

    filled = 0
    for rec in missing:
        row = conn.execute(
            """SELECT * FROM odds_snapshots WHERE game_id = ? AND market = 'moneyline'
               ORDER BY captured_at DESC LIMIT 1""",
            (rec["game_id"],),
        ).fetchone()
        if not row:
            print(f"  id {rec['id']} ({rec['game_id']}): no moneyline data available yet, skipping")
            continue

        price = row["home_price"] if rec["favored_side"] == "home" else row["away_price"]
        if not price:
            print(f"  id {rec['id']} ({rec['game_id']}): price is null on the {rec['favored_side']} side, skipping")
            continue

        conn.execute("UPDATE recommendations SET odds_price = ? WHERE id = ?", (price, rec["id"]))
        conn.commit()
        filled += 1
        print(f"  id {rec['id']} ({rec['game_id']}, {rec['signal_type']}): filled in odds_price = {price}")

    conn.close()
    print(f"\nBackfilled {filled} of {len(missing)} recommendation(s).")


if __name__ == "__main__":
    init_db()
    backfill()
