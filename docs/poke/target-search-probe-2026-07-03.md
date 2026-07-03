# Target search acquisition probe — 2026-07-03 (Slice 3)

**Question:** can the `target_search` discovery adapter get product/price data from plain
requests, as Phase-0's WebFetch verdict ("fetchable-plain") suggested?

**Answer: no.** Plain-requests acquisition is not available today; the adapter ships as an
honestly-degraded stub (`NOT_IMPLEMENTED`, `requires="playwright"`), pending the wave-2
Playwright decision (spec §10). **No evasion was attempted; none is permitted.**

## Evidence (plain `requests` GETs, browser UA, 1 s politeness, one attempt each)

| Probe | Result |
| --- | --- |
| `GET https://www.target.com/s?searchTerm=pokemon+trading+cards` | HTTP 200, 134,938 bytes — a JS shell. Embedded `__TGT_DATA__` contains only config (store ids, asset prefixes, endpoint names). Zero product titles, zero product prices ("Elite Trainer" count = 0; `product_summaries` appears only as an endpoint name). Products are loaded client-side via XHR. |
| `GET redsky.target.com/.../plp_search_v2` with the fulfillment public key (`9f36ae…`) | HTTP 403. |
| `GET redsky.target.com/.../plp_search_v2` with the page-embedded front-end search key (`c6b68a…`) | **HTTP 403 with a captcha challenge** (`{"captchaRelativeURL":"/captcha?trackingId=…"}`). The search API is bot-walled. |

Phase-0's WebFetch verdict does not transfer: WebFetch's fetch/render stack received a
product list, but the scheduled pipeline runs plain `requests`, which gets the shell.

## Ladder (per spec §4.2 pattern)

1. **Blocked (today):** `target_search` = declared stub, state `NOT_IMPLEMENTED`, reason
   recorded. The restock lane's Target adapter (RedSky `product_fulfillment_v1` by TCIN)
   is unaffected — it still answers plain requests for tracked catalog items.
2. **Wave 2 (operator decision):** Playwright fetch of the rendered search page — same
   gate as TrackaLacker/TCGplayer search (spec §10 open question 2).
3. **Never:** captcha/bot-wall evasion of `plp_search_v2`.

Raw probe responses retained in the session scratchpad; key facts recorded here. The
captcha response contained no credentials and no personal data.
