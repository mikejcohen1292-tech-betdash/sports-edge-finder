"""
Joins computed signals to actual game results and reports whether each
signal type actually wins money — with sample-size honesty baked in.

This is the answer to your original question: is this trend real, or noise?

Usage:
    python backtest.py                # all sports, all signal types
    python backtest.py --sport mlb
"""

import argparse
import csv
import math

from db import get_connection, init_db

STANDARD_JUICE = -110


def american_to_profit(stake, odds):
    if odds > 0:
        return stake * (odds / 100.0)
    else:
        return stake * (100.0 / abs(odds))


def wilson_interval(wins, n, z=1.96):
    """95% confidence interval for a win rate — the honest way to look at
    a small sample instead of trusting the raw percentage."""
    if n == 0:
        return (0.0, 0.0)
    phat = wins / n
    denom = 1 + z**2 / n
    center = phat + z**2 / (2 * n)
    margin = z * math.sqrt((phat * (1 - phat) + z**2 / (4 * n)) / n)
    low = (center - margin) / denom
    high = (center + margin) / denom
    return (max(0, low), min(1, high))


def grade_spread_bet(favored_side, close_point, home_score, away_score):
    """Grades an ATS bet on favored_side at the closing home_point spread."""
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
    """Grades an over/under bet at the closing total line."""
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


def grade_bet(signal_type, favored_side, close_point, home_score, away_score):
    if signal_type == "steam_total":
        return grade_total_bet(favored_side, close_point, home_score, away_score)
    return grade_spread_bet(favored_side, close_point, home_score, away_score)


def run_backtest(sport_key=None, min_strength=0.0):
    conn = get_connection()
    query = """
        SELECT s.*, r.home_score, r.away_score, g.sport as game_sport
        FROM signals s
        JOIN results r ON r.game_id = s.game_id AND r.completed = 1
        JOIN games g ON g.game_id = s.game_id
        WHERE s.strength >= ?
    """
    params = [min_strength]
    if sport_key:
        query += " AND g.sport = ?"
        params.append(sport_key)

    rows = conn.execute(query, params).fetchall()
    conn.close()

    buckets = {}
    for r in rows:
        if r["signal_type"] not in ("steam_spread", "steam_total", "reverse_line_movement"):
            continue
        if r["close_point"] is None:
            continue
        key = (r["game_sport"], r["signal_type"])
        buckets.setdefault(key, []).append(r)

    results_summary = []
    for (sport, sig_type), games in buckets.items():
        wins = losses = pushes = 0
        total_profit = 0.0
        for g in games:
            outcome = grade_bet(g["signal_type"], g["favored_side"], g["close_point"], g["home_score"], g["away_score"])
            if outcome == "win":
                wins += 1
                total_profit += american_to_profit(100, STANDARD_JUICE)
            elif outcome == "loss":
                losses += 1
                total_profit -= 100
            else:
                pushes += 1

        n_decided = wins + losses
        win_pct = wins / n_decided if n_decided else 0.0
        low, high = wilson_interval(wins, n_decided)
        roi_pct = (total_profit / (n_decided * 100)) * 100 if n_decided else 0.0

        results_summary.append({
            "sport": sport, "signal_type": sig_type, "n": n_decided,
            "wins": wins, "losses": losses, "pushes": pushes,
            "win_pct": round(win_pct * 100, 1),
            "ci_low": round(low * 100, 1), "ci_high": round(high * 100, 1),
            "roi_pct": round(roi_pct, 1),
        })

    results_summary.sort(key=lambda x: (-x["n"]))
    return results_summary


def print_report(rows):
    if not rows:
        print("No completed, graded signals yet. Run ingest + signals first, and give it time to accumulate.")
        return
    print(f"\n{'Sport':<8}{'Signal':<22}{'N':>6}{'Win%':>8}{'95% CI':>16}{'ROI%':>9}")
    print("-" * 70)
    for r in rows:
        ci = f"{r['ci_low']}-{r['ci_high']}"
        flag = "  <- small sample, don't trust yet" if r["n"] < 30 else (
               "  <- decent, keep watching" if r["n"] < 100 else "")
        print(f"{r['sport']:<8}{r['signal_type']:<22}{r['n']:>6}{r['win_pct']:>7.1f}%{ci:>16}{r['roi_pct']:>8.1f}%{flag}")
    print()
    print("Reading this: break-even at -110 is 52.4% win rate. Anything with a 95% CI")
    print("that stays above 52.4% at n>=100 is worth taking seriously. Below n=30, this")
    print("is not signal yet — it's noise with a shape.")


def export_csv(rows, path="data/backtest_report.csv"):
    if not rows:
        return
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"Exported to {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport", default=None)
    parser.add_argument("--min-strength", type=float, default=0.0)
    args = parser.parse_args()

    init_db()
    report = run_backtest(args.sport, args.min_strength)
    print_report(report)
    export_csv(report)
