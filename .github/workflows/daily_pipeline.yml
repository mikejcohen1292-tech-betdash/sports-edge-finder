name: Daily Sports Data Pipeline

on:
  schedule:
    - cron: '0 13 * * *'
  workflow_dispatch: {}

permissions:
  contents: write

jobs:
  run-pipeline:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Pull today's results (safe to re-run, skips duplicates)
        run: |
          python ingest_results_espn.py --sport mlb --today
          python ingest_results_espn.py --sport wnba --today
          python ingest_results_espn.py --sport nfl --today
          python ingest_results_espn.py --sport ncaaf --today

      - name: Pull yesterday's MLB bullpen usage (official MLB Stats API, free)
        run: python ingest_bullpen_usage.py

      - name: Pull today's odds
        env:
          ODDSPAPI_KEY: ${{ secrets.ODDSPAPI_KEY }}
        run: |
          python ingest_odds_oddspapi.py --sport mlb
          python ingest_odds_oddspapi.py --sport wnba
          python ingest_odds_oddspapi.py --sport nfl
          python ingest_odds_oddspapi.py --sport ncaaf

      - name: Compute signals
        run: python signals.py

      - name: Generate today's recommendations
        run: |
          python recommend.py --sport mlb
          python recommend.py --sport wnba
          python recommend.py --sport nfl
          python recommend.py --sport ncaaf

      - name: Grade past recommendations against finished games
        run: python grade_recommendations.py

      - name: Build dashboard
        run: |
          python dashboard.py
          mkdir -p docs
          cp data/dashboard.html docs/index.html

      - name: Save today's data + dashboard back to the repo
        run: |
          git config user.name "sports-edge-bot"
          git config user.email "actions@github.com"
          git add data docs
          git commit -m "Daily update $(date +'%Y-%m-%d')" || echo "Nothing new to commit"
          git push
