from companion.sources.yahoo import (collection, flat, lineup_xml, parse_league_settings, parse_matchups,
                                     parse_roster, parse_standings)


def _player(key, name, team, pos, selected, status=None, bye=7, eligible=None):
    attrs = [{"player_key": key}, {"player_id": key.split(".")[-1]}, {"name": {"full": name}},
             {"editorial_team_abbr": team}, {"bye_weeks": {"week": str(bye)}}, {"display_position": pos},
             {"eligible_positions": [{"position": p} for p in (eligible or [pos])]}, []]
    if status:
        attrs.append({"status": status})
        attrs.append({"injury_note": "Hamstring"})
    return {"player": [attrs, {"selected_position": [{"coverage_type": "week"}, {"week": "10"}, {"position": selected}]}]}


ROSTER = {"fantasy_content": {"team": [
    [{"team_key": "461.l.1.t.3"}, {"name": "Mine"}],
    {"roster": {"coverage_type": "week", "week": "10", "0": {"players": {
        "0": _player("461.p.100", "Ace Quarterback", "Buf", "QB", "QB"),
        "1": _player("461.p.200", "Wide Out", "Wsh", "WR", "BN", "Q", eligible=["WR", "W/R/T"]),
        "2": _player("461.p.100003", "Buffalo", "Buf", "DEF", "DEF"),
        "count": 3}}}},
]}}


def test_flat_and_collection():
    assert flat([{"a": 1}, [{"b": 2}], []]) == {"a": 1, "b": 2}
    assert collection({"count": 2, "1": {"x": "b"}, "0": {"x": "a"}}, "x") == ["a", "b"]


def test_parse_roster():
    players = parse_roster(ROSTER, "461.l.1.t.3")
    assert [p.name for p in players] == ["Ace Quarterback", "Wide Out", "Buffalo"]
    qb, wr, d = players
    assert qb.selected_position == "QB" and qb.nfl_team == "BUF" and qb.bye_week == 7
    assert wr.status == "Q" and wr.nfl_team == "WAS" and "W/R/T" in wr.eligible and wr.injury_note == "Hamstring"
    assert d.position == "DEF" and d.nfl_id == "BUF"


def test_parse_settings():
    payload = {"fantasy_content": {"league": [
        {"league_key": "461.l.1", "name": "Office", "season": "2026", "current_week": "10", "end_week": "17", "num_teams": "12"},
        {"settings": [{"roster_positions": [{"roster_position": {"position": "QB", "count": 1}},
                                            {"roster_position": {"position": "W/R/T", "count": "2"}},
                                            {"roster_position": {"position": "BN", "count": 6}}],
                       "stat_modifiers": {"stats": [{"stat": {"stat_id": 11, "value": "0.5"}}]}}]},
    ]}}
    info = parse_league_settings(payload)
    assert info["roster_positions"] == [("QB", 1), ("W/R/T", 2), ("BN", 6)]
    assert info["scoring"] == "half" and info["current_week"] == 10 and info["num_teams"] == 12


def _team(key, name, pts=None, proj=None, mine=False, standings=None):
    extra = {}
    if pts is not None:
        extra["team_points"] = {"total": str(pts)}
        extra["team_projected_points"] = {"total": str(proj)}
    if standings:
        extra["team_standings"] = standings
    return {"team": [[{"team_key": key}, {"name": name}, {"is_owned_by_current_login": 1 if mine else 0}], extra]}


def test_parse_matchups_and_standings():
    payload = {"fantasy_content": {"team": [[{"team_key": "t1"}], {"matchups": {"count": 1, "0": {"matchup": {
        "week": "3", "status": "postevent",
        "0": {"teams": {"count": 2, "0": _team("t1", "Me", 120.5, 110, True), "1": _team("t2", "Them", 99, 105)}}}}}}]}}
    m = parse_matchups(payload, "t1")[0]
    assert m["week"] == 3 and m["points"] == 120.5 and m["opp_name"] == "Them" and m["opp_points"] == 99

    st = {"fantasy_content": {"league": [{"league_key": "l"}, {"standings": [{"teams": {"count": 2,
        "0": _team("t2", "Them", standings={"rank": "2", "outcome_totals": {"wins": 3, "losses": 6}, "points_for": "900"}),
        "1": _team("t1", "Me", mine=True, standings={"rank": "1", "outcome_totals": {"wins": 6, "losses": 3}, "points_for": "1000"})}}]}]}}
    rows = parse_standings(st)
    assert rows[0]["name"] == "Me" and rows[0]["wins"] == 6 and rows[0]["is_mine"]


def test_lineup_xml():
    xml = lineup_xml(10, {"461.p.1": "QB", "461.p.2": "BN"})
    assert "<week>10</week>" in xml and "<player_key>461.p.1</player_key><position>QB</position>" in xml
