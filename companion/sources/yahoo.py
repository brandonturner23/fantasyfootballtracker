"""Yahoo Fantasy Sports: OAuth2 + API client + JSON parsing.

Yahoo's JSON format is notoriously nested: objects arrive as lists of single-key
dicts and collections as {"count": n, "0": {...}, "1": {...}}. The helpers
`flat`, `collection` and `find` normalise that into plain dicts.
"""
from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlencode
from xml.sax.saxutils import escape

import requests

from ..db import DB
from ..models import Player, norm_status, norm_team

AUTH_URL = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
API_BASE = "https://fantasysports.yahooapis.com/fantasy/v2"


# ---------------------------------------------------------------- JSON helpers
def flat(obj: Any) -> dict:
    """Merge Yahoo's list-of-dicts objects (possibly nested lists) into one dict."""
    if isinstance(obj, dict):
        return obj
    out: dict = {}
    for item in obj or []:
        if isinstance(item, list):
            out.update(flat(item))
        elif isinstance(item, dict):
            out.update(item)
    return out


def collection(container: Any, key: str) -> list:
    """Items of a Yahoo collection {"count": n, "0": {key: ...}, ...}, in order."""
    if isinstance(container, list):
        items = []
        for c in container:
            items.extend(collection(c, key))
        return items
    if not isinstance(container, dict):
        return []
    idx = sorted((int(k) for k in container if str(k).isdigit()))
    return [container[str(i)][key] for i in idx if isinstance(container[str(i)], dict) and key in container[str(i)]]


