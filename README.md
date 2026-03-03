# NBA game win probability & picks

Automated pipeline that fetches upcoming NBA games and outputs win percentages and a pick per game using team strength (point differential), home/away, and recent form.

## Setup

```bash
cd "/Users/josephpang/repos/projects/Project 2"
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Optional (fallback injury source): `pip install nbainjuries` and Java 8+. Injuries are **primarily** from ESPN’s **league injuries API** (no Java needed); nbainjuries is used only if ESPN returns no data.

Create a `.env` file for the AI chat assistant (or export the variable in your shell):

```bash
cp .env.example .env
# then edit .env and paste your key:
# OPENAI_API_KEY=sk-...
```

The web app loads `.env` automatically via `python-dotenv` (`load_dotenv()` in `app/main.py`).

## Web app (full-stack)

Pick a date and view matchup predictions with rosters, statlines, injury report, ORtg/DRtg, and win %.

```bash
uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000 — choose a date and click **Calculate predictions**. Results show each game: away @ home, win % bar, pick, team ORtg/DRtg, full roster with MIN/PTS/AST/REB/STL/BLK and Playing/Out/Questionable status, and injury report.

On the right side of the results page there is an **AI assistant chat panel**. It uses OpenAI (model `gpt-4o-mini` by default) plus the current matchup context to answer questions about:

- Why a team is favored, which players matter most, how injuries/rest affect the edge
- How the model works for this specific game

If `OPENAI_API_KEY` is not set, the chat panel will tell you to configure the key instead of calling the API.

## Run (CLI)

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
| **Injuries** | **ESPN** league injuries API (primary), `nbainjuries` (fallback) | League-wide feed of Out/Doubtful/Questionable; mapped from ESPN team ids/abbrevs to `nba_api` ids (handles GS/GSW, NO/NOP, etc.); no Java required for ESPN |
| **Team ORtg/DRtg** | TeamEstimatedMetrics | E_OFF_RATING, E_DEF_RATING per team |
| **Player stats** | CommonTeamRoster + LeagueDashPlayerStats (PerGame) | Season MIN, PTS, AST, REB, STL, BLK; blended with **last 5 games** (LeagueGameLog) so recent form matters; injured players excluded from "available value" |
| **Stat importance** | `src/analysis/stat_importance.py` | Correlation of team PTS/AST/REB/STL/BLK with W_PCT → weights for player contribution |

## How win % is calculated

1. **Strength (point-like units)**  
   Each team gets a strength number from: **season point differential** (PLUS_MINUS), **team net rating** (ORtg − DRtg, scaled), and **available player value** (weighted sum of PTS/AST/REB/STL/BLK for non-out players, using **season + last 5 games** blend so recent performance matters more).

2. **Adjustments**  
   We add **home-court advantage** (~2.5 pts), **recent form** (last 10 games win rate), subtract **injury penalties** (Out / Questionable), and **rest** (back-to-back penalty, extra rest bonus).

3. **Strength difference → win %**  
   `diff = home_strength - away_strength`. We convert to probability with a **logistic curve**: `win_pct_home = 1 / (1 + exp(-diff / 9))`. The divisor 9 keeps the curve gentle so a big gap doesn’t push 98%. We then **clamp** win % to **12%–88%** so you rarely see extreme numbers.

4. **Tunables in `config.py`**  
   - `PLAYER_VALUE_WEIGHT`: how much “who’s playing and their stats” matters.  
   - `LOGISTIC_SCALE`: larger = softer curve (fewer extremes).  
   - `WIN_PCT_FLOOR` / `WIN_PCT_CEIL`: clamp range.  
   - `RECENT_STATS_GAMES` and `RECENT_STATS_WEIGHT`: last N games and blend with season (e.g. 0.55 = slight tilt to recent).

## Improving later

- **Player-level:** Use roster + player impact (e.g. BPM, VORP) to adjust for “who’s in”.
- **Model:** Replace logistic-style formula with a proper model (e.g. Elo, Poisson, or ML) and backtest.
- **Refresh:** Run as a daemon or cron; optionally serve via FastAPI and a small frontend.

## Project layout

```
config.py           # season, UPCOMING_DAYS, REFRESH_MINUTES, model weights
main.py             # CLI: fetch → predict → print/JSON
app/
  main.py           # FastAPI: / (date picker), /results (predictions for date)
  templates/        # index.html, results.html
  static/style.css  # dark theme, game cards, rosters, badges
src/
  data/fetchers.py  # games, team stats, roster, player stats, ORtg/DRtg, injuries, rest
  web_pipeline.py   # build_predictions_for_date() for web
  analysis/stat_importance.py
  model.py
requirements.txt
.venv/
```
