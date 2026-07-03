# In-House Comp Engine v1 (Slice 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `scanner/comps/` — a multi-source comp engine (TCGplayer + PriceCharting +
eBay Browse, PPT demoted to an off-hot-path validator) that emits legacy-shaped quote rows,
switchable into the sweep behind `comps.engine` (default `legacy` — today's behavior must
not change).

**Architecture:** Pure confidence resolution (`model.py`) separated from I/O sources
(`tcgplayer.py`, `pricecharting.py`, `ebay.py` — the latter two wrap existing
`scanner/resale.py` machinery) and from orchestration (`engine.py`: fan-out, SQLite cache,
ledger history, legacy-dict emit). Spec: `docs/superpowers/specs/2026-07-02-buyable-deal-pipeline-design.md`
§3.1/§4 (read it first — the confidence table in §4.3 is normative).

**Tech Stack:** Python 3.12, `requests` (already a dep), sqlite3 via `scanner/state.py`,
pytest. **No new dependencies.**

## Global Constraints

- Python: `.venv/Scripts/python.exe`; full suite must pass: `.venv/Scripts/python.exe -m pytest -q` (baseline 276 passed).
- Tests are network-mocked — no test may perform live HTTP.
- STOP-class: never fabricate/guess a price; `unknown` confidence ⇒ comp is `None`, no number anywhere.
- Money-class: any PPT call pins `limit=1`; validator refuses without key + `--yes` + hard-stops below 15 remaining credits.
- eBay keyset is NOT provisioned (operator awaiting eBay developer-program acceptance): the eBay source must return `not_configured` cleanly and every engine test must pass with eBay degraded.
- Default-config behavior byte-identical: `comps.engine` defaults to `"legacy"`; no existing test may change.
- Live network happens in exactly one place: Task 1's probe (max 3 GETs to tcgplayer.com, operator-approved via spec sign-off 2026-07-03).
- Never push to any remote. Execute in-place on local `main` (repo convention). Conventional commits: `feat(comps):`, `test(comps):`, `refactor(resale):`, `docs(poke):`.
- ASCII-only in `print()` output; file writes use `encoding="utf-8"`.
- Commit trailer: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`. Run commits in PowerShell-safe form (single-line `-m` or bash heredoc — NOT PowerShell here-strings in bash).

## File Structure

```
scanner/comps/__init__.py        # empty package marker
scanner/comps/model.py           # CompSourceQuote, EbayAsk, NormalizedComp, resolve(), to_legacy_row()
scanner/comps/tcgplayer.py       # TcgPlayerSource (variant fixed by Task 1 probe)
scanner/comps/pricecharting.py   # PriceChartingSource (wraps resale.PriceChartingSearchClient)
scanner/comps/ebay.py            # EbayAskSource (wraps resale eBay Browse machinery; degrades w/o keyset)
scanner/comps/engine.py          # CompEngine: fan-out, cache, ledger, legacy emit
scanner/comps/ppt_validator.py   # off-hot-path PPT spot-check CLI
scanner/resale.py                # MODIFY: extract matched_prices(); split EbayResaleClient.search_payload()
scanner/state.py                 # MODIFY: comp_cache table + get/put
scanner/config.py                # MODIFY: CompsCfg + comps block parsing
config.example.yaml              # MODIFY: comps block
scanner/discovery/sweep.py       # MODIFY: LiveCompLookup honors comps.engine
scripts/probe_tcgplayer.py       # one-shot probe (Task 1)
docs/poke/reference/tcgplayer-probe.md   # probe evidence + decision
tests/fixtures/comps/            # saved probe HTML (trimmed) + any static payloads
tests/test_comps_model.py        # confidence matrix + legacy mapping
tests/test_comps_sources.py      # pricecharting/ebay/tcgplayer source normalization
tests/test_comps_engine.py       # cache TTL/degrade, ledger, legacy round-trip, politeness
tests/test_comps_validator.py    # refusal + hard-stop paths
```

Interface notes an implementer must know (verified against current code this week):

- `resale` quote-dict keys consumed downstream: `status`, `estimate` (money **string** like
  `"$180.65"`), `confidence`, `url`, `sourceUrl`, `source`, `basis`, `confidenceReason`.
  `market.comp_from_row(row)` → `(resale._amount(row["estimate"]), row["confidence"])` when
  `status=="ok"` else `(None, "none")`. `sweep._provenance` grants `"verified"` only when
  `sourceUrl` is set AND confidence is high/medium.
- `resale.CONFIDENCE_LABELS` has keys `high/medium/low/none` (no `unknown` — map it).
- `ledger.append_observation(path, obs)` requires `obs["kind"] in {"deal","market_comp"}`;
  identity = `(kind, item_key, source_url, capture_date)`.
- `State(db_path=...)` creates tables in `_init_schema`; follow the existing
  `CREATE TABLE IF NOT EXISTS` + `ON CONFLICT ... DO UPDATE` pattern.

---

### Task 1: TCGplayer acquisition probe + evidence (LIVE NETWORK — bounded)

**Files:**
- Create: `scripts/probe_tcgplayer.py`
- Create: `docs/poke/reference/tcgplayer-probe.md`
- Create: `tests/fixtures/comps/` (probe output)

**Interfaces:**
- Consumes: nothing.
- Produces: the **variant decision** for Task 5 (`PARSER` if a market price is parseable
  from plain-requests HTML, else `STUB`), written in `tcgplayer-probe.md`, plus trimmed
  fixture file(s) `tests/fixtures/comps/tcgplayer_product_<id>.html`.

- [ ] **Step 1: Record the baseline suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: `276 passed` (record the exact number; it is the regression floor).

- [ ] **Step 2: Write the probe script**

```python
"""One-shot TCGplayer product-page probe (Slice 1, Task 1).

Operator-approved live fetch (spec Appendix A, Step 0). Max 3 GETs, 1.5s apart,
plain requests only - no browser, no bot-wall evasion. Saves raw HTML as fixtures
and prints whether a market price is parseable from the static response.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

import requests

# Seeded catalog ids (data/products.yaml ppt_id == TCGplayer product id).
IDS = ["593355", "624676", "610930"]  # Prismatic ETB, Destined Rivals ETB, Journey Together ETB
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0 Safari/537.36"
)
OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "comps"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for pid in IDS:
        url = f"https://www.tcgplayer.com/product/{pid}"
        resp = requests.get(url, headers={"User-Agent": UA, "Accept": "text/html"}, timeout=30)
        (OUT / f"tcgplayer_product_{pid}.html").write_text(resp.text, encoding="utf-8")
        hits = re.findall(r'.{0,40}[Mm]arket\s*[Pp]rice.{0,120}', resp.text)
        json_hits = re.findall(r'"marketPrice"\s*:\s*"?\$?[0-9][0-9.,]*"?', resp.text)
        print(f"{pid}: HTTP {resp.status_code}, {len(resp.text)} bytes, "
              f"text-hits={len(hits)}, json-hits={len(json_hits)}")
        for sample in (json_hits or hits)[:5]:
            print("   ", sample[:110].replace("\n", " "))
        time.sleep(1.5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Run the probe (the only live-network step in this plan)**

Run: `.venv/Scripts/python.exe scripts/probe_tcgplayer.py`
Expected: three lines of `<id>: HTTP <code>, <bytes>, text-hits=<n>, json-hits=<n>` and
fixture files written under `tests/fixtures/comps/`.

- [ ] **Step 4: Decide the variant and write the evidence doc**

Decision rule (mechanical):
- **PARSER** if any saved fixture contains a machine-readable market price for the product
  (a `"marketPrice"`-style JSON number, or an unambiguous `Market Price` + `$X.XX` pair in
  static HTML) AND the value is plausible (within 0.25x–4x of the known comp for that id —
  e.g. 593355 ≈ $191 on 2026-07-01).
- **STUB** otherwise (HTTP 403/blocked, JS shell, or no parseable number).

Write `docs/poke/reference/tcgplayer-probe.md`:

```markdown
# TCGplayer product-page probe — Slice 1 Task 1 (2026-07-03)

Method: plain requests GET, Chrome UA, 3 product pages (593355, 624676, 610930),
1.5s spacing. Script: scripts/probe_tcgplayer.py. Raw responses saved to
tests/fixtures/comps/ (trimmed for commit; see below).

| id | HTTP | bytes | parseable market price? | evidence excerpt |
| --- | --- | --- | --- | --- |
| 593355 | <fill from run> | <fill> | <yes $X.XX / no> | <exact matched text, <=120 chars> |
| 624676 | <fill> | <fill> | <...> | <...> |
| 610930 | <fill> | <fill> | <...> | <...> |

**DECISION: <PARSER | STUB>** — <one sentence why>.
If STUB: spec section 4.2 ladder continues with Probe B (supervised devtools
observation) or the Playwright dependency decision; the engine ships TCGplayer-degraded
(PriceCharting + eBay only, max MEDIUM) and remains fully functional.
```

Every `<fill>` is replaced with observed values before commit — a committed doc with
angle-bracket placeholders is a task failure.

- [ ] **Step 5: Trim fixtures for commit**

For each fixture used by tests, keep a trimmed copy that still contains the parse target
(or, for STUB, the proof-of-absence region): if the raw file is > 500 KB, cut it to the
2 KB region around the first market-price match (PARSER) or the `<title>` + first 4 KB
(STUB), same filename. Delete untrimmed multi-MB leftovers.

- [ ] **Step 6: Commit**

```bash
git add scripts/probe_tcgplayer.py docs/poke/reference/tcgplayer-probe.md tests/fixtures/comps/
git commit -m "feat(comps): TCGplayer acquisition probe + evidence (Slice 1 Task 1)"
```

---

### Task 2: `comps/model.py` — quotes + confidence resolution (pure)

**Files:**
- Create: `scanner/comps/__init__.py` (empty)
- Create: `scanner/comps/model.py`
- Test: `tests/test_comps_model.py`

**Interfaces:**
- Consumes: `scanner.resale` helpers (`_money`, `_amount`, `_premium_ratio`,
  `CONFIDENCE_LABELS`, `product_query`, `ebay_search_web_url`).
- Produces (used by Tasks 4–6, 9):
  - `CompSourceQuote(source, kind, status, price, url, fetched_at, sample_size=None, detail="", raw_excerpt="")` (frozen dataclass)
  - `EbayAsk(quote, floor=None, count=None)` (frozen dataclass)
  - `NormalizedComp(item_key, comp, comp_basis, confidence, confidence_reason, sources, ebay_floor, ebay_active_count, spread_pct, captured_at, stale=False)` (frozen dataclass)
  - `resolve(item_key, msrp, tcg, pc, ebay, captured_at, *, tolerance_pct=20.0, floor_sanity_pct=50.0) -> NormalizedComp`
  - `to_legacy_row(n: NormalizedComp, product_key: str, product: dict, checked_at: int) -> dict`
  - constants `SOLD_DERIVED = "sold_derived"`, `ACTIVE_ASK = "active_ask"`, `VALIDATOR = "validator"`, `HIGH_PREMIUM_RATIO = 4.0`

- [ ] **Step 1: Write the failing confidence-matrix tests**

```python
"""Confidence resolution matrix - spec 4.3, exhaustive per tier + edges."""
from scanner.comps import model


def q(source, price, kind=model.SOLD_DERIVED, status="ok", url="", sample_size=None):
    return model.CompSourceQuote(
        source=source, kind=kind, status=status, price=price,
        url=url or f"https://example.com/{source}", fetched_at="2026-07-03T10:00:00",
        sample_size=sample_size,
    )


def ask(median, floor, count):
    return model.EbayAsk(
        quote=q("ebay_api", median, kind=model.ACTIVE_ASK, sample_size=count),
        floor=floor, count=count,
    )


def resolve(msrp=50.0, tcg=None, pc=None, ebay=None, tol=20.0, floor_pct=50.0):
    return model.resolve("set|item|||", msrp, tcg, pc, ebay, "2026-07-03",
                         tolerance_pct=tol, floor_sanity_pct=floor_pct)


def test_high_both_agree_floor_sane():
    n = resolve(tcg=q("tcgplayer", 100.0), pc=q("pricecharting", 110.0), ebay=ask(105.0, 95.0, 12))
    assert n.confidence == "high"
    assert n.comp == 100.0          # min() of the agreeing pair - conservative
    assert n.spread_pct is not None and 9.9 < n.spread_pct < 10.1
    assert n.ebay_floor == 95.0 and n.ebay_active_count == 12


def test_high_both_agree_no_ebay():
    n = resolve(tcg=q("tcgplayer", 100.0), pc=q("pricecharting", 110.0))
    assert n.confidence == "high" and n.comp == 100.0
    assert n.ebay_floor is None and n.ebay_active_count is None


def test_medium_floor_insane():
    n = resolve(tcg=q("tcgplayer", 100.0), pc=q("pricecharting", 110.0), ebay=ask(60.0, 40.0, 8))
    assert n.confidence == "medium"
    assert "floor_below_comp" in n.confidence_reason


def test_medium_source_spread():
    n = resolve(tcg=q("tcgplayer", 100.0), pc=q("pricecharting", 150.0))
    assert n.confidence == "medium" and n.comp == 100.0
    assert "source_spread" in n.confidence_reason


def test_premium_caps_agreeing_pair_to_low():
    n = resolve(msrp=20.0, tcg=q("tcgplayer", 100.0), pc=q("pricecharting", 105.0))
    assert n.confidence == "low" and "high_premium" in n.confidence_reason
    assert n.comp == 100.0          # capped, not suppressed (Phase-0 closure)


def test_medium_single_sold_corroborated_by_ask():
    n = resolve(tcg=q("tcgplayer", 100.0), ebay=ask(108.0, 90.0, 5))
    assert n.confidence == "medium" and n.comp == 100.0
    assert "active_ask" not in n.comp_basis   # comp is sold-derived; STEAL stays eligible


def test_medium_pc_side_corroboration():
    n = resolve(pc=q("pricecharting", 100.0), ebay=ask(95.0, 80.0, 4))
    assert n.confidence == "medium" and n.comp == 100.0


def test_low_single_sold_uncorroborated():
    n = resolve(pc=q("pricecharting", 100.0))
    assert n.confidence == "low" and n.comp == 100.0


def test_low_single_sold_ask_diverges():
    n = resolve(tcg=q("tcgplayer", 100.0), ebay=ask(200.0, 150.0, 9))
    assert n.confidence == "low"


def test_low_ask_only_with_sample():
    n = resolve(ebay=ask(80.0, 70.0, 6))
    assert n.confidence == "low" and n.comp == 80.0
    assert "active_ask" in n.comp_basis      # ask-derived comp is marked - blocks STEAL later


def test_unknown_ask_only_thin_sample():
    n = resolve(ebay=ask(80.0, 70.0, 2))
    assert n.confidence == "unknown" and n.comp is None


def test_unknown_nothing_ok():
    n = resolve(tcg=q("tcgplayer", None, status="blocked"), pc=q("pricecharting", None, status="no_match"))
    assert n.confidence == "unknown" and n.comp is None
    assert n.comp_basis == "none"
    assert len(n.sources) == 2               # failures are still recorded as evidence


def test_premium_caps_single_source():
    n = resolve(msrp=20.0, pc=q("pricecharting", 90.0))
    assert n.confidence == "low" and "high_premium" in n.confidence_reason
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_comps_model.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scanner.comps'`.

- [ ] **Step 3: Implement `scanner/comps/model.py`**

Create empty `scanner/comps/__init__.py`, then:

```python
"""In-house comp model: normalized source quotes + deterministic confidence.

