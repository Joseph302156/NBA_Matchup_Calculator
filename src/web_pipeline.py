"""
Build full game payload for web: rosters with statlines, injury status, ORtg/DRtg, win%.
"""
from datetime import datetime

from config import RECENT_GAMES_N
from src.data.fetchers import (
    get_games_for_date,
    get_team_season_stats,
    get_recent_form,
    get_injuries,
    get_rest_days,
    get_team_ortg_drtg,
    get_available_player_value,
    get_roster_with_stats,
    get_player_last_game_dates,
    get_player_recent_stats,
    augment_injuries_with_recent_games,
    _normalize_name_for_match,
)
from src.analysis.stat_importance import get_player_stat_weights
from src.model import predict_game


def _roster_with_injury_status(team_id, injuries_list, player_stats_cache):
    """Roster with stats; each player has 'status': 'Playing'|'Out'|'Questionable'|'Doubtful'."""
    roster = get_roster_with_stats(team_id, player_stats_cache)
    out = set()
    questionable = set()
    doubtful = set()
    for inv in injuries_list or []:
        n = _normalize_name_for_match(inv.get("player_name") or "")
        if not n:
            continue
        st = inv.get("status")
        if st == "Out":
            out.add(n)
        elif st == "Questionable":
            questionable.add(n)
        elif st == "Doubtful":
            doubtful.add(n)
    result = []
    for p in roster:
        nnorm = _normalize_name_for_match(p.get("player_name") or "")
        if nnorm in out:
            status = "Out"
        elif nnorm in doubtful:
            status = "Doubtful"
        elif nnorm in questionable:
            status = "Questionable"
        else:
            status = "Playing"
        result.append({**p, "status": status})
    # Sort: playing first, then questionable, doubtful, out; within that by MIN desc
    order = {"Playing": 0, "Questionable": 1, "Doubtful": 2, "Out": 3}
    result.sort(key=lambda x: (order.get(x["status"], 4), -float(x.get("MIN") or 0)))
    return result


