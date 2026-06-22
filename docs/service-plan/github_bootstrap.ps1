<#
  GitHub bootstrap — TCG MSRP scanner
  ---------------------------------------------------------------------------
  Creates labels, 6 milestones, and the first 20 issues from docs/service-plan/07.
  Dry-run by DEFAULT (prints every gh command). Pass -Apply to actually run them.

  Requires the GitHub CLI, authenticated once:   gh auth login
  Usage:
    powershell -ExecutionPolicy Bypass -File docs\service-plan\github_bootstrap.ps1
    powershell -ExecutionPolicy Bypass -File docs\service-plan\github_bootstrap.ps1 -Apply -Repo weaverjsdw-ux/Pokemon
#>
[CmdletBinding()]
param([string]$Repo = "weaverjsdw-ux/Pokemon", [switch]$Apply)

function Run([string]$cmd) {
  if ($Apply) { Write-Host ">> $cmd"; Invoke-Expression $cmd }
  else        { Write-Host "(dry-run) $cmd" }
}
Write-Host "Repo: $Repo  (dry-run = $(-not $Apply))`n"

# ---- Labels -------------------------------------------------------------
$labels = @(
  @{n="type:bug";c="d73a4a"}, @{n="type:feature";c="a2eeef"}, @{n="type:chore";c="cfd3d7"}, @{n="type:docs";c="0075ca"},
  @{n="area:scanner";c="5319e7"}, @{n="area:web";c="1d76db"}, @{n="area:retailer";c="b60205"}, @{n="area:state";c="0e8a16"},
  @{n="area:notify";c="fbca04"}, @{n="area:catalog";c="c2e0c6"}, @{n="area:sources";c="d4c5f9"},
  @{n="prio:P0";c="b60205"}, @{n="prio:P1";c="d93f0b"}, @{n="prio:P2";c="fbca04"}, @{n="prio:P3";c="c5def5"},
  @{n="effort:S";c="ededed"}, @{n="effort:M";c="ededed"}, @{n="effort:L";c="ededed"},
  @{n="doctrine-review";c="5319e7"}, @{n="blocked";c="000000"}, @{n="good-first-issue";c="7057ff"}
)
foreach ($l in $labels) { Run "gh label create `"$($l.n)`" --color $($l.c) --force --repo $Repo" }

# ---- Milestones (idempotent; ignore 'already_exists') -------------------
$milestones = @("M0 — Clean Baseline","M1 — Reliability","M2 — Catalog & Sources","M3 — Operator Dashboard","M4 — Alert Quality","M5 — Packaging & Packs")
foreach ($m in $milestones) { Run "gh api repos/$Repo/milestones -f title=`"$m`" 2>`$null" }

# ---- Issues -------------------------------------------------------------
# Body convention: goal + acceptance, pointing at the spec docs.
$D = "See docs/service-plan/"
$issues = @(
 @{t="Phase 0: add *.bak + scratch to .gitignore, remove scratch files"; m="M0 — Clean Baseline"; l="type:chore,area:scanner,effort:S,prio:P0"; b="Add *.bak + scratch patterns to .gitignore; delete sprint*.txt/iddoctor_offline.txt/test_baseline.txt and large .tmp_web_*.err.log. Accept: git status clean of scratch; no secrets/.db/.bak staged. $D 06 Phase 0 + phase0_cleanup.ps1."}
 @{t="Phase 0: commit untracked modules + docs as reviewed baseline"; m="M0 — Clean Baseline"; l="type:chore,effort:S,prio:P0"; b="Commit confidence/provenance/resale/verify_ids/workqueue + test_confidence + docs. Accept: 170 tests pass on the commit; CI green."}
 @{t="Phase 0: smoke-verify --check-config, --safe-demo, web boot"; m="M0 — Clean Baseline"; l="type:chore,effort:S,prio:P1"; b="Document a clean run of all three. Accept: each runs without error; --safe-demo renders with zero network."}
 @{t="notify: raise_for_status + retry + local alert-log"; m="M1 — Reliability"; l="type:bug,area:notify,effort:S,prio:P0"; b="A dead webhook currently fails silently. Add raise_for_status + one retry + an alert-log fallback; make ntfy base URL configurable. Accept: 4xx webhook is logged+surfaced (test). $D 06 Phase 1."}
 @{t="main: crash-safe outer loop + exponential backoff + heartbeat"; m="M1 — Reliability"; l="type:feature,area:scanner,effort:S,prio:P0"; b="Wrap the while-loop in try/except + capped backoff; write a heartbeat each cycle; graceful shutdown; periodic store re-discovery. Accept: loop survives a thrown exception (test)."}
 @{t="state: heartbeat row + WAL + single-txn writes"; m="M1 — Reliability"; l="area:state,effort:M,prio:P1"; b="Enable WAL; add heartbeat/runner_meta; wrap should_alert+record_observation in one txn. Accept: existing state tests green; heartbeat set/get."}
 @{t="web: truthful Liveness indicator (live/stale/down)"; m="M1 — Reliability"; l="area:web,effort:M,prio:P1"; b="Derive live/stale/down from the heartbeat; show last/next scan. Accept: indicator goes stale within one interval of a stalled loop (test)."}
 @{t="health: persist on every write + config thresholds"; m="M1 — Reliability"; l="area:scanner,effort:M,prio:P2"; b="Persist health each record_*; make DOWN/STALE thresholds config-driven. Accept: health survives restart (test)."}
 @{t="resale: persist quote cache to disk"; m="M1 — Reliability"; l="area:scanner,effort:S,prio:P2"; b="Persist + reload the resale cache so a restart doesn't blank prices. Accept: prices reappear after a simulated restart (test)."}
 @{t="source_mode setting + enforcement + acknowledgment gate"; m="M2 — Catalog & Sources"; l="type:feature,area:sources,doctrine-review,effort:M,prio:P1"; b="Add source_mode = all_sources (default) | durable_only. In durable_only only Best Buy+eBay+geo run; others manual. Accept: durable_only makes zero internal-endpoint calls (test). $D 03 fork."}
 @{t="catalog: add Mega Evolution block + Pitch Black"; m="M2 — Catalog & Sources"; l="area:catalog,effort:M,prio:P1"; b="Add Ascended Heroes/Perfect Order/Chaos Rising/Pitch Black (ETB+Bundle+Box; PC ETBs). Verify Best Buy SKUs via API; record provenance. $D 02/F."}
 @{t="catalog: add 30th Celebration + First Partner S1-S3 + Destined Rivals tins"; m="M2 — Catalog & Sources"; l="area:catalog,effort:M,prio:P2"; b="Add the Sep 16 30th Celebration line, First Partner collections, DR Team Rocket tins. Label unconfirmed MSRPs [needs validation]."}
 @{t="release-watch model (data/releases.yaml + loader)"; m="M2 — Catalog & Sources"; l="type:feature,area:catalog,effort:M,prio:P2"; b="Structured upcoming-release records (set, date, products, IDs-needed). Accept: parse/validate tests; feeds the inbox."}
 @{t="ID Doctor truthfulness: relabel 'URL-resolves only'"; m="M2 — Catalog & Sources"; l="type:bug,area:retailer,effort:S,prio:P2"; b="Walmart/Costco/GameStop verification only confirms a 200, not identity — relabel accordingly; add real checks where an official API exists. Accept: statuses accurate (test)."}
 @{t="/api/verify-ids endpoint + ID Doctor UI"; m="M3 — Operator Dashboard"; l="type:feature,area:web,effort:M,prio:P1"; b="Run verification from the UI; show verifiedAt per product. Accept: endpoint updates provenance (test). $D 05 ID Doctor."}
 @{t="release-watch inbox UI"; m="M3 — Operator Dashboard"; l="type:feature,area:web,effort:M,prio:P2"; b="Surface upcoming releases + IDs-needed with a countdown. Accept: release <14d w/ missing IDs surfaces at top."}
 @{t="workqueue: severity-first sort + first test_workqueue.py"; m="M3 — Operator Dashboard"; l="area:scanner,effort:S,prio:P2"; b="Make severity a first-class sort key; add the missing test file. Accept: deterministic ordering (test)."}
 @{t="source cards: durability badge + reason codes"; m="M3 — Operator Dashboard"; l="area:web,effort:S,prio:P3"; b="Each source card shows durability (official/internal/alert-only) + reason. $D 05."}
 @{t="alert ranking by MSRP-protection tier + dedupe"; m="M4 — Alert Quality"; l="type:feature,area:notify,effort:M,prio:P2"; b="Rank alerts by protection tier ([02/E]); improve dedupe. Accept: Tier-1 ETB out-ranks Tier-3 pack (test)."}
 @{t="quiet-hours / urgency routing (urgent->ntfy, digest->Discord)"; m="M4 — Alert Quality"; l="type:feature,area:notify,effort:M,prio:P3"; b="Suppress non-urgent in quiet hours; keep cadence >=60s. Accept: non-urgent held in quiet hours (test)."}
)
foreach ($i in $issues) {
  $body = ($i.b -replace '"','\"')
  Run "gh issue create --repo $Repo --title `"$($i.t)`" --body `"$body`" --label `"$($i.l)`" --milestone `"$($i.m)`""
}

Write-Host "`nDone. (dry-run prints commands; re-run with -Apply once 'gh auth status' is OK.)"
