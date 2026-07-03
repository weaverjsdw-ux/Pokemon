"""Notification sinks: console, Discord webhook, ntfy.sh."""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

import requests


def _safe_url(url: str) -> str:
    """http(s) only, else empty. Buy URLs are untrusted (web/AI-derived); a
    javascript:/data: link must never become a clickable alert target."""
    try:
        return url if urlparse(str(url)).scheme.lower() in ("http", "https") else ""
    except ValueError:
        return ""


def _ago(ts: int | None) -> str:
    """Compact human delta like '3m', '2h', '4d' for a unix timestamp."""
    if not ts:
        return ""
    delta = max(0, int(time.time()) - int(ts))
    if delta < 90:
        return f"{delta}s"
    if delta < 5400:
        return f"{delta // 60}m"
    if delta < 36 * 3600:
        return f"{delta // 3600}h"
    return f"{delta // 86400}d"


@dataclass
class StockAlert:
    retailer: str
    product_name: str
    store_label: str         # "Target #1234 — Springfield, IL"
    distance_miles: float | None
    status: str              # "IN_STOCK", "LIMITED", "ONLINE_IN_STOCK"
    url: str
    price: str = ""
    # Decision-support context (all optional; render only when present).
    priority: str = ""               # "High priority" | "Standard"
    msrp: str = ""                   # catalog MSRP, if known
    image_url: str = ""              # catalog image, if known
    first_seen: int | None = None    # unix ts this combo was first observed
    seen_count: int | None = None    # how many distinct restocks we've logged
    verdict: str = ""                # "BUY · +$18 net, 42% ROI" | "" when no comp

    def _context_bits(self) -> list[str]:
        bits: list[str] = []
        if self.priority and self.priority != "Standard":
            bits.append(self.priority)
        if self.seen_count and self.seen_count > 1:
            bits.append(f"seen {self.seen_count}x")
        if self.first_seen:
            bits.append(f"first seen {_ago(self.first_seen)} ago")
        if self.verdict:
            bits.append(self.verdict)
        return bits

    def line(self) -> str:
        dist = f" ({self.distance_miles:.1f} mi)" if self.distance_miles is not None else ""
        price = f" — {self.price}" if self.price else ""
        if self.msrp and self.price and self.price != self.msrp:
            price += f" (MSRP {self.msrp})"
        context = self._context_bits()
        ctx_line = f"\n   {' · '.join(context)}" if context else ""
        return (
            f"[{self.retailer}] {self.status}: {self.product_name}{price}\n"
            f"   {self.store_label}{dist}\n"
            f"   {self.url}{ctx_line}"
        )


