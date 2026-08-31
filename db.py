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
    commence_time   TEXT NOT NULL,
    season          TEXT
);

CREATE TABLE IF NOT EXISTS odds_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id         TEXT NOT NULL,
    book            TEXT NOT NULL,
    captured_at     TEXT NOT NULL,
    market          TEXT NOT NULL,
    home_price      REAL,
    away_price      REAL,
    home_point      REAL,
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

CREATE TABLE IF NOT EXISTS public_betting (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id         TEXT NOT NULL,
    captured_at     TEXT NOT NULL,
    side            TEXT NOT NULL,
    bet_pct         REAL,
    handle_pct      REAL,
    source          TEXT,
    FOREIGN KEY (game_id) REFERENCES games(game_id)
);

CREATE TABLE IF NOT EXISTS signals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id         TEXT NOT NULL,
    sport           TEXT NOT NULL,
    signal_type     TEXT NOT NULL,
    favored_side    TEXT NOT NULL,
    strength        REAL NOT NULL,
    open_point      REAL,
    close_point     REAL,
    computed_at     TEXT NOT NULL,
    FOREIGN KEY (game_id) REFERENCES games(game_id)
);

CREATE TABLE IF NOT EXISTS recommendations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id         TEXT NOT NULL,
    sport           TEXT NOT NULL,
    signal_id       INTEGER NOT NULL,
    signal_type     TEXT NOT NULL,
    favored_side    TEXT NOT NULL,
    strength        REAL NOT NULL,
    close_point     REAL,
    recommended_at  TEXT NOT NULL,
    graded          INTEGER NOT NULL DEFAULT 0,
    outcome         TEXT,
    UNIQUE(game_id, signal_type),
    FOREIGN KEY (game_id) REFERENCES games(game_id),
    FOREIGN KEY (signal_id) REFERENCES signals(id)
);

-- Bullpen usage per team per date, from MLB's official free Stats API.
-- Feeds the bullpen-fatigue signal: heavy bullpen usage yesterday -> more
-- likely to lose today, per the trend you flagged.
CREATE TABLE IF NOT EXISTS bullpen_usage (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    team                TEXT NOT NULL,
    game_date           TEXT NOT NULL,
    relief_innings      REAL NOT NULL,
    relief_pitcher_count INTEGER NOT NULL,
    captured_at         TEXT NOT NULL,
    UNIQUE(team, game_date)
);

CREATE INDEX IF NOT EXISTS idx_odds_game ON odds_snapshots(game_id);
CREATE INDEX IF NOT EXISTS idx_signals_game ON signals(game_id);
CREATE INDEX IF NOT EXISTS idx_games_sport_time ON games(sport, commence_time);
CREATE INDEX IF NOT EXISTS idx_recs_graded ON recommendations(graded);
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
