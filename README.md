# Pokémon TCG Restock Scanner

Polls retailer stock endpoints for sealed Pokémon TCG product and fires
alerts when something pops at a store along your home↔work commute (or
online). Discord, ntfy, Pushover, email, and arbitrary webhooks supported.

**Coverage**
- Big-box: Target, Walmart, GameStop, Best Buy, Barnes & Noble, Meijer, Five Below
- Online: Pokémon Center, Amazon (soft signal), TCGPlayer, Costco, Sam's Club
- LGS via Shopify + Crystal Commerce (generic adapters cover many stores)
- Community signal: Reddit (and experimental X/Twitter via Nitter)

**Polite by default**
- 3-minute poll interval with jitter; adaptive cadence around known drop windows
- Real browser User-Agent, per-retailer health tracking, per-hour request budget
- SQLite dedupe so you don't get the same alert twice
- Local-first: addresses + secrets live in `config.yaml` (gitignored) or env vars
- Aggressive polling / login scraping / distributed proxies fine *only when not against ToS* — see [`docs/retailer-tos.md`](docs/retailer-tos.md)

**Not in scope (and won't be)**
- Auto-checkout / cart bots (against every retailer's ToS, gets accounts banned, doesn't actually help you)
- Anything labeled "leaked" — there are no secret guides; the community is open and information moves fast.

---

## Quickstart

```bash
git clone https://github.com/weaverjsdw-ux/Pokemon.git
cd Pokemon
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m scanner --init           # interactive setup wizard
python -m scanner --check-config   # validate, no network
python -m scanner --dry-run        # confirm route + store discovery
python -m scanner                  # run the loop
```

Windows (PowerShell) is the same with `.\.venv\Scripts\Activate.ps1` instead of `source` — see [`docs/configuration.md`](docs/configuration.md) for details, ExecutionPolicy notes, and Docker.

### Discord webhook (30 seconds)

1. Open Discord and pick a server you own. If you don't have one, click the **+** button in the server list and "Create My Own → For me and my friends".
2. **Right-click the channel** you want alerts in → **Edit Channel** → **Integrations** → **Webhooks** → **New Webhook**.
3. **Copy Webhook URL**. Paste into `config.yaml` as `discord_webhook` (or set `DISCORD_WEBHOOK` and use `"${DISCORD_WEBHOOK}"`).

---

## Run modes

| Command | What it does |
|---|---|
| `python -m scanner --init` | Interactive setup wizard, writes `config.yaml`. |
| `python -m scanner --check-config` | Validate config + catalog, no network. |
| `python -m scanner --dry-run` | Geocode, route, discover stores. No stock checks. |
| `python -m scanner --once` | One scan pass and exit. |
| `python -m scanner` | Long-running loop with jitter + adaptive cadence. |
| `python -m scanner.dashboard` | Read-only web UI at `http://127.0.0.1:8765/`. |
| `python -m scanner.tools.extract_sku <url>` | Paste a product URL, get the right `products.yaml` field. |
| `docker compose up -d` | Containerized run; survives reboots. |

For systemd / launchd / Windows Task Scheduler templates see [`deploy/README.md`](deploy/README.md).

---

## Docs

| Doc | Covers |
|---|---|
| [`docs/configuration.md`](docs/configuration.md) | Every `config.yaml` field. The deep dive. |
| [`docs/retailer-tos.md`](docs/retailer-tos.md) | What's permitted per retailer; contributor checklist for new adapters. |
| [`deploy/README.md`](deploy/README.md) | systemd / launchd / Windows Task Scheduler / Docker. |

---

## How it works

```
addresses
  ↓ Nominatim → Mapbox → Google (fallback chain)
(home_lat, home_lng), (work_lat, work_lng)
  ↓ OSRM (or Google) directions
route polyline
  ↓ haversine point-to-segment filter
candidate stores within N miles of route
  ↓ retailer adapters (parallel-safe HTTP client w/ retry, health, budget)
(retailer × product × store) stock checks
  ↓ priority gate + quiet hours + price filter + SQLite dedupe
Discord webhook + ntfy + Pushover + email + custom webhooks + dashboard
```

Each retailer is a self-contained module in `scanner/retailers/`. Adding
one is small — subclass `Retailer` with `find_stores()` + `check()` and
register in `scanner/retailers/__init__.py`. See the existing adapters
for the pattern, and [`docs/retailer-tos.md`](docs/retailer-tos.md) for
the policy bar a new adapter has to meet.

Community-signal sources live in `scanner/sources/`; same shape.

---

## Adding products

`data/products.yaml` is the catalog. Each entry maps a friendly name to per-retailer SKUs and optional metadata (priority, mute, MSRP, max-price, image, multi-variant lists).

Easiest way to fill in a new SKU: paste the retailer URL into the helper.

```bash
python -m scanner.tools.extract_sku https://www.target.com/p/.../A-93954435
# →   target_tcin: "93954435"
```

Recognized retailers: target, walmart, bestbuy, gamestop, pokemoncenter, costco, samsclub, amazon, tcgplayer, barnesnoble, meijer, fivebelow.

Each per-retailer ID field accepts either a string or a list, so one product entry can track multiple SKU variants (alt-cover ETBs, regional packagings).

---

## Operational notes

- **Polling cadence**: default 3 min + jitter. Drop windows in config can override during known restock periods. Don't lower below ~30s — these are public site endpoints, not real APIs.
- **Endpoint shape probe**: a nightly GitHub workflow (`.github/workflows/endpoint-shape.yml`) hits each retailer with a known SKU and fails CI if the response shape changes. Catches silent breakage before the user does.
- **Logs**: `logs/scanner.log` (rotated, 5MB × 5). `LOG_LEVEL=DEBUG` for verbose.
- **State**: `data/state.db`. Automatic daily backup to `data/backups/`, last 7 retained. `state.restore_latest()` to roll back.
- **Best Buy**: free developer API at https://developer.bestbuy.com — get a key, set `BESTBUY_API_KEY`, flip `enabled: true`. The only retailer where aggressive (within their documented rate limit) polling is unambiguously permitted.
- **What to do when something hits**: alerts include a direct URL + (where available) a click-to-cart deep link. That's the entire workflow. No bot will do this faster than a person who's already at their phone.

---

## Why this approach (and not a "leaked" tool)

Every successful Pokémon restock tracker (BrickSeek, HotStock, NowInStock, the major Discords) does some combination of these four things:

1. **Poll documented or de-facto-public retailer stock endpoints by SKU + zip/store** — exactly what this scanner does.
2. **Watch product-page state changes** for online drops.
3. **Mirror community signal** from Discord/Reddit/X where humans on the ground confirm shelf restocks.
4. **Notify fast.**

The "edge" isn't a leaked guide. It's coverage (more SKUs × more retailers × more stores) and latency (alert → tap-to-buy in <30s). This codebase is built to be extended on both axes.
