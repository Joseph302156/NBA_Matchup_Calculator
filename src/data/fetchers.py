"""
Fetch upcoming games, team stats, recent form, injuries (nbainjuries), rest/B2B.
"""
import time
from datetime import datetime, timedelta

import pandas as pd

from nba_api.stats.endpoints import (
    LeagueDashTeamStats,
    ScheduleLeagueV2,
    TeamGameLog,
)
from nba_api.stats.static import teams as static_teams
from nba_api.live.nba.endpoints import scoreboard

from config import current_season, UPCOMING_DAYS, RECENT_GAMES_N, REQUEST_DELAY


def _season():
    return current_season()


def get_upcoming_games(days_ahead=UPCOMING_DAYS):
    """
    Return list of dicts: game_id, game_date_est, home_team_id, away_team_id,
    home_team_name, away_team_name, home_tricode, away_tricode, home_wins, home_losses,
    away_wins, away_losses, is_home_team_known (from schedule we know home/away).
    Uses ScheduleLeagueV2 then filters to future/scheduled only.
    """
    season = _season()
    s = ScheduleLeagueV2(season=season)
    time.sleep(REQUEST_DELAY)
    df = s.get_data_frames()[0]
    if df is None or df.empty:
        return []

    # gameStatus: 1 = scheduled, 2 = in progress, 3 = final
    df = df[df["gameStatus"].isin([1, 2])].copy()

    now_est = datetime.utcnow() - timedelta(hours=5)
    start_cutoff = now_est - timedelta(hours=12)  # include today's games
    end_cutoff = now_est + timedelta(days=days_ahead)

    def parse_est(s):
        if pd.isna(s):
            return None
        try:
            return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        except Exception:
            return None

    out = []
    for _, row in df.iterrows():
        try:
            est = parse_est(row.get("gameDateEst") or row.get("gameDateTimeEst"))
        except Exception:
            est = None
        if est and est.tzinfo:
            est_naive = est.replace(tzinfo=None) - timedelta(hours=5)
        else:
            est_naive = est
        if est_naive is None or est_naive < start_cutoff or est_naive > end_cutoff:
            continue
        out.append({
            "game_id": row.get("gameId"),
            "game_date_est": row.get("gameDateEst") or row.get("gameDateTimeEst"),
            "game_status": row.get("gameStatus"),
            "home_team_id": int(row["homeTeam_teamId"]),
            "away_team_id": int(row["awayTeam_teamId"]),
            "home_team_name": row["homeTeam_teamName"],
            "away_team_name": row["awayTeam_teamName"],
            "home_tricode": row["homeTeam_teamTricode"],
            "away_tricode": row["awayTeam_teamTricode"],
            "home_wins": int(row.get("homeTeam_wins", 0) or 0),
            "home_losses": int(row.get("homeTeam_losses", 0) or 0),
            "away_wins": int(row.get("awayTeam_wins", 0) or 0),
            "away_losses": int(row.get("awayTeam_losses", 0) or 0),
        })
    # Sort by date
    out.sort(key=lambda x: (x["game_date_est"] or ""))
    return out[: 50]  # cap


def get_team_season_stats():
    """
    LeagueDashTeamStats for current season. Returns dict team_id -> { PTS, OPP_PTS, W, L, ... }.
    """
    season = _season()
    e = LeagueDashTeamStats(season=season)
    time.sleep(REQUEST_DELAY)
    df = e.get_data_frames()[0]
    if df is None or df.empty:
        return {}
    by_id = {}
    for _, row in df.iterrows():
        tid = int(row["TEAM_ID"])
        gp = int(row.get("GP", 1)) or 1
        pts = float(row.get("PTS", 0))
        by_id[tid] = {
            "PTS": pts / gp,
            "PLUS_MINUS": float(row.get("PLUS_MINUS", 0)) / gp,
            "W": int(row.get("W", 0)),
            "L": int(row.get("L", 0)),
            "GP": gp,
        }
    return by_id


def get_recent_form(team_id, n=RECENT_GAMES_N):
    """Last N games for a team: list of W/L (1/0)."""
    season = _season()
    e = TeamGameLog(team_id=str(team_id), season=season)
    time.sleep(REQUEST_DELAY)
    df = e.get_data_frames()[0]
    if df is None or df.empty:
        return []
    # WL column is 'W' or 'L'
    df = df.head(n)
    return [1 if wl == "W" else 0 for wl in df["WL"].tolist()]


def _team_name_to_id():
    """Map full team name (e.g. 'Boston Celtics') -> nba_api team id."""
    return {t["full_name"]: t["id"] for t in static_teams.get_teams()}


def get_injuries():
    """
    Current injury report via nbainjuries. Returns dict team_id -> list of {'status': 'Out'|'Questionable'}.
    Counts only Out/Questionable (not Available). If nbainjuries unavailable, returns {}.
    """
    try:
        from nbainjuries import injury
    except Exception:
        return {}
    name_to_id = _team_name_to_id()
    now = datetime.utcnow()
    try:
        data = injury.get_reportdata(datetime(now.year, now.month, now.day, now.hour, now.minute))
    except Exception:
        return {}
    if not data:
        return {}
    by_team = {}
    for row in data:
        team_name = row.get("Team") or row.get("team")
        status = (row.get("Current Status") or row.get("current_status") or "").strip()
        if status not in ("Out", "Questionable"):
            continue
        tid = name_to_id.get(team_name)
        if tid is None:
            continue
        by_team.setdefault(tid, []).append({"status": status})
    return by_team


def get_last_game_date(team_id):
    """Date of team's most recent game (season). Returns datetime.date or None."""
    season = _season()
    e = TeamGameLog(team_id=str(team_id), season=season)
    time.sleep(REQUEST_DELAY)
    df = e.get_data_frames()[0]
    if df is None or df.empty:
        return None
    first_date = df.iloc[0].get("GAME_DATE")
    if pd.isna(first_date):
        return None
    try:
        return pd.to_datetime(first_date).date()
    except Exception:
        return None


def get_rest_days(team_id, game_date_est_str, last_game_dates_cache=None):
    """
    Rest days before this game. 0 = back-to-back, 1 = one day rest, 2+ = well rested.
    last_game_dates_cache: optional dict team_id -> date to avoid re-fetching.
    """
    if last_game_dates_cache is not None and team_id in last_game_dates_cache:
        last_d = last_game_dates_cache[team_id]
    else:
        last_d = get_last_game_date(team_id)
        if last_game_dates_cache is not None:
            last_game_dates_cache[team_id] = last_d
    if last_d is None:
        return None
    try:
        if "T" in str(game_date_est_str):
            game_d = pd.to_datetime(game_date_est_str).date()
        else:
            game_d = pd.to_datetime(game_date_est_str).date()
    except Exception:
        return None
    delta = (game_d - last_d).days - 1
    return max(0, delta)


def get_live_scoreboard():
    """Today's games from live scoreboard (backup for 'today' when schedule might be stale)."""
    try:
        sb = scoreboard.ScoreBoard()
        d = sb.get_dict()
        games = d.get("scoreboard", {}).get("games", [])
        return games
    except Exception:
        return []
