# Buyable-Deal Pipeline — Operator Runbook

**Scope:** the discovery pipeline shipped by Slices 1–5 and hardened in Slice 6A
(`scanner/discovery/pipeline.py`). This is the **discovery lane**: discover →
verify purchasability → comp → verdict → dashboard + alert. It is separate from
the **restock lane** (`python -m scanner`, route-corridor store polling) which
has its own runbook (`docs/poke/live-sealed-board.md`) and its own scheduler.

**Design spec:** `docs/superpowers/specs/2026-07-02-buyable-deal-pipeline-design.md`.

**Golden rule this pipeline enforces:** *no alert without fresh, same-run,
evidenced purchasability.* Everything below is in service of that, and of never
presenting a number the system cannot source.

---

## 0. Current gate state (read before a live run)

As of 2026-07-03 the pipeline is fully built and green (520 tests), but two
operator unlocks are still pending and one cutover is deliberately **not** done:

| Item | State | Effect until done |
| --- | --- | --- |
| eBay developer keyset | **PENDING** (`docs/poke/ebay-keyset-setup.md`) | `ebay_browse` adapter and the eBay comp source report `NEEDS_API_KEY` and yield nothing. Do **not** treat eBay lanes as active. |
| 6 unseeded `ppt_id`s | **PENDING** (~36 PPT credits, after daily reset) | Those 6 catalog items have no TCGplayer id; comp coverage is thinner for them. Not required for the discovery lane. |
| `comps.engine` cutover to `inhouse` | **NOT DONE — do not do it** (see §10) | Legacy comp path stays active. This is correct. |
| Live network smoke | **operator-gated** (see §11) | Tests are network-mocked; a live run happens only with explicit go-ahead. |

A prior one-off `--sources slickdeals` live GET was run in a Slice-5 session
(3 real candidates, all honestly `unverifiable`, zero credits). From here
forward, **any** live network run requires explicit operator go-ahead (§11).

---

## 1. Run once (live)

One-shot pass (this is what the scheduler invokes; it is **not** a daemon):

```
.venv/Scripts/python.exe -m scanner.discovery.pipeline --once
```

Optionally restrict to specific adapter slugs (default is `discovery.sources`
from config: `target_search, slickdeals, ebay_browse`):

```
.venv/Scripts/python.exe -m scanner.discovery.pipeline --once --sources slickdeals
```

`--out <ROOT>` redirects all writes under a different root (default = repo
root) — useful to run against a throwaway directory without touching
`data/poke/`.

A live `--once` performs read-only stock-query fetches only. **It never adds to
a cart, logs in, or evades a bot wall**, and it spends **zero PPT credits** (the
comp path is structurally PPT-free). It only alerts on a candidate that its own
run verified as buyable with evidence.

Exit codes: `0` success · `1` a golden check failed (dashboard withheld, JSON
evidence kept) · `2` a config error (e.g. an unknown source slug).

---

## 2. Dry run (validate, zero network, no writes, no alerts)

```
.venv/Scripts/python.exe -m scanner.discovery.pipeline --dry-run
```

A dry run:
- makes **zero** network calls (asserted in tests down to `requests.get/post`
  and `retailers.http.get`),
- writes **no** board, manifest, or dashboard,
- sends **no** alerts,
- persists **nothing** to `data/state.db` (no `seen_listings`, no
  `deal_alerts`, no `last_run`).

It prints the per-source states and the candidate/bucket summary so you can
confirm the wiring and config before a live pass. This is the safe way to prove
the schedule/plumbing works. Every configured source still reports its honest
state — under `--dry-run` the network is stubbed before the auth check, so
`target_search` → `NOT_IMPLEMENTED` and both `slickdeals` and `ebay_browse` →
`DEGRADED "network disabled"` (the `NEEDS_API_KEY` state only surfaces on a
**live** run of a keyless `ebay_browse`).

---

## 3. Inspect the output

A live `--once` writes three files (dated `YYYY-MM-DD-discovery`):

| File | What it is |
| --- | --- |
| `data/poke/<date>-discovery.json` | **Board**: the deal rows + per-source states + counts. |
| `data/poke/<date>-discovery.manifest.json` | **Manifest**: candidate total, counts, per-source reports, and one per-candidate outcome each. |
| `dashboards/<date>-discovery.html` | **Dashboard**: self-contained HTML; open in a browser. |
| `data/poke/price_history.jsonl` | Append-only ledger: one `listing` observation per discovered candidate (and `market_comp` rows from the comp engine). |

