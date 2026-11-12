"""Trade and waiver analysis across every roster in the league."""
from __future__ import annotations

import math
from dataclasses import replace

from .lineup import optimize
from .models import Player
from .research import form


def player_value(p: Player, week: int) -> float:
    """Rest-of-season weekly value: blend of this week's projection and recent production."""
    f = form(p.history, week)
    proj = p.projection if not p.on_bye else (f["season_avg"] or p.projection)
    if f["games"] == 0:
        v = proj
    else:
        v = 0.45 * proj + 0.35 * f["last3_avg"] + 0.20 * f["season_avg"]
    if p.status in ("IR", "PUP-R", "NFI-R"):
        v *= 0.35
    elif p.status in ("O", "SUSP"):
        v *= 0.75
    return round(v, 2)


def _lineup_value(players: list[Player], roster_positions, values: dict[str, float]) -> float:
    clones = [replace(p, game_state="pre", selected_position="BN") for p in players]
    return optimize(clones, roster_positions, score=lambda p: values.get(p.key, 0.0))["total"]


def position_strength(players: list[Player], roster_positions, values: dict[str, float]) -> dict[str, float]:
    clones = [replace(p, game_state="pre", selected_position="BN") for p in players]
    res = optimize(clones, roster_positions, score=lambda p: values.get(p.key, 0.0))
    out: dict[str, float] = {}
    for _, p in res["slots"]:
        if p:
            out[p.position] = round(out.get(p.position, 0) + values.get(p.key, 0), 2)
    return out


