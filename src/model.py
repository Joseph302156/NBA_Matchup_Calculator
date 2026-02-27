"""
Win-probability model: team strength, home/away, recent form, injuries, rest/B2B.
Strength is in "point-like" units; we convert to win % with a logistic curve.
More weight is on who's actually playing and their (season + recent) stats.
"""
import math

from config import (
    RECENT_GAMES_N,
    HOME_ADVANTAGE_PTS,
    RECENT_FORM_WEIGHT,
    REST_B2B_PENALTY_PTS,
    REST_EXTRA_BONUS_PTS,
    INJURY_WEIGHT,
    INJURY_OUT_WEIGHT,
    INJURY_QUESTIONABLE_WEIGHT,
    ORTG_DRTG_WEIGHT,
    PLAYER_VALUE_WEIGHT,
    LOGISTIC_SCALE,
    WIN_PCT_FLOOR,
    WIN_PCT_CEIL,
)


def _team_strength(pts_for, pts_against):
    """Simple strength = offensive rating - defensive (points)."""
    if pts_against and pts_against > 0:
        return pts_for - pts_against
    return pts_for


def _form_rate(form_list):
    return sum(form_list) / len(form_list) if form_list else 0.5


def _injury_penalty(injury_list):
    """Sum weighted penalty for Out (1.0), Questionable (0.4), Doubtful (0.4)."""
    if not injury_list:
        return 0.0
    s = 0.0
    for item in injury_list:
        if isinstance(item, dict):
            status = (item.get("status") or "").strip()
        else:
            status = str(item)
        if status == "Out":
            s += INJURY_OUT_WEIGHT
        elif status in ("Questionable", "Doubtful"):
            s += INJURY_QUESTIONABLE_WEIGHT
    return s * INJURY_WEIGHT


def predict_game(
    game,
    team_stats,
    recent_form=None,
    injuries=None,
    rest=None,
    ortg_drtg=None,
    available_value_home=None,
    available_value_away=None,
):
    """
    game: dict with home_team_id, away_team_id, ...
    team_stats: dict team_id -> { PTS, PLUS_MINUS, W, L, GP }.
    recent_form: dict team_id -> list of 1/0 (W/L) for last N games.
    injuries: dict team_id -> list of {'status': 'Out'|'Questionable', 'player_name': str}.
    rest: dict with 'home_days', 'away_days' (int or None); 0 = B2B.
    ortg_drtg: dict team_id -> {E_OFF_RATING, E_DEF_RATING}.
    available_value_home/away: float, weighted sum of available players' stats.

    Returns: (win_pct_home, win_pct_away, pick_home True/False).
    """
    recent_form = recent_form or {}
    injuries = injuries or {}
    rest = rest or {}
    ortg_drtg = ortg_drtg or {}
    hid = game["home_team_id"]
    aid = game["away_team_id"]

    home_stats = team_stats.get(hid, {})
    away_stats = team_stats.get(aid, {})

    home_str = home_stats.get("PLUS_MINUS")
    if home_str is None:
        home_str = home_stats.get("PTS") or 0.0
    else:
        home_str = float(home_str)
    away_str = away_stats.get("PLUS_MINUS")
    if away_str is None:
        away_str = away_stats.get("PTS") or 0.0
    else:
        away_str = float(away_str)

    # Team offensive/defensive rating: net rating vs league (~100)
    home_od = ortg_drtg.get(hid, {})
    away_od = ortg_drtg.get(aid, {})
    home_net = (float(home_od.get("E_OFF_RATING", 0) or 0) - float(home_od.get("E_DEF_RATING", 0) or 0))
    away_net = (float(away_od.get("E_OFF_RATING", 0) or 0) - float(away_od.get("E_DEF_RATING", 0) or 0))
    home_str += home_net * ORTG_DRTG_WEIGHT
    away_str += away_net * ORTG_DRTG_WEIGHT

    # Available player value (who's actually playing)
    if available_value_home is not None:
        home_str += available_value_home * PLAYER_VALUE_WEIGHT
    if available_value_away is not None:
        away_str += available_value_away * PLAYER_VALUE_WEIGHT

    home_str += HOME_ADVANTAGE_PTS

    home_form_rate = _form_rate(recent_form.get(hid, []))
    away_form_rate = _form_rate(recent_form.get(aid, []))
    home_str += (home_form_rate - 0.5) * 10 * RECENT_FORM_WEIGHT
    away_str += (away_form_rate - 0.5) * 10 * RECENT_FORM_WEIGHT

    home_str -= _injury_penalty(injuries.get(hid, []))
    away_str -= _injury_penalty(injuries.get(aid, []))

    home_rest = rest.get("home_days")
    away_rest = rest.get("away_days")
    if home_rest is not None:
        if home_rest == 0:
            home_str -= REST_B2B_PENALTY_PTS
        elif home_rest >= 2:
            home_str += REST_EXTRA_BONUS_PTS
    if away_rest is not None:
        if away_rest == 0:
            away_str -= REST_B2B_PENALTY_PTS
        elif away_rest >= 2:
            away_str += REST_EXTRA_BONUS_PTS

    diff = home_str - away_str
    # Softer curve: win_pct = 1 / (1 + exp(-diff/scale)). Larger scale = less extreme %.
    raw = 1 / (1 + math.exp(-diff / LOGISTIC_SCALE))
    win_pct_home = max(WIN_PCT_FLOOR, min(WIN_PCT_CEIL, raw))
    win_pct_away = 1 - win_pct_home
    pick_home = win_pct_home >= 0.5
    return round(win_pct_home, 3), round(win_pct_away, 3), pick_home
