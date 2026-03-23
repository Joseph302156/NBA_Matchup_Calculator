#!/usr/bin/env python3
"""
Full-stack web app: pick a date → see NBA matchup predictions with rosters, stats, injuries, win%.
Run from project root: uvicorn app.main:app --reload
"""
import json
import logging
import os

from dotenv import load_dotenv
load_dotenv()  # load .env from project root so OPENAI_API_KEY is available
from datetime import date, timedelta
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, Request, Form, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from config import RECENT_STATS_GAMES
from src.web_pipeline import build_predictions_for_date
from src.predictions_db import is_configured as predictions_db_configured, try_get_cached, warm_date_range
from app.chat import build_chat_context, get_reply, _json_safe
from src.data.fetchers import (
    get_player_last_n_game_logs,
    get_league_player_stats_per_game,
    get_roster_with_stats,
    get_injuries,
    _normalize_name_for_match,
)
from src.player_projection import PlayerBaseStats, PlayerGameContext, project_player_stats

logger = logging.getLogger(__name__)

# Minutes to add to projected MIN when a star teammate (≥18 PPG) is Out.
STAR_OUT_MINUTES_BUMP = 4.0

# Cached rows must match what results.html expects or we refetch live (avoids 500 on bad JSONB).
_GAME_KEYS_F = (
    "win_pct_away",
    "win_pct_home",
    "pick",
    "pick_win_pct",
    "away_tricode",
    "home_tricode",
)


def _prediction_cache_usable(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    if "games" not in payload or "date_display" not in payload:
        return False
    games = payload.get("games")
    if not isinstance(games, list):
        return False
    for g in games:
        if not isinstance(g, dict):
            return False
        if not all(k in g for k in _GAME_KEYS_F):
            return False
    return True


def _index_form_context(request: Request, error: Optional[str] = None) -> dict:
    today = date.today()
    return {
        "request": request,
        "error": error,
        "today": today,
        "min_date": today - timedelta(days=30),
        "max_date": today + timedelta(days=180),
    }


def _normalize_results_payload(data: dict) -> None:
    """Mutate payload so results.html never hits missing keys (stale cache rows)."""
    for g in data.get("games") or []:
        if not isinstance(g, dict):
            continue
        g.setdefault("away_roster", [])
        g.setdefault("home_roster", [])
        g.setdefault("away_injuries", [])
        g.setdefault("home_injuries", [])
        g.setdefault("team_comparison", {})


def _results_html_or_index(request: Request, data: dict):
    """Template render can still throw (e.g. unexpected types in loops); never return raw 500."""
    try:
        return templates.TemplateResponse(request, "results.html", data)
    except Exception:
        logger.exception("results.html render failed")
        return templates.TemplateResponse(
            request,
            "index.html",
            _index_form_context(
                request,
                "Page failed to render — often a stale or incompatible cache row for this date. "
                "Try another date or re-run the warm script; you can delete that date in predictions_date_cache.",
            ),
        )


app = FastAPI(title="NBA Matchup Calculator", version="1.0")

BASE = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE, "templates"))


def _tojson_filter(v: object) -> str:
    """Embed JSON in HTML; must survive Decimal/datetime/NaN from cached DB payloads."""
    try:
        safe = _json_safe(v if v is not None else {})
        return json.dumps(safe)
    except (TypeError, ValueError):
        logger.exception("tojson filter failed")
        return "{}"


templates.env.filters["tojson"] = _tojson_filter

if os.path.exists(os.path.join(BASE, "static")):
    app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")


def _background_warm_predictions(start: date, end: date) -> None:
    try:
        warm_date_range(start, end)
    except Exception as exc:
        print(f"[predictions-cache] warm failed: {exc}", flush=True)


