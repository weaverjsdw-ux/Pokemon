"""Normalized discovery candidates + catalog/set-watch title matching.

Every adapter emits CandidateDeal — never its own shape — so downstream stages
(verify, comp, verdict) are adapter-agnostic. Matching reuses the resale
module's title machinery (NEGATIVE_TITLE_PARTS, token expansion) so a listing
is matched by the same rules everywhere; no parallel matcher.

Rings (spec section 6): Ring 1 = tracked catalog product; Ring 2 = watched set
without a catalog product; Ring 3 = neither (wildcard, matched fields empty).
"""
from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass

from .. import resale


def _fold_char(ch: str) -> str:
    if ord(ch) < 128:
        return ch
    decomposed = unicodedata.normalize("NFKD", ch)
    base = [c for c in decomposed if not unicodedata.combining(c)]
    if len(base) == 1 and ord(base[0]) < 128:
        return base[0]        # é -> e
    return " "                # ™/½/— must not merge neighbors into one token


def _ascii_fold(text: str) -> str:
    """'Pokémon' -> 'Pokemon', 'Evolution—Ascended' -> 'Evolution Ascended',
    'Pokémon™' -> 'Pokemon ' (NOT 'PokemonTM').

    Real listing titles carry diacritics, em-dashes, and trademark signs;
    folding them naively either splits tokens (é), merges neighbors (—), or
    glues compatibility expansions onto words (™ -> TM), silently unmatching
    the title."""
    return "".join(_fold_char(ch) for ch in text)


@dataclass(frozen=True)
class CandidateDeal:
    source: str               # adapter slug
    listing_id: str           # stable id (thread id, eBay itemId, else sha256(url))
    item_name: str            # raw title as parsed
    price: float              # advertised item price, USD
    shipping: float | None
    url: str                  # direct listing/product URL
    retailer: str             # merchant name
    seen_at: str              # ISO datetime
    evidence_excerpt: str     # raw title+price text, <=200 chars
    matched_product_key: str | None   # catalog key when resolved (Ring 1)
    matched_set: str          # set-watch resolution (Ring 2), "" for Ring 3
    asset_class: str = "sealed"
    variant: str = ""
    condition_note: str = ""


def stable_listing_id(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def junk_title(title: str) -> bool:
    """Empty boxes, code cards, non-English prints, lots — never candidates."""
    lower = _ascii_fold(title).lower()
    return any(part in lower for part in resale.NEGATIVE_TITLE_PARTS)


def match_title(
    title: str,
    catalog: dict[str, dict],
    set_watch: list[str],
) -> tuple[str | None, str]:
    """(matched_product_key, matched_set) for a raw listing title.

    Ring 1 uses resale._title_allowed per product; when several products match
    (ETB vs bundle share set tokens), the most specific wins — the one whose
    required-token set is largest.
    """
    title = _ascii_fold(title)
    if junk_title(title):
        return None, ""
    item = {"title": title}
    best_key: str | None = None
    best_specificity = -1
    for key, product in catalog.items():
        if not resale._title_allowed(product, item):
            continue
        specificity = len(resale._required_tokens(product))
        if specificity > best_specificity:
            best_key, best_specificity = key, specificity
    if best_key is not None:
        return best_key, str(catalog[best_key].get("set") or "")

    title_tokens = resale._tokens(title)
    if "pokemon" not in title_tokens:
        return None, ""
    for set_name in set_watch:
        # Same generic-token subtraction Ring 1 uses: real listings say
        # "Pokemon TCG 151", not "Scarlet & Violet 151" — the distinctive
        # tokens are what identify the set.
        required = resale._tokens(set_name) - resale.GENERIC_QUERY_TOKENS
        if required and required <= title_tokens:
            return None, set_name
    return None, ""
