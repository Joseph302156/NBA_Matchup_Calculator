"""
Player-level stat projections for upcoming games.

This module is intentionally UI-agnostic: it just computes a mean and
an approximate distribution (variance) per stat, given:

- season-long per-game or per-minute averages
- recent N-game averages
- simple context flags (home/away, rest, opponent defensive strength)

The idea is to keep a transparent, tweakable model that we can adjust
with basketball intuition, not a black-box ML stack.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Literal, Optional, Tuple

from config import RECENT_STATS_GAMES, RECENT_STATS_WEIGHT

StatKey = Literal["pts", "reb", "ast", "stl", "blk", "min"]


@dataclass
class PlayerBaseStats:
    """Season + recent stats for one player, for a neutral context."""

    # Season-long per-game (or per-36) averages
    season_pts: float
    season_reb: float
    season_ast: float
    season_stl: float
    season_blk: float
    season_min: float

    # Recent N-game raw list of game-by-game lines (already filtered to last RECENT_STATS_GAMES)
    # Each entry: {"pts": float, "reb": float, ...}
    recent_games: list[Dict[str, float]]


@dataclass
class PlayerGameContext:
    """
    Lightweight game context knobs.

    These are kept deliberately simple and numeric so we can later map
    higher-level ideas (e.g. "slow defense", "usage bump without star")
    into small multiplicative adjustments.
    """

    is_home: bool = False
    # Pace multiplier relative to league average, e.g. 1.05 for slightly faster game
    pace_factor: float = 1.0
    # Opponent defensive adjustment for scoring-related stats
    # < 1.0 = tougher, > 1.0 = softer. Typically in [0.9, 1.1].
    scoring_def_factor: float = 1.0
    # Opponent rebounding environment; same semantics as scoring_def_factor
    reb_def_factor: float = 1.0
    # Usage bump due to injuries / role change, applied to scoring + assists
    # e.g. 1.10 when a high-usage teammate is out.
    usage_factor: float = 1.0
    # Minutes expectation multiplier relative to season average
    minutes_factor: float = 1.0
    # Games missed prior to this game (including injury DNPs).
    # 0 = no recent absence, 1–2 = light rust, 3–5 = moderate rust, >5 = heavy rust.
    games_missed: int = 0


def _recent_avg(recent_games: list[Dict[str, float]], key: StatKey) -> Optional[float]:
    if not recent_games:
        return None
    vals = [float(g.get(key, 0.0) or 0.0) for g in recent_games]
    if not vals:
        return None
    return sum(vals) / len(vals)


def _blend_season_and_recent(season_val: float, recent_val: Optional[float]) -> float:
    """
    Blend season-long and last-N-game averages.

    RECENT_STATS_WEIGHT is interpreted as the fraction of weight on the
    recent N games *when we have a full N-game window*. With fewer games,
    we taper that influence linearly down toward 0.
    """
    if recent_val is None:
        return float(season_val)
    w_recent_full = float(RECENT_STATS_WEIGHT)
    # With fewer than RECENT_STATS_GAMES games, reduce recent weight.
    # The caller is expected to only pass up to RECENT_STATS_GAMES entries.
    # For example: with 3 of 5 games available, recent gets 3/5 of its full weight.
    recent_count = len(recent_val if isinstance(recent_val, list) else [])  # type: ignore[arg-type]
    # Fallback: if we don't know count because we just passed a scalar, use full weight.
    if recent_count <= 0:
        w_recent = w_recent_full
    else:
        w_recent = w_recent_full * min(1.0, recent_count / float(RECENT_STATS_GAMES))
    w_season = 1.0 - w_recent
    return w_season * float(season_val) + w_recent * float(recent_val)  # type: ignore[operator]


def _project_single_stat(
    base: PlayerBaseStats,
    ctx: PlayerGameContext,
    stat: StatKey,
) -> Tuple[float, float]:
    """
    Project mean and stdev for a single counting stat.

    Returns (mean, stdev).
    """
    # 1) Neutral baseline from season + recent.
    season_val = getattr(base, f"season_{stat}")
    recent_val = _recent_avg(base.recent_games, stat)

    if recent_val is None:
        neutral = float(season_val)
    else:
        # For blending, we want access to the count; pass scalar and use full weight heuristic.
        neutral = (1.0 - RECENT_STATS_WEIGHT) * float(season_val) + RECENT_STATS_WEIGHT * float(
            recent_val
        )

    mean = neutral

    # 2) Contextual multipliers (all close to 1.0, so they are mild).
    # Minutes / role — sublinear response so a 13% minutes jump ≈ 10% stat jump.
    if stat in ("pts", "reb", "ast", "min"):
        mean *= ctx.minutes_factor ** 0.75

    # Usage bump for scoring + AST (e.g., star teammate out)
    if stat in ("pts", "ast"):
        mean *= ctx.usage_factor

    # Opponent defense / pace
    if stat == "pts":
        mean *= ctx.scoring_def_factor * ctx.pace_factor
    elif stat in ("reb", "stl", "blk"):
        mean *= ctx.reb_def_factor * ctx.pace_factor

    # Home court: small bump to scoring-related stats at home
    if ctx.is_home and stat in ("pts", "ast"):
        mean *= 1.03  # +3%

    # Rust from time away (including injury DNPs), not "extra rest".
    if ctx.games_missed > 0:
        gm = ctx.games_missed
        if gm == 1 or gm == 2:
            mean *= 0.95  # 1–2 games out → ~5% dip first game back
        elif 3 <= gm <= 5:
            mean *= 0.92  # 3–5 games out → ~8% dip
        elif gm > 5:
            mean *= 0.87  # 6+ games out → ~13% dip

    # 3) Distribution: simple variance model.
    # Empirically, NBA box-score stats are overdispersed vs Poisson;
    # as a starting point we set stdev ~ sqrt(mean * k) with k>1.
    if mean <= 0:
        stdev = 0.0
    else:
        if stat == "pts":
            stdev = (mean * 0.6) ** 0.5  # more volatile
        elif stat in ("reb", "ast"):
            stdev = (mean * 0.5) ** 0.5
        else:
            stdev = (mean * 0.4) ** 0.5

    return mean, stdev


def project_player_stats(
    base: PlayerBaseStats,
    ctx: Optional[PlayerGameContext] = None,
) -> Dict[StatKey, Dict[str, float]]:
    """
    High-level helper: project all supported stats for one player in a given game.

    Returns a mapping like:
    {
        "pts": {"mean": 24.3, "stdev": 5.1},
        "reb": {"mean": 8.7, "stdev": 2.4},
        ...
    }
    """
    ctx = ctx or PlayerGameContext()
    out: Dict[StatKey, Dict[str, float]] = {}
    for stat in ("pts", "reb", "ast", "stl", "blk", "min"):
        mu, sigma = _project_single_stat(base, ctx, stat)  # type: ignore[arg-type]
        out[stat] = {"mean": mu, "stdev": sigma}
    return out

