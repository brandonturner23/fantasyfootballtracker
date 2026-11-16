"""Send alerts to phone (ntfy), Discord, Slack and/or email."""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

import requests

from .config import Settings

log = logging.getLogger(__name__)
NTFY_PRIORITY = {1: "urgent", 2: "high", 3: "default", 4: "low"}


class Notifier:
    def __init__(self, settings: Settings):
        self.s = settings

    @property
    def channels(self) -> list[str]:
        return self.s.notification_channels

    def send(self, title: str, message: str, priority: int = 3, url: str | None = None) -> dict[str, str]:
        results: dict[str, str] = {}
        for ch in self.channels:
            try:
                getattr(self, f"_{ch}")(title, message, priority, url)
                results[ch] = "ok"
            except Exception as exc:  # one broken channel shouldn't block the others
                log.warning("notification via %s failed: %s", ch, exc)
                results[ch] = f"error: {exc}"
        return results

    def _ntfy(self, title, message, priority, url):
        headers = {"Title": title.encode("utf-8"), "Priority": NTFY_PRIORITY.get(priority, "default"),
                   "Tags": "football"}
        if url:
            headers["Click"] = url
        r = requests.post(f"{self.s.ntfy_server}/{self.s.ntfy_topic}", data=message.encode("utf-8"),
                          headers=headers, timeout=15)
        r.raise_for_status()

    def _discord(self, title, message, priority, url):
        content = f"**{title}**\n{message}"
        if url:
            content += f"\n{url}"
        r = requests.post(self.s.discord_webhook_url, json={"content": content[:1990]}, timeout=15)
        r.raise_for_status()

    def _slack(self, title, message, priority, url):
        text = f"*{title}*\n{message}" + (f"\n<{url}|Open dashboard>" if url else "")
        r = requests.post(self.s.slack_webhook_url, json={"text": text}, timeout=15)
        r.raise_for_status()

    def _email(self, title, message, priority, url):
        msg = EmailMessage()
        msg["Subject"] = f"[Gridiron Griddle] {title}"
        msg["From"] = self.s.email_from or self.s.smtp_user
        msg["To"] = self.s.email_to
        msg.set_content(message + (f"\n\n{url}" if url else ""))
        with smtplib.SMTP(self.s.smtp_host, self.s.smtp_port, timeout=20) as smtp:
            smtp.starttls()
            if self.s.smtp_user:
                smtp.login(self.s.smtp_user, self.s.smtp_password)
            smtp.send_message(msg)