def load_predictions_for_web(date_str: str) -> dict:
    """Use Postgres cache when present and shape-valid; otherwise live NBA pipeline."""
    key = (date_str or "").strip()[:10]
    if predictions_db_configured():
        cached = try_get_cached(key)
        if cached is not None and _prediction_cache_usable(cached):
            return cached
    return build_predictions_for_date(key)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Date picker: choose which day to see matchup predictions."""
    return templates.TemplateResponse(request, "index.html", _index_form_context(request))


@app.get("/results", response_class=HTMLResponse)
async def results_get(request: Request, date_str: str = ""):
    """Results page: show predictions for the given date (GET with ?date=YYYY-MM-DD)."""
    if not date_str:
        return templates.TemplateResponse(
            request,
            "index.html",
            _index_form_context(request, "Please select a date."),
        )
    try:
        data = load_predictions_for_web(date_str)
    except Exception:
        logger.exception("load_predictions_for_web failed date=%r", date_str)
        return templates.TemplateResponse(
            request,
            "index.html",
            _index_form_context(
                request,
                "Could not load predictions (NBA API timeout or server error). "
                "Try again shortly; if this persists on Render, warm the cache from a machine that can reach stats.nba.com.",
            ),
        )
    data["request"] = request
    _normalize_results_payload(data)
    dd = data.get("date_display") or date_str
    data["chat_context"] = (
        build_chat_context(dd, data.get("games") or []) if data.get("games") else {}
    )
    return _results_html_or_index(request, data)


@app.post("/results", response_class=HTMLResponse)
async def results_post(request: Request, game_date: str = Form(...)):
    """Results page: form submit with selected date."""
    raw = (game_date or "").strip()
    if not raw:
        return templates.TemplateResponse(
            request,
            "index.html",
            _index_form_context(request, "Please select a date."),
        )
    try:
        data = load_predictions_for_web(raw)
    except Exception:
        logger.exception("load_predictions_for_web failed date=%r", raw)
        return templates.TemplateResponse(
            request,
            "index.html",
            _index_form_context(
                request,
                "Could not load predictions (NBA API timeout or server error). "
                "Try again shortly; if this persists on Render, warm the cache from a machine that can reach stats.nba.com.",
            ),
        )
    data["request"] = request
    _normalize_results_payload(data)
    dd = data.get("date_display") or raw
    data["chat_context"] = (
        build_chat_context(dd, data.get("games") or []) if data.get("games") else {}
    )
    return _results_html_or_index(request, data)

class ChatBody(BaseModel):
    message: str = ""
    game_index: int = 0
    game_date: Optional[str] = None


@app.post("/api/chat")
async def api_chat(body: ChatBody):
    """Chat endpoint: answer questions about the matchup using server-side matchup data."""
    try:
        target_date = (body.game_date or date.today().strftime("%Y-%m-%d")).strip()
        data = load_predictions_for_web(target_date)
        ctx = build_chat_context(data.get("date_display", target_date), data.get("games") or [])
        reply = get_reply(body.message, body.game_index, ctx)
        return {"reply": reply}
    except Exception:
        logger.exception("api_chat failed")
        return JSONResponse(
            status_code=503,
            content={
                "reply": "Could not load matchup data (NBA timeout or server error). Refresh the page or try again.",
            },
        )


@app.get("/api/player-games")
async def api_player_games(player_id: int, n: int = 5):
    """Last N game-by-game stat lines for a player (for player stats / chart)."""
    try:
        games = get_player_last_n_game_logs(player_id, n=n)
        return {"games": games}
    except Exception:
        logger.exception("api_player_games failed player_id=%s", player_id)
        return JSONResponse(status_code=503, content={"games": [], "error": "nba_fetch_failed"})


# Reused for /api/player-projection so we don't refetch league stats on every click.
_player_stats_cache: dict = {}


def _star_out_minutes_bump(team_id: int) -> float:
    """Return extra minutes (e.g. 4) when a star teammate (≥18 PPG) is Out, else 0."""
    try:
        injuries = get_injuries()
        injuries_list = injuries.get(team_id) or []
        out_names = {
            _normalize_name_for_match(i.get("player_name") or "")
            for i in injuries_list
            if (i.get("status") or "").strip().lower() == "out"
        }
        if not out_names:
            return 0.0
        roster = get_roster_with_stats(team_id, _player_stats_cache)
        for p in roster:
            if _normalize_name_for_match(p.get("player_name") or "") in out_names:
                try:
                    if float(p.get("PTS") or 0) >= 18:
                        return STAR_OUT_MINUTES_BUMP
                except (TypeError, ValueError):
                    pass
    except Exception:
        pass
    return 0.0


@app.get("/api/player-projection")
async def api_player_projection(player_id: int, is_home: bool = False, team_id: Optional[int] = None):
    """On-demand projection (season + recent blend, home bump). If team_id given, add minutes when a star teammate is Out."""
    try:
        stats_map = get_league_player_stats_per_game(_player_stats_cache)
        row = stats_map.get(player_id, {})
        if not row:
            return {"projections": {}}
        season_min = float(row.get("MIN") or 0.0)
        season_pts = float(row.get("PTS") or 0.0)
        season_ast = float(row.get("AST") or 0.0)
        season_reb = float(row.get("REB") or 0.0)
        season_stl = float(row.get("STL") or 0.0)
        season_blk = float(row.get("BLK") or 0.0)
        try:
            logs = get_player_last_n_game_logs(player_id, n=RECENT_STATS_GAMES)
        except Exception:
            logs = []
        recent_games = [
            {"pts": g.get("pts", 0.0), "reb": g.get("reb", 0.0), "ast": g.get("ast", 0.0),
             "stl": g.get("stl", 0.0), "blk": g.get("blk", 0.0), "min": g.get("min", 0.0)}
            for g in logs
        ]
        base = PlayerBaseStats(
            season_pts=season_pts, season_reb=season_reb, season_ast=season_ast,
            season_stl=season_stl, season_blk=season_blk, season_min=season_min,
            recent_games=recent_games,
        )
        bump = _star_out_minutes_bump(team_id) if team_id is not None else 0.0
        ctx = PlayerGameContext(is_home=is_home, star_out_minutes_bump=bump)
        proj = project_player_stats(base, ctx)
        return {
            "projections": {
                k: {"mean": round(v["mean"], 1), "stdev": round(v["stdev"], 1)}
                for k, v in proj.items()
            }
        }
    except Exception:
        logger.exception("api_player_projection failed player_id=%s", player_id)
        return JSONResponse(status_code=503, content={"projections": {}, "error": "nba_fetch_failed"})


@app.post("/internal/refresh-predictions-cache")
def internal_refresh_predictions_cache(
    background_tasks: BackgroundTasks,
    authorization: Optional[str] = Header(None),
):
    """
    Queue warm of predictions_date_cache for today .. today+WARM_CACHE_DAYS_AHEAD.
    Returns immediately (warm runs in background) so HTTP cron probes don't time out.

    Authorization: Bearer <CRON_SECRET>

    For a blocking run with exit codes (e.g. local CI), use:
      python scripts/warm_predictions_cache.py
    """
    secret = (os.environ.get("CRON_SECRET") or "").strip()
    if not secret or (authorization or "").strip() != f"Bearer {secret}":
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not predictions_db_configured():
        raise HTTPException(
            status_code=503,
            detail="DATABASE_URL not set or psycopg missing — cannot warm cache.",
        )
    days = int(os.environ.get("WARM_CACHE_DAYS_AHEAD", "7"))
    today = date.today()
    end = today + timedelta(days=days)
    background_tasks.add_task(_background_warm_predictions, today, end)
    return {
        "status": "accepted",
        "from": today.isoformat(),
        "through": end.isoformat(),
        "days": days,
    }
