"""
Fetch upcoming games, team stats, recent form, injuries (ESPN primary, nbainjuries fallback), rest/B2B.
"""
import time
from datetime import datetime, timedelta

import pandas as pd
import requests

from nba_api.stats.endpoints import (
    CommonTeamRoster,
    LeagueDashPlayerStats,
    LeagueDashTeamStats,
    ScheduleLeagueV2,
    TeamGameLog,
    TeamEstimatedMetrics,
)
from nba_api.stats.library.parameters import PerModeDetailed
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


def get_games_for_date(target_date):
    """
    Return games on a single date. target_date: datetime.date or 'YYYY-MM-DD' string.
    Includes scheduled (1) and in-progress (2). Same structure as get_upcoming_games.
    """
    if hasattr(target_date, "strftime"):
        date_str = target_date.strftime("%Y-%m-%d")
    else:
        date_str = str(target_date)[:10]
    season = _season()
    s = ScheduleLeagueV2(season=season)
    time.sleep(REQUEST_DELAY)
    df = s.get_data_frames()[0]
    if df is None or df.empty:
        return []

    df = df[df["gameStatus"].isin([1, 2, 3])].copy()  # scheduled, in progress, or final

    out = []
    for _, row in df.iterrows():
        est = row.get("gameDateEst") or row.get("gameDateTimeEst")
        if pd.isna(est):
            continue
        try:
            d = pd.to_datetime(est).date()
            row_date = d.strftime("%Y-%m-%d")
        except Exception:
            continue
        if row_date != date_str:
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
    out.sort(key=lambda x: (x["game_date_est"] or ""))
    return out


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


def get_team_roster(team_id):
    """Current roster: list of {player_id, player_name, position}."""
    season = _season()
    e = CommonTeamRoster(team_id=str(team_id), season=season)
    time.sleep(REQUEST_DELAY)
    dfs = e.get_data_frames()
    roster_df = dfs[0] if dfs else None
    if roster_df is None or roster_df.empty:
        return []
    out = []
    for _, row in roster_df.iterrows():
        out.append({
            "player_id": int(row["PLAYER_ID"]),
            "player_name": (row.get("PLAYER") or row.get("PLAYER_NAME") or "").strip(),
            "position": (row.get("POSITION") or "").strip(),
        })
    return out


def get_league_player_stats_per_game(cache=None):
    """
    All players season per-game: MIN, PTS, AST, REB, STL, BLK. Returns dict player_id -> stats.
    cache: optional dict to store result and skip refetch.
    """
    if cache is not None and "player_stats" in cache:
        return cache["player_stats"]
    season = _season()
    e = LeagueDashPlayerStats(season=season, per_mode_detailed=PerModeDetailed.per_game)
    time.sleep(REQUEST_DELAY)
    df = e.get_data_frames()[0]
    if df is None or df.empty:
        result = {}
    else:
        result = {}
        for _, row in df.iterrows():
            pid = int(row["PLAYER_ID"])
            gp = int(row.get("GP", 1)) or 1
            result[pid] = {
                "MIN": float(row.get("MIN", 0) or 0),
                "PTS": float(row.get("PTS", 0) or 0),
                "AST": float(row.get("AST", 0) or 0),
                "REB": float(row.get("REB", 0) or 0),
                "STL": float(row.get("STL", 0) or 0),
                "BLK": float(row.get("BLK", 0) or 0),
                "GP": gp,
            }
    if cache is not None:
        cache["player_stats"] = result
    return result


def get_team_ortg_drtg(cache=None):
    """Team estimated offensive/defensive rating. Dict team_id -> {E_OFF_RATING, E_DEF_RATING}."""
    if cache is not None and "ortg_drtg" in cache:
        return cache["ortg_drtg"]
    season = _season()
    e = TeamEstimatedMetrics(season=season)
    time.sleep(REQUEST_DELAY)
    df = e.get_data_frames()[0]
    if df is None or df.empty:
        result = {}
    else:
        result = {}
        for _, row in df.iterrows():
            tid = int(row["TEAM_ID"])
            result[tid] = {
                "E_OFF_RATING": float(row.get("E_OFF_RATING", 0) or 0),
                "E_DEF_RATING": float(row.get("E_DEF_RATING", 0) or 0),
            }
    if cache is not None:
        cache["ortg_drtg"] = result
    return result