Pure - no I/O, no network, no clock. Normative contract:
docs/superpowers/specs/2026-07-02-buyable-deal-pipeline-design.md section 4.
"""
from __future__ import annotations

from dataclasses import dataclass

from .. import resale

SOLD_DERIVED = "sold_derived"
ACTIVE_ASK = "active_ask"
VALIDATOR = "validator"
HIGH_PREMIUM_RATIO = 4.0  # mirrors resale.HIGH_PREMIUM_RATIO; kept per Phase-0 closure
ASK_MIN_SAMPLE = 3        # ask-only comps need at least this many matched listings

QUOTE_STATUSES = {"ok", "no_match", "blocked", "error", "not_configured", "skipped"}


@dataclass(frozen=True)
class CompSourceQuote:
    source: str            # "tcgplayer" | "pricecharting" | "ebay_api" | "ppt"
    kind: str              # SOLD_DERIVED | ACTIVE_ASK | VALIDATOR
    status: str            # QUOTE_STATUSES
    price: float | None
    url: str               # exact page/search URL fetched (attribution)
    fetched_at: str        # ISO datetime
    sample_size: int | None = None
    detail: str = ""
    raw_excerpt: str = ""


@dataclass(frozen=True)
class EbayAsk:
    quote: CompSourceQuote
    floor: float | None = None
    count: int | None = None


@dataclass(frozen=True)
class NormalizedComp:
    item_key: str
    comp: float | None
    comp_basis: str
    confidence: str          # high | medium | low | unknown
    confidence_reason: str
    sources: tuple[CompSourceQuote, ...]
    ebay_floor: float | None
    ebay_active_count: int | None
    spread_pct: float | None
    captured_at: str         # ISO date
    stale: bool = False


def _ok(quote: CompSourceQuote | None) -> bool:
    return bool(quote and quote.status == "ok" and quote.price and quote.price > 0)


def _spread(a: float, b: float) -> float:
    return abs(a - b) / min(a, b) * 100.0


def _premium_capped(comp: float, msrp: float | None) -> bool:
    return bool(msrp and msrp > 0 and comp / msrp >= HIGH_PREMIUM_RATIO)


def resolve(
    item_key: str,
    msrp: float | None,
    tcg: CompSourceQuote | None,
    pc: CompSourceQuote | None,
    ebay: EbayAsk | None,
    captured_at: str,
    *,
    tolerance_pct: float = 20.0,
    floor_sanity_pct: float = 50.0,
) -> NormalizedComp:
    """Spec 4.3 precedence table. UNKNOWN means comp None - never invent a number."""
    sources = tuple(q for q in (tcg, pc, ebay.quote if ebay else None) if q is not None)
    floor = ebay.floor if ebay else None
    count = ebay.count if ebay else None
    e_ok = ebay is not None and _ok(ebay.quote)

    def build(comp, basis, confidence, reason, spread=None):
        return NormalizedComp(
            item_key=item_key, comp=comp, comp_basis=basis, confidence=confidence,
            confidence_reason=reason, sources=sources, ebay_floor=floor,
            ebay_active_count=count, spread_pct=spread, captured_at=captured_at,
        )

    if _ok(tcg) and _ok(pc):
        spread = _spread(tcg.price, pc.price)
        comp = min(tcg.price, pc.price)
        premium = _premium_capped(comp, msrp)
        if spread <= tolerance_pct:
            basis = f"min(tcgplayer,pricecharting) agree@{tolerance_pct:g}%"
            if premium:
                return build(comp, basis, "low",
                             f"high_premium: comp >= {HIGH_PREMIUM_RATIO:g}x MSRP", spread)
            if floor is None or floor >= comp * (floor_sanity_pct / 100.0):
                return build(comp, basis, "high",
                             f"two sold-derived sources agree within {tolerance_pct:g}%", spread)
            return build(comp, basis, "medium",
                         f"floor_below_comp: eBay floor ${floor:.2f} is under "
                         f"{floor_sanity_pct:g}% of comp", spread)
        basis = f"min(tcgplayer,pricecharting) spread {spread:.0f}%"
        if premium:
            return build(comp, basis, "low",
                         f"high_premium: comp >= {HIGH_PREMIUM_RATIO:g}x MSRP", spread)
        return build(comp, basis, "medium",
                     f"source_spread: sold-derived sources disagree by {spread:.0f}%", spread)

    sold = tcg if _ok(tcg) else pc if _ok(pc) else None
    if sold is not None:
        comp = sold.price
        if _premium_capped(comp, msrp):
            return build(comp, f"{sold.source} uncorroborated", "low",
                         f"high_premium: comp >= {HIGH_PREMIUM_RATIO:g}x MSRP")
        if e_ok and _spread(comp, ebay.quote.price) <= tolerance_pct:
            return build(comp, f"{sold.source} corroborated by ebay ask median", "medium",
                         "single sold-derived source, ask-side corroboration")
        return build(comp, f"{sold.source} uncorroborated", "low",
                     "single sold-derived source, no corroboration")

    if e_ok and (count or 0) >= ASK_MIN_SAMPLE:
        return build(ebay.quote.price, f"ebay active_ask median (n={count})", "low",
                     "ask-basis only: median of active fixed-price listings, not sold comps")

    return build(None, "none", "unknown", "no usable source; no comp invented")
```

Note the marker rule: the substring `active_ask` appears in `comp_basis` **only** when the
comp value itself is ask-derived (Slice 2's STEAL check keys on this).

- [ ] **Step 4: Run the matrix tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_comps_model.py -q`
Expected: all PASS.

- [ ] **Step 5: Write the failing legacy-mapping tests (append to the same file)**

```python
from scanner import market as market_mod


def test_legacy_row_ok_high_verified_eligible():
    tcg = q("tcgplayer", 180.65, url="https://www.tcgplayer.com/product/624676")
    pc = q("pricecharting", 190.0, url="https://www.pricecharting.com/game/pokemon-destined-rivals/elite-trainer-box")
    n = resolve(msrp=49.99, tcg=tcg, pc=pc)
    row = model.to_legacy_row(n, "destined_rivals_etb", {"name": "Destined Rivals ETB", "msrp": "$49.99"}, 1780500000)
    assert row["status"] == "ok"
    assert row["estimate"] == "$180.65"           # money STRING - comp_from_row parses it
    assert market_mod.comp_from_row(row) == (180.65, "high")
    assert row["sourceUrl"] == "https://www.tcgplayer.com/product/624676"  # exact page -> verified-eligible
    assert row["basis"] == n.comp_basis
    assert row["checkedAt"] == 1780500000


def test_legacy_row_low_has_no_sourceurl():
    n = resolve(pc=q("pricecharting", 100.0, url="https://www.pricecharting.com/game/x/y"))
    row = model.to_legacy_row(n, "k", {"name": "X", "msrp": "$50"}, 1)
    assert row["confidence"] == "low"
    assert "sourceUrl" not in row                 # low never earns the verified path


def test_legacy_row_medium_pc_exact_url_promotes():
    pc = q("pricecharting", 100.0, url="https://www.pricecharting.com/game/pokemon-x/etb")
    n = resolve(pc=pc, ebay=ask(102.0, 90.0, 5))
    row = model.to_legacy_row(n, "k", {"name": "X", "msrp": "$50"}, 1)
    assert row["confidence"] == "medium"
    assert row["sourceUrl"] == pc.url             # PC product page counts as exact


def test_legacy_row_unknown_is_no_match_with_no_number():
    n = resolve()
    row = model.to_legacy_row(n, "k", {"name": "X"}, 1)
    assert row["status"] == "no_matches"
    assert row["estimate"] == "" and row["confidence"] == "none"
    assert market_mod.comp_from_row(row) == (None, "none")


def test_legacy_row_carries_annotate_quote_keys():
    n = resolve(tcg=q("tcgplayer", 100.0), pc=q("pricecharting", 105.0))
    row = model.to_legacy_row(n, "k", {"name": "X", "msrp": "$50"}, 1)
    for key in ("productKey", "status", "source", "basis", "query", "estimate", "low",
                "high", "sampleSize", "checkedAt", "url", "detail", "confidence",
                "confidenceLabel", "confidenceReason", "premiumRatio", "flags",
                "needsVerification", "asterisk", "compBasis", "ebayFloor",
                "ebayActiveCount", "sources"):
        assert key in row, key
```

- [ ] **Step 6: Run to verify the new tests fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_comps_model.py -q`
Expected: FAIL — `AttributeError: ... 'to_legacy_row'`.

- [ ] **Step 7: Implement `to_legacy_row` (append to model.py)**

```python
_EXACT_PC_PREFIX = "https://www.pricecharting.com/game/"


def _exact_source_url(n: NormalizedComp) -> str:
    """Exact-product attribution URL, or '' - the sweep's verified gate keys on this."""
    for quote in n.sources:
        if quote.status != "ok":
            continue
        if quote.source == "tcgplayer" and quote.url:
            return quote.url                       # always a product page by construction
        if quote.source == "pricecharting" and quote.url.startswith(_EXACT_PC_PREFIX):
            return quote.url
    return ""


