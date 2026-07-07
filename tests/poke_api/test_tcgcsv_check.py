from scanner.poke_api import tcgcsv_check


def _pair(diff_pct):
    return {"asset_key": f"a{diff_pct}", "tcgplayer_id": 1, "ppt_price": 100.0,
            "tcgcsv_price": 100.0 * (1 + diff_pct / 100.0), "diff_pct": diff_pct}


def test_pass_when_enough_pairs_all_within_tolerance():
    pairs = [_pair(0.0), _pair(0.5), _pair(1.0), _pair(1.5), _pair(1.9)]
    result = tcgcsv_check.sample_check(pairs)
    assert result["status"] == "pass"
    assert result["n"] == 5


def test_fail_when_any_pair_exceeds_tolerance():
    pairs = [_pair(0.0), _pair(0.5), _pair(1.0), _pair(1.5), _pair(3.0)]
    result = tcgcsv_check.sample_check(pairs)
    assert result["status"] == "fail"
    assert "tolerance" in result["reason"]


def test_fail_when_too_few_pairs():
    pairs = [_pair(0.0), _pair(0.5)]
    result = tcgcsv_check.sample_check(pairs)
    assert result["status"] == "fail"
    assert "n=2" in result["reason"] or "minimum" in result["reason"]
