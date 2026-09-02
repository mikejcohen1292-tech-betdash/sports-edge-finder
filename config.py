"""
Central config for the Sports Edge Finder pipeline.
Edit SPORTS / API keys here. Nothing else should need editing to get started.
"""

import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

EASTERN_TZ = ZoneInfo("America/New_York")


def eastern_today():
    return datetime.now(EASTERN_TZ).date().isoformat()


def to_eastern_date(iso_utc_str):
    if not iso_utc_str:
        return None
    s = iso_utc_str.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(EASTERN_TZ).date().isoformat()

ODDSPAPI_KEY = os.environ.get("ODDSPAPI_KEY", "")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")

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

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "edge_finder.db")

STEAM_MOVE_SPREAD_POINTS = 1.0
STEAM_WINDOW_MINUTES = 90
STEAM_MOVE_ML_CENTS = 20
MIN_SIGNAL_STRENGTH_TO_RECOMMEND = 0.6

STEAM_MOVE_ML_LOGIT = 0.20

PREFERRED_BOOK = "draftkings"

BULLPEN_LOOKBACK_DAYS = 3
BULLPEN_CUMULATIVE_HEAVY_THRESHOLD = 9.0

MAX_THEODDSAPI_CALLS_PER_RUN = 2
