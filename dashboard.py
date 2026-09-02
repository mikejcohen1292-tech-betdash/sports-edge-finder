"""
Generates a single self-contained HTML dashboard from whatever is in the
database right now. No server needed - open the file in a browser.

Usage:
    python dashboard.py
    open data/dashboard.html
"""

import json
from datetime import datetime, timezone

from db import get_connection, init_db
from backtest import run_backtest
from config import eastern_today, to_eastern_date

TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Sports Edge Finder - Dashboard</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  body {{ font-family: -apple-system, Segoe UI, sans-serif; background: #0f1117; color: #e6e8eb; margin: 0; padding: 32px; }}
  h1 {{ font-size: 22px; margin-bottom: 4px; }}
  h2 {{ font-size: 16px; margin: 0 0 14px 0; }}
  .subtitle {{ color: #9099a8; margin-bottom: 28px; font-size: 14px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 20px; margin-bottom: 32px; }}
  .card {{ background: #171a22; border: 1px solid #262b36; border-radius: 12px; padding: 20px; }}
  .card h3 {{ margin-top: 0; font-size: 14px; color: #9099a8; text-transform: uppercase; letter-spacing: 0.04em; }}
  .highlight {{ border: 1px solid #3b4b6b; background: #131a2a; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th, td {{ text-align: left; padding: 8px 6px; border-bottom: 1px solid #262b36; }}
  th {{ color: #9099a8; font-weight: 500; }}
  .win {{ color: #4ade80; }}
  .loss {{ color: #f87171; }}
  .push {{ color: #9099a8; }}
  .small-sample {{ color: #fbbf24; font-size: 11px; }}
  .empty {{ color: #6b7280; font-style: italic; padding: 20px 0; }}
  canvas {{ max-height: 280px; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 20px; font-size: 11px; font-weight: 600; }}
  .badge-home {{ background: #1e3a5f; color: #93c5fd; }}
  .badge-away {{ background: #4a1d3d; color: #f9a8d4; }}
</style>
</head>
<body>
<h1>Sports Edge Finder</h1>
<div class="subtitle">Generated {generated_at} - {n_games} games tracked - {n_signals} signals computed</div>

<div class="card highlight" style="margin-bottom:20px;">
  <h2>Today's Recommended Plays</h2>
  {todays_plays_html}
</div>

<div class="card" style="margin-bottom:20px;">
  <h2>Top 5 Public Consensus Plays Per Sport</h2>
  <div class="subtitle" style="margin-bottom:12px;">Real DraftKings sportsbook betting data - where the public's money is heaviest today.</div>
  {public_consensus_html}
</div>

<div class="card" style="margin-bottom:32px;">
  <h2>Recommendation Track Record</h2>
  <div class="subtitle" style="margin-bottom:12px;">Not the full backtest below - this is specifically what the
  system actually told you to bet on past mornings, graded against what happened.</div>
  {track_record_html}
</div>

<div class="grid">
  <div class="card">
    <h3>Signal performance (ATS, vs -110 breakeven of 52.4%)</h3>
    {backtest_table}
  </div>
  <div class="card">
    <h3>Win % by signal type</h3>
    <canvas id="winPctChart"></canvas>
  </div>
  <div class="card">
    <h3>Games tracked per sport</h3>
    <canvas id="sportCountChart"></canvas>
  </div>
  <div class="card">
    <h3>Signal volume over time</h3>
    <canvas id="signalTimelineChart"></canvas>
  </div>
</div>

<script>
const backtestData = {backtest_json};
const sportCounts = {sport_counts_json};
const timeline = {timeline_json};

new Chart(document.getElementById('winPctChart'), {{
  type: 'bar',
  data: {{
    labels: backtestData.map(r => r.sport + ' / ' + r.signal_type),
    datasets: [{{
      label: 'Win %',
      data: backtestData.map(r => r.win_pct),
      backgroundColor: backtestData.map(r => r.win_pct >= 52.4 ? '#4ade80' : '#f87171')
    }}]
  }},
  options: {{ plugins: {{ legend: {{ display: false }} }}, scales: {{ y: {{ min: 0, max: 100 }} }} }}
}});

new Chart(document.getElementById('sportCountChart'), {{
  type: 'doughnut',
  data: {{
    labels: Object.keys(sportCounts),
    datasets: [{{ data: Object.values(sportCounts), backgroundColor: ['#60a5fa','#a78bfa','#fb923c','#4ade80'] }}]
  }}
}});

new Chart(document.getElementById('signalTimelineChart'), {{
  type: 'line',
  data: {{
    labels: timeline.map(t => t.date),
    datasets: [{{ label: 'Signals computed', data: timeline.map(t => t.count), borderColor: '#60a5fa', tension: 0.3 }}]
  }}
}});
</script>
</body>
</html>
"""


def build_backtest_table_html(rows):
    if not rows:
        return '<div class="empty">No graded signals yet - run the pipeline for a while first.</div>'
    trs = ""
    for r in rows:
        cls = "win" if r["win_pct"] >= 52.4 else "loss"
        note = '<div class="small-sample">small sample</div>' if r["n"] < 30 else ""
        trs += (f"<tr><td>{r['sport']}</td><td>{r['signal_type']}</td><td>{r['n']}</td>"
                f"<td class='{cls}'>{r['win_pct']}%</td><td>{r['roi_pct']}%{note}</td></tr>")
    return (f"<table><thead><tr><th>Sport</th><th>Signal</th><th>N</th><th>Win%</th><th>ROI%</th>"
            f"</tr></thead><tbody>{trs}</tbody></table>")


def _american_odds_str(decimal_price):
    if not decimal_price:
        return "N/A"
    if decimal_price >= 2.0:
        american = (decimal_price - 1) * 100
    else:
        american = -100 / (decimal_price - 1)
    return f"{american:+.0f}"


def _suggest_units(strength):
    if strength >= 0.9:
        return 3
    elif strength >= 0.75:
        return 2
    return 1


def build_todays_plays_html(conn):
    today = eastern_today()
    rows = conn.execute(
        """SELECT rec.*, g.home_team, g.away_team
           FROM recommendations rec
           JOIN games g ON g.game_id = rec.game_id
           ORDER BY rec.strength DESC"""
    ).fetchall()
    rows = [r for r in rows if to_eastern_date(r["recommended_at"]) == today]
    if not rows:
        return ('<div class="empty">No games clear the bar today - that is a valid, correct '
                'result on plenty of days, not a broken system.</div>')
    trs = ""
    for r in rows:
        badge_cls = "badge-home" if r["favored_side"] == "home" else "badge-away"
        matchup = f"{r['away_team']} @ {r['home_team']}"
        odds_str = _american_odds_str(r["odds_price"]) if "odds_price" in r.keys() else "N/A"
        units = _suggest_units(r["strength"])
        trs += (f"<tr><td>{r['sport']}</td><td>{matchup}</td><td>{r['signal_type']}</td>"
                f"<td><span class='badge {badge_cls}'>{r['favored_side'].upper()}</span></td>"
                f"<td>{odds_str}</td><td>{units}u</td><td>{r['strength']:.2f}</td></tr>")
    return (f"<table><thead><tr><th>Sport</th><th>Matchup</th><th>Signal</th><th>Take</th>"
            f"<th>Odds</th><th>Units</th><th>Strength</th></tr></thead><tbody>{trs}</tbody></table>"
            f"<div class='subtitle' style='margin-top:10px;'>Odds shown are the actual moneyline price - "
            f"a heavy favorite and a live underdog are not the same bet even at equal strength. Units are a "
            f"standard confidence-weighted sizing convention (1-3u), not a proven-optimal size. Check the "
            f"track record below before sizing anything for real.</div>")


def build_public_consensus_html(conn):
    today = eastern_today()
    rows = conn.execute(
        """SELECT pb.game_id, pb.side, pb.bet_pct, pb.handle_pct, pb.source,
                  g.sport, g.home_team, g.away_team, g.commence_time
           FROM public_betting pb
           JOIN games g ON g.game_id = pb.game_id
           ORDER BY pb.captured_at DESC"""
    ).fetchall()
    rows = [r for r in rows if to_eastern_date(r["commence_time"]) == today]

    if not rows:
        return ('<div class="empty">No public betting data for today\'s games yet - '
                'this updates once the daily pipeline runs.</div>')

    latest = {}
    for r in rows:
        key = (r["game_id"], r["side"])
        if key not in latest:
            latest[key] = r

    def rank_value(r):
        return r["handle_pct"] if r["handle_pct"] is not None else r["bet_pct"]

    by_game = {}
    for (game_id, side), r in latest.items():
        if game_id not in by_game or rank_value(r) > rank_value(by_game[game_id]):
            by_game[game_id] = r

    by_sport = {}
    for r in by_game.values():
        by_sport.setdefault(r["sport"], []).append(r)

    html = ""
    for sport in sorted(by_sport.keys()):
        top5 = sorted(by_sport[sport], key=rank_value, reverse=True)[:5]
        html += f"<h4 style='margin:14px 0 6px 0;color:#9099a8;font-size:12px;text-transform:uppercase;'>{sport}</h4>"
        html += "<table><thead><tr><th>Matchup</th><th>Public side</th><th>Handle%</th><th>Bet%</th></tr></thead><tbody>"
        for r in top5:
            matchup = f"{r['away_team']} @ {r['home_team']}"
            side_team = r["home_team"] if r["side"] == "home" else r["away_team"]
            handle_str = f"{r['handle_pct']:.0f}%" if r["handle_pct"] is not None else "N/A"
            bet_str = f"{r['bet_pct']:.0f}%" if r["bet_pct"] is not None else "N/A"
            html += f"<tr><td>{matchup}</td><td>{side_team}</td><td>{handle_str}</td><td>{bet_str}</td></tr>"
        html += "</tbody></table>"

    has_real = any(r["source"] == "vsin_draftkings" for r in by_game.values())
    if has_real:
        html += ("<div class='subtitle' style='margin-top:10px;'>Source: VSiN - real DraftKings "
                 "sportsbook data. Handle% = actual money wagered, Bet% = ticket count. Not a proxy.</div>")
    else:
        html += ("<div class='subtitle' style='margin-top:10px;'>Source: Covers.com free pick'em "
                 "consensus - real people's picks, NOT literal sportsbook betting handle.</div>")
    return html


def build_track_record_html(conn):
    rows = conn.execute("SELECT * FROM recommendations WHERE graded = 1").fetchall()
    if not rows:
        return '<div class="empty">No graded recommendations yet - check back once today\'s (or past) plays have finished.</div>'

    wins = sum(1 for r in rows if r["outcome"] == "win")
    losses = sum(1 for r in rows if r["outcome"] == "loss")
    pushes = sum(1 for r in rows if r["outcome"] == "push")
    n = wins + losses
    win_pct = (wins / n * 100) if n else 0.0
    cls = "win" if win_pct >= 52.4 else "loss"
    note = '<div class="small-sample">Small sample - treat as informational, not conclusive.</div>' if n < 30 else ""

    recent = sorted(rows, key=lambda r: r["recommended_at"], reverse=True)[:10]
    recent_trs = ""
    for r in recent:
        oc = r["outcome"] or "pending"
        odds_str = _american_odds_str(r["odds_price"]) if "odds_price" in r.keys() else "N/A"
        recent_trs += (f"<tr><td>{r['recommended_at'][:10]}</td><td>{r['sport']}</td>"
                        f"<td>{r['signal_type']}</td><td>{odds_str}</td><td class='{oc}'>{oc}</td></tr>")

    return (f"<div style='font-size:28px;font-weight:700;' class='{cls}'>{win_pct:.1f}% "
            f"<span style='font-size:14px;color:#9099a8;font-weight:400;'>({wins}-{losses}-{pushes} on {n} decided plays)</span></div>"
            f"{note}<div style='margin-top:16px;'><table><thead><tr><th>Date</th><th>Sport</th>"
            f"<th>Signal</th><th>Odds</th><th>Result</th></tr></thead><tbody>{recent_trs}</tbody></table></div>")


def generate():
    conn = get_connection()
    n_games = conn.execute("SELECT COUNT(*) c FROM games").fetchone()["c"]
    n_signals = conn.execute("SELECT COUNT(*) c FROM signals").fetchone()["c"]

    sport_counts = {}
    for row in conn.execute("SELECT sport, COUNT(*) c FROM games GROUP BY sport"):
        sport_counts[row["sport"]] = row["c"]

    timeline = []
    for row in conn.execute(
        "SELECT date(computed_at) d, COUNT(*) c FROM signals GROUP BY date(computed_at) ORDER BY d"
    ):
        timeline.append({"date": row["d"], "count": row["c"]})

    todays_plays_html = build_todays_plays_html(conn)
    public_consensus_html = build_public_consensus_html(conn)
    track_record_html = build_track_record_html(conn)

    conn.close()

    backtest_rows = run_backtest()

    html = TEMPLATE.format(
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        n_games=n_games,
        n_signals=n_signals,
        todays_plays_html=todays_plays_html,
        public_consensus_html=public_consensus_html,
        track_record_html=track_record_html,
        backtest_table=build_backtest_table_html(backtest_rows),
        backtest_json=json.dumps(backtest_rows),
        sport_counts_json=json.dumps(sport_counts),
        timeline_json=json.dumps(timeline),
    )

    out_path = "data/dashboard.html"
    with open(out_path, "w") as f:
        f.write(html)
    print(f"Dashboard written to {out_path}")
    return out_path


if __name__ == "__main__":
    init_db()
    generate()
