"""
Pulls REAL DraftKings sportsbook public betting data from VSiN
(data.vsin.com) - actual money wagered (Handle %) and actual ticket count
(Bet %) on every game, not a pick'em-contest proxy.

Usage:
    python ingest_public_betting_vsin.py --sport mlb
"""

import argparse
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

from config import SPORTS
from db import get_connection, init_db

VSIN_SPORT_PARAM = {
    "mlb": "MLB",
    "nfl": "NFL",
    "ncaaf": "CFB",
}
VSIN_DIRECT_URL = {
    "wnba": "https://data.vsin.com/wnba/betting-splits/",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; sports-edge-finder personal research bot)"
}


def fetch_splits_page(sport_key):
    if sport_key in VSIN_DIRECT_URL:
        url = VSIN_DIRECT_URL[sport_key]
    elif sport_key in VSIN_SPORT_PARAM:
        url = f"https://data.vsin.com/betting-splits/?source=DK&sport={VSIN_SPORT_PARAM[sport_key]}"
    else:
        return None
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.text


def parse_splits_rows(html):
    soup = BeautifulSoup(html, "html.parser")
    all_trs = soup.find_all("tr")
    cell_counts = {}
    for tr in all_trs:
        n = len(tr.find_all("td"))
        cell_counts[n] = cell_counts.get(n, 0) + 1
    print(f"  [debug] {len(all_trs)} <tr> rows found, cell-count distribution: {cell_counts}")
    if len(html) < 2000:
        print(f"  [debug] response looks suspiciously short ({len(html)} chars) - "
              f"possible block page. First 300 chars: {html[:300]}")

    team_rows = []
    for tr in all_trs:
        cells = tr.find_all("td")
        if len(cells) != 11:
            continue
        texts = [c.get_text(strip=True) for c in cells]
        team_name = texts[1]
        if not team_name:
            continue
        team_rows.append({
            "team": team_name,
            "spread_handle_pct": texts[3],
            "spread_bet_pct": texts[4],
            "ml_handle_pct": texts[9],
            "ml_bet_pct": texts[10],
        })

    games = []
    for i in range(0, len(team_rows) - 1, 2):
        a, b = team_rows[i], team_rows[i + 1]
        games.append((a, b))
    return games


def _pct_to_float(s):
    try:
        return float(s.replace("%", "").strip())
    except (ValueError, AttributeError):
        return None


def match_game(sport_key, team_a, team_b, conn):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    candidates = conn.execute(
        """SELECT g.game_id, g.home_team, g.away_team, g.commence_time
           FROM games g
           LEFT JOIN results r ON r.game_id = g.game_id
           WHERE g.sport = ? AND g.commence_time >= ?
             AND (r.completed IS NULL OR r.completed = 0)
           ORDER BY g.commence_time ASC""",
        (sport_key, cutoff),
    ).fetchall()

    def names_match(a, b):
        a, b = a.lower(), b.lower()
        return a in b or b in a

    for g in candidates:
        if ((names_match(team_a, g["home_team"]) and names_match(team_b, g["away_team"])) or
                (names_match(team_a, g["away_team"]) and names_match(team_b, g["home_team"]))):
            home_is_a = names_match(team_a, g["home_team"])
            return g["game_id"], home_is_a
    return None, None


def store_public_betting(game_id, home_bet_pct, home_handle_pct, away_bet_pct, away_handle_pct):
    conn = get_connection()
    captured_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO public_betting (game_id, captured_at, side, bet_pct, handle_pct, source)
           VALUES (?, ?, 'home', ?, ?, 'vsin_draftkings')""",
        (game_id, captured_at, home_bet_pct, home_handle_pct),
    )
    conn.execute(
        """INSERT INTO public_betting (game_id, captured_at, side, bet_pct, handle_pct, source)
           VALUES (?, ?, 'away', ?, ?, 'vsin_draftkings')""",
        (game_id, captured_at, away_bet_pct, away_handle_pct),
    )
    conn.commit()
    conn.close()


def run(sport_key):
    html = fetch_splits_page(sport_key)
    if html is None:
        print(f"No VSiN splits page configured for {sport_key}, skipping.")
        return

    games = parse_splits_rows(html)
    conn = get_connection()

    # MLB's spread (run line) is almost always fixed at +/-1.5 — the point
    # doesn't carry the same "who covers" meaning it does in NFL/NCAAF/WNBA,
    # so moneyline is the more meaningful public split for MLB specifically.
    # Every other sport uses the spread split instead.
    bet_key, handle_key = ("ml_bet_pct", "ml_handle_pct") if sport_key == "mlb" \
        else ("spread_bet_pct", "spread_handle_pct")

    matched = 0
    skipped_bad_pair = 0
    for team_a, team_b in games:
        if team_a["team"].strip().lower() == team_b["team"].strip().lower():
            skipped_bad_pair += 1
            continue

        game_id, home_is_a = match_game(sport_key, team_a["team"], team_b["team"], conn)
        if game_id is None:
            continue

        a_bet, a_handle = _pct_to_float(team_a[bet_key]), _pct_to_float(team_a[handle_key])
        b_bet, b_handle = _pct_to_float(team_b[bet_key]), _pct_to_float(team_b[handle_key])
        if a_bet is None or b_bet is None:
            continue

        if not (90 <= (a_bet + b_bet) <= 110):
            skipped_bad_pair += 1
            continue

        if a_bet in (0.0, 100.0) or b_bet in (0.0, 100.0):
            skipped_bad_pair += 1
            continue

        home_bet, home_handle = (a_bet, a_handle) if home_is_a else (b_bet, b_handle)
        away_bet, away_handle = (b_bet, b_handle) if home_is_a else (a_bet, a_handle)
        store_public_betting(game_id, home_bet, home_handle, away_bet, away_handle)
        matched += 1

    conn.close()
    if skipped_bad_pair:
        print(f"  [warning] skipped {skipped_bad_pair} row-pair(s) that looked misaligned (self-matched team or bad percentage sum).")
    print(f"{sport_key}: {len(games)} games parsed, {matched} matched to known games "
          f"(real DraftKings handle%/bet%, not a proxy).")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport", required=True, choices=SPORTS.keys())
    args = parser.parse_args()

    init_db()
    run(args.sport)


if __name__ == "__main__":
    main()
