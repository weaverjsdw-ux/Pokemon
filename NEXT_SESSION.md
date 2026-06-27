# NEXT SESSION — Pokémon deal-intelligence (new brainstorm)

Port the **GUN DEALS `/gun`** AI deal-research pipeline to the Pokémon resale engine. This is a **fresh brainstorm** (its own spec → plan → build). Memory `[[pokemon-ai-driven-deal-research]]` + `[[pokemon-resale-engine-phase1]]` auto-recall the context.

## Open the session
New session, then:
```
/superpowers:brainstorming port the GUN DEALS AI deal-research pipeline to my Pokemon resale engine
```

## What to reuse from the gun build (proven 2026-06-27)
The gun program (`OneDrive\Desktop\GUN DEALS\`) is the reference implementation. Lift its **spine**, re-cast for TCG:
- **Pipeline:** discover → research → score → verify → persist → render an HTML dashboard.
- **Price-accuracy discipline (load-bearing):** every price carries source URL + capture date; estimates badged EST; "% off" vs **verified market**, never inflated; **never fabricate**; stale sources excluded.
- **Acquisition reality:** big sites Cloudflare-block plain fetch → **Playwright** clears aggregators; editorial curators + WebSearch fill gaps. Expect the same for TCG retailers.
- **Regression subsystem:** append-only price ledger, watchlist continuity, golden test, prompt-durability hash + audit gate.
- **Multi-lens scoring** (gun used Collector/Shooter/Builder/Flipper) → re-cast for TCG (e.g., Collector / Player / Investor / Flipper).

## Key questions that brainstorm must resolve
1. **Marketplaces/sources:** TCGplayer, eBay (sold/completed), Cardmarket, COMC, local? Which are fetchable vs blocked?
2. **Comp source for "market price":** TCGplayer Market, eBay sold median, PSA APR for graded?
3. **Graded (PSA/CGC/BGS) vs raw**, and **sealed product vs singles** — different valuation models; pick scope for v1.
4. **Scope vs the existing `Pokemon-main` scanner:** does this become the Phase-1 *deal-intelligence* layer, or a sibling? (See `docs/superpowers/plans/2026-06-18-phase1-deal-intelligence.md`.)
5. **Deliverable:** dashboard like the gun one? Tie into the existing resale engine's outputs?

## References
- Gun reference: `OneDrive\Desktop\GUN DEALS\DESIGN.md`, `OPENER.md`, `template.html`.
- This repo's existing plan: `docs/superpowers/plans/2026-06-18-phase1-deal-intelligence.md` (reframed hobby-funded-resale; implementation was gated).