Read the manifest first — it is the source of truth for "what happened this
run" and it **reconciles** by construction:

```
candidates == alerted + suppressed_dupe + out_of_stock + price_mismatch
            + unverifiable + no_comp + below_min_discount + below_confidence
```

Every candidate also appears once in `manifest["outcomes"]` as
`{source, listing_id, terminal, reason}` — no candidate is ever silently
dropped. The console line at the end of a run prints the same counts.

**Dashboard — the "Buyable now" section** is the top section and contains
**only** rows with verified positive stock (`in_stock`/`limited`), non-empty
evidence, and a buy link. If a row cannot prove buyability it stays in the
reference sections below, never in Buyable now. (Enforced three ways — §9.)

---

## 4. Terminal buckets (how to read a run)

Each candidate ends in exactly one bucket:

| Bucket | Meaning | Alerts? |
| --- | --- | --- |
| `alerted` | Verified buyable, comped, cleared the verdict + dedupe gates → pushed. | **yes** |
| `suppressed_dupe` | Would alert, but same listing already alerted (within cooldown, no ≥5% price drop, no status flip). | no |
| `out_of_stock` | Verifier saw an affirmative out-of-stock. | no |
| `price_mismatch` | Live price differs from the advertised price by >5%. | no |
| `unverifiable` | Could not confirm buyability (no wired resolver, page unparseable, blocked, page unavailable, parser-suspect, or a lying "verified" object caught by the alert gate). | no |
| `no_comp` | No usable comp from any source, or a comp with no attribution URL. | no |
| `below_min_discount` | Comped, but `pct_off < poke.min_discount_pct`. | no |
| `below_confidence` | A Ring-3 (wildcard) candidate whose comp confidence < `discovery.min_alert_confidence`. | no |

Only `alerted` fires a notification. Everything else is on the board (where
applicable) with an honest reason, never a push.

---

## 5. Source degradation states

Each source reports one operational state (single taxonomy —
`scanner/confidence.py`). In the manifest `sources[]` and on the dashboard
Sources section:

| State | Meaning / your action |
| --- | --- |
| `WORKING` | Healthy, producing candidates. |
| `THROTTLED` | Skipped this run: fired more recently than its `min_interval_seconds`. Normal. |
| `NOT_IMPLEMENTED` | Declared stub (e.g. `target_search`, `trackalacker` — Playwright wave 2). Expected. |
| `NEEDS_API_KEY` | Enabled but no credentials (e.g. `ebay_browse` without the keyset). Provision to activate (§7). |
| `BLOCKED` | HTTP 403/429. Back off; not a code bug. Do **not** attempt evasion. |
| `PARSER_SUSPECT` | HTTP 200 but nothing parsed / inner markup drifted. **Needs a code fix** — the upstream page changed. See §5.1. |
| `DEGRADED` | Transient error / partial failure (e.g. network down, some queries failed). Usually self-heals next run. |
| `DISABLED` / `READY` / `NEEDS_ID` / `ID_SUSPECT` | As documented in `confidence.py`; not typical for discovery adapters. |

A degraded source never stops the pipeline — it contributes zero candidates and
its state is recorded. No alert is ever produced from a degraded source.

### 5.1 What `PARSER_SUSPECT` means and what to do

`PARSER_SUSPECT` is the drift alarm: the source answered HTTP 200 but the parser
extracted nothing where it should have. Causes and coverage:

- **Slickdeals** — zero deal cards parsed, **or** live cards present but no title
  parsed from any of them (inner-markup drift). The second case used to pass as
  `WORKING`/empty (a silent lie) and was closed in Slice 6A.
- **eBay Browse** — no query returned an `itemSummaries` key (Browse schema
  drift).
- **verify_page** (merchant page fallback) — no schema.org availability signal,
  or ambiguous signals (recommendation carousel next to the product).

When you see it: the upstream HTML/JSON changed. Re-capture the fixture, update
the selectors in the relevant parser, and confirm the drift canary in
`tests/test_parser_drift.py` still fires on a gutted fixture. Never "fix" it by
loosening the parser into guessing — a wrong number is worse than none.

---

## 6. Configure Discord / ntfy

Alert channels are optional; with none set, alerts print to the console only and
the pipeline still works. Set either or both in the gitignored `config.yaml`
(top-level keys; env fallbacks `DISCORD_WEBHOOK` / `NTFY_TOPIC`):

