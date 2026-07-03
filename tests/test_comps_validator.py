"""Validator refusal + hard-stop paths. Zero network - clients injected."""
from scanner.comps import ppt_validator


class Cfg:
    market_api_key = "k"
    products = {"a": {"name": "A", "ppt_id": "1", "msrp": "$50"},
                "b": {"name": "B", "ppt_id": "2", "msrp": "$30"}}


class FakePpt:
    def __init__(self, rows):
        self.rows, self.calls = rows, 0
    def estimate(self, key, product, checked_at):
        row = self.rows[self.calls]
        self.calls += 1
        return row


class FakeEngine:
    def estimate(self, key, product, checked_at):
        return {"status": "ok", "estimate": "$100.00", "confidence": "high"}


def test_refuses_without_key(capsys):
    cfg = Cfg(); cfg.market_api_key = ""
    assert ppt_validator.main(["--products", "a", "--yes"], cfg=cfg) == 2
    assert "market.api_key" in capsys.readouterr().out


def test_refuses_without_yes(capsys):
    assert ppt_validator.main(["--products", "a"], cfg=Cfg()) == 2
    out = capsys.readouterr().out
    assert "--yes" in out and "1 credit" in out     # spend surfaced before refusal


def test_refuses_unknown_product(capsys):
    assert ppt_validator.main(["--products", "nope", "--yes"], cfg=Cfg()) == 2


def test_hard_stops_below_15_remaining(capsys):
    ppt = FakePpt([{"status": "ok", "estimate": "$99.00", "dailyRemaining": 9,
                    "creditsConsumed": 1}])
    rc = ppt_validator.main(["--products", "a,b", "--yes"], cfg=Cfg(),
                            ppt_client=ppt, engine=FakeEngine())
    assert rc == 1
    assert ppt.calls == 1                            # never touched product b
    assert "HARD STOP" in capsys.readouterr().out


def test_compares_and_reports_delta(capsys):
    ppt = FakePpt([{"status": "ok", "estimate": "$110.00", "dailyRemaining": 80,
                    "creditsConsumed": 1}])
    rc = ppt_validator.main(["--products", "a", "--yes"], cfg=Cfg(),
                            ppt_client=ppt, engine=FakeEngine())
    assert rc == 0
    out = capsys.readouterr().out
    assert "a" in out and "$110.00" in out and "$100.00" in out and "9.1%" in out
