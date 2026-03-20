#!/usr/bin/env python3
"""Quick check: can this machine resolve DATABASE_URL and connect to Postgres?"""
import os
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")


def main() -> int:
    raw = (os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL") or "").strip()
    if not raw:
        print("ERROR: Set DATABASE_URL in .env", file=sys.stderr)
        return 1
    # Hide password in output
    p = urlparse(raw)
    host = p.hostname or "?"
    port = p.port or 5432
    print(f"Host: {host}")
    print(f"Port: {port}")
    print("Resolving DNS (getaddrinfo)...")
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        print(f"OK: {len(infos)} address(es), e.g. {infos[0][4]}")
    except socket.gaierror as e:
        print(f"FAIL: DNS — {e}", file=sys.stderr)
        print(
            "\nFix: (1) Supabase → Settings → Database → copy **Session pooler** URI "
            "(host is often *.pooler.supabase.com, not db.*.supabase.co). "
            "(2) Try other Wi‑Fi / hotspot / disable VPN. "
            "(3) Set DNS to 8.8.8.8. "
            "(4) Run: nslookup " + host,
            file=sys.stderr,
        )
        return 2

    print("Connecting with psycopg...")
    try:
        import psycopg
    except ImportError:
        print("ERROR: pip install 'psycopg[binary]'", file=sys.stderr)
        return 1
    try:
        with psycopg.connect(raw, connect_timeout=15) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        print("OK: Postgres connection works.")
    except Exception as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
