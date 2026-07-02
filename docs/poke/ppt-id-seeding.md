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
Free tier = 100 credits/day. A by-id lookup is 1 credit **only if `limit=1` is passed explicitly**
— omitting `limit` on `/sealed-products` defaults to `limit=50` and bills 50 credits (confirmed live
2026-07-01: one no-`limit` by-id call dropped `X-RateLimit-Daily-Remaining` from 95 to 45). Always
pass `limit=1` for by-id verification. Seeding all ~26 sealed products via limit=5 searches +
limit=1 verifies is well under one day's budget at ~6 credits/product. Once seeded, steady-state is
~1 credit/product per 24h cache refresh — `scanner/market.py` pins `limit=1` on its by-id GET
(fixed 2026-07-01) — requests bill on the requested limit (default 50), not results; never remove
it.

## Target keys (active sealed catalog)
- [x] prismatic_evolutions_etb — `ppt_id: 593355` (standalone ETB; $199.14; verified 2026-06-28)
- [x] prismatic_evolutions_booster_bundle — ppt_id: 600518 ($92.40; verified 2026-07-01)
- [x] prismatic_evolutions_surprise_box — ppt_id: 593466 ($72.67; verified 2026-07-01)
- [x] journey_together_etb — ppt_id: 610930 ($132.58; verified 2026-07-01)
- [x] journey_together_booster_bundle — ppt_id: 610953 ($48.81; verified 2026-07-01)
- [x] destined_rivals_booster_bundle — ppt_id: 625670 ($84.74; verified 2026-07-01)
- [x] destined_rivals_etb — ppt_id: 624676 ($180.65; verified 2026-07-02)
- [ ] surging_sparks_etb
- [ ] surging_sparks_booster_bundle
- [ ] scarlet_violet_151_etb
- [ ] scarlet_violet_151_booster_bundle
- [ ] paldean_fates_etb
- [ ] crown_zenith_etb
- STOP (2026-07-02): opening `X-RateLimit-Daily-Remaining` was 10 (not the expected ~95) on the
  very first search call of the session; the run's own hard-stop rule (`remaining < 15`) fired
  immediately after that call. Only `destined_rivals_etb` was seeded (already-paid-for search +
  1-credit by-id verify, remaining 10→9). The other six keys above were never attempted — no
  search credits were spent on them. Investigate why today's daily credit budget was already
  ~90 credits consumed before this session's first call.
- (MTG products: PPT is Pokémon-only — leave `ppt_id` empty; they keep the eBay/PriceCharting path.)

## Done when
Each checked box has a verified `ppt_id` in `data/products.yaml`, OR a recorded NOT_FOUND note
(product not in PPT's sealed catalog → stays on the resale fallback).
