#!/usr/bin/env python3
"""
Run predictions for upcoming NBA games. Use from project root:
  python main.py
  python main.py --days 1
  python main.py --json
"""
import argparse
import json
import sys

from config import UPCOMING_DAYS, RECENT_GAMES_N
from src.data.fetchers import (
    get_upcoming_games,
    get_team_season_stats,
    get_recent_form,
    get_injuries,
    get_rest_days,
    get_team_ortg_drtg,
    get_available_player_value,
    get_player_last_game_dates,
    augment_injuries_with_recent_games,
)
from src.analysis.stat_importance import get_player_stat_weights
from src.model import predict_game


def main():
    ap = argparse.ArgumentParser(description="NBA game win probability and picks")
    ap.add_argument("--days", type=int, default=UPCOMING_DAYS, help="Upcoming days to include")
    ap.add_argument("--json", action="store_true", help="Output JSON only")
    args = ap.parse_args()

    if not args.json:
        print("Fetching upcoming games and team data...")
    games = get_upcoming_games(days_ahead=args.days)
    if not games:
        if args.json:
            print(json.dumps({"games": [], "message": "No upcoming games in window"}))
        else:
            print("No upcoming games in the next {} days.".format(args.days))
        return 0

    team_stats = get_team_season_stats()
    team_ids = set()
    for g in games:
        team_ids.add(g["home_team_id"])
        team_ids.add(g["away_team_id"])
    recent_form = {tid: get_recent_form(tid, RECENT_GAMES_N) for tid in team_ids}
    injuries = get_injuries()
    data_cache = {}
    player_last_game = get_player_last_game_dates(data_cache)
    augment_injuries_with_recent_games(injuries, team_ids, player_last_game)
    last_game_dates = {}

    ortg_drtg = get_team_ortg_drtg(data_cache)
    try:
        player_weights = get_player_stat_weights()
    except Exception:
        player_weights = {"PTS": 1.0, "AST": 0.5, "REB": 0.4, "STL": 0.6, "BLK": 0.6}

    results = []
    for g in games:
        home_days = get_rest_days(
            g["home_team_id"], g["game_date_est"], last_game_dates
        )
        away_days = get_rest_days(
            g["away_team_id"], g["game_date_est"], last_game_dates
        )
        rest = {"home_days": home_days, "away_days": away_days}

        avail_home, _ = get_available_player_value(
            g["home_team_id"], injuries.get(g["home_team_id"], []), data_cache, player_weights
        )
        avail_away, _ = get_available_player_value(
            g["away_team_id"], injuries.get(g["away_team_id"], []), data_cache, player_weights
        )

        win_home, win_away, pick_home = predict_game(
            g,
            team_stats,
            recent_form=recent_form,
            injuries=injuries,
            rest=rest,
            ortg_drtg=ortg_drtg,
            available_value_home=avail_home,
            available_value_away=avail_away,
        )
        pick_team = g["home_team_name"] if pick_home else g["away_team_name"]
        pick_pct = win_home if pick_home else win_away
        results.append({
            "game_id": g["game_id"],
            "game_date_est": g["game_date_est"],
            "away": f"{g['away_team_name']} ({g['away_tricode']})",
            "home": f"{g['home_team_name']} ({g['home_tricode']})",
            "win_pct_away": win_away,
            "win_pct_home": win_home,
            "pick": pick_team,
            "pick_win_pct": pick_pct,
        })

    if args.json:
        print(json.dumps({"games": results}, indent=2))
        return 0

    print("\n--- Upcoming games (next {} days) ---\n".format(args.days))
    for r in results:
        print("{} @ {}  |  {}  {}".format(
            r["away"], r["home"], r["game_date_est"] or "", r["game_id"]
        ))
        print("  Win%: Away {:.1%}  Home {:.1%}  →  Pick: {} ({:.1%})\n".format(
            r["win_pct_away"], r["win_pct_home"], r["pick"], r["pick_win_pct"]
        ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
