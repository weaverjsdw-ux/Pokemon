"""Append-only paper-trade ledger for the Money Hypothesis Lab (Phase C).

One immutable JSON object per line in ``data/poke/paper_decisions.jsonl`` (a
SEPARATE file from the market-observation ledger ``price_history.jsonl``). Two row
kinds share the file:

* ``decision`` — the program's paper call on an opportunity (PAPER_BUY / WATCH /
  REJECT / LIVE_PACKET_ELIGIBLE) plus the evidence snapshot it was based on.
* ``outcome``  — what happened later, recorded as a SEPARATE row keyed by
  ``opportunity_id``. Never an edit to the decision.

**No hindsight mutation.** Rows are never rewritten; a changed call or a new
observation is a new appended line, and "current state" is always a fold
(``current_by_id``) that takes the latest row per opportunity. Idempotent by a
sha256 ``entry_id``, mirroring ``scanner/discovery/ledger.py``.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

OUTCOME_STATUSES = {"SOLD", "HELD", "PRICE_UP", "PRICE_DOWN", "EXPIRED", "VOID"}

# Fields lifted from an opportunity (asdict) onto a decision row. ``input_snapshot``
# preserves the candidate provenance (source + stock evidence) that backed the call.
_DECISION_SNAPSHOT = (
    "product_key", "name", "trade_type", "hypothesis", "entry_price", "market_comp",
    "msrp", "discount_pct", "expected_net", "expected_roi_pct", "verdict_tier",
    "latest_confidence", "momentum_delta_pct", "momentum_status", "stale", "score",
    "input_snapshot",
)


def decision_entry_id(opportunity_id: str, decision: str, as_of: str) -> str:
    raw = f"decision|{opportunity_id}|{decision}|{as_of}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def outcome_entry_id(opportunity_id: str, status: str, observed_at: str) -> str:
    raw = f"outcome|{opportunity_id}|{status}|{observed_at}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_decision_row(opportunity: dict, *, decision: str | None = None,
                       reason: str = "", as_of: str | None = None,
                       recorded_at: str = "") -> dict:
    oid = str(opportunity.get("opportunity_id") or "")
    decision = decision or str(opportunity.get("decision_hint") or "WATCH")
    as_of = as_of if as_of is not None else str(opportunity.get("as_of") or "")
    row = {
        "entry_id": decision_entry_id(oid, decision, as_of),
        "kind": "decision",
        "opportunity_id": oid,
        "decision": decision,
        "decision_reason": reason,
        "as_of": as_of,
        "recorded_at": recorded_at,
    }
    for field in _DECISION_SNAPSHOT:
        row[field] = opportunity.get(field)
    return row


def build_outcome_row(opportunity_id: str, status: str, observed_at: str, *,
                      realized_price=None, realized_net=None, note: str = "") -> dict:
    return {
        "entry_id": outcome_entry_id(opportunity_id, status, observed_at),
        "kind": "outcome",
        "opportunity_id": opportunity_id,
        "status": status,
        "observed_at": observed_at,
        "realized_price": realized_price,
        "realized_net": realized_net,
        "note": note,
    }


# ---------------------------------------------------------------- read/append

def read_rows(path) -> list[dict]:
    """Read the JSONL ledger safely. Missing file -> empty; malformed / non-object
    lines are skipped; blank lines ignored. File order == append order."""
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
    return {r["entry_id"] for r in read_rows(path) if "entry_id" in r}


def append_row(path, row: dict) -> bool:
    """Append one row; idempotent by ``entry_id`` (re-appending is a no-op)."""
    eid = row.get("entry_id")
    if not eid:
        raise ValueError("row must carry an entry_id")
    path = Path(path)
    if eid in _existing_ids(path):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return True


def record_decision(path, opportunity: dict, *, decision: str | None = None,
                    reason: str = "", as_of: str | None = None,
                    recorded_at: str = "") -> bool:
    return append_row(path, build_decision_row(
        opportunity, decision=decision, reason=reason, as_of=as_of,
        recorded_at=recorded_at))


def record_outcome(path, opportunity_id: str, status: str, observed_at: str, *,
                   realized_price=None, realized_net=None, note: str = "") -> bool:
    if status not in OUTCOME_STATUSES:
        raise ValueError(
            f"outcome status must be one of {sorted(OUTCOME_STATUSES)}, got {status!r}")
    return append_row(path, build_outcome_row(
        opportunity_id, status, observed_at, realized_price=realized_price,
        realized_net=realized_net, note=note))


# ---------------------------------------------------------------- folds

def decisions(rows) -> list[dict]:
    return [r for r in rows if r.get("kind") == "decision"]


def outcomes(rows) -> list[dict]:
    return [r for r in rows if r.get("kind") == "outcome"]


def current_by_id(rows) -> dict[str, dict]:
    """Fold to {opportunity_id: {"decision": latest_decision, "outcome":
    latest_outcome}}. Latest-wins by append order; earlier rows are never lost
    from the file — this is a read-time projection, not a mutation."""
    out: dict[str, dict] = {}
    for r in rows:
        oid = r.get("opportunity_id")
        if not oid:
            continue
        slot = out.setdefault(oid, {"decision": None, "outcome": None})
        if r.get("kind") == "decision":
            slot["decision"] = r
        elif r.get("kind") == "outcome":
            slot["outcome"] = r
    return out


def signals_report(rows) -> dict:
    """Which hypotheses are working over time: per-trade-type counts, and for
    opportunities with a realized-net outcome, a hit-rate (net>0) and mean net.
    Metrics stay ``None`` (never a fabricated number) when no outcome exists."""
    current = current_by_id(rows)
    by_decision: dict[str, int] = {}
    by_trade_type: dict[str, dict] = {}
    decisions_recorded = outcomes_recorded = 0

    for slot in current.values():
        d = slot["decision"]
        if not d:
            continue
        decisions_recorded += 1
        by_decision[d.get("decision", "unknown")] = by_decision.get(d.get("decision", "unknown"), 0) + 1
        tt = d.get("trade_type", "unknown")
        agg = by_trade_type.setdefault(
            tt, {"count": 0, "with_outcome": 0, "wins": 0, "realized_net_sum": 0.0})
        agg["count"] += 1
        o = slot["outcome"]
        if o is not None:
            outcomes_recorded += 1
            if o.get("realized_net") is not None:
                net = float(o["realized_net"])
                agg["with_outcome"] += 1
                agg["realized_net_sum"] += net
                if net > 0:
                    agg["wins"] += 1

    for agg in by_trade_type.values():
        n = agg["with_outcome"]
        agg["hit_rate"] = round(agg["wins"] / n, 3) if n else None
        agg["mean_realized_net"] = round(agg["realized_net_sum"] / n, 2) if n else None

    return {
        "opportunities": len(current),
        "decisions_recorded": decisions_recorded,
        "outcomes_recorded": outcomes_recorded,
        "by_decision": by_decision,
        "by_trade_type": by_trade_type,
    }