```yaml
discord_webhook: "https://discord.com/api/webhooks/XXXX/YYYY"
ntfy_topic: "my-poke-deals-topic"
```

Behavior:
- **Discord** always posts on an alert (a silent, durable history — even in
  quiet hours).
- **ntfy** pushes only outside quiet hours (`alerts.quiet_hours`, default
  `23:00-08:00`, local, wrap-aware). In quiet hours the board still updates and
  Discord still posts; only the phone push is suppressed.
- A channel that fails (network down, bad webhook) prints a one-line stderr
  notice and never aborts the run (Slice 6A also guards against an unexpected
  notifier failure — the run always completes and the board is always written;
  a delivery that fails is not recorded, so the next run re-attempts it).
- Untrusted buy URLs are scheme-allowlisted (`http(s)` only) before they become
  clickable in any channel or on the dashboard.

Relevant `alerts` config (all defaulted; see `config.example.yaml`):

```yaml
alerts:
  quiet_hours: "23:00-08:00"
  price_drop_realert_pct: 5     # re-alert a live listing when price drops >= this %
  cooldown_hours: 24            # otherwise no repeat alert until this elapses
```

---

## 7. Provision the eBay keyset

Follow `docs/poke/ebay-keyset-setup.md` (free, ~15 min). Until it lands,
`ebay_browse` (discovery) and the eBay comp source both report `NEEDS_API_KEY`
and contribute nothing; the rest of the pipeline runs normally. **Do not treat
eBay lanes as active before the keyset is provisioned** — the manifest will say
`NEEDS_API_KEY` and that is the truth.

After provisioning, verify with a dry run: `ebay_browse` should move from
`NEEDS_API_KEY` to `DEGRADED "network disabled"` under `--dry-run` (proving it
now *would* fetch), and to `WORKING`/`PARSER_SUSPECT`/`BLOCKED` on a live run.

---

## 8. Install / uninstall the scheduler (operator-run only)

The pipeline is a one-shot; `scripts/register_tasks.ps1` registers a repeating
Windows Scheduled Task that runs it on an interval. **The build never registers
tasks — you do, after review.** The script is dry-run-by-default (prints the
plan, changes nothing) and every action is reversible.

```powershell
# See the plan only (no changes):
powershell -ExecutionPolicy Bypass -File scripts\register_tasks.ps1

# Register a SAFE dry-run schedule first (fires the pipeline in --dry-run):
powershell -ExecutionPolicy Bypass -File scripts\register_tasks.ps1 -Install -DryRunTask

# Register the LIVE repeating pipeline (default every 120 min):
powershell -ExecutionPolicy Bypass -File scripts\register_tasks.ps1 -Install

# Custom interval:
powershell -ExecutionPolicy Bypass -File scripts\register_tasks.ps1 -Install -IntervalMinutes 180

# Remove it (reversible; touches no code/config/data):
powershell -ExecutionPolicy Bypass -File scripts\register_tasks.ps1 -Unregister
```

Task properties: runs via the venv `pythonw.exe` (no console window), no
overlapping instances, a 30-minute execution cap (a hung fetch is killed),
starts when available. Inspect/trigger manually:

```powershell
Start-ScheduledTask     -TaskName PokemonDiscoveryPipeline    # run now
Get-ScheduledTaskInfo   -TaskName PokemonDiscoveryPipeline    # last result
```

The **restock lane** is a separate task with its own registrar — do not
duplicate it here:
`powershell -ExecutionPolicy Bypass -File scripts\install-scheduled-task.ps1 -Install`.

**Recommended first-time sequence:** dry-run CLI → `-Install -DryRunTask` for a
day → confirm it fires cleanly → `-Unregister` → `-Install` (live).

---

## 9. Evidence belts (why an alert can be trusted)

Three independent belts stand between a candidate and an alert. All three are
wired on the discovery path and covered by tests:

1. **Alert gate** — `verify.assert_alertable(v)` runs on the *fresh, same-run*
   `StockVerification` object (`pipeline.py`), re-checking the actual evidence
   (state, positive stock, verified price, buy URL, evidence text, timestamp),
   never trusting the state label. A "verified" object without evidence is
   refused → `unverifiable`. *(tests: `test_poke_pipeline.py` —
   `test_verified_buyable_alerts_and_gate_runs_on_fresh_object`,
   `test_fabricated_verified_without_evidence_never_alerts`.)*
