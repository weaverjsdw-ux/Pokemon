"""Ledger-backed price-history reads/index + momentum (Track B).

Turns ``data/poke/price_history.jsonl`` (append-only evidence) into a queryable
time-series layer. Pure: no network, no clock, no writes. ``today`` is passed in
so staleness is deterministic and unit-testable.

The ledger has two writers with slightly different shapes:
* ``discovery/sweep.py`` writes one resolved ``market_comp`` per rendered row
  (no explicit ``source`` field; the retailer is implied by ``source_url``).
* ``comps/engine.py`` writes one ``market_comp`` per contributing source and
  stamps an explicit ``source`` field.
``source_of`` reconciles both; momentum collapses to one canonical value per
capture_date so an engine-style same-day multi-source write never looks like
day-over-day movement.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date as _date_cls
from pathlib import Path
from urllib.parse import urlparse

from ..discovery import ledger as ledger_mod

MARKET_COMP = "market_comp"
DEAL = "deal"
LISTING = "listing"


@dataclass(frozen=True)
class LedgerRead:
    """Result of reading the JSONL ledger. ``valid`` == len(observations)."""
    observations: list[dict]
    total_lines: int
    valid: int
    malformed: int


def read_ledger(path) -> LedgerRead:
    """Read the JSONL ledger safely. Missing file -> empty. Malformed / non-object
    lines are skipped and counted; blank lines are ignored (not counted)."""
    path = Path(path)
    if not path.exists():
        return LedgerRead([], 0, 0, 0)
    observations: list[dict] = []
    total = 0
    malformed = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        total += 1
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if not isinstance(rec, dict):
            malformed += 1
            continue
        observations.append(rec)
    return LedgerRead(observations, total, len(observations), malformed)


def item_key_for_product(product: dict, product_key: str = "") -> str:
    """Catalog product -> ledger item_key, identical to how comps/engine.py and
    discovery/sweep.py stamp it (set|item|variant|grade|condition, lowercased).

    Sealed products carry none of variant/grade/condition, so this stays exactly
    ``set|name|||`` — unchanged. Raw/graded assets use ``item_key_for_asset``,
    which fills the variant/grade/condition slots so identities never collide."""
    return ledger_mod.item_key({
        "set": product.get("set", ""),
        "item": product.get("name") or product_key,
        "variant": "", "grade": "", "condition": "",
    })


def item_key_for_asset(asset: dict, asset_key: str = "") -> str:
    """Raw/graded asset -> ledger item_key. The normalized ``grade_key`` ("psa10")
    goes in the grade slot, ``card_number`` in the variant slot, and ``condition``
    ("nm"/"lp") in the condition slot — so raw NM, raw LP, PSA 10, PSA 9, and the
    all-empty sealed key are all distinct, and never collide with a sealed product."""
    return ledger_mod.item_key({
        "set": asset.get("set", ""),
        "item": asset.get("name") or asset_key,
        "variant": asset.get("card_number") or asset.get("variant") or "",
        "grade": asset.get("grade_key") or "",
        "condition": asset.get("condition") or "",
    })


_SOURCE_BY_HOST = (
    ("pricecharting.com", "pricecharting"),
    ("tcgplayer.com", "tcgplayer"),
    ("ebay.com", "ebay"),
    ("slickdeals.net", "slickdeals"),
)


def source_of(obs: dict) -> str:
    """Retailer/source for an observation: the explicit ``source`` field if the
    writer stamped one, else derived from the ``source_url`` host."""
    src = str(obs.get("source") or "").strip()
    if src:
        return src
    host = urlparse(str(obs.get("source_url") or "")).netloc.lower()
    for needle, name in _SOURCE_BY_HOST:
        if needle in host:
            return name
    return host or "unknown"


def filter_observations(observations, *, item_key=None, source=None, kind=None) -> list[dict]:
    """File-order-preserving filter by item_key / source / kind (any combination)."""
    out = []
    for obs in observations:
        if item_key is not None and obs.get("item_key") != item_key:
            continue
        if kind is not None and obs.get("kind") != kind:
            continue
        if source is not None and source_of(obs) != source:
            continue
        out.append(obs)
    return out


def _capture_date(obs: dict) -> str:
    return str(obs.get("capture_date") or "")


def _comp_value(obs: dict) -> float | None:
    """Numeric price for an observation, kind-aware. market_comp -> comp; a deal
    row -> deal_price; else the market_comp field it carries."""
    for field in ("comp", "deal_price", "market_comp", "price"):
        val = obs.get(field)
        if isinstance(val, (int, float)):
            return float(val)
    return None


def latest(observations, item_key, *, kind=MARKET_COMP, source=None) -> dict | None:
    """Most recent matching observation by capture_date; among equal dates the
    last-appended (file order) wins."""
    best = None
    for obs in filter_observations(observations, item_key=item_key, kind=kind, source=source):
        if best is None or _capture_date(obs) >= _capture_date(best):
            best = obs
    return best


def history_grouped(observations, item_key, *, kind=MARKET_COMP) -> dict[str, list[dict]]:
    """Observations for an item grouped by source, each list sorted by date."""
    groups: dict[str, list[dict]] = {}
    for obs in filter_observations(observations, item_key=item_key, kind=kind):
        groups.setdefault(source_of(obs), []).append(obs)
    for src in groups:
        groups[src] = sorted(groups[src], key=_capture_date)
    return groups


def _canonical_series(observations) -> list[tuple[str, dict]]:
    """One observation per capture_date (last-appended wins), ascending by date.
    Collapsing per-date is what stops a same-day multi-source write from reading
    as movement."""
    by_date: dict[str, dict] = {}
    for obs in observations:  # file order == append order
        by_date[_capture_date(obs)] = obs
    return sorted(by_date.items(), key=lambda kv: kv[0])


def _parse_date(value: str) -> _date_cls | None:
    try:
        parts = str(value).split("-")
        if len(parts) != 3:
            return None
        return _date_cls(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, TypeError):
        return None


def _days_between(d_from: str, d_to: str) -> int | None:
    a, b = _parse_date(d_from), _parse_date(d_to)
    if a is None or b is None:
        return None
    return (b - a).days


def momentum(observations, item_key, *, kind=MARKET_COMP, today=None,
             stale_days=30) -> dict:
    """Movement summary for one item.

    status: ``no_history`` (0 obs), ``single_observation`` (one distinct date;
    latest surfaced, no delta), ``ok`` (>=2 distinct dates; delta computed).
    ``previous`` is the value on the most recent *earlier* date, so delta is
    genuine day-over-day movement. ``today`` (ISO date) drives staleness; when
    omitted, stale fields stay unknown (None/False)."""
    matches = filter_observations(observations, item_key=item_key, kind=kind)
    series = _canonical_series(matches)
    result: dict = {
        "item_key": item_key,
        "kind": kind,
        "status": "no_history",
        "latest": None,
        "previous": None,
        "delta_abs": None,
        "delta_pct": None,
        "observations": len(matches),
        "distinct_dates": len(series),
        "sources": sorted({source_of(o) for o in matches}),
        "first_seen": series[0][0] if series else None,
        "last_seen": series[-1][0] if series else None,
        "latest_confidence": None,
        "stale_days": None,
        "stale": False,
    }
    if not series:
        return result

    latest_date, latest_obs = series[-1]
    result["latest"] = _comp_value(latest_obs)
    result["latest_confidence"] = str(latest_obs.get("comp_confidence") or "") or None
    if today:
        days = _days_between(latest_date, today)
        result["stale_days"] = days
        result["stale"] = days is not None and days > stale_days

    if len(series) == 1:
        result["status"] = "single_observation"
        return result

    prev_price = _comp_value(series[-2][1])
    latest_price = result["latest"]
    result["previous"] = prev_price
    if latest_price is not None and prev_price not in (None, 0):
        result["delta_abs"] = round(latest_price - prev_price, 2)
        result["delta_pct"] = round((latest_price - prev_price) / prev_price * 100.0, 2)
    result["status"] = "ok"
    return result
