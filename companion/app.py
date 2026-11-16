"""FastAPI web app: dashboard, Yahoo login, JSON API and background monitor."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import Settings
from .db import DB
from .monitor import MonitorThread, run_check
from .notifier import Notifier
from .service import Companion
from .sources.demo import DemoSource
from .sources.nfl import SleeperEspnSource
from .sources.yahoo import YahooAuth, YahooLeagueSource

log = logging.getLogger("companion")
STATIC = Path(__file__).parent / "static"


class State:
    def __init__(self, settings: Settings, db: DB | None = None):
        self.settings = settings
        self.db = db or DB(settings.db_path)
        self.notifier = Notifier(settings)
        self.auth = None
        if settings.demo_mode:
            demo = DemoSource(self.db)
            self.league, self.nfl = demo, demo
        else:
            self.auth = YahooAuth(settings.yahoo_client_id, settings.yahoo_client_secret,
                                  settings.yahoo_redirect_uri, self.db)
            self.league = YahooLeagueSource(self.auth, self.db, settings.yahoo_league_key or None)
            self.nfl = SleeperEspnSource(self.db)
        self.companion = Companion(self.db, self.league, self.nfl, settings)

    @property
    def ready(self) -> bool:
        return self.settings.demo_mode or bool(self.auth and self.auth.authenticated)


class CodeBody(BaseModel):
    code: str


class LeagueBody(BaseModel):
    league_key: str


class WatchBody(BaseModel):
    player_key: str
    name: str


class LineupBody(BaseModel):
    week: int | None = None


def create_app(settings: Settings | None = None, db: DB | None = None, start_monitor: bool = True) -> FastAPI:
    settings = settings or Settings.from_env()
    state = State(settings, db)
    monitor: dict = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if start_monitor and settings.monitor_interval_minutes > 0:
            t = MonitorThread(state.companion, settings, state.notifier)
            t.start()
            monitor["thread"] = t
        yield
        if "thread" in monitor:
            monitor["thread"].stop_event.set()

    app = FastAPI(title="Gridiron Griddle", lifespan=lifespan)
    app.state.companion = state
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    def require_ready():
        if not state.ready:
            raise HTTPException(401, "Connect your Yahoo account first")

    @app.exception_handler(PermissionError)
    async def _perm(request: Request, exc: PermissionError):
        return JSONResponse({"detail": str(exc)}, status_code=401)

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/status")
    def status():
        return {
            "demo": settings.demo_mode,
            "authenticated": state.ready,
            "oob": (settings.yahoo_redirect_uri or "oob") == "oob",
            "league_key": None if not state.ready else (settings.yahoo_league_key or state.db.get("league_key")),
            "channels": state.notifier.channels,
            "monitor_minutes": settings.monitor_interval_minutes,
        }

    # ---------------------------------------------------------------- auth
    @app.get("/auth/login")
    def login():
        if settings.demo_mode:
            return RedirectResponse("/")
        return RedirectResponse(state.auth.authorize_url())

    @app.get("/api/auth/url")
    def auth_url():
        if settings.demo_mode:
            raise HTTPException(400, "Demo mode: add YAHOO_CLIENT_ID/SECRET to .env to connect Yahoo")
        return {"url": state.auth.authorize_url()}

    @app.get("/auth/callback")
    def callback(code: str):
        state.auth.exchange_code(code)
        state.companion.invalidate()
        return RedirectResponse("/")

    @app.post("/api/auth/code")
    def submit_code(body: CodeBody):
        if settings.demo_mode:
            raise HTTPException(400, "Demo mode")
        code = body.code.strip()
        if "code=" in code:  # accept a whole pasted redirect URL
            from urllib.parse import parse_qs, urlparse
            code = parse_qs(urlparse(code).query).get("code", [code])[0]
        state.auth.exchange_code(code)
        state.companion.invalidate()
        return {"ok": True}

    @app.post("/api/auth/logout")
    def logout():
        if state.auth:
            state.auth.logout()
        state.db.cache_clear("yahoo:")
        state.companion.invalidate()
        return {"ok": True}

    # -------------------------------------------------------------- leagues
    @app.get("/api/leagues")
    def leagues():
        require_ready()
        return state.league.leagues()

    @app.post("/api/league")
    def choose_league(body: LeagueBody):
        require_ready()
        state.db.set("league_key", body.league_key)
        if hasattr(state.league, "_league_key"):
            state.league._league_key = None if not settings.yahoo_league_key else body.league_key
        state.companion.invalidate()
        return {"ok": True}

    # ------------------------------------------------------------ dashboard
    @app.get("/api/dashboard")
    def dashboard(week: int | None = None, refresh: bool = False):
        require_ready()
        if refresh:
            state.companion.invalidate()
        return state.companion.dashboard(week)

    @app.get("/api/player/{key}")
    def player(key: str, week: int | None = None):
        require_ready()
        d = state.companion.player_detail(key, week)
        if not d:
            raise HTTPException(404, "Player not found")
        return d

    @app.post("/api/lineup/apply")
    def apply_lineup(body: LineupBody):
        require_ready()
        ctx = state.companion.context(body.week)
        dash = state.companion.dashboard(body.week)
        assignments = dash["lineup"]["assignments"]
        locked = {p.key for p in ctx["rosters"][ctx["my_team"]] if p.locked}
        changes = {k: v for k, v in assignments.items() if k not in locked}
        state.league.set_lineup(ctx["my_team"], ctx["week"], changes)
        state.db.cache_clear(f"yahoo:team/{ctx['my_team']}/roster")
        state.companion.invalidate()
        return {"ok": True, "moved": len(changes)}

    # -------------------------------------------------- alerts & watchlist
    @app.get("/api/alerts")
    def alerts(limit: int = 50):
        return state.db.recent_alerts(limit)

    @app.post("/api/check")
    def check(request: Request):
        require_ready()
        return run_check(state.companion, settings, state.notifier, str(request.base_url))

    @app.post("/api/notify/test")
    def notify_test():
        if not state.notifier.channels:
            raise HTTPException(400, "No notification channels configured in .env")
        return state.notifier.send("Gridiron Griddle test", "Notifications are working!", 3)

    @app.get("/api/watchlist")
    def watchlist():
        return state.db.watchlist()

    @app.post("/api/watchlist")
    def watch(body: WatchBody):
        state.db.watch(body.player_key, body.name)
        state.companion.invalidate()
        return {"ok": True}

    @app.delete("/api/watchlist/{key}")
    def unwatch(key: str):
        state.db.unwatch(key)
        state.companion.invalidate()
        return {"ok": True}

    return app


def __getattr__(name):  # lets `uvicorn companion.app:app` work lazily
    if name == "app":
        logging.basicConfig(level=logging.INFO)
        return create_app()
    raise AttributeError(name)
