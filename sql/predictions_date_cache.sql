-- Run once in Supabase SQL editor (or any Postgres) before using the cache.
CREATE TABLE IF NOT EXISTS predictions_date_cache (
    game_date DATE PRIMARY KEY,
    payload JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_predictions_date_cache_updated_at
    ON predictions_date_cache (updated_at DESC);
