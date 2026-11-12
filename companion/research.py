"""Player research: form, consistency, matchup strength and a plain-English outlook."""
from __future__ import annotations

import statistics
from collections import defaultdict

from .models import FANTASY_POSITIONS, Player


def defense_vs_position(weekly_stats: dict[int, dict[str, dict]], player_pos: dict[str, str],
                        player_team: dict[str, str], opponents: dict[int, dict[str, str]]) -> dict[str, dict[str, int]]:
    """Rank each NFL defense by fantasy points allowed per game to each position.

    Returns {position: {team: rank}} where rank 1 = allows the MOST points (easiest matchup).
    """
    allowed: dict[str, dict[str, list[float]]] = {pos: defaultdict(list) for pos in FANTASY_POSITIONS}
    for week, stats in weekly_stats.items():
        per: dict[tuple[str, str], float] = defaultdict(float)
        for pid, row in stats.items():
            pos = player_pos.get(pid)
            if not pos:
                continue
            opp = row.get("opponent") or opponents.get(week, {}).get(row.get("team") or player_team.get(pid, ""))
            if opp:
                per[(pos, opp)] += row["pts"]
        for (pos, opp), pts in per.items():
            allowed[pos][opp].append(pts)
    ranks: dict[str, dict[str, int]] = {}
    for pos, teams in allowed.items():
        avg = {t: sum(v) / len(v) for t, v in teams.items() if v}
        ranks[pos] = {t: i + 1 for i, (t, _) in enumerate(sorted(avg.items(), key=lambda kv: -kv[1]))}
    return ranks


def matchup_grade(rank: int | None, n: int = 32) -> str:
    if not rank:
        return "–"
    pct = rank / n
    return "A" if pct <= 0.2 else "B" if pct <= 0.4 else "C" if pct <= 0.6 else "D" if pct <= 0.8 else "F"


def form(history: dict[int, float], before_week: int) -> dict:
    played = [history[w] for w in sorted(history) if w < before_week]
    if not played:
        return {"games": 0, "season_avg": 0.0, "last3_avg": 0.0, "trend": 0.0, "stdev": 0.0,
                "floor": 0.0, "ceiling": 0.0, "consistency": None}
    last3 = played[-3:]
    season_avg = sum(played) / len(played)
    last3_avg = sum(last3) / len(last3)
    sd = statistics.pstdev(played) if len(played) > 1 else 0.0
    srt = sorted(played)
    floor = srt[max(0, int(len(srt) * 0.2) - 1)] if len(srt) >= 3 else srt[0]
    ceiling = srt[min(len(srt) - 1, int(len(srt) * 0.8))]
    # share of weeks within ±35% of the average
    consistency = sum(1 for x in played if abs(x - season_avg) <= 0.35 * max(season_avg, 1)) / len(played)
    return {"games": len(played), "season_avg": round(season_avg, 2), "last3_avg": round(last3_avg, 2),
            "trend": round(last3_avg - season_avg, 2), "stdev": round(sd, 2), "floor": round(floor, 2),
            "ceiling": round(ceiling, 2), "consistency": round(consistency, 2)}


def tier(p: Player, pos_rank: int | None) -> str:
    if p.on_bye:
        return "Bye"
    if p.injury_multiplier == 0:
        return "Out"
    if pos_rank is None:
        return "Bench"
    cut = {"QB": (6, 12), "RB": (12, 24), "WR": (12, 30), "TE": (5, 12), "K": (6, 12), "DEF": (6, 12)}
    elite, startable = cut.get(p.position, (12, 24))
    return "Must start" if pos_rank <= elite else "Start" if pos_rank <= startable else "Flex/Sit"


def report(p: Player, week: int, pos_rank: int | None = None) -> dict:
    f = form(p.history, week)
    tags = []
    if p.on_bye:
        tags.append("Bye")
    if p.status:
        tags.append(p.status)
    if f["games"] >= 3 and f["trend"] >= max(3, 0.25 * f["season_avg"]):
        tags.append("Hot")
    if f["games"] >= 3 and f["trend"] <= -max(3, 0.25 * f["season_avg"]):
        tags.append("Cold")
    if f["games"] >= 4 and f["season_avg"] > 0 and f["stdev"] / max(f["season_avg"], 1) > 0.6:
        tags.append("Boom/Bust")
    if p.trending >= 5000:
        tags.append("Trending")
    grade = matchup_grade(p.matchup_rank)
    if grade in ("A",) and not p.on_bye:
        tags.append("Smash spot")
    t = tier(p, pos_rank)
    return {
        **f,
        "projection": round(p.projection, 2),
        "matchup_grade": grade,
        "matchup_rank": p.matchup_rank,
        "pos_rank": pos_rank,
        "tier": t,
        "tags": tags,
        "outlook": outlook(p, f, grade, t, pos_rank),
    }


def outlook(p: Player, f: dict, grade: str, t: str, pos_rank: int | None) -> str:
    if p.on_bye:
        return f"{p.name} is on bye this week. Slide in a replacement."
    if p.injury_multiplier == 0:
        note = f" ({p.injury_note})" if p.injury_note else ""
        return f"{p.name} is listed {p.status}{note} and won't play. Don't start him."
    bits = []
    opp = f"{'vs' if p.home else '@'} {p.opponent}" if p.opponent else "this week"
    rank_txt = f", {p.position}{pos_rank} this week" if pos_rank else ""
    bits.append(f"Projected {p.projection:.1f} pts {opp}{rank_txt}.")
    if grade in ("A", "B"):
        bits.append(f"Favourable matchup: this defense ranks #{p.matchup_rank} in points allowed to {p.position}s.")
    elif grade in ("D", "F"):
        bits.append(f"Tough matchup: #{p.matchup_rank} of 32 against {p.position}s. Temper expectations.")
    if f["games"]:
        if f["trend"] >= max(3, 0.25 * f["season_avg"]):
            bits.append(f"Heating up: {f['last3_avg']:.1f} ppg over the last 3 vs {f['season_avg']:.1f} on the season.")
        elif f["trend"] <= -max(3, 0.25 * f["season_avg"]):
            bits.append(f"Cooling off: {f['last3_avg']:.1f} ppg over the last 3 vs {f['season_avg']:.1f} on the season.")
        else:
            bits.append(f"Averaging {f['season_avg']:.1f} ppg (floor {f['floor']:.1f}, ceiling {f['ceiling']:.1f}).")
    if p.status in ("Q", "D"):
        bits.append(f"Listed {'questionable' if p.status == 'Q' else 'doubtful'}"
                    f"{' with a ' + p.injury_note.lower() + ' issue' if p.injury_note else ''}; have a backup ready.")
    if p.trending >= 5000:
        bits.append(f"Added in {p.trending:,} leagues in the last day.")
    bits.append(f"Verdict: {t}.")
    return " ".join(bits)
