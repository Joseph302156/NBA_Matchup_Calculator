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

### Predictions cache (Postgres / Supabase) — optional

For **fast first load** on `/results`, you can store each date’s full pipeline output in Postgres and refresh on a schedule.

1. **Create a Supabase project** (or any Postgres). In **SQL Editor**, run `sql/predictions_date_cache.sql`.
2. **Connection string:** Project Settings → Database → URI. Set `DATABASE_URL` in `.env` / Render (use **Session mode** pooler or direct `5432`; include `?sslmode=require` if required).
3. **Install:** `pip install -r requirements.txt` (adds `psycopg`).
4. **Warm rows** for today through today+14 days:
   ```bash
   export DATABASE_URL="postgresql://..."
   python scripts/warm_predictions_cache.py
   ```
5. **App behavior:** If `DATABASE_URL` is set and a row exists for the requested date, `/results` and `/api/chat` **read from DB**. Otherwise they use the **live** pipeline (same as before). Optional `PREDICTIONS_DB_MAX_AGE_SECONDS` forces a live refresh when the row is too old.
6. **Cron every 30–60 min:**
   - **GitHub Actions** (recommended for long runs): scheduled workflow that runs `python scripts/warm_predictions_cache.py` with `DATABASE_URL` in repo secrets.
   - **HTTP trigger:** `POST /internal/refresh-predictions-cache` with header `Authorization: Bearer <CRON_SECRET>` and env `CRON_SECRET` set. The handler **queues** work in a background task and returns immediately. On **Render free tier**, the instance may sleep right after the response and **kill** the background warm — prefer the **script** on a scheduler, or a **paid** always-on instance, for reliable warms.

Env vars: see `.env.example` (`DATABASE_URL`, `CRON_SECRET`, `WARM_CACHE_DAYS_AHEAD`, `PREDICTIONS_DB_MAX_AGE_SECONDS`).

## Web app (full-stack)

Pick a date and view matchup predictions with rosters, statlines, injury report, ORtg/DRtg, and win %.

```bash
uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000 — choose a date and click **Calculate predictions**. Results show each game: away @ home, win % bar, pick, team ORtg/DRtg, full roster with MIN/PTS/AST/REB/STL/BLK and Playing/Out/Questionable status, and injury report.

**Player card:** Click a player name to open a profile with headshot, season averages, **projected stats** for the upcoming game (blend of season + last 5 games, home-court bump, and extra minutes when a star teammate is out), and a bar chart of their last 5 games (switchable by stat: PTS, AST, REB, STL, BLK, MIN). Projections are computed **on demand** when you open the card (not at page load) to keep date selection fast.

On the right side of the results page there is an **AI assistant chat panel**. It uses OpenAI (model `gpt-4o-mini` by default) plus the current matchup context to answer questions about:

- Why a team is favored, which players matter most, how injuries/rest affect the edge
- How the model works for this specific game

If `OPENAI_API_KEY` is not set, the chat panel will tell you to configure the key instead of calling the API.

**Backend speed (env vars, optional):**

| Variable | Default | Effect |
|----------|---------|--------|
| `PIPELINE_CACHE_TTL_SECONDS` | `1800` (30 min) | Reuses NBA/ESPN-heavy responses for this many seconds (schedule per date, team stats, injuries, ORtg/DRtg + league recent-player rollup, stat weights). Set `0` to disable. |
| `PIPELINE_PARALLEL_WORKERS` | `6` | Parallel fetches for team recent form + each team’s last game date (rest). Lower (e.g. `2`) if you hit NBA rate limits. |

### APIs used by the results page

| Endpoint | Purpose |
|----------|---------|
| `GET /api/player-games?player_id=...&n=5` | Last N game-by-game stat lines (for the bar chart). |
| `GET /api/player-projection?player_id=...&is_home=true\|false&team_id=...` | On-demand projected stats (mean per stat). Optional `team_id` enables “star out” minutes bump when a teammate with ≥18 PPG is Out. |

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
| **Projected player stats** | `src/player_projection.py` + on-demand API | Shown in player card: blend of season + last 5 games (65% recent / 35% season), home-court +3% to PTS/AST, and +3–5 min when a star teammate (≥18 PPG) is Out; computed only when the user opens a player’s card |

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
   - `RECENT_STATS_GAMES` and `RECENT_STATS_WEIGHT`: last N games and blend with season (e.g. 0.65 = stronger tilt to recent for player projections).

### How projected player stats are calculated

Used in the player card when you click a player. Implemented in `src/player_projection.py` and requested on demand via `/api/player-projection`.

1. **Baseline** — Blend season per-game averages with last-5-game averages (`RECENT_STATS_WEIGHT` = 0.65 toward recent).
2. **Context (when available)**  
   - **Home:** +3% to PTS and AST.  
   - **Star teammate out:** If `team_id` is sent and a teammate with ≥18 PPG is Out (injury report), add **+4 minutes** to projected MIN (configurable as `STAR_OUT_MINUTES_BUMP` in `app/main.py`).  
   Other factors (opponent defense, usage bump, rust from games missed) are in the model but not yet wired in the on-demand API path.
3. **Output** — Mean (and stdev) per stat (MIN, PTS, AST, REB, STL, BLK); the UI shows the mean in the "Proj" column next to season average.

## Improving later

- **Player-level:** Use roster + player impact (e.g. BPM, VORP) to adjust for “who’s in”.
- **Model:** Replace logistic-style formula with a proper model (e.g. Elo, Poisson, or ML) and backtest.
- **Projections:** Wire opponent defense, pace, usage, and rust (games missed) into the on-demand projection API so the player card uses full context.
- **Refresh:** Run as a daemon or cron for automated picks.

## Project layout

```
config.py           # season, UPCOMING_DAYS, REFRESH_MINUTES, model weights
main.py             # CLI: fetch → predict → print/JSON
app/
  main.py           # FastAPI: / (date picker), /results (predictions for date)
  templates/        # index.html, results.html
  static/style.css  # dark theme, game cards, rosters, badges
src/
  data/fetchers.py   # games, team stats, roster, player stats, ORtg/DRtg, injuries, rest
  web_pipeline.py    # build_predictions_for_date() for web (rosters + recent averages only; no per-player projection at load)
  player_projection.py  # projected stats: season+recent blend, home, star-out minutes bump
  analysis/stat_importance.py
  model.py
requirements.txt
.venv/
```
