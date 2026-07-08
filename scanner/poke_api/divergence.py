"""API-vs-external divergence audit (Session E Slice H) — OFF the hot path.

Compares our owned ``/api/poke`` comp against the external card provider (PPT) and
classifies any disagreement. This is an operator tool, never called by a read
endpoint. It exists to *investigate* divergences — not to tune our answers blindly
to PPT: for every material gap it says whether ours or theirs is more defensible.

Two modes:
* **dry/local (default):** classifies our latest LOCAL-origin comp against an
  already-recorded EXTERNAL-origin (``ppt_cards``) observation in the ledger. Zero
  network, zero credits. No key required.
* **external (money-class):** refuses without ``market.api_key``; prints the
  estimated spend; refuses without operator ``--yes``; hard-stops before the next
  subject if the provider-reported daily remaining would fall below the floor
  (mirrors ``comps.ppt_validator``). Clients are injectable for hermetic tests.

A **material UNEXPLAINED divergence fails the audit** (``blocking``) and must be
documented as blocking. Explained categories (stale, ask-vs-sold, source policy,
mapping error, confidence method, provider payload) are surfaced for investigation
but do not fail the command.
"""
from __future__ import annotations

import time

from .. import market as market_mod
from .. import resale
from ..comps import ppt_validator
from . import asset_model as asset_model_mod
from . import history as history_mod
from . import lab as lab_mod
from . import model as model_mod

HARD_STOP_REMAINING = ppt_validator.HARD_STOP_REMAINING  # 15 — reuse the money-class floor
MAPPING_ERROR_PCT = 100.0                                # >=100% gap => likely a wrong id/variant
_EXTERNAL_SLUGS = frozenset({"ppt_cards", "tcgcsv"})   # non-independent-of-PPT; never the "ours" side
_PPT_SLUGS = frozenset({"ppt_cards"})                  # the canonical audited PPT number (the "theirs" side)
# Sources genuinely INDEPENDENT of the PPT market number for cross-source validation.
# TCGplayer/TCGCSV are excluded: they mirror the PPT number (Phase F finding), so agreement
# with PPT is NOT independent corroboration.
_INDEPENDENT_OF_PPT = frozenset({"pricecharting"})

# The full divergence vocabulary (exposed for docs/CLI). ``fee_assumption_difference``
# is reserved for a net/EV comparison mode (our labeled config fee model vs the
# collectibles FVF / >=$1,000 card discount) and is not produced by the comp-only
# auto-classifier — it is surfaced when a caller compares fee-adjusted values.
CATEGORIES = (
    "agree", "no_external_reference", "mapping_error", "stale_local", "stale_external",
    "source_policy_difference", "ask_vs_sold_difference", "fee_assumption_difference",
    "confidence_method_difference", "provider_payload_issue", "unexplained_material_divergence",
)


def _row(category, material, blocking, delta_pct, defensible, note) -> dict:
    return {"category": category, "material": bool(material), "blocking": bool(blocking),
            "delta_pct": delta_pct, "defensible": defensible, "note": note}


