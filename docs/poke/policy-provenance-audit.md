# Policy Provenance Audit — 2026-07-04

**Purpose.** Inventory every "boundary" statement in the repo (what the program
will/won't do and why) and classify each by **provenance** — is it the operator's
own policy, an assistant-inserted elaboration, a technical safety gate, a
cost/secret control, a release gate, or genuinely-unclear business policy that
should be marked `TBD_OPERATOR_POLICY`?

**This is an audit, not a rewrite.** No boundary language was edited in this
pass. A conservative proposed-patch list is at the end; nothing on it is applied.
Per operator instruction, runtime safety, credit-spend, secret-handling, and
release-gate logic are **classified**, never blindly replaced with TBD.

## Provenance classes

| Class | Meaning |
| --- | --- |
| `OPERATOR_POLICY_CONFIRMED` | Written in the operator's voice or explicitly attributed to the operator. Ground truth: `DOCTRINE.md` (titled "Hobby MSRP Doctrine (v2)", first-person "I"/"my hobby"), `CLAUDE.md` (repo instructions), `config.example.yaml` operator comments. |
| `ASSISTANT_INSERTED_POLICY` | Policy *framing / moralizing* that lives only in assistant-generated design/service-plan docs and elaborates beyond the operator's terse doctrine, without operator attribution. Usually a *faithful* elaboration — flagged for attribution/trim, not deletion. |
| `TECHNICAL_SAFETY_GATE` | A boundary whose primary justification is technical: ToS/account-ban avoidance, anti-bot-wall, no-evasion, read-only/no-cart. Code-enforced. |
| `COST_OR_SECRET_GATE` | Money or secret handling: PPT credits, API keys, `config.yaml` gitignore, webhook redaction. |
| `RELEASE_GATE` | "Not yet, gated on review": operator-gated live smoke, scheduler registration, `comps.engine` cutover. |
| `TBD_OPERATOR_POLICY` | Genuinely unclear or unset **business** policy. Never applied to a technical/cost/release gate. |

**Atoms, not sentences (load-bearing).** Most doctrine lines are *mixed*: "no
proxy/distributed polling" is simultaneously `OPERATOR_POLICY_CONFIRMED` (it is
in `DOCTRINE.md`) and `TECHNICAL_SAFETY_GATE` (ToS/ban rationale). Each row below
carries a **primary** class and a **mixed-with** note. Replacing a mixed line
wholesale would destroy a technical protection while editing wording — which is
exactly why the operator forbade blind replacement.

## Source-of-truth hierarchy

1. **`DOCTRINE.md`** — operator ground truth. First-person, titled "v2". Every
   boundary restated elsewhere traces here.
2. **`CLAUDE.md`** — repo instructions in the operator's voice (price accuracy,
   PPT/credit, git/secrets). Operator policy.
3. **`config.example.yaml`** — operator-facing config with operator comments.
4. **Code docstrings** (`margin.py`, `retailers/http.py`, `verify.py`,
   `verify_ids.py`, `comps/tcgplayer.py`, `ppt_validator.py`) — boundaries
   *encoded and enforced* in code. Technical gates.
5. **`docs/superpowers/specs/**` and `docs/superpowers/plans/**`** — assistant-
   generated design docs. They **restate** doctrine (same provenance as the
   source) and occasionally **elaborate** it (assistant-inserted layer).
6. **`docs/service-plan/**`** — the most elaborated assistant layer. `04_DOCTRINE_AND_SAFETY.md`
   self-attributes: *"These are **your** lines (from DOCTRINE.md), plus the
   engineering and anti-scalper reasoning behind them."* → the **lines** are
   operator; the **anti-scalper reasoning/moralizing** is assistant-inserted.

---

## 1. Auto-checkout / cart automation

