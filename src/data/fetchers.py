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
    LeagueGameLog,
    ScheduleLeagueV2,
    TeamGameLog,
    TeamEstimatedMetrics,
)
from nba_api.stats.library.parameters import PerModeDetailed, PlayerOrTeamAbbreviation
from nba_api.stats.static import teams as static_teams
from nba_api.live.nba.endpoints import scoreboard

from config import current_season, UPCOMING_DAYS, RECENT_GAMES_N, REQUEST_DELAY, DAYS_SINCE_LAST_GAME_OUT, RECENT_STATS_GAMES, RECENT_STATS_WEIGHT


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
    LeagueDashTeamStats for current season. Returns dict team_id -> per-game and percentage stats
    for team comparison: PTS, OPP_PTS (if available), FG_PCT, FG3_PCT, FT_PCT, REB, AST, STL, BLK, TOV, PF.
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
        out = {
            "PTS": round(pts / gp, 1),
            "PLUS_MINUS": float(row.get("PLUS_MINUS", 0)) / gp,
            "W": int(row.get("W", 0)),
            "L": int(row.get("L", 0)),
            "GP": gp,
        }
        # Per-game totals (API returns season totals)
        for key in ("REB", "AST", "STL", "BLK", "TOV", "PF"):
            total = float(row.get(key, 0))
            out[key] = round(total / gp, 1)
        # Percentages (usually 0–1 or already percentage)
        for key in ("FG_PCT", "FG3_PCT", "FT_PCT"):
            val = float(row.get(key, 0))
            if val <= 1 and val != 0:
                out[key] = round(val * 100, 1)
            else:
                out[key] = round(val, 1)
        # Opponent PTS per game if column exists (e.g. from another source or same df)
        opp_pts = row.get("OPP_PTS") or row.get("OPP_PTS_PER_GAME")
        if opp_pts is not None:
            out["OPP_PTS"] = round(float(opp_pts) / gp if float(opp_pts) > 100 else float(opp_pts), 1)
        by_id[tid] = out
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


def get_available_player_value(
    team_id,
    injuries_list,
    player_stats_cache=None,
    weights=None,
    recent_stats=None,
    recent_weight=None,
):
    """
    Sum of weighted stat contributions for players who are NOT out (or half for Questionable/Doubtful).

    Player impact is explicitly scaled by their share of the team's minutes so that
    30–40 MPG starters / stars contribute much more than deep bench players.

    If recent_stats (dict player_id -> {MIN, PTS, ...}) is provided, each player's contribution
    uses a blend of season and recent averages so "how they're playing lately" matters.
    recent_weight: 0 = season only, 1 = recent only; default RECENT_STATS_WEIGHT.

    Returns single float 'value' and list of out player names for logging.
    """
    if weights is None:
        weights = {"PTS": 1.0, "AST": 0.5, "REB": 0.4, "STL": 0.6, "BLK": 0.6}
    if recent_weight is None:
        recent_weight = RECENT_STATS_WEIGHT

    roster_stats = get_roster_with_stats(team_id, player_stats_cache)

    out_names = set()
    questionable_names = set()
    for inv in injuries_list or []:
        pname = _normalize_name_for_match(inv.get("player_name") or "")
        if not pname:
            continue
        status = inv.get("status")
        if status == "Out":
            out_names.add(pname)
        elif status in ("Questionable", "Doubtful"):
            questionable_names.add(pname)

    # Total per-game minutes across the roster; should be ~240 in practice.
    total_min = 0.0
    for p in roster_stats:
        try:
            total_min += float(p.get("MIN") or 0.0)
        except (TypeError, ValueError):
            continue
    if total_min <= 0:
        total_min = 1.0

    value = 0.0
    for p in roster_stats:
        nnorm = _normalize_name_for_match(p["player_name"])
        is_out = nnorm in out_names

        # Minutes share: starters ~0.15–0.2, rotation guys ~0.05–0.1, deep bench very small.
        try:
            p_min = float(p.get("MIN") or 0.0)
        except (TypeError, ValueError):
            p_min = 0.0
        minute_share = max(0.0, p_min / total_min)
        # Use minutes as a softer modifier: mostly driven by statlines, but starters
        # still count more than deep bench. Range roughly [0.2, 1.0].
        minute_factor = 0.2 + 0.8 * minute_share

        # Questionable / doubtful players at half strength. Fully Out players are handled
        # separately via a negative contribution.
        mult = 0.5 if (nnorm in questionable_names and not is_out) else 1.0

        pid = p.get("player_id")
        recent = (recent_stats or {}).get(pid) if pid is not None else None

        for stat, w in weights.items():
            if stat == "MIN":
                continue
            season_val = p.get(stat) or 0.0
            if recent and stat in recent:
                blended = (1 - recent_weight) * season_val + recent_weight * (recent.get(stat) or 0.0)
            else:
                blended = season_val

            # Make scoring and playmaking impact grow faster than linearly so
            # high-usage scorers and creators are valued disproportionately more.
            effective = blended
            if stat == "PTS":
                # Piecewise exponential-ish scaling:
                # - 20+ PPG gets a boost,
                # - 25+ PPG is much higher,
                # - 30+ PPG is worth ~4x a 25 PPG scorer.
                pts = max(0.0, blended)
                if pts >= 30:
                    effective = pts * 4.0
                elif pts >= 25:
                    effective = pts * 2.5
                elif pts >= 20:
                    effective = pts * 1.5
                else:
                    effective = pts
            elif stat == "AST":
                # Similar idea for assists; baseline around 5 APG.
                baseline = 5.0
                norm = max(0.0, blended / baseline)
                effective = baseline * (norm ** 2)

            # Available players add value; Out players subtract their would-be value, so
            # losing a high-PPG, high-minutes star actively drags the team's strength down.
            direction = -1.0 if is_out else 1.0
            value += direction * mult * minute_factor * w * effective

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