def classify_divergence(ours: dict, theirs: dict | None, *, tolerance_pct: float = 20.0) -> dict:
    """Classify our comp vs the external comp. ``ours``: {estimate, confidence, stale,
    ask_only, missing}. ``theirs``: {estimate, confidence, stale, error} or None.
    Only ``unexplained_material_divergence`` is ``blocking`` (fails the command)."""
    o = ours.get("estimate")
    t = theirs.get("estimate") if theirs else None

    if theirs is None or (t is None and not theirs.get("error")):
        return _row("no_external_reference", False, False, None, "ours",
                    "no external observation to compare against")
    if theirs.get("error"):
        return _row("provider_payload_issue", False, False, None, "ours",
                    "external payload error/degraded; cannot compare (not our bug)")
    if o is None:
        if ours.get("ask_only"):
            return _row("ask_vs_sold_difference", False, False, None, "ours",
                        "we refuse to price off active asks (STOP-class); external quoted a number")
        return _row("source_policy_difference", False, False, None, "ours",
                    "no local sold-derived comp under our read-first policy; external has one")

    lo = min(o, t)
    delta = round(abs(o - t) / lo * 100.0, 2) if lo > 0 else float("inf")
    material = delta > tolerance_pct
    if not material:
        return _row("agree", False, False, delta, "both", "within agreement tolerance")

    # material gap — try to explain (explained => not blocking)
    if ours.get("stale"):
        return _row("stale_local", True, False, delta, "theirs (more current)",
                    "our comp is older than the external observation; refresh ours")
    if theirs.get("stale"):
        return _row("stale_external", True, False, delta, "ours (more current)",
                    "the external observation is older than ours")
    if ours.get("ask_only"):
        return _row("ask_vs_sold_difference", True, False, delta, "ours (asks are context)",
                    "our number is ask-derived context; external is sold-derived")
    if delta >= MAPPING_ERROR_PCT:
        return _row("mapping_error", True, False, delta, "unknown - investigate the id/variant",
                    f"delta {delta}% >= {MAPPING_ERROR_PCT}% - likely a wrong tcgplayer_id/variant "
                    "mapping (comparing different cards); fix the mapping before trusting either")
    if str(ours.get("confidence") or "") != str(theirs.get("confidence") or ""):
        return _row("confidence_method_difference", True, False, delta, "context-dependent",
                    "confidence methods differ; the magnitude sits in a method-difference band")
    return _row("unexplained_material_divergence", True, True, delta, "unknown - BLOCKING",
                "material gap with no explanatory category - investigate; do not tune blindly to PPT")


# ---------------------------------------------------------------- local (dry) mode

def _latest_market_comp(observations, item_key, *, external: bool):
    best = None
    for o in history_mod.filter_observations(observations, item_key=item_key,
                                             kind=history_mod.MARKET_COMP):
        src = history_mod.source_of(o)
        if external:
            if src not in _PPT_SLUGS:      # "theirs" is strictly the PPT number
                continue
        elif src in _EXTERNAL_SLUGS:       # "ours" excludes ppt_cards AND tcgcsv (non-independent)
            continue
        if best is None or str(o.get("capture_date") or "") >= str(best.get("capture_date") or ""):
            best = o
    return best


def _local_ours(obs, item_key, ext_date: str | None) -> dict:
    ours_obs = _latest_market_comp(obs, item_key, external=False)
    if ours_obs is None:
        return {"estimate": None, "confidence": "none", "missing": True, "ask_only": False,
                "stale": False, "source": None}
    o_date = str(ours_obs.get("capture_date") or "")
    return {
        "estimate": history_mod._comp_value(ours_obs),
        "confidence": str(ours_obs.get("comp_confidence") or "none"),
        "missing": False,
        "ask_only": history_mod.source_of(ours_obs) == "ebay",
        "stale": bool(ext_date and o_date and o_date < ext_date),
        "source": history_mod.source_of(ours_obs),
    }


def _local_theirs(obs, item_key) -> dict | None:
    ext_obs = _latest_market_comp(obs, item_key, external=True)
    if ext_obs is None:
        return None
    return {"estimate": history_mod._comp_value(ext_obs),
            "confidence": str(ext_obs.get("comp_confidence") or "none"),
            "capture_date": str(ext_obs.get("capture_date") or ""), "stale": False}


def _subject_item_keys(deps, product_keys, asset_keys):
    for k in product_keys or []:
        product = deps.products.get(k)
        if product is not None:
            yield (k, "product", history_mod.item_key_for_product(product, k))
    for k in asset_keys or []:
        asset = (getattr(deps, "assets", None) or {}).get(k)
        if asset is not None:
            yield (k, "asset", history_mod.item_key_for_asset(asset))