def get_roster_with_stats(team_id, player_stats_cache=None):
    """
    Roster for team with per-game stats (MIN, PTS, AST, REB, STL, BLK).
    Returns list of {player_id, player_name, position, MIN, PTS, AST, REB, STL, BLK}.
    """
    roster = get_team_roster(team_id)
    stats_map = get_league_player_stats_per_game(player_stats_cache)
    out = []
    for p in roster:
        s = stats_map.get(p["player_id"], {})
        out.append({
            "player_id": p["player_id"],
            "player_name": p["player_name"],
            "position": p["position"],
            "MIN": s.get("MIN", 0),
            "PTS": s.get("PTS", 0),
            "AST": s.get("AST", 0),
            "REB": s.get("REB", 0),
            "STL": s.get("STL", 0),
            "BLK": s.get("BLK", 0),
        })
    return out


def _normalize_player_name(name):
    """Lowercase, collapse spaces. For matching injury report to roster."""
    if not name:
        return ""
    return " ".join(str(name).lower().split())


def _normalize_name_for_match(name):
    """
    Canonical form for matching: injury report uses "Last, First" (e.g. "Brown, Jaylen"),
    roster uses "First Last" (e.g. "Jaylen Brown"). Convert both to "first last".
    """
    if not name:
        return ""
    s = " ".join(str(name).strip().lower().split())
    if "," in s:
        parts = s.split(",", 1)
        last_part = parts[0].strip()
        first_part = parts[1].strip()
        return f"{first_part} {last_part}"
    return s


def get_available_player_value(team_id, injuries_list, player_stats_cache=None, weights=None):
    """
    Sum of weighted stat contributions for players who are NOT out (or half for Questionable).
    injuries_list: list of {'status': 'Out'|'Questionable', 'player_name': str} for this team.
    weights: dict e.g. {'PTS': 1.0, 'AST': 0.5, 'REB': 0.4, 'STL': 0.6, 'BLK': 0.6}. MIN can be used as weight for minutes.
    Returns single float 'value' and list of out player names for logging.
    """
    if weights is None:
        weights = {"PTS": 1.0, "AST": 0.5, "REB": 0.4, "STL": 0.6, "BLK": 0.6}
    roster_stats = get_roster_with_stats(team_id, player_stats_cache)
    out_names = set()
    questionable_names = set()
    for inv in injuries_list or []:
        pname = _normalize_name_for_match(inv.get("player_name") or "")
        if not pname:
            continue
        if inv.get("status") == "Out":
            out_names.add(pname)
        elif inv.get("status") in ("Questionable", "Doubtful"):
            questionable_names.add(pname)
    value = 0.0
    for p in roster_stats:
        nnorm = _normalize_name_for_match(p["player_name"])
        if nnorm in out_names:
            continue
        mult = 0.5 if nnorm in questionable_names else 1.0
        for stat, w in weights.items():
            if stat == "MIN":
                continue
            value += mult * w * (p.get(stat) or 0)
    return value, list(out_names)


def get_recent_form(team_id, n=RECENT_GAMES_N):
    """Last N games for a team: list of W/L (1/0)."""
    season = _season()
    e = TeamGameLog(team_id=str(team_id), season=season)
    time.sleep(REQUEST_DELAY)
    df = e.get_data_frames()[0]
    if df is None or df.empty:
        return []
    df = df.head(n)
    return [1 if wl == "W" else 0 for wl in df["WL"].tolist()]


def _team_name_to_id():
    """Map full team name (e.g. 'Boston Celtics') -> nba_api team id."""
    return {t["full_name"]: t["id"] for t in static_teams.get_teams()}


