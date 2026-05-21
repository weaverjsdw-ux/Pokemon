"""Additional outbound notification channels beyond Discord + ntfy.

Each channel is opt-in via config. The Notifier orchestrates the
existing Discord/ntfy paths and the channels in this module; failures
in any one channel are logged but don't abort the alert.

Channels here:

  - Pushover: native iOS/Android push with sound + priority. Needs
    pushover.user_key + pushover.app_token. Free 7-day trial then $5/user
    one-time for unlimited push.
  - Email (SMTP): least pleasant on a phone but useful as an archival
    fallback / for users without push apps.
  - Generic webhook: POST a JSON payload to an arbitrary URL. Lets the
    user wire the scanner into IFTTT / Zapier / their own home-automation
    hooks without us needing to know about them.
"""
from __future__ import annotations

import json
import smtplib
from email.mime.text import MIMEText
from typing import Any

import requests

from .log import get_logger

log = get_logger(__name__)


# --- Pushover ---

def send_pushover(cfg: dict[str, Any], title: str, body: str, url: str = "") -> None:
    user = (cfg.get("user_key") or "").strip()
    token = (cfg.get("app_token") or "").strip()
    if not user or not token:
        return
    try:
        requests.post(
            "https://api.pushover.net/1/messages.json",
            data={
                "token": token,
                "user": user,
                "title": title,
                "message": body,
                "url": url,
                "priority": str(cfg.get("priority", 0)),
                "sound": cfg.get("sound", "magic"),
            },
            timeout=10,
        )
    except requests.RequestException as exc:
        log.warning("pushover failed: %s", exc)


# --- Email (SMTP) ---

def send_email(cfg: dict[str, Any], subject: str, body: str) -> None:
    host = (cfg.get("smtp_host") or "").strip()
    if not host:
        return
    sender = (cfg.get("from") or "").strip()
    recipients_raw = cfg.get("to") or []
    if isinstance(recipients_raw, str):
        recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]
    else:
        recipients = [str(r).strip() for r in recipients_raw if str(r).strip()]
    if not sender or not recipients:
        return

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)

    port = int(cfg.get("smtp_port", 587))
    user = (cfg.get("smtp_user") or "").strip()
    password = (cfg.get("smtp_password") or "").strip()
    use_tls = bool(cfg.get("smtp_starttls", True))

    try:
        with smtplib.SMTP(host, port, timeout=10) as smtp:
            if use_tls:
                smtp.starttls()
            if user and password:
                smtp.login(user, password)
            smtp.sendmail(sender, recipients, msg.as_string())
    except (smtplib.SMTPException, OSError) as exc:
        log.warning("email send failed: %s", exc)


# --- Generic webhook ---

def send_generic_webhook(url: str, payload: dict[str, Any]) -> None:
    if not url:
        return
    try:
        requests.post(
            url,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
    except requests.RequestException as exc:
        log.warning("generic webhook %s failed: %s", url, exc)