def _flags(n: NormalizedComp) -> list[str]:
    flags = []
    for marker in ("floor_below_comp", "source_spread", "high_premium"):
        if marker in n.confidence_reason:
            flags.append(marker)
    if "active_ask" in n.comp_basis:
        flags.append("asking_price")
    return flags


def to_legacy_row(n: NormalizedComp, product_key: str, product: dict, checked_at: int) -> dict:
    """Emit the quote-dict shape the existing pipeline consumes (resale.annotate_quote
    superset). market.comp_from_row and sweep._provenance read this unchanged."""
    query = resale.product_query(product)
    base = {
        "productKey": product_key,
        "source": "InHouse comp engine",
        "basis": n.comp_basis,
        "query": query,
        "checkedAt": checked_at,
        "compBasis": n.comp_basis,
        "ebayFloor": n.ebay_floor,
        "ebayActiveCount": n.ebay_active_count,
        "sources": [
            {"source": q.source, "kind": q.kind, "status": q.status, "price": q.price,
             "url": q.url, "fetchedAt": q.fetched_at, "detail": q.detail}
            for q in n.sources
        ],
    }
    if n.comp is None:
        return base | {
            "status": "no_matches", "estimate": "", "low": "", "high": "",
            "sampleSize": 0, "url": resale.ebay_search_web_url(query),
            "detail": n.confidence_reason, "confidence": "none",
            "confidenceLabel": resale.CONFIDENCE_LABELS["none"],
            "confidenceReason": n.confidence_reason, "premiumRatio": None,
            "flags": _flags(n), "needsVerification": False, "asterisk": False,
        }
    money = resale._money(n.comp)
    ok_sold = [q.price for q in n.sources
               if q.status == "ok" and q.kind == SOLD_DERIVED and q.price]
    row = base | {
        "status": "ok",
        "estimate": money,
        "low": resale._money(min(ok_sold)) if len(ok_sold) >= 2 else money,
        "high": resale._money(max(ok_sold)) if len(ok_sold) >= 2 else money,
        "sampleSize": n.ebay_active_count if "active_ask" in n.comp_basis else 0,
        "url": _exact_source_url(n) or resale.ebay_search_web_url(query),
        "detail": n.confidence_reason,
        "confidence": n.confidence,
        "confidenceLabel": resale.CONFIDENCE_LABELS.get(n.confidence,
                                                        resale.CONFIDENCE_LABELS["low"]),
        "confidenceReason": n.confidence_reason,
        "premiumRatio": resale._premium_ratio(product, money),
        "flags": _flags(n),
        "needsVerification": n.confidence == "low",
        "asterisk": n.confidence == "low",
    }
    exact = _exact_source_url(n)
    if exact and n.confidence in {"high", "medium"}:
        row["sourceUrl"] = exact
    return row
```

- [ ] **Step 8: Run the full model test file, then the whole suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_comps_model.py -q`
Expected: all PASS.
Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: baseline count + new tests, 0 failures.

- [ ] **Step 9: Commit**

```bash
git add scanner/comps/__init__.py scanner/comps/model.py tests/test_comps_model.py
git commit -m "feat(comps): quote model + spec-4.3 confidence resolution + legacy row emit"
```

---

### Task 3: `resale.py` extraction refactor (matched_prices + search_payload)

**Files:**
- Modify: `scanner/resale.py` (functions `quote_from_search_payload` ~line 534 and
  `EbayResaleClient.estimate` ~line 626)
- Test: `tests/test_resale.py` (append)

**Interfaces:**
- Produces (used by Task 5): `resale.matched_prices(product, payload) -> list[float]`
  (sorted ascending; title-filtered listing totals) and
  `EbayResaleClient.search_payload(product) -> dict` (the raw Browse JSON; `estimate`
  becomes a thin wrapper over it). Existing behavior byte-identical.

- [ ] **Step 1: Write the failing tests (append to `tests/test_resale.py`, matching its existing style)**