| Location | Language (excerpt) | Primary | Mixed-with | Note |
| --- | --- | --- | --- | --- |
| `DOCTRINE.md:10` | "No auto-checkout, cart automation, account abuse…" | OPERATOR_POLICY_CONFIRMED | TECHNICAL_SAFETY_GATE | Operator ground truth. |
| `scanner/retailers/http.py:9-10` | "GET/POST here are stock-query requests only — they never mutate cart or purchase state" | TECHNICAL_SAFETY_GATE | OPERATOR_POLICY_CONFIRMED | **Code-enforced** contract. |
| `scanner/verify_ids.py:26` | "…cart/purchase state, matching the scanner's no-purchase contract." | TECHNICAL_SAFETY_GATE | — | Code docstring. |
| `scanner/discovery/verify.py:9` | "sanctioned read-only paths only… No carts, no logins, no bot-wall evasion" | TECHNICAL_SAFETY_GATE | OPERATOR_POLICY_CONFIRMED | Code docstring. |
| `README.md:24`, `README.md:303` | "Auto-checkout / cart bots (against every retailer's ToS…)" ; "tap it, add to cart, check out. That's the entire workflow." | OPERATOR_POLICY_CONFIRMED | TECHNICAL_SAFETY_GATE | README is operator-facing; rationale is ToS/ban (technical). |
| `docs/service-plan/04_DOCTRINE_AND_SAFETY.md:25,69` | matrix rows: "Any cart automation, auto-add, or auto-purchase" = never | ASSISTANT_INSERTED_POLICY | TECHNICAL_SAFETY_GATE | Faithful elaboration of DOCTRINE.md:10. |
| specs/plans (2026-06-18, 06-27, 07-02, 07-03, 07-04) | repeated "no auto-checkout / cart automation" | (inherits) | — | Restatements of DOCTRINE.md; same provenance. |

**Verdict:** operator policy, technically enforced. **Not TBD.** No change needed.

## 2. Login-wall / account scraping

| Location | Language | Primary | Mixed-with | Note |
| --- | --- | --- | --- | --- |
| `DOCTRINE.md:10` | "…login-wall scraping…" | OPERATOR_POLICY_CONFIRMED | TECHNICAL_SAFETY_GATE | Ground truth. |
| `README.md:21` | "No aggressive polling, scraping behind login walls…" | OPERATOR_POLICY_CONFIRMED | TECHNICAL_SAFETY_GATE | |
| `docs/service-plan/04_DOCTRINE_AND_SAFETY.md:26` | "Automating or scraping behind authentication; storing anyone else's account data" | ASSISTANT_INSERTED_POLICY | TECHNICAL_SAFETY_GATE + COST_OR_SECRET_GATE | The "anyone else's account data" atom is a privacy gate; faithful. |

**Verdict:** operator policy + technical/privacy gate. **Not TBD.** No change needed.

## 3. Proxy / distributed polling

| Location | Language | Primary | Mixed-with | Note |
| --- | --- | --- | --- | --- |
| `DOCTRINE.md:11` | "…or proxy/distributed polling. A human reviews and executes every buy and sell." | OPERATOR_POLICY_CONFIRMED | TECHNICAL_SAFETY_GATE | Ground truth; human-in-the-loop is operator's. |
| `README.md:21` | "…distributed/proxy networks" | OPERATOR_POLICY_CONFIRMED | TECHNICAL_SAFETY_GATE | |
| `docs/service-plan/04_DOCTRINE_AND_SAFETY.md:24,70` | "Proxies, proxy rotation, distributed/multi-node polling, residential IP pools" ; polling floor ≥60s | ASSISTANT_INSERTED_POLICY | TECHNICAL_SAFETY_GATE | Elaborated specifics (IP pools, ≥60s floor) are assistant-added engineering detail, faithful to the operator line. |
| `docs/service-plan/03_SERVICE_STRATEGY.md:29,62` | "distributed-traffic pattern the doctrine forbids" (re: hosting/distribution) | ASSISTANT_INSERTED_POLICY | TECHNICAL_SAFETY_GATE | Applies the doctrine to a *hosting* decision — assistant analysis. |