def audit_local(deps, *, product_keys=None, asset_keys=None, tolerance_pct=None) -> dict:
    """Classify our recorded LOCAL comp vs a recorded EXTERNAL (ppt_cards) observation
    for each subject — 0 network, 0 credits. Used by normal operators to sanity-check
    divergence without spending anything."""
    tol = float(tolerance_pct if tolerance_pct is not None else deps.cfg.comps.agreement_tolerance_pct)
    obs = deps.read_observations()
    rows = []
    for key, kind, item_key in _subject_item_keys(deps, product_keys, asset_keys):
        theirs = _local_theirs(obs, item_key)
        ext_date = theirs.get("capture_date") if theirs else None
        ours = _local_ours(obs, item_key, ext_date)
        # date-based staleness of the external side too
        if theirs is not None and ours.get("estimate") is not None:
            ours_obs = _latest_market_comp(obs, item_key, external=False)
            o_date = str((ours_obs or {}).get("capture_date") or "")
            theirs["stale"] = bool(o_date and ext_date and ext_date < o_date)
        clazz = classify_divergence(ours, theirs, tolerance_pct=tol)
        ours_source = ours.get("source")
        # Only a GENUINELY independent-of-PPT source counts as cross-source validation
        # (tcgplayer mirrors the PPT market number — Phase F finding — so it does not).
        cross = bool(ours_source in _INDEPENDENT_OF_PPT
                     and theirs is not None and clazz["category"] == "agree")
        rows.append({"subject_key": key, "subject_kind": kind, "ours": ours.get("estimate"),
                     "ours_source": ours_source, "theirs": (theirs or {}).get("estimate"),
                     "cross_source_validated": cross, **clazz})
    failed = any(r["blocking"] for r in rows)
    return {"mode": "local", "rows": rows, "failed": failed, "credits_spent": 0,
            "material_count": sum(1 for r in rows if r["material"])}


# ---------------------------------------------------------------- F.1 multi-asset gap matrix

# The full matrix classification vocabulary (superset of the auto-produced set; exposed for
# docs/CLI). ``source_policy_difference`` is inherited from the base classifier (a served
# comp of None under read-first policy vs an external number) and is not produced by the
# pure-ledger matrix, which classifies a missing independent comp as
# ``no_independent_reference``.
MATRIX_CATEGORIES = (
    "agree", "no_external_reference", "no_independent_reference",
    "source_policy_difference", "mapping_error", "grade_mapping_difference",
    "raw_condition_difference", "stale_local", "stale_external",
    "confidence_method_difference", "unexplained_material_divergence",
)


def _latest_independent_comp(observations, item_key):
    """Latest recorded market_comp whose source is independent of PPT (not ppt_cards,
    not an ebay ask) — the ``ours`` side of the gap matrix."""
    best = None
    for o in history_mod.filter_observations(observations, item_key=item_key,
                                             kind=history_mod.MARKET_COMP):
        src = history_mod.source_of(o)
        if src in _EXTERNAL_SLUGS or src == "ebay":
            continue
        if best is None or str(o.get("capture_date") or "") >= str(best.get("capture_date") or ""):
            best = o
    return best


def _grade_is_grader_agnostic(asset) -> bool:
    from . import independent_sources as indep
    cell, note = indep._grade_cell_for(asset.get("grade_key"))
    return cell is not None and "grader-agnostic" in note


def _raw_non_nm(asset) -> bool:
    from . import independent_sources as indep
    if str(asset.get("asset_class") or "").strip().lower() != "raw":
        return False
    ok, _ = indep.raw_condition_recordable(asset)
    return not ok