```python
def test_matched_prices_sorted_and_filtered():
    from scanner import resale
    product = {"name": "Prismatic Evolutions Elite Trainer Box", "type": "ETB",
               "resale_query": "Pokemon TCG Prismatic Evolutions Elite Trainer Box sealed"}
    payload = {"itemSummaries": [
        {"title": "Pokemon TCG Prismatic Evolutions Elite Trainer Box sealed",
         "price": {"value": "199.99", "currency": "USD"}},
        {"title": "Pokemon TCG Prismatic Evolutions Elite Trainer Box sealed",
         "price": {"value": "149.99", "currency": "USD"}},
        {"title": "empty box only Prismatic Evolutions",   # negative-title filtered
         "price": {"value": "9.99", "currency": "USD"}},
    ]}
    assert resale.matched_prices(product, payload) == [149.99, 199.99]


def test_search_payload_split_keeps_estimate_identical(monkeypatch):
    from scanner import resale

    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {"itemSummaries": [
                {"title": "Pokemon TCG Prismatic Evolutions Elite Trainer Box sealed",
                 "price": {"value": "150.00", "currency": "USD"}},
            ]}

    class FakeSession:
        def get(self, url, **kwargs): return FakeResp()
        def post(self, url, **kwargs): raise AssertionError("no token call expected")

    client = resale.EbayResaleClient(resale.ResaleCredentials(token="t"), session=FakeSession())
    product = {"name": "Prismatic Evolutions Elite Trainer Box", "type": "ETB",
               "resale_query": "Pokemon TCG Prismatic Evolutions Elite Trainer Box sealed"}
    payload = client.search_payload(product)
    assert payload["itemSummaries"][0]["price"]["value"] == "150.00"
    row = client.estimate("k", product, 123)
    assert row["status"] == "ok" and row["estimate"] == "$150.00"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_resale.py -q`
Expected: the two new tests FAIL (`matched_prices` / `search_payload` undefined); all
pre-existing tests PASS.

- [ ] **Step 3: Implement the extraction**

In `scanner/resale.py`, add above `quote_from_search_payload`:

```python
def matched_prices(product: dict[str, Any], payload: dict[str, Any]) -> list[float]:
    """Sorted listing totals (price+shipping) for title-matched active listings."""
    prices = [
        price
        for item in payload.get("itemSummaries") or []
        if isinstance(item, dict) and _title_allowed(product, item)
        for price in [_listing_total(item)]
        if price is not None
    ]
    prices.sort()
    return prices
```

Replace the identical inline comprehension at the top of `quote_from_search_payload` with:

```python
    prices = matched_prices(product, payload)
```

(delete the now-redundant `prices.sort()` line there). In `EbayResaleClient`, split
`estimate` (keep the request kwargs byte-identical):

```python
    def search_payload(self, product: dict[str, Any]) -> dict[str, Any]:
        query = product_query(product)
        response = self.session.get(
            EBAY_SEARCH_URL,
            params={
                "q": query,
                "limit": "50",
                "filter": "buyingOptions:{FIXED_PRICE},conditions:{1000},priceCurrency:USD",
            },
            headers={
                "Authorization": f"Bearer {self._access_token()}",
                "X-EBAY-C-MARKETPLACE-ID": self.credentials.marketplace_id,
            },
            timeout=20,
        )
        response.raise_for_status()
        return response.json()

    def estimate(self, product_key: str, product: dict[str, Any], checked_at: int) -> dict[str, Any]:
        return quote_from_search_payload(
            product_key, product, self.search_payload(product), checked_at)
```

- [ ] **Step 4: Run the resale tests, then the full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_resale.py -q` — Expected: all PASS.
Run: `.venv/Scripts/python.exe -m pytest -q` — Expected: 0 failures (pure extraction).

- [ ] **Step 5: Commit**

```bash
git add scanner/resale.py tests/test_resale.py
git commit -m "refactor(resale): extract matched_prices + EbayResaleClient.search_payload (byte-compatible)"
```

---

### Task 4: `comps/pricecharting.py` source

**Files:**
- Create: `scanner/comps/pricecharting.py`
- Test: `tests/test_comps_sources.py` (new file)

**Interfaces:**
- Consumes: `resale.PriceChartingSearchClient.estimate` (Task-3-unchanged),
  `model.CompSourceQuote`.
- Produces (used by Task 9): `PriceChartingSource(cfg, client=None)` with
  `fetch(product_key, product, checked_at) -> CompSourceQuote` (never raises).

- [ ] **Step 1: Write the failing tests**

```python
"""Source normalization tests: every source returns a CompSourceQuote and never raises."""
import requests

from scanner.comps import model
from scanner.comps.pricecharting import PriceChartingSource

PRODUCT = {"name": "Destined Rivals Elite Trainer Box", "set": "Destined Rivals",
           "type": "ETB", "msrp": "$49.99",
           "resale_query": "Pokemon TCG Destined Rivals Elite Trainer Box sealed"}


class FakePcClient:
    def __init__(self, row=None, exc=None):
        self.row, self.exc = row, exc
    def estimate(self, key, product, checked_at):
        if self.exc: raise self.exc
        return self.row


def test_pc_ok_row_maps_to_quote():
    row = {"status": "ok", "estimate": "$190.00",
           "url": "https://www.pricecharting.com/game/pokemon-destined-rivals/elite-trainer-box",
           "detail": "PriceCharting ungraded market summary"}
    quote = PriceChartingSource(cfg=None, client=FakePcClient(row)).fetch("k", PRODUCT, 1780500000)
    assert quote.status == "ok" and quote.price == 190.0
    assert quote.source == "pricecharting" and quote.kind == model.SOLD_DERIVED
    assert quote.url.startswith("https://www.pricecharting.com/game/")
    assert quote.raw_excerpt


def test_pc_no_match():
    row = {"status": "no_matches", "url": "https://www.pricecharting.com/search-products?q=x",
           "detail": "No usable PriceCharting result matched this product."}
    quote = PriceChartingSource(cfg=None, client=FakePcClient(row)).fetch("k", PRODUCT, 1)
    assert quote.status == "no_match" and quote.price is None


def test_pc_http_403_is_blocked():
    quote = PriceChartingSource(cfg=None, client=FakePcClient(
        exc=requests.HTTPError("403 Client Error: Forbidden"))).fetch("k", PRODUCT, 1)
    assert quote.status == "blocked" and quote.price is None


def test_pc_transport_error():
    quote = PriceChartingSource(cfg=None, client=FakePcClient(
        exc=requests.ConnectionError("boom"))).fetch("k", PRODUCT, 1)
    assert quote.status == "error" and quote.price is None
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_comps_sources.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```python
"""PriceCharting sold-derived summary as a CompSourceQuote (wraps scanner.resale)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

import requests

from .. import resale
from .model import SOLD_DERIVED, CompSourceQuote


class PriceChartingSource:
    def __init__(self, cfg: Any, client: Any = None) -> None:
        self.client = client or resale.PriceChartingSearchClient()

    def fetch(self, product_key: str, product: dict, checked_at: int) -> CompSourceQuote:
        fetched_at = datetime.fromtimestamp(checked_at).isoformat(timespec="seconds")
        fallback_url = resale._pricecharting_search_url(resale.product_query(product))
        try:
            row = self.client.estimate(product_key, product, checked_at)
        except requests.RequestException as exc:
            detail = resale._safe_detail(str(exc))
            status = "blocked" if ("403" in detail or "429" in detail) else "error"
            return CompSourceQuote("pricecharting", SOLD_DERIVED, status, None,
                                   fallback_url, fetched_at, detail=detail)
        url = str(row.get("url") or fallback_url)
        if row.get("status") == "ok":
            return CompSourceQuote(
                "pricecharting", SOLD_DERIVED, "ok", resale._amount(row.get("estimate")),
                url, fetched_at,
                raw_excerpt=str(row.get("detail") or "")[:200])
        return CompSourceQuote("pricecharting", SOLD_DERIVED, "no_match", None, url,
                               fetched_at, detail=str(row.get("detail") or row.get("status") or ""))
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_comps_sources.py -q` — Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scanner/comps/pricecharting.py tests/test_comps_sources.py
git commit -m "feat(comps): PriceCharting sold-derived source"
```

---

### Task 5: `comps/ebay.py` source (degrades without keyset — REQUIRED path)

**Files:**
- Create: `scanner/comps/ebay.py`
- Test: `tests/test_comps_sources.py` (append)

**Interfaces:**
- Consumes: `resale.auth_configured`, `resale.EbayResaleClient.search_payload` (Task 3),
  `resale.matched_prices`, `resale._quantile`, `resale.ebay_search_web_url`;
  `model.EbayAsk`.
- Produces (used by Task 9): `EbayAskSource(cfg, client=None)` with
  `fetch(product_key, product, checked_at) -> EbayAsk` (never raises). Keyset absent →
  `EbayAsk(quote.status == "not_configured", floor=None, count=None)`.

- [ ] **Step 1: Write the failing tests (append)**

```python
from scanner.comps.ebay import EbayAskSource


class _NoAuthCfg:
    ebay_browse_api_token = ""
    ebay_client_id = ""
    ebay_client_secret = ""
    ebay_marketplace_id = "EBAY_US"


class FakeEbayClient:
    def __init__(self, payload=None, exc=None):
        self.payload, self.exc = payload, exc
    def search_payload(self, product):
        if self.exc: raise self.exc
        return self.payload


def test_ebay_not_configured_degrades_cleanly(monkeypatch):
    # Operator is still waiting on eBay developer-program acceptance: this IS the
    # production path today. Env creds must not leak in.
    for var in ("EBAY_BROWSE_API_TOKEN", "EBAY_OAUTH_TOKEN", "EBAY_CLIENT_ID",
                "EBAY_CLIENT_SECRET"):
        monkeypatch.delenv(var, raising=False)
    ask = EbayAskSource(cfg=_NoAuthCfg()).fetch("k", PRODUCT, 1)
    assert ask.quote.status == "not_configured"
    assert ask.floor is None and ask.count is None
    assert "ebay-keyset-setup" in ask.quote.detail


