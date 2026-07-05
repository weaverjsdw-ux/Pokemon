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

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import asset_model as asset_model_mod
from . import candidates as candidates_mod
from . import catalog as catalog_mod
from . import history as history_mod
from . import lab as lab_mod
from . import model as model_mod
from . import paper_ledger as ledger_mod
from . import sources as sources_mod

_PREFIX = "/api/poke/"
_TRUTHY = {"1", "true", "yes", "on"}


@dataclass
class PokeApiDeps:
    """Injected dependencies. ``read_observations`` returns the ledger records
    (read fresh per request); ``comp_provider`` exposes ``cached``/``estimate``;
    ``today`` (ISO date) drives momentum staleness.

    Phase C adds: ``cfg`` (the full Config — opportunity scoring reuses its fees/
    thresholds/business policy), ``candidate_for`` (optional verified deal per
    product; a future discovery wire, defaults to none so the read API works
    without it), ``read_decisions`` (paper-ledger rows), and ``decisions_path``."""
    products: dict[str, dict[str, Any]]
    read_observations: Callable[[], list[dict]]
    comp_provider: Any
    today: str | None = None
    cfg: Any = None
    candidate_for: Callable[[str, dict], dict | None] = lambda key, product: None
    read_decisions: Callable[[], list[dict]] = lambda: []
    decisions_path: Any = None
    read_candidates: Callable[[], list[dict]] = lambda: []
    candidates_path: Any = None
    # Track D: raw/graded assets (default empty so every sealed-only test is
    # unchanged) and the dormant PPT /cards client (None unless configured).
    # ``assets_error`` is set (assets left empty) when the asset catalog fails to
    # load — the failure is contained to the asset routes so a malformed
    # assets.yaml never takes the sealed catalog offline (surfaced, never silent).
    assets: dict[str, dict[str, Any]] = field(default_factory=dict)
    card_client: Any = None
    assets_error: str = ""


# ---------------------------------------------------------------- payload helpers

def _ok(payload: dict) -> dict:
    return {"ok": True, **payload}


def _error(status: int, message: str, **extra) -> dict:
    return {"ok": False, "error": message, "httpStatus": status, **extra}


def _not_found(product_key: str) -> dict:
    return _error(404, f"unknown product_key: {product_key!r}", product_key=product_key)


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in _TRUTHY


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
    row = lab_mod.resolve_comp_row(
        deps.comp_provider, deps.read_observations(), product_key, product)
    if row:
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
    row = lab_mod.resolve_comp_row(deps.comp_provider, observations, match_key, match_product)
    summary = history_mod.momentum(observations, ikey, today=deps.today)
    return model_mod.sealed_facade(
        match_key, match_product, row,
        price_history=model_mod.price_points(observations, ikey),
        momentum=summary,
        last_scraped_at=summary.get("last_seen"),
        updated_at=summary.get("last_seen"),
    )


# ---------------------------------------------------------------- Track D (assets)

def _asset_not_found(asset_key: str) -> dict:
    return _error(404, f"unknown asset_key: {asset_key!r}", asset_key=asset_key)


def _asset_catalog_error(deps: PokeApiDeps) -> dict | None:
    """Honest error payload when the asset catalog failed to load (contained here so
    sealed routes stay up). ``None`` when the catalog is fine."""
    if deps.assets_error:
        return _error(500, f"asset catalog invalid: {deps.assets_error}",
                      assetsError=deps.assets_error)
    return None


def _today_ts(today: str | None) -> int:
    """Deterministic timestamp from the injected ISO ``today`` (no wall clock) for
    the source resolvers' capture labels; falls back to 0 if today is unset/bad."""
    from datetime import date, datetime
    try:
        return int(datetime(*[int(p) for p in str(today).split("-")]).timestamp())
    except (TypeError, ValueError):
        return int(datetime.combine(date(1970, 1, 1), datetime.min.time()).timestamp())


