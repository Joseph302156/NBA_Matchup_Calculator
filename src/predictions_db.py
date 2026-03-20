"""
Postgres JSONB cache for build_predictions_for_date() payloads (one row per game date).
Used for fast first loads when a cron job keeps rows warm.

Env:
  DATABASE_URL or SUPABASE_DB_URL — Postgres connection string (Supabase: Project Settings → Database).
  PREDICTIONS_DB_MAX_AGE_SECONDS — optional; if set, try_get_cached returns None when row is older (fallback to live).
"""
from __future__ import annotations

import json
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

try:
    import psycopg
    from psycopg.types.json import Json
except ImportError:  # pragma: no cover
    psycopg = None  # type: ignore
    Json = None  # type: ignore


def get_database_url() -> Optional[str]:
    return (os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL") or "").strip() or None


def is_configured() -> bool:
    return bool(get_database_url() and psycopg is not None)


def verify_db_connection() -> None:
    """Raise on first failed connect (fail fast before expensive NBA warm)."""
    if not is_configured():
        raise RuntimeError("DATABASE_URL not set or psycopg not installed")
    url = get_database_url()
    assert url and psycopg
    with psycopg.connect(url, connect_timeout=20) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")


def _warm_pause_seconds() -> float:
    """Sleep between dates when warming cache (easier on NBA + DNS)."""
    try:
        return max(0.0, float(os.environ.get("WARM_CACHE_PAUSE_SECONDS", "5")))
    except ValueError:
        return 5.0


def _max_age_seconds() -> Optional[int]:
    raw = os.environ.get("PREDICTIONS_DB_MAX_AGE_SECONDS", "").strip()
    if not raw:
        return None
    try:
        return max(0, int(raw))
    except ValueError:
        return None


def ensure_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS predictions_date_cache (
                game_date DATE PRIMARY KEY,
                payload JSONB NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_predictions_date_cache_updated_at
            ON predictions_date_cache (updated_at DESC);
            """
        )


def try_get_cached(game_date_str: str) -> Optional[dict[str, Any]]:
    """
    Return cached payload dict (same shape as build_predictions_for_date) or None.
    """
    if not is_configured():
        return None
    url = get_database_url()
    assert url
    max_age = _max_age_seconds()
    try:
        with psycopg.connect(url) as conn:
            ensure_table(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload, updated_at
                    FROM predictions_date_cache
                    WHERE game_date = %s::date
                    """,
                    (game_date_str[:10],),
                )
                row = cur.fetchone()
            if not row:
                return None
            payload, updated_at = row[0], row[1]
            if max_age is not None and updated_at is not None:
                now = datetime.now(timezone.utc)
                if updated_at.tzinfo is None:
                    updated_at = updated_at.replace(tzinfo=timezone.utc)
                age = (now - updated_at).total_seconds()
                if age > max_age:
                    return None
            if isinstance(payload, str):
                return json.loads(payload)
            if isinstance(payload, dict):
                return payload
            return json.loads(json.dumps(payload, default=str))
    except Exception:
        return None


def _upsert_predictions_once(game_date_str: str, body: dict[str, Any]) -> None:
    url = get_database_url()
    assert url and psycopg and Json
    with psycopg.connect(url, connect_timeout=30) as conn:
        ensure_table(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO predictions_date_cache (game_date, payload, updated_at)
                VALUES (%s::date, %s::jsonb, NOW())
                ON CONFLICT (game_date) DO UPDATE SET
                    payload = EXCLUDED.payload,
                    updated_at = NOW();
                """,
                (game_date_str[:10], Json(body)),
            )
        conn.commit()


def _upsert_transient_msg(msg: str) -> bool:
    m = msg.lower()
    return any(
        s in m
        for s in (
            "resolve",
            "nodename",
            "connection",
            "timeout",
            "closed",
            "eof",
            "broken pipe",
            "server closed",
            "ssl",
            "network",
        )
    )


def upsert_predictions(game_date_str: str, payload: dict[str, Any]) -> None:
    """Store full pipeline dict for a date (UPSERT), with retries for flaky DNS/network."""
    if not is_configured():
        raise RuntimeError("DATABASE_URL not set or psycopg not installed")
    body = json.loads(json.dumps(payload, default=str))
    for attempt in range(4):
        try:
            _upsert_predictions_once(game_date_str, body)
            return
        except Exception as e:
            if attempt < 3 and _upsert_transient_msg(str(e)):
                time.sleep(1.5 * (2**attempt))
                continue
            raise


def warm_date_range(
    start: date,
    end: date,
    *,
    skip_on_pipeline_error: bool = True,
) -> dict[str, Any]:
    """
    For each date in [start, end] inclusive, run build_predictions_for_date and upsert.
    Lazy-imports web pipeline to avoid heavy import when DB unused.
    """
    from src.web_pipeline import build_predictions_for_date

    if start > end:
        start, end = end, start
    verify_db_connection()
    stats: dict[str, Any] = {"ok": 0, "failed": 0, "errors": []}
    d = start
    one_day = timedelta(days=1)
    pause = _warm_pause_seconds()
    while d <= end:
        ds = d.isoformat()
        try:
            data = build_predictions_for_date(ds)
            upsert_predictions(ds, data)
            stats["ok"] += 1
        except Exception as e:  # pragma: no cover
            stats["failed"] += 1
            stats["errors"].append({"date": ds, "error": str(e)})
            if not skip_on_pipeline_error:
                raise
        d += one_day
        if d <= end and pause > 0:
            time.sleep(pause)
    return stats
