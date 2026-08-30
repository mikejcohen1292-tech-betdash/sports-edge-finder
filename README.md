# Sports Edge Finder

A pipeline to test whether line-movement patterns (reverse line movement,
steam moves) actually predict outcomes in MLB, WNBA, NFL, and NCAAF — with
real backtested numbers, not gut feel.

## What's real vs. what needs your input

This was built and **tested with synthetic data** in a sandboxed environment
that can't reach sports/odds APIs directly. Every script runs and the logic
is proven correct — but it needs to run somewhere with open internet access
(your laptop, a $5/mo VPS, a Raspberry Pi) and your own free API key to pull
real data.

## Setup (10 minutes)

```bash
pip install requests
export ODDSPAPI_KEY=your_free_key_here   # sign up free at https://oddspapi.io
```

Get a free key from **oddspapi.io** — no credit card required, 250
requests/month, includes free historical odds. This is the one paid-adjacent
step and it's still $0.

## Phase 1 — Backfill what you can, right now

Results (scores/outcomes) are free and **unlimited** via ESPN's public API,
so backfill full seasons immediately:

```bash
python ingest_results_espn.py --sport mlb --start 2025-03-20 --end 2025-11-01
python ingest_results_espn.py --sport wnba --start 2025-05-01 --end 2025-10-01
python ingest_results_espn.py --sport mlb --start 2026-03-15   # this season, to date
python ingest_results_espn.py --sport wnba --start 2026-05-01
```

NFL and NCAAF backfill becomes useful once games start (~Sept). Odds
history is the harder part — OddsPapi's free tier gives you *some* free
historical odds, but coverage depends on their archive start date, not on
your needs:

```bash
python ingest_odds_oddspapi.py --sport mlb --backfill-days 1   # pulls whatever's archived
```

**The honest expectation:** free historical *odds* (not scores) will be
thin. Don't wait for a perfect backfill — the real dataset builds from here
forward. Every day you run this, your archive of games with graded signals
grows, and in 2-3 months you'll have something no free source gives you
out of the box.

## Phase 2 — Daily capture going forward (the important part)

Set up a cron job (or Task Scheduler on Windows) to run each morning:

```bash
# crontab -e
0 9 * * * cd /path/to/sports_edge_finder && python ingest_odds_oddspapi.py --sport mlb
0 9 * * * cd /path/to/sports_edge_finder && python ingest_odds_oddspapi.py --sport wnba
0 20 * * * cd /path/to/sports_edge_finder && python ingest_results_espn.py --sport mlb --today
0 20 * * * cd /path/to/sports_edge_finder && python ingest_results_espn.py --sport wnba --today
```

Add nfl/ncaaf lines once their seasons start. **Don't poll more than a
few times a day** — the free OddsPapi tier is capped around 250
requests/month, and `MAX_ODDSPAPI_CALLS_PER_RUN` in `config.py` protects
you from burning it in one run, but not from running it too often.

## Phase 3 — Compute signals

After ingesting, score every game's line movement:

```bash
python signals.py           # all sports
python signals.py mlb       # just one
```

This detects **steam moves** (fast, large line movement — works without any
bet% data) and **reverse line movement** (only fires if you later populate
the `public_betting` table — see below).

## Phase 4 — Backtest: does it actually work?

```bash
python backtest.py                    # all sports
python backtest.py --sport mlb
```

This is the answer to your original question. It reports win% and ROI per
signal type, with a **95% confidence interval** and explicit small-sample
warnings — because a 65% win rate on 15 games is noise, and the same rate
on 300 games is real. Break-even at standard -110 juice is 52.4%; that's
your bar.

## Phase 5 — Morning recommendations

Once backtest.py shows a signal type with a real edge at meaningful sample
size, tune `MIN_SIGNAL_STRENGTH_TO_RECOMMEND` in `config.py` to match, then:

```bash
python recommend.py               # today's flagged games, all sports
python recommend.py --sport nfl
```

It will correctly return **nothing** on days where no game clears the bar —
that's the system working, not broken.

## Dashboard

```bash
python dashboard.py
```

Opens as a plain HTML file (`data/dashboard.html`) — win% by signal type,
game counts by sport, signal volume over time. No server needed, just open
it in a browser. Regenerate any time after new data comes in.

## About the bet%/handle% data (your original signal)

Free, reliable sources for public bet%/handle% (the exact data point your
Twitter account posts) essentially don't exist — it's the one piece of this
that's genuinely hard to get without paying a provider. The `public_betting`
table in the schema is ready for it whenever you want to add a source
(manual daily entry, a paid feed, or screen-scraping that specific account's
posts yourself, which is on you since automating around a platform's access
controls isn't something I can build). Until then, `steam_spread` — pure
price-action movement — is a legitimate, well-studied proxy signal that
needs no bet% data at all, and it's what the backtest will validate first.

## Files

| File | Purpose |
|---|---|
| `config.py` | Sports, thresholds, API keys — the only file you'll routinely edit |
| `db.py` | SQLite schema (games, odds_snapshots, results, signals, public_betting) |
| `ingest_results_espn.py` | Free, unlimited historical + daily score backfill |
| `ingest_odds_oddspapi.py` | Odds snapshots — daily + limited free historical |
| `signals.py` | Steam move + RLM detection |
| `backtest.py` | Win%/ROI by signal type, with confidence intervals |
| `recommend.py` | Morning ranked play list, gated by your validated thresholds |
| `dashboard.py` | Self-contained HTML visualization |
