"""Lineup optimizer: best legal starting lineup from projections, byes, injuries and game locks."""
from __future__ import annotations

from typing import Callable, Iterable

from .models import Player

NON_STARTING = {"BN", "IR", "IR+", "NA"}
STATUS_LABEL = {"O": "OUT", "IR": "on IR", "SUSP": "suspended", "PUP-R": "on PUP", "NA": "inactive", "D": "doubtful"}
FLEX_LETTERS = {"Q": "QB", "W": "WR", "R": "RB", "T": "TE"}


def slot_positions(slot: str) -> set[str]:
    s = slot.upper()
    if s in ("D", "DEF", "D/ST", "DST"):
        return {"DEF"}
    if s == "OP":
        return {"QB", "RB", "WR", "TE"}
    if "/" in s:
        return {FLEX_LETTERS.get(part, part) for part in s.split("/")}
    return {s}


def is_flex(slot: str) -> bool:
    return len(slot_positions(slot)) > 1


def player_positions(p: Player) -> set[str]:
    pos = set(p.eligible or []) | {p.position}
    return {"DEF" if x in ("D/ST", "DST", "D") else x for x in pos if x}


def eligible(p: Player, slot: str) -> bool:
    return bool(player_positions(p) & slot_positions(slot))


def effective_points(p: Player) -> float:
    if p.on_bye:
        return 0.0
    return round(p.projection * p.injury_multiplier, 2)


def starting_slots(roster_positions: Iterable[tuple[str, int]]) -> list[str]:
    slots = []
    for pos, count in roster_positions:
        if pos not in NON_STARTING:
            slots.extend([pos] * int(count))
    # dedicated slots first, wider flex slots last (keeps output tidy)
    return sorted(slots, key=lambda s: len(slot_positions(s)))


