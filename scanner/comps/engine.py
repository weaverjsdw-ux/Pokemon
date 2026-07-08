"""CompEngine: fan out to sources, resolve confidence, cache, record history,
emit the legacy quote-dict the existing sweep/scanner pipeline consumes.

Spends zero PPT credits (creditsConsumed always 0). Staleness ladder: spec 4.4.
"""
from __future__ import annotations

import time
from datetime import date
from pathlib import Path
from typing import Any, Callable

from .. import config as cfg_mod
from ..discovery import ledger as ledger_mod
from ..state import State
from . import model
from .ebay import EbayAskSource
from .pricecharting import PriceChartingSource
from .tcgplayer import TcgPlayerSource

_DOWNGRADE = {"high": "medium", "medium": "low", "low": "low"}
_DAY_SECONDS = 86400


class CompEngine:
    def __init__(
        self,
        cfg: Any,
        state: State | None = None,
        tcg_source: Any = None,
        pc_source: Any = None,
        ebay_source: Any = None,
        ledger_path: str | Path | None = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.cfg = cfg
        self._state = state
        self.tcg = tcg_source or TcgPlayerSource(cfg)
        self.pc = pc_source or PriceChartingSource(cfg)
        self.ebay = ebay_source or EbayAskSource(cfg)
        self.ledger_path = Path(ledger_path) if ledger_path else (
            cfg_mod.ROOT / "data" / "poke" / "price_history.jsonl")
        self.clock = clock
        self.sleep = sleep
        self._last_fetch = 0.0

    @classmethod
    def from_config(cls, cfg: Any) -> "CompEngine":
        # Sealed tcg slot: the free TCGCSV mirror when poke.tcgcsv is on (spec §9.2 — its
        # number lifts confidence via the unchanged tcg+pc agreement path); else the dead
        # TcgPlayerSource. TCGCSV stays NON-independent (edge/divergence classification).
        # Lazy import: comps must not import poke_api at module load (cycle-proofing).
        from ..poke_api import tcgcsv as _tcgcsv
        from ..poke_api.tcgcsv_source import TcgCsvSource
        tcg = TcgCsvSource(cfg) if _tcgcsv.tcgcsv_enabled(cfg) else None
        return cls(cfg, tcg_source=tcg)

    @property
    def state(self) -> State:
        if self._state is None:
            self._state = State()
        return self._state

    def estimate(self, product_key: str, product: dict, checked_at: int) -> dict:
        now = int(checked_at)
        ikey = ledger_mod.item_key({
            "set": product.get("set", ""),
            "item": product.get("name") or product_key,
            "variant": "", "grade": "", "condition": "",
        })
        ttl = int(self.cfg.comps.cache_ttl_seconds)
        cached = self.state.comp_cache_get(ikey)
        if cached and now - cached[1] <= ttl:
            return dict(cached[0]) | {"cacheHit": True}

        self._politeness_wait()
        tcg_q = self._safe_quote(self.tcg, product_key, product, now, "tcgplayer")
        pc_q = self._safe_quote(self.pc, product_key, product, now, "pricecharting")
        ebay_a = self._safe_ask(product_key, product, now)

        normalized = model.resolve(
            ikey, model.resale._amount(product.get("msrp")), tcg_q, pc_q, ebay_a,
            date.fromtimestamp(now).isoformat(),
            tolerance_pct=self.cfg.comps.agreement_tolerance_pct,
            floor_sanity_pct=self.cfg.comps.ebay_floor_sanity_pct,
        )
        row = model.to_legacy_row(normalized, product_key, product, now)
        row["creditsConsumed"] = 0

        if normalized.comp is not None:
            self.state.comp_cache_put(ikey, row, ts=now)
            self._append_history(normalized, product, product_key)
            return row
        return self._degraded_or_honest(row, cached, now)

    # -- internals ----------------------------------------------------------

    def _politeness_wait(self) -> None:
        gap = float(getattr(self.cfg.comps, "politeness_seconds", 1.0))
        wait = gap - (self.clock() - self._last_fetch)
        if wait > 0:
            self.sleep(wait)
        self._last_fetch = self.clock()

    def _safe_quote(self, source, product_key, product, now, slug) -> model.CompSourceQuote:
        try:
            return source.fetch(product_key, product, now)
        except Exception as exc:  # a source bug never fails a comp lookup
            return model.CompSourceQuote(
                slug, model.SOLD_DERIVED, "error", None, "",
                date.fromtimestamp(now).isoformat(), detail=str(exc)[:200])

    def _safe_ask(self, product_key, product, now) -> model.EbayAsk:
        try:
            return self.ebay.fetch(product_key, product, now)
        except Exception as exc:
            return model.EbayAsk(model.CompSourceQuote(
                "ebay_api", model.ACTIVE_ASK, "error", None, "",
                date.fromtimestamp(now).isoformat(), detail=str(exc)[:200]))

    def _degraded_or_honest(self, fresh_row, cached, now) -> dict:
        """Spec 4.4: serve cached degraded one tier to 24h; stale+low to 30d; then honest."""
        if not cached:
            return fresh_row
        payload, fetched_at = cached
        age = now - fetched_at
        if payload.get("status") != "ok":
            return fresh_row
        if age <= _DAY_SECONDS:
            confidence = _DOWNGRADE.get(str(payload.get("confidence")), "low")
            return dict(payload) | {
                "confidence": confidence,
                "confidenceLabel": model.resale.CONFIDENCE_LABELS[confidence],
                "detail": "refetch failed; serving cached comp (degraded one tier)",
            }
        if age <= int(self.cfg.poke.staleness_days) * _DAY_SECONDS:
            return dict(payload) | {
                "confidence": "low",
                "confidenceLabel": model.resale.CONFIDENCE_LABELS["low"],
                "detail": "stale cached comp (>24h old); refetch failed",
                "stale": True,
            }
        return fresh_row

    def _append_history(self, n: model.NormalizedComp, product: dict, product_key: str) -> None:
        for quote in n.sources:
            if quote.status != "ok" or quote.price is None:
                continue
            ledger_mod.append_observation(self.ledger_path, {
                "kind": "market_comp",
                "set": product.get("set", ""),
                "item": product.get("name") or product_key,
                "variant": "", "grade": "", "condition": "",
                "source_url": quote.url,
                "capture_date": n.captured_at,
                "comp": quote.price,
                "comp_confidence": n.confidence,
                "source": quote.source,
            })
