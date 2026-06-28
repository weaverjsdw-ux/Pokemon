"""Phase-0 spike: does the comp backbone return a VERIFIED-tier comp for a
sealed product in the current repo state? Prints the comp + confidence tier.
Read-only; no writes to state. Run manually."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root on path

from scanner import config as cfg_mod
from scanner import market as market_mod

SEALED_KEY = "prismatic_evolutions_etb"  # a known catalog sealed product


def main() -> int:
    cfg = cfg_mod.load()  # uses the operator's real config.yaml (keys if present)
    product = cfg.products.get(SEALED_KEY)
    if not product:
        print(f"FAIL: {SEALED_KEY} not in catalog")
        return 1
    client = market_mod.market_client_from_config(cfg)
    row = client.estimate(SEALED_KEY, product, 0)
    comp, confidence = market_mod.comp_from_row(row)
    print(f"product={SEALED_KEY}")
    print(f"client={type(client).__name__}")
    print(f"status={row.get('status')!r} source={row.get('source')!r}")
    print(f"comp={comp!r} confidence_tier={confidence!r}")
    print(f"price_confidence={'verified' if confidence in {'high','medium'} else 'est/low'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
