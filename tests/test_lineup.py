from companion.lineup import eligible, optimize, slot_positions
from companion.models import Player

RP = [("QB", 1), ("RB", 2), ("WR", 2), ("TE", 1), ("W/R/T", 1), ("BN", 4)]


def P(key, pos, proj, slot="BN", **kw):
    return Player(key=key, name=key, position=pos, eligible=[pos], nfl_team="KC", projection=proj,
                  selected_position=slot, **kw)


def test_slot_positions():
    assert slot_positions("W/R/T") == {"WR", "RB", "TE"}
    assert slot_positions("Q/W/R/T") == {"QB", "WR", "RB", "TE"}
    assert eligible(P("d", "DEF", 5), "DEF")


def test_benches_bye_and_out_players():
    roster = [P("qb", "QB", 20, "QB"), P("rb1", "RB", 15, "RB", on_bye=True), P("rb2", "RB", 12, "RB"),
              P("rb3", "RB", 9), P("wr1", "WR", 14, "WR", status="O"), P("wr2", "WR", 11, "WR"),
              P("wr3", "WR", 10), P("te", "TE", 8, "TE"), P("wr4", "WR", 7, "W/R/T")]
    res = optimize(roster, RP)
    starters = {p.key for _, p in res["slots"] if p}
    assert "rb1" not in starters and "wr1" not in starters
    assert {"qb", "rb2", "rb3", "wr2", "wr3", "te", "wr4"} == starters
    assert res["gain"] > 0
    assert any("BYE" in n["text"] for n in res["notes"])


def test_flex_takes_best_leftover_and_questionable_discount():
    roster = [P("qb", "QB", 20), P("rb1", "RB", 15), P("rb2", "RB", 14), P("rb3", "RB", 13),
              P("wr1", "WR", 12), P("wr2", "WR", 11), P("wr3", "WR", 12.5, status="Q"), P("te", "TE", 8)]
    res = optimize(roster, RP)
    flex = next(p for s, p in res["slots"] if s == "W/R/T")
    assert flex.key == "rb3"  # wr3 is 12.5 * 0.85 = 10.6 after the injury discount


def test_locked_players_stay_put():
    roster = [P("qb", "QB", 2, "QB", game_state="post"), P("qb2", "QB", 25), P("rb1", "RB", 10, "RB"),
              P("rb2", "RB", 10, "RB"), P("wr1", "WR", 10, "WR"), P("wr2", "WR", 10, "WR"), P("te", "TE", 5, "TE")]
    res = optimize(roster, RP)
    assert next(p for s, p in res["slots"] if s == "QB").key == "qb"


def test_latest_kickoff_goes_to_flex():
    roster = [P("qb", "QB", 20), P("rb1", "RB", 15, kickoff="2026-11-15T18:00:00Z"),
              P("rb2", "RB", 14, kickoff="2026-11-15T18:00:00Z"), P("rb3", "RB", 13, kickoff="2026-11-17T01:15:00Z"),
              P("wr1", "WR", 16, kickoff="2026-11-15T18:00:00Z"), P("wr2", "WR", 11, kickoff="2026-11-15T18:00:00Z"),
              P("te", "TE", 8)]
    res = optimize(roster, RP)
    assert next(p for s, p in res["slots"] if s == "W/R/T").key == "rb3"
    roster[3].projection = 16  # Monday-night RB is now the best RB but should still sit in FLEX
    res = optimize(roster, RP)
    assert next(p for s, p in res["slots"] if s == "W/R/T").key == "rb3"