def test_ebay_ok_median_floor_count():
    payload = {"itemSummaries": [
        {"title": "Pokemon TCG Destined Rivals Elite Trainer Box sealed",
         "price": {"value": "170.00", "currency": "USD"}},
        {"title": "Pokemon TCG Destined Rivals Elite Trainer Box sealed",
         "price": {"value": "180.00", "currency": "USD"}},
        {"title": "Pokemon TCG Destined Rivals Elite Trainer Box sealed",
         "price": {"value": "200.00", "currency": "USD"}},
    ]}
    ask = EbayAskSource(cfg=None, client=FakeEbayClient(payload)).fetch("k", PRODUCT, 1)
    assert ask.quote.status == "ok" and ask.quote.price == 180.0   # median
    assert ask.floor == 170.0 and ask.count == 3
    assert ask.quote.sample_size == 3 and ask.quote.kind == model.ACTIVE_ASK


def test_ebay_no_matches():
    ask = EbayAskSource(cfg=None, client=FakeEbayClient({"itemSummaries": []})).fetch("k", PRODUCT, 1)
    assert ask.quote.status == "no_match" and ask.floor is None


def test_ebay_transport_error():
    ask = EbayAskSource(cfg=None, client=FakeEbayClient(
        exc=requests.ConnectionError("down"))).fetch("k", PRODUCT, 1)
    assert ask.quote.status == "error"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_comps_sources.py -q`
Expected: new tests FAIL (module not found); Task-4 tests PASS.

- [ ] **Step 3: Implement**

```python
"""eBay Browse active-ask source: median + floor + matched count.

Ask prices are context and corroboration - kind=ACTIVE_ASK is load-bearing (an
ask-derived comp can never mint a STEAL). Degrades to not_configured while the
operator's eBay developer keyset is pending (docs/poke/ebay-keyset-setup.md).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import requests

from .. import resale
from .model import ACTIVE_ASK, CompSourceQuote, EbayAsk


class EbayAskSource:
    def __init__(self, cfg: Any, client: Any = None) -> None:
        if client is not None:
            self.client = client
        elif cfg is not None and resale.auth_configured(cfg):
            self.client = resale.EbayResaleClient.from_config(cfg)
        else:
            self.client = None

    def fetch(self, product_key: str, product: dict, checked_at: int) -> EbayAsk:
        query = resale.product_query(product)
        url = resale.ebay_search_web_url(query)
        fetched_at = datetime.fromtimestamp(checked_at).isoformat(timespec="seconds")

        def quote(status, price=None, sample=None, detail="", excerpt=""):
            return EbayAsk(CompSourceQuote("ebay_api", ACTIVE_ASK, status, price, url,
                                           fetched_at, sample_size=sample, detail=detail,
                                           raw_excerpt=excerpt))

        if self.client is None:
            return quote("not_configured",
                         detail="eBay Browse keyset not configured "
                                "(docs/poke/ebay-keyset-setup.md)")
        try:
            payload = self.client.search_payload(product)
        except resale.ResaleAuthMissing as exc:
            return quote("not_configured", detail=str(exc))
        except requests.RequestException as exc:
            return quote("error", detail=resale._safe_detail(str(exc)))
        prices = resale.matched_prices(product, payload)
        if not prices:
            return quote("no_match", detail="no matched active listings")
        median = resale._quantile(prices, 0.5)
        return EbayAsk(
            CompSourceQuote("ebay_api", ACTIVE_ASK, "ok", median, url, fetched_at,
                            sample_size=len(prices),
                            raw_excerpt=f"{len(prices)} matched active listings; "
                                        f"floor ${prices[0]:.2f}"),
            floor=prices[0], count=len(prices))
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_comps_sources.py -q` — Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scanner/comps/ebay.py tests/test_comps_sources.py
git commit -m "feat(comps): eBay Browse active-ask source with keyset-pending degradation"
```

---

### Task 6: `comps/tcgplayer.py` source (variant per Task-1 decision)

**Files:**
- Create: `scanner/comps/tcgplayer.py`
- Test: `tests/test_comps_sources.py` (append)

**Interfaces:**
- Consumes: Task-1 fixtures + decision; `model.CompSourceQuote`.
- Produces (used by Task 9): `TcgPlayerSource(cfg, session=None)` with
  `fetch(product_key, product, checked_at) -> CompSourceQuote` (never raises);
  module constant `PRODUCT_URL = "https://www.tcgplayer.com/product/{ppt_id}"`.

Both variants below are complete; ship exactly the one Task 1 decided. The shared shell is
identical — only `market_price_from_html` vs the hard `blocked` return differs.

- [ ] **Step 1: Write the failing tests (append; keep all four for PARSER, the marked three for STUB)**

```python
from pathlib import Path

from scanner.comps.tcgplayer import TcgPlayerSource

FIXTURES = Path(__file__).parent / "fixtures" / "comps"


class FakeHttpResp:
    def __init__(self, status_code=200, text=""):
        self.status_code, self.text = status_code, text


class FakeHttpSession:
    def __init__(self, resp=None, exc=None):
        self.resp, self.exc = resp, exc
    def get(self, url, **kwargs):
        if self.exc: raise self.exc
        return self.resp


def test_tcg_no_ppt_id_is_skipped():          # both variants
    quote = TcgPlayerSource(cfg=None, session=FakeHttpSession()).fetch(
        "k", {"name": "X"}, 1)
    assert quote.status == "skipped" and quote.price is None


def test_tcg_http_403_is_blocked():           # both variants
    quote = TcgPlayerSource(cfg=None, session=FakeHttpSession(FakeHttpResp(403))).fetch(
        "k", {"name": "X", "ppt_id": "593355"}, 1)
    assert quote.status == "blocked"
    assert quote.url == "https://www.tcgplayer.com/product/593355"


def test_tcg_transport_error():               # both variants
    import requests
    quote = TcgPlayerSource(cfg=None, session=FakeHttpSession(
        exc=requests.ConnectionError("x"))).fetch("k", {"name": "X", "ppt_id": "1"}, 1)
    assert quote.status == "error"


def test_tcg_parses_market_price_from_fixture():   # PARSER variant ONLY
    html = (FIXTURES / "tcgplayer_product_593355.html").read_text(encoding="utf-8")
    quote = TcgPlayerSource(cfg=None, session=FakeHttpSession(FakeHttpResp(200, html))).fetch(
        "k", {"name": "Prismatic Evolutions Elite Trainer Box", "ppt_id": "593355"}, 1)
    assert quote.status == "ok"
    assert quote.price is not None and 40.0 < quote.price < 800.0  # plausibility band
    assert quote.raw_excerpt
# STUB variant ONLY: replace the fixture test with -
# def test_tcg_stub_reports_blocked_pending_acquisition():
#     quote = TcgPlayerSource(cfg=None, session=FakeHttpSession(FakeHttpResp(200, "<html/>"))).fetch(
#         "k", {"name": "X", "ppt_id": "593355"}, 1)
#     assert quote.status == "blocked"
#     assert "tcgplayer-probe" in quote.detail
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_comps_sources.py -q`
Expected: new tests FAIL (module not found).

- [ ] **Step 3: Implement the shared shell + the decided variant**

```python
"""TCGplayer product-page market price (sold-derived; the number PPT resells).

Acquisition path fixed by the Task-1 probe - see docs/poke/reference/tcgplayer-probe.md.
Plain requests only; 403/429 -> blocked (never evaded).
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import requests

from .model import SOLD_DERIVED, CompSourceQuote

PRODUCT_URL = "https://www.tcgplayer.com/product/{ppt_id}"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0 Safari/537.36"
)

# PARSER variant: pattern locked to the Task-1 fixture. Adjust the regex to the
# fixture's exact shape if it differs, and keep the fixture test pinning it.
_MARKET_PRICE = re.compile(r'"marketPrice"\s*:\s*"?\$?([0-9][0-9,]*(?:\.[0-9]{1,2})?)"?')


def market_price_from_html(text: str) -> tuple[float | None, str]:
    match = _MARKET_PRICE.search(text)
    if not match:
        return None, ""
    try:
        return float(match.group(1).replace(",", "")), match.group(0)[:200]
    except ValueError:
        return None, ""


class TcgPlayerSource:
    def __init__(self, cfg: Any, session: Any = None) -> None:
        self.session = session or requests.Session()

    def fetch(self, product_key: str, product: dict, checked_at: int) -> CompSourceQuote:
        fetched_at = datetime.fromtimestamp(checked_at).isoformat(timespec="seconds")
        ppt_id = str(product.get("ppt_id") or "").strip()
        if not ppt_id:
            return CompSourceQuote("tcgplayer", SOLD_DERIVED, "skipped", None, "",
                                   fetched_at,
                                   detail="no ppt_id (TCGplayer product id) mapped")
        url = PRODUCT_URL.format(ppt_id=ppt_id)
        try:
            resp = self.session.get(url, headers={"User-Agent": UA, "Accept": "text/html"},
                                    timeout=20)
        except requests.RequestException as exc:
            return CompSourceQuote("tcgplayer", SOLD_DERIVED, "error", None, url,
                                   fetched_at, detail=str(exc)[:200])
        if resp.status_code in (403, 429):
            return CompSourceQuote("tcgplayer", SOLD_DERIVED, "blocked", None, url,
                                   fetched_at, detail=f"HTTP {resp.status_code}")
        if resp.status_code != 200:
            return CompSourceQuote("tcgplayer", SOLD_DERIVED, "error", None, url,
                                   fetched_at, detail=f"HTTP {resp.status_code}")
        price, excerpt = market_price_from_html(resp.text)
        if price is None:
            return CompSourceQuote("tcgplayer", SOLD_DERIVED, "no_match", None, url,
                                   fetched_at,
                                   detail="page fetched but no market price parsed "
                                          "(parser drift? see tcgplayer-probe.md)")
        return CompSourceQuote("tcgplayer", SOLD_DERIVED, "ok", price, url, fetched_at,
                               raw_excerpt=excerpt)
