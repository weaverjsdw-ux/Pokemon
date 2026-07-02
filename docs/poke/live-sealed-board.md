# Live Sealed Deal Board — runbook

The board answers: **"which sealed products are most worth grabbing at retail (MSRP) right now?"**
It ranks the tracked catalog by appreciation headroom = live market comp vs MSRP.

## Prerequisites
- `config.yaml` with `market.preferred: true` and `market.api_key` set (or `PPT_API_KEY`).
  Without a key the board still runs — every comp comes from the eBay/PriceCharting
  fallback and renders EST (lower confidence), never a confirmed STEAL.
- Pokemon products should have verified `ppt_id`s (see `ppt-id-seeding.md`).
  MTG products always use the fallback (PPT is Pokemon-only).

## Run
    python -m scanner.discovery.sweep            # writes dashboards/<date>-sealed.html
    python -m scanner.discovery.sweep --out DIR  # everything under DIR instead (testing)

Outputs per run: `data/poke/<date>-sealed.json` (sweep), `.manifest.json` (counts,
badges, sources, credits, golden results), `data/poke/price_history.jsonl`
(append-only observation ledger — idempotent, safe to re-run), and the dashboard.
A golden hard-fail (structure broken, rows below `poke.min_rows`, or a row without
provenance) exits 1 and does NOT write the dashboard.

## Credits
One comp call per product per run (~13 PPT credits with a fully seeded catalog;
Free tier = 100/day). `poke.daily_credit_cap` (default 90) short-circuits the rest
of a run to the fallback if a run would blow the budget. The manifest and run
summary print credits consumed.
PPT bills on the requested `limit` (default 50), not results returned — the client
pins `limit=1` on by-id lookups; never remove it.

## Reading the board
- **STEAL** — verified comp, >= `poke.steal_pct` off. **EST** — estimated comp
  (fallback source or weak confidence); trust it less, click the source link.
- **Rank** — rows sort by % off (appreciation headroom vs MSRP).
- **Scanner column** — the same fee-adjusted BUY/THIN/SKIP verdict the scanner
  alerts with (identical math, pinned by test).
- The tool advises; the human transacts. Verify price + seal before buying.

## Spot-check after a live run (manual, ~2 min)
1. Prismatic Evolutions ETB shows a comp near its live market (~$199 as of 2026-06)
   with confidence `medium`+, badge STEAL, and a sane scanner verdict.
2. Row source links open the right product/search pages.
3. No secrets or addresses in the HTML: search it for your street/city and API key.
4. Manifest `counts` reconcile: scanned = comped + no_comp + no_msrp + no_source.
