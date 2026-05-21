"""Distance math used by the route corridor filter."""
from __future__ import annotations

import math

from scanner.geo import distance_to_polyline_miles, haversine_miles


def test_haversine_zero_distance():
    p = (40.7128, -74.0060)  # NYC
    assert haversine_miles(p, p) == 0.0


def test_haversine_known_distance_nyc_to_la():
    nyc = (40.7128, -74.0060)
    la = (34.0522, -118.2437)
    # Great-circle distance NYC -> LA is ~2451 miles. Allow 1% tolerance.
    d = haversine_miles(nyc, la)
    assert math.isclose(d, 2451, rel_tol=0.01)


def test_distance_to_empty_polyline_is_inf():
    assert distance_to_polyline_miles((40.0, -74.0), []) == float("inf")


def test_distance_to_single_point_polyline():
    p = (40.0, -74.0)
    poly = [(40.5, -74.0)]
    d = distance_to_polyline_miles(p, poly)
    # 0.5 deg lat ~= 34.5 miles. Allow 1% tolerance.
    assert math.isclose(d, 34.54, rel_tol=0.02)


def test_point_on_segment_has_near_zero_distance():
    a = (40.0, -74.0)
    b = (40.0, -73.0)
    midpoint = (40.0, -73.5)
    d = distance_to_polyline_miles(midpoint, [a, b])
    assert d < 0.01


def test_point_off_segment_returns_perpendicular_distance():
    # Segment runs east-west at lat 40.0; point is 0.1 deg north.
    a = (40.0, -74.0)
    b = (40.0, -73.0)
    p = (40.1, -73.5)
    d = distance_to_polyline_miles(p, [a, b])
    # 0.1 deg lat ~= 6.9 miles
    assert math.isclose(d, 6.9, rel_tol=0.05)
