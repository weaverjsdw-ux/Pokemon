"""Personal edge layer (Session E) — decision policy, source posture, and the
first-class ``EdgePacket``.

E is the program's OWN decision layer on top of the owned ``/api/poke`` evidence
spine (comp + momentum + verified candidates + asset history). It is not a PPT
clone: external/PPT output is an optional adapter or an off-hot-path audit oracle,
never a source of truth here, never on a read path (structurally 0 credits).

Doctrine carried from Phase C, verbatim:
* Money math is the exact alert-path composition (``opportunities.compute_margin``
  -> ``margin.net_margin`` + ``verdict.buy_verdict``). No new math.
* Price accuracy is STOP-class: no verified entry price or no comp => dollar fields
  are ``None`` (never fabricated, never MSRP-as-if-a-price).
* ``LIVE_PACKET_ELIGIBLE`` is strictly stricter than ``PAPER_BUY`` and reachable
  ONLY through the verified evidence spine: verified entry + attributed comp +
  fresh data + sufficient confidence + fee-adjusted ``BUY`` verdict + the stricter
  live floor + a live-eligible trade type.

What E adds over D: raw/graded singles can become buy-shaped, but ONLY through the
new E verified-entry route (a verified asset candidate). A D-era raw/graded
WATCH-with-comp row is NEVER promoted to live here — ``opportunities.py`` (the D
layer) is untouched and keeps its "assets never live in D" guarantee.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .. import margin as margin_mod
from .. import resale
from . import asset_model as asset_model_mod
from . import grading_ev as gev_mod
from . import history as history_mod
from . import lab as lab_mod
from . import model as model_mod
from . import opportunities as opp

# Edge trade taxonomy: the sealed + D asset types, plus the NEW E verified-entry
# arbitrage types for singles and the raw grading-EV type. Only the three
# ``*_arbitrage`` types are ever live-eligible.
LIVE_ELIGIBLE_EDGE: set[str] = {
    "sealed_retail_arbitrage", "raw_verified_arbitrage", "graded_verified_arbitrage"}

EDGE_TRADE_TYPES: dict[str, str] = dict(opp.TRADE_TYPES)
EDGE_TRADE_TYPES.update({
    "raw_verified_arbitrage":
        "raw single with a verified buyable entry materially below current raw comp",
    "graded_verified_arbitrage":
        "graded slab with a verified buyable entry materially below current graded comp",
    "raw_grading_ev":
        "buy raw, grade, sell the slab — grading EV on an operator gem-rate assumption",
})

# Source-slug provenance classes (Slice E). External-origin = a paid card provider;
# local-origin = our own / free-fetch sources; ask = an active listing (context only).
_EXTERNAL_SLUGS = frozenset({"ppt_cards", "tcgcsv"})
# NOTE: legacy "tcgplayer" stays in _LOCAL_SLUGS below — same lineage as tcgcsv but inert
# (that source is always-blocked/dead). tcgcsv is the live external-footing reference.
_LOCAL_SLUGS = frozenset({"tcgplayer", "pricecharting", "inhouse", "ledger", "ledger latest"})
_ASK_SLUGS = frozenset({"ebay"})


# ---------------------------------------------------------------- source posture (E)

def _source_slugs(comp: dict) -> list[str]:
    out = []
    for s in comp.get("sources") or []:
        if isinstance(s, dict) and s.get("source"):
            out.append(str(s["source"]).strip().lower())
    return out


def source_posture(comp: dict) -> list[str]:
    """Deterministic posture tags derived from the comp's OWN data provenance (source
    slugs / status / staleness) — never from live-call state (read paths never call
    external). Tags may co-apply. ``ask_only_context`` = an active ask with no
    sold-derived estimate (an ask is context, never sold-comp truth)."""
    estimate = comp.get("estimate")
    slugs = _source_slugs(comp)
    has_ext = any(s in _EXTERNAL_SLUGS for s in slugs)
    has_local = any(s in _LOCAL_SLUGS for s in slugs)
    has_ask = any(s in _ASK_SLUGS for s in slugs)
    sold_count = sum(1 for s in slugs if s in _EXTERNAL_SLUGS or s in _LOCAL_SLUGS)

    tags: list[str] = []
    if estimate is None:
        if has_ask and not (has_ext or has_local):
            tags.append("ask_only_context")
        else:
            tags.append("missing_comp")
    else:
        if has_ext and has_local:
            tags.append("local_plus_external_audit")
        elif has_ext:
            tags.append("external_only")
        elif has_local:
            tags.append("local_only")
        if sold_count == 1:
            tags.append("single_source")
    if comp.get("stale"):
        tags.append("stale_comp")
    return tags


def provider_dependency(comp: dict) -> dict:
    """Provider-dependency flags for the packet. ``used_external_on_read`` is always
    False (read paths spend 0 credits); the rest are provenance facts."""
    slugs = _source_slugs(comp)
    has_ext = any(s in _EXTERNAL_SLUGS for s in slugs)
    has_local = any(s in _LOCAL_SLUGS for s in slugs)
    return {
        "used_external_on_read": False,
        "comp_is_external_origin": has_ext,
        "external_only": has_ext and not has_local,
        "requires_external_refresh": comp.get("estimate") is None,
    }


# ---------------------------------------------------------------- decision policy (C)

def _missing_live_reason(net, roi, confidence, stale, cfg) -> str:
    """Why a BUY-verdict arbitrage is PAPER not LIVE (the closest live blocker)."""
    if stale:
        return "stale comp; not live-eligible"
    if net is None or net < cfg.opportunity.live_min_expected_net:
        return "expected net below live floor"
    if roi is None or roi < cfg.opportunity.live_min_roi_pct:
        return "roi below live floor"
    if not opp._confidence_ge(confidence, cfg.opportunity.live_min_confidence):
        return "confidence below live floor"
    return "paper buy"


def decide_edge(*, asset_class, market_comp, stale, entry_price, verdict_tier,
                expected_net, expected_roi_pct, latest_confidence, trade_type, cfg):
    """Total edge decision across sealed / raw / graded. Returns
    ``(hint, reason, blockers)``; never raises. Hints:
    ``REJECT | WATCH | DATA_NEEDED | PAPER_BUY | LIVE_PACKET_ELIGIBLE``."""
    if market_comp is None:
        return "DATA_NEEDED", "no comp - cannot value this subject (STOP-class)", ["no comp"]

    # A stale comp is never safe to act on — WATCH before any buy-shaping (defense in
    # depth: classify normally demotes stale to a *_stale/watch type, but decide_edge
    # must not depend on that to keep the live gate honest).
    if stale:
        return "WATCH", "stale comp; refresh before acting", ["stale comp"]

    live_eligible = trade_type in LIVE_ELIGIBLE_EDGE
    live_clear = (
        expected_net is not None and expected_roi_pct is not None
        and expected_net >= cfg.opportunity.live_min_expected_net
        and expected_roi_pct >= cfg.opportunity.live_min_roi_pct
        and opp._confidence_ge(latest_confidence, cfg.opportunity.live_min_confidence)
    )
    # A verified-entry arbitrage type with an actual entry is the only buy-shaped path.
    if live_eligible and entry_price is not None:
        if verdict_tier == "BUY" and live_clear:
            return "LIVE_PACKET_ELIGIBLE", "verified buyable + clears live floor", []
        if verdict_tier == "BUY":
            return "PAPER_BUY", _missing_live_reason(
                expected_net, expected_roi_pct, latest_confidence, stale, cfg), []
        if verdict_tier == "SKIP":
            return "REJECT", "fee-adjusted margin below skip floor", []
        return "WATCH", "thin margin / capped confidence", []

    # Everything else: comp present but not buy-shaped (evidence, never live).
    if entry_price is None:
        return "WATCH", "comp present but no verified entry price", ["no verified entry price"]
    return "WATCH", "no current actionable edge", []


# ---------------------------------------------------------------- EdgePacket (A)

@dataclass(frozen=True)
class EdgePacket:
    """A first-class personal-edge packet: an explainable decision over one subject
    (sealed product or raw/graded asset), understandable without reading internals.
    Every numeric field carries provenance (``comp_provenance`` / ``entry_provenance``
    / ``grading_ev``) or is ``None`` — STOP-class."""
    edge_packet_id: str
    opportunity_id: str          # == edge_packet_id, so it unifies with the paper ledger
    subject_key: str             # product_key (sealed) or asset_key (raw/graded)
    subject_kind: str            # "product" | "asset"
    asset_class: str             # "sealed" | "raw" | "graded"
    name: str
    as_of: str
    thesis: str
    trade_type: str
    decision_hint: str           # REJECT | WATCH | DATA_NEEDED | PAPER_BUY | LIVE_PACKET_ELIGIBLE
    decision_reason: str
    score: float
    blockers: list = field(default_factory=list)
    evidence: list = field(default_factory=list)
    risks: list = field(default_factory=list)
    source_stack: list = field(default_factory=list)
    source_posture: list = field(default_factory=list)
    comp_provenance: dict | None = None
    entry_provenance: dict | None = None
    expected_net: float | None = None
    expected_roi_pct: float | None = None
    verdict_tier: str = "n/a"
    momentum_status: str = ""
    momentum_delta_pct: float | None = None
    grading_ev: dict | None = None
    provider_dependency: dict = field(default_factory=dict)
    status: dict = field(default_factory=dict)
    input_snapshot: dict = field(default_factory=dict)
    # asset identity (None for sealed)
    condition: str | None = None
    grader: str | None = None
    grade: str | None = None
    card_number: str | None = None


def comp_provenance(comp: dict) -> dict | None:
    """Comp attribution block, or None when there is no comp (STOP-class)."""
    if comp.get("estimate") is None:
        return None
    return {
        "estimate": comp.get("estimate"),
        "confidence": str(comp.get("confidence") or "none"),
        "basis": str(comp.get("compBasis") or comp.get("basis") or ""),
        "primary_source": opp._primary_source(comp),
        "checked_at": comp.get("checkedAt"),
        "stale": bool(comp.get("stale")),
    }


def entry_provenance(candidate: dict | None) -> dict | None:
    """Verified-entry attribution block, or None when there is no verified entry."""
    if not candidate or resale._amount(candidate.get("verified_price")) is None:
        return None
    return {
        "entry_price": resale._amount(candidate.get("verified_price")),
        "retailer": candidate.get("retailer"),
        "source": candidate.get("source"),
        "candidate_id": candidate.get("candidate_id"),
        "buy_url": candidate.get("url"),
        "stock_evidence": candidate.get("stock_evidence"),
        "stock_checked_at": candidate.get("stock_checked_at"),
        "observed_at": candidate.get("observed_at"),
    }


def _source_stack(comp: dict) -> list[str]:
    return _source_slugs(comp)


def _status_block(comp: dict, momentum: dict) -> dict:
    return {
        "stale": bool(comp.get("stale")) or bool(momentum.get("stale")),
        "missing_comp": comp.get("estimate") is None,
        "confidence": str(comp.get("confidence") or "none"),
    }


def _fee_model(cfg) -> margin_mod.FeeModel:
    return margin_mod.FeeModel(
        ebay_fvf_pct=cfg.ebay_fvf_pct, ebay_fixed_fee=cfg.ebay_fixed_fee,
        local_haircut_pct=cfg.local_haircut_pct)


def build_sealed_packet(product_key, product, comp, momentum, candidate, cfg, *, as_of) -> dict:
    """Build a sealed edge packet by layering the edge decision + posture over the
    Phase C opportunity (reuses its facts + money math; no new math). Returns a plain
    dict (``asdict``) so it is JSON-serializable and ledger-ready."""
    o = opp.build_opportunity(product_key, product, comp, momentum, candidate, cfg, as_of=as_of)
    hint, reason, edge_blockers = decide_edge(
        asset_class="sealed", market_comp=o.market_comp, stale=o.stale,
        entry_price=o.entry_price, verdict_tier=o.verdict_tier,
        expected_net=o.expected_net, expected_roi_pct=o.expected_roi_pct,
        latest_confidence=o.latest_confidence, trade_type=o.trade_type, cfg=cfg)

    packet = EdgePacket(
        edge_packet_id=o.opportunity_id,
        opportunity_id=o.opportunity_id,
        subject_key=product_key,
        subject_kind="product",
        asset_class="sealed",
        name=o.name,
        as_of=as_of,
        thesis=o.hypothesis,
        trade_type=o.trade_type,
        decision_hint=hint,
        decision_reason=reason,
        score=o.score,
        blockers=edge_blockers,
        evidence=list(o.evidence),
        risks=list(o.risks),
        source_stack=_source_stack(comp),
        source_posture=source_posture(comp),
        comp_provenance=comp_provenance(comp),
        entry_provenance=entry_provenance(candidate),
        expected_net=o.expected_net,
        expected_roi_pct=o.expected_roi_pct,
        verdict_tier=o.verdict_tier,
        momentum_status=o.momentum_status,
        momentum_delta_pct=o.momentum_delta_pct,
        grading_ev=None,
        provider_dependency=provider_dependency(comp),
        status=_status_block(comp, momentum),
        input_snapshot=o.input_snapshot,
    )
    return asdict(packet)


def classify_asset_edge_trade(asset_class, market_comp, momentum_status, entry_price) -> str:
    """First-match-wins edge classification for a raw/graded asset. A verified entry
    + a comp is the ONLY path to a live-eligible ``*_verified_arbitrage`` type."""
    prefix = "graded" if asset_class == "graded" else "raw"
    if market_comp is None:
        return f"{prefix}_catalog_gap"
    if entry_price is not None:
        return f"{prefix}_verified_arbitrage"
    if momentum_status == "no_history":
        return f"{prefix}_catalog_gap"
    return f"{prefix}_market_watch"


def build_asset_packet(asset_key, asset, comp, momentum, asset_candidate, cfg, *,
                       as_of, graded_sibling_comp=None, target_grade="",
                       downside_comp=None, gem_rate=None, gem_rate_source="") -> dict:
    """Build a raw/graded edge packet. A raw/graded single becomes buy-shaped ONLY
    through a verified asset candidate (the E route); with no verified entry it stays
    WATCH/DATA_NEEDED evidence — never live off a comp alone. Raw packets carry a
    grading-EV block (enrichment); a grading-EV-actionable raw with a verified entry
    lifts to PAPER_BUY (never LIVE — the gem rate is an operator assumption)."""
    asset_class = str(asset.get("asset_class") or "raw").strip().lower()
    market_comp = comp.get("estimate")
    confidence = str(comp.get("confidence") or "none")
    stale = bool(comp.get("stale")) or bool(momentum.get("stale"))
    momentum_status = str(momentum.get("status") or "no_history")
    latest_confidence = confidence if confidence != "none" else None

    entry_price = (resale._amount(asset_candidate.get("verified_price"))
                   if asset_candidate else None)
    discount_pct = None
    if entry_price is not None and market_comp is not None and market_comp > 0:
        discount_pct = round((market_comp - entry_price) / market_comp * 100.0, 2)

    expected_net, expected_roi_pct, verdict_tier = opp.compute_margin(
        entry_price, market_comp, confidence, asset, cfg)

    trade_type = classify_asset_edge_trade(asset_class, market_comp, momentum_status, entry_price)
    hint, reason, blockers = decide_edge(
        asset_class=asset_class, market_comp=market_comp, stale=stale,
        entry_price=entry_price, verdict_tier=verdict_tier, expected_net=expected_net,
        expected_roi_pct=expected_roi_pct, latest_confidence=latest_confidence,
        trade_type=trade_type, cfg=cfg)

    # Grading EV (raw only). Gem rate is read from the asset unless the caller overrides;
    # absent => the EV block blocks with a named blocker (never invented).
    grading = None
    if asset_class == "raw":
        gem = gem_rate if gem_rate is not None else asset.get("gem_rate")
        gem_src = gem_rate_source or str(asset.get("gem_rate_source") or "")
        grading = gev_mod.grading_ev(
            raw_entry=entry_price, raw_comp=market_comp, graded_comp=graded_sibling_comp,
            grading_fee=cfg.poke.grading_cost_all_in, gem_rate=gem, fees=_fee_model(cfg),
            tax_rate=cfg.tax_rate, est_shipping=opp._shipping_for(asset, cfg),
            target_grade=target_grade, downside_comp=downside_comp,
            buy_floor_net=cfg.buy_floor_net, gem_rate_basis=gem_src,
            grading_fee_basis=(f"PSA all-in ${cfg.poke.grading_cost_all_in:.2f} "
                               f"(config poke.grading_cost_all_in; PSA Regular tier, "
                               f"value tiers paused 2026-06)"))
        # A grading-EV-actionable raw with a verified entry is the buy reason when the
        # raw-flip route did not already produce a buy. Capped at PAPER_BUY (never LIVE).
        if (grading["status"] == "actionable" and entry_price is not None
                and not stale and hint not in ("LIVE_PACKET_ELIGIBLE", "PAPER_BUY")):
            trade_type = "raw_grading_ev"
            hint = "PAPER_BUY"
            reason = "grading EV clears the paper buy floor: " + grading["reason"]
            expected_net = grading["expected_net"]
            expected_roi_pct = grading["expected_roi_pct"]
            verdict_tier = "BUY"
            blockers = []
        elif (grading["status"] == "blocked" and grading["blockers"]
              and market_comp is not None and graded_sibling_comp is not None):
            # Only surface grading-EV blockers on the packet when the raw+graded comps
            # both exist (grading EV is genuinely one operator assumption — the gem rate
            # — away). Avoids cluttering an unmapped/no-comp asset's top-level blockers.
            blockers = list(blockers) + [f"grading EV: {b}" for b in grading["blockers"]]

    # evidence + risks reuse the D asset opportunity's honest lines (STOP-class)
    o_evidence = opp._evidence(comp=comp, momentum=momentum, candidate=asset_candidate,
                               entry_price=entry_price, discount_pct=discount_pct,
                               expected_net=expected_net, expected_roi_pct=expected_roi_pct)
    o_risks = opp._risks(stale=stale, momentum_status=momentum_status, confidence=confidence,
                         source_count=len(comp.get("sources") or []), market_comp=market_comp,
                         msrp=None, momentum_delta_pct=momentum.get("delta_pct"),
                         entry_price=entry_price)

    edge_id = opp.opportunity_id(asset_key, trade_type, as_of)
    packet = EdgePacket(
        edge_packet_id=edge_id,
        opportunity_id=edge_id,
        subject_key=asset_key,
        subject_kind="asset",
        asset_class=asset_class,
        name=asset.get("name") or asset_key,
        as_of=as_of,
        thesis=EDGE_TRADE_TYPES.get(trade_type, trade_type),
        trade_type=trade_type,
        decision_hint=hint,
        decision_reason=reason,
        score=opp.score_opportunity(
            discount_pct=discount_pct, expected_net=expected_net,
            expected_roi_pct=expected_roi_pct, momentum_status=momentum_status,
            momentum_delta_pct=momentum.get("delta_pct"), confidence=confidence,
            source_agreement=opp._source_agreement(len(comp.get("sources") or []), confidence),
            stale=stale, risks=o_risks, cfg=cfg)[0],
        blockers=blockers,
        evidence=o_evidence,
        risks=o_risks,
        source_stack=_source_stack(comp),
        source_posture=source_posture(comp),
        comp_provenance=comp_provenance(comp),
        entry_provenance=entry_provenance(asset_candidate),
        expected_net=expected_net,
        expected_roi_pct=expected_roi_pct,
        verdict_tier=verdict_tier,
        momentum_status=momentum_status,
        momentum_delta_pct=momentum.get("delta_pct"),
        grading_ev=grading,
        provider_dependency=provider_dependency(comp),
        status=_status_block(comp, momentum),
        input_snapshot=opp._input_snapshot(asset_candidate),
        condition=asset.get("condition"),
        grader=asset.get("grader"),
        grade=asset.get("grade"),
        card_number=asset.get("card_number"),
    )
    return asdict(packet)


# ---------------------------------------------------------------- orchestration (F)

def _grade_num(asset: dict) -> float:
    try:
        return float(asset.get("grade") or 0)
    except (TypeError, ValueError):
        return 0.0


def _asset_comp_estimate(observations, asset_key, asset) -> float | None:
    """Read-first (ledger latest, offline, 0 credits) comp estimate for one asset."""
    row = lab_mod.resolve_asset_comp_row(observations, asset_key, asset)
    if not row:
        return None
    return asset_model_mod.asset_comp_response(asset_key, asset, row).get("estimate")


def graded_sibling_comp(raw_asset, assets, observations) -> tuple[float | None, str, float | None]:
    """(target_graded_comp, target_grade_key, downside_comp) for a raw asset, matched
    on the SAME ``tcgplayer_id`` (never guessed). Target = the highest-grade sibling;
    downside = the next-highest sibling's comp (else None). Read-first, 0 credits."""
    tcg = str(raw_asset.get("tcgplayer_id") or "").strip()
    if not tcg:
        return (None, "", None)
    graded = [(k, a) for k, a in assets.items()
              if str(a.get("asset_class") or "") == "graded"
              and str(a.get("tcgplayer_id") or "").strip() == tcg]
    if not graded:
        return (None, "", None)
    graded.sort(key=lambda ka: -_grade_num(ka[1]))
    tkey, tasset = graded[0]
    target_comp = _asset_comp_estimate(observations, tkey, tasset)
    downside = None
    if len(graded) > 1:
        downside = _asset_comp_estimate(observations, graded[1][0], graded[1][1])
    return (target_comp, str(tasset.get("grade_key") or ""), downside)


