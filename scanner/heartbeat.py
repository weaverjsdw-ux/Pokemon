"""Periodic 'scanner alive' ping.

Posts a low-priority status embed to Discord (and optionally ntfy) every
`interval_seconds`, summarizing per-retailer health + budget so the user
can tell at a glance that things are working without needing to tail logs.
A scanner that silently stops alerting because every retailer got blocked
is worse than one that complains every few hours."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .http import HTTPClient
from .log import get_logger

log = get_logger(__name__)

_DEFAULT_INTERVAL = 6 * 3600  # 6 hours


@dataclass
class HeartbeatState:
    last_sent: float = 0.0
    passes: int = 0
    alerts: int = 0


class Heartbeat:
    def __init__(
        self,
        interval_seconds: int = _DEFAULT_INTERVAL,
        http: HTTPClient | None = None,
    ):
        self.interval = interval_seconds
        self.http = http
        self.started = time.time()
        # Initialize last_sent to start so the first heartbeat fires exactly
        # `interval_seconds` after launch, not immediately on the first pass.
        self.state = HeartbeatState(last_sent=self.started)

    def record_pass(self, alerts_fired: int) -> None:
        self.state.passes += 1
        self.state.alerts += alerts_fired

    def maybe_send(
        self,
        notifier_send_raw,
        retailer_health: dict[str, dict[str, Any]],
        stores_by_retailer: dict[str, list],
    ) -> None:
        """Call once per scan pass. Sends a heartbeat if it's been long enough.

        `notifier_send_raw(title, fields)` is a callable that pushes a plain
        status message through whatever channels the user has configured —
        we don't reuse the StockAlert path because heartbeats aren't alerts.
        """
        now = time.time()
        if now - self.state.last_sent < self.interval:
            return
        self.state.last_sent = now

        uptime_h = (now - self.started) / 3600
        retailer_lines = []
        for slug, stores in stores_by_retailer.items():
            h = retailer_health.get(slug, {})
            tag = "DISABLED" if h.get("disabled") else "ok"
            retailer_lines.append(
                f"{slug}: {tag} · stores={len(stores)} · req/h={h.get('requests_last_hour', 0)}"
            )

        fields = [
            ("Uptime", f"{uptime_h:.1f} h"),
            ("Passes", str(self.state.passes)),
            ("Alerts fired", str(self.state.alerts)),
            ("Retailers", "\n".join(retailer_lines) or "(none)"),
        ]
        try:
            notifier_send_raw("Scanner heartbeat", fields)
            log.info(
                "heartbeat sent uptime_h=%.1f passes=%d alerts=%d",
                uptime_h, self.state.passes, self.state.alerts,
            )
        except Exception:
            log.exception("heartbeat send failed")
