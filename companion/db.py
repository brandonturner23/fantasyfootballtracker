"""SQLite persistence: OAuth tokens, API cache, alerts, watchlist, key/value state."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT NOT NULL, fetched_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dedupe_key TEXT UNIQUE NOT NULL,
    kind TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 3,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at REAL NOT NULL,
    sent INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS watchlist (
    player_key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    added_at REAL NOT NULL
);
"""


class DB:
    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    # ---- key/value ----
    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self._conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)),
            )
            self._conn.commit()

    def delete(self, key: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM kv WHERE key=?", (key,))
            self._conn.commit()

    # ---- cache ----
    def cache_get(self, key: str, max_age: float | None) -> Any:
        with self._lock:
            row = self._conn.execute("SELECT value, fetched_at FROM cache WHERE key=?", (key,)).fetchone()
        if not row:
            return None
        if max_age is not None and time.time() - row["fetched_at"] > max_age:
            return None
        return json.loads(row["value"])

    def cache_set(self, key: str, value: Any) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO cache(key,value,fetched_at) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, fetched_at=excluded.fetched_at",
                (key, json.dumps(value), time.time()),
            )
            self._conn.commit()

    def cache_clear(self, prefix: str = "") -> None:
        with self._lock:
            self._conn.execute("DELETE FROM cache WHERE key LIKE ?", (prefix + "%",))
            self._conn.commit()

    # ---- alerts ----
    def add_alert(self, dedupe_key: str, kind: str, title: str, message: str, priority: int = 3) -> bool:
        """Insert an alert; returns False if one with the same dedupe key already exists."""
        with self._lock:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO alerts(dedupe_key,kind,priority,title,message,created_at) VALUES(?,?,?,?,?,?)",
                (dedupe_key, kind, priority, title, message, time.time()),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def unsent_alerts(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM alerts WHERE sent=0 ORDER BY priority, id").fetchall()
        return [dict(r) for r in rows]

    def mark_sent(self, ids: list[int]) -> None:
        if not ids:
            return
        with self._lock:
            self._conn.executemany("UPDATE alerts SET sent=1 WHERE id=?", [(i,) for i in ids])
            self._conn.commit()

    def recent_alerts(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    # ---- watchlist ----
    def watchlist(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM watchlist ORDER BY added_at").fetchall()
        return [dict(r) for r in rows]

    def watch(self, player_key: str, name: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO watchlist(player_key,name,added_at) VALUES(?,?,?)",
                (player_key, name, time.time()),
            )
            self._conn.commit()

    def unwatch(self, player_key: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM watchlist WHERE player_key=?", (player_key,))
            self._conn.commit()