def build_edge_packets(deps, *, as_of=None) -> list[dict]:
    """All edge packets (sealed products + raw/graded assets), score desc. Read-first,
    network-free, 0 credits — mirrors the /opportunities belt. Never constructs a
    billed source: comps resolve from the in-house cache / ledger only."""
    as_of = as_of or deps.today
    observations = deps.read_observations()
    packets: list[dict] = []

    candidate_for = getattr(deps, "candidate_for", None)
    for key, product in deps.products.items():
        row = lab_mod.resolve_comp_row(deps.comp_provider, observations, key, product)
        comp = (model_mod.comp_response(key, product, row) if row else
                model_mod.no_comp_response(key, product, status="no_history",
                    detail="no cached comp; ledger has no comp for this item"))
        ikey = history_mod.item_key_for_product(product, key)
        momentum = history_mod.momentum(observations, ikey, today=deps.today,
                                        stale_days=deps.cfg.opportunity.stale_after_days)
        candidate = candidate_for(key, product) if candidate_for else None
        packets.append(build_sealed_packet(key, product, comp, momentum, candidate,
                                           deps.cfg, as_of=as_of))

    assets = getattr(deps, "assets", None) or {}
    asset_candidate_for = getattr(deps, "asset_candidate_for", None)
    for key, asset in assets.items():
        row = lab_mod.resolve_asset_comp_row(observations, key, asset)
        comp = (asset_model_mod.asset_comp_response(key, asset, row) if row else
                asset_model_mod.asset_no_comp_response(key, asset, status="no_history",
                    detail="no asset comp in the ledger for this identity"))
        ikey = history_mod.item_key_for_asset(asset)
        momentum = history_mod.momentum(observations, ikey, today=deps.today,
                                        stale_days=deps.cfg.opportunity.stale_after_days)
        cand = asset_candidate_for(key, asset) if asset_candidate_for else None
        gcomp, tgrade, downside = (graded_sibling_comp(asset, assets, observations)
                                   if str(asset.get("asset_class")) == "raw" else (None, "", None))
        packets.append(build_asset_packet(key, asset, comp, momentum, cand, deps.cfg,
                                          as_of=as_of, graded_sibling_comp=gcomp,
                                          target_grade=tgrade, downside_comp=downside))

    packets.sort(key=lambda p: (-float(p.get("score") or 0.0), p["subject_key"]))
    return packets


