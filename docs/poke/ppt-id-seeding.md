# Data Task — PokemonPriceTracker `ppt_id` seeding (sealed catalog)

Separate from engine code. PPT sealed comps resolve by **exact `tcgPlayerId`** only — a bare
name search returns the wrong variant (Sam's Club bundle, case, store exclusive), so every
sealed product needs a verified `ppt_id` in `data/products.yaml`. Until a product has one, the
PPT path skips it (0 credits) and the scanner falls back to eBay/PriceCharting — safe, just not
PPT-backed.

## How to source an id (1-5 credits each, verify before commit)
```
python -c "
import requests
from scanner import config as cfg_mod
cfg = cfg_mod.load()
r = requests.get('https://www.pokemonpricetracker.com/api/v2/sealed-products',
    params={'search':'<clean product name>','limit':5},
    headers={'Authorization': f'Bearer {cfg.market_api_key}'}, timeout=30)
for d in r.json().get('data', []):
    print(d.get('tcgPlayerId'), repr(d.get('name')), d.get('unopenedPrice'), repr(d.get('setName')))
"
```
Pick the row whose `name` is the **standalone product in the right set** (exclude '… and Pokeball',
'… Case', '(Sam's Club)', '(Dollar General Exclusive)', sticker/tech collections, etc.). Then add:
`ppt_id: "<tcgPlayerId>"` to that product. Verify by re-running `scripts/poke_phase0_comp_probe.py`
(or a by-id GET) and confirming the name + a plausible `unopenedPrice`.

## Budget
Free tier = 100 credits/day. A by-id lookup is 1 credit; seeding all ~26 sealed products via a few
limit=5 searches is well under one day's budget. Once seeded, steady-state is ~1 credit/product per
24h cache refresh.

## Target keys (active sealed catalog)
- [x] prismatic_evolutions_etb — `ppt_id: 593355` (standalone ETB; $199.14; verified 2026-06-28)
- [ ] prismatic_evolutions_booster_bundle
- [ ] prismatic_evolutions_surprise_box
- [ ] journey_together_etb
- [ ] journey_together_booster_bundle
- [ ] destined_rivals_booster_bundle
- [ ] destined_rivals_etb
- [ ] surging_sparks_etb
- [ ] surging_sparks_booster_bundle
- [ ] scarlet_violet_151_etb
- [ ] scarlet_violet_151_booster_bundle
- [ ] paldean_fates_etb
- [ ] crown_zenith_etb
- (MTG products: PPT is Pokémon-only — leave `ppt_id` empty; they keep the eBay/PriceCharting path.)

## Done when
Each checked box has a verified `ppt_id` in `data/products.yaml`, OR a recorded NOT_FOUND note
(product not in PPT's sealed catalog → stays on the resale fallback).