def build_predictions_for_date(target_date):
    """
    target_date: date object or 'YYYY-MM-DD' string.
    Returns: {
        "date": "YYYY-MM-DD",
        "date_display": "Fri, Feb 28, 2026",
        "games": [
            {
                "game_id", "game_date_est",
                "away_team_name", "away_tricode", "away_team_id",
                "home_team_name", "home_tricode", "home_team_id",
                "away_roster": [ { player_name, position, MIN, PTS, AST, REB, STL, BLK, status } ],
                "home_roster": [ ... ],
                "away_injuries": [ { player_name, status } ],
                "home_injuries": [ ... ],
                "away_ortg", "away_drtg", "home_ortg", "home_drtg",
                "win_pct_away", "win_pct_home", "pick", "pick_win_pct",
            },
            ...
        ],
        "error": str or None,
    }
    """
    if hasattr(target_date, "strftime"):
        date_obj = target_date
        date_str = target_date.strftime("%Y-%m-%d")
    else:
        date_str = str(target_date)[:10]
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return {"date": date_str, "date_display": date_str, "games": [], "error": "Invalid date"}

    games = get_games_for_date(date_obj)
    if not games:
        return {
            "date": date_str,
            "date_display": date_obj.strftime("%a, %b %d, %Y"),
            "games": [],
            "error": None,
        }

    team_stats = get_team_season_stats()
    team_ids = set()
    for g in games:
        team_ids.add(g["home_team_id"])
        team_ids.add(g["away_team_id"])
    recent_form = {tid: get_recent_form(tid, RECENT_GAMES_N) for tid in team_ids}
    injuries = get_injuries()
    data_cache = {}
    # Long-term injured: no game in 14+ days → show as Out (best-effort; skip on error)
    try:
        player_last_game = get_player_last_game_dates(data_cache)
        if player_last_game:
            augment_injuries_with_recent_games(injuries, team_ids, player_last_game)
    except Exception:
        pass
    last_game_dates = {}
    ortg_drtg = get_team_ortg_drtg(data_cache)
    try:
        player_recent = get_player_recent_stats(data_cache)
    except Exception:
        player_recent = {}
    try:
        player_weights = get_player_stat_weights()
    except Exception:
        player_weights = {"PTS": 1.0, "AST": 0.5, "REB": 0.4, "STL": 0.6, "BLK": 0.6}

    games_payload = []
    for g in games:
        hid = g["home_team_id"]
        aid = g["away_team_id"]
        home_injuries = injuries.get(hid, [])
        away_injuries = injuries.get(aid, [])

        home_roster = _roster_with_injury_status(hid, home_injuries, data_cache)
        away_roster = _roster_with_injury_status(aid, away_injuries, data_cache)

        home_days = get_rest_days(hid, g["game_date_est"], last_game_dates)
        away_days = get_rest_days(aid, g["game_date_est"], last_game_dates)
        rest = {"home_days": home_days, "away_days": away_days}

        avail_home, _ = get_available_player_value(hid, home_injuries, data_cache, player_weights, recent_stats=player_recent)
        avail_away, _ = get_available_player_value(aid, away_injuries, data_cache, player_weights, recent_stats=player_recent)

        win_home, win_away, pick_home = predict_game(
            g, team_stats, recent_form=recent_form, injuries=injuries, rest=rest,
            ortg_drtg=ortg_drtg, available_value_home=avail_home, available_value_away=avail_away,
        )
        pick_team = g["home_team_name"] if pick_home else g["away_team_name"]
        pick_pct = win_home if pick_home else win_away

        home_od = ortg_drtg.get(hid, {})
        away_od = ortg_drtg.get(aid, {})

        home_ts = team_stats.get(hid, {})
        away_ts = team_stats.get(aid, {})

        games_payload.append({
            "game_id": g["game_id"],
            "game_date_est": g["game_date_est"],
            "away_team_name": g["away_team_name"],
            "away_tricode": g["away_tricode"],
            "away_team_id": aid,
            "home_team_name": g["home_team_name"],
            "home_tricode": g["home_tricode"],
            "home_team_id": hid,
            "away_roster": away_roster,
            "home_roster": home_roster,
            "away_injuries": away_injuries,
            "home_injuries": home_injuries,
            "away_ortg": round(float(away_od.get("E_OFF_RATING") or 0), 1),
            "away_drtg": round(float(away_od.get("E_DEF_RATING") or 0), 1),
            "home_ortg": round(float(home_od.get("E_OFF_RATING") or 0), 1),
            "home_drtg": round(float(home_od.get("E_DEF_RATING") or 0), 1),
            "win_pct_away": round(win_away, 3),
            "win_pct_home": round(win_home, 3),
            "pick": pick_team,
            "pick_win_pct": round(pick_pct, 3),
            "team_comparison": {
                "away": {
                    "PTS": away_ts.get("PTS"),
                    "DRtg": round(float(away_od.get("E_DEF_RATING") or 0), 1),
                    "FG_PCT": away_ts.get("FG_PCT"),
                    "FG3_PCT": away_ts.get("FG3_PCT"),
                    "FT_PCT": away_ts.get("FT_PCT"),
                    "TOV": away_ts.get("TOV"),
                    "REB": away_ts.get("REB"),
                    "AST": away_ts.get("AST"),
                    "STL": away_ts.get("STL"),
                    "BLK": away_ts.get("BLK"),
                    "PF": away_ts.get("PF"),
                },
                "home": {
                    "PTS": home_ts.get("PTS"),
                    "DRtg": round(float(home_od.get("E_DEF_RATING") or 0), 1),
                    "FG_PCT": home_ts.get("FG_PCT"),
                    "FG3_PCT": home_ts.get("FG3_PCT"),
                    "FT_PCT": home_ts.get("FT_PCT"),
                    "TOV": home_ts.get("TOV"),
                    "REB": home_ts.get("REB"),
                    "AST": home_ts.get("AST"),
                    "STL": home_ts.get("STL"),
                    "BLK": home_ts.get("BLK"),
                    "PF": home_ts.get("PF"),
                },
            },
        })
        comp = games_payload[-1]["team_comparison"]
        stat_keys = ["PTS", "DRtg", "FG_PCT", "FG3_PCT", "FT_PCT", "TOV", "REB", "AST", "STL", "BLK", "PF"]
        comp["bars"] = {}
        for k in stat_keys:
            a = comp["away"].get(k)
            h = comp["home"].get(k)
            if a is None:
                a = 0
            if h is None:
                h = 0
            try:
                a, h = float(a), float(h)
            except (TypeError, ValueError):
                a, h = 0, 0
            total = a + h
            if total <= 0:
                comp["bars"][k] = {"away_pct": 50, "home_pct": 50}
            else:
                comp["bars"][k] = {"away_pct": round(a / total * 100, 1), "home_pct": round(h / total * 100, 1)}

    return {
        "date": date_str,
        "date_display": date_obj.strftime("%a, %b %d, %Y"),
        "games": games_payload,
        "error": None,
    }