def _matrix_classify(asset, ours, theirs, tol):
    """(classification, cross_source_validated, blocking, defensibility, notes, delta_pct).
    A material UNEXPLAINED divergence is the only blocking outcome. The grade-mapping and
    raw-condition categories are explained (non-blocking); they are demonstrated via
    constructed observations (they do not fire on the live F.1 ledger)."""
    o = ours["estimate"] if ours else None
    t = theirs["estimate"] if theirs else None
    if theirs is None or t is None:
        return ("no_external_reference", False, False, "ours",
                "no recorded ppt_cards observation to compare against", None)
    if o is None:
        return ("no_independent_reference", False, False, "n/a — need an independent source",
                "a PPT-sourced local reference exists but no independent (PriceCharting) "
                "comp to cross-validate it", None)
    lo = min(o, t)
    delta = round(abs(o - t) / lo * 100.0, 2) if lo > 0 else float("inf")
    if delta <= tol:
        cross = str((ours or {}).get("source") or "") in _INDEPENDENT_OF_PPT
        return "agree", cross, False, "both", "within agreement tolerance", delta
    # material — try to explain (an explained category is never blocking)
    ours_date, theirs_date = str(ours.get("capture_date") or ""), str(theirs.get("capture_date") or "")
    if ours_date and theirs_date and ours_date < theirs_date:
        return ("stale_local", False, False, "theirs (more current)",
                "our comp is older than the PPT observation; refresh ours", delta)
    if ours_date and theirs_date and theirs_date < ours_date:
        return ("stale_external", False, False, "ours (more current)",
                "the PPT observation is older than ours", delta)
    if _raw_non_nm(asset):
        return ("raw_condition_difference", False, False, "ours (condition-honest)",
                "gap attributable to a non-NM raw condition vs the condition-agnostic "
                "Ungraded/external number (demonstrated via constructed observations)", delta)
    if str(asset.get("asset_class") or "").strip().lower() == "graded" and _grade_is_grader_agnostic(asset):
        return ("grade_mapping_difference", False, False, "context-dependent",
                "grader-agnostic PriceCharting Grade-N proxy vs a grader-specific external "
                "number (demonstrated via constructed observations)", delta)
    if delta >= MAPPING_ERROR_PCT:
        return ("mapping_error", False, False, "unknown - investigate the id/variant/slug",
                f"delta {delta}% >= {MAPPING_ERROR_PCT}% - likely a wrong mapping "
                "(comparing different cards); fix the mapping before trusting either", delta)
    if str(ours.get("confidence") or "") != str(theirs.get("confidence") or ""):
        return ("confidence_method_difference", False, False, "context-dependent",
                "confidence methods differ; the magnitude sits in a method-difference band", delta)
    return ("unexplained_material_divergence", False, True, "unknown - BLOCKING",
            "material gap with no explanatory category - investigate; do not tune blindly to PPT", delta)


def _matrix_row(key, asset, ours_obs, theirs_obs, tol) -> dict:
    asset_class = str(asset.get("asset_class") or "")
    cond_or_grade = (asset.get("grade_key") if asset_class == "graded"
                     else asset.get("condition")) or ""
    ours = None
    if ours_obs is not None:
        ours = {"estimate": history_mod._comp_value(ours_obs),
                "source": history_mod.source_of(ours_obs),
                "confidence": str(ours_obs.get("comp_confidence") or "none"),
                "capture_date": str(ours_obs.get("capture_date") or "")}
    theirs = None
    if theirs_obs is not None:
        theirs = {"estimate": history_mod._comp_value(theirs_obs),
                  "confidence": str(theirs_obs.get("comp_confidence") or "none"),
                  "capture_date": str(theirs_obs.get("capture_date") or "")}
    classification, cross, blocking, defensibility, notes, delta = _matrix_classify(asset, ours, theirs, tol)
    return {
        "asset_key": key, "asset_class": asset_class, "condition_or_grade_key": cond_or_grade,
        "ours": (ours or {}).get("estimate"), "ours_source": (ours or {}).get("source"),
        "ours_capture_date": (ours or {}).get("capture_date"),
        "ppt_reference": (theirs or {}).get("estimate"),
        "ppt_capture_date": (theirs or {}).get("capture_date"),
        "delta_pct": delta, "classification": classification,
        "cross_source_validated": bool(cross), "defensibility": defensibility, "notes": notes,
        "material": classification not in ("agree", "no_external_reference", "no_independent_reference"),
        "blocking": bool(blocking),
    }


