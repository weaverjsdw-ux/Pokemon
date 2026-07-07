"""TCGCSV sample-check gate (spec T1). Earns the 'TCGplayer market == PPT' credit-saving
claim at real n BEFORE TCGCSV is trusted as a reference. Pure decision + a thin fetch
orchestrator; 0 PPT credits (reads already-recorded ppt_cards rows).

Only RAW assets are eligible for a pair: TCGCSV/TCGplayer ``marketPrice`` is inherently
an ungraded-card price, with no graded (PSA/CGC slab) counterpart in the catalog. A
graded asset's ppt_cards comp (e.g. a PSA10 "smart price") is a different quantity
entirely — comparing it to a raw tcgcsv price would fail on tolerance for a reason that
has nothing to do with TCGCSV-vs-PPT agreement, which would mislabel the gate's evidence.
Graded assets are honestly skipped, never compared.
"""
from __future__ import annotations

from typing import Callable

from . import history as history_mod
from . import tcgcsv as tcgcsv_mod

MIN_N = 5
TOL_PCT = 2.0


def sample_check(pairs: list[dict], *, min_n: int = MIN_N, tol_pct: float = TOL_PCT) -> dict:
    """PASS only when >= min_n pairs and EVERY pair within tol_pct. Fixed gate (spec 8.2)."""
    n = len(pairs)
    diffs = [abs(float(p["diff_pct"])) for p in pairs]
    max_diff = max(diffs) if diffs else None
    if n < min_n:
        return {"status": "fail", "n": n, "max_diff_pct": max_diff, "pairs": pairs,
                "reason": f"insufficient sample: n={n} below minimum {min_n}"}
    if max_diff is not None and max_diff > tol_pct:
        return {"status": "fail", "n": n, "max_diff_pct": max_diff, "pairs": pairs,
                "reason": f"tolerance exceeded: max diff {max_diff:.2f}% > {tol_pct:g}%"}
    return {"status": "pass", "n": n, "max_diff_pct": max_diff, "pairs": pairs,
            "reason": f"{n} pairs all within {tol_pct:g}%"}


# ---------------------------------------------------------------- thin fetch orchestrator

def _normalize_set_name(name: str) -> str:
    """'SV: Prismatic Evolutions' -> 'prismatic evolutions'. TCGCSV group names carry a
    set-family prefix (``SV:``, ``SWSH:``, ``SV10:``...) the catalog's ``set`` field
    omits; stripping the leading ``PREFIX: `` segment lines the two up. A name with no
    ``: `` is left as-is (already bare)."""
    text = str(name or "").strip()
    if ": " in text:
        text = text.split(": ", 1)[1]
    return text.strip().lower()


def resolve_group_id(set_name: str, groups: list[dict]) -> int | None:
    """The single TCGCSV ``groupId`` whose normalized name matches ``set_name``, or
    ``None`` when zero or more than one group matches (honest skip — never guess which
    group/reprint a set name means)."""
    target = _normalize_set_name(set_name)
    if not target:
        return None
    matches = [g for g in groups
               if _normalize_set_name(g.get("name", "")) == target
               and isinstance(g.get("groupId"), int)]
    if len(matches) != 1:
        return None
    return matches[0]["groupId"]


def _ppt_raw_price(observations: list[dict], asset: dict, asset_key: str) -> float | None:
    """The latest held ``ppt_cards`` ``market_comp`` price for this asset's identity, or
    None (no held reference — nothing to compare)."""
    item_key = history_mod.item_key_for_asset(asset, asset_key)
    row = history_mod.latest(observations, item_key, kind=history_mod.MARKET_COMP,
                             source="ppt_cards")
    if row is None:
        return None
    price = row.get("comp")
    if not isinstance(price, (int, float)) or isinstance(price, bool) or price <= 0:
        return None
    return float(price)


def build_pairs(assets: dict[str, dict], observations: list[dict], groups: list[dict],
                fetch_prices: Callable[[int], list[dict]] | None = None,
                ) -> tuple[list[dict], list[dict]]:
    """(pairs, skipped) across the catalog. A pair needs: asset_class == raw (the only
    class TCGCSV's ungraded marketPrice is comparable to), a mapped tcgplayer_id, a held
    ppt_cards market comp, an unambiguous TCGCSV group for the asset's set, and a clean
    (non-ambiguous, non-null) TCGCSV market price for that exact product/subtype. Every
    other case is an honest, named skip — never a guess. ``skipped`` entries are
    ``{"asset_key", "reason"}``. Caches one ``fetch_prices`` call per resolved group so a
    multi-asset set (e.g. two Prismatic Evolutions cards) doesn't refetch.

    ``fetch_prices`` defaults to ``None``, resolved to ``tcgcsv_mod.fetch_prices`` INSIDE
    the function body (not as a bound default) so a test's
    ``monkeypatch.setattr(tcgcsv_mod, "fetch_prices", ...)`` is honored — a default bound
    at def-time would freeze the original function object and silently ignore the patch."""
    if fetch_prices is None:
        fetch_prices = tcgcsv_mod.fetch_prices
    pairs: list[dict] = []
    skipped: list[dict] = []
    prices_by_group: dict[int, list[dict]] = {}

    for asset_key, asset in assets.items():
        tcgplayer_id = str(asset.get("tcgplayer_id") or "").strip()
        if not tcgplayer_id:
            continue  # unmapped — nothing to compare

        ppt_price = _ppt_raw_price(observations, asset, asset_key)
        if ppt_price is None:
            continue  # no held ppt_cards reference for this asset — nothing to compare

        # Only past this point has the asset actually got both a mapped id AND a held
        # ppt reference — i.e. it would otherwise qualify. NOW the raw/graded scope
        # exclusion is worth naming (never a silent continue for a near-miss).
        if str(asset.get("asset_class") or "").strip().lower() != "raw":
            skipped.append({"asset_key": asset_key,
                            "reason": "graded asset — TCGCSV marketPrice is ungraded-only, "
                                      "not comparable to a graded ppt_cards comp"})
            continue

        group_id = resolve_group_id(asset.get("set", ""), groups)
        if group_id is None:
            skipped.append({"asset_key": asset_key,
                            "reason": f"no unambiguous TCGCSV group for set {asset.get('set')!r}"})
            continue

        if group_id not in prices_by_group:
            prices_by_group[group_id] = fetch_prices(group_id)
        price_rows = prices_by_group[group_id]

        subtype = asset.get("tcgcsv_subtype")  # optional; absent -> None (never guess a printing)
        try:
            tcgplayer_id_int = int(tcgplayer_id)
        except ValueError:
            skipped.append({"asset_key": asset_key, "reason": "non-numeric tcgplayer_id"})
            continue
        tcgcsv_price = tcgcsv_mod.pick_market_price(tcgplayer_id_int, subtype, price_rows)
        if tcgcsv_price is None:
            skipped.append({"asset_key": asset_key,
                            "reason": "no clean TCGCSV market price (missing/ambiguous/null)"})
            continue

        diff_pct = abs(tcgcsv_price - ppt_price) / ppt_price * 100.0
        pairs.append({"asset_key": asset_key, "tcgplayer_id": tcgplayer_id,
                      "ppt_price": ppt_price, "tcgcsv_price": tcgcsv_price,
                      "diff_pct": diff_pct})

    return pairs, skipped
