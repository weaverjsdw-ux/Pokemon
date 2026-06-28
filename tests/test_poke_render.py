import json
import re
from pathlib import Path

import pytest

from scanner.discovery.render import nav_anchors, element_ids, render_sweep
from scanner.discovery.schema import StopGateError

SWEEP = json.loads(Path("data/poke/fixtures/sample-sweep.json").read_text(encoding="utf-8"))


def test_required_sections_present():
    html = render_sweep(SWEEP)
    for needle in ("Top Steals", "Watch Out", "Sources"):
        assert needle in html


def test_every_nav_anchor_resolves():
    html = render_sweep(SWEEP)
    ids = set(element_ids(html))
    for anchor in nav_anchors(html):
        assert anchor in ids, f"dangling nav anchor #{anchor}"


def test_every_deal_row_carries_source_and_date():
    html = render_sweep(SWEEP)
    rows = re.findall(r'data-source-url="([^"]*)"\s+data-captured-at="([^"]*)"', html)
    assert len(rows) >= 10
    assert all(src and date for src, date in rows)


def test_est_row_renders_est_badge_and_watch_out_reseal():
    html = render_sweep(SWEEP)
    assert "EST" in html
    assert "reseal" in html.lower()


def test_stop_gate_blocks_render_on_bad_row():
    bad = json.loads(json.dumps(SWEEP))
    bad["deals"][0]["source_url"] = ""   # verified row missing source
    with pytest.raises(StopGateError):
        render_sweep(bad)
