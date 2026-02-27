# NBA game win probability & picks

Automated pipeline that fetches upcoming NBA games and outputs win percentages and a pick per game using team strength (point differential), home/away, and recent form.

## Setup

```bash
cd "/Users/josephpang/repos/projects/Project 2"
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Optional (for injury data): `pip install nbainjuries` and ensure Java 8+ is installed. Without it, the model still runs; injury counts are treated as 0.

## Run

From project root:

```bash
python main.py              # next 3 days (config.UPCOMING_DAYS)
python main.py --days 1     # next 1 day
python main.py --json       # machine-readable JSON
```

## Updating data regularly

- **Cron (recommended):** Run every 30–60 min and write results to a file or DB.

  ```bash
  # every 30 min
  */30 * * * * cd /path/to/Project\ 2 && .venv/bin/python main.py --json >> /tmp/nba_picks.jsonl
  ```

- **Loop script (optional):** A `run_loop.py` can sleep `REFRESH_MINUTES` and re-run; run it in a terminal or under systemd/supervisor.

## What it uses today

| Factor | Source | Notes |
|--------|--------|--------|
| Schedule / upcoming games | `nba_api` ScheduleLeagueV2 | Filter by game status & date window |
| Team strength | LeagueDashTeamStats | PTS/game, PLUS_MINUS (point diff) |
| Recent form | TeamGameLog (last N games) | Win rate in last 10 games |
| Home/away | Schedule | Home-court advantage (~2.5 pts) |
| **Rest / back-to-back** | TeamGameLog last game date | B2B (0 rest): −2 pts; 2+ days rest: +0.5 pts |
| **Injuries** | `nbainjuries` (optional) | Out/Questionable with **player names**; matched to roster so we know who is missing |
| **Team ORtg/DRtg** | TeamEstimatedMetrics | E_OFF_RATING, E_DEF_RATING per team |
| **Player stats** | CommonTeamRoster + LeagueDashPlayerStats (PerGame) | MIN, PTS, AST, REB, STL, BLK; injured players excluded from "available value" |
| **Stat importance** | `src/analysis/stat_importance.py` | Correlation of team PTS/AST/REB/STL/BLK with W_PCT → weights for player contribution |

## Improving later

- **Player-level:** Use roster + player impact (e.g. BPM, VORP) to adjust for “who’s in”.
- **Model:** Replace logistic-style formula with a proper model (e.g. Elo, Poisson, or ML) and backtest.
- **Refresh:** Run as a daemon or cron; optionally serve via FastAPI and a small frontend.

## Project layout

```
config.py           # season, UPCOMING_DAYS, RECENT_GAMES_N, REFRESH_MINUTES
main.py             # CLI: fetch → predict → print/JSON
src/
  data/fetchers.py  # games, team stats, roster, player stats, ORtg/DRtg, injuries, rest
  analysis/stat_importance.py  # correlation-based weights for PTS/AST/REB/STL/BLK
  model.py          # predict_game(..., ortg_drtg, available_value_home/away)
requirements.txt
.venv/
```
