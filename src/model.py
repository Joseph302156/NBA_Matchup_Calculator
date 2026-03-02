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
    SEASON_STRENGTH_WEIGHT,
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
    total_value_home=None,
    total_value_away=None,
):
    """
    game: dict with home_team_id, away_team_id, ...
    team_stats: dict team_id -> { PTS, PLUS_MINUS, W, L, GP }.
    recent_form: dict team_id -> list of 1/0 (W/L) for last N games.
    injuries: dict team_id -> list of {'status': 'Out'|'Questionable', 'player_name': str}.
    rest: dict with 'home_days', 'away_days' (int or None); 0 = B2B.
    ortg_drtg: dict team_id -> {E_OFF_RATING, E_DEF_RATING}.
    available_value_home/away: float, weighted sum of available players' stats.
    total_value_home/away: float, same metric if everyone played; used to scale ORtg/DRtg
        by who is actually playing so ratings reflect the current lineup.

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

    # ----- Season-long team strength (heavily downweighted) -----
    home_base = home_stats.get("PLUS_MINUS")
    if home_base is None:
        home_base = home_stats.get("PTS") or 0.0
    else:
        home_base = float(home_base)
    away_base = away_stats.get("PLUS_MINUS")
    if away_base is None:
        away_base = away_stats.get("PTS") or 0.0
    else:
        away_base = float(away_base)

    # Team offensive/defensive rating: scale by who is actually playing so ORtg/DRtg
    # reflect contribution of available players only (league avg = 100).
    home_od = ortg_drtg.get(hid, {})
    away_od = ortg_drtg.get(aid, {})
    home_ortg_raw = float(home_od.get("E_OFF_RATING", 0) or 0)
    home_drtg_raw = float(home_od.get("E_DEF_RATING", 0) or 0)
    away_ortg_raw = float(away_od.get("E_OFF_RATING", 0) or 0)
    away_drtg_raw = float(away_od.get("E_DEF_RATING", 0) or 0)

    league_avg = 100.0
    if total_value_home and total_value_home > 0 and available_value_home is not None:
        ratio_h = max(0.0, min(1.0, available_value_home / total_value_home))
        home_ortg_adj = league_avg + (home_ortg_raw - league_avg) * ratio_h
        home_drtg_adj = league_avg + (home_drtg_raw - league_avg) * ratio_h
    else:
        home_ortg_adj, home_drtg_adj = home_ortg_raw, home_drtg_raw
    if total_value_away and total_value_away > 0 and available_value_away is not None:
        ratio_a = max(0.0, min(1.0, available_value_away / total_value_away))
        away_ortg_adj = league_avg + (away_ortg_raw - league_avg) * ratio_a
        away_drtg_adj = league_avg + (away_drtg_raw - league_avg) * ratio_a
    else:
        away_ortg_adj, away_drtg_adj = away_ortg_raw, away_drtg_raw

    home_net = home_ortg_adj - home_drtg_adj
    away_net = away_ortg_adj - away_drtg_adj
    home_base += home_net * ORTG_DRTG_WEIGHT
    away_base += away_net * ORTG_DRTG_WEIGHT

    # Season strength is scaled down so history matters but much less than players + recent games.
    home_str = home_base * SEASON_STRENGTH_WEIGHT
    away_str = away_base * SEASON_STRENGTH_WEIGHT

    # ----- Player-based component: who is actually available, minutes-weighted -----
    if available_value_home is not None:
        home_str += available_value_home * PLAYER_VALUE_WEIGHT
    if available_value_away is not None:
        away_str += available_value_away * PLAYER_VALUE_WEIGHT

    # Home court advantage
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