def analyze(rosters: dict[str, list[Player]], my_team: str, team_names: dict[str, str],
            roster_positions, week: int, available: list[Player], max_proposals: int = 6) -> dict:
    values = {p.key: player_value(p, week) for ps in rosters.values() for p in ps}
    values.update({p.key: player_value(p, week) for p in available})

    # --- positional needs
    strength = {tk: position_strength(ps, roster_positions, values) for tk, ps in rosters.items()}
    positions = sorted({pos for s in strength.values() for pos in s})
    needs = []
    for pos in positions:
        others = [s.get(pos, 0) for tk, s in strength.items()]
        avg = sum(others) / len(others) if others else 0
        mine = strength.get(my_team, {}).get(pos, 0)
        rank = 1 + sum(1 for o in others if o > mine)
        needs.append({"position": pos, "mine": mine, "league_avg": round(avg, 2),
                      "delta": round(mine - avg, 2), "rank": rank})
    needs.sort(key=lambda n: n["delta"])

    # --- 1-for-1 trade proposals that help both lineups
    mine = rosters.get(my_team, [])
    base_me = _lineup_value(mine, roster_positions, values)
    proposals = []
    for tk, theirs in rosters.items():
        if tk == my_team:
            continue
        base_them = _lineup_value(theirs, roster_positions, values)
        for give in mine:
            vg = values[give.key]
            if give.position in ("K", "DEF") or vg < 3:
                continue
            for get in theirs:
                vt = values[get.key]
                if get.position in ("K", "DEF") or vt < 3 or get.status in ("IR", "O"):
                    continue
                if abs(vg - vt) / max(vg, vt) > 0.35:
                    continue
                new_me = [p for p in mine if p.key != give.key] + [get]
                new_them = [p for p in theirs if p.key != get.key] + [give]
                gain_me = _lineup_value(new_me, roster_positions, values) - base_me
                gain_them = _lineup_value(new_them, roster_positions, values) - base_them
                if gain_me >= 1.0 and gain_them >= -0.25:
                    proposals.append({
                        "team_key": tk, "team": team_names.get(tk, tk),
                        "give": _brief(give, values), "get": _brief(get, values),
                        "my_gain": round(gain_me, 2), "their_gain": round(gain_them, 2),
                        "score": gain_me + 0.6 * max(gain_them, 0),
                        "pitch": (f"Your {give.position} depth for their {get.position}: you add "
                                  f"{gain_me:.1f} pts/week to your lineup"
                                  + (f", they add {gain_them:.1f}" if gain_them > 0.2 else ", roughly neutral for them") + "."),
                    })
    proposals.sort(key=lambda x: -x["score"])
    seen, picked = set(), []
    for prop in proposals:  # diversify: one proposal per player we give and per team
        if prop["give"]["key"] in seen or prop["get"]["key"] in seen:
            continue
        seen.update({prop["give"]["key"], prop["get"]["key"]})
        picked.append(prop)
        if len(picked) >= max_proposals:
            break

    # --- buy-low / sell-high
    sell_high, buy_low = [], []
    for tk, ps in rosters.items():
        for p in ps:
            f = form(p.history, week)
            if f["games"] < 4 or p.position in ("K", "DEF"):
                continue
            proj_now = f["season_avg"] if p.on_bye else p.projection
            if tk == my_team and p.injury_multiplier > 0.5 and f["last3_avg"] >= 1.25 * max(f["season_avg"], 1) and proj_now < 0.85 * f["last3_avg"]:
                sell_high.append({**_brief(p, values), "season_avg": f["season_avg"], "last3_avg": f["last3_avg"],
                                  "reason": f"Scoring {f['last3_avg']:.1f} lately vs {f['season_avg']:.1f} season avg, "
                                            f"but projections only expect {proj_now:.1f}. His value may never be higher."})
            if tk != my_team and f["season_avg"] >= 10 and f["last3_avg"] <= 0.75 * f["season_avg"] and p.injury_multiplier > 0.5:
                buy_low.append({**_brief(p, values), "team": team_names.get(tk, tk), "team_key": tk,
                                "season_avg": f["season_avg"], "last3_avg": f["last3_avg"],
                                "reason": f"Slumping ({f['last3_avg']:.1f} over last 3 vs {f['season_avg']:.1f} avg) but healthy; "
                                          f"his manager may sell cheap."})
    sell_high.sort(key=lambda x: -(x["last3_avg"] - x["season_avg"]))
    buy_low.sort(key=lambda x: -(x["season_avg"] - x["last3_avg"]))

    # --- waivers
    need_pos = {n["position"] for n in needs[:2] if n["delta"] < 0}
    # what a pickup would replace: my weakest starter at that position (flex counts for RB/WR/TE)
    clones = [replace(p, game_state="pre", selected_position="BN") for p in mine]
    my_lineup = optimize(clones, roster_positions, score=lambda p: values.get(p.key, 0.0))["slots"]
    weakest: dict[str, float] = {}
    for slot, p in my_lineup:
        if p:
            for pos in ({"RB", "WR", "TE"} if p.position in ("RB", "WR", "TE") and "/" in slot else {p.position}):
                weakest[pos] = min(weakest.get(pos, 1e9), values.get(p.key, 0.0))
    waivers = []
    for p in available:
        f = form(p.history, week)
        upgrade = values[p.key] - weakest.get(p.position, 0.0)
        if values[p.key] < 2 and p.trending < 1000:
            continue
        score = max(upgrade, -5) + 0.15 * values[p.key] + 1.2 * math.log10(max(p.trending, 1)) \
            + (1.5 if p.position in need_pos else 0)
        waivers.append({**_brief(p, values), "trending": p.trending, "last3_avg": f["last3_avg"],
                        "season_avg": f["season_avg"], "projection": round(p.projection, 2),
                        "upgrade": round(upgrade, 2), "fills_need": upgrade > 0,
                        "score": round(score, 2)})
    waivers.sort(key=lambda w: -w["score"])
    return {"needs": needs, "proposals": picked, "sell_high": sell_high[:5], "buy_low": buy_low[:8],
            "waivers": waivers[:15], "values": values}


def _brief(p: Player, values: dict[str, float]) -> dict:
    return {"key": p.key, "name": p.name, "position": p.position, "nfl_team": p.nfl_team,
            "status": p.status, "value": values.get(p.key, 0.0)}
