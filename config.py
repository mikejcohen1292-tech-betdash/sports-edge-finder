"""
Central config for the Sports Edge Finder pipeline.
Edit SPORTS / API keys here. Nothing else should need editing to get started.
"""

import os

# ---- API keys (set as environment variables, never hardcode) ----
ODDSPAPI_KEY = os.environ.get("ODDSPAPI_KEY", "")  # free key from https://oddspapi.io

# ---- Sports in scope ----
# ESPN slugs (for results) and OddsPapi sport identifiers (for odds) side by side.
SPORTS = {
    "mlb": {
        "espn_sport": "baseball",
        "espn_league": "mlb",
        "oddspapi_sport": "baseball",
        "oddspapi_league": "mlb",
        "season_start_month": 3,  # rough backfill anchor
    },
    "wnba": {
        "espn_sport": "basketball",
        "espn_league": "wnba",
        "oddspapi_sport": "basketball",
        "oddspapi_league": "wnba",
        "season_start_month": 5,
    },
    "nfl": {
        "espn_sport": "football",
        "espn_league": "nfl",
        "oddspapi_sport": "football",
        "oddspapi_league": "nfl",
        "season_start_month": 9,
    },
    "ncaaf": {
        "espn_sport": "football",
        "espn_league": "college-football",
        "oddspapi_sport": "football",
        "oddspapi_league": "ncaaf",
        "season_start_month": 8,
    },
}

# ---- Storage ----
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "edge_finder.db")

# ---- Signal thresholds (starting points — recalibrate once backtest.py has real data) ----
STEAM_MOVE_SPREAD_POINTS = 1.0     # spread move >= this within STEAM_WINDOW_MINUTES = steam
STEAM_WINDOW_MINUTES = 90
STEAM_MOVE_ML_CENTS = 20           # moneyline move >= this (American odds) within window
MIN_SIGNAL_STRENGTH_TO_RECOMMEND = 0.6  # 0-1 scale, tune after backtest results come in

# ---- Odds API request budgeting ----
# OddsPapi free tier is capped around 250 req/month. Spend it deliberately:
# one snapshot pull per sport per day by default, not continuous polling.
MAX_ODDSPAPI_CALLS_PER_RUN = 40
