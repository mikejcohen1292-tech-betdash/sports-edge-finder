"""
Computes betting signals from stored odds snapshots.

Signal types, in order of how much data they need:

1. steam_moneyline
   Sharp, fast shift in implied win probability from moneyline price moves.
   This is the one working reliably right now with real data.

2. steam_spread / steam_total
   Same idea for the point spread and over/under. Currently a safe no-op —
   OddsPapi structures these markets with each specific point value as its
   own market ID (like Asian Handicaps), which needs one more piece of
   decoding work before these produce real signals.

3. reverse_line_movement
   The exact pattern you originally described: line moves AGAINST the side
   getting more public bets. Only computes if the public_betting table has
   rows for a game — otherwise it's skipped, not faked.

Run this after ingesting odds, before backtest.py or recommend.py.
"""

from datetime import datetime, timezone

from config import STEAM_MOVE_SPREAD_POINTS, STEAM_WINDOW_MINUTES, STEAM_MOVE_ML_PROB
from db import get_connection, init_db


def _minutes_between(t1, t2):
    return abs((_parse(t2) - _parse(t1)).total_seconds()) / 60.0


def _parse(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def compute_spread_steam(game_id, conn):
    rows = conn.execute(
        """SELECT * FROM odds_snapshots WHERE game_id = ? AND market = 'spread'
           ORDER BY captured_at ASC""",
        (game_id,),
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
        return [{
            "signal_type": "steam_spread",
            "favored_side": favored_side,
            "strength": round(strength, 3),
            "open_point": open_row["home_point"],
            "close_point": close_row["home_point"],
        }]
    return []


def compute_totals_steam(game_id, conn):
    rows = conn.execute(
        """SELECT * FROM odds_snapshots WHERE game_id = ? AND market = 'total'
           ORDER BY captured_at ASC""",
        (game_id,),
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
        return [{
            "signal_type": "steam_total",
            "favored_side": favored_side,
            "strength": round(strength, 3),
            "open_point": open_row["home_point"],
            "close_point": close_row["home_point"],
        }]
    return []


def compute_moneyline_steam(game_id, conn):
    """Steam detection on moneyline prices, using implied probability shift
    (1/decimal_price) rather than raw price, since a 1.50->1.40 move means
    something different at different starting prices. This is the signal
    that's actually reliable right now — spread/total markets need one more
    piece of setup (OddsPapi structures each specific point as its own market,
    similar to Asian Handicaps) before they're trustworthy."""
    rows = conn.execute(
        """SELECT * FROM odds_snapshots WHERE game_id = ? AND market = 'moneyline'
           ORDER BY captured_at ASC""",
        (game_id,),
    ).fetchall()
    if len(rows) < 2:
        return []

    open_row, close_row = rows[0], rows[-1]
    if not all([open_row["home_price"], open_row["away_price"],
                close_row["home_price"], close_row["away_price"]]):
        return []

    open_home_prob = 1.0 / open_row["home_price"]
    close_home_prob = 1.0 / close_row["home_price"]
    move = close_home_prob - open_home_prob
    minutes = _minutes_between(open_row["captured_at"], close_row["captured_at"])

    if abs(move) >= STEAM_MOVE_ML_PROB and minutes <= STEAM_WINDOW_MINUTES:
        favored_side = "home" if move > 0 else "away"
        strength = min(1.0, abs(move) / (STEAM_MOVE_ML_PROB * 3))
        return [{
            "signal_type": "steam_moneyline",
            "favored_side": favored_side,
            "strength": round(strength, 3),
            "open_point": round(open_home_prob, 4),
            "close_point": round(close_home_prob, 4),
        }]
    return []


def compute_rlm_signals(game_id, conn):
    """Only fires if public_betting data exists for this game."""
    betting_rows = conn.execute(
        "SELECT * FROM public_betting WHERE game_id = ? ORDER BY captured_at DESC LIMIT 1",
        (game_id,),
    ).fetchall()
    if not betting_rows:
        return []

    latest_bet = betting_rows[0]
    public_side = latest_bet["side"]

    spread_rows = conn.execute(
        """SELECT * FROM odds_snapshots WHERE game_id = ? AND market = 'spread'
           ORDER BY captured_at ASC""",
        (game_id,),
    ).fetchall()
    if len(spread_rows) < 2:
        return []

    open_row, close_row = spread_rows[0], spread_rows[-1]
    if open_row["home_point"] is None or close_row["home_point"] is None:
        return []

    move = close_row["home_point"] - open_row["home_point"]
    line_favored_side = "home" if move < 0 else ("away" if move > 0 else None)
    if line_favored_side is None or line_favored_side == public_side:
        return []

    strength = min(1.0, abs(move) / (STEAM_MOVE_SPREAD_POINTS * 2))
    return [{
        "signal_type": "reverse_line_movement",
        "favored_side": line_favored_side,
        "strength": round(strength, 3),
        "open_point": open_row["home_point"],
        "close_point": close_row["home_point"],
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
        found = (compute_spread_steam(game_id, conn)
                 + compute_totals_steam(game_id, conn)
                 + compute_moneyline_steam(game_id, conn)
                 + compute_rlm_signals(game_id, conn))
        for sig in found:
            conn.execute(
                """INSERT INTO signals (game_id, sport, signal_type, favored_side, strength,
                                         open_point, close_point, computed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (game_id, sport, sig["signal_type"], sig["favored_side"], sig["strength"],
                 sig["open_point"], sig["close_point"], computed_at),
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
