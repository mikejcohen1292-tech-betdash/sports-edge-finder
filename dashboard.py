"""
Generates a single self-contained HTML dashboard from whatever is in the
database right now. No server needed — open the file in a browser.

Usage:
    python dashboard.py
    open data/dashboard.html
"""

import json
from datetime import datetime, timezone

from db import get_connection, init_db
from backtest import run_backtest

TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Sports Edge Finder — Dashboard</title>
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
<div class="subtitle">Generated {generated_at} · {n_games} games tracked · {n_signals} signals computed</div>

<div class="card highlight" style="margin-bottom:20px;">
  <h2>Today's Recommended Plays</h2>
  {todays_plays_html}
</div>

<div class="card" style="margin-bottom:20px;">
  <h2>Top 5 Public Consensus Plays Per Sport</h2>
  <div class="subtitle" style="margin-bottom:12px;">Real DraftKings sportsbook betting data — where the public's money is heaviest today.</div>
  {public_consensus_html}
</div>

<div class="card" style="margin-bottom:32px;">
  <h2>Recommendation Track Record</h2>
  <div class="subtitle" style="margin-bottom:12px;">Not the full backtest below — this is specifically what the
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
        return '<div class="empty">No graded signals yet — run the pipeline for a while first.</div>'
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
        return "—"
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
    today = datetime.now(timezone.utc).date().isoformat()
    rows = conn.execute(
        """SELECT rec.*, g.home_team, g.away_team
           FROM recommendations rec
           JOIN games g ON g.game_id = rec.game_id
           WHERE date(rec.recommended_at) = ?
           ORDER BY rec.strength DESC""",
        (today,),
    ).fetchall()
    if not rows:
        return ('<div class="empty">No games clear the bar today — that\'s a valid, correct '
                'result on plenty of days, not a broken system.</div>')
    trs = ""
    for r in rows:
        badge_cls = "badge-home" if r["favored_side"] == "home" else "badge-away"
        matchup = f"{r['away_team']} @ {r['home_team']}"
        odds_str = _american_odds_str(r["odds_price"]) if "odds_price" in r.keys() else "—"
        units = _suggest_units(r["strength"])
        trs += (f"<tr><td>{r['sport']}</td><td>{matchup}</td><td>{r['signal_type']}</td>"
                f"<td><span class='badge {badge_cls}'>{r['favored_side'].upper()}</span></td>"
                f"<td>{odds_str}</td><td>{units}u</td><td>{r['strength']:.2f}</td></tr>")
    return (f"<table><thead><tr><th>Sport</th><th>Matchup</th><th>Signal</th><th>Take</th>"
            f"<th>Odds</th><th>Units</th><th>Strength</th></tr></thead><tbody>{trs}</tbody></table>"
            f"<div class='subtitle' style='margin-top:10px;'>Odds shown are the actual moneyline price — "
            f"a heavy favorite and a live underdog are not the same bet even at equal strength. Units are a "
            f"standard confidence-weighted sizing convention (1-3u), not a proven-optimal size. Check the "
            f"track record below before sizing anything for real.</div>")


def build_public_consensus_html(conn):
    """Top 5 games per sport with the strongest public lean today, by REAL
    DraftKings sportsbook handle% (money wagered) — confirmed real data from
    VSiN, not a proxy. Falls back to bet% only if handle% isn't available."""
    today = datetime.now(timezone.utc).date().isoformat()
    rows = conn.execute(
        """SELECT pb.game_id, pb.side, pb.bet_pct, pb.handle_pct, pb.source,
                  g.sport, g.home_team,
