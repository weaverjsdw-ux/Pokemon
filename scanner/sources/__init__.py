"""Community-signal sources.

Sources are read-only feeds (Reddit, Discord, X/Twitter, etc.) that the
scanner watches for restock chatter. Each source emits SignalHit objects
which the main loop deduplicates against its own polling-based hits and
surfaces as a different kind of alert.

Sources do not poll retailer endpoints; they are purely about humans
reporting drops that the polling adapters might have missed."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SignalHit:
    source: str            # "reddit", "discord", "x", etc.
    where: str             # subreddit / channel / handle that posted it
    author: str
    title: str
    summary: str           # one-line summary for the alert
    url: str
    matched_keywords: list[str]
    posted_ts: int         # unix
    external_id: str       # post id (for dedupe)
