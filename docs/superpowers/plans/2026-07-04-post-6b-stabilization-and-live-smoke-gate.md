# Post-6B Stabilization and Live-Smoke Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate the completed Slice 6B work, prove the discovery pipeline in a controlled live smoke only with operator approval, and prevent the next feature slice from expanding before the live evidence says what is actually useful.

**Architecture:** This is a gate plan, not a new feature build. First preserve and verify the dirty 6B tree, then commit it in logical local chunks, then prepare and run an isolated Slickdeals live-smoke only after explicit approval. The smoke result decides the next scoped plan: selector repair, eBay keyset activation, scheduler rollout, or ad-hoc Ring-2/Ring-3 comps.

**Tech Stack:** Python 3, pytest, existing `scanner/discovery` pipeline, existing `docs/poke/buyable-pipeline-runbook.md`, PowerShell for the operator-gated smoke command.

---

## Direction Call

The program is headed in the right direction: it now has the right spine for a useful MSRP/source-truth operator tool: discover candidates, verify buyability from the actual page, keep comps separate from stock truth, enforce no-alert-without-evidence, and degrade honestly.

The next work must not be "more sources" or "cutover." The next work is a release gate:

1. Preserve and commit the completed 6B resolver work locally.
2. Run a single operator-approved live Slickdeals smoke in an isolated output/state directory.
3. Let the manifest decide the next slice.

Do not start ad-hoc non-catalog comps, Playwright sources, scheduler registration, or `comps.engine` cutover until this gate is complete.

## File Structure

- `scanner/discovery/resolve.py`: new Slice 6B resolver. Responsibility: resolve Slickdeals thread URLs into safe merchant URLs or honest resolver failures.
- `scanner/discovery/verify.py`: changed Slice 6B verifier. Responsibility: compose Slickdeals resolution into the existing `verify_page` path while keeping the Slickdeals price as expectation only.
- `scanner/discovery/pipeline.py`: changed Slice 6B pipeline. Responsibility: route `source == "slickdeals"` through the resolver verifier and preserve hermetic injected HTTP behavior.
- `tests/test_disc_resolve.py`: new resolver unit tests.
- `tests/test_poke_verify.py`: added Slickdeals verify integration tests.
- `tests/test_poke_pipeline.py`: added default-verifier and end-to-end Slickdeals pipeline tests.
- `tests/fixtures/discovery/slickdeals_thread_*.html`: resolver fixtures.
- `docs/poke/buyable-pipeline-runbook.md`: updated operator runbook and live-smoke checklist.
- `data/poke/*.json`, `data/poke/*.manifest.json`, `data/poke/price_history.jsonl`, `sw-military-le.md`: external/unrelated artifacts. Preserve untouched.

## Hard Boundaries

- No remote push.
- No live network without explicit operator approval for that exact run.
- No PPT calls or credit spend.
- No `comps.engine` flip; it stays `legacy`.
- No scheduler registration.
- No dependency install.
- No Playwright.
- No bot-wall evasion, cart automation, login, or proxy polling.
- No cleanup of unrelated/untracked artifacts.

### Task 1: Reconfirm and Preserve the Dirty 6B Tree

**Files:**
- Read: `git status --short`
- Read: `git diff --stat`
- Preserve: external `data/poke/*` artifacts and `sw-military-le.md`

- [ ] **Step 1: Check working tree status**

Run:

```powershell
git status --short
```

Expected: tracked edits in `docs/poke/buyable-pipeline-runbook.md`, `scanner/discovery/pipeline.py`, `scanner/discovery/verify.py`, `tests/test_poke_pipeline.py`, `tests/test_poke_verify.py`; untracked Slice 6B resolver files; unrelated data artifacts remain untracked.

- [ ] **Step 2: Check diff size**

Run:

```powershell
git diff --stat
```

Expected: the tracked diff is limited to the Slice 6B surfaces and runbook. If unrelated tracked files appear, stop and report before staging.

- [ ] **Step 3: Confirm external artifacts are untouched**

Run:

```powershell
git status --short data/poke sw-military-le.md
```

Expected: untracked external artifacts only. Do not stage them in this plan.

### Task 2: Verification Before Local Commit

**Files:**
- Read/test: full repo

- [ ] **Step 1: Run the full suite with a known-good temp path**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp C:\Users\Weave\AppData\Local\Temp\pokemon_repo_check_0704
```

Expected:

```text
575 passed
```

If this fails with `PermissionError` in pytest temp setup, treat it as environment friction and rerun with a fresh `--basetemp` path under `C:\Users\Weave\AppData\Local\Temp\pokemon_repo_check_<date>`. If it fails on an assertion, stop and fix before committing.

- [ ] **Step 2: Run Slice 6B targeted tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_disc_resolve.py tests/test_poke_verify.py tests/test_poke_pipeline.py -q --basetemp C:\Users\Weave\AppData\Local\Temp\pokemon_6b_targeted_0704
```

