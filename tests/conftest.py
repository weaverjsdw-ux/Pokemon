"""Make the project root importable so `from scanner import ...` works
regardless of where pytest is invoked from."""
import sys
from pathlib import Path

import pytest

from scanner import config as cfg_mod

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def poke_cfg():
    """Minimal config fixture for tests. Reuses the same pattern as test_poke_sweep._cfg()."""
    raw = {"locations": {"home": "A", "work": "B"}}
    cfg = cfg_mod.from_mapping(raw)
    cfg.products = {
        "fake_etb": {"name": "Fake ETB", "set": "FakeSet", "type": "ETB", "msrp": "$49.99"},
        "fake_bundle": {"name": "Fake Bundle", "set": "FakeSet", "type": "Booster Bundle", "msrp": "$26.94"},
        "fake_box": {"name": "Fake Box", "set": "FakeSet", "type": "Surprise Box", "msrp": "$22.99"},
    }
    cfg.products_filter = None
    return cfg
