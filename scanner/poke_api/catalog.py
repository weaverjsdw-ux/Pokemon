"""Raw + graded asset catalog loader + validation (Track D1).

A separate catalog from the sealed ``data/products.yaml`` — raw singles and graded
slabs live in ``data/poke/assets.yaml`` so the sealed catalog is never polluted.
Pure: no network, no clock. Identity lives in ``history.item_key_for_asset``.

Required fields (STOP-class — a mis-specified asset is a hard load error, not a
silent skip):
* raw    -> ``asset_class: raw``,   ``name``, ``set``, ``condition`` (``card_number`` when known)
* graded -> ``asset_class: graded``, ``name``, ``set``, ``grader``, ``grade``
            (``grade_key`` is derived if omitted; ``card_number`` when known)

Optional exact source ids/urls (never required; absent => honest ``none`` comp):
``tcgplayer_id``, ``pricecharting_slug``, ``ebay_query``.
"""
from __future__ import annotations

from pathlib import Path

import yaml

RAW = "raw"
GRADED = "graded"
ASSET_CLASSES = frozenset({RAW, GRADED})

# Fields surfaced on an asset summary / carried onto opportunities + comps.
_SUMMARY_FIELDS = (
    "name", "set", "card_number", "condition", "grader", "grade", "grade_key",
    "tcgplayer_id", "pricecharting_slug", "ebay_query")


class AssetCatalogError(Exception):
    """Raised when the asset catalog file contains an invalid/mis-specified asset."""


def normalize_grade_key(grader, grade) -> str:
    """('PSA','10') -> 'psa10'; ('CGC','9.5') -> 'cgc9.5'. Lowercased, spaces
    stripped, ``{grader}{grade}`` concatenated — the 1:1 PPT ``salesByGrade`` key."""
    return f"{str(grader).strip()}{str(grade).strip()}".lower().replace(" ", "")


def validate_asset(asset_key: str, asset: dict) -> list[str]:
    """Return a list of problems (empty == valid). Never raises. Checks the
    per-class required fields; ``card_number`` is optional ('when known')."""
    tag = asset_key or asset.get("name") or "<unnamed>"
    problems: list[str] = []
    asset_class = str(asset.get("asset_class") or "").strip().lower()
    if asset_class not in ASSET_CLASSES:
        problems.append(f"{tag}: asset_class must be one of {sorted(ASSET_CLASSES)}")
    if not str(asset.get("name") or "").strip():
        problems.append(f"{tag}: asset needs a name")
    if not str(asset.get("set") or "").strip():
        problems.append(f"{tag}: asset needs a set")
    if asset_class == RAW and not str(asset.get("condition") or "").strip():
        problems.append(f"{tag}: raw asset needs a condition (e.g. NM, LP)")
    if asset_class == GRADED:
        if not str(asset.get("grader") or "").strip():
            problems.append(f"{tag}: graded asset needs a grader (PSA, CGC, BGS)")
        if not str(asset.get("grade") or "").strip():
            problems.append(f"{tag}: graded asset needs a grade")
    return problems


def _normalized(asset: dict) -> dict:
    """Fill derived fields (asset_class lowercased; grade_key for graded) without
    mutating the input."""
    out = dict(asset)
    out["asset_class"] = str(asset.get("asset_class") or "").strip().lower()
    if out["asset_class"] == GRADED and not str(asset.get("grade_key") or "").strip():
        if str(asset.get("grader") or "").strip() and str(asset.get("grade") or "").strip():
            out["grade_key"] = normalize_grade_key(asset["grader"], asset["grade"])
    return out


def load_assets(path) -> dict[str, dict]:
    """Read the raw/graded asset catalog. Missing file -> ``{}`` (assets are
    optional). Every asset is normalized then validated; any problem raises
    ``AssetCatalogError`` naming every offending asset (fail loud, like config)."""
    path = Path(path)
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        # A syntactically malformed catalog is a bad catalog file just like an
        # invalid asset — raise the same error type so build_deps' containment
        # keeps it off the sealed routes (never lets a raw YAMLError escape).
        raise AssetCatalogError(f"{path.name}: not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise AssetCatalogError(f"{path.name}: top level must be a mapping of asset_key -> asset")

    assets: dict[str, dict] = {}
    problems: list[str] = []
    for asset_key, asset in raw.items():
        if not isinstance(asset, dict):
            problems.append(f"{asset_key}: asset entry must be a mapping")
            continue
        normalized = _normalized(asset)
        problems.extend(validate_asset(asset_key, normalized))
        assets[str(asset_key)] = normalized
    if problems:
        raise AssetCatalogError(f"{path.name}: invalid assets:\n" + "\n".join(problems))
    return assets


def asset_summary(asset_key: str, asset: dict) -> dict:
    """Owned summary row for ``GET /api/poke/assets``. Carries identity + which
    exact source ids are mapped (so a caller can see what will/won't resolve)."""
    summary = {"asset_key": asset_key, "asset_class": str(asset.get("asset_class") or "")}
    for field in _SUMMARY_FIELDS:
        summary[field] = asset.get(field)
    return summary
