# Phase 0 Findings — `/poke` pipeline

## Probe A — sealed comp verification (Task 1)
- Date run: 2026-06-27
- Client used: **PublicFallbackResaleClient** (PPT is NOT configured — `market_preferred=false`
  / no key, so `market_client_from_config` returned the resale fallback, not the PPT
  `MarketFallbackClient`).
- Sealed product: `prismatic_evolutions_etb`
- Result: `status=ok`, `source='PriceCharting market fallback'`, `comp=163.75`,
  `confidence_tier='medium'` → under the render gate, medium = **verified-tier** (non-EST).
- **Verdict:** **QUALIFIED YES.** Sealed yields a *medium*-confidence, verified-tier comp
  today, so under the §3.3 gate sealed can render as a non-EST deal. **But two caveats make
  this necessary-not-sufficient:**
  1. **PPT is not active.** The best sealed comp source (PokemonPriceTracker) is unconfigured;
     today's comp comes from the PriceCharting *fallback*.
  2. **Comp value looks unreliable.** $163.75 for an ETB with ~$50 MSRP is almost certainly a
     loose/mismatched fallback match (expected sealed street ~$60). The "medium" tier label
     does **not** guarantee the number is right.
- **Implication for follow-on plan:**
  - Obtain + enable the **PPT key** before the live-acquisition phase; treat it as the gating
    prereq for trustworthy sealed comps (and the only native source for raw/graded).
  - The live RESEARCH stage must **sanity-check fallback comps against an expected range**
    (e.g. flag a comp that is a large multiple of MSRP as suspect / downgrade to EST), so a
    loose PriceCharting match never produces a confident STEAL. This is a concrete addition to
    the follow-on plan's comp-routing task, surfaced only because this probe ran live.
