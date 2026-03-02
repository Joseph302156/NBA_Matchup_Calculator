"""
AI chat for matchup Q&A: uses matchup context to explain picks, edges, and model logic.
Requires OPENAI_API_KEY; all natural-language understanding is handled by the model.
"""
import json
import os


def _json_safe(obj):
    """Convert to JSON-serializable; replace NaN/Inf."""
    if obj is None:
        return None
    if isinstance(obj, (str, int)):
        return obj
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        if obj != obj or obj == float("inf") or obj == float("-inf"):
            return None
        return round(obj, 4)
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(x) for x in obj]
    return str(obj)


def _player_summary(p, include_recent=True):
    """One player as JSON-safe dict for context (season + optional last-5)."""
    d = {
        "player_name": p.get("player_name"),
        "position": p.get("position"),
        "status": (p.get("status") or "Playing").strip(),
        "MIN": _json_safe(p.get("MIN")),
        "PTS": _json_safe(p.get("PTS")),
        "AST": _json_safe(p.get("AST")),
        "REB": _json_safe(p.get("REB")),
        "STL": _json_safe(p.get("STL")),
        "BLK": _json_safe(p.get("BLK")),
    }
    if include_recent and (p.get("recent_pts") is not None or p.get("recent_min") is not None):
        d["last_5_avg"] = {
            "MIN": _json_safe(p.get("recent_min")),
            "PTS": _json_safe(p.get("recent_pts")),
            "AST": _json_safe(p.get("recent_ast")),
            "REB": _json_safe(p.get("recent_reb")),
            "STL": _json_safe(p.get("recent_stl")),
            "BLK": _json_safe(p.get("recent_blk")),
        }
    return d


def _top_players_by_min(roster, n=10):
    """Top n players by MIN (season)."""
    roster = list(roster or [])
    try:
        roster.sort(key=lambda x: (-float(x.get("MIN") or 0), x.get("player_name") or ""))
    except (TypeError, ValueError):
        pass
    return roster[:n]


def build_chat_context(date_display: str, games: list) -> dict:
    """Build a compact, JSON-safe context for the chat including per-player stats (season + last-5)."""
    out = []
    for g in games:
        away_roster = g.get("away_roster") or []
        home_roster = g.get("home_roster") or []
        away_players = [_player_summary(p) for p in _top_players_by_min(away_roster)]
        home_players = [_player_summary(p) for p in _top_players_by_min(home_roster)]
        out.append({
            "away_team": g.get("away_team_name"),
            "away_tricode": g.get("away_tricode"),
            "home_team": g.get("home_team_name"),
            "home_tricode": g.get("home_tricode"),
            "pick": g.get("pick"),
            "pick_win_pct": _json_safe(g.get("pick_win_pct")),
            "win_pct_away": _json_safe(g.get("win_pct_away")),
            "win_pct_home": _json_safe(g.get("win_pct_home")),
            "away_ortg": g.get("away_ortg"),
            "away_drtg": g.get("away_drtg"),
            "home_ortg": g.get("home_ortg"),
            "home_drtg": g.get("home_drtg"),
            "away_injuries": [{"player_name": i.get("player_name"), "status": i.get("status")} for i in (g.get("away_injuries") or [])],
            "home_injuries": [{"player_name": i.get("player_name"), "status": i.get("status")} for i in (g.get("home_injuries") or [])],
            "away_out": [p.get("player_name") for p in away_roster if (p.get("status") or "").lower() == "out"],
            "home_out": [p.get("player_name") for p in home_roster if (p.get("status") or "").lower() == "out"],
            "away_players": away_players,
            "home_players": home_players,
        })
    return {"date_display": date_display, "games": out}


SYSTEM_PROMPT = """You are an AI assistant for an NBA matchup prediction tool. You help users understand the predictions, edges, and how the model works.

Model summary (use this to explain when asked):
- Predictions combine: (1) season-long team strength (downweighted to 40%) — points, plus/minus; (2) availability-adjusted offensive/defensive rating — ORtg/DRtg scaled by who is actually playing (ratio of available player value to full roster value, so missing stars pull ratings toward league average); (3) who's on the floor — weighted player value by minutes share and stats (scoring has exponential scaling above 20 PPG so stars count more); (4) last 5 games form (W/L) with weight 1.5; (5) injuries — Out players subtract their value and add a penalty; (6) rest — back-to-back penalty, extra rest bonus; (7) small home-court advantage.
- Win probabilities are from a logistic curve on the strength difference; displayed win% is floored/ceilinged to avoid 0–5% or 95–100%.
- "Pick" is the team with higher win probability (home or away).

You are given per-team data (pick, win%, ORtg/DRtg, injuries) and per-player data: away_players and home_players. Each entry has season averages (MIN, PTS, AST, REB, STL, BLK), status (Playing, Out, Questionable, Doubtful), and when available a last_5_avg object with the same stats over their last 5 games.

Use this context to interpret any natural-language question the user asks about this matchup: explain why a team is favored, how a specific player has been performing, how injuries or rest affect the edge, or how the model works.

Answer in 2–4 short paragraphs when explaining a pick or the model. Be concrete: cite the matchup data you're given (win%, ORtg/DRtg, who's out, individual player stats). If the user asks about a specific game, use the matchup for that game index (0-based). The data you're given is always for the date shown as date_display (the results page the user has open). If they ask about a different date (e.g. 'For March 2 why...'), explain that you only have data for the loaded date and they should select that date on the home page to see those matchups."""


def get_reply(message: str, game_index: int, context: dict) -> str:
    """
    Return a reply for the user message given the current matchup context.
    Uses OpenAI; there is no keyword-based fallback so the model can adapt to arbitrary questions.
    """
    message = (message or "").strip()
    if not message:
        return "Ask a question about the matchup, the pick, or how the model works."

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return (
            "To answer detailed natural-language questions about this matchup, set OPENAI_API_KEY "
            "in the server environment and reload the app."
        )

    try:
        return _openai_reply(message, game_index, context, api_key)
    except Exception as e:
        return f"The AI service returned an error: {e}. Try again in a moment."


def _mentioned_players(message: str, game: dict) -> list:
    """If the user message likely mentions a player, return matching player names from this game."""
    msg = (message or "").strip().lower()
    if not msg or not game:
        return []
    names = []
    for key in ("away_players", "home_players"):
        for p in (game.get(key) or []):
            pname = (p.get("player_name") or "").strip()
            if not pname:
                continue
            # Match last name or full name (e.g. "Jaylen Brown", "Brown")
            parts = pname.lower().split()
            if any(part in msg for part in parts if len(part) > 1) or pname.lower() in msg:
                names.append(pname)
    return names


def _openai_reply(message: str, game_index: int, context: dict, api_key: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    games = context.get("games") or []
    g = games[game_index] if 0 <= game_index < len(games) else (games[0] if games else {})
    mentioned = _mentioned_players(message, g)
    focus = ""
    if mentioned:
        focus = f"The user is likely asking about these players: {', '.join(mentioned)}. Use their stats from away_players / home_players above.\n\n"
    user_content = (
        f"Matchup context for the game the user is viewing (index {game_index}):\n"
        f"{json.dumps(g, indent=2)}\n\n"
        f"{focus}User question: {message}"
    )
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        max_tokens=600,
        temperature=0.3,
    )
    text = (resp.choices[0].message.content or "").strip()
    return text or "I couldn't generate a reply."