def paper_ledger_view(packet: dict) -> dict:
    """A Phase-C-paper-ledger-shaped view of an edge packet.

    The packet renamed the evidence columns (``subject_key`` not ``product_key``,
    ``comp_provenance.estimate`` not ``market_comp``, ``entry_provenance.entry_price``
    not ``entry_price``, ``status.stale``/``.confidence`` not ``stale``/
    ``latest_confidence``, ``thesis`` not ``hypothesis``). ``paper_ledger.build_decision_row``
    reads the legacy names, so recording a packet *directly* would null those columns.
    This view maps them back so the durable audit row carries the SAME evidence a
    sealed opportunity decision does (STOP-class: the id AND the evidence unify)."""
    comp = packet.get("comp_provenance") or {}
    entry = packet.get("entry_provenance") or {}
    status = packet.get("status") or {}
    e = entry.get("entry_price")
    m = comp.get("estimate")
    discount = (round((m - e) / m * 100.0, 2)
                if (e is not None and m not in (None, 0)) else None)
    return {
        "opportunity_id": packet.get("opportunity_id") or packet.get("edge_packet_id"),
        "decision_hint": packet.get("decision_hint"),
        "as_of": packet.get("as_of"),
        "product_key": packet.get("subject_key"),
        "name": packet.get("name"),
        "trade_type": packet.get("trade_type"),
        "hypothesis": packet.get("thesis"),
        "entry_price": e,
        "market_comp": m,
        "msrp": packet.get("msrp"),        # packets carry no msrp -> honest null
        "discount_pct": discount,
        "expected_net": packet.get("expected_net"),
        "expected_roi_pct": packet.get("expected_roi_pct"),
        "verdict_tier": packet.get("verdict_tier"),
        "latest_confidence": comp.get("confidence"),
        "momentum_delta_pct": packet.get("momentum_delta_pct"),
        "momentum_status": packet.get("momentum_status"),
        "stale": status.get("stale"),
        "score": packet.get("score"),
        "input_snapshot": packet.get("input_snapshot") or {},
        # carry the edge-native fields too so the row is self-describing
        "edge_packet_id": packet.get("edge_packet_id"),
        "asset_class": packet.get("asset_class"),
        "subject_kind": packet.get("subject_kind"),
    }


