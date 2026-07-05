"""Verified candidate intake for the Money Hypothesis Lab (Phase C activation).

This is the *verified-entry wire* the lab was built to consume: a normalized
``VerifiedCandidate`` that carries an ``entry_price`` ONLY when there is explicit
observed price + stock evidence. Without that evidence a candidate is still a
valid *evidence* record — it just never becomes a buy row (``entry_price`` is
``None``), so downstream it can WATCH/REJECT but never PAPER_BUY /
LIVE_PACKET_ELIGIBLE. The entry gate mirrors ``discovery/verify.alert_allowed``
so "buyable" means the same thing here as on the alert path.

Records are one immutable JSON object per line in
``data/poke/verified_candidates.jsonl`` (a SEPARATE file from the
market-observation ``price_history.jsonl`` and the ``paper_decisions.jsonl``
ledger). Idempotent by a sha256 ``candidate_id``, mirroring
``scanner/discovery/ledger.py`` and ``scanner/poke_api/paper_ledger.py``. Pure:
no network, no clock (``observed_at`` is passed in), no hindsight mutation.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from .. import resale

# Positive-buyable stock vocabulary. ``verified_buyable`` is the operator-facing
# manual value; ``in_stock``/``limited`` are the discovery-schema positives
# (schema.POSITIVE_STOCK) that a manifest replay carries. Anything else
# (unverifiable, parser_suspect, out_of_stock, price_mismatch, unknown) is
# evidence, never an entry.
VERIFIED_STOCK = frozenset({"verified_buyable", "in_stock", "limited"})


@dataclass(frozen=True)
class VerifiedCandidate:
    candidate_id: str
    source: str
    product_key: str
    listing_id: str
    item_name: str
    entry_price: float | None
    buy_url: str
    observed_at: str
    stock_status: str
    stock_evidence: str
    stock_checked_at: str
    evidence_method: str
    source_url: str
    retailer: str
    confidence: str
    asset_class: str = "sealed"
    # Session E — precise raw/graded identity so an asset candidate never collides
    # with a sealed product (or a different condition/grade) that shares a key string.
    # candidate_id does NOT hash these, so existing sealed ids/rows are unchanged.
    asset_key: str = ""
    condition: str = ""
    grade_key: str = ""
    entry_verified: bool = False   # True only when the entry-evidence gate passes
    reason: str = ""               # why NOT entry-verified (the blocker), else ""
    raw_snapshot: dict = field(default_factory=dict)


# ---------------------------------------------------------------- entry gate

def entry_evidence_ok(*, stock_status, buy_url, entry_price, stock_evidence,
                      stock_checked_at) -> tuple[bool, str]:
    """(ok, reason). STOP-class gate — an entry_price is only legitimate with a
    positive-buyable stock status, an observed price > 0, a buy link, evidence
    text, and a check timestamp. Mirrors ``verify.alert_allowed``; ``reason``
    names every failed condition (never a silent drop)."""
    problems: list[str] = []
    if str(stock_status or "").lower() not in VERIFIED_STOCK:
        problems.append(f"stock_status {stock_status!r} is not verified-buyable")
    price = resale._amount(entry_price)
    if price is None or price <= 0:
        problems.append("no observed entry price")
    if not buy_url:
        problems.append("no buy_url")
    if not stock_evidence:
        problems.append("no stock_evidence")
    if not stock_checked_at:
        problems.append("no stock_checked_at")
    return (not problems), "; ".join(problems)


# ---------------------------------------------------------------- ids & build

def _stable_listing_id(*parts: str) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:16]


def candidate_id(source, product_key, listing_id, observed_at, entry_price,
                 buy_url, stock_status) -> str:
    """Stable, evidence-sensitive identity. An identical re-add is a no-op; a
    corrected price/evidence appends a NEW row (append-only, no mutation)."""
    price = resale._amount(entry_price)
    price_tag = f"{price:.2f}" if price is not None else "none"
    raw = "|".join(str(p) for p in (
        source, product_key, listing_id, observed_at, price_tag, buy_url, stock_status))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def make_candidate(*, source, product_key, listing_id="", item_name="",
                   entry_price=None, buy_url="", observed_at="", stock_status="unknown",
                   stock_evidence="", stock_checked_at="", evidence_method="",
                   source_url="", retailer="", confidence="none", asset_class="sealed",
                   asset_key="", condition="", grade_key="",
                   raw_snapshot=None) -> VerifiedCandidate:
    """Normalize a raw candidate into a ``VerifiedCandidate``. Never rejects — a
    candidate that fails the entry gate is kept as an evidence row with
    ``entry_price=None`` and ``entry_verified=False`` (the blocker in ``reason``).

    ``asset_key`` / ``condition`` / ``grade_key`` (Session E) carry the precise
    raw/graded identity for an asset candidate; they are absent ("") for sealed."""
    listing_id = listing_id or _stable_listing_id(source, buy_url or source_url or item_name)
    ok, reason = entry_evidence_ok(
        stock_status=stock_status, buy_url=buy_url, entry_price=entry_price,
        stock_evidence=stock_evidence, stock_checked_at=stock_checked_at)
    price = resale._amount(entry_price) if ok else None
    cid = candidate_id(source, product_key, listing_id, observed_at, entry_price,
                       buy_url, stock_status)
    return VerifiedCandidate(
        candidate_id=cid, source=str(source), product_key=str(product_key),
        listing_id=str(listing_id), item_name=str(item_name or product_key),
        entry_price=price, buy_url=str(buy_url), observed_at=str(observed_at),
        stock_status=str(stock_status), stock_evidence=str(stock_evidence),
        stock_checked_at=str(stock_checked_at), evidence_method=str(evidence_method),
        source_url=str(source_url), retailer=str(retailer), confidence=str(confidence),
        asset_class=str(asset_class or "sealed"), asset_key=str(asset_key or ""),
        condition=str(condition or ""), grade_key=str(grade_key or ""),
        entry_verified=ok, reason="" if ok else reason, raw_snapshot=dict(raw_snapshot or {}))


# ---------------------------------------------------------------- ledger

def build_record(candidate: VerifiedCandidate) -> dict:
    return {"kind": "candidate", **asdict(candidate)}


def read_rows(path) -> list[dict]:
    """Read the JSONL candidate ledger safely. Missing file -> empty; malformed /
    non-object lines skipped; blank lines ignored. File order == append order."""
    path = Path(path)
    if not path.exists():
        return []
    rows: list[dict] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            rows.append(rec)
    return rows


def _existing_ids(path) -> set[str]:
    return {r["candidate_id"] for r in read_rows(path) if "candidate_id" in r}


def append_candidate(path, candidate: VerifiedCandidate) -> bool:
    """Append one candidate; idempotent by ``candidate_id`` (re-append is a no-op).
    Old records are never rewritten."""
    path = Path(path)
    if candidate.candidate_id in _existing_ids(path):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(build_record(candidate), ensure_ascii=False) + "\n")
    return True


# ---------------------------------------------------------------- folds / wire

def to_opportunity_candidate(record: dict) -> dict:
    """Shape a stored candidate record into the ``candidate`` dict
    ``opportunities.build_opportunity`` consumes. Carries the full provenance so
    it can be preserved in the paper decision's ``input_snapshot``."""
    return {
        "verified_price": record.get("entry_price"),
        "retailer": record.get("retailer"),
        "source": record.get("source"),
        "asset_class": record.get("asset_class") or "sealed",
        "asset_key": record.get("asset_key") or "",
        "condition": record.get("condition") or "",
        "grade_key": record.get("grade_key") or "",
        "item_name": record.get("item_name"),
        "url": record.get("buy_url") or record.get("source_url"),
        "matched_product_key": record.get("product_key"),
        "candidate_id": record.get("candidate_id"),
        "listing_id": record.get("listing_id"),
        "stock_status": record.get("stock_status"),
        "stock_evidence": record.get("stock_evidence"),
        "stock_checked_at": record.get("stock_checked_at"),
        "evidence_method": record.get("evidence_method"),
        "observed_at": record.get("observed_at"),
        "confidence": record.get("confidence"),
    }