def _espn_team_id_to_nba_id():
    """Map ESPN API team id -> nba_api team id. Fetches ESPN teams list once."""
    nba_by_abbrev = {t["abbreviation"]: t["id"] for t in static_teams.get_teams()}
    try:
        r = requests.get(
            "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams",
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
    except Exception:
        return {}
    # Response can be: { "teams": [...] } or { "sports": [ { "leagues": [ { "teams": [...] } ] } ] }
    teams_list = data.get("teams")
    if not teams_list and "sports" in data and data["sports"]:
        leagues = data["sports"][0].get("leagues") or []
        if leagues:
            teams_list = leagues[0].get("teams")
    if not teams_list:
        return {}
    out = {}
    for item in teams_list:
        team = item.get("team", item) if isinstance(item, dict) else item
        if not isinstance(team, dict):
            continue
        espn_id = team.get("id")
        abbr = (team.get("abbreviation") or "").strip()
        if espn_id is not None and abbr:
            nba_id = nba_by_abbrev.get(abbr)
            if nba_id is not None:
                out[str(espn_id)] = nba_id
    return out


def get_injuries_espn():
    """
    Injury report from ESPN roster API. Each team roster includes athletes with
    injuries[] (status + date). Returns dict team_id (nba_api id) -> list of
    {'status': 'Out'|'Doubtful'|'Questionable', 'player_name': str}.
    """
    espn_to_nba = _espn_team_id_to_nba_id()
    if not espn_to_nba:
        return {}
    by_team = {}
    for espn_id_str, nba_id in espn_to_nba.items():
        try:
            time.sleep(0.15)
            r = requests.get(
                f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{espn_id_str}/roster",
                timeout=10,
            )
            r.raise_for_status()
            data = r.json()
        except Exception:
            continue
        athletes = data.get("athletes") or []
        for ath in athletes:
            injuries = ath.get("injuries") or []
            if not injuries:
                continue
            full_name = (ath.get("fullName") or ath.get("displayName") or "").strip()
            if not full_name:
                continue
            # Use first injury entry; status can be "Out", "Doubtful", "Questionable", "Day-To-Day", etc.
            raw_status = (injuries[0].get("status") or "").strip()
            if not raw_status:
                continue
            status = raw_status
            if status.lower() in ("out", "out for season"):
                status = "Out"
            elif status.lower() in ("doubtful",):
                status = "Doubtful"
            else:
                status = "Questionable"  # Questionable, Day-To-Day, etc.
            by_team.setdefault(nba_id, []).append({"status": status, "player_name": full_name})
    return by_team


def get_injuries():
    """
    Injury report: tries ESPN roster API first (no Java, reliable); if empty or error,
    falls back to nbainjuries. Returns dict team_id -> list of
    {'status': 'Out'|'Doubtful'|'Questionable', 'player_name': str}.
    """
    injuries = get_injuries_espn()
    if injuries:
        return injuries
    try:
        from nbainjuries import injury
    except Exception:
        return {}
    name_to_id = _team_name_to_id()
    now = datetime.utcnow()
    step_hours = 6
    max_hours_back = 24 * 6
    data = []
    for hours_back in range(0, max_hours_back, step_hours):
        if hours_back == 0:
            ts = now
        else:
            ts = now - timedelta(hours=hours_back)
        try:
            if hours_back > 0:
                time.sleep(0.25)
            data = injury.get_reportdata(ts)
            if data:
                break
        except Exception:
            continue
    if not data:
        return {}
    by_team = {}
    for row in data:
        team_name = row.get("Team") or row.get("team")
        status = (row.get("Current Status") or row.get("current_status") or "").strip()
        if status not in ("Out", "Questionable", "Doubtful"):
            continue
        tid = name_to_id.get(team_name)
        if tid is None:
            continue
        player_name = (row.get("Player Name") or row.get("player_name") or "").strip()
        if not player_name:
            continue
        by_team.setdefault(tid, []).append({"status": status, "player_name": player_name})
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
