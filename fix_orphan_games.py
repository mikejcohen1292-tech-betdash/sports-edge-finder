"""
ONE-TIME REPAIR. Fixes games that got a separate, fallback ID instead of
being matched to their real ESPN record, which meant results (and grading)
could never attach to them, and often caused the same real game to show up
twice as "duplicate" recommendations.

Usage:
    python fix_orphan_games.py
"""

from db import get_connection, init_db


def looks_like_oddspapi_id(game_id):
    suffix = game_id.split("_", 1)[1] if "_" in game_id else game_id
    return not suffix.isdigit()


def names_match(a, b):
    a, b = (a or "").lower(), (b or "").lower()
    return bool(a) and bool(b) and (a in b or b in a)


def reconcile():
    conn = get_connection()
    all_games = conn.execute("SELECT * FROM games").fetchall()
    orphans = [g for g in all_games if looks_like_oddspapi_id(g["game_id"])]
    espn_style = [g for g in all_games if not looks_like_oddspapi_id(g["game_id"])]
    print(f"Found {len(orphans)} orphan game(s) to check against "
          f"{len(espn_style)} ESPN-sourced game(s) already in the database.")

    fixed = 0
    for g in orphans:
        date_str = g["commence_time"][:10]

        match = None
        for eg in espn_style:
            if eg["sport"] != g["sport"]:
                continue
            if eg["commence_time"][:10] != date_str:
                continue
            if ((names_match(g["home_team"], eg["home_team"]) and names_match(g["away_team"], eg["away_team"])) or
                    (names_match(g["home_team"], eg["away_team"]) and names_match(g["away_team"], eg["home_team"]))):
                match = eg
                break

        if not match:
            print(f"  {g['game_id']} ({g['away_team']} @ {g['home_team']}, {date_str}): no ESPN match found yet")
            continue

        new_id = match["game_id"]
        if new_id == g["game_id"]:
            continue

        for table in ("odds_snapshots", "signals", "public_betting"):
            conn.execute(f"UPDATE {table} SET game_id = ? WHERE game_id = ?", (new_id, g["game_id"]))

        recs = conn.execute("SELECT * FROM recommendations WHERE game_id = ?", (g["game_id"],)).fetchall()
        for rec in recs:
            try:
                conn.execute("UPDATE recommendations SET game_id = ? WHERE id = ?", (new_id, rec["id"]))
            except Exception:
                conn.execute("DELETE FROM recommendations WHERE id = ?", (rec["id"],))
                print(f"    recommendation {rec['id']}: duplicate of an existing pick, removed")

        conn.execute("DELETE FROM games WHERE game_id = ?", (g["game_id"],))
        conn.commit()
        fixed += 1
        print(f"  Merged {g['game_id']} -> {new_id}  ({g['away_team']} @ {g['home_team']}, {date_str})")

    conn.close()
    print(f"\nReconciled {fixed} of {len(orphans)} orphaned game(s).")


if __name__ == "__main__":
    init_db()
    reconcile()
