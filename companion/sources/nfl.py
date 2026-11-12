"""Public NFL data: Sleeper (players, injuries, projections, stats, trending) and ESPN (schedule).

Neither needs an API key. Responses are cached in SQLite so we stay polite.
"""
from __future__ import annotations

from typing import Any

import requests

from ..db import DB
from ..models import FANTASY_POSITIONS, norm_status, norm_team

SLEEPER = "https://api.sleeper.app/v1"
SLEEPER_WEB = "https://api.sleeper.com"
ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
SCORING_FIELD = {"ppr": "pts_ppr", "half": "pts_half_ppr", "std": "pts_std"}
POS_PARAMS = [("season_type", "regular")] + [("position[]", p) for p in FANTASY_POSITIONS]


class SleeperEspnSource:
    def __init__(self, db: DB, session: requests.Session | None = None):
        self.db = db
        self.http = session or requests.Session()
        self.http.headers.setdefault("User-Agent", "fantasy-companion/0.1")

    def _get(self, url: str, params: Any = None, ttl: float | None = 3600) -> Any:
        key = f"nfl:{url}?{params}"
        hit = self.db.cache_get(key, ttl)
        if hit is not None:
            return hit
        r = self.http.get(url, params=params, timeout=45)
        r.raise_for_status()
        data = r.json()
        self.db.cache_set(key, data)
        return data

    # ------------------------------------------------------------------ state
    def state(self) -> dict:
        s = self._get(f"{SLEEPER}/state/nfl", ttl=1800)
        week = int(s.get("display_week") or s.get("week") or 1)
        return {"season": int(s.get("season") or s.get("league_season")), "week": max(1, week),
                "season_type": s.get("season_type")}

    # ---------------------------------------------------------------- players
    def players(self) -> dict[str, dict]:
        raw = self._get(f"{SLEEPER}/players/nfl", ttl=12 * 3600)
        out = {}
        for pid, p in raw.items():
            pos = p.get("position")
            if pos not in FANTASY_POSITIONS:
                continue
            if pos != "DEF" and not p.get("team") and p.get("status") != "Active":
                continue
            name = p.get("full_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
            out[pid] = {
                "id": pid,
                "name": name,
                "position": pos,
                "team": norm_team(p.get("team")),
                "status": norm_status(p.get("injury_status")),
                "injury_note": " ".join(x for x in [p.get("injury_body_part"), p.get("injury_notes")] if x),
                "yahoo_id": str(p["yahoo_id"]) if p.get("yahoo_id") else None,
                "age": p.get("age"),
                "depth": p.get("depth_chart_order"),
            }
        return out

    # ------------------------------------------------- projections and stats
    @staticmethod
    def _points(data: Any, field: str) -> dict[str, dict]:
        """Accept both list ([{player_id, stats, opponent}]) and dict ({id: stats}) shapes."""
        out: dict[str, dict] = {}
        if isinstance(data, dict):
            for pid, stats in data.items():
                if isinstance(stats, dict) and field in stats:
                    out[pid] = {"pts": float(stats[field] or 0)}
        elif isinstance(data, list):
            for row in data:
                stats = row.get("stats") or {}
                pid = str(row.get("player_id"))
                if field in stats:
                    out[pid] = {"pts": float(stats[field] or 0), "opponent": norm_team(row.get("opponent")),
                                "team": norm_team(row.get("team"))}
        return out

    def _weekly(self, kind: str, season: int, week: int, scoring: str, ttl: float | None) -> dict[str, dict]:
        field = SCORING_FIELD.get(scoring, "pts_ppr")
        try:
            data = self._get(f"{SLEEPER_WEB}/{kind}/nfl/{season}/{week}", params=POS_PARAMS, ttl=ttl)
        except requests.RequestException:
            data = self._get(f"{SLEEPER}/{kind}/nfl/regular/{season}/{week}", ttl=ttl)
        return self._points(data, field)

    def projections(self, season: int, week: int, scoring: str) -> dict[str, dict]:
        return self._weekly("projections", season, week, scoring, ttl=3 * 3600)

    def stats(self, season: int, week: int, scoring: str, final: bool = True) -> dict[str, dict]:
        # finished weeks barely change; live weeks refresh every 10 minutes
        return self._weekly("stats", season, week, scoring, ttl=7 * 86400 if final else 600)

    # --------------------------------------------------------------- schedule
    def schedule(self, season: int, week: int) -> list[dict]:
        data = self._get(ESPN_SCOREBOARD, params={"seasontype": 2, "week": week, "dates": season}, ttl=1800)
        games = []
        for ev in data.get("events", []):
            comp = (ev.get("competitions") or [{}])[0]
            teams = {c.get("homeAway"): norm_team(c.get("team", {}).get("abbreviation")) for c in comp.get("competitors", [])}
            state = (comp.get("status") or ev.get("status") or {}).get("type", {}).get("state", "pre")
            games.append({"home": teams.get("home"), "away": teams.get("away"),
                          "kickoff": ev.get("date"), "state": state})
        return games

    # --------------------------------------------------------------- trending
    def trending(self, kind: str = "add", hours: int = 24, limit: int = 50) -> list[dict]:
        data = self._get(f"{SLEEPER}/players/nfl/trending/{kind}",
                         params={"lookback_hours": hours, "limit": limit}, ttl=1800)
        return [{"id": str(r["player_id"]), "count": int(r.get("count", 0))} for r in data]
