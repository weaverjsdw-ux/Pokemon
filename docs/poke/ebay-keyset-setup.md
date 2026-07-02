# eBay Browse API — keyset setup (operator task)

The scanner's eBay comp client (`scanner/resale.py` — `EbayResaleClient`) is fully built but
has no credentials, so `resale_client_from_config` silently returns the
PriceCharting/public fallback today (confirmed 2026-07-02). Two values fix it.

## 1. Provision (free, developer.ebay.com)

1. Register at <https://developer.ebay.com> (free account) and sign in.
2. Create an application → request a **Production** keyset (sandbox keys do NOT serve
   production Browse data). Application approval can take from minutes to days.
3. From the keyset page copy two values: **App ID (Client ID)** and **Cert ID (Client
   Secret)**.

## 2. Wire (two lines in the gitignored config.yaml)

Resolution order is config-first, env fallback (`scanner/resale.py:94-107`):

    ebay_client_id: "<App ID>"
    ebay_client_secret: "<Cert ID>"

Env alternative: `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET`. Nothing else is needed — the
client mints its own OAuth token via client-credentials (`resale.py:609`);
`ebay_marketplace_id` defaults to `EBAY_US` (leave unset). A pre-minted token via
`ebay_browse_api_token` / `EBAY_BROWSE_API_TOKEN` also works but expires — prefer id+secret.

## 3. Verify (zero API calls, zero secret output)

    .venv/Scripts/python.exe -c "
    from scanner import config as cfg_mod, resale
    cfg = cfg_mod.load()
    print('auth_configured:', resale.auth_configured(cfg))
    print('client:', type(resale.resale_client_from_config(cfg)).__name__)
    "

Before keyset: `auth_configured: False` / `client: PublicFallbackResaleClient`.
After keyset: `auth_configured: True` / `client: EbayResaleClient`.
Optional live check (1 Browse call): run any scanner comp path and confirm the quote's flags
no longer include `public_ebay_search`.

## Security

- These are secrets: never commit, never print, never paste into chat. `config.yaml` is
  already gitignored.
- If a value leaks, rotate the keyset on the eBay developer console (Application Keys page).
