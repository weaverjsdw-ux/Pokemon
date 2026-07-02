import json
from pathlib import Path

from scanner import config as cfg_mod
from scanner.discovery.golden import golden_check
from scanner.discovery.render import render_sweep

SWEEP = json.loads(Path("data/poke/fixtures/sample-sweep.json").read_text(encoding="utf-8"))
CFG = cfg_mod.from_mapping({"locations": {"home": "A", "work": "B"}})


def test_golden_passes_on_fixture():
    html = render_sweep(SWEEP)
    assert golden_check(html, CFG.poke.min_rows) == []


def test_golden_fails_on_missing_section():
    html = render_sweep(SWEEP).replace("Sources", "Srcs")
    fails = golden_check(html, CFG.poke.min_rows)
    assert any("Sources" in f for f in fails)


def test_golden_fails_on_dangling_anchor():
    html = render_sweep(SWEEP) + '<a href="#nope-nope"></a>'
    fails = golden_check(html, CFG.poke.min_rows)
    assert any("nope-nope" in f for f in fails)


def test_golden_fails_below_row_floor():
    html = render_sweep(SWEEP)
    fails = golden_check(html, min_rows=999)
    assert any("acquisition failure" in f for f in fails)
