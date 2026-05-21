"""Address -> (lat, lng) with a fallback chain.

Tries providers in order until one returns a result:
  1. Nominatim (OpenStreetMap) — free, no key, but rate-limited and
     occasionally times out. Default.
  2. Mapbox — free tier 100k req/month, needs MAPBOX_TOKEN env var.
  3. Google Geocoding — paid, needs GOOGLE_API_KEY env var.

Results are cached on disk so repeated runs don't re-hit any provider.
If a provider is unreachable (timeout / 5xx), we move to the next one
rather than failing the boot — one geocoder being down shouldn't take
the scanner offline."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests

from .log import get_logger

log = get_logger(__name__)

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


def _try_nominatim(address: str) -> tuple[float, float] | None:
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": address, "format": "json", "limit": 1, "countrycodes": "us"},
            headers={"User-Agent": USER_AGENT},
            timeout=15,
        )
    except requests.RequestException as exc:
        log.warning("nominatim unreachable: %s", exc)
        return None
    if resp.status_code != 200:
        log.warning("nominatim returned %d", resp.status_code)
        return None
    try:
        results = resp.json()
    except ValueError:
        return None
    time.sleep(1.1)  # courtesy
    if not results:
        return None
    return float(results[0]["lat"]), float(results[0]["lon"])


def _try_mapbox(address: str) -> tuple[float, float] | None:
    token = os.environ.get("MAPBOX_TOKEN", "").strip()
    if not token:
        return None
    try:
        from urllib.parse import quote
        resp = requests.get(
            f"https://api.mapbox.com/geocoding/v5/mapbox.places/{quote(address)}.json",
            params={"access_token": token, "limit": 1, "country": "us"},
            timeout=15,
        )
    except requests.RequestException as exc:
        log.warning("mapbox unreachable: %s", exc)
        return None
    if resp.status_code != 200:
        log.warning("mapbox returned %d", resp.status_code)
        return None
    try:
        features = resp.json().get("features", [])
    except ValueError:
        return None
    if not features:
        return None
    lng, lat = features[0]["center"]
    return float(lat), float(lng)


def _try_google(address: str) -> tuple[float, float] | None:
    key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if not key:
        return None
    try:
        resp = requests.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"address": address, "key": key},
            timeout=15,
        )
    except requests.RequestException as exc:
        log.warning("google geocoder unreachable: %s", exc)
        return None
    if resp.status_code != 200:
        return None
    try:
        results = resp.json().get("results", [])
    except ValueError:
        return None
    if not results:
        return None
    loc = results[0]["geometry"]["location"]
    return float(loc["lat"]), float(loc["lng"])


_PROVIDERS = [
    ("nominatim", _try_nominatim),
    ("mapbox", _try_mapbox),
    ("google", _try_google),
]


def geocode(address: str) -> tuple[float, float]:
    cache = _load_cache()
    key = address.strip().lower()
    if key in cache:
        lat, lng = cache[key]
        return lat, lng

    for name, fn in _PROVIDERS:
        result = fn(address)
        if result is not None:
            log.info("geocoded via %s: %s -> %s", name, address, result)
            cache[key] = list(result)
            _save_cache(cache)
            return result
        log.info("geocoder %s did not return a result; trying next", name)

    raise RuntimeError(
        f"All geocoders failed for address: {address!r}. "
        f"Set MAPBOX_TOKEN or GOOGLE_API_KEY for a fallback."
    )
