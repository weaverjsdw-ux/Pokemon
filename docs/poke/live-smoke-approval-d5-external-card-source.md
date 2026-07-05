# Live-Smoke Approval Packet — D.5 External Card Source (raw + graded)

**Status: NOT RUN. Requires explicit operator approval for the exact run below.**
D.5 makes no live/billed calls. This packet is the gate for the one later smoke
that validates the *real* external provider response shape against the hardened
adapter — the last remaining blocker before Session E.

## What this validates

The `refresh=true` asset comp path against a **real** external card-price provider:
that the live `/cards` JSON matches what `sources._card_market` /
`sources._graded_smart_from` parse, that `metadata.apiCallsConsumed.total` reflects
real spend, and that a real 401/429/odd-payload degrades honestly. Validates **raw
and graded** (two calls). Sealed is a separate provider path (`market.py`) and is
NOT exercised here.

## Preconditions (operator)

1. Map a real TCGplayer product id onto the asset(s) in `data/poke/assets.yaml`
   (today `tcgplayer_id` is commented out on all four Umbreon rows, so a refresh
   currently costs 0 — it issues no call). Map at least:
   - `umbreon_ex_161_raw_nm` → `tcgplayer_id: "<real id>"`   (raw path, 1 credit)
   - `umbreon_ex_161_psa10`  → `tcgplayer_id: "<real id>"`, `grade_key: psa10`
     (graded path, 2 credits)
2. Configure the external card source (either is fine):
   - `config.yaml` → `market: { preferred: true, api_key: "<key>" }`, **or**
   - env: `CARD_PRICE_API_KEY=<key>` (preferred) or legacy `PPT_API_KEY=<key>`,
     with `market.preferred: true`.

| Field | Value |
|---|---|
| Endpoint (raw) | `GET /api/poke/assets/umbreon_ex_161_raw_nm/comp?refresh=true` |
| Endpoint (graded) | `GET /api/poke/assets/umbreon_ex_161_psa10/comp?refresh=true` |
| Required config flag | `market.preferred: true` (+ a key) |
| Required key / env | `config.yaml market.api_key`, or `CARD_PRICE_API_KEY` (legacy `PPT_API_KEY`) |
| Expected credit cost | **raw = 1**, **graded = 2** (`includeEbay` +1) → **3 total** |
| Validates | raw + graded (NOT sealed) |

## Expected successful response

Each call returns `ok: true` with:
- `estimate`: a number (raw: sold-derived ladder; graded: `smartMarketPrice`), or
  honest `null`/`confidence: "none"` if the provider has no usable price for that id.
- `metadata.source: "external"`, `metadata.apiCallsConsumed.total`: **1** (raw) /
  **2** (graded), `estimated: true` (deterministic bound).
- `sources[]` carries the provenance (slug `ppt_cards`, exact URL).

## Expected failure behavior (must NOT crash)

- 401 (bad key) / 429 (rate/credit exhausted) → `estimate: null`, `confidence:
  "none"`, route returns `ok: true` (honest no-comp). `apiCallsConsumed.total` still
  reports the bound (the request was billable).
- Malformed 200 / missing or mistyped `data`/`prices`/`salesByGrade`/
  `smartMarketPrice` → honest `none`, no exception, sealed routes unaffected.

## How to prove no extra calls happened

- Before/after the run, hit the provider dashboard **daily-remaining** counter
  (the adapter also sees `X-RateLimit-Daily-Remaining`): total drop must equal
  **exactly 3** (1 raw + 2 graded) for the two calls above — no more.
- Confirm the read paths spent nothing: `GET .../comp` (no `refresh`),
  `/api/poke/opportunities`, `/api/poke/cards`, `/api/poke/assets` must each report
  `apiCallsConsumed.total: 0` and cause **no** counter movement.

## How to disable / roll back

- Set `market.preferred: false` (or unset the key / `CARD_PRICE_API_KEY` /
  `PPT_API_KEY`) → the client is dormant again, every refresh reports 0 credits.
- Re-comment `tcgplayer_id` in `assets.yaml` to return refresh to 0-call.
- No state is written by a comp refresh; nothing else to undo. No remote push.

## Decision after the run

- Live JSON parses + credit counter matches (3) → the adapter is provider-shape
  proven; the last E blocker clears (subject to operator sign-off).
- Live JSON diverges from the parsers → narrow adapter-repair task (capture one
  live fixture, fix `_card_market`/`_graded_smart_from`, no scope creep).
- Counter drops by more than 3 → STOP: an accidental extra call exists; fix before E.