def get_player_last_game_dates(cache=None):
    """
    Last game date for every player who has played this season (league game log, player mode).
    Returns dict player_id (int) -> datetime.date. Cached in cache['player_last_game'] if provided.
    Used to treat "no game in 14+ days" as Out (long-term injured / not on active report).
    """
    if cache is not None and "player_last_game" in cache:
        return cache["player_last_game"]
    season = _season()
    try:
        e = LeagueGameLog(
            season=season,
            player_or_team_abbreviation=PlayerOrTeamAbbreviation.player,
        )
        time.sleep(REQUEST_DELAY)
        df = e.get_data_frames()[0]
    except Exception:
        if cache is not None:
            cache["player_last_game"] = {}
        return {}
    if df is None or df.empty:
        if cache is not None:
            cache["player_last_game"] = {}
        return {}
    # Player mode returns PLAYER_ID and GAME_DATE (NBA API)
    pid_col = "PLAYER_ID" if "PLAYER_ID" in df.columns else None
    if pid_col is None and "Player_ID" in df.columns:
        pid_col = "Player_ID"
    date_col = "GAME_DATE" if "GAME_DATE" in df.columns else "GAME_DATE"
    if pid_col is None or date_col not in df.columns:
        if cache is not None:
            cache["player_last_game"] = {}
        return {}
    df = df.copy()
    df["_date"] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=["_date"])
    # Most recent game per player (log is usually descending by date)
    last = df.groupby(pid_col)["_date"].max()
    result = {}
    for pid, dt in last.items():
        try:
            result[int(pid)] = dt.date()
        except Exception:
            continue
    if cache is not None:
        cache["player_last_game"] = result
    return result


def get_player_recent_stats(cache=None, last_n=None):
    """
    Per-player averages over their last N games (LeagueGameLog player mode).
    Returns dict player_id -> { MIN, PTS, AST, REB, STL, BLK }.
    Used to blend with season stats so "how they're playing lately" matters.
    """
    if last_n is None:
        last_n = RECENT_STATS_GAMES
    if cache is not None and "player_recent_stats" in cache:
        return cache["player_recent_stats"]
    season = _season()
    try:
        e = LeagueGameLog(
            season=season,
            player_or_team_abbreviation=PlayerOrTeamAbbreviation.player,
        )
        time.sleep(REQUEST_DELAY)
        df = e.get_data_frames()[0]
    except Exception:
        if cache is not None:
            cache["player_recent_stats"] = {}
        return {}
    if df is None or df.empty:
        if cache is not None:
            cache["player_recent_stats"] = {}
        return {}
    pid_col = "PLAYER_ID" if "PLAYER_ID" in df.columns else ("Player_ID" if "Player_ID" in df.columns else None)
    date_col = "GAME_DATE" if "GAME_DATE" in df.columns else None
    stat_cols = ["MIN", "PTS", "AST", "REB", "STL", "BLK"]
    if pid_col is None or date_col is None or any(c not in df.columns for c in stat_cols):
        if cache is not None:
            cache["player_recent_stats"] = {}
        return {}
    df = df.copy()
    df["_date"] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=["_date"])
    df = df.sort_values("_date", ascending=False)
    result = {}
    for pid, grp in df.groupby(pid_col):
        head = grp.head(last_n)
        if head.empty:
            continue
        try:
            result[int(pid)] = {
                "MIN": float(head["MIN"].mean()),
                "PTS": float(head["PTS"].mean()),
                "AST": float(head["AST"].mean()),
                "REB": float(head["REB"].mean()),
                "STL": float(head["STL"].mean()),
                "BLK": float(head["BLK"].mean()),
            }
        except Exception:
            continue
    if cache is not None:
        cache["player_recent_stats"] = result
    return result


def augment_injuries_with_recent_games(injuries, team_ids, player_last_game_dates, cutoff_days=None):
    """
    Add to injuries any roster player who hasn't played in cutoff_days (default DAYS_SINCE_LAST_GAME_OUT).
    Mutates injuries in place. Use so long-term injured players (off current report) show as Out.
    """
    if cutoff_days is None:
        cutoff_days = DAYS_SINCE_LAST_GAME_OUT
    from datetime import date
    today = date.today()
    for tid in team_ids:
        roster = get_team_roster(tid)
        existing = {_normalize_name_for_match(i.get("player_name") or "") for i in injuries.get(tid, [])}
        for p in roster:
            pname = (p.get("player_name") or "").strip()
            if not pname:
                continue
            if _normalize_name_for_match(pname) in existing:
                continue
            pid = p.get("player_id")
            last_d = player_last_game_dates.get(pid) if pid is not None else None
            if last_d is None:
                # No game this season -> treat as Out
                days_since = 999
            else:
                days_since = (today - last_d).days
            if days_since >= cutoff_days:
                injuries.setdefault(tid, []).append({"status": "Out", "player_name": pname})


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
