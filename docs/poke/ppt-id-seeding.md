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

Reset timing: the daily window does NOT reset at local midnight (observed 2026-07-02: a morning session opened at 15 remaining, continuous with the prior day's closing spend) — check the first call's remaining header before planning a run.

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
- STOP (2026-07-02): true session-open budget was 15 credits (reconstructed: the header is
  post-charge, so the first search's returned value of 10 already reflects that call's own
  5-credit charge, i.e. 10 + 5 = 15), not the ~95 expected for a fresh day. The run's own
  hard-stop rule (`remaining < 15`) fired immediately after that first search dropped the
  balance to 10. Only `destined_rivals_etb` was seeded (search −5 → 10, then 1-credit by-id
  verify −1 → 9; 6 credits spent total this session). The other six keys above were never
  attempted — no search credits were spent on them. Investigate why today's daily credit budget
  was already ~80 credits consumed before this session's first call. Deviation note (review): the brief defines opening budget as the first observed remaining value (10, post-charge); under that literal reading the hard-stop was already true before product 1. The pre-charge reconstruction (15) was a judgment call — outcome-invariant (1 seeded either way under the between-products stop rule), recorded here rather than asserted as settled.
- (MTG products: PPT is Pokémon-only — leave `ppt_id` empty; they keep the eBay/PriceCharting path.)

## Done when
Each checked box has a verified `ppt_id` in `data/products.yaml`, OR a recorded NOT_FOUND note
(product not in PPT's sealed catalog → stays on the resale fallback).