def audit_matrix(deps, *, asset_keys=None, tolerance_pct=None) -> dict:
    """Multi-asset PPT-vs-ours gap matrix (F.1) — 0 network / 0 credits. For each asset it
    compares our latest INDEPENDENT (PriceCharting) recorded comp against the latest
    recorded ppt_cards observation and classifies the gap with the F.1 vocabulary. A
    material UNEXPLAINED divergence fails the matrix (never tune blindly to PPT)."""
    tol = float(tolerance_pct if tolerance_pct is not None else deps.cfg.comps.agreement_tolerance_pct)
    obs = deps.read_observations()
    assets = getattr(deps, "assets", None) or {}
    rows = []
    for key in asset_keys or []:
        asset = assets.get(key)
        if asset is None:
            continue
        item_key = history_mod.item_key_for_asset(asset)
        ours_obs = _latest_independent_comp(obs, item_key)
        theirs_obs = _latest_market_comp(obs, item_key, external=True)
        rows.append(_matrix_row(key, asset, ours_obs, theirs_obs, tol))
    return {"mode": "local-matrix", "rows": rows,
            "failed": any(r["blocking"] for r in rows), "credits_spent": 0,
            "material_count": sum(1 for r in rows if r["material"])}


# ---------------------------------------------------------------- external (guarded)

def _asset_credit(asset: dict) -> int:
    if not str(asset.get("tcgplayer_id") or "").strip():
        return 0
    ac = str(asset.get("asset_class") or "").strip().lower()
    if ac == "raw":
        return 1
    if ac == "graded" and str(asset.get("grade_key") or "").strip():
        return 2
    return 0


def estimate_spend(deps, *, product_keys=None, asset_keys=None) -> dict:
    """Deterministic UPPER-BOUND external credit spend for an audit (limit=1 pinned):
    1 credit / sealed product, 1 / raw asset, 2 / graded asset."""
    sealed = len(product_keys or [])
    asset_credits = sum(_asset_credit((getattr(deps, "assets", None) or {}).get(k, {}))
                        for k in (asset_keys or []))
    return {"credits": sealed + asset_credits, "sealed": sealed, "assets": asset_credits}


def _our_served(deps, kind, key) -> dict:
    """Our /api/poke-served comp (read-first) normalized for classify."""
    obs = deps.read_observations()
    if kind == "product":
        product = deps.products.get(key, {})
        row = lab_mod.resolve_comp_row(deps.comp_provider, obs, key, product)
        comp = model_mod.comp_response(key, product, row) if row else \
            model_mod.no_comp_response(key, product, status="no_history", detail="")
    else:
        asset = (getattr(deps, "assets", None) or {}).get(key, {})
        row = lab_mod.resolve_asset_comp_row(obs, key, asset)
        comp = asset_model_mod.asset_comp_response(key, asset, row) if row else \
            asset_model_mod.asset_no_comp_response(key, asset, status="no_history", detail="")
    slugs = [str(s.get("source") or "").lower() for s in (comp.get("sources") or [])
             if isinstance(s, dict)]
    return {"estimate": comp.get("estimate"), "confidence": str(comp.get("confidence") or "none"),
            "stale": bool(comp.get("stale")), "missing": comp.get("estimate") is None,
            "ask_only": comp.get("estimate") is None and slugs == ["ebay"]}


def _external_sealed(client, deps, key) -> tuple[dict, int | None]:
    product = deps.products.get(key, {})
    raw = client.estimate(key, product, int(time.time())) or {}
    theirs = {"estimate": resale._amount(raw.get("estimate")),
              "confidence": str(raw.get("confidence") or "none"),
              "error": str(raw.get("status") or "ok") != "ok", "stale": False}
    remaining = raw.get("dailyRemaining")
    return theirs, (int(remaining) if isinstance(remaining, int) else None)