```

STUB variant: delete `_MARKET_PRICE`/`market_price_from_html`, and replace everything
after the 403/429 check in `fetch` with:

```python
        return CompSourceQuote(
            "tcgplayer", SOLD_DERIVED, "blocked", None, url, fetched_at,
            detail="acquisition unresolved (probe 2026-07-03): page serves no parseable "
                   "price to plain requests; see docs/poke/reference/tcgplayer-probe.md")
```

- [ ] **Step 4: Run to verify pass, then full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_comps_sources.py -q` — Expected: PASS.
Run: `.venv/Scripts/python.exe -m pytest -q` — Expected: 0 failures.

- [ ] **Step 5: Commit**

```bash
git add scanner/comps/tcgplayer.py tests/test_comps_sources.py
git commit -m "feat(comps): TCGplayer sold-derived source (variant per Task-1 probe)"
```

---

### Task 7: `state.py` comp cache table

**Files:**
- Modify: `scanner/state.py` (`_init_schema` ~line 65; new methods after `source_health_snapshot`)
- Test: `tests/test_state_history.py` (append)

**Interfaces:**
- Produces (used by Task 9): `State.comp_cache_get(item_key) -> tuple[dict, int] | None`
  (payload, fetched_at unix ts) and `State.comp_cache_put(item_key, payload: dict, ts: int | None = None) -> None`.

