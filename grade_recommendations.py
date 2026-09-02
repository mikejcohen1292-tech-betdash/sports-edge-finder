"""
Goes back through every recommendation that was logged but not yet graded,
checks if that game has finished, and records win/loss/push. This is what
turns "here's what we told you" into "here's how that actually did."

Run this daily, after ingest_results_espn.py has pulled the day's finals -
it's cheap and safe to run every time (only touches ungraded rows).

Usage:
    python grade_recommendations.py
"""

from db import get_connection, init_db


def grade_spread_bet(favored_side, close_point, home_score, away_score):
    if close_point is None:
        return None
    margin = home_score - away_score
    if favored_side == "home":
        result = margin + close_point
    else:
        result = -margin - close_point
    if result > 0:
        return "win"
    elif result < 0:
        return "loss"
    return "push"


def grade_total_bet(favored_side, close_point, home_score, away_score):
    if close_point is None:
        return None
    total_score = home_score + away_score
    if favored_side == "over":
        result = total_score - close_point
    else:
        result = close_point - total_score
    if result > 0:
        return "win"
    elif result < 0:
        return "loss"
    return "push"


def grade_moneyline_bet(favored_side, home_score, away_score):
    if home_score == away_score:
        return "push"
    winner = "home" if home_score > away_score else "away"
    return "win" if winner == favored_side else "loss"


def grade_bet(signal_type, favored_side, close_point, home_score, away_score):
    if signal_type == "steam_total":
        return grade_total_bet(favored_side, close_point, home_score, away_score)
    if signal_type in ("steam_moneyline", "bullpen_fatigue", "reverse_line_movement"):
        return grade_moneyline_bet(favored_side, home_score, away_score)
    return grade_spread_bet(favored_side, close_point, home_score, away_score)


def grade_pending_recommendations():
    conn = get_connection()
    pending = conn.execute(
        """SELECT rec.*, r.home_score, r.away_score
           FROM recommendations rec
           JOIN results r ON r.game_id = rec.game_id
           WHERE rec.graded = 0 AND r.completed = 1"""
    ).fetchall()

    graded_count = 0
    for rec in pending:
        outcome = grade_bet(rec["signal_type"], rec["favored_side"], rec["close_point"],
                            rec["home_score"], rec["away_score"])
        if outcome is None:
            continue
        conn.execute(
            "UPDATE recommendations SET graded = 1, outcome = ? WHERE id = ?",
            (outcome, rec["id"]),
        )
        graded_count += 1

    conn.commit()
    conn.close()
    print(f"Graded {graded_count} recommendations that have finished.")
    return graded_count


def summarize_track_record(sport_key=None):
    conn = get_connection()
    query = "SELECT * FROM recommendations WHERE graded = 1"
    params = []
    if sport_key:
        query += " AND sport = ?"
        params.append(sport_key)
    rows = conn.execute(query, params).fetchall()
    conn.close()

    if not rows:
        print("No graded recommendations yet.")
        return

    wins = sum(1 for r in rows if r["outcome"] == "win")
    losses = sum(1 for r in rows if r["outcome"] == "loss")
    pushes = sum(1 for r in rows if r["outcome"] == "push")
    n = wins + losses
    win_pct = (wins / n * 100) if n else 0.0

    print(f"\nTrack record{' (' + sport_key + ')' if sport_key else ''}: "
          f"{wins}-{losses}-{pushes} ({win_pct:.1f}% win rate on {n} decided plays)")
    if n < 30:
        print("Still a small sample - treat this as informational, not conclusive.")


if __name__ == "__main__":
    init_db()
    grade_pending_recommendations()
    summarize_track_record()
