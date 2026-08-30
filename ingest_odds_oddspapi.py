"""
Pulls odds (moneyline + spread) from OddsPapi and stores snapshots.

IMPORTANT — free tier reality: OddsPapi's free key is capped around 250
requests/month. That's not enough to poll continuously across 4 sports, so
this script defaults to ONE efficient snapshot per sport per run. Point cron
at this a few times a day (e.g. morning open, midday, close) rather than
polling every few minutes, or you'll burn the month's quota in a week.

Usage:
    python ingest_odds_oddspapi.py --sport mlb                 # today's live snapshot
    python ingest_odds_oddspapi.py --sport mlb --backfill-days 14  # free historical, if available

Set your key first:
    export ODDSPAPI_KEY=your_free_key_here
"""

import argparse
import time
from datetime import datetime, timedelta, timezone

import requests

from config import SPORTS, ODDSPAPI_KEY, MAX_ODDSPAPI_CALLS_PER_RUN
from db import get_connection, init_db

BASE = "https://api.oddspapi.io/v4"

# Hardcoded from OddsPapi's own docs — skips a live /sports lookup call every
# run, which matters a lot on a 250-requests/month free tier.
SPORT_ID_MAP = {
    "baseball": 13,
    "basketball": 11,
    "american-football": 14,
}

# Which tournamentName text (case-insensitive substring) identifies each league
# in OddsPapi's fixture data. Their fixtures endpoint returns a plain tournamentName
# string per fixture, so we match on that instead of needing a separate lookup.
LEAGUE_NAME_MATCH = {
    "mlb": ["mlb", "major league baseball"],
    "wnba": ["wnba"],
    "nfl": ["nfl"],
    "ncaaf": ["ncaa", "college football", "ncaaf"],
}


def _key_param():
    if not ODDSPAPI_KEY:
        raise SystemExit("Set ODDSPAPI_KEY as an environment variable first. Get a free key at oddspapi.io")
    return {"apiKey": ODDSPAPI_KEY}


def get_sport_id(sport_slug, session):
    if sport_slug in
