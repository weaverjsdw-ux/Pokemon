# Slickdeals Track-A Evidence Classification — 2026-07-04

**Question:** Is Slickdeals a *live actionable* deal source, or only a *research
signal*?

**Method:** Paper-first classification. No fresh live network smoke was run this
session (operator elected paper-first). This classifies the **existing**
operator-approved live evidence — the single live GET of thread `19650840`
(2026-07-04, HTTP 200, 763 KB, no Cloudflare/JS challenge) captured in
`tests/fixtures/discovery/slickdeals_thread_live_19650840.html` — together with
the structural behavior of `resolve.py` / `verify.py` / `pipeline.py`.

The operator's four candidate outcomes were:

1. resolver works **and** merchant verification works
2. resolver works **but** merchant pages are blocked / parser_suspect / price_mismatch
3. verified candidates reach `no_comp`
4. invariant failure

## Verdict: **RESEARCH SIGNAL, not yet a live actionable source.**

The honest classification is a **blend of (2) and (3)**, with (1) unproven and
(4) not observed. The single stage that is *proven* is thread→merchant-URL
resolution; every downstream stage that would make Slickdeals *actionable* is
either unproven or structurally blocked in this build.

## Stage-by-stage evidence

| Stage | Status | Evidence |
| --- | --- | --- |
| **Thread discovery (search → candidates)** | UNPROVEN this cycle | No live search run this session. Prior Slice-5 one-off returned 3 real candidates, all honestly `unverifiable` (no resolver existed then). |
| **Thread → merchant-URL resolution** | ✅ **WORKS (live-confirmed)** | `resolve._see_deal_hrefs` selects exactly the 4 featured-deal `/click` anchors on the real thread and rejects related-deal cards (`dealCardGrid__*`), the sticky-image link, the in-post `data-cta="outclick"`-only link, and forum/nav. The **wrong-anchor risk** the runbook flagged is closed by test `test_resolve_live_thread_selects_only_featured_deal_ctas`. |
| **`/click` → merchant landing hop** | ⚠️ **UNPROVEN (mocked)** | The featured CTA is an *internal* `slickdeals.net/click` redirect endpoint, not a direct merchant href. The `/click`→Amazon (`B0GRCDKMSW`) hop was **mocked** in the fixture, never fetched live. Whether Slickdeals actually 3xx-redirects that endpoint for an anonymous client is unconfirmed. If it stops redirecting, the lane under-alerts (safe). |
| **Merchant-page verification (schema.org stock+price)** | ⚠️ **UNPROVEN, structurally low-yield** | `verify_page` reads schema.org markup from a plain `requests` GET. The resolved merchant here is **Amazon** (and big-box merchants generally), which routinely serve JS shells / anti-bot pages to plain requests → expected `parser_suspect` / `blocked`, or `price_mismatch` because Slickdeals prices are frequently coupon/promo-gated. This is outcome **(2)**. |
| **Comp** | ⚠️ **structurally `no_comp`** | Slickdeals candidates are non-catalog (Ring-2/Ring-3). `pipeline.default_comp_lookup` returns `no_match` for any candidate with no `matched_product_key` ("non-catalog candidate; no ad-hoc comp in this build"). So **even a fully verified Slickdeals candidate lands in `no_comp`** today. This is outcome **(3)**, and it is *structural*, not incidental. |
| **Invariant health** | ✅ no failure | Full suite green (577 passed) including the live-fixture tests. Manifest reconciliation, alert-gate, STOP-gate, and golden belts are all intact. Outcome **(4)** not observed. |

## What this means for actionability

Two independent gaps stand between Slickdeals and a *money* decision, and
**both** must close before any Slickdeals candidate could reach
`LIVE_PACKET_ELIGIBLE`:

1. **Merchant hop + parse (outcome 2).** Needs a fresh live smoke to learn
   whether the `/click` hop resolves and whether the resolved merchant page
   parses. Expectation is low-yield (JS shells / price_mismatch). *Deferred by
   operator choice; the approval packet at
   `docs/poke/live-smoke-approval-2026-07-04.md` remains valid for when it is
   run.*
2. **Ad-hoc non-catalog comp (outcome 3).** Even a verified candidate cannot be
   comped today (no catalog key → `no_comp`). This is the Post-6B plan's
   **Branch D** trigger: the next comp feature is ad-hoc Ring-2/Ring-3 comps,
   scoped in `docs/superpowers/plans/2026-07-04-post-6b-stabilization-and-live-smoke-gate.md`
   Task 6 Step 4.

Until both close, Slickdeals feeds the **research/WATCH** tier of the Money
Hypothesis Lab (Track D), not the actionable tier. The resolver is trustworthy;
the lane is not yet a source of buyable, comped, verified deals.

## Recommendation

- Keep Slickdeals wired as a **research signal** feeding `WATCH` /
  `SOURCE_BLOCKED` / `PARSER_SUSPECT` / `PRICE_MISMATCH` / `NO_COMP` reporting in
  the Track-D decision output — never the actionable tier — until a live smoke
  confirms the merchant hop+parse **and** ad-hoc comps exist.
- The next live smoke, when run, is also the merchant-hop + merchant-parse probe;
  its result selects Post-6B Branch C (source unlocks) vs Branch D (ad-hoc comps).
