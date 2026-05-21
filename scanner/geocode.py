"""Address -> (lat, lng) via Nominatim (OpenStreetMap, free, no key).

Per Nominatim usage policy we set a real User-Agent and rate-limit to
<= 1 req/sec. Results are cached on disk so repeated runs don't re-hit
the API."""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "geocode.cache.json"
USER_AGENT = "pokemon-restock-scanner/0.1 (personal use)"


def _load_cache() -> dict[str, list[float]]:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def _save_cache(cache: dict[str, list[float]]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2))


def geocode(address: str) -> tuple[float, float]:
    cache = _load_cache()
    key = address.strip().lower()
    if key in cache:
        lat, lng = cache[key]
        return lat, lng

    resp = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": address, "format": "json", "limit": 1, "countrycodes": "us"},
        headers={"User-Agent": USER_AGENT},
        timeout=15,
    )
    resp.raise_for_status()
    results = resp.json()
    if not results:
        raise RuntimeError(f"Could not geocode address: {address!r}")
    lat = float(results[0]["lat"])
    lng = float(results[0]["lon"])

    cache[key] = [lat, lng]
    _save_cache(cache)
    time.sleep(1.1)  # Nominatim courtesy
    return lat, lng
