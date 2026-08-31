"""
Central config for the Sports Edge Finder pipeline.
Edit SPORTS / API keys here. Nothing else should need editing to get started.
"""

import os

ODDSPAPI_KEY = os.environ.get("ODDSPAPI_KEY", "")

SPORTS = {
    "mlb": {
        "espn_sport": "baseball",
        "espn_league": "mlb",
        "oddspapi_sport": "baseball",
        "oddspapi_league": "mlb",
        "season_start_month": 3,
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
        "oddspapi_sport": "american-football",
        "oddspapi_league": "nfl",
        "season_start_month": 9,
    },
    "ncaaf": {
        "espn_sport": "football",
        "espn_league": "college-football",
        "oddspapi_sport": "american-football",
        "oddspapi_league": "ncaaf",
        "season_start_month": 8,
    },
}

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "edge_finder.db")

STEAM_MOVE_SPREAD_POINTS = 1.0
STEAM_WINDOW_MINUTES = 90
STEAM_MOVE_ML_CENTS = 20
STEAM_MOVE_ML_PROB = 0.05
MIN_SIGNAL_STRENGTH_TO_RECOMMEND = 0.6

# ---- Bullpen fatigue (MLB only) ----
BULLPEN_HEAVY_INNINGS_THRESHOLD = 4.0

# ---- Odds API request budgeting ----
MAX_ODDSPAPI_CALLS_PER_RUN = 2
