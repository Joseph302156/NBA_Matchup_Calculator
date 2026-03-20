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


def upsert_predictions(game_date_str: str, payload: dict[str, Any]) -> None:
    """Store full pipeline dict for a date (UPSERT)."""
    if not is_configured():
        raise RuntimeError("DATABASE_URL not set or psycopg not installed")
    url = get_database_url()
    assert url
    body = json.loads(json.dumps(payload, default=str))
    with psycopg.connect(url) as conn:
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
    stats: dict[str, Any] = {"ok": 0, "failed": 0, "errors": []}
    d = start
    one_day = timedelta(days=1)
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
    return stats
