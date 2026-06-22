# TCG MSRP Restock Scanner

This project exists because I rip packs for a hobby. I buy sealed Pokemon TCG
and Magic: The Gathering products to open them, play, collect, and enjoy the
release cycle. The point of tracking MSRP is protection from inflated resale
pricing, not resale optimization.

See [DOCTRINE.md](DOCTRINE.md) and [ADVISOR_ROLE.md](ADVISOR_ROLE.md) before
making roadmap, pricing, or product-coverage decisions.

Polls retailer stock endpoints for sealed TCG product and fires a Discord alert
when something pops at a store along your home/work commute.

**Scope of this build**
- Route-aware store checks: Target, Costco after you add `costco_item_id` IDs, and GameStop after you add `gamestop_pid` IDs and enable it
- Online checks: Walmart by default; Best Buy with an API key; Pokemon Center after you add `pokemoncenter_slug` IDs and enable it
- Placeholders: Sam's is listed in config but disabled because live checks are not implemented yet
- Route-aware mode only alerts for supported store retailers within N miles of your driving route, not just radial from one point
- Polite by default: 3-minute poll interval with jitter, identifies itself with a real User-Agent, dedupes via SQLite so you don't get hammered with the same alert
- Local-first: addresses + webhook live in `config.yaml` which is gitignored
- No aggressive polling, scraping behind login walls, or distributed/proxy networks