**Verdict:** operator policy + technical gate. **Not TBD.** No change needed.

## 4. Bot-wall / CAPTCHA / evasion

| Location | Language | Primary | Mixed-with | Note |
| --- | --- | --- | --- | --- |
| `scanner/comps/tcgplayer.py:4` | "Plain requests only; 403/429 -> blocked (never evaded)." | TECHNICAL_SAFETY_GATE | — | Code-enforced. |
| `docs/poke/buyable-pipeline-runbook.md:155,201,232` | `BLOCKED` = HTTP 403/429, "Do **not** attempt evasion"; anti-bot page → honest low-yield | TECHNICAL_SAFETY_GATE | OPERATOR_POLICY_CONFIRMED | Runbook operationalizes the doctrine. |
| `docs/poke/target-search-probe-2026-07-03.md:8,28,31` | "No evasion was attempted; none is permitted"; captcha response had no credentials | TECHNICAL_SAFETY_GATE | COST_OR_SECRET_GATE | Probe honored the gate. |
| `docs/service-plan/04_DOCTRINE_AND_SAFETY.md:28,72` | "Solving, bypassing, or outsourcing CAPTCHAs" = never | ASSISTANT_INSERTED_POLICY | TECHNICAL_SAFETY_GATE | Faithful elaboration. |
| `scanner/discovery/resolve.py` docstring, `verify.py` `_blocked_or_unavailable` | 403/429 → SOURCE_BLOCKED, "no evasion" | TECHNICAL_SAFETY_GATE | — | Code-enforced. |

**Verdict:** primarily technical safety, operator-endorsed. **Not TBD.** No change needed.

## 5. Scalping / profit framing  *(the atom the operator flagged to scrutinize)*

| Location | Language | Primary | Mixed-with | Note |
| --- | --- | --- | --- | --- |
| `DOCTRINE.md:6` | "…the objective is still legitimate retail buying, **not scalping**." | OPERATOR_POLICY_CONFIRMED | — | **First-person operator doctrine.** The "not scalping" objective is the operator's, not assistant-injected. |
| `scanner/margin.py:3` | "Resale comps are context for MSRP-protection decisions, not a scalping target." | OPERATOR_POLICY_CONFIRMED | TECHNICAL_SAFETY_GATE | Encoded in the money-math module; matches DOCTRINE. |
| `config.example.yaml:53` | "Resale comps are context for MSRP-protection decisions, never a scalping target." | OPERATOR_POLICY_CONFIRMED | — | Operator config comment. |
| `docs/superpowers/specs/2026-06-18-hobby-resale-engine-design.md:21` | "**Kept (these are moat, not moralizing):** no auto-checkout… A human reviews and executes every buy… by principle, not just because a given site blocks automation." | OPERATOR_POLICY_CONFIRMED | TECHNICAL_SAFETY_GATE | Self-labels as *moat, not moralizing* — explicitly operator-endorsed engineering. |
| `docs/service-plan/04_DOCTRINE_AND_SAFETY.md:3,11,34,40,74,90` | "don't be a scalper"; "**anything that makes the tool look or behave like the scalper bots the community is fighting is a hard never**"; "ranking by profit" = never | **ASSISTANT_INSERTED_POLICY** | OPERATOR_POLICY_CONFIRMED (underlying rule) | **This is the elaborated moralizing layer.** The *rule* ("don't rank by resale profit") traces to DOCTRINE; the *community-facing moral framing* is assistant-authored. Candidate for attribution/trim (patch list §P1) — **not** deletion of the rule. |
| `docs/service-plan/07_DELIVERY_AND_KNOWLEDGE.md:166` | "any framing that implies flipping/resale profit… must NOT appear in public material" | ASSISTANT_INSERTED_POLICY | OPERATOR_POLICY_CONFIRMED | Public-comms rule; assistant-elaborated from operator's anti-scalp stance. |
| `README.md:224,287` | "scalper-price alerts" (marketplace caveat); "Flipper" lens computed via `scanner.margin`/`verdict` | OPERATOR_POLICY_CONFIRMED | — | Neutral/functional usage; the "Flipper" lens is a *named feature*, not a profit-ranking objective. |