_ASSET_CLASSES = frozenset({"raw", "graded"})


def current_entry_candidates(rows) -> dict[str, dict]:
    """Latest entry-verified SEALED candidate per product_key (latest wins by
    ``observed_at``; ties -> last appended). Evidence-only rows are ignored here —
    they inform the activation report, not the buy wire.

    Session E: raw/graded rows are EXCLUDED so a sealed opportunity never absorbs an
    asset candidate that shares a key string (the folds are disjoint by asset_class)."""
    out: dict[str, dict] = {}
    for r in rows:
        if not r.get("entry_verified"):
            continue
        if str(r.get("asset_class") or "sealed") in _ASSET_CLASSES:
            continue
        key = r.get("product_key")
        if not key:
            continue
        cur = out.get(key)
        if cur is None or str(r.get("observed_at") or "") >= str(cur.get("observed_at") or ""):
            out[key] = r
    return out


def current_asset_entry_candidates(rows) -> dict[str, dict]:
    """Latest entry-verified RAW/GRADED candidate per ``asset_key`` (Session E). The
    counterpart of ``current_entry_candidates`` for the asset keyspace — keyed on the
    explicit ``asset_key`` (never ``product_key``, which may equal a sealed key)."""
    out: dict[str, dict] = {}
    for r in rows:
        if not r.get("entry_verified"):
            continue
        if str(r.get("asset_class") or "sealed") not in _ASSET_CLASSES:
            continue
        key = r.get("asset_key")
        if not key:
            continue
        cur = out.get(key)
        if cur is None or str(r.get("observed_at") or "") >= str(cur.get("observed_at") or ""):
            out[key] = r
    return out


