"""Catalog coverage scoring."""
from __future__ import annotations

from scanner.config import Config, RetailerCfg
from scanner.coverage import coverage_report, format_report


def _cfg(retailers, products):
    return Config(
        home_address="h",
        work_address="w",
        route_radius_miles=4,
        routing_engine="osrm",
        google_api_key="",
        retailers=retailers,
        poll_interval_seconds=180,
        discord_webhook="",
        ntfy_topic="",
        products_filter="all_sealed",
        products=products,
    )


def test_score_counts_actionable_products():
    cfg = _cfg(
        {"target": RetailerCfg(enabled=True), "walmart": RetailerCfg(enabled=True)},
        {
            "a": {"name": "A", "target_tcin": "1"},          # actionable (target on)
            "b": {"name": "B", "walmart_item_id": "2"},      # actionable (walmart on)
            "c": {"name": "C", "target_tcin": ""},           # no ids -> not actionable
        },
    )
    report = coverage_report(cfg)
    assert report["totalProducts"] == 3
    assert report["actionableProducts"] == 2
    assert report["score"] == 67


def test_id_present_but_retailer_disabled_is_not_actionable():
    cfg = _cfg(
        {"target": RetailerCfg(enabled=False)},
        {"a": {"name": "A", "target_tcin": "1"}},
    )
    report = coverage_report(cfg)
    assert report["actionableProducts"] == 0
    assert report["score"] == 0
    target = next(r for r in report["retailers"] if r["slug"] == "target")
    assert target["withId"] == 1          # has the ID...
    assert target["enabled"] is False     # ...but retailer is off


def test_unsupported_retailer_ids_do_not_count():
    cfg = _cfg(
        {"samsclub": RetailerCfg(enabled=True)},
        {"a": {"name": "A", "samsclub_item_id": "1"}},
    )
    report = coverage_report(cfg)
    assert report["actionableProducts"] == 0


def test_supported_costco_ids_count_when_enabled():
    cfg = _cfg(
        {"costco": RetailerCfg(enabled=True)},
        {"a": {"name": "A", "costco_item_id": "4000313298"}},
    )
    report = coverage_report(cfg)
    costco = next(r for r in report["retailers"] if r["slug"] == "costco")
    assert costco["withId"] == 1
    assert costco["ready"] is True
    assert report["actionableProducts"] == 1


def test_api_key_retailer_without_key_is_not_actionable():
    cfg = _cfg(
        {"bestbuy": RetailerCfg(enabled=True, api_key="")},
        {"a": {"name": "A", "bestbuy_sku": "12345"}},
    )
    report = coverage_report(cfg)
    bestbuy = next(r for r in report["retailers"] if r["slug"] == "bestbuy")
    assert bestbuy["withId"] == 1
    assert bestbuy["apiKeyRequired"] is True
    assert bestbuy["ready"] is False
    assert report["actionableProducts"] == 0


def test_format_report_is_stringy_and_mentions_score():
    cfg = _cfg(
        {"target": RetailerCfg(enabled=True)},
        {"a": {"name": "A", "target_tcin": "1"}},
    )
    text = format_report(coverage_report(cfg))
    assert "Active coverage: 100%" in text
    assert "Target" in text