**Verdict on the flagged atom:** the "not scalping" **objective is operator
policy, confirmed** (DOCTRINE.md:6, first person). It is **not** assistant-
injected. What *is* assistant-inserted is the **moralizing elaboration** in
`docs/service-plan/04` and `07` (community-framing, "hard never" rhetoric). Those
are faithful to operator intent but written by the assistant — flagged for
optional attribution/trim, not removal. **The Money Hypothesis Lab must not add
new moralizing of this kind** (operator instruction) — it inherits the terse
DOCTRINE.md framing only.

## 6. PPT / credit gates  (money-class)

| Location | Language | Primary | Note |
| --- | --- | --- | --- |
| `CLAUDE.md:17-22` | "PPT API bills on requested `limit`… `limit=1` is mandatory… get operator go-ahead before any live PPT run." | COST_OR_SECRET_GATE | Operator instruction; **hard money gate**. |
| `config.example.yaml:70,86` | "Free tier ~100 credits/day"; `daily_credit_cap: 90` | COST_OR_SECRET_GATE | Operator-set cap. |
| `scanner/comps/ppt_validator.py:4,38,52` | "refuses without --yes (operator go-ahead)… hard-stops"; "PPT credits are money-class" | COST_OR_SECRET_GATE | **Code-enforced**. |
| `docs/poke/buyable-pipeline-runbook.md` §11 | "Zero PPT credits… the discovery comp path is PPT-free by construction" | COST_OR_SECRET_GATE | Structural. |
| `tests/test_comps_engine.py:64` | asserts `creditsConsumed == 0` | COST_OR_SECRET_GATE | Test-enforced. |

**Verdict:** cost/secret gate, code- and test-enforced. **Never TBD, never
relaxed.** No change.

## 7. Scheduler / live-network gates

| Location | Language | Primary | Note |
| --- | --- | --- | --- |
| `docs/poke/buyable-pipeline-runbook.md` §8, §11 | "The build never registers tasks — you do, after review"; live run needs "Explicit operator go-ahead… not implied by a prior run" | RELEASE_GATE | Operator-gated. |
| `scripts/register_tasks.ps1:21-22` | "read-only stock queries only, no auto-checkout… no live PPT credit spend on this path"; dry-run-by-default | RELEASE_GATE | Mixed with TECHNICAL_SAFETY_GATE + COST_OR_SECRET_GATE. |
| `scanner/discovery/pipeline.py:475` | "run a single one-shot pass (the scheduler invokes this)" — one-shot, not a daemon | TECHNICAL_SAFETY_GATE | Architectural. |
| `docs/poke/live-smoke-approval-2026-07-04.md`, `docs/superpowers/plans/2026-07-04-post-6b…:40-46,191` | "No live network without explicit operator approval for that exact run." | RELEASE_GATE | Governs Track A. |

**Verdict:** release gates, operator-owned. **Not TBD** (the gate exists and is
clear); the *decision to run* is the operator's per-run call.

## 8. `comps.engine` cutover gate

| Location | Language | Primary | Note |
| --- | --- | --- | --- |
| `docs/poke/buyable-pipeline-runbook.md` §10 | "Do **NOT** flip `comps.engine` to `inhouse` yet"; flip only after TCGplayer resolved or eBay keyset lands + side-by-side review | RELEASE_GATE | Evidence-gated, reversible one-liner. |
| `config.example.yaml:103` | "`engine: legacy` # 'inhouse' = multi-source comp engine (Slice 6 flips default)" | RELEASE_GATE | Default is legacy. |
| `docs/superpowers/plans/2026-07-04-post-6b…:42` | "No `comps.engine` flip; it stays `legacy`." | RELEASE_GATE | Reaffirmed. |

