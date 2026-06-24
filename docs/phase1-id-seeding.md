# Phase 1 Data Task — Costco & Pokémon Center ID Seeding

Separate from the engine code. Missing IDs must never block margin/verdict.
All IDs pass the existing verify → provenance gate (`scanner/verify_ids.py`,
`data/id_provenance.json`). No guessing — verify each before commit.

## Costco (`costco_item_id`) — target keys (active Prismatic-era, in catalog)
- [ ] prismatic_evolutions_etb
- [ ] prismatic_evolutions_booster_bundle
- [ ] prismatic_evolutions_surprise_box

Source: Costco product URL segment before `.html`. Verify via the Costco
4-endpoint chain in `scanner/retailers/costco.py`. Record verdict in provenance.

## Pokémon Center (`pokemoncenter_slug`) — target keys
- [ ] prismatic_evolutions_etb
- [ ] (add PC-exclusive SKUs as they appear; PC stays alert-only/human checkout)

Source: Pokémon Center product URL slug. Verify the slug resolves before commit.

## Done when
Each checked box has a verified ID in `data/products.yaml` + a provenance entry,
OR a recorded NOT_FOUND/BLOCKED verdict explaining why it could not be sourced.
