"""
Generates a single self-contained HTML dashboard from whatever is in the
database right now. No server needed — open the file in a browser.

Usage:
    python dashboard.py
    open data/dashboard.html
"""

import json
from datetime import datetime

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
  .subtitle {{ color: #9099a8; margin-bottom: 28px; font-size: 14px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 20px; margin-bottom: 32px; }}
  .card {{ background: #171a22; border: 1px solid #262b36; border-radius: 12px; padding: 20px; }}
  .card h3 {{ margin-top: 0; font-size: 14px; color: #9099a8; text-transform: uppercase; letter-spacing: 0.04em; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th, td {{ text-align: left; padding: 8px 6px; border-bottom: 1px solid #262b36; }}
  th {{ color: #9099a8; font-weight: 500; }}
  .win {{ color: #4ade80; }}
  .loss {{ color: #f87171; }}
  .small-sample {{ color: #fbbf24; font-size: 11px; }}
  .empty {{ color: #6b7280; font-style: italic; padding: 20px 0; }}
  canvas {{ max-height: 280px; }}
</style>
</head>
<body>
<h1>Sports Edge Finder</h1>
<div class="subtitle">Generated {generated_at} · {n_games} games tracked · {n_signals} signals computed</div>

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

    conn.close()

    backtest_rows = run_backtest()

    html = TEMPLATE.format(
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        n_games=n_games,
        n_signals=n_signals,
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
