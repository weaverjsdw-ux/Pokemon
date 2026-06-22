# 05 — Product & UX Operating Model

*Designs the operational surface of the command center. Builds on the existing dashboard (`web.py` + `web_assets/`), which already implements most of this — this doc says what to keep, what to add, and how the operator actually works. Not a marketing page; the usable surface comes first.*

---

## Information architecture

The dashboard is a **single operator console** with one live status feed (`GET /api/status`, 5s poll) and a few action panels. Group surfaces into four zones:

```
┌─ COMMAND BAR ───────────────────────────────────────────────┐
│  Liveness ● live/stale/down · Last scan · Next scan · Mode   │
│  [Scan once] [Start] [Stop] [Safe demo] [Dry run]            │
├─ ZONE 1: WHAT NEEDS ME (triage) ────────────────────────────┤
│  Action Queue · ID Doctor queue · Release-watch inbox        │
├─ ZONE 2: WHAT'S HAPPENING (signal) ─────────────────────────┤
│  Store stock board · Recently in stock · Alerts              │
├─ ZONE 3: HOW HEALTHY IS IT (trust) ─────────────────────────┤
│  Active coverage · Source health · Store diagnostics         │
├─ ZONE 4: CONTEXT & CONFIG (reference) ──────────────────────┤
│  Price/MSRP watch · Products · Add-ID · Settings · Log       │
└──────────────────────────────────────────────────────────────┘
```

Today's dashboard already renders almost all of these (verified in `web_assets/app.js`); the work is (a) a true **Liveness** indicator, (b) the **Release-watch inbox**, (c) the **ID Doctor** action surface, and (d) **source-mode labels**.

---

## Surface specs

Each surface: *question it answers · data · actions · hide-until-needed · doctrine-impossible · empty state · failure state · acceptance.*

