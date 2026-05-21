# Configuration reference

Every field in `config.yaml`, what it does, and what valid values look
like. `config.example.yaml` is the canonical template; copy it (or run
`python -m scanner --init`) and edit. The file is gitignored.

Any string value supports `${VAR}` or `${VAR:-default}` interpolation,
so you can keep secrets in env vars and reference them from the file.

---

## Locations + routing

```yaml
locations:
  home: "123 Main St, Springfield, IL 62701"
  work: "456 Market St, Springfield, IL 62702"

route_radius_miles: 4

routing:
  engine: osrm           # "osrm" (free) | "google" (needs key)
  google_api_key: ""     # only used when engine=google
```

`home` and `work` are geocoded once and cached in `data/geocode.cache.json`. Fallback chain: Nominatim → Mapbox (`MAPBOX_TOKEN`) → Google (`GOOGLE_API_KEY`). Any provider being down won't block boot.

The home→work route polyline is filtered to stores within `route_radius_miles`. The route is computed both ways (forward + reverse) so one-way detours work.

---

## Time zone + heartbeat

```yaml
timezone: America/Chicago      # IANA name; controls quiet hours + drop windows

heartbeat_seconds: 21600       # 6 hours; 0 disables
```

Heartbeat posts a status summary (uptime, passes, alerts fired, per-retailer health, requests/hour) to your Discord channel so a silently-stuck scanner can't go unnoticed. First heartbeat fires after `heartbeat_seconds` from launch (not on startup).

---

## Retailers

```yaml
retailers:
  target:        { enabled: true }
  walmart:       { enabled: true }
  bestbuy:       { enabled: false, api_key: "${BESTBUY_API_KEY:-}" }
  pokemoncenter: { enabled: true }
  gamestop:      { enabled: true }
  costco:        { enabled: false }
  samsclub:      { enabled: false }
  amazon:        { enabled: false }
  tcgplayer:     { enabled: false }
  barnesnoble:   { enabled: false }
  meijer:        { enabled: false }
  fivebelow:     { enabled: false }

  lgs_shopify:
    enabled: false
    stores:
      - { name: "Bob's TCG",   domain: "bobs-tcg.myshopify.com" }
      - { name: "Card Castle", domain: "cardcastle.com" }

  lgs_crystalcommerce:
    enabled: false
    stores:
      - { name: "City Cards", domain: "citycards.crystalcommerce.com" }
```

Each adapter can take `api_key` or arbitrary extra config. See [`docs/retailer-tos.md`](retailer-tos.md) for per-retailer policy.

---

## Polling cadence

```yaml
poll_interval_seconds: 180         # default 3 min + jitter

drop_windows:
  - retailers: [target]
    days: [tue, fri]
    start: "06:00"
    end:   "10:00"
    poll_interval_seconds: 60
  - retailers: [pokemoncenter]
    days: [mon, tue, wed, thu, fri]
    start: "13:00"
    end:   "13:30"
    poll_interval_seconds: 30
```

Drop windows override the global interval when any window matches an enabled retailer. The smallest interval wins. Times are in `timezone`. Wrap midnight is fine (start > end).

---

## Alert routing

```yaml
discord_webhook: "${DISCORD_WEBHOOK}"

ntfy_topic: "pkmn-restock-johnny"

# Optional: route each priority tier to its own channel
priority_channels:
  must_have:    "https://discord.com/api/webhooks/.../must-have"
  nice_to_have: ""    # falls back to discord_webhook
  fyi:          "https://discord.com/api/webhooks/.../fyi"

# Optional: Pushover for native push with priority + sound
pushover:
  user_key:  "${PUSHOVER_USER:-}"
  app_token: "${PUSHOVER_TOKEN:-}"
  priority:  0          # -2..2; 1 = bypass quiet hours on the phone
  sound:     "magic"

# Optional: email fallback over SMTP
email:
  smtp_host:     ""
  smtp_port:     587
  smtp_starttls: true
  smtp_user:     ""
  smtp_password: "${SMTP_PASSWORD:-}"
  from:          ""
  to:            []

# Optional: post a JSON dump to arbitrary URLs (IFTTT, Zapier, Home Assistant)
outbound_webhooks: []
```

All channels run independently per alert. Any one failing is logged but doesn't abort the rest.

---

## Quiet hours

```yaml
quiet_hours:
  start: "23:00"
  end:   "07:00"
```

Suppresses `nice_to_have` and `fyi` alerts during the window. `must_have` alerts always go through. Empty/missing start or end disables. Timezone is `timezone` above.

---

## Price filters

```yaml
price_filter:
  only_at_or_near_msrp: false
  msrp_multiplier: 1.10        # allow up to 10% over MSRP
```

When on, drops any alert whose listed price exceeds `msrp * msrp_multiplier` for products that declare an MSRP. Unparseable prices abstain (better to alert than miss). Per-product `max_price: "$X"` adds a hard ceiling regardless of MSRP.

---

## Community signal sources

```yaml
community_signal:
  reddit:
    enabled: false
    subs:    [PokemonTCG, PokeInvesting]
    max_age_seconds: 3600
    # keywords:  [restock, "in stock"]
    # retailers: [target, walmart]

  nitter:                       # experimental — X/Twitter via Nitter RSS
    enabled: false
    instance: ""                # e.g. https://nitter.privacydev.net
    accounts: []                # ["restockalert", "pokemonrestock"]
    max_age_seconds: 3600
```

Posts that match restock keywords (and for Reddit, also a retailer name) are surfaced to Discord as `COMMUNITY:` status messages. Deduplicated by source+post id across passes.

---

## Product selection

```yaml
products: all_sealed             # default — every key in data/products.yaml
# products: [prismatic_evolutions_etb, journey_together_etb]
```

Set to a list of product keys to scan only those.

Per-product fields (in `data/products.yaml`):

| Field | What |
|---|---|
| `name` | Display name in alerts. |
| `set` / `type` | Optional grouping shown in the dashboard. |
| `priority` | `must_have` / `nice_to_have` / `fyi`. Default `nice_to_have`. |
| `mute` | `true` short-circuits all alerts for the product. |
| `msrp` | `"$49.99"`. Used by price filter and shown in embeds. |
| `max_price` | `"$59.99"`. Per-product price ceiling. |
| `image_url` | Thumbnail in Discord embeds. |
| `<retailer>_<id>` | The retailer-specific SKU. Accepts a string or a list. |
| `lgs_shopify_slugs` | `{ "store.com": "slug" }` map for the Shopify LGS adapter. |
| `lgs_crystalcommerce_paths` | `{ "store.com": "products/path" }` map. |

---

## Logging

```bash
LOG_LEVEL=DEBUG python -m scanner            # one shot
python -m scanner --log-level WARNING        # CLI override
```

Logs go to stdout *and* to `logs/scanner.log` (rotated, 5MB × 5). Container runs that can't write to the filesystem fall back to stdout-only.
