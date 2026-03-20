#!/usr/bin/env python3
"""
Warm predictions_date_cache for today .. today+N days.

Usage (from project root):
  pip install -r requirements.txt
  export DATABASE_URL="postgresql://..."
  python scripts/warm_predictions_cache.py

Env:
  WARM_CACHE_DAYS_AHEAD — default 14 (matches typical “next two weeks” warm window).
"""
import os
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

def main() -> int:
    from src.predictions_db import get_database_url, is_configured, warm_date_range

    if not get_database_url():
        print("ERROR: Set DATABASE_URL (or SUPABASE_DB_URL) in the environment.", file=sys.stderr)
        return 1
    if not is_configured():
        print("ERROR: Install psycopg: pip install 'psycopg[binary]'", file=sys.stderr)
        return 1

    days = int(os.environ.get("WARM_CACHE_DAYS_AHEAD", "14"))
    today = date.today()
    end = today + timedelta(days=days)
    print(f"Warming predictions cache: {today.isoformat()} .. {end.isoformat()} ({days} days ahead)")
    stats = warm_date_range(today, end)
    print(f"OK: {stats['ok']}  Failed: {stats['failed']}")
    for err in stats.get("errors", []):
        print(f"  {err['date']}: {err['error']}", file=sys.stderr)
    return 0 if stats["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
