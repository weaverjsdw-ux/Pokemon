"""Coverage as a ranked work queue.

"85% coverage" is a diagnosis, not an instruction. This turns the confidence
model (:mod:`scanner.confidence`) plus the per-product blocked-reasons already
computed in the web product payload into a *ranked to-do list*: the exact next
actions that raise coverage, cheapest-and-highest-gain first, with the chase
products surfaced by name.

Pure function: takes the confidence rows and the product payload, returns queue
items. Each item carries a ``oneClick`` hint so the UI can drop the operator
straight into the Add-ID form (or Settings) pre-filled.
"""
from __future__ import annotations

from typing import Any

from . import confidence as conf

# Effort tiers - lower is cheaper, and cheaper work sorts first for equal gain.
EFFORT_PASTE_ID = 1     # paste a product URL
EFFORT_TOGGLE = 1       # flip an enabled switch
EFFORT_API_KEY = 2      # get a free key from an external site
EFFORT_REVERIFY = 2     # re-check a flagged ID
EFFORT_ADAPTER = 3      # write/fix adapter code


def _missing_id_products(slug: str, products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for product in products:
        for entry in product.get("retailers", []):
            if entry["slug"] != slug:
                continue
            if entry.get("blockedReason") == "missing product ID":
                out.append(product)
            break
    return _by_priority(out)


def _suspect_id_products(slug: str, products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for product in products:
        for entry in product.get("retailers", []):
            if entry["slug"] == slug and entry.get("idSuspect"):
                out.append(product)
            if entry["slug"] == slug:
                break
    return _by_priority(out)


def _by_priority(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        products,
        key=lambda p: (-int(p.get("priorityScore") or 0), str(p.get("name"))),
    )


def _product_refs(products: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [{"key": p["key"], "name": p.get("name", p["key"])} for p in products]


def _chase_count(products: list[dict[str, Any]]) -> int:
    return sum(1 for p in products if p.get("priority") == "High priority")


def build(
    confidence_rows: list[dict[str, Any]],
    products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return ranked work-queue items derived from confidence + products."""
    items: list[dict[str, Any]] = []
    for row in confidence_rows:
        slug = row["slug"]
        name = row.get("name", slug)
        state = row["state"]

        if state == conf.NEEDS_ID:
            addable = _missing_id_products(slug, products)
            if not addable:
                continue
            top = addable[0]
            items.append(_item(
                slug, name, state,
                action="Add IDs",
                title=f"Add {len(addable)} {name} ID{'s' if len(addable) != 1 else ''}",
                detail=f"0 of your tracked products have a {name} ID. "
                       + _chase_phrase(addable),
                count=len(addable), effort=EFFORT_PASTE_ID,
                products=_product_refs(addable),
                one_click={"type": "add-id", "retailer": slug, "productKey": top["key"]},
            ))

        elif state == conf.NEEDS_API_KEY:
            items.append(_item(
                slug, name, state,
                action="Add API key",
                title=f"Add {name} API key",
                detail=f"{row.get('withId', 0)} IDs are ready; only the key is missing.",
                count=int(row.get("withId") or 0), effort=EFFORT_API_KEY,
                one_click={"type": "settings", "retailer": slug},
            ))

        elif state == conf.DISABLED and int(row.get("withId") or 0) > 0:
            items.append(_item(
                slug, name, state,
                action="Enable source",
                title=f"Enable {name}",
                detail=f"{row['withId']} IDs are ready but {name} is turned off.",
                count=int(row["withId"]), effort=EFFORT_TOGGLE,
                one_click={"type": "settings", "retailer": slug},
            ))

        elif state == conf.ID_SUSPECT:
            suspect = _suspect_id_products(slug, products)
            top = suspect[0] if suspect else None
            items.append(_item(
                slug, name, state,
                action="Re-verify ID",
                title=f"Re-verify {len(suspect) or 1} {name} ID"
                      f"{'s' if len(suspect) != 1 else ''}",
                detail="An ID failed verification (run python -m scanner.verify_ids).",
                count=len(suspect) or 1, effort=EFFORT_REVERIFY,
                products=_product_refs(suspect),
                one_click=({"type": "add-id", "retailer": slug, "productKey": top["key"]}
                           if top else None),
            ))

        elif state == conf.PARSER_SUSPECT:
            items.append(_item(
                slug, name, state,
                action="Fix adapter (dev)",
                title=f"Fix {name} adapter",
                detail="Returns HTTP 200 but no inventory rows - the parser likely drifted.",
                count=int(row.get("withId") or 0), effort=EFFORT_ADAPTER,
            ))

        elif state == conf.BLOCKED:
            items.append(_item(
                slug, name, state,
                action="Diversify coverage",
                title=f"{name} is blocked",
                detail=f"{name} has been blocked recently; add IDs for other sources "
                       "so your coverage doesn't depend on it.",
                count=int(row.get("withId") or 0), effort=EFFORT_PASTE_ID,
            ))

    items.sort(key=lambda it: (-it["score"], it["effort"], it["slug"]))
    return items


def _chase_phrase(products: list[dict[str, Any]]) -> str:
    chase = [p for p in products if p.get("priority") == "High priority"][:3]
    if not chase:
        return "Start with your highest-priority sets."
    names = ", ".join(p.get("name", p["key"]) for p in chase)
    return f"Chase products first: {names}."


def _item(slug, name, state, *, action, title, detail, count, effort,
          products=None, one_click=None) -> dict[str, Any]:
    chase = _chase_count(products or [])
    # gain: products unlocked, with a bonus for chase products; eased by effort.
    gain = count + chase
    score = round((gain * (4 - effort)) + conf.SEVERITY.get(state, 0) / 100, 3)
    return {
        "slug": slug,
        "retailerName": name,
        "state": state,
        "action": action,
        "title": title,
        "detail": detail,
        "count": count,
        "effort": effort,
        "gain": gain,
        "score": score,
        "products": products or [],
        "oneClick": one_click,
    }
