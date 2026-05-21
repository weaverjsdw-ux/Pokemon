"""Twitter/X community-signal via Nitter (experimental).

Nitter is an open-source frontend for Twitter that exposes a per-user RSS
feed without authentication. We use that to pick up restock chatter from
accounts that post drop reports.

**This is experimental.** Twitter actively blocks Nitter instances and
the public instance landscape is volatile — instances appear, get rate-
limited, and disappear. Treat this source as best-effort: if it works
for a stretch, great; if your configured instance dies, the source will
log a warning and yield nothing, but it won't take down the scanner.

Config:

    community_signal:
      nitter:
        enabled: true
        instance: "https://nitter.privacydev.net"   # whichever still works
        accounts: ["restockalert", "pokemonrestock"]

Each account's RSS feed is polled; entries with restock keywords are
deduplicated against signal_seen and surfaced. RSS lacks rich metadata
so we do a simpler keyword-only match (no retailer-name gate) since most
of these tracker accounts are domain-restricted already."""
from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from typing import Iterable

from ..http import HTTPClient, default_client
from ..log import get_logger
from . import SignalHit

log = get_logger(__name__)

DEFAULT_KEYWORDS = [
    "restock", "in stock", "back in stock", "drop", "available now",
]


class NitterSource:
    name = "nitter"

    def __init__(
        self,
        instance: str,
        accounts: list[str],
        keywords: list[str] | None = None,
        max_age_seconds: int = 3600,
        http: HTTPClient | None = None,
    ):
        self.instance = instance.rstrip("/")
        self.accounts = [a.lstrip("@") for a in accounts if a]
        self.keywords = [k.lower() for k in (keywords or DEFAULT_KEYWORDS)]
        self.max_age = max_age_seconds
        self.http = http or default_client

    def fetch(self) -> Iterable[SignalHit]:
        if not self.instance or not self.accounts:
            return
        cutoff = time.time() - self.max_age
        for account in self.accounts:
            url = f"{self.instance}/{account}/rss"
            try:
                resp = self.http.request(
                    "nitter", "GET", url,
                    headers={"User-Agent": "pokemon-restock-scanner/0.1"},
                    timeout=15,
                )
            except Exception as exc:
                log.warning("nitter fetch %s failed: %s", account, exc)
                continue
            if resp.status_code != 200:
                log.warning("nitter %s returned %d (instance may be blocked)",
                            account, resp.status_code)
                continue
            try:
                root = ET.fromstring(resp.text)
            except ET.ParseError:
                continue
            channel = root.find("channel")
            if channel is None:
                continue
            for item in channel.findall("item"):
                title = (item.findtext("title") or "").strip()
                desc = (item.findtext("description") or "").strip()
                link = (item.findtext("link") or "").strip()
                guid = (item.findtext("guid") or link).strip()
                pub_str = (item.findtext("pubDate") or "").strip()
                pub_ts = _parse_pubdate(pub_str)
                if pub_ts < cutoff:
                    continue
                t = f"{title}\n{desc}".lower()
                matched = [k for k in self.keywords if k in t]
                if not matched:
                    continue
                # Build a Twitter-facing URL even though we fetched from Nitter,
                # so the user can click through to the real source.
                twitter_url = re.sub(r"^https?://[^/]+", "https://twitter.com", link) or link
                yield SignalHit(
                    source="x",
                    where=f"@{account}",
                    author=f"@{account}",
                    title=title,
                    summary=f"{title} · matched: {', '.join(matched)}",
                    url=twitter_url,
                    matched_keywords=matched,
                    posted_ts=int(pub_ts),
                    external_id=guid,
                )


def _parse_pubdate(s: str) -> float:
    """RSS pubDate is RFC 2822. Fall back to 'now' if unparseable."""
    if not s:
        return 0.0
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(s)
        return dt.timestamp() if dt else 0.0
    except (TypeError, ValueError):
        return 0.0
