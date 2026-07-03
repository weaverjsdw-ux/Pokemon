"""One-shot TCGplayer product-page probe (Slice 1, Task 1).

Operator-approved live fetch (spec Appendix A, Step 0). Max 3 GETs, 1.5s apart,
plain requests only - no browser, no bot-wall evasion. Saves raw HTML as fixtures
and prints whether a market price is parseable from the static response.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

import requests

# Seeded catalog ids (data/products.yaml ppt_id == TCGplayer product id).
IDS = ["593355", "624676", "610930"]  # Prismatic ETB, Destined Rivals ETB, Journey Together ETB
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0 Safari/537.36"
)
OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "comps"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for pid in IDS:
        url = f"https://www.tcgplayer.com/product/{pid}"
        resp = requests.get(url, headers={"User-Agent": UA, "Accept": "text/html"}, timeout=30)
        (OUT / f"tcgplayer_product_{pid}.html").write_text(resp.text, encoding="utf-8")
        hits = re.findall(r'.{0,40}[Mm]arket\s*[Pp]rice.{0,120}', resp.text)
        json_hits = re.findall(r'"marketPrice"\s*:\s*"?\$?[0-9][0-9.,]*"?', resp.text)
        print(f"{pid}: HTTP {resp.status_code}, {len(resp.text)} bytes, "
              f"text-hits={len(hits)}, json-hits={len(json_hits)}")
        for sample in (json_hits or hits)[:5]:
            print("   ", sample[:110].replace("\n", " "))
        time.sleep(1.5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
