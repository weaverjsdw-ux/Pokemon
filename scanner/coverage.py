"""Catalog coverage score.

"Coverage" is the share of selected products that are actually actionable:
they have at least one identifier for a retailer that is enabled and
supported. A pretty product list with no IDs is decorative, not a scanner -
this turns that gap into a number the operator can watch (and improve with
``python -m scanner.add_id``).

Run as: ``python -m scanner.coverage``
"""
from __future__ import annotations

import sys
from typing import Any

from . import config as cfg_mod
from .retailers import ALL as RETAILER_REGISTRY


def _has_id(product: dict[str, Any], fields: tuple[str, ...]) -> bool:
    return any(str(product.get(field) or "").strip() for field in fields)


def _retailer_ready(slug: str, cls: type, cfg: cfg_mod.Config) -> bool:
    rcfg = cfg.retailers.get(slug)
    if not (rcfg and rcfg.enabled):
        return False
    if not getattr(cls, "supported", True):
        return False
    if getattr(cls, "api_key_required", False) and not rcfg.api_key.strip():
        return False
    return True


def coverage_report(cfg: cfg_mod.Config) -> dict[str, Any]:
    """Compute per-retailer and overall coverage for the selected products."""
    try:
        selected = cfg_mod.selected_products(cfg)
    except SystemExit:
        selected = {}
    total = len(selected)

    retailers: list[dict[str, Any]] = []
    for slug, cls in RETAILER_REGISTRY.items():
        fields = getattr(cls, "product_id_fields", ())
        if not fields:
            continue
        rcfg = cfg.retailers.get(slug)
        enabled = bool(rcfg and rcfg.enabled)
        supported = bool(getattr(cls, "supported", True))
        api_key_required = bool(getattr(cls, "api_key_required", False))
        api_key_set = bool(rcfg and rcfg.api_key.strip())
        ready = _retailer_ready(slug, cls, cfg)
        with_id = sum(1 for p in selected.values() if _has_id(p, fields))
        retailers.append(
            {
                "slug": slug,
                "name": cls.name,
                "enabled": enabled,
                "supported": supported,
                "apiKeyRequired": api_key_required,
                "apiKeySet": api_key_set,
                "ready": ready,
                "onlineOnly": bool(getattr(cls, "online_only", False)),
                "withId": with_id,
                "total": total,
                "pct": round(100 * with_id / total) if total else 0,
            }
        )

    # A product is "actionable" if some enabled + supported retailer has an ID.
    actionable = 0
    for product in selected.values():
        for slug, cls in RETAILER_REGISTRY.items():
            if not _retailer_ready(slug, cls, cfg):
                continue
            if _has_id(product, getattr(cls, "product_id_fields", ())):
                actionable += 1
                break

    return {
        "totalProducts": total,
        "actionableProducts": actionable,
        "score": round(100 * actionable / total) if total else 0,
        "retailers": retailers,
    }


def format_report(report: dict[str, Any]) -> str:
    lines: list[str] = []
    score = report["score"]
    bar_len = 24
    filled = round(bar_len * score / 100)
    bar = "#" * filled + "-" * (bar_len - filled)
    lines.append(
        f"Active coverage: {score}%  [{bar}]  "
        f"{report['actionableProducts']}/{report['totalProducts']} products actionable"
    )
    lines.append("")
    lines.append("Per-retailer ID coverage (of selected products):")
    for r in sorted(report["retailers"], key=lambda x: (-x["withId"], x["slug"])):
        flag = "on " if r["enabled"] else "off"
        if not r["supported"]:
            flag = "n/a"
        elif r.get("apiKeyRequired") and not r.get("apiKeySet"):
            flag = "key"
        lines.append(
            f"  {r['name']:<14} [{flag}] {r['withId']:>2}/{r['total']:<2} ({r['pct']}%)"
        )
    if report["score"] < 100:
        lines.append("")
        lines.append(
            "Tip: add IDs with  python -m scanner.add_id <retailer> <product_key> <url>"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    cfg = cfg_mod.load()
    report = coverage_report(cfg)
    print(format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