**Not in scope (and won't be)**
- Auto-checkout / cart bots (against every retailer's ToS, gets accounts banned, doesn't actually help you)
- Anything labeled "leaked" — there are no secret guides; the community is open and information moves fast.

---

## Setup

### 1. Install

**macOS / Linux (bash/zsh):**

```bash
git clone https://github.com/weaverjsdw-ux/Pokemon.git
cd Pokemon
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

**Windows (PowerShell):**

```powershell
git clone https://github.com/weaverjsdw-ux/Pokemon.git
cd Pokemon
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If `python` isn't found, install it from python.org or `winget install -e --id Python.Python.3.12` (the Microsoft Store stub does not count). If `Activate.ps1` is blocked, run once:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

**Windows (cmd.exe):** same as PowerShell, but activate with `.venv\Scripts\activate.bat`.

### 2. Config

```bash
cp config.example.yaml config.yaml
```

Open `config.yaml` and fill in:
- `locations.home` and `locations.work` — full addresses or zips work
- `route_radius_miles` — default 4; this is the corridor distance from your
  home/work route, not a generic "search every store within X miles" setting
- `discord_webhook` — see walkthrough below
- Enable/disable retailers as you like

`config.yaml` is in `.gitignore` so your addresses and webhook never get committed.

### 3. Discord webhook (30-second walkthrough)

1. Open Discord and pick a server you own. If you don't have one, click the **+** button in the server list and "Create My Own → For me and my friends" (takes 10 seconds).
2. **Right-click the channel** you want alerts in → **Edit Channel**.
3. Left sidebar → **Integrations** → **Webhooks** → **New Webhook**.
4. Give it a name (e.g. "TCG MSRP Scanner"), optionally a picture.
5. Click **Copy Webhook URL**.
6. Paste that URL into `config.yaml` as `discord_webhook`.

Done — alerts will appear as embed messages in that channel.

### 4. (Optional) Mobile push backup

Discord notifications can be slow to fire on phones if the app is backgrounded. As a backup channel, set `ntfy_topic` to any unique string (e.g. `pkmn-restock-yourname-xyz`), then install the [ntfy](https://ntfy.sh) app on your phone and subscribe to that topic. Free, no account needed.

### 5. Run

Sanity-check the install first (no network calls — confirms `config.yaml` parses and the product catalog loads):

```bash
python -m scanner --check-config
```

Then dry run — confirms geocoding, routing, and store discovery without polling stock:

```bash
python -m scanner --dry-run
```

You should see something like:

```
target: 3 stores in corridor
  Target #1234 — Springfield, IL  (0.42 mi from route)
  Target #5678 — Bloomington, IL  (3.81 mi from route)

walmart (online-only)
```

If you want to verify the CLI and dashboard wiring without sending your
home/work addresses to any geocoder, router, or retailer endpoint, use the
local-only safe demo:

```bash
python -m scanner --safe-demo
```

Safe demo uses synthetic stores and out-of-stock rows. It is not a live stock
check; it exists so you can validate coverage, board layout, source labels, and
the UI without transmitting private location data.

If that looks right, kick off the real loop:

```bash
python -m scanner
```

Or one pass and exit:

```bash
python -m scanner --once
```

### Local UI

The scanner also ships with a local web UI. It reads `config.yaml`, can save the
same local config file, shows the exact products and retailer IDs being scanned,
groups the latest product statuses by store or online retailer, and calls the
same scanner code paths as the CLI. When `config.yaml` is valid, the UI starts
the interval scanner automatically so it keeps checking on the configured
cadence. Products confirmed out of stock show as **Out** rather than
**Unknown** for every supported retailer.

```bash
python -m scanner.web
```

Open <http://127.0.0.1:8765>. The UI is local-only by default and does not
expose the scanner outside your machine unless you run it with a different host.
Use `python -m scanner.web --no-autostart` if you only want the dashboard
without starting the interval scanner.

The dashboard also surfaces three things that make it worth opening even when
nothing is live:

- **Active coverage** — what share of your tracked products are actually
  actionable (have an ID for an enabled, supported retailer). A pretty product
  list with no IDs is decorative, not a scanner.
- **Source health** — per retailer: healthy / degraded / down, last successful
  check, last HTTP status, and *why* it's quiet — genuinely out of stock vs.
  blocked vs. parser returned nothing vs. network error. These used to all look
  identical.
- **Store discovery diagnostics** — shows how route radius was applied: how
  many route sample centers were queried, how many candidate stores came back,
  how many survived the corridor filter, and which enabled sources ignore
  radius because they are online-only.
- **MSRP + resale confidence** — product cards show catalog MSRP plus a cached
  rough resale estimate. The cache refreshes every four hours by default. The
  dashboard labels each estimate by source confidence, shows the premium over
  MSRP when available, and adds `*` when the number needs manual verification.
  Official eBay credentials are preferred for active listing asks; fallback
  estimates can use public eBay search or PriceCharting market summaries.
- **Recently in stock** — restock memory per product/store: when it was last
  seen in stock and how many distinct restocks have been logged.
- **Add Product ID** — paste a retailer product URL or bare ID and the UI writes
  the matching field into `data/products.yaml` through the same parser used by
  `python -m scanner.add_id`.

---

## Coverage & health from the CLI

```bash
python -m scanner.coverage      # active-coverage score + per-retailer ID counts
python -m scanner --check-config # now also prints the coverage score
```

Coverage is the single best signal of whether this tool is doing anything. Drive
it up by adding IDs (below) for current sets — the catalog ships intentionally
sparse so it never carries stale or guessed identifiers.

---

## Running unattended (Windows)

A scanner that only runs while a terminal is open isn't much of a scanner. The
included script registers a Windows Scheduled Task that launches the scanner at
logon (no console window) and restarts it if it exits. It is **dry-run by
default** — it prints the plan and changes nothing until you pass `-Install`:

```powershell
# See the plan (no changes):
powershell -ExecutionPolicy Bypass -File scripts\install-scheduled-task.ps1

# Install the background scan loop:
powershell -ExecutionPolicy Bypass -File scripts\install-scheduled-task.ps1 -Install

# Or install the local dashboard instead; remove either with -Remove:
powershell -ExecutionPolicy Bypass -File scripts\install-scheduled-task.ps1 -Install -Web
powershell -ExecutionPolicy Bypass -File scripts\install-scheduled-task.ps1 -Remove
```

---

## Adding products / new sets

`data/products.yaml` is the catalog. Each entry needs the retailer-specific ID for products you want to track at that retailer. To add a new ID:

- **Target**: open the product page on target.com, find the URL like `/p/.../A-93954435`. The number after `A-` is the `target_tcin`.
- **Walmart**: open the product page on walmart.com, URL like `/ip/.../15433520586`. The trailing number is `walmart_item_id`. Skip third-party marketplace listings unless you explicitly want scalper-price alerts.
- **Best Buy**: SKU is the digits in the URL `/site/.../6566943.p`. Prefer products sold by Best Buy; marketplace seller SKUs can point at inflated third-party listings.
- **Costco**: parent item number is in URLs like `/pokemon-foo.product.4000313298.html`. The number after `.product.` is `costco_item_id`. The adapter resolves child item numbers before checking warehouse inventory.
- **GameStop**: URL like `/p/pokemon-tcg-...`. The slug after `/p/` is `gamestop_pid`.
- **Pokemon Center**: URL like `pokemoncenter.com/product/...`. The path after `/product/` is `pokemoncenter_slug`.

Or skip the copy/paste: paste the product-page URL and let the scanner pull the
id out and write it into `data/products.yaml` for you (comments and formatting
are preserved — only the one field line is rewritten):

```bash
python -m scanner.add_id target prismatic_evolutions_etb https://www.target.com/p/-/A-93954435
python -m scanner.add_id walmart prismatic_evolutions_etb 15433520586   # a bare id works too
```

Leave fields blank to skip that retailer for that product. `--check-config`
fails if you enable a retailer but the selected products have no IDs for it,
so either fill in the IDs or keep that retailer disabled.

Use `products: all_tcg` or `products: all_sealed` to track every catalog row,
`products: pokemon` for Pokemon-only, `products: magic` for Magic-only, or an
explicit list of product keys when you want a tight watchlist.

Each product can also carry pricing context:

- `msrp` is the static retail reference shown in the dashboard and alerts.
- `resale_query` is the market search phrase used for the rough resale estimate.
  The scanner prefers the official eBay Browse API when you set either
  `resale_prices.ebay.browse_api_token` or `resale_prices.ebay.client_id` plus
  `client_secret` in your gitignored `config.yaml`. Browse API results are
  active fixed-price asking comps, not completed sales. Without credentials it
  tries public eBay search and PriceCharting fallback rows, and the API/UI label
  low-confidence or high-premium results with a verification `*`.

---

## How it works

```
addresses
  ↓ Nominatim (free geocoder)
(home_lat, home_lng), (work_lat, work_lng)
  ↓ OSRM (or Google) directions
route polyline
  ↓ haversine point-to-segment filter
candidate stores within N miles of route
  ↓ retailer adapters
(retailer × product × store) stock checks
  ↓ SQLite dedupe (status change or 6h cooldown)
Discord webhook + optional ntfy + console
```

Each retailer is a self-contained module in `scanner/retailers/`. To add a new retailer, subclass `Retailer` with `find_stores()` + `check()` and register it in `scanner/retailers/__init__.py`.

---

## Operational notes

- **Polling cadence**: default 3 min + jitter. Don't lower this past ~60s — these are public site endpoints, not real APIs, and hammering them is what gets them locked down for everyone.
- **Rate-limit backoff**: individual stock checks retry HTTP 429 (Too Many Requests) and transient 5xx with exponential backoff, honoring the server's `Retry-After` header when present, instead of silently dropping that check for the cycle.
- **Coverage gaps**: Walmart's per-store stock API is unreliable; this build surfaces Walmart **online** restocks instead, which is still useful (you can ship-to-store for free). When their store API works again, the Walmart adapter is the place to add it.
- **Local game stores (LGS)**: not auto-discoverable — every LGS uses a different POS (Square, Crystal Commerce, BinderPOS, Shopify). The cleanest path is to follow your local stores on Instagram/Discord directly; auto-scraping them is high-effort, low-yield, and antagonizes the store owners you actually want to be friendly with.
- **Best Buy**: free developer API at https://developer.bestbuy.com — get a key, set `retailers.bestbuy.api_key`, fill `bestbuy_sku` values in `data/products.yaml`, then flip `enabled: true`.
- **Costco**: route-aware warehouse checks are implemented through Costco's warehouse locator, product summary, and inventory availability endpoints. Add real `costco_item_id` values before enabling it; `--check-config` fails if Costco is enabled with no Costco IDs.
- **Sam's Club**: disabled placeholder only. If you enable it, `--check-config` fails until a real adapter is implemented.
- **What to do when something hits**: alerts include a direct URL — tap it, add to cart, check out. That's the entire workflow. No bot will do this faster than a person who's already at their phone.

---

## Why this approach (and not a "leaked" tool)

Every successful TCG restock tracker (BrickSeek, HotStock, NowInStock, the major Discords) does some combination of these four things:

1. **Poll documented or de-facto-public retailer stock endpoints by SKU + zip/store** — exactly what this scanner does.
2. **Watch product-page state changes** for online drops.
3. **Mirror community signal** from Discord/Reddit/X where humans on the ground confirm shelf restocks.
4. **Notify fast.**

The "edge" isn't a leaked guide. It's coverage (more SKUs × more retailers × more stores) and latency (alert → tap-to-buy in <30s). This codebase is built to be extended on both axes.
