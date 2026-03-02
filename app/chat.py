"""
AI chat for matchup Q&A: uses matchup context to explain picks, edges, and model logic.
If OPENAI_API_KEY is set, uses GPT; otherwise answers from a static FAQ/keyword responder.
"""
import json
import os
import re


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

You are given per-player data for both teams: away_players and home_players. Each entry has season averages (MIN, PTS, AST, REB, STL, BLK), status (Playing, Out, Questionable, Doubtful), and when available a last_5_avg object with the same stats over their last 5 games. Use this to:
- Answer "how has [player] been performing?" with concrete numbers: cite both season averages and last_5_avg when present, and note if they're Out or Questionable.
- Answer "wouldn't [team] have a disadvantage because [player] is out?" by confirming the disadvantage, citing that player's season (and recent) impact and how the model treats Out players (they subtract value and scale down that team's ORtg/DRtg).

Answer in 2–4 short paragraphs when explaining a pick or the model. Be concrete: cite the matchup data you're given (win%, ORtg/DRtg, who's out, individual player stats). If the user asks about a specific game, use the matchup for that game index (0-based)."""


def _static_reply(message: str, game_index: int, context: dict) -> str:
    """Keyword-based replies when no API key."""
    msg = (message or "").strip().lower()
    games = context.get("games") or []
    g = games[game_index] if 0 <= game_index < len(games) else (games[0] if games else None)

    if not g:
        return "No matchup data is available for this date."

    away = g.get("away_tricode") or g.get("away_team") or "Away"
    home = g.get("home_tricode") or g.get("home_team") or "Home"
    pick = g.get("pick") or "—"
    win_home = (g.get("win_pct_home") or 0) * 100
    win_away = (g.get("win_pct_away") or 0) * 100

    # Who's out
    if re.search(r"who('s|s| is) out|injur|out (for|tonight)|missing", msg):
        parts = []
        a_inj = g.get("away_injuries") or g.get("away_out") or []
        h_inj = g.get("home_injuries") or g.get("home_out") or []
        if a_inj:
            names = [x.get("player_name", x) if isinstance(x, dict) else x for x in a_inj]
            parts.append(f"{away}: {', '.join(names)}")
        if h_inj:
            names = [x.get("player_name", x) if isinstance(x, dict) else x for x in h_inj]
            parts.append(f"{home}: {', '.join(names)}")
        if not parts:
            return f"No players listed as out for {away} or {home} in the current injury report."
        return "Injury report — " + "; ".join(parts)

    # Why favored / pick
    if re.search(r"why (is|are)|favored|pick|who (wins|to pick)|edge", msg):
        return (
            f"The model picks **{pick}** (home win% {win_home:.1f}%, away {win_away:.1f}%). "
            "The prediction weighs: availability-adjusted ORtg/DRtg, who's actually playing (with extra weight on high scorers and recent form), last 5 games, injuries (out players hurt the team), and rest. "
            f"Ratings: {away} ORtg {g.get('away_ortg')} / DRtg {g.get('away_drtg')}; {home} ORtg {g.get('home_ortg')} / DRtg {g.get('home_drtg')}. "
            "For a deeper explanation, set OPENAI_API_KEY and ask again."
        )

    # How does the model work
    if re.search(r"how (does|do)|model|work|calculat|predict", msg):
        return (
            "Predictions combine: (1) season strength at 40% weight; (2) ORtg/DRtg scaled by who's playing (so missing stars pull ratings toward average); "
            "(3) player value by minutes and stats (scoring scales up above 20 PPG); (4) last 5 games form (weight 1.5); (5) injury penalties; (6) rest (B2B penalty, extra rest bonus); (7) small home court. "
            "Win% comes from a logistic curve on the strength difference."
        )

    # Player performance: "how has X been performing" / "how's X been"
    if re.search(r"how (has|have|'s|is) .* (been )?perform|how .* (been )?play", msg):
        for plist in (g.get("away_players") or [], g.get("home_players") or []):
            for p in plist:
                pname = (p.get("player_name") or "").strip()
                if not pname:
                    continue
                if pname.lower() in msg or any(part in msg for part in pname.lower().split() if len(part) > 2):
                    season = f"Season: {p.get('MIN')} MIN, {p.get('PTS')} PTS, {p.get('AST')} AST, {p.get('REB')} REB"
                    last5 = p.get("last_5_avg")
                    if last5:
                        season += f". Last 5: {last5.get('PTS')} PTS, {last5.get('MIN')} MIN"
                    return f"{pname} ({p.get('status', 'Playing')}): {season}."
        return "Ask about a specific player by name; I'll use their season and last-5 stats from this matchup."

    # Disadvantage because X is out
    if re.search(r"disadvantage|hurt|weaker|without .* out|because .* (is |'s )?out", msg):
        for plist in (g.get("away_players") or [], g.get("home_players") or []):
            for p in plist:
                pname = (p.get("player_name") or "").strip()
                if not pname or (p.get("status") or "").lower() != "out":
                    continue
                if pname.lower() in msg or any(part in msg for part in pname.lower().split() if len(part) > 2):
                    pts = p.get("PTS") or 0
                    return (
                        f"Yes. {pname} is Out, so the model reduces that team's strength: it subtracts his value "
                        f"(season ~{pts} PPG and minutes) and scales their ORtg/DRtg toward league average. So that side is at a disadvantage."
                    )
        return "The model does penalize teams when key players are Out (value subtracted, ORtg/DRtg scaled down). Check the injury report for who's out."

    # Default
    return (
        f"For **{away} @ {home}**: pick is **{pick}** (win% home {win_home:.1f}%, away {win_away:.1f}%). "
        "Ask 'Who's out?', 'Why is [team] favored?', or 'How does the model work?' for more. To get detailed AI explanations, set OPENAI_API_KEY."
    )


def get_reply(message: str, game_index: int, context: dict) -> str:
    """
    Return a reply for the user message given the current matchup context.
    Uses OpenAI if OPENAI_API_KEY is set; otherwise static FAQ.
    """
    message = (message or "").strip()
    if not message:
        return "Ask a question about the matchup, the pick, or how the model works."

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if api_key:
        try:
            return _openai_reply(message, game_index, context, api_key)
        except Exception as e:
            return f"The AI service returned an error: {e}. Falling back to a short answer: " + _static_reply(message, game_index, context)

    return _static_reply(message, game_index, context)


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
