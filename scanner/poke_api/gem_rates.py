"""Gem-rate evidence ledger + gem-rate math (Phase G).

Append-only, provenance-stamped gem-rate records in ``data/poke/gem_rates.jsonl`` (a
SEPARATE file from the market-observation ledger ``price_history.jsonl`` and the
paper-trade ledger ``paper_decisions.jsonl``). A gem rate is either **``sourced``**
(derived from a dated PriceCharting population blob, 0 PPT credits) or an explicit
**``operator_assumption``** — it is NEVER invented (missing/insufficient population
blocks or falls back to a labeled assumption, never a guess).

Grader-specific by construction: PSA and CGC are separate series and are **never
combined**. Canonical Phase G formula (fixed here, documented in the G spec):

    gem_rate = PSA10 / total PSA population        (grader-specific)

The population gem rate is a **broad population proxy**, not a copy-specific grade
prediction — the graded population mixes gambled-on damaged submissions with NM copies,
and the bias direction is unknown. That is exactly why grading EV built on a gem rate is
capped at PAPER_BUY and never LIVE. Idempotent by a sha256 ``entry_id`` (mirrors
``paper_ledger.py`` / ``scanner/discovery/ledger.py``). Pure: no network, no clock.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

SAMPLE_FLOOR_DEFAULT = 300
# Grader-specific formula label — PSA and CGC are separate series, so the stored formula
# must name the row's own grader ("PSA10 / total PSA population" / "CGC10 / total CGC
# population"), never a PSA figure on a CGC row. Build it with ``gem_rate_formula``.
GEM_RATE_FORMULA_TEMPLATE = "{grader}10 / total {grader} population"
GEM_RATE_SOURCE_POP = "pricecharting_pop"
LABEL_SOURCED = "sourced"
LABEL_ASSUMPTION = "operator_assumption"

# The base-rate caveat, stated once so every sourced-rate surface can cite it verbatim.
POP_PROXY_CAVEAT = (
    "population gem rate is a broad population proxy over ALL graded submissions of this "
    "card, not a copy-specific grade prediction; grading EV is capped at PAPER_BUY, never LIVE")

# Pinned index -> printed grade for a PriceCharting ``VGPC.pop_data`` per-grader array.
# Ten elements along the grade ladder; the LAST element is grade 10. Confirmed (not
# assumed) by cross-checking the array against Umbreon's independently published PSA
# total (17,990) and PSA-10 (5,487) — see test_index_map_pins_last_element_as_grade_10.
POP_GRADE_LADDER = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)


def _norm_grader(grader) -> str:
    return str(grader or "").strip().upper()


def gem_rate_formula(grader) -> str:
    """Grader-specific gem-rate formula label ('PSA10 / total PSA population',
    'CGC10 / total CGC population', ...). Grader-specific by construction — the label
    never implies a PSA figure for a CGC row or vice-versa (PSA and CGC never combined)."""
    return GEM_RATE_FORMULA_TEMPLATE.format(grader=_norm_grader(grader))


def gem_rate_from_counts(counts, *, grader, sample_floor: int = SAMPLE_FLOOR_DEFAULT) -> dict:
    """Grader-specific gem rate from a per-grade population array (STOP-class, pure).

    ``status`` ∈ ``ok`` (total >= floor) | ``insufficient_sample`` (0 < total < floor) |
    ``invalid`` (wrong length / nonnumeric / negative / zero population). Never guesses:
    an invalid array yields no rate; an insufficient one yields a flagged rate the caller
    must not persist as ``sourced`` (block or fall back to operator_assumption)."""
    formula = gem_rate_formula(grader)
    invalid = {
        "status": "invalid", "gem_rate": None, "sample_size": None,
        "counts_by_grade": None, "psa10": None, "gem_rate_formula": formula,
        "grader": _norm_grader(grader),
    }
    if not isinstance(counts, (list, tuple)) or len(counts) != len(POP_GRADE_LADDER):
        return {**invalid, "reason": f"pop array must have {len(POP_GRADE_LADDER)} elements"}
    nums: list[float] = []
    for c in counts:
        if isinstance(c, bool) or not isinstance(c, (int, float)):
            return {**invalid, "reason": "nonnumeric population count"}
        if c < 0:
            return {**invalid, "reason": "negative population count"}
        nums.append(float(c))
    total = sum(nums)
    if total <= 0:
        return {**invalid, "reason": "zero population (no graded submissions)"}
    top = nums[-1]                                    # grade 10 == last element
    gem_rate = round(top / total, 4)
    counts_by_grade = {str(g): int(n) if float(n).is_integer() else n
                       for g, n in zip(POP_GRADE_LADDER, nums)}
    status = "ok" if total >= sample_floor else "insufficient_sample"
    reason = ("" if status == "ok"
              else f"total pop {int(total)} below sample floor {sample_floor}")
    return {
        "status": status,
        "gem_rate": gem_rate,
        "sample_size": int(total),
        "counts_by_grade": counts_by_grade,
        "psa10": int(top) if float(top).is_integer() else top,
        "gem_rate_formula": formula,
        "grader": _norm_grader(grader),
        "reason": reason,
    }


# ---------------------------------------------------------------- entry identity

def gem_rate_entry_id(*, asset_key: str, grader: str, source_url: str,
                      capture_date: str, formula: str, label: str) -> str:
    """sha256 over the STABLE identity of a gem-rate record: asset key, grader, source
    URL, capture date, formula, and label. Two captures of the same population on the
    same day for the same asset/grader/source collapse to one row (idempotent)."""
    raw = (f"gem_rate|{asset_key}|{_norm_grader(grader)}|{source_url}|"
           f"{capture_date}|{formula}|{label}")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- row builders

def build_sourced_row(*, asset_key: str, grader: str, counts, source_url: str,
                      capture_date: str, basis: str = "",
                      sample_floor: int = SAMPLE_FLOOR_DEFAULT) -> dict:
    """A ``sourced`` gem-rate row from a population array. Raises ``ValueError`` when the
    array is invalid or below the sample floor — a sourced row is NEVER written for an
    unusable population (block; the operator may record an assumption instead)."""
    calc = gem_rate_from_counts(counts, grader=grader, sample_floor=sample_floor)
    if calc["status"] == "invalid":
        raise ValueError(f"cannot source a gem rate: {calc.get('reason', 'invalid population')}")
    if calc["status"] != "ok":
        raise ValueError(
            f"population below sample floor ({calc.get('reason')}); record an explicit "
            f"operator_assumption instead of a sourced rate — never guess")
    grader = _norm_grader(grader)
    formula = gem_rate_formula(grader)
    return {
        "entry_id": gem_rate_entry_id(
            asset_key=asset_key, grader=grader, source_url=source_url,
            capture_date=capture_date, formula=formula, label=LABEL_SOURCED),
        "kind": "gem_rate",
        "asset_key": str(asset_key or ""),
        "grader": grader,
        "counts_by_grade": calc["counts_by_grade"],
        "gem_rate": calc["gem_rate"],
        "gem_rate_formula": formula,
        "label": LABEL_SOURCED,
        "source": GEM_RATE_SOURCE_POP,
        "source_url": str(source_url or ""),
        "capture_date": str(capture_date or ""),
        "sample_size": calc["sample_size"],
        # The floor the row was recorded against — read-time provenance judges sufficiency
        # against THIS, not the current default (a custom --sample-floor persists honestly).
        "sample_floor": int(sample_floor),
        "status": "ok",
        "basis": str(basis or ""),
    }


def build_assumption_row(*, asset_key: str, grader: str, gem_rate: float,
                         basis: str, capture_date: str, source_url: str = "") -> dict:
    """An ``operator_assumption`` gem-rate row. The rate must be a probability in
    ``(0, 1]`` (an assumption is still not a fabrication of a *value* — it is an explicit,
    labeled judgment call, capped PAPER_BUY). ``basis`` is required (why this number)."""
    try:
        rate = float(gem_rate)
    except (TypeError, ValueError):
        rate = None
    if rate is None or not (0.0 < rate <= 1.0):
        raise ValueError("operator assumption gem_rate must be a probability in (0, 1]")
    if not str(basis or "").strip():
        raise ValueError("operator assumption requires a basis (why this rate)")
    grader = _norm_grader(grader)
    return {
        "entry_id": gem_rate_entry_id(
            asset_key=asset_key, grader=grader, source_url=source_url,
            capture_date=capture_date, formula="operator_assumption", label=LABEL_ASSUMPTION),
        "kind": "gem_rate",
        "asset_key": str(asset_key or ""),
        "grader": grader,
        "counts_by_grade": None,
        "gem_rate": round(rate, 4),
        "gem_rate_formula": "operator_assumption",
        "label": LABEL_ASSUMPTION,
        "source": LABEL_ASSUMPTION,
        "source_url": str(source_url or ""),
        "capture_date": str(capture_date or ""),
        "sample_size": None,
        "status": "operator_assumption",
        "basis": str(basis).strip(),
    }


# ---------------------------------------------------------------- read / append

def read_rows(path) -> list[dict]:
    """Read the JSONL ledger safely. Missing file -> empty; malformed / non-object /
    blank lines skipped. File order == append order."""
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


def existing_ids(path) -> set[str]:
    return {r["entry_id"] for r in read_rows(path) if "entry_id" in r}


def append_row(path, row: dict) -> bool:
    """Append one row; idempotent by ``entry_id`` (re-appending is a no-op)."""
    eid = row.get("entry_id")
    if not eid:
        raise ValueError("gem-rate row must carry an entry_id")
    path = Path(path)
    if eid in existing_ids(path):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return True


def record_sourced(path, *, asset_key: str, grader: str, counts, source_url: str,
                   capture_date: str, basis: str = "",
                   sample_floor: int = SAMPLE_FLOOR_DEFAULT) -> bool:
    """Build + append a sourced gem-rate row (0 credits — the population was scraped free
    upstream). Raises on an invalid / below-floor population (never persists a guess)."""
    return append_row(path, build_sourced_row(
        asset_key=asset_key, grader=grader, counts=counts, source_url=source_url,
        capture_date=capture_date, basis=basis, sample_floor=sample_floor))


def record_assumption(path, *, asset_key: str, grader: str, gem_rate: float,
                      basis: str, capture_date: str, source_url: str = "") -> bool:
    """Build + append an operator-assumption gem-rate row (no network)."""
    return append_row(path, build_assumption_row(
        asset_key=asset_key, grader=grader, gem_rate=gem_rate, basis=basis,
        capture_date=capture_date, source_url=source_url))


# ---------------------------------------------------------------- folds

def rows_for_asset(rows, asset_key: str) -> list[dict]:
    return [r for r in rows if r.get("asset_key") == asset_key and r.get("kind") == "gem_rate"]


def latest_for(rows, asset_key: str, grader: str) -> dict | None:
    """Latest recorded gem-rate row for an asset+grader (last-write-wins by append order;
    earlier rows stay in the file — this is a read-time projection, not a mutation)."""
    g = _norm_grader(grader)
    latest = None
    for r in rows:
        if (r.get("kind") == "gem_rate" and r.get("asset_key") == asset_key
                and _norm_grader(r.get("grader")) == g):
            latest = r
    return latest