def hungarian_max(weights: list[list[float]]) -> list[int]:
    """Assignment maximising total weight. rows <= cols. Returns col index for each row."""
    n, m = len(weights), len(weights[0]) if weights else 0
    if n == 0:
        return []
    INF = float("inf")
    cost = [[-w for w in row] for row in weights]
    u, v = [0.0] * (n + 1), [0.0] * (m + 1)
    p, way = [0] * (m + 1), [0] * (m + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [INF] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], INF, 0
            for j in range(1, m + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    result = [-1] * n
    for j in range(1, m + 1):
        if p[j]:
            result[p[j] - 1] = j - 1
    return result


def optimize(players: list[Player], roster_positions: list[tuple[str, int]],
             score: Callable[[Player], float] = effective_points) -> dict:
    """Return the optimal lineup plus human-readable notes about what to change."""
    slots = starting_slots(roster_positions)
    # players whose games have kicked off cannot move
    locked = [p for p in players if p.locked]
    fixed: list[tuple[str, Player]] = []
    open_slots = slots[:]
    for p in locked:
        if p.selected_position in open_slots:
            open_slots.remove(p.selected_position)
            fixed.append((p.selected_position, p))
    candidates = [p for p in players if not p.locked and p.selected_position not in ("IR", "IR+", "NA")
                  or (not p.locked and p.selected_position in ("IR", "IR+", "NA") and p.injury_multiplier > 0)]

    assigned: list[tuple[str, Player | None]] = list(fixed)
    if open_slots:
        width = max(len(candidates), len(open_slots))
        BIG = -1e6
        weights = []
        for slot in open_slots:
            row = []
            for j in range(width):
                if j < len(candidates):
                    c = candidates[j]
                    # tiny tie-breaker keeps players where they already are
                    row.append(score(c) + (0.001 if c.selected_position == slot else 0) if eligible(c, slot) else BIG)
                else:
                    row.append(BIG / 2)
            weights.append(row)
        picks = hungarian_max(weights)
        for slot, j in zip(open_slots, picks):
            ok = 0 <= j < len(candidates) and weights[open_slots.index(slot)][j] > BIG / 4
            assigned.append((slot, candidates[j] if ok else None))

    _late_flex_swap(assigned)
    order = {s: i for i, s in enumerate(dict.fromkeys(slots))}
    assigned.sort(key=lambda sp: order.get(sp[0], 99))
    starters = {p.key for _, p in assigned if p}
    bench = [p for p in players if p.key not in starters]
    total = round(sum(score(p) for _, p in assigned if p), 2)
    current = [p for p in players if p.selected_position and p.selected_position not in NON_STARTING]
    current_total = round(sum(score(p) for p in current), 2)

    assignments = {p.key: slot for slot, p in assigned if p}
    for p in bench:
        assignments[p.key] = p.selected_position if p.selected_position in ("IR", "IR+", "NA") else "BN"

    return {
        "slots": assigned,
        "bench": sorted(bench, key=lambda p: -score(p)),
        "total": total,
        "current_total": current_total,
        "gain": round(total - current_total, 2),
        "assignments": assignments,
        "notes": _notes(players, assigned, assignments, score, roster_positions),
    }


def _late_flex_swap(assigned: list[tuple[str, Player | None]]) -> None:
    """Put the latest-kickoff player in FLEX so you keep pivot options on game day."""
    for i, (fslot, f) in enumerate(assigned):
        if not f or f.locked or not is_flex(fslot) or not f.kickoff:
            continue
        for j, (dslot, d) in enumerate(assigned):
            if i == j or not d or d.locked or is_flex(dslot) or not d.kickoff:
                continue
            if eligible(d, fslot) and eligible(f, dslot) and d.kickoff > f.kickoff:
                assigned[i], assigned[j] = (fslot, d), (dslot, f)
                f = d


def _notes(players, assigned, assignments, score, roster_positions) -> list[dict]:
    notes = []
    by_key = {p.key: p for p in players}
    for p in players:
        cur = p.selected_position
        new = assignments.get(p.key)
        cur_start = cur and cur not in NON_STARTING
        new_start = new and new not in NON_STARTING
        if cur_start and p.on_bye:
            notes.append({"level": "critical", "text": f"{p.name} is on BYE this week but is in your starting lineup."})
        elif cur_start and p.injury_multiplier == 0:
            notes.append({"level": "critical", "text": f"{p.name} is {STATUS_LABEL.get(p.status, p.status or 'out')} — bench him."})
        elif cur_start and p.status in ("Q", "D"):
            notes.append({"level": "warning", "text": f"{p.name} is {'questionable' if p.status == 'Q' else 'doubtful'}"
                          f"{' (' + p.injury_note + ')' if p.injury_note else ''}. Check inactives before kickoff."})
        if p.locked and cur_start != bool(new_start):
            continue
        if new_start and not cur_start:
            notes.append({"level": "change", "text": f"Start {p.name} ({p.position}, {score(p):.1f} proj) at {new}."})
        elif cur_start and not new_start:
            notes.append({"level": "change", "text": f"Bench {p.name} ({score(p):.1f} proj)."})
        elif cur_start and new_start and cur != new:
            notes.append({"level": "info", "text": f"Move {p.name} from {cur} to {new}."})
    flex = [(s, p) for s, p in assigned if p and is_flex(s) and p.kickoff]
    for s, p in flex:
        notes.append({"level": "info", "text": f"{p.name} is in {s}: he kicks off latest among your eligible starters, "
                      "so you can still swap him for a bench player if news breaks."})
    has_ir = any(pos.startswith("IR") and c > 0 for pos, c in roster_positions)
    if has_ir:
        in_ir = [p for p in players if p.selected_position in ("IR", "IR+")]
        for p in players:
            if p.status in ("IR", "O", "PUP-R", "NFI-R") and p.selected_position == "BN" and len(in_ir) == 0:
                notes.append({"level": "info", "text": f"{p.name} ({p.status}) can go in your IR slot to open a bench spot for a waiver pickup."})
                break
    for slot, p in assigned:
        if p is None:
            notes.append({"level": "critical", "text": f"No healthy player available for {slot} — grab one off waivers."})
    return notes