Expected: all targeted tests pass. If only the full suite was already run immediately before this task, this step may be used as a quick post-review confirmation after any fix.

### Task 3: Commit Slice 6B in Logical Local Chunks

**Files:**
- Stage/commit only Slice 6B files.
- Do not stage `data/poke/*` or `sw-military-le.md`.

- [ ] **Step 1: Commit resolver core and verify/pipeline wiring**

Run:

```powershell
git add scanner/discovery/resolve.py scanner/discovery/verify.py scanner/discovery/pipeline.py
git commit -m "feat(disc): resolve Slickdeals threads to verified merchant pages"
```

Expected: one local commit. No remote push.

- [ ] **Step 2: Commit resolver fixtures and tests**

Run:

```powershell
git add tests/test_disc_resolve.py tests/test_poke_verify.py tests/test_poke_pipeline.py tests/fixtures/discovery/slickdeals_thread_direct.html tests/fixtures/discovery/slickdeals_thread_nocta.html tests/fixtures/discovery/slickdeals_thread_redirect.html tests/fixtures/discovery/slickdeals_thread_u2.html
git commit -m "test(disc): cover Slickdeals resolver and verified pipeline path"
```

Expected: one local commit. No remote push.

- [ ] **Step 3: Commit runbook updates**

Run:

```powershell
git add docs/poke/buyable-pipeline-runbook.md
git commit -m "docs(poke): document Slickdeals resolver live-smoke gate"
```

Expected: one local commit. No remote push.

- [ ] **Step 4: Recheck status after commits**

Run:

```powershell
git status --short
```

Expected: only unrelated untracked artifacts remain. If any Slice 6B tracked file remains modified, inspect before proceeding.

### Task 4: Prepare the Live-Smoke Approval Packet

**Files:**
- Create: `docs/poke/live-smoke-approval-2026-07-04.md`

- [ ] **Step 1: Write the approval packet**

Create `docs/poke/live-smoke-approval-2026-07-04.md` with this content:

```markdown
# Live Slickdeals Smoke Approval Packet - 2026-07-04

## Purpose

Run one isolated live Slickdeals discovery pass to validate that the Slice 6B resolver can resolve current Slickdeals thread markup to merchant pages and that the pipeline classifies every candidate honestly.

## What Will Touch Network

- `slickdeals.net` search/thread pages through the discovery pipeline.
- Resolved merchant pages from Slickdeals candidates.

## What Will Not Happen

- No PPT calls.
- No credit spend.
- No cart, checkout, login, proxy polling, or bot-wall evasion.
- No scheduler registration.
- No `comps.engine` cutover.
- No remote push.

## Isolation

- State database: `%TEMP%\poke-smoke\state.db`
- Output root: `%TEMP%\poke-smoke`
- Repo `data/poke/` remains untouched by this smoke.

## Command

```powershell
$env:POKEMON_SCANNER_STATE_DB = "$env:TEMP\poke-smoke\state.db"
.\.venv\Scripts\python.exe -m scanner.discovery.pipeline `
  --once --sources slickdeals --out "$env:TEMP\poke-smoke"
Remove-Item Env:\POKEMON_SCANNER_STATE_DB
```

## Success Criteria

- Exit code `0`, unless golden intentionally halts dashboard writing while preserving JSON evidence.
- Manifest count reconciliation holds.
- Every candidate has exactly one `outcomes[]` terminal bucket and reason.
- At least one Slickdeals candidate shows a resolver method like `slickdeals_resolve:u2_param+page_fetch`, `slickdeals_resolve:direct_href+page_fetch`, or `slickdeals_resolve:redirect_chain+page_fetch`, or every candidate honestly explains why it could not resolve.
- No silent drops.
- No PPT credits used.

## Decision After Run

- If resolver selectors work and merchant pages parse: keep 6B, consider scheduler dry-run.
- If resolver selectors drift: capture one live thread fixture and make a narrow selector-repair plan.
- If merchant pages are mostly JS shells/blocked/price_mismatch: keep the lane as honest low-yield and prioritize eBay keyset or catalog coverage instead of loosening parsers.
- If Ring-2/Ring-3 candidates verify but land in `no_comp`: next feature slice is ad-hoc non-catalog comps, not a parser change.
```

- [ ] **Step 2: Review the packet for forbidden actions**

Run:

```powershell
Select-String -Path docs/poke/live-smoke-approval-2026-07-04.md -Pattern "PPT|credit|scheduler|comps.engine|push|cart|checkout|login"
```

Expected: every match appears in the "will not happen" or gate language, not as an enabled action.

- [ ] **Step 3: Commit the approval packet**

Run:

```powershell
git add docs/poke/live-smoke-approval-2026-07-04.md
git commit -m "docs(poke): add Slickdeals live-smoke approval packet"
```

Expected: one local commit. No remote push.

### Task 5: Operator-Gated Live Smoke

**Files:**
- Writes only under `%TEMP%\poke-smoke` when using the command below.

- [ ] **Step 1: Ask for explicit operator approval**

Ask:

```text
Do you approve one live Slickdeals smoke using the command in docs/poke/live-smoke-approval-2026-07-04.md? It will touch Slickdeals and resolved merchant pages, write only under %TEMP%\poke-smoke, spend zero PPT credits, and will not register scheduler tasks.
```

Expected: proceed only on explicit approval. A prior approval for a different run does not count.

- [ ] **Step 2: Run the isolated smoke after approval**

Run:

```powershell
$env:POKEMON_SCANNER_STATE_DB = "$env:TEMP\poke-smoke\state.db"
.\.venv\Scripts\python.exe -m scanner.discovery.pipeline `
  --once --sources slickdeals --out "$env:TEMP\poke-smoke"
Remove-Item Env:\POKEMON_SCANNER_STATE_DB
```