def _resolve_asset_source(deps: PokeApiDeps, asset: dict, checked_at: int) -> dict:
    """Run the raw/graded source resolver (refresh path). With no configured card
    client this returns an honest ``none`` row and touches no network."""
    comps = getattr(deps.cfg, "comps", None)
    tol = float(getattr(comps, "agreement_tolerance_pct", 20.0))
    floor = float(getattr(comps, "ebay_floor_sanity_pct", 50.0))
    if str(asset.get("asset_class")) == catalog_mod.RAW:
        return sources_mod.resolve_raw_comp(
            asset, checked_at=checked_at, ppt_client=deps.card_client,
            tolerance_pct=tol, floor_sanity_pct=floor)
    return sources_mod.resolve_graded_comp(
        asset, checked_at=checked_at, ppt_client=deps.card_client)


def _assets(deps: PokeApiDeps) -> dict:
    items = [catalog_mod.asset_summary(k, a) for k, a in deps.assets.items()]
    return _ok({"assets": items, "count": len(items)})


def _asset_comp(deps: PokeApiDeps, asset_key: str, query: dict) -> dict:
    asset = deps.assets.get(asset_key)
    if asset is None:
        return _asset_not_found(asset_key)

    if _truthy(query.get("refresh")):
        row = _resolve_asset_source(deps, asset, _today_ts(deps.today))
        return _ok(asset_model_mod.asset_comp_response(asset_key, asset, row))

    # read-first: latest ledger comp for this identity (offline), else honest none.
    row = lab_mod.resolve_asset_comp_row(deps.read_observations(), asset_key, asset)
    if row:
        return _ok(asset_model_mod.asset_comp_response(asset_key, asset, row))
    return _ok(asset_model_mod.asset_no_comp_response(
        asset_key, asset, status="no_history",
        detail="no asset comp in the ledger and refresh not requested; an unmapped/"
               "unconfigured source yields no number (STOP-class)"))


def _asset_history(deps: PokeApiDeps, asset_key: str) -> dict:
    asset = deps.assets.get(asset_key)
    if asset is None:
        return _asset_not_found(asset_key)
    observations = deps.read_observations()
    ikey = history_mod.item_key_for_asset(asset)
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
        "asset_key": asset_key,
        "item_key": ikey,
        "observations": len(for_item),
        "byKind": by_kind,
        "bySource": by_source,
        "priceHistory": model_mod.price_points(observations, ikey),
    })


def _asset_momentum(deps: PokeApiDeps, asset_key: str) -> dict:
    asset = deps.assets.get(asset_key)
    if asset is None:
        return _asset_not_found(asset_key)
    ikey = history_mod.item_key_for_asset(asset)
    summary = history_mod.momentum(deps.read_observations(), ikey, today=deps.today)
    return _ok({
        "asset_key": asset_key,
        "name": asset.get("name") or asset_key,
        "asset_class": str(asset.get("asset_class") or ""),
        "tcgPlayerId": asset_model_mod._tcg_player_id(asset),
        "momentum": summary,
    })


def _cards(deps: PokeApiDeps, query: dict) -> dict:
    """PPT-``/cards``-compatible resolve by ``tcgPlayerId`` + an explicit ``condition``
    (raw) or ``grade``/``grade_key`` (graded) discriminator. One id maps to several
    assets, so an id with no discriminator that matches >1 asset returns an
    ``ambiguous`` facade (never a guessed variant). Read-first, 0 credits."""
    tcg_id = str(query.get("tcgPlayerId") or "").strip()
    if not tcg_id:
        return _error(400, "tcgPlayerId query param is required")

    matches = [(k, a) for k, a in deps.assets.items()
               if str(a.get("tcgplayer_id") or "").strip() == tcg_id]
    if not matches:
        return asset_model_mod.card_no_match(tcg_id)

    condition = str(query.get("condition") or "").strip().lower()
    grade = str(query.get("grade") or query.get("grade_key") or "").strip().lower()
    if condition:
        matches = [(k, a) for k, a in matches
                   if str(a.get("condition") or "").strip().lower() == condition]
    elif grade:
        matches = [(k, a) for k, a in matches
                   if grade in (str(a.get("grade_key") or "").strip().lower(),
                                str(a.get("grade") or "").strip().lower())]

    if len(matches) == 1:
        key, asset = matches[0]
        observations = deps.read_observations()
        ikey = history_mod.item_key_for_asset(asset)
        row = lab_mod.resolve_asset_comp_row(observations, key, asset)
        summary = history_mod.momentum(observations, ikey, today=deps.today)
        return asset_model_mod.card_facade(
            key, asset, row,
            price_history=model_mod.price_points(observations, ikey), momentum=summary)
    if not matches:
        return asset_model_mod.card_no_match(
            tcg_id, detail="tcgPlayerId matched assets but none matched the condition/grade filter")
    return asset_model_mod.card_ambiguous(tcg_id, matches)


