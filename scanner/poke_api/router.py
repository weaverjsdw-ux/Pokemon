"""Thin dispatch for the owned sealed price API (Track A).

``handle_get(path, query, deps)`` returns a JSON-ready payload dict for a
matching ``/api/poke/...`` GET, or ``None`` for a non-poke path (so web.py falls
through to its own 404). All real logic lives in history.py / model.py; this
module only routes and wires the read-first comp policy:

* ``refresh=false`` (default): serve a cached comp (offline), else the latest
  ledger comp (offline), else an honest no-comp. Never constructs a network
  comp source.
* ``refresh=true``: call the injected comp provider's ``estimate`` (CompEngine).

The comp provider and ledger reader are dependency-injected via ``PokeApiDeps``
so tests are hermetic; ``build_deps`` wires the real, still-PPT-free defaults.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .. import resale
from . import history as history_mod
from . import model as model_mod

_PREFIX = "/api/poke/"
_TRUTHY = {"1", "true", "yes", "on"}


@dataclass
class PokeApiDeps:
    """Injected dependencies. ``read_observations`` returns the ledger records
    (read fresh per request); ``comp_provider`` exposes ``cached``/``estimate``;
    ``today`` (ISO date) drives momentum staleness."""
    products: dict[str, dict[str, Any]]
    read_observations: Callable[[], list[dict]]
    comp_provider: Any
    today: str | None = None


# ---------------------------------------------------------------- payload helpers

def _ok(payload: dict) -> dict:
    return {"ok": True, **payload}


def _error(status: int, message: str, **extra) -> dict:
    return {"ok": False, "error": message, "httpStatus": status, **extra}


def _not_found(product_key: str) -> dict:
    return _error(404, f"unknown product_key: {product_key!r}", product_key=product_key)


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in _TRUTHY


def _ledger_comp_row(obs: dict, product_key: str, product: dict) -> dict:
    """Shape a latest ledger market_comp observation into a legacy comp row so
    model.comp_response can adapt it. Estimate is money-formatted exactly like the
    real comp rows, so comp_from_row parses it back to a number."""
    price = history_mod._comp_value(obs)
    src = history_mod.source_of(obs)
    url = str(obs.get("source_url") or "")
    return {
        "productKey": product_key,
        "status": "ok",
        "estimate": resale._money(price) if price is not None else "",
        "confidence": str(obs.get("comp_confidence") or "low"),
        "confidenceReason": "latest recorded market_comp (no fresh comp cache)",
        "compBasis": "ledger latest",
        "sources": [{"source": src, "status": "ok", "price": price, "url": url}],
        "sourceUrl": url,
        "url": url,
        "checkedAt": obs.get("capture_date"),
        "cacheHit": False,
    }


# ---------------------------------------------------------------- endpoints

def _products(deps: PokeApiDeps) -> dict:
    items = [model_mod.product_summary(k, p) for k, p in deps.products.items()]
    return _ok({"products": items, "count": len(items)})


def _comp(deps: PokeApiDeps, product_key: str, query: dict) -> dict:
    product = deps.products.get(product_key)
    if product is None:
        return _not_found(product_key)

    if _truthy(query.get("refresh")):
        row = deps.comp_provider.estimate(product_key, product) or {}
        return _ok(model_mod.comp_response(product_key, product, row))

    # read-only: cached comp first (offline), then latest ledger comp (offline).
    cached = deps.comp_provider.cached(product_key, product)
    if cached:
        return _ok(model_mod.comp_response(product_key, product, cached))

    ikey = history_mod.item_key_for_product(product, product_key)
    latest = history_mod.latest(deps.read_observations(), ikey)
    if latest is not None:
        row = _ledger_comp_row(latest, product_key, product)
        return _ok(model_mod.comp_response(product_key, product, row))

    return _ok(model_mod.no_comp_response(
        product_key, product, status="no_history",
        detail="no cached comp and refresh not requested; ledger has no comp for this item"))


def _history(deps: PokeApiDeps, product_key: str) -> dict:
    product = deps.products.get(product_key)
    if product is None:
        return _not_found(product_key)
    observations = deps.read_observations()
    ikey = history_mod.item_key_for_product(product, product_key)
    for_item = history_mod.filter_observations(observations, item_key=ikey)
    by_kind: dict[str, int] = {}
    for obs in for_item:
        kind = str(obs.get("kind") or "unknown")
        by_kind[kind] = by_kind.get(kind, 0) + 1
    grouped = history_mod.history_grouped(observations, ikey)
    by_source = {
        src: [{"date": str(o.get("capture_date") or ""),
               "price": history_mod._comp_value(o),
               "confidence": str(o.get("comp_confidence") or "") or None}
              for o in obs_list]
        for src, obs_list in grouped.items()
    }
    return _ok({
        "product_key": product_key,
        "item_key": ikey,
        "observations": len(for_item),
        "byKind": by_kind,
        "bySource": by_source,
        "priceHistory": model_mod.price_points(observations, ikey),
    })


def _momentum(deps: PokeApiDeps, product_key: str) -> dict:
    product = deps.products.get(product_key)
    if product is None:
        return _not_found(product_key)
    ikey = history_mod.item_key_for_product(product, product_key)
    summary = history_mod.momentum(deps.read_observations(), ikey, today=deps.today)
    return _ok({
        "product_key": product_key,
        "name": product.get("name") or product_key,
        "tcgPlayerId": model_mod._tcg_player_id(product),
        "momentum": summary,
    })


def _sealed_products(deps: PokeApiDeps, query: dict) -> dict:
    tcg_id = str(query.get("tcgPlayerId") or "").strip()
    if not tcg_id:
        return _error(400, "tcgPlayerId query param is required")

    match_key = match_product = None
    for key, product in deps.products.items():
        if str(product.get("ppt_id") or product.get("ppt_query") or "").strip() == tcg_id:
            match_key, match_product = key, product
            break
    if match_product is None:
        return model_mod.no_match_facade(tcg_id)   # 200, empty data, 0 credits

    observations = deps.read_observations()
    ikey = history_mod.item_key_for_product(match_product, match_key)
    row = deps.comp_provider.cached(match_key, match_product)
    if not row:
        latest = history_mod.latest(observations, ikey)
        row = _ledger_comp_row(latest, match_key, match_product) if latest else None
    summary = history_mod.momentum(observations, ikey, today=deps.today)
    return model_mod.sealed_facade(
        match_key, match_product, row,
        price_history=model_mod.price_points(observations, ikey),
        momentum=summary,
        last_scraped_at=summary.get("last_seen"),
        updated_at=summary.get("last_seen"),
    )


# ---------------------------------------------------------------- dispatch

def handle_get(path: str, query: dict[str, str], deps: PokeApiDeps) -> dict | None:
    """Route a GET. Returns a payload dict for a poke route (matched or 404), or
    None when the path is not under /api/poke (web.py owns that 404)."""
    if path != "/api/poke" and not path.startswith(_PREFIX):
        return None
    segments = [s for s in path[len(_PREFIX):].split("/") if s] if path.startswith(_PREFIX) else []

    if segments == ["products"]:
        return _products(deps)
    if segments == ["sealed-products"]:
        return _sealed_products(deps, query)
    if len(segments) == 3 and segments[0] == "products":
        _, key, leaf = segments
        if leaf == "comp":
            return _comp(deps, key, query)
        if leaf == "history":
            return _history(deps, key)
        if leaf == "momentum":
            return _momentum(deps, key)
    return _error(404, f"unknown poke API route: {path}")


# ---------------------------------------------------------------- real defaults

class ReadFirstCompProvider:
    """Default provider. ``cached`` reads only the in-house comp cache (State /
    sqlite - no network). ``estimate`` lazily builds a CompEngine (PPT-free) and
    fetches. Constructing this does no I/O; State/CompEngine are built on first
    use so a read-only request never opens a network comp source."""

    def __init__(self, cfg: Any) -> None:
        self.cfg = cfg
        self._state = None
        self._engine = None

    def cached(self, product_key: str, product: dict) -> dict | None:
        try:
            if self._state is None:
                from ..state import State
                self._state = State()
            ikey = history_mod.item_key_for_product(product, product_key)
            got = self._state.comp_cache_get(ikey)
        except Exception:
            return None
        if not got:
            return None
        row, _fetched_at = got
        return dict(row) | {"cacheHit": True}

    def estimate(self, product_key: str, product: dict) -> dict:
        import time
        if self._engine is None:
            from ..comps.engine import CompEngine
            self._engine = CompEngine.from_config(self.cfg)
        return self._engine.estimate(product_key, product, int(time.time()))


def build_deps(cfg: Any, *, ledger_path: Path | None = None,
               today: str | None = None) -> PokeApiDeps:
    """Wire the real, PPT-free defaults from config. ``today``/``ledger_path``
    are overridable so callers stay deterministic in tests."""
    from .. import config as cfg_mod

    path = ledger_path or (cfg_mod.ROOT / "data" / "poke" / "price_history.jsonl")

    def read_observations() -> list[dict]:
        return history_mod.read_ledger(path).observations

    if today is None:
        from datetime import date
        today = date.today().isoformat()

    return PokeApiDeps(
        products=dict(getattr(cfg, "products", {}) or {}),
        read_observations=read_observations,
        comp_provider=ReadFirstCompProvider(cfg),
        today=today,
    )