Expected: command completes with a printed count summary. If it exits `1`, inspect the manifest/board JSON because the dashboard may be intentionally withheld by golden while JSON evidence remains.

- [ ] **Step 3: Inspect manifest outcomes**

Run:

```powershell
Get-ChildItem "$env:TEMP\poke-smoke\data\poke" -Filter "*-discovery.manifest.json" |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1 |
  ForEach-Object { Get-Content -LiteralPath $_.FullName -Raw }
```

Expected: `candidates` equals the sum of terminal counts; every `outcomes[]` item has `source`, `listing_id`, `terminal`, and `reason`.

- [ ] **Step 4: Classify the smoke result**

Use the manifest to choose exactly one branch:

```text
BRANCH A: resolver works and at least one candidate reached page_fetch.
BRANCH B: resolver selectors drifted; candidates are unverifiable with Slickdeals resolve drift reasons.
BRANCH C: resolver works but merchant pages are parser_suspect/blocked/price_mismatch.
BRANCH D: candidates verify but land in no_comp because they are non-catalog Ring-2/Ring-3.
BRANCH E: an invariant failed; stop and fix before any further work.
```

Expected: one branch selected from evidence, not vibes.

### Task 6: Next-Scope Decision

**Files:**
- Create one future plan only after Task 5 evidence exists.

- [ ] **Step 1: If Branch A, plan scheduler dry-run rollout**

Create a small plan for `scripts/register_tasks.ps1 -Install -DryRunTask` only. Do not register live schedule yet. Acceptance: dry-run scheduled task fires, writes no board, makes zero network, and can be unregistered.

- [ ] **Step 2: If Branch B, plan selector repair**

Create a narrow selector-repair plan touching only:

```text
scanner/discovery/resolve.py
tests/fixtures/discovery/<new-live-thread-fixture>.html
tests/test_disc_resolve.py
tests/test_poke_verify.py
```

Acceptance: the live fixture resolves to the primary CTA, not a sidebar/footer anchor; all resolver tests and full suite pass.

- [ ] **Step 3: If Branch C, stop feature expansion and prioritize source unlocks**

Do not loosen `verify_page`. Recommend one of:

```text
1. eBay keyset activation, because it is API-backed and same-listing.
2. targeted catalog retailer ID coverage, because catalog lanes can verify through sanctioned retailer adapters.
3. Playwright decision as a separate dependency/spec discussion, not a quiet install.
```

- [ ] **Step 4: If Branch D, start a new ad-hoc comp design/spec**

Only after live evidence shows verified non-catalog candidates landing in `no_comp`, write a new design for ad-hoc Ring-2/Ring-3 comps. Required scope:

```text
Inputs: CandidateDeal title, matched_set, asset_class, variant, condition.
Outputs: attributed comp row or no_comp.
Allowed sources: PriceCharting and eBay Browse only after keyset; no PPT hot path.
Forbidden: fabricated comps, title-only confident matches, hidden low confidence, comp-engine cutover.
Alert policy: non-catalog alerting requires verified buyability plus attributed comp plus confidence gate.
```

- [ ] **Step 5: If Branch E, fix the invariant before any new plan**

Invariant failures include:

```text
manifest counts do not reconcile
alert fires without assert_alertable
Buyable-now contains missing evidence
PPT is touched
repo data/poke is modified during isolated smoke
unsafe URL becomes clickable
```

Expected: no new feature work until the invariant is fixed and the full suite passes.

## Self-Review

- Spec coverage: this plan covers the completed Slice 6B dirty tree, live-smoke approval, explicit no-credit/no-scheduler/no-cutover gates, and the next-scope decision tree.
- Placeholder scan: no TBD/TODO/fill-in language remains.
- Type consistency: uses existing names `StockVerification`, `verify.assert_alertable`, `CandidateDeal`, `comps.engine`, and terminal bucket names from `scanner/discovery/pipeline.py`.
- Scope check: ad-hoc Ring-2/Ring-3 comps, Playwright sources, eBay activation, and scheduler rollout are separate future plans. They are not included in this stabilization gate.