@dataclass(frozen=True)
class DealAlert:
    """User-facing verified-buyable deal. Every field an operator needs to act
    without re-deriving anything: what/where, the price VERIFIED from the buy
    page, the comp + its confidence + basis, the fee-adjusted verdict, and the
    stock evidence + when it was checked. Emitted only for VERIFIED_BUYABLE
    candidates that passed verify.assert_alertable (enforced in the pipeline)."""
    item: str
    retailer: str
    source_adapter: str
    listing_id: str
    buy_url: str
    verified_price: float | None
    stock_status: str
    stock_evidence: str
    checked_at: str
    msrp: float | None = None
    comp: float | None = None
    comp_confidence: str = ""
    comp_basis: str = ""
    pct_off: float | None = None
    verdict_headline: str = ""
    badges: list[str] = field(default_factory=list)
    warn_flags: list[str] = field(default_factory=list)

    def _price(self, value: float | None) -> str:
        return f"${value:.2f}" if isinstance(value, (int, float)) else "n/a"

    def line(self) -> str:
        head = self.verdict_headline or "BUYABLE"
        comp_bit = ""
        if self.comp is not None:
            conf = f" ({self.comp_confidence})" if self.comp_confidence else ""
            comp_bit = f" vs comp {self._price(self.comp)}{conf}"
        pct_bit = f" · {self.pct_off}% off" if self.pct_off is not None else ""
        warn = f" · ⚠ {', '.join(self.warn_flags)}" if self.warn_flags else ""
        badges = f" [{' '.join(self.badges)}]" if self.badges else ""
        return (
            f"[deal] {head}: {self.item} @ {self.retailer}{badges}\n"
            f"   {self._price(self.verified_price)}{comp_bit}{pct_bit} · "
            f"{self.stock_status}{warn}\n"
            f"   {self.buy_url}\n"
            f"   checked {self.checked_at} · {self.stock_evidence}"
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

    def _build_embed(self, alert: StockAlert) -> dict:
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
            price_value = alert.price
            if alert.msrp and alert.msrp != alert.price:
                price_value += f" (MSRP {alert.msrp})"
            embed["fields"].append({"name": "Price", "value": price_value, "inline": True})
        if alert.priority and alert.priority != "Standard":
            embed["fields"].append({"name": "Priority", "value": alert.priority, "inline": True})
        if alert.seen_count and alert.seen_count > 1:
            embed["fields"].append(
                {"name": "Restocks seen", "value": str(alert.seen_count), "inline": True}
            )
        if alert.verdict:
            embed["fields"].append(
                {"name": "Verdict", "value": alert.verdict, "inline": False}
            )
        if alert.image_url:
            embed["thumbnail"] = {"url": alert.image_url}
        return embed

    def _discord(self, alert: StockAlert) -> None:
        embed = self._build_embed(alert)
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

    # ------------------------------------------------------------ deal alerts

    def send_deal(self, alert: DealAlert, *, push: bool = True) -> None:
        """Emit a verified-buyable deal. Discord always posts (silent history);
        ntfy pushes only when ``push`` (quiet hours pass push=False)."""
        print(alert.line(), flush=True)
        if self.discord_webhook:
            self._discord_deal(alert)
        if self.ntfy_topic and push:
            self._ntfy_deal(alert)

    def _build_deal_embed(self, alert: DealAlert) -> dict:
        color = {"in_stock": 0x2ECC71, "limited": 0xF1C40F}.get(alert.stock_status, 0x3498DB)
        title = f"{alert.verdict_headline or 'BUYABLE'}: {alert.item}"
        embed: dict = {
            "title": title[:250],
            "url": _safe_url(alert.buy_url),
            "color": color,
            "fields": [
                {"name": "Retailer", "value": f"{alert.retailer} ({alert.source_adapter})",
                 "inline": True},
                {"name": "Verified price", "value": alert._price(alert.verified_price),
                 "inline": True},
            ],
        }
        if alert.msrp is not None:
            embed["fields"].append(
                {"name": "MSRP", "value": alert._price(alert.msrp), "inline": True})
        if alert.comp is not None:
            comp_val = alert._price(alert.comp)
            if alert.comp_confidence:
                comp_val += f" ({alert.comp_confidence})"
            embed["fields"].append({"name": "Comp", "value": comp_val, "inline": True})
        if alert.comp_basis:
            embed["fields"].append(
                {"name": "Comp basis", "value": alert.comp_basis[:200], "inline": False})
        if alert.pct_off is not None:
            embed["fields"].append(
                {"name": "% off", "value": f"{alert.pct_off}%", "inline": True})
        if alert.verdict_headline:
            embed["fields"].append(
                {"name": "Verdict", "value": alert.verdict_headline, "inline": False})
        embed["fields"].append(
            {"name": "Stock", "value": f"{alert.stock_status} · checked {alert.checked_at}",
             "inline": False})
        if alert.stock_evidence:
            embed["fields"].append(
                {"name": "Evidence", "value": alert.stock_evidence[:1000], "inline": False})
        if alert.warn_flags:
            embed["fields"].append(
                {"name": "⚠ Warnings", "value": ", ".join(alert.warn_flags)[:1000],
                 "inline": False})
        return embed

    def _discord_deal(self, alert: DealAlert) -> None:
        embed = self._build_deal_embed(alert)
        try:
            requests.post(
                self.discord_webhook,
                data=json.dumps({"embeds": [embed]}),
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
        except requests.RequestException as exc:
            print(f"  ! discord webhook failed: {exc}", file=sys.stderr)

    def _ntfy_deal(self, alert: DealAlert) -> None:
        headers = {
            "Title": f"{alert.verdict_headline or 'BUYABLE'}: {alert.item}"[:250],
            "Tags": "moneybag",
        }
        click = _safe_url(alert.buy_url)
        if click:
            headers["Click"] = click
        try:
            requests.post(
                f"https://ntfy.sh/{self.ntfy_topic}",
                data=alert.line().encode("utf-8"),
                headers=headers,
                timeout=10,
            )
        except requests.RequestException as exc:
            print(f"  ! ntfy failed: {exc}", file=sys.stderr)
