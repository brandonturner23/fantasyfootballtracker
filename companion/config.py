"""Settings loaded from environment variables and an optional .env file."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def load_dotenv(path: str | Path = ".env") -> None:
    """Minimal .env loader: KEY=VALUE lines; existing env vars win."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def _bool(v: str | None) -> bool | None:
    if v is None or v.strip() == "":
        return None
    return v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    yahoo_client_id: str = ""
    yahoo_client_secret: str = ""
    yahoo_redirect_uri: str = "oob"
    yahoo_league_key: str = ""
    demo_mode: bool = True
    db_path: str = "data/companion.db"
    ntfy_topic: str = ""
    ntfy_server: str = "https://ntfy.sh"
    discord_webhook_url: str = ""
    slack_webhook_url: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = ""
    email_to: str = ""
    monitor_interval_minutes: float = 60
    lineup_gain_alert: float = 2.0
    waiver_trend_min: int = 1500
    extra: dict = field(default_factory=dict)

    @property
    def notification_channels(self) -> list[str]:
        ch = []
        if self.ntfy_topic:
            ch.append("ntfy")
        if self.discord_webhook_url:
            ch.append("discord")
        if self.slack_webhook_url:
            ch.append("slack")
        if self.smtp_host and self.email_to:
            ch.append("email")
        return ch

    @classmethod
    def from_env(cls, dotenv: str | Path | None = ".env") -> "Settings":
        if dotenv:
            load_dotenv(dotenv)
        e = os.environ.get
        client_id = e("YAHOO_CLIENT_ID", "")
        demo = _bool(e("DEMO_MODE"))
        if demo is None:
            demo = not client_id
        return cls(
            yahoo_client_id=client_id,
            yahoo_client_secret=e("YAHOO_CLIENT_SECRET", ""),
            yahoo_redirect_uri=e("YAHOO_REDIRECT_URI", "oob") or "oob",
            yahoo_league_key=e("YAHOO_LEAGUE_KEY", ""),
            demo_mode=demo,
            db_path=e("DB_PATH", "data/companion.db") or "data/companion.db",
            ntfy_topic=e("NTFY_TOPIC", ""),
            ntfy_server=(e("NTFY_SERVER", "") or "https://ntfy.sh").rstrip("/"),
            discord_webhook_url=e("DISCORD_WEBHOOK_URL", ""),
            slack_webhook_url=e("SLACK_WEBHOOK_URL", ""),
            smtp_host=e("SMTP_HOST", ""),
            smtp_port=int(e("SMTP_PORT", "587") or 587),
            smtp_user=e("SMTP_USER", ""),
            smtp_password=e("SMTP_PASSWORD", ""),
            email_from=e("EMAIL_FROM", ""),
            email_to=e("EMAIL_TO", ""),
            monitor_interval_minutes=float(e("MONITOR_INTERVAL_MINUTES", "60") or 0),
            lineup_gain_alert=float(e("LINEUP_GAIN_ALERT", "2.0") or 2.0),
            waiver_trend_min=int(e("WAIVER_TREND_MIN", "1500") or 1500),
        )
