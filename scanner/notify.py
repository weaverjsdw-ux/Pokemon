"""Notification sinks: console, Discord webhook, ntfy.sh."""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass

import requests


@dataclass
class StockAlert:
    retailer: str
    product_name: str
    store_label: str         # "Target #1234 — Springfield, IL"
    distance_miles: float | None
    status: str              # "IN_STOCK", "LIMITED", "ONLINE_IN_STOCK"
    url: str
    price: str = ""

    def line(self) -> str:
        dist = f" ({self.distance_miles:.1f} mi)" if self.distance_miles is not None else ""
        price = f" — {self.price}" if self.price else ""
        return (
            f"[{self.retailer}] {self.status}: {self.product_name}{price}\n"
            f"   {self.store_label}{dist}\n"
            f"   {self.url}"
        )


class Notifier:
    def __init__(self, discord_webhook: str = "", ntfy_topic: str = ""):
        self.discord_webhook = discord_webhook.strip()
        self.ntfy_topic = ntfy_topic.strip()

    def send(self, alert: StockAlert) -> None:
        print(alert.line(), flush=True)
        if self.discord_webhook:
            self._discord(alert)
        if self.ntfy_topic:
            self._ntfy(alert)

    def _discord(self, alert: StockAlert) -> None:
        color = {
            "IN_STOCK": 0x2ECC71,
            "LIMITED": 0xF1C40F,
            "ONLINE_IN_STOCK": 0x3498DB,
        }.get(alert.status, 0x95A5A6)
        embed = {
            "title": f"{alert.status}: {alert.product_name}",
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
            embed["fields"].append({"name": "Price", "value": alert.price, "inline": True})
        try:
            requests.post(
                self.discord_webhook,
                data=json.dumps({"embeds": [embed]}),
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
        except requests.RequestException as exc:
            print(f"  ! discord webhook failed: {exc}", file=sys.stderr)

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
            print(f"  ! ntfy failed: {exc}", file=sys.stderr)
