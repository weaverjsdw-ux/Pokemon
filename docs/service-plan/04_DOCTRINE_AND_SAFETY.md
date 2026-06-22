# 04 — Operating Doctrine & Safety

*The boundary matrix a coding agent consults before adding any source or feature. These are **your** lines (from DOCTRINE.md), plus the engineering and anti-scalper reasoning behind them. The goal: don't be a scalper, don't be abusive, don't leak secrets, and don't depend on things that break. When in doubt, classify up (toward "never" / "ask first").*

---

## What we hold to

This tool polls public product endpoints for personal, single-user use — that's fine and intended. The lines we actually hold ourselves to:

- **Not behaving like scalper infrastructure** (no auto-checkout, no proxies/distributed polling, no queue-jumping ahead of other hobby buyers).
- **Not being abusive** (polite cadence, honor backoff, single machine/IP).
- **Not leaking secrets or private location data.**
- **Not depending on fragile/undurable sources without knowing it** (see [02](02_MARKET_AND_RETAILER_MAP.md)/[03](03_SERVICE_STRATEGY.md) for the durability view).

---

## Boundary matrix

| Area | ✅ Allowed | ⚠️ With care | ⛔ Never |
|---|---|---|---|
| **Data sources** | Any public product endpoint, polite, single-user. Official APIs (Best Buy, eBay) preferred for **durability**, not virtue. | Heavier polling on one hot product during a release window (stay ≥60s) | Powering a **shared/hosted/monetized** service off scraped endpoints (that's scalper-scale infra) |
| **Polling cadence** | ≥180s default; honor `Retry-After`; exponential backoff | Tighten toward the 60s floor for a single release-window product | Sub-60s hammering; ignoring 429s; retry storms on error |
| **Polling architecture** | One machine, one IP, sequential polite checks | — | Proxies, proxy rotation, distributed/multi-node polling, residential IP pools |
| **Auto-checkout / cart** | Alert the human with a tap-to-buy URL | — | Any cart automation, auto-add, or auto-purchase |
| **Login walls / accounts** | Read your own account pages manually | — | Automating or scraping behind authentication; storing anyone else's account data |
| **Queues / invite systems** (Pokémon Center, Best Buy) | **Alert** the user that a drop/queue is live so *they* can enter | Detect a public page-status change (waitlist→buy) | Auto-entering queues, holding multiple positions, gaming invite selection, multi-account — this is **queue-jumping ahead of other openers** (anti-scalp doctrine) |
| **CAPTCHA / bot walls** | Stop and tell the user | — | Solving, bypassing, or outsourcing CAPTCHAs |
| **Credentials / secrets** | Read keys/webhook from `config.yaml` or env | — | Logging, printing, transmitting, or committing secrets |
| **Webhooks** | Discord/ntfy to the user's own channel | — | Exposing webhook URLs in any artifact, log, screenshot, or commit |
| **Addresses / route coords** | Stored only in local `config.yaml`; redacted in logs | — | Printing/exposing addresses or route polylines anywhere |
| **Hosting / privacy** | A no-user-data catalog/release feed (Option 3) | — | Hosting a scanner that custodies user addresses/webhooks/keys |
| **Affiliate links** | eBay/Best Buy/Walmart affiliate links **if disclosed** | — | Hidden/undisclosed affiliate injection |
| **Resale data** | Distortion **context** (premium-over-MSRP), labeled | Low-confidence/asking estimates flagged `*` | Framing resale as a flip target; ranking by profit |
| **Marketplace sellers** | Distinguish first-party retail from marketplace | Show marketplace price as context only | Alerting on scalper/marketplace listings as "restocks" |
| **Notifications** | Restock alerts to the user's own channels | Multi-channel (Discord + ntfy) | Spamming; alerting third parties; selling alert access |
| **User data storage** | Local SQLite + caches, minimal | — | Telemetry phoning home; cloud-syncing secrets |
| **Public demo data** | Synthetic via `--safe-demo` | — | Real addresses/store IDs/coords in any public material |

> The single throughline: **anything that makes the tool look or behave like the scalper bots the community is fighting is a hard "never."** Polite personal monitoring is not that.

---

## Service privacy model

- **Local-first.** Addresses, webhook, API keys, and route coordinates live only in the gitignored `config.yaml`. They're transmitted only to the service that strictly needs them (geocoder ← address; router ← coords; webhook host ← alert).
- **Redaction by default.** Logs and dashboard already redact coordinates and query strings (`_safe_log_text`, `_redact_query_strings`). Keep this on every new surface.
- **No phone-home.** No telemetry/analytics/crash reporting to a remote endpoint without explicit opt-in.
- **Loopback by default.** Dashboard binds `127.0.0.1`. A non-loopback `--host` must require a token (ask-first).

## Secret-handling rules

1. Secrets come from `config.yaml` or env only; never hardcoded. (The scraped Target `REDSKY_KEY` is a legacy exception — keep it env-overridable and prefer the durable Best Buy path.)
2. Never print/log/return a secret value. `--check-config` prints "set / not set" only (already correct).
3. `.gitignore` must cover `config.yaml`, `*.db*`, `*.bak`, cookies, logs (add `*.bak` — currently missing).
4. No secret in any doc, issue, screenshot, demo, or commit. Use `--safe-demo` for public material.

## Data retention rules

- **SQLite state:** keep restock history (small, useful) but local-only; never commit `*.db`/`*.bak`.
- **Caches:** TTL-bound the geocode cache (add ~30-day expiry); resale already refreshes every 4h.
- **Logs:** cap/rotate; the repo has multi-MB `.tmp_web_*.err.log` files — cap + keep ignored.
- **Provenance sidecar:** safe to commit (URLs + verdicts, no secrets).

---

## "Never implement" list

1. Auto-checkout / cart automation / purchase bots.
2. Proxy rotation, distributed/multi-node polling, residential IP pools.
3. Login-wall or authenticated-page scraping.
4. CAPTCHA solving/bypass; queue/invite circumvention (= jumping ahead of other openers).
5. Hosted multi-user scanner custodying user secrets.
6. Any feature that ranks or optimizes for **resale profit** / flipping.
7. Alerting on marketplace/scalper listings as if they were retail restocks.
8. Sub-60s polling or ignoring `Retry-After`/429.
9. Telemetry that transmits user data without explicit opt-in.
10. Exposing addresses, webhooks, keys, route coordinates, or `config.yaml` contents anywhere.

## "Ask operator first" list

1. Adding a **new live-scan source** — note its durability ([02/H]) and confirm it crosses no "never" line.
2. Changing the **default source mode** or the polling floor.
3. Binding the dashboard to a **non-loopback host** (needs token auth).
4. Adding **affiliate links** (needs disclosure copy).
5. **Publishing** anything (Option 3 packs, public README/screenshots) — review for secrets + scraped data.
6. Letting **multiple users/IPs** share scanning infrastructure.
7. Persisting or transmitting any **new category of user data**.

> Rule of thumb: if a feature would make the tool look like scalper infrastructure or leak private data, it's a "never." If it merely changes what data is touched or where it goes, it's an "ask first."
