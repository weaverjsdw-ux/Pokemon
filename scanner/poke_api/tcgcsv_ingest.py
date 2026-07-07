"""TCGCSV identity ingest (spec T3): propose EXACT tcgplayer_id mappings for review.

Replaces a fuzzy mapping assistant with an exact join (card number + name → productId).
Emits PROPOSALS only — never writes assets.yaml; a non-exact candidate is 'none',
surfaced for review, never accepted (STOP-class exact identity).
"""
from __future__ import annotations

from .tcgcsv import card_number_of


def _norm(s) -> str:
    return " ".join(str(s or "").strip().lower().split())


def propose_mappings(products: list[dict], assets: list[dict]) -> list[dict]:
    by_number: dict[str, list[dict]] = {}
    for p in products:
        num = card_number_of(p)
        if num:
            by_number.setdefault(num.strip(), []).append(p)
    out: list[dict] = []
    for asset in assets:
        want_num = str(asset.get("card_number") or "").strip()
        want_name = _norm(asset.get("name"))
        candidates = by_number.get(want_num, [])
        exact = [p for p in candidates if _norm(p.get("name")) == want_name]
        if len(exact) == 1:
            out.append({"asset_key": asset.get("asset_key"),
                        "tcgplayer_id": exact[0].get("productId"),
                        "card_number": want_num,
                        "product_name": exact[0].get("name"), "match": "exact"})
        else:
            out.append({"asset_key": asset.get("asset_key"), "tcgplayer_id": None,
                        "card_number": want_num, "product_name": None, "match": "none"})
    return out
