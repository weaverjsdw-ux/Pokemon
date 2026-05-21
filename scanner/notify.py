"""Notification sinks: console, Discord webhook, ntfy.sh."""
from __future__ import annotations

import json
from dataclasses import dataclass

import requests

from .log import get_logger
from .priority import NICE_TO_HAVE

log = get_logger(__name__)


@dataclass
class StockAlert:
    retailer: str
    product_name: str
    store_label: str         # "Target #1234 — Springfield, IL"
    distance_miles: float | None
    status: str              # "IN_STOCK", "LIMITED", "ONLINE_IN_STOCK"
    url: str
    price: str = ""
    tier: str = NICE_TO_HAVE
    msrp: str = ""           # e.g. "$49.99" — surfaced for at-or-below-MSRP signal
    cart_url: str = ""       # Direct add-to-cart deep link, when available
    image_url: str = ""      # Product thumbnail URL

    def line(self) -> str:
        dist = f" ({self.distance_miles:.1f} mi)" if self.distance_miles is not None else ""
        price = f" — {self.price}" if self.price else ""
        tag = f" [{self.tier.upper()}]" if self.tier != NICE_TO_HAVE else ""
        return (
            f"[{self.retailer}]{tag} {self.status}: {self.product_name}{price}\n"
            f"   {self.store_label}{dist}\n"
            f"   {self.url}"
        )


class Notifier:
    def __init__(
        self,
        discord_webhook: str = "",
        ntfy_topic: str = "",
        priority_channels: dict[str, str] | None = None,
    ):
        self.discord_webhook = discord_webhook.strip()
        self.ntfy_topic = ntfy_topic.strip()
        self.priority_channels = {
            k: v.strip() for k, v in (priority_channels or {}).items() if v and v.strip()
        }

    def send(self, alert: StockAlert) -> None:
        log.info("alert %s", alert.line().replace("\n", " | "))
        webhook = self.priority_channels.get(alert.tier) or self.discord_webhook
        if webhook:
            self._discord(alert, webhook)
        if self.ntfy_topic:
            self._ntfy(alert)

    def send_status(self, title: str, fields: list[tuple[str, str]]) -> None:
        """Push a non-alert status message (heartbeat, health warning, etc.)

        Plain embed without the stock-status color coding; ntfy gets a
        lower-priority tag so phones don't buzz."""
        log.info("status %s | %s", title, " · ".join(f"{k}={v}" for k, v in fields))
        if self.discord_webhook:
            embed = {
                "title": title,
                "color": 0x95A5A6,
                "fields": [
                    {"name": k, "value": v, "inline": (len(v) < 40)}
                    for k, v in fields
                ],
            }
            try:
                requests.post(
                    self.discord_webhook,
                    data=json.dumps({"embeds": [embed]}),
                    headers={"Content-Type": "application/json"},
                    timeout=10,
                )
            except requests.RequestException as exc:
                log.warning("discord status failed: %s", exc)
        if self.ntfy_topic:
            body = "\n".join(f"{k}: {v}" for k, v in fields)
            try:
                requests.post(
                    f"https://ntfy.sh/{self.ntfy_topic}",
                    data=body.encode("utf-8"),
                    headers={
                        "Title": title,
                        "Priority": "low",
                        "Tags": "information_source",
                    },
                    timeout=10,
                )
            except requests.RequestException as exc:
                log.warning("ntfy status failed: %s", exc)

    def _discord(self, alert: StockAlert, webhook: str) -> None:
        color = {
            "IN_STOCK": 0x2ECC71,
            "LIMITED": 0xF1C40F,
            "ONLINE_IN_STOCK": 0x3498DB,
        }.get(alert.status, 0x95A5A6)
        title = f"{alert.status}: {alert.product_name}"
        if alert.tier != NICE_TO_HAVE:
            title = f"[{alert.tier.upper()}] " + title
        embed: dict = {
            "title": title,
            "url": alert.url,
            "color": color,
            "fields": [
                {"name": "Retailer", "value": alert.retailer, "inline": True},
                {"name": "Store", "value": alert.store_label, "inline": True},
            ],
        }
        if alert.distance_miles is not None:
            embed["fields"].append(
                {"name": "Distance", "value": f"{alert.distance_miles:.1f} mi", "inline": True}
            )
        if alert.price:
            price_value = alert.price
            if alert.msrp and alert.msrp != alert.price:
                price_value = f"{alert.price} (MSRP {alert.msrp})"
            embed["fields"].append({"name": "Price", "value": price_value, "inline": True})
        elif alert.msrp:
            embed["fields"].append({"name": "MSRP", "value": alert.msrp, "inline": True})
        if alert.cart_url:
            embed["fields"].append(
                {
                    "name": "Add to cart",
                    "value": f"[Tap to add]({alert.cart_url})",
                    "inline": False,
                }
            )
        if alert.image_url:
            embed["thumbnail"] = {"url": alert.image_url}
        try:
            requests.post(
                webhook,
                data=json.dumps({"embeds": [embed]}),
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
        except requests.RequestException as exc:
            log.warning("discord webhook failed: %s", exc)

    def _ntfy(self, alert: StockAlert) -> None:
        try:
            requests.post(
                f"https://ntfy.sh/{self.ntfy_topic}",
                data=alert.line().encode("utf-8"),
                headers={
                    "Title": f"{alert.retailer}: {alert.product_name}",
                    "Click": alert.url,
                    "Tags": "package",
                },
                timeout=10,
            )
        except requests.RequestException as exc:
            log.warning("ntfy failed: %s", exc)
