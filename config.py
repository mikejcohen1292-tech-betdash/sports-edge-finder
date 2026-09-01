"""
Central config for the Sports Edge Finder pipeline.
Edit SPORTS / API keys here. Nothing else should need editing to get started.
"""

import os

# ---- API keys (set as environment variables, never hardcode) ----
ODDSPAPI_KEY = os.environ.get("ODDSPAPI_KEY", "")  # legacy, no longer used
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")   # free key from https://the-odds-api.com

# ---- Sports in scope ----
SPORTS = {
    "mlb": {
        "espn_sport": "baseball",
        "espn_league": "mlb",
        "theoddsapi_key": "baseball_mlb",
        "season_start_month": 3,
    },
    "wnba": {
        "espn_sport": "basketball",
        "espn_league": "wnba",
        "theoddsapi_key": "basketball_wnba",
        "season_start_month": 5,
    },
    "nfl": {
        "espn_sport": "football",
        "espn_league": "nfl",
        "theoddsapi_key": "americanfootball_nfl",
        "season_start_month": 9,
    },
    "ncaaf": {
        "espn_sport": "football",
        "espn_league": "college-football",
        "theoddsapi_key": "americanfootball_ncaaf",
        "season_start_month": 8,
    },
}

# ---- Storage ----
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "edge_finder.db")

# ---- Signal thresholds ----
STEAM_MOVE_SPREAD_POINTS = 1.0
STEAM_WINDOW_MINUTES = 90
STEAM_MOVE_ML_CENTS = 20
STEAM_MOVE_ML_PROB = 0.05
MIN_SIGNAL_STRENGTH_TO_RECOMMEND = 0.6

# The Odds API returns real, well-known sportsbooks (draftkings, fanduel,
# betmgm, etc.) — no more sorting through hundreds of obscure/broken ones.
PREFERRED_BOOK = "draftkings"

# ---- Bullpen fatigue (MLB only) ----
BULLPEN_HEAVY_INNINGS_THRESHOLD = 4.0

# ---- Odds API request budgeting ----
# The Odds API free tier: 500 credits/month. Requesting just the moneyline
# market for one region costs 1 credit per call, and each call returns the
# ENTIRE day's games for that sport in one shot — so this budget is generous.
MAX_THEODDSAPI_CALLS_PER_RUN = 2
