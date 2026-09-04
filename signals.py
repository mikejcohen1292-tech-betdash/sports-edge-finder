"""
Computes betting signals from stored odds snapshots.

Three signal types, in order of how much data they need:

1. steam_spread
   Sharp, fast line movement on the point spread in one direction across
   books. Doesn't require bet% data — pure price-action detection.

2. steam_total
   Same idea, applied to the over/under total instead of the spread.

3. reverse_line_movement
   The exact pattern you originally described: line moves AGAINST the side
   getting more public bets. Only computes if the public_betting table has
   rows for a game — otherwise it's skipped, not faked.

Run this after ingesting odds, before backtest.py or recommend.py.
"""

from datetime import datetime, timedelta, timezone

import math

from config import (STEAM_MOVE_SPREAD_POINTS, STEAM_WINDOW_MINUTES, STEAM_MOVE_ML_LOGIT,
                    BULLPEN_LOOKBACK_DAYS, BULLPEN_CUMULATIVE_HEAVY_THRESHOLD, PREFERRED_BOOK)
from db import get_connection, init_db


def _minutes_between(t1, t2):
    return abs((_parse(t2) - _parse(t1)).total_seconds()) / 60.0


def _parse(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _logit(p, eps=1e-4):
    """Converts a probability to log-odds. Clipped away from exactly 0/1 to
    avoid a math domain error on an extreme (but real) price."""
    p = min(max(p, eps), 1 - eps)
    return math.log(p / (1 - p))


def _latest_price_any_book(game_id, market, side, conn):
    """Fallback when the primary (PREFERRED_BOOK) price lookup comes back
    empty for some reason — grabs the most recent real price for that side
    from ANY book, so the displayed odds are never silently blank when real
    data exists somewhere in the table."""
    row = conn.execute(
        """SELECT * FROM odds_snapshots WHERE game_id = ? AND market = ?
           ORDER BY captured_at DESC LIMIT 1""",
        (game_id, market),
    ).fetchone()
    if not row:
        return None
    return row["home_price"] if side == "home" else row["away_price"]


def compute_spread_steam(game_id, conn, sport):
    """MLB's run line is almost always fixed at +/-1.5 — it's the PRICE
    around that line that moves, not the point itself, so a point-movement
    check would almost never fire for MLB. NFL/NCAAF/WNBA spreads move in
    real, meaningful point increments, so point-tracking is the right check
    there. Branches by sport instead of using one check for all of them."""
    if sport == "mlb":
        return _compute_spread_price_steam(game_id, conn)
    return _compute_spread_point_steam(game_id, conn)


def _compute_spread_price_steam(game_id, conn):
    """MLB spread signal: tracks the PRICE at whatever fixed point the line
    sits at, using the same log-odds approach as moneyline steam — the point
    number itself isn't the signal, the market's confidence in covering it is."""
    rows = conn.execute(
        """SELECT * FROM odds_snapshots WHERE game_id = ? AND market = 'spread' AND book = ?
           ORDER BY captured_at ASC""",
        (game_id, PREFERRED_BOOK),
    ).fetchall()
    if len(rows) < 2:
        return []

    open_row, close_row = rows[0], rows[-1]
    if not all([open_row["home_price"], open_row["away_price"],
                close_row["home_price"], close_row["away_price"]]):
        return []
    if open_row["home_point"] != close_row["home_point"]:
        return []

    open_home_prob = 1.0 / open_row["home_price"]
    close_home_prob = 1.0 / close_row["home_price"]
    logit_move = _logit(close_home_prob) - _logit(open_home_prob)
    minutes = _minutes_between(open_row["captured_at"], close_row["captured_at"])

    if abs(logit_move) >= STEAM_MOVE_ML_LOGIT and minutes <= STEAM_WINDOW_MINUTES:
        favored_side = "home" if logit_move > 0 else "away"
        strength = min(1.0, abs(logit_move) / (STEAM_MOVE_ML_LOGIT * 3))
        odds_price = close_row["home_price"] if favored_side == "home" else close_row["away_price"]
        return [{
            "signal_type": "steam_spread",
            "favored_side": favored_side,
            "strength": round(strength, 3),
            "open_point": close_row["home_point"],
            "close_point": close_row["home_point"],
            "odds_price": odds_price,
        }]
    return []


def _compute_spread_point_steam(game_id, conn):
    """NFL/NCAAF/WNBA spread signal: tracks ONE consistent book's spread
    POINT over time (see PREFERRED_BOOK) so open-vs-close is a real point
    move, not a comparison across bookmakers."""
    rows = conn.execute(
        """SELECT * FROM odds_snapshots WHERE game_id = ? AND market = 'spread' AND book = ?
           ORDER BY captured_at ASC""",
        (game_id, PREFERRED_BOOK),
    ).fetchall()
    if len(rows) < 2:
        return []

    open_row, close_row = rows[0], rows[-1]
    if open_row["home_point"] is None or close_row["home_point"] is None:
        return []

    move = close_row["home_point"] - open_row["home_point"]
    minutes = _minutes_between(open_row["captured_at"], close_row["captured_at"])

    if abs(move) >= STEAM_MOVE_SPREAD_POINTS and minutes <= STEAM_WINDOW_MINUTES:
        favored_side = "home" if move < 0 else "away"
        strength = min(1.0, abs(move) / (STEAM_MOVE_SPREAD_POINTS * 3))
        odds_price = close_row["home_price"] if favored_side == "home" else close_row["away_price"]
        if odds_price is None:
            odds_price = _latest_price_any_book(game_id, "spread", favored_side, conn)
        return [{
            "signal_type": "steam_spread",
            "favored_side": favored_side,
            "strength": round(strength, 3),
            "open_point": open_row["home_point"],
            "close_point": close_row["home_point"],
            "odds_price": odds_price,
        }]
    return []


def compute_totals_steam(game_id, conn):
    """Same steam-detection logic, applied to the over/under total line, on
    the same single reliable book."""
    rows = conn.execute(
        """SELECT * FROM odds_snapshots WHERE game_id = ? AND market = 'total' AND book = ?
           ORDER BY captured_at ASC""",
        (game_id, PREFERRED_BOOK),
    ).fetchall()
    if len(rows) < 2:
        return []

    open_row, close_row = rows[0], rows[-1]
    if open_row["home_point"] is None or close_row["home_point"] is None:
        return []

    move = close_row["home_point"] - open_row["home_point"]
    minutes = _minutes_between(open_row["captured_at"], close_row["captured_at"])

    if abs(move) >= STEAM_MOVE_SPREAD_POINTS and minutes <= STEAM_WINDOW_MINUTES:
        favored_side = "over" if move > 0 else "under"
        strength = min(1.0, abs(move) / (STEAM_MOVE_SPREAD_POINTS * 3))
        odds_price = close_row["home_price"] if favored_side == "over" else close_row["away_price"]
        if odds_price is None:
            odds_price = _latest_price_any_book(game_id, "total", "home" if favored_side == "over" else "away", conn)
        return [{
            "signal_type": "steam_total",
            "favored_side": favored_side,
            "strength": round(strength, 3),
            "open_point": open_row["home_point"],
            "close_point": close_row["home_point"],
            "odds_price": odds_price,
        }]
    return []


def compute_moneyline_steam(game_id, conn):
    """Steam detection on moneyline prices, using LOG-ODDS shift rather than
    raw probability difference — a move of a given size is more meaningful
    the further out at the extremes it happens (see STEAM_MOVE_ML_LOGIT).
    Tracks ONE consistent book."""
    rows = conn.execute(
        """SELECT * FROM odds_snapshots WHERE game_id = ? AND market = 'moneyline' AND book = ?
           ORDER BY captured_at ASC""",
        (game_id, PREFERRED_BOOK),
    ).fetchall()
    if len(rows) < 2:
        return []

    open_row, close_row = rows[0], rows[-1]
    if not all([open_row["home_price"], open_row["away_price"],
                close_row["home_price"], close_row["away_price"]]):
        return []

    open_home_prob = 1.0 / open_row["home_price"]
    close_home_prob = 1.0 / close_row["home_price"]
    logit_move = _logit(close_home_prob) - _logit(open_home_prob)
    minutes = _minutes_between(open_row["captured_at"], close_row["captured_at"])

    if abs(logit_move) >= STEAM_MOVE_ML_LOGIT and minutes <= STEAM_WINDOW_MINUTES:
        favored_side = "home" if logit_move > 0 else "away"
        strength = min(1.0, abs(logit_move) / (STEAM_MOVE_ML_LOGIT * 3))
        odds_price = close_row["home_price"] if favored_side == "home" else close_row["away_price"]
        return [{
            "signal_type": "steam_moneyline",
            "favored_side": favored_side,
            "strength": round(strength, 3),
            "open_point": round(open_home_prob, 4),
            "close_point": round(close_home_prob, 4),
            "odds_price": odds_price,
        }]
    return []


def _latest_moneyline_price(game_id, side, conn):
    row = conn.execute(
        """SELECT * FROM odds_snapshots WHERE game_id = ? AND market = 'moneyline' AND book = ?
           ORDER BY captured_at DESC LIMIT 1""",
        (game_id, PREFERRED_BOOK),
    ).fetchone()
    if not row:
        return None
    return row["home_price"] if side == "home" else row["away_price"]


def compute_bullpen_fatigue_signal(game_id, conn):
    """MLB only. Sums relief innings over the past BULLPEN_LOOKBACK_DAYS
    days (not just yesterday) — a bullpen worn down over several straight
    heavy days is more meaningfully fatigued than a single heavy day, and a
    one-day check couldn't see that cumulative pattern at all."""
    game = conn.execute(
        "SELECT * FROM games WHERE game_id = ? AND sport = 'mlb'", (game_id,)
    ).fetchone()
    if not game:
        return []

    game_date = datetime.fromisoformat(game["commence_time"][:10])
    lookback_dates = [
        (game_date - timedelta(days=n)).strftime("%Y-%m-%d")
        for n in range(1, BULLPEN_LOOKBACK_DAYS + 1)
    ]

    def cumulative_usage_for(team_name):
        placeholders = ",".join("?" for _ in lookback_dates)
        row = conn.execute(
            f"SELECT SUM(relief_innings) as total FROM bullpen_usage "
            f"WHERE team = ? AND game_date IN ({placeholders})",
            (team_name, *lookback_dates),
        ).fetchone()
        return row["total"] or 0.0

    home_total = cumulative_usage_for(game["home_team"])
    away_total = cumulative_usage_for(game["away_team"])
    if home_total == 0.0 and away_total == 0.0:
        return []

    home_heavy = home_total >= BULLPEN_CUMULATIVE_HEAVY_THRESHOLD
    away_heavy = away_total >= BULLPEN_CUMULATIVE_HEAVY_THRESHOLD

    if home_heavy == away_heavy:
        return []

    favored_side = "away" if home_heavy else "home"
    heavy_total = home_total if home_heavy else away_total
    strength = min(1.0, (heavy_total - BULLPEN_CUMULATIVE_HEAVY_THRESHOLD + 1) / 4.0)
    odds_price = _latest_moneyline_price(game_id, favored_side, conn)

    return [{
        "signal_type": "bullpen_fatigue",
        "favored_side": favored_side,
        "strength": round(strength, 3),
        "open_point": None,
        "close_point": None,
        "odds_price": odds_price,
    }]


def compute_rlm_signals(game_id, conn):
    betting_rows = conn.execute(
        "SELECT * FROM public_betting WHERE game_id = ? ORDER BY captured_at DESC",
        (game_id,),
    ).fetchall()
    if not betting_rows:
        return []

    latest_captured_at = betting_rows[0]["captured_at"]
    latest_rows = [r for r in betting_rows if r["captured_at"] == latest_captured_at]
    home_pct = next((r["bet_pct"] for r in latest_rows if r["side"] == "home"), None)
    away_pct = next((r["bet_pct"] for r in latest_rows if r["side"] == "away"), None)
    if home_pct is None or away_pct is None:
        return []
    public_side = "home" if home_pct > away_pct else "away"

    ml_rows = conn.execute(
        """SELECT * FROM odds_snapshots WHERE game_id = ? AND market = 'moneyline' AND book = ?
           ORDER BY captured_at ASC""",
        (game_id, PREFERRED_BOOK),
    ).fetchall()
    if len(ml_rows) < 2:
        return []

    open_row, close_row = ml_rows[0], ml_rows[-1]
    if not all([open_row["home_price"], close_row["home_price"]]):
        return []

    open_home_prob = 1.0 / open_row["home_price"]
    close_home_prob = 1.0 / close_row["home_price"]
    logit_move = _logit(close_home_prob) - _logit(open_home_prob)
    line_favored_side = "home" if logit_move > 0 else ("away" if logit_move < 0 else None)
    if line_favored_side is None or line_favored_side == public_side:
        return []

    strength = min(1.0, abs(logit_move) / (STEAM_MOVE_ML_LOGIT * 2))
    odds_price = close_row["home_price"] if line_favored_side == "home" else close_row["away_price"]
    return [{
        "signal_type": "reverse_line_movement",
        "favored_side": line_favored_side,
        "strength": round(strength, 3),
        "open_point": round(open_home_prob, 4),
        "close_point": round(close_home_prob, 4),
        "odds_price": odds_price,
    }]


def compute_all_signals(sport_key=None):
    conn = get_connection()
    query = "SELECT game_id FROM games"
    params = ()
    if sport_key:
        query += " WHERE sport = ?"
        params = (sport_key,)
    game_ids = [r["game_id"] for r in conn.execute(query, params).fetchall()]

    computed_at = datetime.now(timezone.utc).isoformat()
    total = 0
    for game_id in game_ids:
        sport = conn.execute("SELECT sport FROM games WHERE game_id = ?", (game_id,)).fetchone()["sport"]
        found = (compute_spread_steam(game_id, conn, sport)
                 + compute_totals_steam(game_id, conn)
                 + compute_moneyline_steam(game_id, conn)
                 + compute_rlm_signals(game_id, conn))
        if sport == "mlb":
            found += compute_bullpen_fatigue_signal(game_id, conn)
        for sig in found:
            conn.execute(
                """INSERT INTO signals (game_id, sport, signal_type, favored_side, strength,
                                         open_point, close_point, computed_at, odds_price)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (game_id, sport, sig["signal_type"], sig["favored_side"], sig["strength"],
                 sig["open_point"], sig["close_point"], computed_at, sig.get("odds_price")),
            )
            total += 1
    conn.commit()
    conn.close()
    print(f"Computed {total} signals across {len(game_ids)} games"
          f"{' for ' + sport_key if sport_key else ''}.")


if __name__ == "__main__":
    import sys
    init_db()
    sport_arg = sys.argv[1] if len(sys.argv) > 1 else None
    compute_all_signals(sport_arg)
