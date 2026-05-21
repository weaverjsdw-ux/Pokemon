"""Reddit community-signal source. Uses the Replay HTTP fake."""
from __future__ import annotations

import time

from scanner.sources.reddit import RedditSource, _matches

from .replay import Replay, json_resp


def _reddit_payload(posts):
    return {
        "data": {
            "children": [{"data": p} for p in posts],
        }
    }


def test_matches_requires_keyword_and_retailer():
    assert _matches("just a regular post about cards",
                    ["restock"], ["target"]) == []
    assert _matches("found a restock at Target!",
                    ["restock"], ["target"]) == ["restock"]
    # keyword without retailer
    assert _matches("got a restock today!",
                    ["restock"], ["target"]) == []


def test_fetches_and_filters_to_matching_posts():
    now = time.time()
    payload = _reddit_payload([
        {"id": "a1", "title": "Restock at Target!", "selftext": "", "author": "u",
         "permalink": "/r/PokemonTCG/comments/a1/", "created_utc": now - 60},
        {"id": "a2", "title": "I pulled a Charizard",  "selftext": "", "author": "u",
         "permalink": "/r/PokemonTCG/comments/a2/", "created_utc": now - 60},
        {"id": "a3", "title": "old post",  "selftext": "restock target",
         "author": "u", "permalink": "/r/PokemonTCG/comments/a3/",
         "created_utc": now - 7200},
    ])
    client = Replay({("GET", "https://www.reddit.com/r/PokemonTCG/new.json"):
                     json_resp(payload)})
    src = RedditSource(subs=["PokemonTCG"], http=client, max_age_seconds=3600)
    hits = list(src.fetch())
    assert len(hits) == 1
    assert hits[0].external_id == "a1"
    assert "restock" in hits[0].matched_keywords


def test_iterates_multiple_subs():
    now = time.time()
    a = _reddit_payload([{"id": "1", "title": "restock walmart", "selftext": "",
                          "author": "u", "permalink": "/x/1/", "created_utc": now}])
    b = _reddit_payload([{"id": "2", "title": "restock target", "selftext": "",
                          "author": "u", "permalink": "/x/2/", "created_utc": now}])
    client = Replay({
        ("GET", "https://www.reddit.com/r/A/new.json"): json_resp(a),
        ("GET", "https://www.reddit.com/r/B/new.json"): json_resp(b),
    })
    src = RedditSource(subs=["A", "B"], http=client)
    ids = sorted(h.external_id for h in src.fetch())
    assert ids == ["1", "2"]


def test_handles_5xx_gracefully():
    client = Replay({("GET", "https://www.reddit.com/r/PokemonTCG/new.json"):
                     json_resp({}, status=500)})
    # The http wrapper retries 5xx and ultimately raises; the source
    # must swallow that and continue.
    src = RedditSource(subs=["PokemonTCG"], http=client)
    # Wrap so the replay client's retries-on-5xx behavior fails fast and
    # the source catches.
    assert list(src.fetch()) == []