2. **STOP gate** — `schema.assert_sweep(board_rows)` runs in the pipeline and
   again inside `render_sweep` before any HTML is produced: a row claiming
   positive stock without evidence/buy_url/checked_at (or a fabricated price)
   halts the render. *(tests: `test_poke_schema.py` gate-violation cases +
   `test_assert_sweep_raises_on_any_violation`.)*
3. **Golden belt** — `golden.golden_check` fails the dashboard if the Buyable-now
   section contains any non-positive stock row or any positive row without
   evidence; on failure the dashboard is withheld and JSON evidence is kept.
   *(tests: `test_poke_golden.py` — mutation-verified evidence-tamper case.)*

No alert can bypass fresh verification evidence. That is the pipeline's reason to
exist.

---

## 10. Do **NOT** flip `comps.engine` to `inhouse` yet

`comps.engine` stays `legacy`. Flipping it to `inhouse` now would be a
**downgrade**, for two reasons recorded at Slice 1:

- **TCGplayer source is a STUB.** The product page served a JS shell with no
  parseable price to plain requests (Task-1 probe,
  `docs/poke/reference/tcgplayer-probe.md`). The in-house TCGplayer source
  returns `blocked` — no price.
- **eBay keyset is pending.** The in-house eBay comp source is `NEEDS_API_KEY`.

With both sold-derived lanes dark, the in-house engine would produce
**PriceCharting-only, LOW-confidence** comps — worse than the legacy path's
PriceCharting/eBay fallback. Flip only after **at least one** of {TCGplayer
acquisition resolved, eBay keyset provisioned} lands, and only after a
side-by-side legacy-vs-inhouse comparison run is reviewed. This runbook and
Slice 6A do **not** perform the cutover.

Rollback of a mistaken flip is one line: set `comps.engine: legacy` in
`config.yaml` (default) — no data migration involved.

---

## 11. Live-smoke approval checklist

The spec's final validation (§8.3) is a live, network-touching smoke run. It is
**operator-gated**. Before running any live network pass (smoke or scheduled),
confirm all of:

- [ ] **Explicit operator go-ahead** for this specific live run (not implied by
      a prior run).
- [ ] **Zero PPT credits** will be spent (the discovery comp path is PPT-free by
      construction; do not add `--validate` or any PPT call).
- [ ] **Sanctioned sources only** — `slickdeals` (plain fetch) and, once
      provisioned, `ebay_browse` (API). `target_search`/`trackalacker` stay
      stubbed (no Playwright unless separately approved).
- [ ] **Read-only** — stock-query fetches only; no cart, no login, no bot-wall
      evasion.
- [ ] Run against an **isolated state db / out dir** if you don't want the smoke
      to touch real dedupe history: `--out <tmp>` for the board/ledger writes,
      and set `POKEMON_SCANNER_STATE_DB` to a throwaway db so dedupe history is
      isolated too.

**Success = the pipeline told the truth:** the manifest shows ≥1 candidate
reaching `alerted` (with buy link + verified price + evidence) **or** every
candidate honestly classified (`unverifiable`/`out_of_stock`/`no_comp`/…) with a
reason string, and the counts reconcile. No silent drops.

Suggested first smoke (after go-ahead), in PowerShell:

```powershell
$env:POKEMON_SCANNER_STATE_DB = "$env:TEMP\poke-smoke\state.db"
.venv\Scripts\python.exe -m scanner.discovery.pipeline `
  --once --sources slickdeals --out "$env:TEMP\poke-smoke"
Remove-Item Env:\POKEMON_SCANNER_STATE_DB   # clear it afterward
```

---

## 12. Rollback

Everything here is additive and reversible:

- **Scheduler:** `register_tasks.ps1 -Unregister` (removes the task only).
- **Alerts:** unset `discord_webhook` / `ntfy_topic` → console-only.
- **Comp engine:** `comps.engine: legacy` (the default) — never flip in the
  first place until §10's prereqs clear.
- **Code:** the discovery pipeline is new files + additive edits; the
  `state.db` tables (`seen_listings`, `deal_alerts`, `discovery_runs`,
  `comp_cache`) are `CREATE TABLE IF NOT EXISTS` and inert if unused — no
  migration to undo. Reverting the discovery commits leaves the restock lane
  untouched.
- **Data:** board/manifest/dashboard files are dated and disposable; the ledger
  (`price_history.jsonl`) is append-only history — delete a run's rows only if
  you know why.

Nothing in this pipeline is pushed to any remote without explicit operator
instruction.