### Command bar — Liveness & runner
- **Q:** "Is it actually running right now?"
- **Data:** persisted heartbeat (last loop ts), runner mode/interval, last/next scan, `source_mode`.
- **Actions:** start/stop/scan-once/dry-run/safe-demo (exist).
- **Hide:** advanced runner stats behind a disclosure.
- **Impossible:** showing "live" when the loop has actually died (today's gap — fix with heartbeat).
- **Empty:** "Not started — press Start or install the scheduled task."
- **Failure:** "Stale — last loop 14m ago (expected 3m). Last error: …".
- **Accept:** indicator flips to *stale* within one interval of a stalled loop; *down* when the process is gone (heartbeat older than N×interval).

### Zone 1 — Action Queue (exists, `workqueue.build`)
- **Q:** "What single thing most improves coverage right now?"
- **Data:** confidence rows + products. **Actions:** one-click → Add-ID or Settings prefilled.
- **Hide:** `NOT_IMPLEMENTED`/`DISABLED` retailers unless they have IDs.
- **Impossible:** suggesting work on a `samsclub`-style stub as if real.
- **Empty:** "Coverage looks complete for enabled retailers 🎉".
- **Failure:** if confidence can't build, show why (config error), not a blank list.
- **Accept:** top item is always the highest-leverage gap; clicking it lands on a prefilled form.

### Zone 1 — ID Doctor queue (NEW; `verify_ids` is CLI-only today)
- **Q:** "Which catalog IDs are wrong, stale, or unverified?"
- **Data:** provenance sidecar (`status`, `verifiedAt`) + a new `POST /api/verify-ids` run.
- **Actions:** "Verify now" (per product or all), "Fix ID" (→ Add-ID), mark reviewed.
- **Hide:** confirmed-recent IDs (collapse "all good").
- **Impossible:** claiming an ID is verified when the check only confirmed a URL returns 200 (label these "URL-resolves only" for Walmart/Costco/GameStop — honesty over fake confidence).
- **Empty:** "All IDs verified within 30 days."
- **Failure:** verification blocked (403) shows as *blocked*, not *confirmed*.
- **Accept:** every product-retailer pair shows a real status + age; running the Doctor updates provenance and the queue.

### Zone 1 — Release-watch inbox (NEW)
- **Q:** "What's dropping soon and am I ready (IDs in hand)?"
- **Data:** new release-watch records (set, date, products, IDs-needed, retailers expected).
- **Actions:** "Add to catalog," "Find IDs" (→ Add-ID), "Snooze," "Escalate to release-week cadence."
- **Hide:** releases >60 days out (collapsed).
- **Impossible:** auto-buying or queue automation for a drop.
- **Empty:** "No upcoming releases tracked — import a catalog pack."
- **Failure:** if a date passed without IDs, flag "missed prep."
- **Accept:** a release within 14 days with missing IDs surfaces at the top with a countdown.

### Zone 2 — Store stock board / Recently in stock / Alerts (exist)
- **Q:** "Where is my product right now / where was it recently?"
- **Data:** runner snapshot, `stock_history`, last alerts. **Actions:** open product URL.
- **Impossible:** showing marketplace/3P listings as retail restocks; exposing exact store addresses in any shareable view.
- **Empty / Failure:** "No board yet — run a scan" / per-source error chips.
- **Accept:** a confirmed restock appears on the board and (if alertable) in Alerts within one cycle, deduped.

### Zone 3 — Coverage / Source health / Store diagnostics (exist)
- **Q:** "Is the tool covering what I think, and are sources trustworthy?"
- **Data:** `coverage_report`, `health.snapshot`, discovery diagnostics.
- **Impossible:** a green "healthy" that actually means "never checked" (distinguish out-of-stock vs blocked vs parser-empty vs network — already modeled in `health.py`).
- **Accept:** each source shows healthy/degraded/down + last success + reason; coverage shows %, and **which** products are non-actionable.

### Zone 4 — Price/MSRP watch, Products, Add-ID, Settings, Log (exist)
- **Q:** "How distorted is the market, what am I tracking, and how do I configure safely?"
- **Data:** resale cache (labeled, `*` for low-confidence), catalog, config.
- **Impossible:** displaying resale as a flip target; showing secrets in Settings (webhook/keys are write-only — already the case).
- **Accept:** Settings round-trips `config.yaml` without ever echoing secret values; Add-ID writes `products.yaml` preserving comments (already does).

---

## Primary operator flows

**Flow A — New set announced → verified IDs → alert ready** *(the core loop)*
1. Release-watch inbox shows the new set (from a catalog pack or manual add) with "IDs needed."
2. Operator opens each retailer's product page, pastes the URL into **Add-ID** (auto-extracts TCIN/SKU/slug; records provenance).
3. **ID Doctor** verifies the new IDs; green ones go live, "URL-resolves only" ones are flagged.
4. Coverage ticks up; the product enters the scan rotation.
5. On a real restock, the **stock board** updates and an **alert** fires (Discord/ntfy) with a tap-to-buy URL.
6. Operator buys it themselves. No automation past the alert. ✅ doctrine.

**Flow B — Daily check (≤60 seconds).** Open dashboard → glance at Liveness (live?), Action Queue (anything red?), Recently-in-stock (did I miss something overnight?). Done. The point of the dashboard is that *nothing needs doing* most days.

**Flow C — Release week.** Switch the watched set to release-week cadence (tighter, still ≥60s); confirm IDs are all green in ID Doctor; ensure Discord + ntfy both deliver (test alert); for Pokémon Center / Best Buy invite drops, the tool only *reminds* the operator to be ready to enter the queue / watch email.

**Flow D — Mobile alert.** Phone gets a Discord embed + ntfy push with product name, store/online, price vs MSRP, and a direct URL. One tap → retailer's own cart/checkout in the operator's browser. The tool never touches checkout.

---

## Experience targets

- **First-time setup should feel like:** "copy config, paste a Discord webhook, get a free Best Buy key, run `--check-config`, see a coverage number." The Best Buy key is the durable happy path; the other (personal-use) adapters are an explicit opt-in.
- **A daily check should feel like:** a 10-second glance that usually says "all good," with anything needing attention surfaced in Zone 1.
- **Release week should feel like:** calm readiness — IDs verified ahead of time, both alert channels tested, cadence tightened, and clear "go enter the queue yourself" prompts for queue/invite retailers.

---

## Text wireframe (dashboard, default state)

```
TCG MSRP Command Center            ● LIVE · last 1m ago · next ~2m · mode: personal_polite
[Scan once] [Start] [Stop]                                   [Safe demo] [Dry run]

WHAT NEEDS ME
  ▸ Add Best Buy SKU for "Pitch Black ETB"        coverage +1   [Add ID]
  ▸ Verify Target TCIN for "Chaos Rising ETB"     stale 41d     [Verify] [Fix]
  ▸ Release in 5 days: First Partner S2 — 0/3 IDs  ⏳            [Find IDs]

WHAT'S HAPPENING
  Stock board:  Best Buy · Pitch Black ETB · ONLINE_IN_STOCK · $49.99   [Open]
  Recently in stock:  Chaos Rising Bundle @ Target #1234 · 2h ago · 3 restocks
  Alerts (last 24h):  1 fired · Discord ✓ · ntfy ✓

HOW HEALTHY IS IT
  Active coverage  ███████████████████░  86% (19/22)   non-actionable: 3 [view]
  Sources:  Best Buy ● healthy (API)   Target ● healthy   Walmart ◐ degraded (parser empty)
            Pokémon Center ○ alert-only (queue)   GameStop ○ disabled
  Discovery:  8 centers · 22 candidates · 6 in corridor

CONTEXT & CONFIG
  Price watch:  Pitch Black ETB  MSRP $49.99 · resale ~$95* (asking, low-conf)
  [Products] [Add ID] [Settings] [Technical log ▾]
```

This is close to what exists; the **bold deltas** are the Liveness truth indicator, the Release-watch row, the ID Doctor "Verify/stale" affordances, and the source-mode label + source badges.
