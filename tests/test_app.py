from fastapi.testclient import TestClient

from companion.app import create_app
from companion.config import Settings
from companion.db import DB
from companion.monitor import run_check
from companion.notifier import Notifier


def make_client():
    settings = Settings(demo_mode=True, db_path=":memory:", monitor_interval_minutes=0)
    app = create_app(settings, DB(":memory:"), start_monitor=False)
    return TestClient(app), app


def test_dashboard_end_to_end():
    client, _ = make_client()
    assert client.get("/api/status").json()["demo"] is True
    d = client.get("/api/dashboard").json()
    for key in ("players", "lineup", "matchups", "standings", "trade", "bye_planner", "weekly_breakdown", "game_day"):
        assert key in d
    assert d["lineup"]["slots"] and d["players"]
    assert d["lineup"]["gain"] > 0  # demo story: a starter on bye + one ruled out
    assert client.get(f"/api/player/{d['players'][0]['key']}").status_code == 200
    assert client.get("/").status_code == 200


def test_apply_lineup_and_watchlist():
    client, _ = make_client()
    before = client.get("/api/dashboard").json()["lineup"]
    assert client.post("/api/lineup/apply", json={}).json()["ok"]
    after = client.get("/api/dashboard?refresh=1").json()["lineup"]
    assert after["gain"] <= 0.01 and abs(after["current_total"] - before["total"]) < 0.01
    key = client.get("/api/dashboard").json()["trade"]["waivers"][0]["key"]
    client.post("/api/watchlist", json={"player_key": key, "name": "x"})
    assert client.get("/api/dashboard?refresh=1").json()["watchlist"][0]["key"] == key


def test_monitor_generates_and_dedupes_alerts():
    _, app = make_client()
    state = app.state.companion
    settings = Settings(demo_mode=True, monitor_interval_minutes=0)
    first = run_check(state.companion, settings, Notifier(settings))
    assert first["new_alerts"] > 0
    kinds = {a["kind"] for a in state.db.recent_alerts()}
    assert "lineup" in kinds
    assert run_check(state.companion, settings, Notifier(settings))["new_alerts"] == 0
