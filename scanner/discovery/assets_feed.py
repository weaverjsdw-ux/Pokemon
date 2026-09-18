"""Feed the raw/graded singles catalog (``data/poke/assets.yaml``) into discovery.

Discovery already *supports* singles end to end — ``schema.DealRow`` carries
``asset_class``/``grade``/``grader``/``condition`` and gates on them, and
``score.lens_tags`` already branches on the ``singles-meta`` category. What was
missing was only the **source**: ``pipeline.run_once`` and
``sweep.build_sealed_sweep`` both load ``config.selected_products`` (sealed only)
and stamp ``asset_class="sealed"``. Nothing read the asset catalog.

This module is that source, and nothing more. It builds no comps, invents no
matcher and fabricates no price:

* **Board watch rows** (``build_asset_watch``) come from the catalog. A single has
  no MSRP and no verified-entry buy wire, so it is never a priced deal row — it is
  an honest WATCH record carrying the read-first ledger comp, or ``estimate: null /
  confidence: none`` when the asset has no verified exact source. Same shaping
  functions the ``/api/poke/assets`` routes use, so the two surfaces cannot drift.
* **Discovered singles** (``match_asset``) come from a real listing with a real
  verified price. Matching reuses ``resale``'s title machinery via a product-shaped
  view of the asset — no parallel matcher — and **refuses an ambiguous match**: raw
  NM, LP and PSA 10 of one card share a name, and picking the wrong one is a wrong
  number (the same STOP-class rule ``asset_model.card_ambiguous`` enforces).

Gated by ``poke.singles_board`` (default **off**), so a default run's sealed board
and ledger writes are byte-for-byte what they were.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import config as cfg_mod
from .. import resale
from .. import setname as setname_mod
from ..poke_api import asset_model as asset_model_mod
from ..poke_api import catalog as catalog_mod
from ..poke_api import lab as lab_mod
from ..poke_api import opportunities as opp_mod

# Assets render in the category score.lens_tags already knows about.
SINGLES_CATEGORY = "singles-meta"


def singles_enabled(cfg: Any) -> bool:
    """Whether the singles catalog feeds discovery. Default off: turning it on
    changes what the board and the ledger contain, which is an operator call."""
    return bool(getattr(getattr(cfg, "poke", None), "singles_board", False))


def assets_path(cfg: Any = None) -> Path:
    return cfg_mod.ROOT / "data" / "poke" / "assets.yaml"


def load_feed_assets(cfg: Any, *, path=None) -> tuple[dict[str, dict], str]:
    """``(assets, error)`` for the discovery feed. Returns ``({}, "")`` when the
    gate is off. A malformed catalog is CONTAINED and reported, never raised: the
    same rule the API routes follow, so a bad assets.yaml can never take the
    sealed board offline."""
    if not singles_enabled(cfg):
        return {}, ""
    try:
        return catalog_mod.load_assets(path or assets_path(cfg)), ""
    except catalog_mod.AssetCatalogError as exc:
        return {}, str(exc)[:300]


# ------------------------------------------------------------ catalog watch rows

def asset_comp(observations: list[dict], asset_key: str, asset: dict) -> dict:
    """Read-first comp for one asset: latest ledger observation, offline, 0
    credits. No ledger entry -> the honest empty comp (``estimate`` null,
    ``confidence`` "none"), never a number."""
    row = lab_mod.resolve_asset_comp_row(observations, asset_key, asset)
    if row:
        return asset_model_mod.asset_comp_response(asset_key, asset, row)
    return asset_model_mod.asset_no_comp_response(
        asset_key, asset, status="no_history",
        detail="no asset comp in the ledger for this identity; an unmapped/"
               "unconfigured source yields no number (STOP-class)")


def build_asset_watch(assets: dict[str, dict], observations: list[dict]) -> list[dict]:
    """One WATCH record per catalog asset, comped or honestly empty.

    ``decision`` is always WATCH — assets are never live-eligible on this path
    (there is no verified-entry buy wire for singles), so the record states that
    rather than leaving it to be inferred. ``trade_type`` is the existing
    classifier, so a catalog gap here reads the same as it does in the API."""
    watch: list[dict] = []
    for asset_key, asset in assets.items():
        comp = asset_comp(observations, asset_key, asset)
        estimate = comp.get("estimate")
        asset_class = str(asset.get("asset_class") or "raw")
        trade_type = opp_mod.classify_asset_trade(
            asset_class=asset_class,
            market_comp=estimate,
            # no comp => no history to read; the classifier only needs to know
            # which of the two WATCH buckets this is.
            momentum_status="ok" if estimate is not None else "no_history")
        watch.append({
            "asset_key": asset_key,
            "item": asset.get("name") or asset_key,
            "asset_class": asset_class,
            "category": SINGLES_CATEGORY,
            "set": str(asset.get("set") or ""),
            "set_identity": setname_mod.set_identity(asset.get("set")),
            "card_number": str(asset.get("card_number") or ""),
            "condition": str(asset.get("condition") or ""),
            "grader": str(asset.get("grader") or ""),
            "grade": str(asset.get("grade") or ""),
            "estimate": estimate,
            "confidence": comp.get("confidence") or "none",
            "comp_basis": comp.get("compBasis") or "",
            "source_url": comp.get("sourceUrl") or "",
            "stale": bool(comp.get("stale")),
            "detail": comp.get("detail") or "",
            "trade_type": trade_type,
            "decision": "WATCH",
        })
    watch.sort(key=lambda w: (w["estimate"] is None, -(w["estimate"] or 0), w["asset_key"]))
    return watch


def watch_counts(watch: list[dict]) -> dict[str, int]:
    """Coverage tally for the manifest: how many assets actually carry a comp.
    A batch summary is not proof of coverage — this counts the rows."""
    comped = sum(1 for w in watch if w["estimate"] is not None)
    return {"assets": len(watch), "comped": comped,
            "catalog_gap": len(watch) - comped}


# ------------------------------------------------------------ listing matching

def asset_as_match_product(asset_key: str, asset: dict) -> dict:
    """A product-shaped view of an asset so ``resale``'s existing title matcher
    can score it — NOT a catalog entry, and never persisted.

    ``resale_match`` carries the grading/condition discriminator, so a PSA 10
    listing cannot match the raw row of the same card: the graded view requires
    {"psa","10"} tokens the raw title does not have, and "most specific wins"
    then resolves the pair the same way it resolves ETB vs bundle. ``game`` is
    stamped so ``product_family`` applies the Pokemon guard (an asset name alone
    says "Mamoswine ex 174", which would otherwise match any game's listing)."""
    parts = [str(asset.get("name") or asset_key), str(asset.get("card_number") or "")]
    if str(asset.get("asset_class") or "").lower() == "graded":
        parts += [str(asset.get("grader") or ""), str(asset.get("grade") or "")]
    else:
        parts.append(str(asset.get("condition") or ""))
    return {
        "name": asset.get("name") or asset_key,
        "resale_match": " ".join(p for p in parts if p.strip()),
        "game": "Pokemon TCG",
        "set": asset.get("set") or "",
    }


def match_asset(title: str, assets: dict[str, dict]) -> str | None:
    """``asset_key`` for a listing title, or None.

    Exactly-one-match or nothing. Several assets of one card legitimately share a
    name; with no discriminator in the title there is no evidence for either, and
    guessing raw-vs-PSA-10 is a 10x wrong number. Ambiguity is refused, not
    resolved — the candidate stays honestly unmatched."""
    from .candidates import junk_title, _ascii_fold  # same folding every match uses

    folded = _ascii_fold(title)
    if junk_title(folded):
        return None
    item = {"title": folded}
    best: list[str] = []
    best_specificity = -1
    for asset_key, asset in assets.items():
        view = asset_as_match_product(asset_key, asset)
        if not resale._title_allowed(view, item):
            continue
        specificity = len(resale._required_tokens(view))
        if specificity > best_specificity:
            best, best_specificity = [asset_key], specificity
        elif specificity == best_specificity:
            best.append(asset_key)
    return best[0] if len(best) == 1 else None
