from companion.models import Player
from companion.research import defense_vs_position, form, matchup_grade, report
from companion.trades import analyze

RP = [("QB", 1), ("RB", 2), ("WR", 2), ("TE", 1), ("W/R/T", 1), ("BN", 3)]


def P(key, pos, proj, hist, team="t1", **kw):
    return Player(key=key, name=key, position=pos, eligible=[pos], nfl_team="KC", projection=proj,
                  history=hist, fantasy_team_key=team, **kw)


def steady(v, n=9):
    return {w: v for w in range(1, n + 1)}


def test_form_and_report():
    f = form({1: 10, 2: 10, 3: 10, 4: 20, 5: 20, 6: 20}, 7)
    assert f["season_avg"] == 15 and f["last3_avg"] == 20 and f["trend"] == 5
    p = P("x", "WR", 18, {1: 10, 2: 10, 3: 10, 4: 20, 5: 20, 6: 20}, opponent="NYJ", matchup_rank=2, home=True)
    r = report(p, 7, pos_rank=5)
    assert "Hot" in r["tags"] and r["tier"] == "Must start" and "vs NYJ" in r["outlook"]
    assert matchup_grade(1) == "A" and matchup_grade(32) == "F"


def test_defense_vs_position_ranks_generous_defense_first():
    stats = {1: {"a": {"pts": 30, "opponent": "NYJ"}, "b": {"pts": 5, "opponent": "SF"}}}
    ranks = defense_vs_position(stats, {"a": "WR", "b": "WR"}, {}, {})
    assert ranks["WR"]["NYJ"] == 1 and ranks["WR"]["SF"] == 2


def _team(prefix, team, qb, rbs, wrs, te):
    return ([P(f"{prefix}qb", "QB", qb, steady(qb), team)] + [P(f"{prefix}rb{i}", "RB", v, steady(v), team) for i, v in enumerate(rbs)]
            + [P(f"{prefix}wr{i}", "WR", v, steady(v), team) for i, v in enumerate(wrs)] + [P(f"{prefix}te", "TE", te, steady(te), team)])


def test_trade_finds_mutually_useful_swap_and_sell_high():
    mine = _team("m", "t1", 20, [16, 15, 14, 13], [8, 7], 8)        # RB-rich, WR-poor
    theirs = _team("o", "t2", 20, [6, 5], [16, 15, 14, 13], 8)      # WR-rich, RB-poor
    hot = P("mhot", "WR", 6, {1: 5, 2: 5, 3: 5, 4: 5, 5: 5, 6: 5, 7: 14, 8: 15, 9: 16}, "t1")
    mine.append(hot)
    fa = [P("fa1", "WR", 12, steady(11), None, trending=20000)]
    res = analyze({"t1": mine, "t2": theirs}, "t1", {"t1": "Me", "t2": "Them"}, RP, 10, fa)
    assert res["proposals"], "expected an RB-for-WR trade idea"
    top = res["proposals"][0]
    assert top["give"]["position"] == "RB" and top["get"]["position"] == "WR" and top["my_gain"] > 0
    assert any(s["key"] == "mhot" for s in res["sell_high"])
    assert res["waivers"][0]["key"] == "fa1" and res["waivers"][0]["upgrade"] > 0
    assert next(n for n in res["needs"] if n["position"] == "WR")["delta"] < 0
