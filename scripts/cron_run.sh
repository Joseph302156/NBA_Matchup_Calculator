#!/usr/bin/env bash
# Run from cron every 30 min. Uses project dir and venv.
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT"
mkdir -p logs
.venv/bin/python main.py --json >> logs/nba_picks.jsonl 2>&1