# ---------------------------------------------------------------- Phase C (Lab)

def _opportunities(deps: PokeApiDeps) -> dict:
    """Scored opportunities across the catalog + a summary. Read-first, no
    network, 0 credits (mirrors the rest of the owned API). Sealed opportunities
    first, then raw/graded asset WATCH rows (Track D) — the sealed dormancy /
    activation wire (/signals) stays sealed-scoped."""
    opps = (lab_mod.build_opportunities(deps, as_of=deps.today)
            + lab_mod.build_asset_opportunities(deps, as_of=deps.today))
    return _ok({"count": len(opps), "summary": lab_mod.summary(opps), "opportunities": opps})


def _opportunity(deps: PokeApiDeps, product_key: str) -> dict:
    product = deps.products.get(product_key)
    if product is None:
        return _not_found(product_key)
    o = lab_mod.build_opportunity_row(
        deps, product_key, product, deps.read_observations(), as_of=deps.today)
    return _ok({"opportunity": o})


def _paper_decisions(deps: PokeApiDeps) -> dict:
    """Current paper decision + latest outcome per opportunity (the replay fold).
    Immutable history lives in the ledger; this is a read-time projection."""
    current = ledger_mod.current_by_id(deps.read_decisions())
    items = [{"opportunity_id": oid, **slot} for oid, slot in current.items()]
    return _ok({"count": len(items), "decisions": items})


def _signals(deps: PokeApiDeps) -> dict:
    """Which hypotheses are working over time (hit-rate + mean realized net), plus
    the activation/dormancy view (why there are no live packets today)."""
    opps = lab_mod.build_opportunities(deps, as_of=deps.today)
    return _ok({
        "signals": ledger_mod.signals_report(deps.read_decisions()),
        "activation": lab_mod.activation_report(opps, deps.read_candidates()),
    })


def _candidates(deps: PokeApiDeps) -> dict:
    """Current verified (entry-bearing) candidates + ledger counts. Read-only, 0
    credits. Evidence-only rows are counted but not returned as buy candidates."""
    rows = deps.read_candidates()
    current = candidates_mod.current_entry_candidates(rows)
    items = [candidates_mod.to_opportunity_candidate(r) for r in current.values()]
    return _ok({
        "count": len(items),
        "candidates_seen": len(rows),
        "verified_candidates": len(items),
        "candidates": items,
    })


