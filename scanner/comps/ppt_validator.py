"""PPT spot-check validator - NEVER called by any pipeline (spec 4.6).

Money-class guardrails: refuses without market.api_key; surfaces the credit
estimate and refuses without --yes (operator go-ahead); hard-stops when the
daily remaining balance drops below 15 (post-charge header, seeding convention).
Spec: docs/superpowers/specs/2026-07-02-buyable-deal-pipeline-design.md 4.6.
Note: spec 4.6 wrote `-m scanner.comps.validate`; canonical module name is
ppt_validator (cosmetic naming deviation, recorded here).
"""
from __future__ import annotations

import argparse
import time
from typing import Any

from .. import config as cfg_mod
from .. import market as market_mod
from .. import resale
from .engine import CompEngine

HARD_STOP_REMAINING = 15


def _delta_pct(ours: float | None, theirs: float | None) -> str:
    if not ours or not theirs:
        return "n/a"
    return f"{abs(ours - theirs) / theirs * 100.0:.1f}%"


def main(argv: list[str] | None = None, cfg: Any = None,
         ppt_client: Any = None, engine: Any = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scanner.comps.ppt_validator",
        description="Compare in-house comps vs PPT (1 credit/product, limit=1).")
    parser.add_argument("--products", required=True,
                        help="comma-separated catalog keys")
    parser.add_argument("--yes", action="store_true",
                        help="operator go-ahead for the surfaced credit spend")
    args = parser.parse_args(argv)

    cfg = cfg or cfg_mod.load()
    if not getattr(cfg, "market_api_key", ""):
        print("refused: market.api_key not configured")
        return 2
    keys = [k.strip() for k in args.products.split(",") if k.strip()]
    unknown = [k for k in keys if k not in cfg.products]
    if unknown:
        print(f"refused: unknown product keys: {', '.join(unknown)}")
        return 2
    print(f"estimated spend: ~{len(keys)} credit(s) (1 credit/product, limit=1 pinned)")
    if not args.yes:
        print("refused: pass --yes only after operator go-ahead (PPT credits are money-class)")
        return 2

    ppt = ppt_client or market_mod.PokemonPriceTrackerClient.from_config(cfg)
    eng = engine or CompEngine.from_config(cfg)
    for key in keys:
        product = cfg.products[key]
        checked_at = int(time.time())
        theirs = ppt.estimate(key, product, checked_at)
        ours = eng.estimate(key, product, checked_at)
        t_val = resale._amount(theirs.get("estimate"))
        o_val = resale._amount(ours.get("estimate"))
        print(f"{key}: ppt={theirs.get('estimate') or 'n/a'} "
              f"inhouse={ours.get('estimate') or 'n/a'} "
              f"delta={_delta_pct(o_val, t_val)} "
              f"(inhouse confidence: {ours.get('confidence')})")
        remaining = theirs.get("dailyRemaining")
        if isinstance(remaining, int) and remaining < HARD_STOP_REMAINING:
            print(f"HARD STOP: daily remaining {remaining} < {HARD_STOP_REMAINING}; "
                  f"stopping before the next product")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