def candidate_for_provider(rows) -> Callable[[str, dict], dict | None]:
    """Build a ``candidate_for(product_key, product)`` provider from ledger rows —
    the wire ``router.build_deps`` injects so verified candidates flow into
    opportunity scoring. Returns only entry-verified candidates; a product with no
    verified candidate returns None (honest dormancy)."""
    current = current_entry_candidates(rows)

    def candidate_for(product_key: str, product: dict) -> dict | None:
        rec = current.get(product_key)
        return to_opportunity_candidate(rec) if rec else None

    return candidate_for


def _asset_identity_matches(rec: dict, asset: dict) -> bool:
    """A stored asset candidate matches an asset only when class AND identity agree —
    raw on ``condition``, graded on ``grade_key`` — so a psa10 candidate never
    attaches to a psa9 slab and a graded candidate never attaches to a raw single."""
    asset_class = str(asset.get("asset_class") or "").strip().lower()
    if str(rec.get("asset_class") or "") != asset_class:
        return False
    if asset_class == "graded":
        return str(rec.get("grade_key") or "") == str(asset.get("grade_key") or "")
    if asset_class == "raw":
        return (str(rec.get("condition") or "").lower()
                == str(asset.get("condition") or "").lower())
    return False


def asset_candidate_for_provider(rows) -> Callable[[str, dict], dict | None]:
    """Build an ``asset_candidate_for(asset_key, asset)`` provider (Session E) — the
    raw/graded counterpart of ``candidate_for_provider``. Returns an entry-verified
    asset candidate ONLY when its class + identity match the asset (collision-proof),
    else None (honest dormancy)."""
    current = current_asset_entry_candidates(rows)

    def asset_candidate_for(asset_key: str, asset: dict) -> dict | None:
        rec = current.get(asset_key)
        if not rec or not _asset_identity_matches(rec, asset):
            return None
        return to_opportunity_candidate(rec)

    return asset_candidate_for


# ---------------------------------------------------------------- manifest replay

