"""App config. Override with env vars if you add dotenv later."""
from datetime import datetime

def current_season():
    """e.g. 2025-26 for season starting Oct 2025."""
    now = datetime.now()
    if now.month >= 10:
        return f"{now.year}-{str(now.year + 1)[-2:]}"
    return f"{now.year - 1}-{str(now.year)[-2:]}"

# How many days ahead to consider "upcoming" games
UPCOMING_DAYS = 3
# Recent games for form (W/L record)
RECENT_GAMES_N = 10
# Refresh: run every N minutes when in daemon mode (future)
REFRESH_MINUTES = 30
# NBA.com can rate-limit; delay between heavy requests (seconds)
REQUEST_DELAY = 0.6

# Model: home court and form
HOME_ADVANTAGE_PTS = 2.5
RECENT_FORM_WEIGHT = 0.25
# Rest / back-to-back
REST_B2B_PENALTY_PTS = 2.0       # pts to subtract when team played yesterday (0 rest days)
REST_EXTRA_BONUS_PTS = 0.5      # pts to add when team has 2+ days rest
# Injuries (model): strength penalty per player
INJURY_OUT_WEIGHT = 1.0         # full penalty for "Out"
INJURY_QUESTIONABLE_WEIGHT = 0.4  # partial for "Questionable"
INJURY_WEIGHT = 0.35            # multiplier: penalty = INJURY_WEIGHT * (out*1 + questionable*0.4)

# Team offensive/defensive rating (from TeamEstimatedMetrics)
ORTG_DRTG_WEIGHT = 0.015       # (ortg - drtg) scale: ~100 pts typical; 0.015 * 5 ≈ 0.075 strength
# Available player value (weighted sum of non-injured player stats) — higher = more weight on who's playing
PLAYER_VALUE_WEIGHT = 0.005    # increased so player capability and recent form matter more

# Win % curve: soften extremes so we rarely see 98% or 2%
LOGISTIC_SCALE = 9            # larger = gentler curve (diff/9 instead of diff/5)
WIN_PCT_FLOOR = 0.12          # minimum home win % (avoid 0–5% displays)
WIN_PCT_CEIL = 0.88           # maximum home win % (avoid 95–100% displays)

# Player recent games: blend season stats with last N games for "how they're playing lately"
RECENT_STATS_GAMES = 5         # last N games per player for recent averages
RECENT_STATS_WEIGHT = 0.55     # 0 = season only, 1 = recent only; 0.55 = slight tilt to recent

# Long-term / no-recent-game: treat as Out if no game in this many days
DAYS_SINCE_LAST_GAME_OUT = 14
