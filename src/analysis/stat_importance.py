"""
Compute relative importance of stats (PTS, AST, REB, STL, BLK) for winning.
Uses current-season team totals: correlation of each stat per game with team win%.
Returns weights suitable for weighting player contributions.
"""
import math
import time
from nba_api.stats.endpoints import LeagueDashTeamStats
from config import current_season, REQUEST_DELAY


def get_team_stat_weights(season=None):
    """
    For each stat (PTS, AST, REB, STL, BLK), compute correlation with team W_PCT.
    Returns dict stat_name -> weight (positive, relative importance). Higher = more predictive of wins.
    """
    season = season or current_season()
    e = LeagueDashTeamStats(season=season)
    time.sleep(REQUEST_DELAY)
    df = e.get_data_frames()[0]
    if df is None or df.empty:
        return {"PTS": 1.0, "AST": 0.5, "REB": 0.4, "STL": 0.6, "BLK": 0.6}
    # Per-game: totals are in df; divide by GP
    gp = df["GP"].astype(float).replace(0, 1)
    stats = ["PTS", "AST", "REB", "STL", "BLK"]
    w_pct = df["W_PCT"].astype(float)
    correlations = {}
    for s in stats:
        if s not in df.columns:
            correlations[s] = 0.0
            continue
        per_game = df[s].astype(float) / gp
        c = w_pct.corr(per_game)
        correlations[s] = max(0.0, float(c)) if not math.isnan(c) else 0.0
    # Normalize so max is 1.0
    m = max(correlations.values()) or 1.0
    return {k: (v / m) for k, v in correlations.items()}


def get_player_stat_weights(season=None):
    """
    Same as get_team_stat_weights but tuned for player-level (same stats).
    We use team correlations as proxy for player stat importance toward winning.
    """
    return get_team_stat_weights(season)
