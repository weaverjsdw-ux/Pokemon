# 09 - Verification Delta, 2026-06-15

This note preserves the current repo-truth delta from the 2026-06-15 read-only
audit. It does not replace the service-plan pack; it records corrections that
must be applied before using that pack as an execution contract.

## Verified Current State

- Branch: `main`.
- Last commit: `d2f117d Add scanner state DB fallback`.
- Worktree: dirty. Existing modified files and untracked modules/docs were
  preserved.
- Full test suite: `170 passed in 1.96s` when run outside the sandbox. Sandbox
  runs failed with Windows temp-directory `PermissionError`, not code failures.
- `python -m scanner.coverage`: active coverage is 86%, 19/22 products
  actionable.
- `python -m scanner --safe-demo`: local-only safe demo ran, reported 86%
  active coverage and 20 synthetic inventory rows.
- `scanner.web.safe_demo_payload()`: returned `ok=True`, 22 products, 2 stock
  board sections, summary coverage 86.
- `python -m scanner.verify_ids --offline`: exited nonzero by design because it
  found 6 `SUSPECT_FORMAT` Target IDs and 31 `UNCHECKED` identifiers.

## Corrections To Existing Service-Plan Docs

1. `python -m scanner --check-config` is not public-safe today.
   It prints raw configured location fields. Do not paste or publish its output
   until `scanner/main.py::check_config` redacts or summarizes those fields.

2. `scanner.web._config_summary()` returns `homeAddress` and `workAddress`.
   That is acceptable for a loopback-only local settings form, but not for
   public safe-demo screenshots, shareable diagnostics, or any non-loopback
   API mode. A public-safe mode needs redacted config fields.

3. The service-plan pack says `*.bak` is missing from `.gitignore`; that is no
   longer current. `.gitignore` already includes `*.bak`, scratch text patterns,
   `.tmp_web_*.log`, `.tmp_pytest_*`, DB files, caches, and local config.

4. Existing Phase 0 handoffs that say `--check-config` leaks no secrets are
   wrong. Replace that acceptance check with a redacted command, or fix the
   code first and then document the smoke output.

## Current ID Doctor Risk

The offline verifier flagged these Target IDs as suspect-format because they are
10 digits where the checker expects 7-9 digits:

- `prismatic_evolutions_etb.target_tcin`
- `mtg_marvel_super_heroes_play_booster_box.target_tcin`
- `mtg_marvel_super_heroes_collector_booster.target_tcin`
- `mtg_marvel_super_heroes_draft_night.target_tcin`
- `mtg_marvel_super_heroes_jumpstart_2pack.target_tcin`
- `mtg_marvel_super_heroes_beginner_box.target_tcin`

Treat them as research targets, not confirmed bad IDs, until a live verifier or
manual product-page check confirms identity.

## Web Research Status

- Official `pokemon.com` and `tcg.pokemon.com` pages were blocked by Incapsula
  from this environment, so official release-page verification is partial.
- Accessible current sources support the broad market thesis: continuing supply
  pressure, Chaos Rising scarcity, Pitch Black as a July 17, 2026 watch item,
  and 30th Celebration as a September 16, 2026 high-priority watch item.
- Official API durability claims are backed by Best Buy Developer API docs and
  eBay Browse API docs.

Useful public sources checked:

- https://corporate.pokemon.co.jp/en/aboutus/figures/
- https://www.gamesradar.com/tabletop-gaming/roughly-10-billion-pokemon-cards-were-printed-in-the-last-year-which-goes-to-show-how-bad-the-reseller-situation-is-right-now/
- https://www.gamesradar.com/tabletop-gaming/pokemon-tcg-kicks-off-a-dark-new-chapter-with-pitch-black-expansion/
- https://www.gamesradar.com/tabletop-gaming/pokemon-tcg-introduces-new-card-rarity-with-gorgeous-30th-celebration-collection/
- https://as.com/meristation/noticias/megaaevolucion-caos-crfeciente-calienta-pokemon-tcg-con-estas-dos-cartas-que-desvelamos-en-exclusiva-f202604-n/
- https://bestbuyapis.github.io/api-documentation/#products-api
- https://developer.ebay.com/api-docs/buy/browse/resources/item_summary/methods/search

## Revised First Moves

1. Fix/redact `--check-config` and public-safe config payloads before using any
   smoke output in docs, GitHub issues, PRs, or public demos.
2. Commit the existing modules/docs as a reviewed baseline only after confirming
   no DB, backup, cookie, local config, or scratch files are staged.
3. Keep the first service-grade feature PR focused on notification failure
   handling: `raise_for_status`, retry once, and local alert-log fallback.
4. Add persisted heartbeat/liveness next; the dashboard still only knows the
   in-process runner state.