**Verdict:** release gate grounded in a **concrete technical reason** (TCGplayer
STUB + eBay keyset pending → in-house would be a downgrade). **Not TBD, not a
policy opinion** — an engineering hold. No change.

---

## Findings — what is truly TBD vs technical/cost/release

- **Nothing currently in the repo's boundary language is genuinely
  `TBD_OPERATOR_POLICY`.** Every boundary resolves to operator policy, a
  technical safety gate, a cost/secret gate, or a release gate — most are
  *mixed*, which is why blind TBD-replacement was correctly forbidden.
- **The one assistant-inserted layer** is the *moralizing elaboration* of the
  anti-scalp stance in `docs/service-plan/04_DOCTRINE_AND_SAFETY.md` and
  `07_DELIVERY_AND_KNOWLEDGE.md`. The underlying rules are operator policy; only
  the community-facing rhetoric is assistant-authored. Low-priority, faithful,
  **not urgent** to change.
- **Forward-looking TBD (for Tracks B–E, not yet in the repo).** The business-
  policy parameters the Money Hypothesis Lab will need are **unspecified** and
  must be surfaced as `TBD_OPERATOR_POLICY`, never invented:
  - **max acceptable buy price** per candidate/trade-type
  - **expected hold time** per trade type
  - **exit venue assumption** per trade type (eBay vs local vs LGS)
  - whether **live-trade eligibility** requires a stricter margin/ROI floor than
    the paper `BUY` floor (`verdict.py`: net ≥ $15, ROI ≥ 20%, conf ≥ medium)
  - per-trade-type **confidence floor** overrides
- **Defined technical defaults — cite, do not TBD.** These have concrete,
  config-overridable values and must be *cited* in Track E, not stamped TBD:
  - `margin.FeeModel`: eBay FVF **13.25%** + **$0.40** fixed; local haircut **15%**
  - `margin.cost_basis`: landed cost = price × (1 + tax_rate)
  - `verdict.VerdictThresholds`: skip/buy net **$5/$15**, ROI **10%/20%**,
    `min_buy_confidence: medium`
  - `poke.min_discount_pct`, `discovery.min_alert_confidence`
  - *(Open question worth one operator confirm: are these specific default
    values operator-chosen or assistant-chosen reasonable defaults? They are
    config-exposed either way; flagged, not blocking.)*

## Proposed patch list  (NONE APPLIED — for operator review)

> Conservative by design. Each item preserves the underlying boundary; only
> wording/attribution changes are proposed. Blindly replacing boundary language
> with TBD is explicitly out of scope.

- **P1 (low, optional).** `docs/service-plan/04_DOCTRINE_AND_SAFETY.md:40,90` and
  `07_DELIVERY_AND_KNOWLEDGE.md:166` — the "scalper bots the community is
  fighting is a hard never" moralizing. *Proposed:* add a one-line attribution
  ("elaboration of DOCTRINE.md, assistant-authored") **or** trim the rhetoric to
  the functional rule ("don't rank or optimize for resale profit"). **Do not**
  remove the rule. Not urgent.
- **P2 (informational).** No code, config, or runbook boundary needs editing.
  The technical/cost/release gates are correct as written.
- **P3 (forward-looking).** When Tracks B–E introduce business-policy fields,
  emit `TBD_OPERATOR_POLICY` for the five unspecified parameters above; cite the
  defined technical defaults verbatim. This is a *construction rule for new
  work*, not an edit to existing files.

## Test hook

The audit's completeness is checkable: a test can assert that each of the 8
boundary categories has ≥1 catalogued occurrence with a known file:line (the
canonical rows above), so drift (a boundary term deleted or a doc renamed) fails
loudly. See the Money Hypothesis Lab spec for where this test lands.
