"""Richer StockAlert rendering (console line + Discord embed)."""
from __future__ import annotations

import json

from scanner.notify import Notifier, StockAlert


def test_line_includes_priority_and_seen_context():
    alert = StockAlert(
        retailer="Target",
        product_name="Prismatic Evolutions ETB",
        store_label="Target #123",
        distance_miles=1.2,
        status="IN_STOCK",
        url="https://t/x",
        price="$49.99",
        priority="High priority",
        seen_count=3,
        first_seen=1,
    )
    line = alert.line()
    assert "High priority" in line
    assert "seen 3x" in line
    assert "first seen" in line


def test_line_omits_context_when_absent():
    alert = StockAlert(
        retailer="Target",
        product_name="Booster",
        store_label="Online",
        distance_miles=None,
        status="ONLINE_IN_STOCK",
        url="https://t/x",
    )
    line = alert.line()
    assert "seen" not in line
    assert "priority" not in line.lower()


def test_line_shows_msrp_delta_when_price_differs():
    alert = StockAlert(
        retailer="Best Buy", product_name="ETB", store_label="Online",
        distance_miles=None, status="ONLINE_IN_STOCK", url="u",
        price="$59.99", msrp="$49.99",
    )
    assert "MSRP $49.99" in alert.line()


def test_discord_embed_carries_priority_and_thumbnail(monkeypatch):
    captured = {}

    def fake_post(url, data=None, headers=None, timeout=None):
        captured["payload"] = json.loads(data)

        class R:
            pass
        return R()

    monkeypatch.setattr("scanner.notify.requests.post", fake_post)
    n = Notifier(discord_webhook="https://discord.test/hook")
    n.send(
        StockAlert(
            retailer="Target", product_name="ETB", store_label="Target #1",
            distance_miles=2.0, status="IN_STOCK", url="https://t/x",
            price="$49.99", priority="High priority", seen_count=4,
            image_url="https://img/x.png",
        )
    )
    embed = captured["payload"]["embeds"][0]
    field_names = {f["name"] for f in embed["fields"]}
    assert "Priority" in field_names
    assert "Restocks seen" in field_names
    assert embed["thumbnail"]["url"] == "https://img/x.png"


def _alert(**kw):
    base = dict(
        retailer="Best Buy", product_name="Prismatic ETB",
        store_label="Online", distance_miles=None, status="ONLINE_IN_STOCK",
        url="https://example.com", price="$49.99",
    )
    base.update(kw)
    return StockAlert(**base)


def test_verdict_renders_in_line_when_present():
    line = _alert(verdict="BUY · +$18.00 net, 42% ROI").line()
    assert "BUY · +$18.00 net, 42% ROI" in line


def test_no_verdict_means_no_verdict_text():
    line = _alert().line()
    assert "BUY" not in line and "ROI" not in line


def test_verdict_added_to_discord_embed_fields():
    alert = _alert(verdict="SKIP · +$0.50 net, 1% ROI")
    embed = Notifier(discord_webhook="x")._build_embed(alert)
    verdict_fields = [f for f in embed["fields"] if f["name"] == "Verdict"]
    assert verdict_fields and verdict_fields[0]["value"] == "SKIP · +$0.50 net, 1% ROI"


def test_no_verdict_means_no_verdict_embed_field():
    embed = Notifier(discord_webhook="x")._build_embed(_alert())
    assert not any(f["name"] == "Verdict" for f in embed["fields"])
