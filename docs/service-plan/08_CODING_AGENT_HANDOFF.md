# 08 — Coding-Agent Handoff Prompts

*Two self-contained prompts. Phase 0 is safe to run immediately and is gated to NOT start feature work. Phase 1 waits on the Phase-0 baseline commit and operator decisions #1–#4 in [00].*

---

## PROMPT — Phase 0 (Repo Truth & Clean Baseline)

```
You are a careful engineer working in the local repo at:
C:\Users\Weave\OneDrive\Desktop\Pokemon-main

DOCTRINE (read DOCTRINE.md and docs/service-plan/04_DOCTRINE_AND_SAFETY.md first; obey both):
- Hobby MSRP-protection tool, not scalping. No auto-checkout, proxies, distributed polling,
  login-wall scraping, or queue/invite circumvention.
- NEVER read, print, commit, or expose: config.yaml, any *.db / *.db-journal / *.bak,
  .tmp_costco_* cookie files, API keys, webhook URLs, addresses, or route coordinates.

PHASE 0 GOAL: produce a known-good, committed baseline. NO feature work, NO logic changes,
NO adapter changes, NO doctrine changes. Housekeeping + verification only.

The worktree is currently DIRTY with intended uncommitted work. Preserve it. Do this:

1. Run `git status`. Confirm the untracked NEW modules exist and are intended:
   scanner/confidence.py, scanner/provenance.py, scanner/resale.py, scanner/verify_ids.py,
   scanner/workqueue.py, tests/test_confidence.py, plus DOCTRINE.md, ADVISOR_ROLE.md,
   ROADMAP.md, data/id_provenance.json.
2. Edit .gitignore to add:  *.bak
   (and confirm config.yaml, *.db, *.db-journal, .tmp_costco_*, .tmp_web_*.log,
   data/*.cache.json are already ignored — they are.)
3. Delete dev scratch files ONLY (do not touch source): sprint1.txt, sprint1_full.txt,
   sprint2.txt, sprint3a.txt, iddoctor_offline.txt, test_baseline.txt, and the large
   .tmp_web_*.err.log files. Do NOT delete data/*.db, data/*.bak, or anything in scanner/ or tests/.
4. Create a venv and install deps:
   python -m venv .venv ; .\.venv\Scripts\Activate.ps1 ; pip install -r requirements-dev.txt
5. VERIFY (must all pass; paste output):
   - pytest            -> expect 170 passed
   - python -m scanner --check-config   -> prints coverage; no secrets leaked
   - python -m scanner --safe-demo      -> renders synthetic board, zero network
   - python -m scanner.web --no-autostart  -> dashboard boots on 127.0.0.1:8765 (then stop it)
6. Stage ONLY intended files (the new modules, the docs, the .gitignore change). Run
   `git status` again and confirm NO *.db, *.bak, config.yaml, cookie, or scratch file is staged.
7. Commit with message: "Phase 0: clean baseline (new modules + docs + ignore *.bak)".
   Do NOT push unless asked.

HARD STOP after the commit. Do not start Phase 1. Report:
- the final `git status` (clean),
- pytest result,
- confirmation the three smoke checks passed,
- anything surprising.

If any verification fails, STOP and report — do not "fix" by changing logic in Phase 0.
```

---

## PROMPT — Phase 1 (Service-Grade Local Reliability)

```
You are a careful engineer in the local repo:
C:\Users\Weave\OneDrive\Desktop\Pokemon-main
Prereq: the Phase 0 baseline commit exists and `pytest` shows 170 passing. If not, STOP.

Read first: DOCTRINE.md, docs/service-plan/04_DOCTRINE_AND_SAFETY.md,
docs/service-plan/06_ENGINEERING_ROADMAP.md (Phase 1).
Same secret rules as Phase 0 — never read/print/commit secrets, *.db, *.bak, cookies, addresses.

PHASE 1 GOAL: "runs unattended and never lies about its state." No silent unknowns.
Work in small PR-sized commits, each keeping the full suite green. Use test-driven changes:
write/extend a test, then implement. Do NOT add new retailers/sources, catalog entries, ML,
or any new personal-use-source polling in this phase.

Implement, each as its own commit with tests:

A) scanner/notify.py — reliable delivery
   - In _discord() and _ntfy(): call resp.raise_for_status(); on failure retry once with a short
     backoff; on final failure, append the alert to a local alert log (a new state table OR a
     gitignored file) so it is recoverable, and surface it (don't silently drop).
   - Make the ntfy base URL configurable (default https://ntfy.sh).
   - Tests: a 4xx webhook is logged+surfaced (not dropped); retry path exercised with injected fakes.

B) scanner/main.py — crash-safe loop + heartbeat
   - Wrap the outer `while True` in try/except: on exception, log, back off exponentially (cap it,
     and keep it visible — do not hide a sustained outage), continue.
   - Each cycle, write a heartbeat (last-loop timestamp) to state.
   - Handle SIGTERM / KeyboardInterrupt for graceful shutdown.
   - Re-run store discovery every N cycles (config, default e.g. 50) instead of startup-only.
   - Tests: loop survives a thrown exception and backs off; heartbeat advances each cycle.

C) scanner/state.py — durability
   - Enable PRAGMA journal_mode=WAL and synchronous=NORMAL in the connection.
   - Add a heartbeat/runner_meta row API (set/get last-loop ts + runner status).
   - Wrap the should_alert + record_observation pair in a single transaction.
   - Tests: existing state tests stay green; heartbeat set/get; WAL doesn't break concurrent-ish access.

D) scanner/health.py — persistence + config
   - Persist health snapshot on every record_* (not only in the scan loop).
   - Make DOWN_AFTER_CONSECUTIVE_FAILURES and STALE_AFTER_SECONDS config-driven (defaults unchanged).
   - Tests: health survives a simulated restart; thresholds configurable.

E) scanner/resale.py — cache survives restart
   - Persist the quote cache to disk (gitignored) and reload on startup; keep the 4h refresh.
   - Tests: a simulated restart restores prices instead of showing all "pending".

F) scanner/web.py + web_assets/app.js — truthful Liveness
   - Add a Liveness indicator from the heartbeat: live (recent) / stale (older than ~1 interval) /
     down (older than N intervals or process gone). Show last-loop + next-expected.
   - Tests: /api/status exposes liveness; stale/down computed correctly.

ACCEPTANCE (paste evidence):
- All new tests green; full suite still green on your machine.
- Manual "pull the plug" run: stop the network mid-loop -> process stays up, backs off, dashboard
  shows degraded/stale truthfully; restore -> recovers. Restart the process -> prices + health
  reappear from disk; a revoked/blank webhook is logged + surfaced, never silently dropped.
- No secrets, *.db, or *.bak staged in any commit.

Do NOT proceed to Phase 2 (catalog/source-policy) without operator sign-off on decisions #1–#4 in
docs/service-plan/00_EXECUTIVE_BRIEF.md. Report a summary of commits + the acceptance evidence.
```

---

## Notes for whoever runs these

- Both prompts assume **Windows/PowerShell** (matches your environment + the scheduler). On macOS/Linux, swap the venv activation line.
- Phase 1 is deliberately **source-free and catalog-free** — it only hardens what exists, so it can't drift into new-source territory or stale-catalog churn.
- The **source-mode** work (the doctrine-in-code switch) is intentionally **Phase 2**, gated on operator decision #1, because it changes scanning behavior and deserves an explicit sign-off rather than being bundled into reliability fixes.
- If you want me to actually open the [07] issues, scaffold the Notion workspace, or generate the Phase-0 branch, that's operator decision #5 in [00] — say the word.
