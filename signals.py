"""
Computes betting signals from stored odds snapshots.

1. steam_moneyline — sharp, fast shift in implied win probability.
2. steam_spread / steam_total — safe no-op currently.
3. reverse_line_movement — only fires if public_betting has rows.
4. bullpen_fatigue (MLB only) — heavy bullpen usage yesterday flagged today.

All moneyline-based signals now also capture the real price, so
recommendations show actual risk instead of treating every play the same.
"""

from datetime import datetime, timedelta, timezone

from config import STEAM_MOVE_SPREAD_POINTS, STEAM_WINDOW_MINUTES, STEAM_MOVE_ML_PROB, BULLPEN_HEAVY_INNINGS_THRESHOLD
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
        """SELECT * FROM odds_snapshots WHERE game_id = ? AND market = 'moneyline'
           ORDER BY captured_at DESC LIMIT 1""",
        (game_id,),
    ).fetchone()
    if not row:
        return None
    return row["home_price"] if side == "home" else row["away_price"]


def compute_bullpen_fatigue_signal(game_id, conn):
    game = conn.execute(
        "SELECT * FROM games WHERE game_id = ? AND sport = 'mlb'", (game_id,)
    ).fetchone()
    if not game:
        return []

    game_date = game["commence_time"][:10]
    prev_date = (datetime.fromisoformat(game_date) - timedelta(days=1)).strftime("%Y-%m-%d")

    def usage_for(team_name):
        row = conn.execute(
            "SELECT * FROM bullpen_usage WHERE game_date = ? AND team = ?",
            (prev_date, team_name),
        ).fetchone()
        return row

    home_usage = usage_for(game["home_team"])
    away_usage = usage_for(game["away_team"])
    if not home_usage or not away_usage:
        return []

    home_heavy = home_usage["relief_innings"] >= BULLPEN_HEAVY_INNINGS_THRESHOLD
    away_heavy = away_usage["relief_innings"] >= BULLPEN_HEAVY_INNINGS_THRESHOLD

    if home_heavy == away_heavy:
        return []

    favored_side = "away" if home_heavy else "home"
    heavy_innings = home_usage["relief_innings"] if home_heavy else away_usage["relief_innings"]
    strength = min(1.0, (heavy_innings - BULLPEN_HEAVY_INNINGS_THRESHOLD + 1) / 3.0)
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
        """SELECT * FROM odds_snapshots WHERE game_id = ? AND market = 'moneyline'
           ORDER BY captured_at ASC""",
        (game_id,),
    ).fetchall()
    if len(ml_rows) < 2:
        return []

    open_row, close_row = ml_rows[0], ml_rows[-1]
    if not all([open_row["home_price"], close_row["home_price"]]):
        return []

    open_home_prob = 1.0 / open_row["home_price"]
    close_home_prob = 1.0 / close_row["home_price"]
    move = close_home_prob - open_home_prob
    line_favored_side = "home" if move > 0 else ("away" if move < 0 else None)
    if line_favored_side is None or line_favored_side == public_side:
        return []

    strength = min(1.0, abs(move) / (STEAM_MOVE_ML_PROB * 2))
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
        found = (compute_spread_steam(game_id, conn)
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
