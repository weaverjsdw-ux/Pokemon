"""Shared set-name identity for cross-catalog joins.

The sealed catalog (``data/products.yaml``) and the singles catalog
(``data/poke/assets.yaml``) label the same set differently: sealed says
``set: "151"``, singles says ``set: "Scarlet & Violet 151"``. Any join that
compares those strings directly drops the rows silently — a wrong answer, not a
cosmetic mismatch.

This module is the ONE place that decides whether two set labels name the same
set. Kept standalone (no scanner imports) so discovery and poke_api can both use
it without a cycle, the same way ``priority.py`` keeps its heuristic in one place.

**This is a comparison key, never a stored value.** Ledger identity
(``ledger.item_key``) is built from the catalog's own ``set`` string, and the
ledger already holds observations under BOTH labels. Rewriting either catalog's
``set`` — or normalizing it on the way into a row — would change the item_key and
orphan the history it was meant to protect. Join on ``set_identity``; persist
what the catalog said.

Aliases are an explicit exact table, not fuzzy matching: at this catalog size a
deterministic map is 100% precision, and a guess is a wrong number.
"""
from __future__ import annotations

import re
import unicodedata

# Short catalog label -> the set's full name. Only entries proven to name the
# same set belong here; an unknown label normalizes to itself (never guessed).
SET_ALIASES: dict[str, str] = {
    "151": "Scarlet & Violet 151",
}

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _fold(text: str) -> str:
    """'Pokémon' -> 'Pokemon'. Diacritics only; never merges tokens."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def canonical_set_name(name) -> str:
    """Resolve a catalog set label to the set's full name ('151' -> 'Scarlet &
    Violet 151'). An unaliased label is returned stripped, unchanged."""
    label = str(name or "").strip()
    return SET_ALIASES.get(label.lower(), label)


def set_identity(name) -> str:
    """Canonical comparison key for a set label. Alias-resolved, ascii-folded,
    lowercased, punctuation collapsed:

        set_identity("151") == set_identity("Scarlet & Violet 151")
        -> "scarlet violet 151"

    Empty/absent -> "" (an unknown set never joins to a known one)."""
    resolved = canonical_set_name(name)
    if not resolved:
        return ""
    return _NON_ALNUM.sub(" ", _fold(resolved).lower()).strip()


def same_set(left, right) -> bool:
    """True when two set labels name the same set. Two empties are NOT the same
    set — an absent label joins to nothing."""
    left_id = set_identity(left)
    return bool(left_id) and left_id == set_identity(right)
