"""Thin client over the Open-Meteo public weather API.

Open-Meteo (https://open-meteo.com) needs no API key and is free for
non-commercial use within its fair-use limits. We still route through the
proxy-rotating session so bursts of requests don't trip its per-IP limits.
"""
from __future__ import annotations

from dataclasses import dataclass

from .proxy_session import ProxyRotatingSession

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


@dataclass
class Place:
    name: str
    latitude: float
    longitude: float
    country: str = ""

    def label(self) -> str:
        return f"{self.name}, {self.country}".rstrip(", ")


@dataclass
class CurrentWeather:
    place: Place
    temperature_c: float
    windspeed_kmh: float
    description: str


# WMO weather-interpretation codes -> human text (abridged to common cases).
_WMO = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    80: "Rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Severe thunderstorm",
}


def geocode(session: ProxyRotatingSession, query: str) -> Place:
    """Resolve a place name to coordinates."""
    resp = session.get(GEOCODE_URL, params={"name": query, "count": 1})
    resp.raise_for_status()
    results = resp.json().get("results") or []
    if not results:
        raise LookupError(f"no location found for {query!r}")
    top = results[0]
    return Place(
        name=top.get("name", query),
        latitude=float(top["latitude"]),
        longitude=float(top["longitude"]),
        country=top.get("country", ""),
    )


def current_weather(session: ProxyRotatingSession, place: Place) -> CurrentWeather:
    """Fetch current conditions for a resolved place."""
    resp = session.get(
        FORECAST_URL,
        params={
            "latitude": place.latitude,
            "longitude": place.longitude,
            "current_weather": "true",
        },
    )
    resp.raise_for_status()
    cw = resp.json().get("current_weather") or {}
    code = int(cw.get("weathercode", -1))
    return CurrentWeather(
        place=place,
        temperature_c=float(cw.get("temperature", "nan")),
        windspeed_kmh=float(cw.get("windspeed", "nan")),
        description=_WMO.get(code, f"Unknown (code {code})"),
    )
