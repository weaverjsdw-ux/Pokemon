# Pokémon TCG Restock Scanner

Polls retailer stock endpoints for sealed Pokémon TCG product and fires a
Discord alert when something pops at a store along your home↔work commute.

**Scope of this build**
- Big-box: Target, Walmart, GameStop
- Online-only: Pokémon Center (Best Buy/Costco/Sam's wired in but disabled by default)
- Route-aware: only alerts for stores within N miles of your driving route, not just radial from one point
- Polite by default: 3-minute poll interval with jitter, identifies itself with a real User-Agent, dedupes via SQLite so you don't get hammered with the same alert
- Local-first: addresses + webhook live in `config.yaml` which is gitignored
- Aggressive polling, scraping behind login walls, or distributed/proxy networks if not against ToS

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

Either run the wizard (recommended for first-time setup):

```bash
python -m scanner --init
```

…or copy the example and edit by hand:

```bash
cp config.example.yaml config.yaml
```

Either way you'll end up with a `config.yaml` containing:
- `locations.home` and `locations.work` — full addresses or zips work
- `route_radius_miles` — default 4
- `timezone` — IANA name; controls quiet hours and (Phase 2) drop-window awareness
- `discord_webhook` — see walkthrough below; any string field accepts `${ENV_VAR}` so you can keep secrets out of the file
- Enable/disable retailers as you like

`config.yaml` is in `.gitignore` so your addresses and webhook never get committed.

### 3. Discord webhook (30-second walkthrough)

1. Open Discord and pick a server you own. If you don't have one, click the **+** button in the server list and "Create My Own → For me and my friends" (takes 10 seconds).
2. **Right-click the channel** you want alerts in → **Edit Channel**.
3. Left sidebar → **Integrations** → **Webhooks** → **New Webhook**.
4. Give it a name (e.g. "Pokémon Scanner"), optionally a picture.
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
walmart: 5 stores in corridor
  ...
```

If that looks right, kick off the real loop:

```bash
python -m scanner
```

Or one pass and exit:

```bash
python -m scanner --once
```

### 6. Run in Docker (optional)

If you'd rather not babysit a Python install or want the scanner to survive reboots:

```bash
docker compose up -d
docker compose logs -f scanner
```

`compose.yaml` bind-mounts `config.yaml`, `data/`, and `logs/` from the host so state survives container rebuilds. Secrets can be passed via `.env` (`DISCORD_WEBHOOK=...`, `BESTBUY_API_KEY=...`) instead of being baked into the config.

---

## Adding products / new sets

`data/products.yaml` is the catalog. Each entry needs the retailer-specific ID for products you want to track at that retailer. To add a new ID:

- **Target**: open the product page on target.com, find the URL like `/p/.../A-93954435`. The number after `A-` is the `target_tcin`.
- **Walmart**: open the product page on walmart.com, URL like `/ip/.../15433520586`. The trailing number is `walmart_item_id`.
- **Best Buy**: SKU is the digits in the URL `/site/.../6566943.p`.
- **GameStop**: URL like `/p/pokemon-tcg-...`. The slug after `/p/` is `gamestop_pid`.
- **Pokémon Center**: URL like `pokemoncenter.com/product/...`. The path after `/product/` is `pokemoncenter_slug`.

Leave fields blank to skip that retailer for that product. The catalog ships with the most-tracked recent sets pre-populated where IDs were stable; most slots are blank — fill them in for the SKUs you care about.

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
- **Coverage gaps**: Walmart's per-store stock API is unreliable; this build surfaces Walmart **online** restocks instead, which is still useful (you can ship-to-store for free). When their store API works again, the Walmart adapter is the place to add it.
- **Local game stores (LGS)**: not auto-discoverable — every LGS uses a different POS (Square, Crystal Commerce, BinderPOS, Shopify). The cleanest path is to follow your local stores on Instagram/Discord directly; auto-scraping them is high-effort, low-yield, and antagonizes the store owners you actually want to be friendly with.
- **Best Buy**: free developer API at https://developer.bestbuy.com — get a key, set `retailers.bestbuy.api_key`, flip `enabled: true`. Adapter scaffolding is in place; SKU lookups in `data/products.yaml` need to be filled in.
- **What to do when something hits**: alerts include a direct URL — tap it, add to cart, check out. That's the entire workflow. No bot will do this faster than a person who's already at their phone.

---

## Why this approach (and not a "leaked" tool)

Every successful Pokémon restock tracker (BrickSeek, HotStock, NowInStock, the major Discords) does some combination of these four things:

1. **Poll documented or de-facto-public retailer stock endpoints by SKU + zip/store** — exactly what this scanner does.
2. **Watch product-page state changes** for online drops.
3. **Mirror community signal** from Discord/Reddit/X where humans on the ground confirm shelf restocks.
4. **Notify fast.**

The "edge" isn't a leaked guide. It's coverage (more SKUs × more retailers × more stores) and latency (alert → tap-to-buy in <30s). This codebase is built to be extended on both axes.
