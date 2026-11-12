"""A self-contained fictional league + NFL season so the whole app runs with no accounts.

All player names are made up. It implements both the league-source interface
(like YahooLeagueSource) and the NFL-source interface (like SleeperEspnSource).
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from ..db import DB
from ..models import Player

NFL_TEAMS = ["ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET", "GB",
             "HOU", "IND", "JAX", "KC", "LAC", "LAR", "LV", "MIA", "MIN", "NE", "NO", "NYG",
             "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS"]
FIRST = ["Marcus", "Tyler", "Jalen", "Devin", "Andre", "Caleb", "Trey", "Darius", "Elijah", "Isaiah",
         "Jordan", "Malik", "Nate", "Omar", "Quinn", "Reggie", "Shawn", "Terrance", "Victor", "Wes",
         "Xavier", "Zion", "Brock", "Cody", "Dante", "Emmett", "Gavin", "Hunter", "Jace", "Kendall",
         "Logan", "Mason", "Nico", "Preston", "Roman", "Silas", "Tobias", "Ty", "Bryce", "Corey"]
LAST = ["Holloway", "Prescott", "Mabry", "Kincaid", "Okafor", "Delgado", "Whitfield", "Brennan",
        "Castillo", "Ashford", "Ruffin", "Pemberton", "Langley", "Odom", "Sutter", "Vance", "Merritt",
        "Calloway", "Fairbanks", "Gentry", "Hargrove", "Ingram", "Jessup", "Kearney", "Lockett",
        "Monroe", "Norwood", "Oakley", "Pruitt", "Quarles", "Radcliffe", "Stroud", "Tillman", "Underwood",
        "Vickers", "Waverly", "Yates", "Zeller", "Abbott", "Boone", "Crowder", "Dupree", "Ellis", "Forde"]
FANTASY_TEAMS = ["My Squad", "Gridiron Gurus", "Blitz Brigade", "End Zone Express", "Hail Mary Heroes",
                 "Pigskin Prophets", "Red Zone Rebels", "Fourth & Long", "Sunday Funday", "Waiver Wire Warriors"]
ROSTER_POSITIONS = [("QB", 1), ("WR", 2), ("RB", 2), ("TE", 1), ("W/R/T", 1), ("K", 1), ("DEF", 1),
                    ("BN", 6), ("IR", 1)]
# (position, players per NFL team, talent ranges by depth)
DEPTH = {"QB": [(16, 24), (5, 9)], "RB": [(10, 20), (5, 10), (2, 6), (1, 4)],
         "WR": [(11, 19), (8, 13), (5, 9), (2, 5), (1, 4)], "TE": [(6, 13), (2, 5)],
         "K": [(7, 10)], "DEF": [(5, 10)]}
REPLACEMENT = {"QB": 15, "RB": 6, "WR": 6, "TE": 5, "K": 8, "DEF": 7}
SEASON = 2026
SEASON_START = datetime(2026, 9, 10, tzinfo=timezone.utc)  # Thursday of week 1
LAST_REG_WEEK = 18
FANTASY_REG_WEEKS = 14


def demo_current_week(now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    week = (now - (SEASON_START - timedelta(days=2))).days // 7 + 1  # weeks roll over on Tuesday
    return max(1, min(LAST_REG_WEEK, week))


class DemoSource:
    def __init__(self, db: DB | None = None, seed: int = 23, now: datetime | None = None):
        self.db = db
        self.now = now or datetime.now(timezone.utc)
        self.week = demo_current_week(self.now)
        self.rng = random.Random(seed)
        self._build_players()
        self._draft()
        self._tune_story()
        self._build_schedule()
        self._simulate()

    # ------------------------------------------------------------ generation
    def _build_players(self) -> None:
        rng = self.rng
        self.p: dict[str, dict] = {}
        names = set()
        n = 1000
        for team in NFL_TEAMS:
            for pos, tiers in DEPTH.items():
                for depth, (lo, hi) in enumerate(tiers):
                    if pos == "DEF":
                        pid, name = team, f"{team} Defense"
                    else:
                        while True:
                            name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
                            if name not in names:
                                names.add(name)
                                break
                        n += 1
                        pid = str(n)
                    self.p[pid] = {"id": pid, "name": name, "position": pos, "team": team,
                                   "talent": rng.uniform(lo, hi), "depth": depth + 1, "status": "",
                                   "injury_note": "", "age": rng.randint(22, 33), "yahoo_id": pid,
                                   "breakout_week": None, "hot": False, "injured_weeks": set()}
        # a few breakouts (future waiver gems) and injuries
        pool = [p for p in self.p.values() if p["position"] in ("RB", "WR", "TE") and p["depth"] >= 2]
        for p in rng.sample(pool, 14):
            p["breakout_week"] = rng.randint(self.week - 3, self.week - 1)
            p["breakout_talent"] = p["talent"] + rng.uniform(6, 10)
        for p in self.p.values():
            if p["position"] == "DEF":
                continue
            r = rng.random()
            if r < 0.07:
                p["status"], p["injury_note"] = "Q", rng.choice(["Hamstring", "Ankle", "Knee", "Shoulder", "Illness"])
            elif r < 0.09:
                p["status"], p["injury_note"] = "D", rng.choice(["Hamstring", "Ankle", "Calf"])
            elif r < 0.115:
                p["status"], p["injury_note"] = "O", rng.choice(["Concussion", "Ankle", "Groin"])
            elif r < 0.13:
                p["status"], p["injury_note"] = "IR", rng.choice(["ACL", "Achilles", "Foot fracture"])
            if p["status"] in ("O", "IR"):
                first = self.week - (rng.randint(2, 5) if p["status"] == "IR" else 0)
                p["injured_weeks"] = set(range(max(1, first), self.week + (6 if p["status"] == "IR" else 1)))
        self.defense = {t: {pos: rng.uniform(0.78, 1.25) for pos in DEPTH} for t in NFL_TEAMS}

    def _value(self, p: dict) -> float:
        talent = p.get("breakout_talent", p["talent"]) if p["breakout_week"] else p["talent"]
        return talent - REPLACEMENT[p["position"]]

    def _draft(self) -> None:
        rng = self.rng
        caps = {"QB": 2, "RB": 5, "WR": 5, "TE": 2, "K": 1, "DEF": 1}
        self.team_keys = [f"demo.t.{i + 1}" for i in range(len(FANTASY_TEAMS))]
        self.rosters: dict[str, list[str]] = {k: [] for k in self.team_keys}
        # draft on pre-breakout talent so breakouts stay on waivers
        avail = sorted((p for p in self.p.values()), key=lambda p: -(p["talent"] - REPLACEMENT[p["position"]] + rng.gauss(0, 1.5)))
        rounds = 16
        for rnd in range(rounds):
            order = self.team_keys if rnd % 2 == 0 else list(reversed(self.team_keys))
            for tk in order:
                counts = {pos: 0 for pos in caps}
                for pid in self.rosters[tk]:
                    counts[self.p[pid]["position"]] += 1
                need_kdef = [pos for pos in ("K", "DEF") if counts[pos] == 0]
                must = need_kdef if rounds - rnd <= len(need_kdef) else None
                for p in avail:
                    pos = p["position"]
                    if must and pos not in must:
                        continue
                    if not must and pos in ("K", "DEF") and rnd < rounds - 3:
                        continue
                    if p["breakout_week"] and rnd < rounds - 1:
                        continue
                    if counts[pos] < caps[pos]:
                        self.rosters[tk].append(p["id"])
                        avail.remove(p)
                        break
        self.owner = {pid: tk for tk, pids in self.rosters.items() for pid in pids}
        self.my_team = self.team_keys[0]

    def _tune_story(self) -> None:
        """Make the demo interesting: a starter on bye, one ruled out, one on a hot streak."""
        rng = self.rng
        mine = [self.p[pid] for pid in self.rosters[self.my_team]]
        byes = list(range(5, 15))
        self.bye = {}
        teams = NFL_TEAMS[:]
        rng.shuffle(teams)
        for i, t in enumerate(teams):  # byes come in pairs so every week has an even team count
            self.bye[t] = byes[(i // 2) % len(byes)]
        for p in mine:  # start my roster healthy so the story below stays readable
            if p["status"] != "IR":
                p["status"], p["injury_note"], p["injured_weeks"] = "", "", set()
        healthy = [p for p in mine if p["status"] != "IR"]
        wrs = sorted([p for p in healthy if p["position"] == "WR"], key=lambda p: -p["talent"])
        rbs = sorted([p for p in healthy if p["position"] == "RB"], key=lambda p: -p["talent"])
        bye_guy = rbs[0] if rbs else None
        my_teams = {p["team"] for p in mine}
        if 5 <= self.week <= 14 and bye_guy:  # my RB1's team is on bye this week
            swap = next(t for t, w in self.bye.items() if w == self.week)
            self.bye[bye_guy["team"]], self.bye[swap] = self.bye[swap], self.bye[bye_guy["team"]]
        for t in list(my_teams):  # ...and nobody else on my roster is
            if bye_guy and t != bye_guy["team"] and self.bye[t] == self.week:
                swap = next(o for o in NFL_TEAMS if o not in my_teams and self.bye[o] != self.week)
                self.bye[t], self.bye[swap] = self.bye[swap], self.bye[t]
        if wrs:  # my WR1 got hurt in practice and is ruled out
            wrs[0].update(status="O", injury_note="Ankle", injured_weeks={self.week})
        hot = [p for p in wrs[2:] if not bye_guy or p["team"] != bye_guy["team"]]
        if hot:  # a depth WR on a heater: sell-high candidate
            hot[0]["hot"] = True
        qbs = [p for p in healthy if p["position"] == "QB"]
        if qbs:
            qbs[0].update(status="Q", injury_note="Shoulder")
        # a buy-low candidate on another team: strong talent, cold last 3 weeks
        others = [self.p[pid] for tk in self.team_keys[1:] for pid in self.rosters[tk]
                  if self.p[pid]["position"] in ("WR", "RB") and self.p[pid]["depth"] == 1]
        for p in rng.sample(others, min(3, len(others))):
            p["cold"] = True

    def _kickoffs(self, week: int, n_games: int) -> list[datetime]:
        thu = SEASON_START + timedelta(days=7 * (week - 1))
        sun = thu + timedelta(days=3)
        slots = [thu.replace(hour=1, minute=15) + timedelta(days=1)]  # TNF 8:15pm ET
        slots += [sun.replace(hour=18)] * max(0, n_games - 5)
        slots += [sun.replace(hour=21, minute=5), sun.replace(hour=21, minute=25)]
        slots += [sun.replace(hour=1, minute=20) + timedelta(days=1)]  # SNF
        slots += [sun.replace(hour=1, minute=15) + timedelta(days=2)]  # MNF
        return sorted(slots[:n_games])

    def _build_schedule(self) -> None:
        rng = self.rng
        self.games: dict[int, list[dict]] = {}
        for week in range(1, LAST_REG_WEEK + 1):
            teams = [t for t in NFL_TEAMS if self.bye[t] != week]
            rng.shuffle(teams)
            pairs = [(teams[i], teams[i + 1]) for i in range(0, len(teams) - 1, 2)]
            kicks = self._kickoffs(week, len(pairs))
            games = []
            for (home, away), ko in zip(pairs, kicks):
                if self.now >= ko + timedelta(hours=3, minutes=30):
                    state = "post"
                elif self.now >= ko:
                    state = "in"
                else:
                    state = "pre"
                games.append({"home": home, "away": away, "kickoff": ko.isoformat().replace("+00:00", "Z"),
                              "state": state})
            self.games[week] = games
        self.opp: dict[int, dict[str, str]] = {}
        self.state_of: dict[int, dict[str, str]] = {}
        for w, games in self.games.items():
            self.opp[w] = {}
            self.state_of[w] = {}
            for g in games:
                self.opp[w][g["home"]], self.opp[w][g["away"]] = g["away"], g["home"]
                self.state_of[w][g["home"]] = self.state_of[w][g["away"]] = g["state"]

    def _talent(self, p: dict, week: int) -> float:
        t = p["talent"]
        if p["breakout_week"] and week >= p["breakout_week"]:
            t = p["breakout_talent"]
        return t

    def _simulate(self) -> None:
        rng = self.rng
        self.actual: dict[int, dict[str, float]] = {}
        self.proj: dict[int, dict[str, dict]] = {}
        for week in range(1, LAST_REG_WEEK + 1):
            self.actual[week], self.proj[week] = {}, {}
            for pid, p in self.p.items():
                opp = self.opp[week].get(p["team"])
                if not opp:
                    continue
                factor = self.defense[opp][p["position"]]
                talent = self._talent(p, week)
                proj_talent = p["talent"] if (p["breakout_week"] and week < p["breakout_week"] + 1) else talent
                pts_proj = proj_talent * factor
                self.proj[week][pid] = {"pts": round(max(0, pts_proj), 2), "opponent": opp}
                if week in p["injured_weeks"]:
                    self.proj[week][pid]["pts"] = 0.0
                state = self.state_of[week].get(p["team"], "pre")
                if week > self.week or (week == self.week and state == "pre"):
                    continue
                if week in p["injured_weeks"]:
                    pts = 0.0
                else:
                    mult = 1.0
                    if p.get("hot") and week >= self.week - 4:
                        mult = 2.0
                    if p.get("cold") and week >= self.week - 3:
                        mult = 0.45
                    sd = 0.45 if p["position"] in ("WR", "TE", "DEF") else 0.35
                    pts = talent * factor * mult * max(0.0, rng.gauss(1.0, sd))
                    if p["position"] == "DEF" and rng.random() < 0.15:
                        pts -= rng.uniform(0, 4)
                if week == self.week and state == "in":
                    pts *= 0.5
                self.actual[week][pid] = round(pts, 2)
        self.trend = []
        for p in self.p.values():
            if p["id"] in self.owner:
                continue
            if p["breakout_week"]:
                self.trend.append({"id": p["id"], "count": rng.randint(9000, 60000)})
            elif rng.random() < 0.04:
                self.trend.append({"id": p["id"], "count": rng.randint(300, 4000)})
        self.trend.sort(key=lambda r: -r["count"])
        self._fantasy_results()

    def _fantasy_results(self) -> None:
        from ..lineup import optimize  # local import avoids a cycle

        self.results: dict[int, dict[str, float]] = {}
        self.proj_totals: dict[int, dict[str, float]] = {}
        self.lineups: dict[int, dict[str, dict[str, str]]] = {}
        n = len(self.team_keys)
        rot = self.team_keys[1:]
        self.pairings: dict[int, list[tuple[str, str]]] = {}
        for week in range(1, FANTASY_REG_WEEKS + 1):
            r = rot[(week - 1) % (n - 1):] + rot[:(week - 1) % (n - 1)]
            order = [self.team_keys[0]] + r
            self.pairings[week] = [(order[i], order[n - 1 - i]) for i in range(n // 2)]
        for week in range(1, min(self.week, FANTASY_REG_WEEKS) + 1):
            self.results[week], self.proj_totals[week], self.lineups[week] = {}, {}, {}
            for tk in self.team_keys:
                basis_week = week - 1 if (tk == self.my_team and week == self.week) else week
                players = self._players_for(tk, max(1, basis_week))
                rec = optimize(players, ROSTER_POSITIONS)
                assign = {p.key: slot for slot, p in rec["slots"]}
                for p in players:
                    assign.setdefault(p.key, "BN")
                self.lineups[week][tk] = assign
                starters = [pid for pid in self.rosters[tk] if assign.get(f"demo.p.{pid}") not in ("BN", "IR")]
                self.results[week][tk] = round(sum(self.actual[week].get(pid, 0) for pid in starters), 2)
                self.proj_totals[week][tk] = round(sum(self.proj[week].get(pid, {}).get("pts", 0) for pid in starters), 2)

    def _players_for(self, team_key: str, week: int) -> list[Player]:
        out = []
        for pid in self.rosters[team_key]:
            p = self.player_obj(pid, team_key)
            if week != self.week and week not in self.p[pid]["injured_weeks"]:
                p.status = ""  # past weeks: today's injury report didn't exist yet
            proj = self.proj.get(week, {}).get(pid, {}).get("pts", 0.0)
            on_bye = self.bye[p.nfl_team] == week
            out.append(_with(p, projection=0 if on_bye else proj, on_bye=on_bye))
        return out

    def player_obj(self, pid: str, team_key: str | None = None) -> Player:
        p = self.p[pid]
        return Player(key=f"demo.p.{pid}", name=p["name"], position=p["position"],
                      eligible=[p["position"]], nfl_team=p["team"], status=p["status"],
                      injury_note=p["injury_note"], bye_week=self.bye[p["team"]], nfl_id=pid,
                      fantasy_team_key=team_key)

    # --------------------------------------------------- league interface
    def leagues(self) -> list[dict]:
        return [{"league_key": "demo.l.1", "name": "Demo League", "season": SEASON, "num_teams": len(self.team_keys)}]

    def league_info(self) -> dict:
        return {"league_key": "demo.l.1", "name": "Demo League (sample data)", "season": SEASON,
                "current_week": self.week, "start_week": 1, "end_week": 17, "num_teams": len(self.team_keys),
                "roster_positions": ROSTER_POSITIONS, "scoring": "ppr", "url": None,
                "my_team_key": self.my_team}

    def teams(self) -> list[dict]:
        return [{"team_key": tk, "name": FANTASY_TEAMS[i], "manager": "You" if i == 0 else f"Manager {i + 1}",
                 "logo": None, "is_mine": i == 0} for i, tk in enumerate(self.team_keys)]

    def standings(self) -> list[dict]:
        rec = {tk: {"wins": 0, "losses": 0, "ties": 0, "pf": 0.0, "pa": 0.0} for tk in self.team_keys}
        for week, res in self.results.items():
            if week >= self.week:
                continue
            for a, b in self.pairings[week]:
                pa, pb = res[a], res[b]
                rec[a]["pf"] += pa; rec[a]["pa"] += pb; rec[b]["pf"] += pb; rec[b]["pa"] += pa
                if pa > pb:
                    rec[a]["wins"] += 1; rec[b]["losses"] += 1
                elif pb > pa:
                    rec[b]["wins"] += 1; rec[a]["losses"] += 1
                else:
                    rec[a]["ties"] += 1; rec[b]["ties"] += 1
        teams = {t["team_key"]: t for t in self.teams()}
        rows = sorted(self.team_keys, key=lambda k: (-rec[k]["wins"], -rec[k]["pf"]))
        return [{"team_key": k, "name": teams[k]["name"], "manager": teams[k]["manager"], "logo": None,
                 "is_mine": teams[k]["is_mine"], "rank": i + 1, "wins": rec[k]["wins"], "losses": rec[k]["losses"],
                 "ties": rec[k]["ties"], "points_for": round(rec[k]["pf"], 2), "points_against": round(rec[k]["pa"], 2)}
                for i, k in enumerate(rows)]

    def _saved_lineup(self, team_key: str, week: int) -> dict[str, str] | None:
        if self.db is None:
            return None
        return self.db.get(f"demo_lineup:{team_key}:{week}")

    def roster(self, team_key: str, week: int) -> list[Player]:
        lineup = self._saved_lineup(team_key, week) or self.lineups.get(min(week, max(self.lineups)), {}).get(team_key, {})
        out = []
        for pid in self.rosters[team_key]:
            p = self.player_obj(pid, team_key)
            p.selected_position = lineup.get(p.key, "BN")
            out.append(p)
        return out

    def matchups(self, team_key: str, weeks: list[int]) -> list[dict]:
        names = {t["team_key"]: t["name"] for t in self.teams()}
        out = []
        for w in weeks:
            if w not in self.pairings:
                continue
            a, b = next(pair for pair in self.pairings[w] if team_key in pair)
            opp = b if a == team_key else a
            done = w < self.week
            out.append({
                "week": w, "status": "postevent" if done else ("midevent" if w == self.week else "preevent"),
                "points": self.results.get(w, {}).get(team_key) if w <= self.week else None,
                "projected": self.proj_totals.get(w, {}).get(team_key),
                "opp_team_key": opp, "opp_name": names[opp],
                "opp_points": self.results.get(w, {}).get(opp) if w <= self.week else None,
                "opp_projected": self.proj_totals.get(w, {}).get(opp),
            })
        return out

    def set_lineup(self, team_key: str, week: int, assignments: dict[str, str]) -> None:
        current = {p.key: p.selected_position for p in self.roster(team_key, week)}
        current.update(assignments)
        if self.db is not None:
            self.db.set(f"demo_lineup:{team_key}:{week}", current)

    # ----------------------------------------------------- NFL interface
    def state(self) -> dict:
        return {"season": SEASON, "week": self.week, "season_type": "regular"}

    def players(self) -> dict[str, dict]:
        return {pid: {k: p[k] for k in ("id", "name", "position", "team", "status", "injury_note", "yahoo_id", "age", "depth")}
                for pid, p in self.p.items()}

    def projections(self, season: int, week: int, scoring: str) -> dict[str, dict]:
        return self.proj.get(week, {})

    def stats(self, season: int, week: int, scoring: str, final: bool = True) -> dict[str, dict]:
        return {pid: {"pts": pts, "opponent": self.opp[week].get(self.p[pid]["team"])}
                for pid, pts in self.actual.get(week, {}).items()}

    def schedule(self, season: int, week: int) -> list[dict]:
        return self.games.get(week, [])

    def trending(self, kind: str = "add", hours: int = 24, limit: int = 50) -> list[dict]:
        if kind != "add":
            return []
        return self.trend[:limit]


def _with(p: Player, **kw) -> Player:
    for k, v in kw.items():
        setattr(p, k, v)
    return p