def _candidates_report(deps: PokeApiDeps) -> dict:
    """The candidate activation / dormancy report: why no live packets, the top
    blockers, and which products are closest."""
    opps = lab_mod.build_opportunities(deps, as_of=deps.today)
    return _ok({"activation": lab_mod.activation_report(opps, deps.read_candidates())})


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
    if segments == ["assets"]:
        return _asset_catalog_error(deps) or _assets(deps)
    if segments == ["cards"]:
        return _asset_catalog_error(deps) or _cards(deps, query)
    if segments == ["opportunities"]:
        return _opportunities(deps)
    if segments == ["paper-decisions"]:
        return _paper_decisions(deps)
    if segments == ["signals"]:
        return _signals(deps)
    if segments == ["candidates"]:
        return _candidates(deps)
    if segments == ["candidates", "report"]:
        return _candidates_report(deps)
    if len(segments) == 2 and segments[0] == "opportunities":
        return _opportunity(deps, segments[1])
    if len(segments) == 3 and segments[0] == "products":
        _, key, leaf = segments
        if leaf == "comp":
            return _comp(deps, key, query)
        if leaf == "history":
            return _history(deps, key)
        if leaf == "momentum":
            return _momentum(deps, key)
    if len(segments) == 3 and segments[0] == "assets":
        _, key, leaf = segments
        if leaf in ("comp", "history", "momentum"):
            guard = _asset_catalog_error(deps)
            if guard is not None:
                return guard
        if leaf == "comp":
            return _asset_comp(deps, key, query)
        if leaf == "history":
            return _asset_history(deps, key)
        if leaf == "momentum":
            return _asset_momentum(deps, key)
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
               decisions_path: Path | None = None, today: str | None = None,
               candidate_for: Callable[[str, dict], dict | None] | None = None,
               candidates_path: Path | None = None,
               assets_path: Path | None = None) -> PokeApiDeps:
    """Wire the real, PPT-free defaults from config. ``today``/``ledger_path``/
    ``decisions_path``/``candidates_path`` are overridable so callers stay
    deterministic in tests.

    ``candidate_for`` is the verified-deal wire. When not injected, it defaults to
    a provider folded from the append-only ``verified_candidates.jsonl`` ledger —
    so a manually-added or manifest-replayed verified candidate flows into
    opportunity scoring automatically. With an empty ledger it returns none, so the
    read API stays honestly dormant on catalog + comp + momentum alone."""
    from .. import config as cfg_mod

    path = ledger_path or (cfg_mod.ROOT / "data" / "poke" / "price_history.jsonl")
    dpath = decisions_path or (cfg_mod.ROOT / "data" / "poke" / "paper_decisions.jsonl")
    cpath = candidates_path or (cfg_mod.ROOT / "data" / "poke" / "verified_candidates.jsonl")
    apath = assets_path or (cfg_mod.ROOT / "data" / "poke" / "assets.yaml")

    def read_observations() -> list[dict]:
        return history_mod.read_ledger(path).observations

    def read_decisions() -> list[dict]:
        return ledger_mod.read_rows(dpath)

    def read_candidates() -> list[dict]:
        return candidates_mod.read_rows(cpath)

    if candidate_for is None:
        candidate_for = candidates_mod.candidate_for_provider(read_candidates())

    if today is None:
        from datetime import date
        today = date.today().isoformat()

    # Load assets defensively: a malformed asset catalog is contained to the asset
    # routes (surfaced via assets_error) so it never takes the sealed catalog
    # offline. This does NOT silently drop — /assets and the asset routes report it.
    try:
        assets = catalog_mod.load_assets(apath)
        assets_error = ""
    except catalog_mod.AssetCatalogError as exc:
        assets = {}
        assets_error = str(exc)
    except Exception as exc:  # noqa: BLE001 - containment guarantee lives here: NO asset
        # catalog load failure (bad encoding, unreadable file, an unforeseen parser
        # error) may take the sealed routes offline. Surfaced honestly via
        # assets_error -> 500 on the asset routes only; never silent, never sealed.
        assets = {}
        assets_error = f"asset catalog load failed: {exc}"

    return PokeApiDeps(
        products=dict(getattr(cfg, "products", {}) or {}),
        read_observations=read_observations,
        comp_provider=ReadFirstCompProvider(cfg),
        today=today,
        cfg=cfg,
        candidate_for=candidate_for,
        read_decisions=read_decisions,
        decisions_path=dpath,
        read_candidates=read_candidates,
        candidates_path=cpath,
        assets=assets,
        card_client=sources_mod.card_client_from_config(cfg),
        assets_error=assets_error,
    )