@dataclass
class ReplayResult:
    """Outcome of replaying a discovery board/manifest into candidate evidence.

    ``input_kind`` distinguishes a real board from a wrong-file bare manifest so
    "0 candidates" is never confused with "scanned nothing" (no silent drops).
    ``candidates`` are entry-verified; ``blocked`` and ``unmatched`` are evidence
    the report surfaces as missed/blocked, never promoted to buys."""
    input_kind: str = "board"
    note: str = ""
    scanned: int = 0
    candidates: list = field(default_factory=list)   # list[VerifiedCandidate]
    blocked: list = field(default_factory=list)       # list[dict]
    unmatched: list = field(default_factory=list)     # list[dict]

    def summary(self) -> dict:
        by_status: dict[str, int] = {}
        for b in self.blocked:
            s = str(b.get("stock_status") or "unknown")
            by_status[s] = by_status.get(s, 0) + 1
        return {
            "input_kind": self.input_kind, "note": self.note, "scanned": self.scanned,
            "verified_candidates": len(self.candidates), "blocked": len(self.blocked),
            "unmatched": len(self.unmatched), "blocked_by_stock_status": by_status,
        }


def _deal_is_buyable(deal: dict) -> tuple[bool, str]:
    """A board row is a verified-buyable entry iff it clears the entry gate on its
    OWN stock evidence — never on ``deal_price``/``price_confidence`` (a sealed
    board carries MSRP-as-``deal_price`` with ``price_confidence: verified`` for
    the *comp*, which is NOT a purchasable entry)."""
    return entry_evidence_ok(
        stock_status=deal.get("stock_status"), buy_url=deal.get("buy_url"),
        entry_price=deal.get("deal_price"), stock_evidence=deal.get("stock_evidence"),
        stock_checked_at=deal.get("stock_checked_at"))


def replay_deals(deals, catalog, *, source="manifest_replay", set_watch=None,
                 observed_at="") -> ReplayResult:
    """Classify each board deal into an entry-verified candidate, a blocked
    evidence row, or an unmatched-but-buyable row (reported, never dropped)."""
    from ..discovery.candidates import match_title   # lazy: avoid load-time coupling
    set_watch = list(set_watch or [])
    result = ReplayResult(scanned=len(deals))
    for deal in deals:
        item = str(deal.get("item") or deal.get("item_name") or "")
        ok, reason = _deal_is_buyable(deal)
        if not ok:
            result.blocked.append({
                "item": item, "stock_status": str(deal.get("stock_status") or "unknown"),
                "reason": reason or (deal.get("stock_evidence") or "not verified buyable"),
                "buy_url": str(deal.get("buy_url") or "")})
            continue
        product_key, _matched_set = match_title(item, catalog, set_watch)
        if product_key is None:
            result.unmatched.append({
                "item": item, "buy_url": str(deal.get("buy_url") or ""),
                "reason": "verified buyable but no catalog product_key match"})
            continue
        result.candidates.append(make_candidate(
            source=source, product_key=product_key, item_name=item,
            entry_price=deal.get("deal_price"), buy_url=deal.get("buy_url"),
            observed_at=observed_at or str(deal.get("captured_at") or ""),
            stock_status=deal.get("stock_status"), stock_evidence=deal.get("stock_evidence"),
            stock_checked_at=deal.get("stock_checked_at"),
            evidence_method=str(deal.get("stock_method") or ""),
            source_url=str(deal.get("source_url") or ""), retailer=str(deal.get("retailer") or ""),
            confidence=str(deal.get("comp_confidence") or "none"),
            asset_class=str(deal.get("asset_class") or "sealed"),
            raw_snapshot={"pct_off": deal.get("pct_off"), "market_comp": deal.get("market_comp"),
                          "scanner_verdict": deal.get("scanner_verdict")}))
    return result