def edge_summary(packets: list[dict]) -> dict:
    """Compact roll-up: counts by decision / asset_class / trade_type / posture, the
    live count, and the top blockers across all packets."""
    by_decision: dict[str, int] = {}
    by_asset_class: dict[str, int] = {}
    by_trade_type: dict[str, int] = {}
    by_posture: dict[str, int] = {}
    blocker_counts: dict[str, int] = {}
    for p in packets:
        by_decision[p["decision_hint"]] = by_decision.get(p["decision_hint"], 0) + 1
        by_asset_class[p["asset_class"]] = by_asset_class.get(p["asset_class"], 0) + 1
        by_trade_type[p["trade_type"]] = by_trade_type.get(p["trade_type"], 0) + 1
        for tag in p.get("source_posture") or []:
            by_posture[tag] = by_posture.get(tag, 0) + 1
        for b in p.get("blockers") or []:
            blocker_counts[b] = blocker_counts.get(b, 0) + 1
    live = by_decision.get("LIVE_PACKET_ELIGIBLE", 0)
    paper = by_decision.get("PAPER_BUY", 0)
    top_blockers = sorted(({"blocker": k, "count": v} for k, v in blocker_counts.items()),
                          key=lambda b: (-b["count"], b["blocker"]))
    return {
        "count": len(packets),
        "by_decision": by_decision,
        "by_asset_class": by_asset_class,
        "by_trade_type": by_trade_type,
        "by_posture": by_posture,
        "live_packet_eligible": live,
        "paper_buy": paper,
        "top_blockers": top_blockers,
        "dormant": live == 0 and paper == 0,
        "note": ("no buy-shaped packets today - every subject lacks a verified entry, "
                 "a comp, or clears the floors" if live == 0 and paper == 0
                 else f"{live} live-eligible / {paper} paper-buy packet(s)"),
    }

