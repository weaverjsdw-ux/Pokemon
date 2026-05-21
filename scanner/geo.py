"""Haversine + point-to-polyline distance for the route corridor filter."""
from __future__ import annotations

import math

EARTH_RADIUS_MI = 3958.7613


def haversine_miles(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lng1 = a
    lat2, lng2 = b
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    h = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_MI * math.asin(math.sqrt(h))


def _project_to_segment(
    p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]
) -> tuple[float, float]:
    """Approximate planar projection (fine for short segments at mid-latitudes)."""
    lat_scale = math.cos(math.radians((a[0] + b[0]) / 2))
    ax, ay = a[1] * lat_scale, a[0]
    bx, by = b[1] * lat_scale, b[0]
    px, py = p[1] * lat_scale, p[0]
    dx, dy = bx - ax, by - ay
    denom = dx * dx + dy * dy
    if denom == 0:
        return a
    t = ((px - ax) * dx + (py - ay) * dy) / denom
    t = max(0.0, min(1.0, t))
    return (ay + t * dy, (ax + t * dx) / lat_scale)


def distance_to_polyline_miles(
    point: tuple[float, float], polyline: list[tuple[float, float]]
) -> float:
    if not polyline:
        return float("inf")
    if len(polyline) == 1:
        return haversine_miles(point, polyline[0])
    best = float("inf")
    for i in range(len(polyline) - 1):
        proj = _project_to_segment(point, polyline[i], polyline[i + 1])
        d = haversine_miles(point, proj)
        if d < best:
            best = d
    return best
