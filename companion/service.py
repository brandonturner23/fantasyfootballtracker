"""Orchestrates league + NFL data into one dashboard snapshot."""
from __future__ import annotations

import re
import threading
import time
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timezone

from .db import DB
from .lineup import NON_STARTING, optimize
from .models import FANTASY_POSITIONS, Player
from .research import defense_vs_position, form, report
from .trades import analyze


def norm_name(name: str) -> str:
    n = re.sub(r"[^a-z ]", "", name.lower())
    n = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", n)
    return " ".join(n.split())


class Companion:
    def __init__(self, db: DB, league, nfl, settings=None):
        self.db = db
        self.league = league
        self.nfl = nfl
        self.settings = settings
        self._lock = threading.Lock()
        self._memo: dict[int | None, tuple[float, dict, dict]] = {}

    # ------------------------------------------------------------- context
    def context(self, week: int | None = None, max_age: float = 60) -> dict:
        with self._lock:
            hit = self._memo.get(week)
            if hit and time.time() - hit[0] < max_age:
                return hit[2]
            ctx = self._build_context(week)
            self._memo[week] = (time.time(), {}, ctx)
            return ctx

    def invalidate(self) -> None:
        with self._lock:
            self._memo.clear()

    def _build_context(self, week: int | None) -> dict:
        now = datetime.now(timezone.utc)
        info = self.league.league_info()
        state = self.nfl.state()
        season = info.get("season") or state["season"]
        week = int(week or info.get("current_week") or state["week"])
        scoring = info.get("scoring", "ppr")
        last_week = max(info.get("end_week", 17), 18)

        nfl_players = self.nfl.players()
        by_yahoo = {p["yahoo_id"]: pid for pid, p in nfl_players.items() if p.get("yahoo_id")}
        by_name = {(norm_name(p["name"]), p["position"]): pid for pid, p in nfl_players.items()}

        # schedule: opponent, home/away, kickoff and live state per NFL team per week
        sched: dict[int, dict[str, dict]] = {}
        for w in range(1, min(week + 6, last_week) + 1):
            try:
                games = self.nfl.schedule(season, w)
            except Exception:
                games = []
            sched[w] = {}
            for g in games:
                for team, opp, home in ((g["home"], g["away"], True), (g["away"], g["home"], False)):
                    sched[w][team] = {"opp": opp, "home": home, "kickoff": g.get("kickoff"), "state": g.get("state", "pre")}

        # weekly fantasy points for every player (Sleeper scoring in the league's PPR format)
        weekly: dict[int, dict[str, dict]] = {}
        for w in range(1, week + 1):
            try:
                weekly[w] = self.nfl.stats(season, w, scoring, final=w < week)
            except Exception:
                weekly[w] = {}
        history: dict[str, dict[int, float]] = defaultdict(dict)
        for w, rows in weekly.items():
            for pid, row in rows.items():
                history[pid][w] = round(row["pts"], 2)
        try:
            proj = self.nfl.projections(season, week, scoring)
        except Exception:
            proj = {}
        dvp = defense_vs_position(
            {w: s for w, s in weekly.items() if w < week},
            {pid: p["position"] for pid, p in nfl_players.items()},
            {pid: p["team"] for pid, p in nfl_players.items()},
            {w: {t: v["opp"] for t, v in m.items()} for w, m in sched.items()},
        )
        try:
            trending = {r["id"]: r["count"] for r in self.nfl.trending("add", 24, 100)}
        except Exception:
            trending = {}

        pos_rank: dict[str, int] = {}
        by_pos: dict[str, list[tuple[float, str]]] = defaultdict(list)
        for pid, row in proj.items():
            pos = nfl_players.get(pid, {}).get("position")
            if pos:
                by_pos[pos].append((row["pts"], pid))
        for pos, rows in by_pos.items():
            for i, (_, pid) in enumerate(sorted(rows, reverse=True)):
                pos_rank[pid] = i + 1

        def enrich(p: Player) -> Player:
            if not p.nfl_id:
                yid = p.key.split(".p.")[-1] if ".p." in p.key else None
                p.nfl_id = by_yahoo.get(yid) or by_name.get((norm_name(p.name), p.position))
                if p.position == "DEF":
                    p.nfl_id = p.nfl_team
            info_ = nfl_players.get(p.nfl_id or "", {})
            if not p.status and info_.get("status"):
                p.status, p.injury_note = info_["status"], p.injury_note or info_.get("injury_note", "")
            p.projection = proj.get(p.nfl_id or "", {}).get("pts", 0.0)
            p.history = dict(history.get(p.nfl_id or "", {}))
            g = sched.get(week, {}).get(p.nfl_team)
            if g:
                p.opponent, p.home, p.kickoff, p.game_state = g["opp"], g["home"], g["kickoff"], g["state"]
                if p.game_state == "pre" and p.kickoff and _parse(p.kickoff) and _parse(p.kickoff) <= now:
                    p.game_state = "in"
                p.matchup_rank = dvp.get(p.position, {}).get(g["opp"])
                p.on_bye = False
            else:
                p.on_bye = bool(sched.get(week)) or p.bye_week == week
                p.game_state = "bye" if p.on_bye else p.game_state
            if p.bye_week is None:
                for w in range(1, last_week + 1):
                    if sched.get(w) and p.nfl_team and p.nfl_team not in sched[w]:
                        p.bye_week = w
                        break
            p.trending = trending.get(p.nfl_id or "", 0)
            return p

        teams = self.league.teams()
        team_names = {t["team_key"]: t["name"] for t in teams}
        my_team = info["my_team_key"]
        rosters = {t["team_key"]: [enrich(p) for p in self.league.roster(t["team_key"], week)] for t in teams}
        owned = {p.nfl_id for ps in rosters.values() for p in ps if p.nfl_id}

        available = []
        for pid, np_ in nfl_players.items():
            if pid in owned or np_["position"] not in FANTASY_POSITIONS or not np_.get("team"):
                continue
            if proj.get(pid, {}).get("pts", 0) < 3 and trending.get(pid, 0) == 0:
                continue
            p = Player(key=f"nfl.{pid}", name=np_["name"], position=np_["position"], eligible=[np_["position"]],
                       nfl_team=np_["team"], status=np_.get("status", ""), injury_note=np_.get("injury_note", ""),
                       nfl_id=pid)
            available.append(enrich(p))

        return {"info": info, "week": week, "season": season, "scoring": scoring, "sched": sched,
                "rosters": rosters, "available": available, "team_names": team_names, "teams": teams,
                "my_team": my_team, "pos_rank": pos_rank, "history": history, "nfl_players": nfl_players,
                "built_at": now.isoformat()}

    # ---------------------------------------------------------- dashboard
    def dashboard(self, week: int | None = None) -> dict:
        ctx = self.context(week)
        info, week, my_team = ctx["info"], ctx["week"], ctx["my_team"]
        mine = ctx["rosters"][my_team]
        rp = info["roster_positions"]

        lineup = optimize(mine, rp)
        analysis = analyze(ctx["rosters"], my_team, ctx["team_names"], rp, week, ctx["available"])
        values = analysis.pop("values")

        players = []
        for p in mine:
            d = p.to_dict()
            d["report"] = report(p, week, ctx["pos_rank"].get(p.nfl_id or ""))
            d["recommended_slot"] = lineup["assignments"].get(p.key)
            d["value"] = values.get(p.key)
            players.append(d)
        players.sort(key=lambda d: (_slot_order(d["recommended_slot"]), -d["projection"]))

        start = info.get("start_week", 1)
        end = info.get("end_week", 17)
        matchups = self.league.matchups(my_team, list(range(start, min(week, end) + 1)))
        standings = self.league.standings()
        weekly_breakdown = self._weekly_breakdown(ctx, start, min(week, end))

        current = next((m for m in matchups if m["week"] == week), None)
        me_row = next((s for s in standings if s["team_key"] == my_team), None)

        return {
            "league": {k: info.get(k) for k in ("league_key", "name", "season", "num_teams", "scoring", "url",
                                                 "start_week", "end_week", "current_week")},
            "week": week,
            "my_team": {"team_key": my_team, "name": ctx["team_names"].get(my_team), "standing": me_row},
            "matchup": current,
            "matchups": matchups,
            "standings": standings,
            "players": players,
            "lineup": {
                "slots": [{"slot": s, "player": _brief(p) if p else None} for s, p in lineup["slots"]],
                "bench": [_brief(p) for p in lineup["bench"]],
                "total": lineup["total"], "current_total": lineup["current_total"], "gain": lineup["gain"],
                "notes": lineup["notes"], "assignments": lineup["assignments"],
            },
            "game_day": self._game_day(mine, lineup["assignments"]),
            "bye_planner": self._bye_planner(ctx, values),
            "weekly_breakdown": weekly_breakdown,
            "trade": analysis,
            "watchlist": self._watchlist(ctx, values),
            "alerts": self.db.recent_alerts(30),
            "built_at": ctx["built_at"],
        }

    def player_detail(self, key: str, week: int | None = None) -> dict | None:
        ctx = self.context(week)
        for tk, ps in list(ctx["rosters"].items()) + [(None, ctx["available"])]:
            for p in ps:
                if p.key == key:
                    d = p.to_dict()
                    d["report"] = report(p, ctx["week"], ctx["pos_rank"].get(p.nfl_id or ""))
                    d["owner"] = ctx["team_names"].get(tk) if tk else "Free agent"
                    return d
        return None

    # ------------------------------------------------------------ helpers
    def _weekly_breakdown(self, ctx: dict, start: int, end: int) -> list[dict]:
        """Per week: points by position from starters, and points left on the bench."""
        out = []
        rp = ctx["info"]["roster_positions"]
        for w in range(start, end + 1):
            try:
                roster = self.league.roster(ctx["my_team"], w)
            except Exception:
                continue
            by_pos: dict[str, float] = defaultdict(float)
            started = 0.0
            for p in roster:
                nid = p.nfl_id or self._resolve(ctx, p)
                pts = ctx["history"].get(nid or "", {}).get(w, 0.0)
                p.projection, p.game_state, p.on_bye = pts, "pre", False
                if p.selected_position and p.selected_position not in NON_STARTING:
                    by_pos[p.position] += pts
                    started += pts
            best = optimize([replace(p, selected_position="BN") for p in roster], rp, score=lambda x: x.projection)["total"]
            out.append({"week": w, "by_position": {k: round(v, 2) for k, v in by_pos.items()},
                        "started": round(started, 2), "optimal": round(best, 2),
                        "left_on_bench": round(max(0.0, best - started), 2)})
        return out

    def _resolve(self, ctx: dict, p: Player) -> str | None:
        if p.position == "DEF":
            return p.nfl_team
        yid = p.key.split(".p.")[-1]
        for pid, np_ in ctx["nfl_players"].items():
            if np_.get("yahoo_id") == yid or (norm_name(np_["name"]) == norm_name(p.name) and np_["position"] == p.position):
                return pid
        return None

    def _game_day(self, players: list[Player], assignments: dict[str, str]) -> list[dict]:
        slots = defaultdict(list)
        for p in players:
            if p.on_bye or not p.kickoff:
                continue
            slot = assignments.get(p.key, "BN")
            slots[p.kickoff].append({"name": p.name, "position": p.position, "opponent": p.opponent, "home": p.home,
                                     "starting": slot not in NON_STARTING, "slot": slot, "state": p.game_state})
        return [{"kickoff": k, "players": v} for k, v in sorted(slots.items())]

    def _bye_planner(self, ctx: dict, values: dict[str, float]) -> list[dict]:
        info, week = ctx["info"], ctx["week"]
        mine = ctx["rosters"][ctx["my_team"]]
        rp = info["roster_positions"]
        out = []
        for w in range(week, min(week + 5, info.get("end_week", 17)) + 1):
            sched = ctx["sched"].get(w, {})
            on_bye = [p for p in mine if (sched and p.nfl_team and p.nfl_team not in sched) or (not sched and p.bye_week == w)]
            bye_keys = {p.key for p in on_bye}
            clones = [replace(p, game_state="pre", on_bye=p.key in bye_keys, selected_position="BN",
                              projection=values.get(p.key, 0.0), status="" if p.status in ("Q",) else p.status)
                      for p in mine]
            res = optimize(clones, rp)
            holes = [s for s, p in res["slots"] if p is None or p.on_bye or p.projection * p.injury_multiplier == 0]
            starters_on_bye = [p.name for p in on_bye if values.get(p.key, 0) >= 8]
            out.append({"week": w, "on_bye": [{"name": p.name, "position": p.position, "nfl_team": p.nfl_team} for p in on_bye],
                        "key_players_out": starters_on_bye, "holes": holes,
                        "projected_strength": res["total"]})
        return out

    def _watchlist(self, ctx: dict, values: dict[str, float]) -> list[dict]:
        out = []
        everyone = {p.key: (tk, p) for tk, ps in ctx["rosters"].items() for p in ps}
        everyone.update({p.key: (None, p) for p in ctx["available"]})
        for w in self.db.watchlist():
            tk, p = everyone.get(w["player_key"], (None, None))
            if not p:
                out.append({"key": w["player_key"], "name": w["name"], "missing": True})
                continue
            f = form(p.history, ctx["week"])
            out.append({"key": p.key, "name": p.name, "position": p.position, "nfl_team": p.nfl_team,
                        "status": p.status, "owner": ctx["team_names"].get(tk) if tk else "Free agent",
                        "projection": round(p.projection, 2), "last3_avg": f["last3_avg"],
                        "season_avg": f["season_avg"], "value": values.get(p.key), "trending": p.trending})
        return out


def _brief(p: Player) -> dict:
    return {"key": p.key, "name": p.name, "position": p.position, "nfl_team": p.nfl_team, "status": p.status,
            "projection": round(p.projection, 2), "opponent": p.opponent, "home": p.home, "kickoff": p.kickoff,
            "on_bye": p.on_bye, "locked": p.locked, "selected_position": p.selected_position,
            "matchup_rank": p.matchup_rank}


def _slot_order(slot: str | None) -> int:
    order = ["QB", "WR", "RB", "TE", "W/R/T", "W/R", "W/T", "Q/W/R/T", "K", "DEF", "BN", "IR"]
    return order.index(slot) if slot in order else 50


def _parse(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