def _external_asset(client, deps, key) -> dict:
    asset = (getattr(deps, "assets", None) or {}).get(key, {})
    checked = int(time.time())
    if str(asset.get("asset_class")) == "graded":
        smart = client.graded_smart(asset, checked)
        if smart is None:
            return {"estimate": None, "confidence": "none", "error": True, "stale": False}
        return {"estimate": smart.price, "confidence": smart.confidence, "error": False, "stale": False}
    q = client.raw_quote(asset, checked)
    return {"estimate": (q.price if getattr(q, "status", "") == "ok" else None),
            "confidence": "low", "error": getattr(q, "status", "") != "ok", "stale": False}


def run_audit(deps, *, product_keys=None, asset_keys=None, local=True, yes=False,
              client_sealed=None, client_asset=None, tolerance_pct=None,
              hard_stop_remaining=HARD_STOP_REMAINING) -> dict:
    """Run the divergence audit. ``local=True`` (default) is 0-credit. External mode
    is money-class: refuse without a key, surface the spend, refuse without ``--yes``,
    hard-stop below the remaining-credit floor. Returns a structured result (the CLI
    prints it)."""
    product_keys = list(product_keys or [])
    asset_keys = list(asset_keys or [])
    tol = float(tolerance_pct if tolerance_pct is not None else deps.cfg.comps.agreement_tolerance_pct)

    if local:
        res = audit_local(deps, product_keys=product_keys, asset_keys=asset_keys, tolerance_pct=tol)
        return {"mode": "local", "refused": False, "message": "local/dry audit (0 credits)",
                "spend_estimate": {"credits": 0}, "hard_stopped": False,
                "failed": res["failed"], "rows": res["rows"], "credits_spent": 0}

    spend = estimate_spend(deps, product_keys=product_keys, asset_keys=asset_keys)
    if not str(getattr(deps.cfg, "market_api_key", "") or ""):
        return {"mode": "external", "refused": True, "spend_estimate": spend,
                "message": "refused: market.api_key not configured", "hard_stopped": False,
                "failed": False, "rows": [], "credits_spent": 0}
    if not yes:
        return {"mode": "external", "refused": True, "spend_estimate": spend,
                "message": (f"refused: pass --yes only after operator go-ahead "
                            f"(estimated spend ~{spend['credits']} credit(s), limit=1 pinned, money-class)"),
                "hard_stopped": False, "failed": False, "rows": [], "credits_spent": 0}

    sealed_client = client_sealed or market_mod.PokemonPriceTrackerClient.from_config(deps.cfg)
    rows, spent, remaining, hard_stopped = [], 0, None, False

    for key in product_keys:
        if remaining is not None and remaining < hard_stop_remaining:
            hard_stopped = True
            break
        theirs, remaining = _external_sealed(sealed_client, deps, key)
        spent += 1
        ours = _our_served(deps, "product", key)
        rows.append({"subject_key": key, "subject_kind": "product",
                     "ours": ours.get("estimate"), "theirs": theirs.get("estimate"),
                     **classify_divergence(ours, theirs, tolerance_pct=tol)})

    if not hard_stopped and asset_keys:
        asset_client = client_asset
        if asset_client is None:
            from . import sources as sources_mod
            asset_client = sources_mod.card_client_from_config(deps.cfg)
        for key in asset_keys:
            if remaining is not None and remaining < hard_stop_remaining:
                hard_stopped = True
                break
            if asset_client is None:
                break
            theirs = _external_asset(asset_client, deps, key)
            spent += _asset_credit((getattr(deps, "assets", None) or {}).get(key, {}))
            ours = _our_served(deps, "asset", key)
            rows.append({"subject_key": key, "subject_kind": "asset",
                         "ours": ours.get("estimate"), "theirs": theirs.get("estimate"),
                         **classify_divergence(ours, theirs, tolerance_pct=tol)})

    return {"mode": "external", "refused": False, "spend_estimate": spend,
            "message": f"external audit complete ({spent} credit(s) spent)",
            "hard_stopped": hard_stopped, "failed": any(r["blocking"] for r in rows),
            "rows": rows, "credits_spent": spent}
