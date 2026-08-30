"""
SQLite storage layer. One file, zero setup — good enough for years of odds
snapshots across four sports before you'd ever need to graduate to Postgres.
"""

import sqlite3
import os
from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    game_id         TEXT PRIMARY KEY,
    sport           TEXT NOT NULL,
    home_team       TEXT NOT NULL,
    away_team       TEXT NOT NULL,
    commence_time   TEXT NOT NULL,   -- ISO8601 UTC
    season          TEXT
);

CREATE TABLE IF NOT EXISTS odds_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id         TEXT NOT NULL,
    book            TEXT NOT NULL,
    captured_at     TEXT NOT NULL,   -- ISO8601 UTC, when we pulled it
    market          TEXT NOT NULL,   -- 'h2h' | 'spreads' | 'totals'
    home_price      REAL,            -- American odds, moneyline or against-spread price
    away_price      REAL,
    home_point      REAL,            -- spread or total number, home side
    away_point      REAL,
    FOREIGN KEY (game_id) REFERENCES games(game_id)
);

CREATE TABLE IF NOT EXISTS results (
    game_id         TEXT PRIMARY KEY,
    home_score      INTEGER,
    away_score      INTEGER,
    completed       INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (game_id) REFERENCES games(game_id)
);

-- Optional: only populated if/when you plug in a bet%/handle% source.
-- Everything else in the system works without this table having rows.
CREATE TABLE IF NOT EXISTS public_betting (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id         TEXT NOT NULL,
    captured_at     TEXT NOT NULL,
    side            TEXT NOT NULL,   -- 'home' | 'away'
    bet_pct         REAL,            -- % of tickets
    handle_pct      REAL,            -- % of money
    source          TEXT,
    FOREIGN KEY (game_id) REFERENCES games(game_id)
);

CREATE TABLE IF NOT EXISTS signals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id         TEXT NOT NULL,
    sport           TEXT NOT NULL,
    signal_type     TEXT NOT NULL,   -- 'steam_spread' | 'steam_ml' | 'reverse_line_movement'
    favored_side    TEXT NOT NULL,   -- 'home' | 'away'
    strength        REAL NOT NULL,   -- 0-1 normalized
    open_point      REAL,
    close_point     REAL,
    computed_at     TEXT NOT NULL,
    FOREIGN KEY (game_id) REFERENCES games(game_id)
);

CREATE INDEX IF NOT EXISTS idx_odds_game ON odds_snapshots(game_id);
CREATE INDEX IF NOT EXISTS idx_signals_game ON signals(game_id);
CREATE INDEX IF NOT EXISTS idx_games_sport_time ON games(sport, commence_time);
"""


def get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db():
    conn = get_connection()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    print(f"Database ready at {DB_PATH}")


if __name__ == "__main__":
    init_db()