def extract_board_deals(obj: dict, *, manifest_path=None) -> tuple[list, str, str]:
    """(deals, input_kind, note). Resolves the three real shapes: a pipeline
    manifest (``board.deals``), a board file (top-level ``deals``), or a bare
    sealed/sweep manifest whose deals live in the sibling ``<sweep_id>.json``.
    A manifest with no deals and no resolvable sibling is flagged, not read as 0."""
    board = obj.get("board")
    if isinstance(board, dict) and isinstance(board.get("deals"), list):
        return board["deals"], "manifest_embedded_board", ""
    if isinstance(obj.get("deals"), list):
        return obj["deals"], "board", ""
    sweep_id = obj.get("sweep_id")
    if sweep_id and manifest_path is not None:
        sibling = Path(manifest_path).parent / f"{sweep_id}.json"
        if sibling.exists():
            try:
                sib = json.loads(sibling.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                sib = {}
            if isinstance(sib.get("deals"), list):
                return sib["deals"], "manifest_sibling_board", f"resolved sibling board {sibling.name}"
        return [], "manifest_no_deals", (
            f"manifest has no deals array; sibling board {sweep_id}.json not found — "
            f"point --manifest at the board file itself")
    return [], "no_deals", "input has no deals array and no resolvable sibling board"


def load_and_replay(path, catalog, *, source="manifest_replay", set_watch=None,
                    observed_at="") -> ReplayResult:
    """Read a board/manifest JSON at ``path`` and replay its deals into candidate
    evidence. The catalog resolves each buyable row to a product_key."""
    obj = json.loads(Path(path).read_text(encoding="utf-8"))
    deals, input_kind, note = extract_board_deals(obj, manifest_path=path)
    result = replay_deals(deals, catalog, source=source, set_watch=set_watch,
                          observed_at=observed_at)
    result.input_kind = input_kind
    result.note = note
    return result


# ---------------------------------------------------------------- eBay readiness (C.6)

def from_ebay_browse_item(item: dict, product_key: str, *, observed_at="") -> VerifiedCandidate:
    """Map one eBay Browse API item into a ``VerifiedCandidate``. The advertised
    BIN price is NOT a verified purchasable entry until the item-lookup keyset
    verifies live stock/price — so, absent that live check, an eBay candidate is an
    evidence row (``stock_status='unverifiable'``, ``entry_price`` stripped), never
    a fabricated buy. The keyed live check is a later slice."""
    price = item.get("price")
    if isinstance(price, dict):
        price = price.get("value")
    return make_candidate(
        source="ebay_browse", product_key=product_key,
        listing_id=str(item.get("itemId") or item.get("legacyItemId") or ""),
        item_name=str(item.get("title") or ""), entry_price=price,
        buy_url=str(item.get("itemWebUrl") or item.get("itemAffiliateWebUrl") or ""),
        observed_at=observed_at, stock_status="unverifiable", stock_evidence="",
        stock_checked_at="", evidence_method="ebay_browse:no_live_check",
        source_url=str(item.get("itemWebUrl") or ""), retailer="eBay", confidence="none",
        raw_snapshot={"buyingOptions": item.get("buyingOptions") or item.get("buying_options")})


def ebay_candidate_source(cfg, *, product_key="", browse_items=None,
                          observed_at="") -> dict:
    """Readiness hook (C.6). The candidate wire is ready to accept eBay Browse
    records, but only through an explicit call with a configured keyset. Returns a
    clean status dict — ``not_configured`` (``NEEDS_API_KEY``) when no keyset is
    present — and never a fabricated candidate. When a keyset IS present, injected
    ``browse_items`` are mapped to (evidence-only) candidates; live Browse search is
    a later slice, so none are fetched here."""
    token = str(getattr(cfg, "ebay_browse_api_token", "") or "").strip()
    client_id = str(getattr(cfg, "ebay_client_id", "") or "").strip()
    client_secret = str(getattr(cfg, "ebay_client_secret", "") or "").strip()
    if not (token or (client_id and client_secret)):
        return {"status": "not_configured",
                "detail": "NEEDS_API_KEY: no eBay Browse keyset (ebay_browse_api_token or "
                          "ebay_client_id/secret); candidate wire ready but not activated",
                "candidates": []}
    items = list(browse_items or [])
    cands = [from_ebay_browse_item(it, product_key, observed_at=observed_at) for it in items]
    return {"status": "configured",
            "detail": f"eBay keyset present; mapped {len(cands)} injected Browse item(s) to "
                      "evidence-only candidates (live keyed stock/price check is a later slice)",
            "candidates": [build_record(c) for c in cands]}
