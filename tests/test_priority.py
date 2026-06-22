"""Product priority heuristics."""
from __future__ import annotations

from scanner.priority import product_priority


def test_magic_collector_booster_is_high_priority():
    label, score = product_priority(
        {
            "name": "Magic: The Gathering Marvel Super Heroes Collector Booster",
            "game": "Magic: The Gathering",
            "set": "Marvel Super Heroes",
            "type": "Collector Booster",
        }
    )

    assert label == "High priority"
    assert score == 100