- [ ] **Step 1: Write the failing tests (append; follow the file's existing tmp-db pattern)**

```python
def test_comp_cache_roundtrip(tmp_path):
    from scanner.state import State
    state = State(db_path=tmp_path / "state.db")
    assert state.comp_cache_get("set|item|||") is None
    state.comp_cache_put("set|item|||", {"status": "ok", "estimate": "$10.00"}, ts=1000)
    payload, fetched_at = state.comp_cache_get("set|item|||")
    assert payload["estimate"] == "$10.00" and fetched_at == 1000
    state.comp_cache_put("set|item|||", {"status": "ok", "estimate": "$12.00"}, ts=2000)
    payload, fetched_at = state.comp_cache_get("set|item|||")
    assert payload["estimate"] == "$12.00" and fetched_at == 2000   # upsert, one row
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_state_history.py -q`
Expected: new test FAILS (`AttributeError: comp_cache_get`).

- [ ] **Step 3: Implement**

Add to `_init_schema` (after the `source_health` create):

```python
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS comp_cache (
                item_key TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                fetched_at INTEGER NOT NULL
            )
            """
        )
```

Add methods (after `source_health_snapshot`):

```python
    def comp_cache_get(self, item_key: str) -> tuple[dict[str, Any], int] | None:
        row = self.db.execute(
            "SELECT payload_json, fetched_at FROM comp_cache WHERE item_key=?",
            (item_key,),
        ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row[0])
        except (TypeError, ValueError):
            return None
        return (payload, int(row[1])) if isinstance(payload, dict) else None

    def comp_cache_put(
        self, item_key: str, payload: dict[str, Any], ts: int | None = None
    ) -> None:
        now = ts if ts is not None else int(time.time())
        self.db.execute(
            """
            INSERT INTO comp_cache(item_key, payload_json, fetched_at)
            VALUES (?, ?, ?)
            ON CONFLICT(item_key)
            DO UPDATE SET payload_json=excluded.payload_json,
                          fetched_at=excluded.fetched_at
            """,
            (item_key, json.dumps(payload, sort_keys=True), now),
        )
        self.db.commit()
```

- [ ] **Step 4: Run to verify pass, then full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_state_history.py -q` — Expected: PASS.
Run: `.venv/Scripts/python.exe -m pytest -q` — Expected: 0 failures.

- [ ] **Step 5: Commit**

```bash
git add scanner/state.py tests/test_state_history.py
git commit -m "feat(comps): comp_cache table + get/put on State"
```

---

### Task 8: config `comps` block

**Files:**
- Modify: `scanner/config.py` (new `CompsCfg` dataclass near `PokeCfg` ~line 32; parsing in
  `from_mapping` near the `poke` block ~line 158; field on `Config` ~line 76)
- Modify: `config.example.yaml`
- Test: `tests/test_config.py` (append)

**Interfaces:**
- Produces (used by Tasks 9, 11): `cfg.comps` with fields
  `engine: str ("legacy"|"inhouse")`, `agreement_tolerance_pct: float`,
  `ebay_floor_sanity_pct: float`, `cache_ttl_seconds: int`, `politeness_seconds: float`.

- [ ] **Step 1: Write the failing tests (append, following the file's `from_mapping` fixture style)**

```python
def test_comps_defaults(base_raw):
    from scanner import config as cfg_mod
    cfg = cfg_mod.from_mapping(base_raw)
    assert cfg.comps.engine == "legacy"
    assert cfg.comps.agreement_tolerance_pct == 20.0
    assert cfg.comps.ebay_floor_sanity_pct == 50.0
    assert cfg.comps.cache_ttl_seconds == 21600
    assert cfg.comps.politeness_seconds == 1.0


def test_comps_engine_validated(base_raw):
    import pytest
    from scanner import config as cfg_mod
    base_raw["comps"] = {"engine": "warp-drive"}
    with pytest.raises(SystemExit):
        cfg_mod.from_mapping(base_raw)


def test_comps_inhouse_accepted(base_raw):
    from scanner import config as cfg_mod
    base_raw["comps"] = {"engine": "inhouse", "cache_ttl_seconds": 60}
    cfg = cfg_mod.from_mapping(base_raw)
    assert cfg.comps.engine == "inhouse" and cfg.comps.cache_ttl_seconds == 60
```

(If `tests/test_config.py` has no reusable `base_raw` fixture, copy the minimal valid raw
mapping already used by its existing tests into a local fixture.)

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_config.py -q`
Expected: new tests FAIL (`AttributeError: comps`).

- [ ] **Step 3: Implement**

Dataclass (place next to `PokeCfg`):

```python
@dataclass
class CompsCfg:
    engine: str = "legacy"                 # legacy | inhouse (Slice-6 flips the default)
    agreement_tolerance_pct: float = 20.0
    ebay_floor_sanity_pct: float = 50.0
    cache_ttl_seconds: int = 21600
    politeness_seconds: float = 1.0
```

Field on `Config`: `comps: CompsCfg = field(default_factory=CompsCfg)`.

Parsing in `from_mapping` (next to the `poke` block, same idiom):

```python
    comps_raw = raw.get("comps")
    if comps_raw is None:
        comps_raw = {}
    if not isinstance(comps_raw, dict):
        raise SystemExit("config.yaml: comps must be a mapping.")
    comps_engine = str(comps_raw.get("engine", "legacy")).strip().lower()
    if comps_engine not in {"legacy", "inhouse"}:
        raise SystemExit("config.yaml: comps.engine must be 'legacy' or 'inhouse'.")
    try:
        comps_cfg = CompsCfg(
            engine=comps_engine,
            agreement_tolerance_pct=_num(comps_raw, "agreement_tolerance_pct", 20.0,
                                         "comps.agreement_tolerance_pct"),
            ebay_floor_sanity_pct=_num(comps_raw, "ebay_floor_sanity_pct", 50.0,
                                       "comps.ebay_floor_sanity_pct"),
            cache_ttl_seconds=int(comps_raw.get("cache_ttl_seconds", 21600)),
            politeness_seconds=_num(comps_raw, "politeness_seconds", 1.0,
                                    "comps.politeness_seconds"),
        )
    except (TypeError, ValueError):
        raise SystemExit("config.yaml: comps.cache_ttl_seconds must be an integer.")
```

and pass `comps=comps_cfg` in the `Config(...)` constructor call. `config.example.yaml`
addition (bottom of file):

```yaml
comps:
  engine: legacy            # 'inhouse' = multi-source comp engine (Slice 6 flips default)
  agreement_tolerance_pct: 20
  ebay_floor_sanity_pct: 50
  cache_ttl_seconds: 21600  # 6h
```

- [ ] **Step 4: Run to verify pass, then full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_config.py -q` — Expected: PASS.
Run: `.venv/Scripts/python.exe -m pytest -q` — Expected: 0 failures.

- [ ] **Step 5: Commit**

```bash
git add scanner/config.py config.example.yaml tests/test_config.py
git commit -m "feat(comps): comps config block (engine switch defaults to legacy)"
```

---

### Task 9: `comps/engine.py` — fan-out, cache, staleness, ledger, legacy emit

**Files:**
- Create: `scanner/comps/engine.py`
- Test: `tests/test_comps_engine.py`

**Interfaces:**
- Consumes: everything above (`model.resolve`, `model.to_legacy_row`, the three sources,
  `State.comp_cache_*`, `ledger.append_observation`, `cfg.comps`).
- Produces (used by Task 10, 11): `CompEngine(cfg, state=None, tcg_source=None,
  pc_source=None, ebay_source=None, ledger_path=None, clock=time.time, sleep=time.sleep)`
  with `estimate(product_key, product, checked_at) -> dict` (the legacy row; adds
  `creditsConsumed: 0`) and classmethod `from_config(cfg)`.

- [ ] **Step 1: Write the failing tests**

```python
"""CompEngine: cache TTL, staleness ladder (spec 4.4), ledger appends, legacy round-trip."""
import json
from pathlib import Path

from scanner.comps import model
from scanner.comps.engine import CompEngine
from scanner.state import State
from scanner import market as market_mod
from scanner.discovery import sweep as sweep_mod

PRODUCT = {"name": "Destined Rivals Elite Trainer Box", "set": "Destined Rivals",
           "type": "ETB", "msrp": "$49.99",
           "resale_query": "Pokemon TCG Destined Rivals Elite Trainer Box sealed",
           "ppt_id": "624676"}


class Cfg:
    class comps:
        engine = "inhouse"
        agreement_tolerance_pct = 20.0
        ebay_floor_sanity_pct = 50.0
        cache_ttl_seconds = 21600
        politeness_seconds = 0.0
    class poke:
        staleness_days = 30


class RecordingSource:
    def __init__(self, result):
        self.result, self.calls = result, 0
    def fetch(self, key, product, checked_at):
        self.calls += 1
        return self.result


def ok_quote(source, price, url):
    return model.CompSourceQuote(source, model.SOLD_DERIVED, "ok", price, url,
                                 "2026-07-03T10:00:00")


def failed_quote(source):
    return model.CompSourceQuote(source, model.SOLD_DERIVED, "error", None,
                                 "https://example.com", "2026-07-03T10:00:00", detail="down")


def make_engine(tmp_path, tcg, pc, ebay=None, clock=lambda: 1_000_000.0):
    return CompEngine(
        Cfg(), state=State(db_path=tmp_path / "state.db"),
        tcg_source=RecordingSource(tcg), pc_source=RecordingSource(pc),
        ebay_source=RecordingSource(ebay or model.EbayAsk(
            model.CompSourceQuote("ebay_api", model.ACTIVE_ASK, "not_configured", None,
                                  "https://ebay.com", "2026-07-03T10:00:00"))),
        ledger_path=tmp_path / "history.jsonl", clock=clock, sleep=lambda s: None)


def test_estimate_round_trips_through_existing_pipeline(tmp_path):
    engine = make_engine(
        tmp_path,
        ok_quote("tcgplayer", 180.65, "https://www.tcgplayer.com/product/624676"),
        ok_quote("pricecharting", 190.0,
                 "https://www.pricecharting.com/game/pokemon-destined-rivals/elite-trainer-box"))
    row = engine.estimate("destined_rivals_etb", PRODUCT, 1_000_000)
    assert market_mod.comp_from_row(row) == (180.65, "high")
    assert row["creditsConsumed"] == 0            # never spends PPT credits
    price_conf, source_url, method, detail = sweep_mod._provenance(row, "high")
    assert price_conf == "verified"
    assert source_url == "https://www.tcgplayer.com/product/624676"


def test_cache_hit_within_ttl_skips_sources(tmp_path):
    tcg = ok_quote("tcgplayer", 100.0, "https://www.tcgplayer.com/product/1")
    pc = ok_quote("pricecharting", 105.0, "https://www.pricecharting.com/game/a/b")
    engine = make_engine(tmp_path, tcg, pc)
    engine.estimate("k", PRODUCT, 1_000_000)
    assert engine.tcg.calls == 1
    row2 = engine.estimate("k", PRODUCT, 1_000_000 + 60)
    assert engine.tcg.calls == 1                  # served from cache
    assert row2["status"] == "ok" and row2.get("cacheHit") is True


def test_ttl_expiry_refetches(tmp_path):
    tcg = ok_quote("tcgplayer", 100.0, "https://www.tcgplayer.com/product/1")
    pc = ok_quote("pricecharting", 105.0, "https://www.pricecharting.com/game/a/b")
    engine = make_engine(tmp_path, tcg, pc)
    engine.estimate("k", PRODUCT, 1_000_000)
    engine.estimate("k", PRODUCT, 1_000_000 + 21601)
    assert engine.tcg.calls == 2


def test_refetch_failure_serves_cached_degraded_one_tier(tmp_path):
    engine = make_engine(
        tmp_path,
        ok_quote("tcgplayer", 100.0, "https://www.tcgplayer.com/product/1"),
        ok_quote("pricecharting", 105.0, "https://www.pricecharting.com/game/a/b"))
    engine.estimate("k", PRODUCT, 1_000_000)                     # cached as high
    engine.tcg.result = failed_quote("tcgplayer")
    engine.pc.result = failed_quote("pricecharting")
    row = engine.estimate("k", PRODUCT, 1_000_000 + 30000)       # ttl < age < 24h
    assert row["status"] == "ok" and row["confidence"] == "medium"   # high -> medium
    assert "cached" in row["detail"]


def test_cache_older_than_24h_is_stale_low(tmp_path):
    engine = make_engine(
        tmp_path,
        ok_quote("tcgplayer", 100.0, "https://www.tcgplayer.com/product/1"),
        ok_quote("pricecharting", 105.0, "https://www.pricecharting.com/game/a/b"))
    engine.estimate("k", PRODUCT, 1_000_000)
    engine.tcg.result = failed_quote("tcgplayer")
    engine.pc.result = failed_quote("pricecharting")
    row = engine.estimate("k", PRODUCT, 1_000_000 + 90000)       # > 24h
    assert row["status"] == "ok" and row["confidence"] == "low"
    assert row.get("stale") is True


def test_cache_older_than_30d_is_honest_no_match(tmp_path):
    engine = make_engine(
        tmp_path,
        ok_quote("tcgplayer", 100.0, "https://www.tcgplayer.com/product/1"),
        ok_quote("pricecharting", 105.0, "https://www.pricecharting.com/game/a/b"))
    engine.estimate("k", PRODUCT, 1_000_000)
    engine.tcg.result = failed_quote("tcgplayer")
    engine.pc.result = failed_quote("pricecharting")
    row = engine.estimate("k", PRODUCT, 1_000_000 + 31 * 86400)
    assert row["status"] == "no_matches"
    assert market_mod.comp_from_row(row) == (None, "none")       # no invented number


def test_ledger_one_observation_per_ok_source_per_day(tmp_path):
    engine = make_engine(
        tmp_path,
        ok_quote("tcgplayer", 100.0, "https://www.tcgplayer.com/product/1"),
        ok_quote("pricecharting", 105.0, "https://www.pricecharting.com/game/a/b"))
    engine.estimate("k", PRODUCT, 1_000_000)
    lines = [json.loads(l) for l in
             (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 2                       # one per ok source
    assert {l["source"] for l in lines} == {"tcgplayer", "pricecharting"}
    assert all(l["kind"] == "market_comp" for l in lines)
    # idempotent within the day: cache-busted second call adds nothing
    engine.estimate("k", PRODUCT, 1_000_000 + 21601)
    lines2 = (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines2) == 2
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_comps_engine.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `scanner/comps/engine.py`**

```python
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
        return cls(cfg)

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
```

(`model.resale` works because model.py does `from .. import resale`; if the reviewer
prefers, import `resale` directly in engine.py — either is consistent with repo style.)

- [ ] **Step 4: Run to verify pass, then full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_comps_engine.py -q` — Expected: PASS.
Run: `.venv/Scripts/python.exe -m pytest -q` — Expected: 0 failures.

- [ ] **Step 5: Commit**

```bash
git add scanner/comps/engine.py tests/test_comps_engine.py
git commit -m "feat(comps): CompEngine fan-out with cache/staleness ladder + per-source history"
```

---

### Task 10: `comps/ppt_validator.py` — off-hot-path spot check

**Files:**
- Create: `scanner/comps/ppt_validator.py`
- Test: `tests/test_comps_validator.py`

**Interfaces:**
- Consumes: `market.PokemonPriceTrackerClient` (limit=1 already pinned there),
  `CompEngine`, `cfg.products`.
- Produces: CLI `python -m scanner.comps.ppt_validator --products k1,k2 --yes`;
  `main(argv, cfg=None, ppt_client=None, engine=None) -> int` (0 ok, 1 hard-stop, 2 refused).

- [ ] **Step 1: Write the failing tests**

```python
"""Validator refusal + hard-stop paths. Zero network - clients injected."""
from scanner.comps import ppt_validator


class Cfg:
    market_api_key = "k"
    products = {"a": {"name": "A", "ppt_id": "1", "msrp": "$50"},
                "b": {"name": "B", "ppt_id": "2", "msrp": "$30"}}


class FakePpt:
    def __init__(self, rows):
        self.rows, self.calls = rows, 0
    def estimate(self, key, product, checked_at):
        row = self.rows[self.calls]
        self.calls += 1
        return row


class FakeEngine:
    def estimate(self, key, product, checked_at):
        return {"status": "ok", "estimate": "$100.00", "confidence": "high"}


def test_refuses_without_key(capsys):
    cfg = Cfg(); cfg.market_api_key = ""
    assert ppt_validator.main(["--products", "a", "--yes"], cfg=cfg) == 2
    assert "market.api_key" in capsys.readouterr().out


def test_refuses_without_yes(capsys):
    assert ppt_validator.main(["--products", "a"], cfg=Cfg()) == 2
    out = capsys.readouterr().out
    assert "--yes" in out and "1 credit" in out     # spend surfaced before refusal


def test_refuses_unknown_product(capsys):
    assert ppt_validator.main(["--products", "nope", "--yes"], cfg=Cfg()) == 2


def test_hard_stops_below_15_remaining(capsys):
    ppt = FakePpt([{"status": "ok", "estimate": "$99.00", "dailyRemaining": 9,
                    "creditsConsumed": 1}])
    rc = ppt_validator.main(["--products", "a,b", "--yes"], cfg=Cfg(),
                            ppt_client=ppt, engine=FakeEngine())
    assert rc == 1
    assert ppt.calls == 1                            # never touched product b
    assert "HARD STOP" in capsys.readouterr().out


def test_compares_and_reports_delta(capsys):
    ppt = FakePpt([{"status": "ok", "estimate": "$110.00", "dailyRemaining": 80,
                    "creditsConsumed": 1}])
    rc = ppt_validator.main(["--products", "a", "--yes"], cfg=Cfg(),
                            ppt_client=ppt, engine=FakeEngine())
    assert rc == 0
    out = capsys.readouterr().out
    assert "a" in out and "$110.00" in out and "$100.00" in out and "9.1%" in out
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_comps_validator.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```python
"""PPT spot-check validator - NEVER called by any pipeline (spec 4.6).

Money-class guardrails: refuses without market.api_key; surfaces the credit
estimate and refuses without --yes (operator go-ahead); hard-stops when the
daily remaining balance drops below 15 (post-charge header, seeding convention).
Spec: docs/superpowers/specs/2026-07-02-buyable-deal-pipeline-design.md 4.6.
Note: spec 4.6 wrote `-m scanner.comps.validate`; canonical module name is
ppt_validator (cosmetic naming deviation, recorded here).
"""
from __future__ import annotations

import argparse
import time
from typing import Any

from .. import config as cfg_mod
from .. import market as market_mod
from .. import resale
from .engine import CompEngine

HARD_STOP_REMAINING = 15


def _delta_pct(ours: float | None, theirs: float | None) -> str:
    if not ours or not theirs:
        return "n/a"
    return f"{abs(ours - theirs) / theirs * 100.0:.1f}%"


def main(argv: list[str] | None = None, cfg: Any = None,
         ppt_client: Any = None, engine: Any = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scanner.comps.ppt_validator",
        description="Compare in-house comps vs PPT (1 credit/product, limit=1).")
    parser.add_argument("--products", required=True,
                        help="comma-separated catalog keys")
    parser.add_argument("--yes", action="store_true",
                        help="operator go-ahead for the surfaced credit spend")
    args = parser.parse_args(argv)

    cfg = cfg or cfg_mod.load()
    if not getattr(cfg, "market_api_key", ""):
        print("refused: market.api_key not configured")
        return 2
    keys = [k.strip() for k in args.products.split(",") if k.strip()]
    unknown = [k for k in keys if k not in cfg.products]
    if unknown:
        print(f"refused: unknown product keys: {', '.join(unknown)}")
        return 2
    print(f"estimated spend: ~{len(keys)} credit(s) (1 credit/product, limit=1 pinned)")
    if not args.yes:
        print("refused: pass --yes only after operator go-ahead (PPT credits are money-class)")
        return 2

    ppt = ppt_client or market_mod.PokemonPriceTrackerClient.from_config(cfg)
    eng = engine or CompEngine.from_config(cfg)
    for key in keys:
        product = cfg.products[key]
        checked_at = int(time.time())
        theirs = ppt.estimate(key, product, checked_at)
        ours = eng.estimate(key, product, checked_at)
        t_val = resale._amount(theirs.get("estimate"))
        o_val = resale._amount(ours.get("estimate"))
        print(f"{key}: ppt={theirs.get('estimate') or 'n/a'} "
              f"inhouse={ours.get('estimate') or 'n/a'} "
              f"delta={_delta_pct(o_val, t_val)} "
              f"(inhouse confidence: {ours.get('confidence')})")
        remaining = theirs.get("dailyRemaining")
        if isinstance(remaining, int) and remaining < HARD_STOP_REMAINING:
            print(f"HARD STOP: daily remaining {remaining} < {HARD_STOP_REMAINING}; "
                  f"stopping before the next product")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run to verify pass, then full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_comps_validator.py -q` — Expected: PASS.
Run: `.venv/Scripts/python.exe -m pytest -q` — Expected: 0 failures.

- [ ] **Step 5: Commit**

```bash
git add scanner/comps/ppt_validator.py tests/test_comps_validator.py
git commit -m "feat(comps): PPT spot-check validator with money-class refusal gates"
```

---

### Task 11: `LiveCompLookup` engine switch (default unchanged)

**Files:**
- Modify: `scanner/discovery/sweep.py` (`LiveCompLookup.__init__` ~lines 157–168; imports ~line 21)
- Test: `tests/test_poke_sweep.py` (append)

**Interfaces:**
- Consumes: `CompEngine.from_config` (Task 9), `cfg.comps.engine` (Task 8).
- Produces: `comps.engine: "inhouse"` in config routes the sweep's comp lookups through
  `CompEngine`; `"legacy"` (default) keeps today's PPT/resale wiring byte-identical.

- [ ] **Step 1: Write the failing tests (append, reusing the file's existing cfg fixture idiom)**

```python
def test_livecomplookup_inhouse_engine_selected(poke_cfg):
    from scanner.comps.engine import CompEngine
    from scanner.discovery.sweep import LiveCompLookup
    poke_cfg.comps.engine = "inhouse"
    lookup = LiveCompLookup(poke_cfg)
    assert isinstance(lookup.market_client, CompEngine)


def test_livecomplookup_legacy_default_unchanged(poke_cfg):
    from scanner.comps.engine import CompEngine
    from scanner.discovery.sweep import LiveCompLookup
    poke_cfg.comps.engine = "legacy"
    lookup = LiveCompLookup(poke_cfg)
    assert not isinstance(lookup.market_client, CompEngine)
```

(`poke_cfg` = whatever config fixture `tests/test_poke_sweep.py` already builds; if it
constructs `Config` via `from_mapping`, `cfg.comps` exists after Task 8. Adjust attribute
spelling to the fixture, not the other way around.)

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_poke_sweep.py -q`
Expected: the two new tests FAIL; all existing PASS.

- [ ] **Step 3: Implement the switch**

In `scanner/discovery/sweep.py` add the import near the other `..` imports:

```python
from ..comps import engine as comps_engine
```

and in `LiveCompLookup.__init__`, insert the inhouse branch **before** the
`market_preferred` branch (inhouse wins when explicitly configured):

```python
        if market_client is not None:
            self.market_client = market_client
        elif getattr(getattr(cfg, "comps", None), "engine", "legacy") == "inhouse":
            self.market_client = comps_engine.CompEngine.from_config(cfg)
        elif getattr(cfg, "market_preferred", False) and getattr(cfg, "market_api_key", ""):
            self.market_client = market_mod.MarketFallbackClient(
                market_mod.PokemonPriceTrackerClient.from_config(cfg), self.resale_client)
        else:
            self.market_client = None
```

- [ ] **Step 4: Run sweep tests, then full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_poke_sweep.py -q` — Expected: PASS.
Run: `.venv/Scripts/python.exe -m pytest -q` — Expected: 0 failures (legacy default proven
by the untouched pre-existing sweep tests).

- [ ] **Step 5: Commit**

```bash
git add scanner/discovery/sweep.py tests/test_poke_sweep.py
git commit -m "feat(comps): LiveCompLookup honors comps.engine (default legacy, behavior unchanged)"
```

---

### Task 12: Final verification + progress ledger

**Files:**
- Modify: `.superpowers/sdd/progress.md` (append new section)

- [ ] **Step 1: Full suite + focused re-run**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: baseline (276) + all new tests, 0 failures. Record the exact count.
Run: `.venv/Scripts/python.exe -m pytest tests/test_comps_model.py tests/test_comps_sources.py tests/test_comps_engine.py tests/test_comps_validator.py -q`
Expected: all PASS.

- [ ] **Step 2: Grep guardrail spot-checks (all must hold)**

```bash
grep -n "limit.*1" scanner/market.py            # limit=1 still pinned (untouched)
grep -rn "creditsConsumed.*0" scanner/comps/engine.py   # engine spends nothing
grep -n "engine: legacy" config.example.yaml    # default documented as legacy
```

- [ ] **Step 3: Append the progress-ledger section**

```markdown
# Buyable-Deal Pipeline — Slice 1 (comp engine) — Progress Ledger

Plan: docs/superpowers/plans/2026-07-03-comp-engine-slice1.md
Spec: docs/superpowers/specs/2026-07-02-buyable-deal-pipeline-design.md (approved 2026-07-03)
Baseline suite: 276 passed. In-place on local main; never pushed.

## Tasks
Task 1 (probe): <PARSER|STUB> — <one-line evidence summary + commit>
Task 2-11: <commit + one-line status each, filled as executed>
Task 12: final suite <N> passed.
eBay keyset: PENDING operator (developer-program acceptance) — engine runs degraded by design.
```

- [ ] **Step 4: Commit**

```bash
git add .superpowers/sdd/progress.md
git commit -m "docs(poke): Slice-1 progress ledger (comp engine v1 complete)"
```

---

## Plan self-review notes (already applied)

- **Spec coverage:** §4.1 objects (Task 2), §4.2 ladder (Tasks 1, 6), §4.3 matrix (Task 2,
  14 cases), §4.4 staleness (Task 9 tests each rung), §4.5 history (Task 9 ledger tests),
  §4.6 validator (Task 10), §3.1 legacy-shape contract (Tasks 2, 9 round-trip through the
  REAL `comp_from_row` + `_provenance`), Slice-1 acceptance list (Tasks 8, 11, 12).
- **eBay-keyset-pending:** `not_configured` is the tested default path (Task 5 first test;
  Task 9's default fake is not_configured), per operator status 2026-07-03.
- **Known deviation recorded:** validator module named `ppt_validator` (spec §4.6 prose
  said `.validate`; §9.1 layout said `ppt_validator.py` — layout wins, noted in docstring).
- **Type consistency check:** `fetch(...)` returns `CompSourceQuote` for tcg/pc and
  `EbayAsk` for ebay everywhere (Tasks 4/5/6/9); `resolve` signature identical in Tasks 2
  and 9; `comp_cache_get` tuple order (payload, fetched_at) identical in Tasks 7 and 9.
