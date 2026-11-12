"""Turns the latest snapshot into alerts, de-duplicates them and pushes them out."""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from .lineup import NON_STARTING, optimize
from .notifier import Notifier
from .service import Companion

log = logging.getLogger(__name__)
STATUS_WORDS = {"": "healthy", "Q": "questionable", "D": "doubtful", "O": "OUT", "IR": "on IR",
                "PUP-R": "on PUP", "SUSP": "suspended", "NA": "inactive"}


def collect_alerts(companion: Companion, settings) -> int:
    """Generate alerts for the current week. Returns how many new alerts were stored."""
    db = companion.db
    companion.invalidate()
    ctx = companion.context()
    dash = companion.dashboard()
    week, my_team = ctx["week"], ctx["my_team"]
    mine = ctx["rosters"][my_team]
    new = 0

    def add(key, kind, title, msg, prio=3):
        nonlocal new
        if db.add_alert(key, kind, title, msg, prio):
            new += 1

    # 1. injury status changes on my roster
    prev = db.get(f"statuses:{my_team}", None)
    now_status = {p.key: p.status for p in mine}
    if prev is not None:
        for p in mine:
            old = prev.get(p.key)
            if old is not None and old != p.status:
                starter = p.selected_position not in NON_STARTING
                note = f" ({p.injury_note})" if p.injury_note else ""
                add(f"status:{p.key}:{old}->{p.status}:{week}", "injury",
                    f"{p.name}: {STATUS_WORDS.get(old, old)} → {STATUS_WORDS.get(p.status, p.status)}",
                    f"{p.name} ({p.position}, {p.nfl_team}) is now {STATUS_WORDS.get(p.status, p.status)}{note}."
                    + (" He's in your starting lineup." if starter else ""),
                    1 if starter and p.injury_multiplier == 0 else 2)
    db.set(f"statuses:{my_team}", now_status)

    # 2. lineup problems and suboptimal lineup
    for p in mine:
        if p.selected_position in NON_STARTING or p.locked:
            continue
        if p.on_bye:
            add(f"bye:{week}:{p.key}", "lineup", f"{p.name} is on bye",
                f"{p.name} is in your Week {week} lineup but his team is on bye. Swap him out.", 1)
        elif p.injury_multiplier == 0:
            add(f"out:{week}:{p.key}:{p.status}", "lineup", f"Starting an inactive player: {p.name}",
                f"{p.name} is {STATUS_WORDS.get(p.status, p.status)} and in your starting lineup.", 1)
    lineup = optimize(mine, ctx["info"]["roster_positions"])
    if lineup["gain"] >= settings.lineup_gain_alert:
        changes = [n["text"] for n in lineup["notes"] if n["level"] == "change"]
        sig = ",".join(sorted(f"{k}={v}" for k, v in lineup["assignments"].items() if v not in NON_STARTING))
        add(f"gain:{week}:{hash(sig) & 0xffffffff}", "lineup",
            f"Lineup tweak worth +{lineup['gain']:.1f} pts",
            "\n".join(changes[:6]) or "Open the dashboard to apply the recommended lineup.", 2)

    # 3. game-day reminder: first kickoff within 3 hours with issues
    nowdt = datetime.now(timezone.utc)
    for p in mine:
        if p.kickoff and p.game_state == "pre" and p.selected_position not in NON_STARTING and p.status in ("Q", "D"):
            ko = datetime.fromisoformat(p.kickoff.replace("Z", "+00:00"))
            hours = (ko - nowdt).total_seconds() / 3600
            if 0 < hours <= 3:
                add(f"gameday:{week}:{p.key}", "lineup", f"Inactives check: {p.name}",
                    f"{p.name} ({STATUS_WORDS.get(p.status)}) kicks off in {hours:.1f}h. Confirm he's active.", 1)

    # 4. waiver targets
    for w in dash["trade"]["waivers"][:5]:
        if w["trending"] >= settings.waiver_trend_min or (w["fills_need"] and w["value"] >= 8):
            why = f"added in {w['trending']:,} leagues today" if w["trending"] else "fills a weak spot"
            add(f"waiver:{week}:{w['key']}", "waiver", f"Waiver target: {w['name']} ({w['position']}, {w['nfl_team']})",
                f"{w['name']} is available in your league and {why}. Last 3 avg {w['last3_avg']:.1f}, "
                f"projected {w['projection']:.1f}." + (" Fills a positional need." if w["fills_need"] else ""), 3)

    # 5. trade ideas (weekly) and buy-low / sell-high
    for prop in dash["trade"]["proposals"][:2]:
        add(f"trade:{week}:{prop['give']['key']}:{prop['get']['key']}", "trade",
            f"Trade idea: {prop['give']['name']} → {prop['get']['name']}",
            f"Offer {prop['give']['name']} to {prop['team']} for {prop['get']['name']}. {prop['pitch']}", 3)
    for s in dash["trade"]["sell_high"][:2]:
        add(f"sell:{week}:{s['key']}", "trade", f"Sell-high window: {s['name']}", s["reason"], 3)
    for b in dash["trade"]["buy_low"][:2]:
        add(f"buy:{week}:{b['key']}", "trade", f"Buy-low target: {b['name']} ({b['team']})", b["reason"], 4)

    # 6. watchlist moves
    for w in dash["watchlist"]:
        if w.get("missing"):
            continue
        prev_w = db.get(f"watch:{w['key']}")
        cur = {"status": w["status"], "owner": w["owner"]}
        if prev_w and prev_w != cur:
            add(f"watch:{w['key']}:{cur['status']}:{cur['owner']}", "watch", f"Watchlist: {w['name']}",
                f"{w['name']} changed: status {STATUS_WORDS.get(prev_w['status'], prev_w['status'])} → "
                f"{STATUS_WORDS.get(cur['status'], cur['status'])}, owner {prev_w['owner']} → {cur['owner']}.", 2)
        db.set(f"watch:{w['key']}", cur)

    # 7. bye-week holes coming up
    for b in dash["bye_planner"][1:3]:
        if b["holes"]:
            add(f"byehole:{b['week']}", "bye", f"Week {b['week']} bye crunch",
                f"You can't fill {', '.join(b['holes'])} in Week {b['week']} "
                f"({', '.join(x['name'] for x in b['on_bye'])} on bye). Plan a pickup.", 3)
    return new


