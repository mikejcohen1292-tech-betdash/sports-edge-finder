"""
Fetches OddsPapi's own documented market catalog (GET /markets) for each
sport we track. This is the fix for a real problem: each sport has 400+
market IDs (full-game moneyline, first-5-innings moneyline, alternate lines,
player props...), and without this catalog there was no way to tell them
apart.

Run this once (safe to re-run).

Usage:
    python fetch_market_catalog.py
"""

from datetime import datetime, timezone

import requests

from config import ODDSPAPI_KEY
from db import get_connection, init_db
from ingest_odds_oddspapi import BASE, SPORT_ID_MAP, _key_param

EXCLUDE_PERIOD_SUBSTRINGS = [
    "1st5", "first5", "5inning", "half", "quarter", "period",
    "1sthalf", "2ndhalf", "1st", "2nd", "3rd", "4th", "set", "leg",
]


def fetch_markets_for_sport(sport_id, session):
    resp = session.get(
        f"{BASE}/markets",
        params={**_key_param(), "sportId": sport_id},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def store_markets(sport_id, markets):
    conn = get_connection()
    fetched_at = datetime.now(timezone.utc).isoformat()
    stored = 0
    for m in markets:
        try:
            conn.execute(
                """INSERT INTO market_catalog
                   (market_id, sport_id, market_name, market_type, handicap, period, player_prop, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(market_id) DO UPDATE SET
                       market_name=excluded.market_name,
                       market_type=excluded.market_type,
                       handicap=excluded.handicap,
                       period=excluded.period,
                       player_prop=excluded.player_prop,
                       fetched_at=excluded.fetched_at""",
                (m.get("marketId"), sport_id, m.get("marketName"), m.get("marketType"),
                 m.get("handicap"), m.get("period"), int(bool(m.get("playerProp"))), fetched_at),
            )
            stored += 1
        except Exception as e:
            print(f"  market {m.get('marketId')}: could not store ({e})")
    conn.commit()
    conn.close()
    return stored


def find_main_moneyline_market_id(sport_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM market_catalog WHERE sport_id = ? AND player_prop = 0", (sport_id,)
    ).fetchall()
    conn.close()

    candidates = []
    for r in rows:
        market_type = (r["market_type"] or "").lower()
        market_name = (r["market_name"] or "").lower()
        period = (r["period"] or "").lower()
        if market_type not in ("moneyline", "1x2", "h2h"):
            continue
        if r["handicap"] not in (0, 0.0, None):
            continue
        if any(sub in period for sub in EXCLUDE_PERIOD_SUBSTRINGS):
            continue
        if any(sub in market_name for sub in EXCLUDE_PERIOD_SUBSTRINGS):
            continue
        candidates.append(r)

    if not candidates:
        return None
    candidates.sort(key=lambda r: len(r["market_name"] or ""))
    return candidates[0]["market_id"]


def run():
    session = requests.Session()
    for sport_key, sport_id in SPORT_ID_MAP.items():
        try:
            markets = fetch_markets_for_sport(sport_id, session)
            stored = store_markets(sport_id, markets)
            print(f"{sport_key} (sportId={sport_id}): fetched {len(markets)} markets, stored {stored}.")
        except requests.RequestException as e:
            print(f"{sport_key} (sportId={sport_id}): fetch failed ({e})")
            continue

        main_ml = find_main_moneyline_market_id(sport_id)
        if main_ml:
            print(f"  -> identified main moneyline market_id = {main_ml} for {sport_key}")
        else:
            print(f"  -> [warning] could not identify a clear main moneyline market for {sport_key}")


if __name__ == "__main__":
    init_db()
    run()