def find(obj: Any, key: str) -> Any:
    """Depth-first search for the first value stored under `key`."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            r = find(v, key)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = find(v, key)
            if r is not None:
                return r
    return None


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def parse_player(raw: Any) -> Player:
    info = flat(raw)
    name = info.get("name", {})
    full = name.get("full") if isinstance(name, dict) else str(name)
    eligible = [p.get("position") for p in info.get("eligible_positions", []) if isinstance(p, dict)]
    if isinstance(info.get("eligible_positions"), dict):  # single position edge case
        eligible = [info["eligible_positions"].get("position")]
    selected = flat(info.get("selected_position", [])).get("position")
    display = (info.get("display_position") or info.get("primary_position") or (eligible[0] if eligible else "")).split(",")[0]
    bye = info.get("bye_weeks", {})
    bye_week = int(bye["week"]) if isinstance(bye, dict) and str(bye.get("week", "")).isdigit() else None
    team = norm_team(info.get("editorial_team_abbr"))
    return Player(
        key=info.get("player_key", ""),
        name=full or "",
        position="DEF" if display in ("DEF", "D/ST", "DST") else display,
        eligible=[e for e in eligible if e],
        nfl_team=team,
        status=norm_status(info.get("status")),
        injury_note=info.get("injury_note", "") or "",
        bye_week=bye_week,
        selected_position=selected,
        nfl_id=team if display == "DEF" else None,
    )


def parse_roster(payload: dict, team_key: str) -> list[Player]:
    team = flat(payload["fantasy_content"]["team"])
    players = find(team.get("roster", {}), "players")
    out = []
    for raw in collection(players, "player"):
        p = parse_player(raw)
        p.fantasy_team_key = team_key
        out.append(p)
    return out


def parse_league_settings(payload: dict) -> dict:
    league = flat(payload["fantasy_content"]["league"])
    settings = flat(league.get("settings", []))
    positions = []
    for rp in settings.get("roster_positions", []):
        r = rp.get("roster_position", rp)
        positions.append((r.get("position"), int(r.get("count", 1))))
    rec_value = None
    for s in (find(settings.get("stat_modifiers", {}), "stats") or []):
        st = s.get("stat", s)
        if str(st.get("stat_id")) == "11":
            rec_value = _num(st.get("value"))
    scoring = "std"
    if rec_value is not None:
        scoring = "ppr" if rec_value >= 0.75 else "half" if rec_value >= 0.25 else "std"
    return {
        "league_key": league.get("league_key"),
        "name": league.get("name"),
        "season": int(league.get("season", 0) or 0),
        "current_week": int(league.get("current_week", 1) or 1),
        "start_week": int(league.get("start_week", 1) or 1),
        "end_week": int(league.get("end_week", 17) or 17),
        "num_teams": int(league.get("num_teams", 0) or 0),
        "roster_positions": positions,
        "scoring": scoring,
        "url": league.get("url"),
    }


def _team_summary(raw: Any) -> dict:
    t = flat(raw)
    managers = [flat(m.get("manager", m)) for m in (t.get("managers") or [])]
    logos = t.get("team_logos") or []
    logo = None
    if logos:
        logo = flat(logos[0].get("team_logo", {})).get("url") if isinstance(logos[0], dict) else None
    return {
        "team_key": t.get("team_key"),
        "name": t.get("name"),
        "manager": managers[0].get("nickname") if managers else None,
        "logo": logo,
        "is_mine": str(t.get("is_owned_by_current_login", "0")) == "1",
        "points": _num(flat(t.get("team_points", {})).get("total"), None) if t.get("team_points") else None,
        "projected": _num(flat(t.get("team_projected_points", {})).get("total"), None) if t.get("team_projected_points") else None,
        "standings": t.get("team_standings"),
    }


def parse_teams(payload: dict) -> list[dict]:
    league = flat(payload["fantasy_content"]["league"])
    return [_team_summary(raw) for raw in collection(find(league, "teams"), "team")]


def parse_standings(payload: dict) -> list[dict]:
    league = flat(payload["fantasy_content"]["league"])
    out = []
    for raw in collection(find(league.get("standings", []), "teams"), "team"):
        t = _team_summary(raw)
        st = t.pop("standings") or {}
        totals = st.get("outcome_totals", {})
        out.append({
            **{k: t[k] for k in ("team_key", "name", "manager", "logo", "is_mine")},
            "rank": int(st.get("rank") or 0) or None,
            "wins": int(totals.get("wins", 0) or 0),
            "losses": int(totals.get("losses", 0) or 0),
            "ties": int(totals.get("ties", 0) or 0),
            "points_for": _num(st.get("points_for")),
            "points_against": _num(st.get("points_against")),
        })
    out.sort(key=lambda r: (r["rank"] or 99))
    return out


def parse_matchups(payload: dict, team_key: str) -> list[dict]:
    team = flat(payload["fantasy_content"]["team"])
    out = []
    for m in collection(team.get("matchups", {}), "matchup"):
        teams = [_team_summary(raw) for raw in collection(find(m, "teams"), "team")]
        me = next((t for t in teams if t["team_key"] == team_key), None)
        opp = next((t for t in teams if t["team_key"] != team_key), None)
        if not me:
            continue
        out.append({
            "week": int(m.get("week", 0)),
            "status": m.get("status"),
            "points": me["points"],
            "projected": me["projected"],
            "opp_team_key": opp and opp["team_key"],
            "opp_name": opp and opp["name"],
            "opp_points": opp and opp["points"],
            "opp_projected": opp and opp["projected"],
        })
    return out


def lineup_xml(week: int, assignments: dict[str, str]) -> str:
    players = "".join(
        f"<player><player_key>{escape(k)}</player_key><position>{escape(pos)}</position></player>"
        for k, pos in assignments.items()
    )
    return (
        '<?xml version="1.0"?><fantasy_content><roster><coverage_type>week</coverage_type>'
        f"<week>{int(week)}</week><players>{players}</players></roster></fantasy_content>"
    )


# ---------------------------------------------------------------- OAuth
class YahooAuth:
    def __init__(self, client_id: str, client_secret: str, redirect_uri: str, db: DB):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri or "oob"
        self.db = db

    def authorize_url(self) -> str:
        return AUTH_URL + "?" + urlencode({
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "language": "en-us",
        })

    @property
    def tokens(self) -> dict | None:
        return self.db.get("yahoo_tokens")

    @property
    def authenticated(self) -> bool:
        return bool(self.tokens and self.tokens.get("refresh_token"))

    def _token_request(self, data: dict) -> dict:
        r = requests.post(TOKEN_URL, data=data, auth=(self.client_id, self.client_secret), timeout=20)
        if r.status_code != 200:
            raise RuntimeError(f"Yahoo token request failed ({r.status_code}): {r.text[:300]}")
        tok = r.json()
        tok["expires_at"] = time.time() + int(tok.get("expires_in", 3600)) - 60
        old = self.tokens or {}
        tok.setdefault("refresh_token", old.get("refresh_token"))
        self.db.set("yahoo_tokens", tok)
        return tok

    def exchange_code(self, code: str) -> dict:
        return self._token_request({
            "grant_type": "authorization_code",
            "redirect_uri": self.redirect_uri,
            "code": code.strip(),
        })

    def access_token(self) -> str:
        tok = self.tokens
        if not tok:
            raise PermissionError("Not connected to Yahoo yet")
        if time.time() >= tok.get("expires_at", 0):
            tok = self._token_request({
                "grant_type": "refresh_token",
                "redirect_uri": self.redirect_uri,
                "refresh_token": tok["refresh_token"],
            })
        return tok["access_token"]

    def logout(self) -> None:
        self.db.delete("yahoo_tokens")


# ---------------------------------------------------------------- League source
class YahooLeagueSource:
    """Implements the league-source interface against the Yahoo Fantasy API."""

    def __init__(self, auth: YahooAuth, db: DB, league_key: str | None = None):
        self.auth = auth
        self.db = db
        self._league_key = league_key

    # -- plumbing
    @property
    def league_key(self) -> str:
        key = self._league_key or self.db.get("league_key")
        if not key:
            leagues = self.leagues()
            if not leagues:
                raise RuntimeError("No Yahoo NFL leagues found for this account")
            key = leagues[0]["league_key"]
            self.db.set("league_key", key)
        return key

    def _get(self, path: str, ttl: float | None = 600) -> dict:
        cache_key = f"yahoo:{path}"
        if ttl:
            hit = self.db.cache_get(cache_key, ttl)
            if hit is not None:
                return hit
        r = requests.get(
            f"{API_BASE}/{path}",
            params={"format": "json"},
            headers={"Authorization": f"Bearer {self.auth.access_token()}"},
            timeout=30,
        )
        if r.status_code == 401:
            # force refresh once
            tok = self.auth.tokens or {}
            tok["expires_at"] = 0
            self.db.set("yahoo_tokens", tok)
            r = requests.get(f"{API_BASE}/{path}", params={"format": "json"},
                             headers={"Authorization": f"Bearer {self.auth.access_token()}"}, timeout=30)
        r.raise_for_status()
        data = r.json()
        if ttl:
            self.db.cache_set(cache_key, data)
        return data

    # -- interface
    def leagues(self) -> list[dict]:
        data = self._get("users;use_login=1/games;game_keys=nfl/leagues", ttl=3600)
        user = flat(find(data, "user"))
        out = []
        for g in collection(find(user, "games"), "game"):
            game = flat(g)
            for lg in collection(find(g, "leagues"), "league"):
                l = flat(lg)
                out.append({"league_key": l.get("league_key"), "name": l.get("name"),
                            "season": game.get("season") or l.get("season"), "num_teams": l.get("num_teams")})
        return out

    def league_info(self) -> dict:
        info = parse_league_settings(self._get(f"league/{self.league_key}/settings", ttl=3600))
        teams = self.teams()
        mine = next((t for t in teams if t["is_mine"]), None)
        info["my_team_key"] = mine["team_key"] if mine else (teams[0]["team_key"] if teams else None)
        return info

    def teams(self) -> list[dict]:
        return parse_teams(self._get(f"league/{self.league_key}/teams", ttl=3600))

    def standings(self) -> list[dict]:
        return parse_standings(self._get(f"league/{self.league_key}/standings", ttl=900))

    def roster(self, team_key: str, week: int) -> list[Player]:
        return parse_roster(self._get(f"team/{team_key}/roster;week={week}", ttl=600), team_key)

    def matchups(self, team_key: str, weeks: list[int]) -> list[dict]:
        if not weeks:
            return []
        w = ",".join(str(x) for x in weeks)
        return parse_matchups(self._get(f"team/{team_key}/matchups;weeks={w}", ttl=600), team_key)

    def set_lineup(self, team_key: str, week: int, assignments: dict[str, str]) -> None:
        r = requests.put(
            f"{API_BASE}/team/{team_key}/roster",
            data=lineup_xml(week, assignments),
            headers={"Authorization": f"Bearer {self.auth.access_token()}", "Content-Type": "application/xml"},
            timeout=30,
        )
        if r.status_code >= 300:
            raise RuntimeError(f"Yahoo rejected the lineup ({r.status_code}): {r.text[:400]}")
        self.db.cache_clear(f"yahoo:team/{team_key}/roster")
