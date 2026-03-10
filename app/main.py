#!/usr/bin/env python3
"""
Full-stack web app: pick a date → see NBA matchup predictions with rosters, stats, injuries, win%.
Run from project root: uvicorn app.main:app --reload
"""
import json
import os

from dotenv import load_dotenv
load_dotenv()  # load .env from project root so OPENAI_API_KEY is available
from datetime import date, timedelta
from typing import Optional

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from config import RECENT_STATS_GAMES
from src.web_pipeline import build_predictions_for_date
from app.chat import build_chat_context, get_reply
from src.data.fetchers import get_player_last_n_game_logs, get_league_player_stats_per_game
from src.player_projection import PlayerBaseStats, PlayerGameContext, project_player_stats

app = FastAPI(title="NBA Matchup Calculator", version="1.0")

BASE = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE, "templates"))
templates.env.filters["tojson"] = lambda v: json.dumps(v)

if os.path.exists(os.path.join(BASE, "static")):
    app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Date picker: choose which day to see matchup predictions."""
    today = date.today()
    # Season typically Oct–Apr; allow a reasonable range
    min_date = today - timedelta(days=30)
    max_date = today + timedelta(days=180)
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "min_date": min_date, "max_date": max_date, "today": today},
    )


@app.get("/results", response_class=HTMLResponse)
async def results_get(request: Request, date_str: str = ""):
    """Results page: show predictions for the given date (GET with ?date=YYYY-MM-DD)."""
    today = date.today()
    if not date_str:
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "error": "Please select a date.",
                "today": today,
                "min_date": today - timedelta(days=30),
                "max_date": today + timedelta(days=180),
            },
        )
    data = build_predictions_for_date(date_str)
    data["request"] = request
    data["chat_context"] = build_chat_context(data["date_display"], data.get("games") or []) if data.get("games") else {}
    return templates.TemplateResponse("results.html", data)


@app.post("/results", response_class=HTMLResponse)
async def results_post(request: Request, game_date: str = Form(...)):
    """Results page: form submit with selected date."""
    today = date.today()
    if not game_date.strip():
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "error": "Please select a date.",
                "today": today,
                "min_date": today - timedelta(days=30),
                "max_date": today + timedelta(days=180),
            },
        )
    data = build_predictions_for_date(game_date.strip())
    data["request"] = request
    data["chat_context"] = build_chat_context(data["date_display"], data.get("games") or []) if data.get("games") else {}
    return templates.TemplateResponse("results.html", data)

class ChatBody(BaseModel):
    message: str = ""
    game_index: int = 0
    game_date: Optional[str] = None


@app.post("/api/chat")
async def api_chat(body: ChatBody):
    """Chat endpoint: answer questions about the matchup using server-side matchup data."""
    # Use the requested date if provided; otherwise fall back to today's date string.
    target_date = (body.game_date or date.today().strftime("%Y-%m-%d")).strip()
    data = build_predictions_for_date(target_date)
    ctx = build_chat_context(data.get("date_display", target_date), data.get("games") or [])
    reply = get_reply(body.message, body.game_index, ctx)
    return {"reply": reply}


@app.get("/api/player-games")
async def api_player_games(player_id: int, n: int = 5):
    """Last N game-by-game stat lines for a player (for player stats / chart)."""
    games = get_player_last_n_game_logs(player_id, n=n)
    return {"games": games}


# Reused for /api/player-projection so we don't refetch league stats on every click.
_player_stats_cache: dict = {}


@app.get("/api/player-projection")
async def api_player_projection(player_id: int, is_home: bool = False):
    """On-demand projection for one player (season + recent blend, home bump). No defense/usage/rust on this path."""
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
    ctx = PlayerGameContext(is_home=is_home)
    proj = project_player_stats(base, ctx)
    return {
        "projections": {
            k: {"mean": round(v["mean"], 1), "stdev": round(v["stdev"], 1)}
            for k, v in proj.items()
        }
    }
