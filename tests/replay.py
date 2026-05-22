"""Lightweight HTTP mock-replay framework for retailer adapters.

Real retailer endpoints change shape often — a small CSS class rename or
a JSON key shuffle can silently break a parser. Replay fixtures freeze a
known response body so a regression in parsing code surfaces as a test
failure, not a Tuesday-morning silent miss.

Usage:

    from tests.replay import Replay, json_resp

    def test_target_stock_in_stock():
        client = Replay({
            ("GET", "https://redsky.target.com/.../product_fulfillment_v1"):
                json_resp({"data": {...}}),
        })
        adapter = Target(http=client)
        results = list(adapter._check_one(...))
        ...

The Replay client implements just enough of HTTPClient's surface area
that adapter code thinks it's the real thing. Calls that aren't scripted
raise so tests fail loudly rather than silently no-op'ing.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit


@dataclass
class FakeResponse:
    status_code: int = 200
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))


def json_resp(payload: Any, status: int = 200) -> FakeResponse:
    return FakeResponse(
        status_code=status,
        body=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )


def text_resp(body: str, status: int = 200) -> FakeResponse:
    return FakeResponse(status_code=status, body=body.encode("utf-8"))


class _UnscriptedCall(AssertionError):
    pass


class Replay:
    """Stub HTTPClient drop-in. Keys are (method, url-without-querystring)."""

    def __init__(self, routes: dict[tuple[str, str], FakeResponse]):
        self._routes = {(m.upper(), u): r for (m, u), r in routes.items()}
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def request(self, retailer, method, url, **kwargs):
        base = urlsplit(url)._replace(query="").geturl()
        key = (method.upper(), base)
        self.calls.append((method.upper(), base, kwargs))
        if key not in self._routes:
            raise _UnscriptedCall(f"no fixture for {key} (retailer={retailer})")
        return self._routes[key]

    # The base Retailer doesn't need these but mirror the real client.
    def is_disabled(self, retailer: str) -> bool:
        return False

    def health_snapshot(self) -> dict[str, Any]:
        return {}
