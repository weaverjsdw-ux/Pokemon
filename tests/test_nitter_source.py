"""Nitter RSS source."""
from __future__ import annotations

import time
from email.utils import formatdate

from scanner.sources.nitter import NitterSource

from .replay import Replay, text_resp


def _rss(items: list[dict]) -> str:
    pieces = []
    for it in items:
        pieces.append(
            f"<item><title>{it['title']}</title>"
            f"<description>{it.get('desc','')}</description>"
            f"<link>{it['link']}</link>"
            f"<guid>{it['guid']}</guid>"
            f"<pubDate>{it['pub']}</pubDate></item>"
        )
    return (
        '<?xml version="1.0"?><rss><channel><title>x</title>'
        + "".join(pieces) +
        "</channel></rss>"
    )


def _recent_pubdate():
    return formatdate(time.time() - 30, usegmt=True)


def test_skips_old_items():
    old = formatdate(time.time() - 7200, usegmt=True)
    client = Replay({("GET", "https://nitter.example/foo/rss"):
                     text_resp(_rss([{
                        "title": "restock at target",
                        "link": "https://nitter.example/foo/status/1",
                        "guid": "1",
                        "pub": old,
                     }]))})
    src = NitterSource("https://nitter.example", ["foo"], http=client, max_age_seconds=3600)
    assert list(src.fetch()) == []


def test_yields_matching_recent_item():
    client = Replay({("GET", "https://nitter.example/foo/rss"):
                     text_resp(_rss([{
                        "title": "RESTOCK at Target!",
                        "link": "https://nitter.example/foo/status/1",
                        "guid": "1",
                        "pub": _recent_pubdate(),
                     }]))})
    src = NitterSource("https://nitter.example", ["foo"], http=client)
    hits = list(src.fetch())
    assert len(hits) == 1
    assert hits[0].source == "x"
    assert hits[0].where == "@foo"
    assert "restock" in hits[0].matched_keywords
    # Twitter-canonical link, not Nitter
    assert hits[0].url.startswith("https://twitter.com/")


def test_no_match_yields_nothing():
    client = Replay({("GET", "https://nitter.example/foo/rss"):
                     text_resp(_rss([{
                        "title": "just a regular tweet",
                        "link": "https://nitter.example/foo/status/1",
                        "guid": "1",
                        "pub": _recent_pubdate(),
                     }]))})
    src = NitterSource("https://nitter.example", ["foo"], http=client)
    assert list(src.fetch()) == []


def test_no_accounts_no_calls():
    client = Replay({})  # unscripted -> assertion
    src = NitterSource("https://nitter.example", [], http=client)
    list(src.fetch())
    assert client.calls == []


def test_instance_block_logs_and_continues():
    client = Replay({("GET", "https://nitter.dead/foo/rss"): text_resp("", status=503)})
    src = NitterSource("https://nitter.dead", ["foo", "bar"], http=client)
    # First account 503s — we must not raise; second account is unscripted
    # but iteration moves on if first returns nothing.
    # Add a route for the second so iteration completes.
    client._routes[("GET", "https://nitter.dead/bar/rss")] = text_resp("", status=503)
    assert list(src.fetch()) == []
