"""
Raise stats.nba.com read timeout for slow networks (e.g. GitHub Actions runners).

- If NBA_STATS_TIMEOUT_SECONDS is set: use at least that many seconds for every NBA stats request.
- Else if CI=true (GitHub Actions, etc.): default floor 90s (endpoints usually pass 30).
"""
from __future__ import annotations

import os

_applied = False


def apply_nba_stats_timeout_if_needed() -> None:
    global _applied
    if _applied:
        return

    raw = os.environ.get("NBA_STATS_TIMEOUT_SECONDS", "").strip()
    if raw:
        try:
            floor = max(30.0, float(raw))
        except ValueError:
            floor = 90.0
    elif os.environ.get("CI", "").lower() in ("true", "1", "yes"):
        floor = 90.0
    else:
        return

    from nba_api.stats.library.http import NBAStatsHTTP

    _orig = NBAStatsHTTP.send_api_request

    def _send(
        self,
        endpoint,
        parameters,
        referer=None,
        proxy=None,
        headers=None,
        timeout=None,
        raise_exception_on_error=False,
    ):
        use = floor if timeout is None else max(float(timeout), floor)
        return _orig(
            self,
            endpoint,
            parameters,
            referer=referer,
            proxy=proxy,
            headers=headers,
            timeout=use,
            raise_exception_on_error=raise_exception_on_error,
        )

    NBAStatsHTTP.send_api_request = _send  # type: ignore[method-assign]
    _applied = True