def dispatch(db, notifier: Notifier, dashboard_url: str | None = None) -> list[dict]:
    """Send all unsent alerts as one digest per channel."""
    pending = db.unsent_alerts()
    if not pending:
        return []
    if not notifier.channels:
        db.mark_sent([a["id"] for a in pending])  # nothing to send to; keep them on the dashboard only
        return pending
    top = min(a["priority"] for a in pending)
    title = pending[0]["title"] if len(pending) == 1 else f"{len(pending)} fantasy updates: {pending[0]['title']}"
    body = "\n\n".join(f"• {a['title']}\n{a['message']}" for a in pending)
    notifier.send(title, body, top, dashboard_url)
    db.mark_sent([a["id"] for a in pending])
    return pending


def run_check(companion: Companion, settings, notifier: Notifier, dashboard_url: str | None = None) -> dict:
    created = collect_alerts(companion, settings)
    sent = dispatch(companion.db, notifier, dashboard_url)
    return {"new_alerts": created, "sent": len(sent), "channels": notifier.channels}


class MonitorThread(threading.Thread):
    def __init__(self, companion: Companion, settings, notifier: Notifier, dashboard_url: str | None = None):
        super().__init__(daemon=True, name="fantasy-monitor")
        self.companion, self.settings, self.notifier = companion, settings, notifier
        self.dashboard_url = dashboard_url
        self.stop_event = threading.Event()

    def run(self) -> None:
        interval = max(5.0, self.settings.monitor_interval_minutes) * 60
        self.stop_event.wait(15)
        while not self.stop_event.is_set():
            try:
                res = run_check(self.companion, self.settings, self.notifier, self.dashboard_url)
                log.info("monitor check: %s", res)
            except PermissionError:
                log.info("monitor: waiting for Yahoo login")
            except Exception:
                log.exception("monitor check failed")
            self.stop_event.wait(interval)
