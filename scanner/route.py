"""Route polyline via OSRM (free) or Google Directions (key required)."""
from __future__ import annotations

import polyline as _polyline
import requests


def osrm_polyline(start: tuple[float, float], end: tuple[float, float]) -> list[tuple[float, float]]:
    """Driving polyline using the public OSRM demo server. No key required."""
    url = (
        f"https://router.project-osrm.org/route/v1/driving/"
        f"{start[1]},{start[0]};{end[1]},{end[0]}"
    )
    resp = requests.get(
        url,
        params={"overview": "full", "geometries": "geojson"},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != "Ok" or not data.get("routes"):
        raise RuntimeError(f"OSRM routing failed: {data.get('code')}")
    coords = data["routes"][0]["geometry"]["coordinates"]
    # OSRM returns [lng, lat]; normalize to (lat, lng).
    return [(lat, lng) for lng, lat in coords]


def google_polyline(
    start: tuple[float, float], end: tuple[float, float], api_key: str
) -> list[tuple[float, float]]:
    resp = requests.get(
        "https://maps.googleapis.com/maps/api/directions/json",
        params={
            "origin": f"{start[0]},{start[1]}",
            "destination": f"{end[0]},{end[1]}",
            "mode": "driving",
            "key": api_key,
        },
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "OK" or not data.get("routes"):
        raise RuntimeError(f"Google directions failed: {data.get('status')}")
    encoded = data["routes"][0]["overview_polyline"]["points"]
    return _polyline.decode(encoded)  # already (lat, lng)


def get_polyline(
    start: tuple[float, float],
    end: tuple[float, float],
    engine: str,
    google_api_key: str = "",
) -> list[tuple[float, float]]:
    if engine == "google" and google_api_key:
        try:
            return google_polyline(start, end, google_api_key)
        except Exception:
            pass  # fall through to OSRM
    return osrm_polyline(start, end)
