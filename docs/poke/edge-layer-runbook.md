# Personal Edge Layer — Operator Runbook (Session E)

**Scope:** the Session E personal edge layer over the owned `/api/poke` spine —
edge packets, the raw/graded verified-entry buy route, grading EV, and the
API-vs-external divergence audit. Design:
[`private-price-api.md` → Session E](private-price-api.md#session-e--personal-edge-layer);
lab context: [`money-hypothesis-lab.md`](money-hypothesis-lab.md).

**What this layer is (and is not).** It is **our own decision layer**: an explainable
edge packet per subject, ranked and blocked from the evidence we already own.
PPT/external output is an **audit oracle only** — never a read-path source, never a
number we tune to blindly. Read paths spend **0 credits**. The only surface that can
spend credits is the divergence audit's external mode, and only with an explicit
`--yes` + a configured key.

---

## 0. Golden rules (read before running anything)

- **No auto-buy.** `LIVE_PACKET_ELIGIBLE` / `PAPER_BUY` are tags for human review; the
  edge layer never carts, checks out, logs in, or evades a bot wall.
- **No number without a source.** Every packet field carries provenance
  (`comp_provenance` / `entry_provenance` / `grading_ev`) or is `null` (STOP-class).
- **Read endpoints are 0 credits.** `edge-packets` / `edge-packets/{id}` /
  `edge-summary` never call a billed provider (proven by a failing card-client test).
- **External/billed calls need operator go-ahead.** The divergence audit's external
  mode refuses without `--yes`, prints the estimated spend, and hard-stops on the
  remaining-credit floor.

---

## 1. Read the edge packets (0 credits)

```
# HTTP (served by scanner/web.py):
GET /api/poke/edge-packets            # all packets + summary, score desc
GET /api/poke/edge-packets/<id>       # one packet (404 for an unknown id)
GET /api/poke/edge-summary            # compact roll-up

# CLI:
.venv/Scripts/python.exe -m scanner.poke_api.edge_cli list [--json] [--asset-class raw|graded|sealed] [--decision WATCH|PAPER_BUY|...]
.venv/Scripts/python.exe -m scanner.poke_api.edge_cli show --id <edge_packet_id> [--json]
```

`decision_hint` ∈ `REJECT | WATCH | DATA_NEEDED | PAPER_BUY | LIVE_PACKET_ELIGIBLE`.
`DATA_NEEDED` means no comp (fix the data). `WATCH` with `blockers:
["no verified entry price"]` means: supply a verified entry to activate the buy route.

## 2. Make a raw/graded single buy-shaped (the E verified-entry route)

A raw/graded single is **only** buy-shaped through a verified asset candidate — the
same STOP-class gate as sealed (positive stock + observed price > 0 + `buy_url` +
stock evidence + `stock_checked_at`), plus a precise `asset_key` + identity
(`condition` for raw, `grade_key` for graded) so it can never collide with a sealed
product or a different condition/grade.

Add one with the existing candidate wire (asset fields carry through
`make_candidate`), e.g. via a small script or by appending a record with
`asset_class`/`asset_key`/`condition`|`grade_key` set. A D-era WATCH-with-comp asset
is **never** promoted to live off a comp alone.

## 3. Record a paper decision + outcome (append-only, unified ledger)

```
.venv/Scripts/python.exe -m scanner.poke_api.edge_cli record  --id <edge_packet_id> [--decision D] [--reason R]
.venv/Scripts/python.exe -m scanner.poke_api.edge_cli outcome --id <edge_packet_id> --status SOLD --net 20 [--price P] [--note ...]
```

Because `edge_packet_id` uses the same recipe as `opportunity_id`, these land in the
same `data/poke/paper_decisions.jsonl` and replay through `GET /api/poke/signals`.
Outcome `status` ∈ `SOLD | HELD | PRICE_UP | PRICE_DOWN | EXPIRED | VOID`.

## 4. Grading EV (raw → graded)

Raw packets carry a `grading_ev` block when a graded sibling comp (matched on
`tcgplayer_id` + target `grade_key`) and a gem rate are available. **It blocks on any
missing input** (raw entry, raw comp, graded comp, grading fee, resale fees, gem
rate) — never an invented number. Supply the gem rate as an **operator assumption** on
the asset (`gem_rate` + `gem_rate_source`, e.g. `"operator_assumption 2026-07-05"`).
Grading fee comes from `poke.grading_cost_all_in` (PSA Regular $79.99 all-in; value
tiers paused 2026-06). Grading EV is capped at **PAPER_BUY** (never LIVE) because the
gem rate is an assumption, not verified-data confidence.

## 5. Divergence audit (API vs external — investigate, don't clone)

```
# dry/LOCAL (0 credits, no key): compare our comp vs a recorded ppt_cards observation
.venv/Scripts/python.exe -m scanner.poke_api.edge_cli divergence-audit --local [--products a,b] [--assets k] [--json]

# EXTERNAL (money-class): requires market.api_key AND explicit operator go-ahead
.venv/Scripts/python.exe -m scanner.poke_api.edge_cli divergence-audit --products a,b --assets umbreon_ex_161_psa10 --yes
```

- Without `--yes`, an audit that lists subjects **refuses** and prints the estimated
  spend (1 credit/sealed, 1/raw, 2/graded; `limit=1` pinned).
- External mode **hard-stops** before the next subject if the provider-reported daily
  remaining would fall below **15**.
- Each row is classified: `agree`, `stale_local`, `stale_external`,
  `ask_vs_sold_difference`, `source_policy_difference`, `mapping_error`,
  `confidence_method_difference`, `provider_payload_issue`, `no_external_reference`, or
  `unexplained_material_divergence`. A **material unexplained** divergence **fails** the
  command (exit 1) and must be documented as blocking.
- **Divergences are investigated, not automatically treated as our bug.** Each material
  row states whether ours or theirs is more defensible (e.g. we correctly refuse to
  price off active asks; the config fee model differs from the live collectibles FVF /
  ≥$1,000-card discount → `fee_assumption_difference`). Fix a `mapping_error`
  (wrong `tcgplayer_id`/variant); do **not** tune our comp to match PPT.

## 6. What did NOT happen / follow-ons

- **No live or billed calls** were made building Session E — external divergence mode
  is exercised in tests via injected fake clients only.
- **Dashboard "Edge" card** is a scoped follow-on; the read API (`edge-summary`) + CLI
  are the report surface today.
- **Grading-EV-driven LIVE eligibility** is a follow-on (capped at PAPER_BUY this
  session).
- **eBay Browse** remains ask/candidate context only (active FIXED_PRICE listings,
  never a sold comp); the keyed live stock/price check is still keyset-gated.
