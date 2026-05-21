"""Reddit community-signal ingest.

Reddit exposes a JSON listing at /r/<sub>/new.json (no auth required for
read-only). Each post has id, title, selftext, permalink, created_utc,
author. We poll a few subs, filter posts that match restock-y keywords
plus a known retailer or set name, and emit SignalHits the scanner can
surface alongside its own polling hits.

Defaults are conservative: only obvious restock chatter from the most
on-topic subs, dedupe by post id so we don't repeat. The user can widen
or narrow by editing config."""
from __future__ import annotations

import re
import time
from typing import Iterable

from ..http import HTTPClient, default_client
from ..log import get_logger
from . import SignalHit

log = get_logger(__name__)

DEFAULT_KEYWORDS = [
    "restock", "in stock", "drop", "back in stock", "found at",
    "pickup", "scored", "got one", "available",
]
DEFAULT_RETAILERS = [
    "target", "walmart", "best buy", "bestbuy", "gamestop", "costco",
    "sam's club", "samsclub", "pokemon center", "pokémon center",
    "barnes and noble", "barnes & noble", "meijer", "five below", "5 below",
]
DEFAULT_SUBS = ["PokemonTCG", "PokeInvesting"]

UA = "pokemon-restock-scanner/0.1 (https://github.com/weaverjsdw-ux/Pokemon; community-signal)"


def _matches(text: str, keywords: list[str], retailers: list[str]) -> list[str]:
    """Return the matched keywords; empty list means no match.

    A post qualifies if it contains AT LEAST ONE restock-y keyword AND
    AT LEAST ONE retailer name. The retailer match cuts out unrelated
    chatter ('I got one!' about a pull, etc.)."""
    t = text.lower()
    hit_keywords = [k for k in keywords if k in t]
    if not hit_keywords:
        return []
    if not any(r in t for r in retailers):
        return []
    return hit_keywords


class RedditSource:
    name = "reddit"

    def __init__(
        self,
        subs: list[str] | None = None,
        keywords: list[str] | None = None,
        retailers: list[str] | None = None,
        max_age_seconds: int = 3600,
        http: HTTPClient | None = None,
    ):
        self.subs = subs or list(DEFAULT_SUBS)
        self.keywords = [k.lower() for k in (keywords or DEFAULT_KEYWORDS)]
        self.retailers = [r.lower() for r in (retailers or DEFAULT_RETAILERS)]
        self.max_age = max_age_seconds
        self.http = http or default_client

    def fetch(self) -> Iterable[SignalHit]:
        cutoff = time.time() - self.max_age
        for sub in self.subs:
            url = f"https://www.reddit.com/r/{sub}/new.json"
            try:
                resp = self.http.request(
                    "reddit", "GET", url,
                    params={"limit": 25, "raw_json": 1},
                    headers={"User-Agent": UA, "Accept": "application/json"},
                )
            except Exception as exc:
                log.warning("reddit fetch %s failed: %s", sub, exc)
                continue
            if resp.status_code != 200:
                continue
            try:
                payload = resp.json()
            except ValueError:
                continue
            for child in payload.get("data", {}).get("children", []):
                post = child.get("data", {}) or {}
                created = float(post.get("created_utc") or 0)
                if created < cutoff:
                    continue
                title = post.get("title") or ""
                body = post.get("selftext") or ""
                matched = _matches(f"{title}\n{body}", self.keywords, self.retailers)
                if not matched:
                    continue
                # Build the canonical link to the post.
                permalink = post.get("permalink") or ""
                link = f"https://www.reddit.com{permalink}" if permalink else (post.get("url") or "")
                yield SignalHit(
                    source="reddit",
                    where=f"r/{sub}",
                    author=str(post.get("author") or "unknown"),
                    title=title.strip(),
                    summary=_summarize(title, body, matched),
                    url=link,
                    matched_keywords=matched,
                    posted_ts=int(created),
                    external_id=str(post.get("id") or ""),
                )


def _summarize(title: str, body: str, matched: list[str]) -> str:
    # Title is usually self-contained; truncate body for context.
    body_excerpt = re.sub(r"\s+", " ", body).strip()
    if len(body_excerpt) > 240:
        body_excerpt = body_excerpt[:237] + "..."
    tags = ", ".join(matched)
    if body_excerpt:
        return f"{title}  ·  {body_excerpt}  ·  matched: {tags}"
    return f"{title}  ·  matched: {tags}"
