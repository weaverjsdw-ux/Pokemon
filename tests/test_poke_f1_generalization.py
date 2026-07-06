"""Phase F.1 — independent-source generalization: parser hardening, the wrong-slug
record-boundary guard, the raw-condition recordability guard, the batch record CLI,
and the multi-asset gap matrix. Network-free (adapters fed canned HTML via a fake
session; resolvers/ledger exercised with tmp files)."""
from pathlib import Path

import pytest

from scanner import config as config_mod
from scanner.market import comp_from_row
from scanner.poke_api import independent_sources as indep
from scanner.poke_api import sources as sources_mod

FIX = Path(__file__).parent / "fixtures" / "comps"
UMBREON = (FIX / "pricecharting_umbreon_ex_161.html").read_text(encoding="utf-8")
CHARIZARD = (FIX / "pricecharting_charizard_ex_199.html").read_text(encoding="utf-8")
BLANKS = (FIX / "pricecharting_blank_prices.html").read_text(encoding="utf-8")


class _FakeSession:
    def __init__(self, text, status=200, exc=None):
        self._text, self._status, self._exc = text, status, exc

    def get(self, url, **kw):
        if self._exc is not None:
            raise self._exc
        return _FakeResp(self._text, self._status)


class _FakeResp:
    def __init__(self, text, status):
        self.text, self.status_code = text, status


# ---------------------------------------------------------------- parser hardening

def test_second_card_shape_parses_every_cell():
    """The six-cell #price_data layout generalizes to a different card/set (not overfit)."""
    parsed = indep.pricecharting_card_prices_from_html(CHARIZARD)
    assert parsed["blocked"] is False
    cells = parsed["cells"]
    assert cells["used_price"] == 399.99
    assert cells["graded_price"] == 408.53
    assert cells["manual_only_price"] == 1575.00       # comma price "$1,575.00" parses


def test_comma_price_parses():
    parsed = indep.pricecharting_card_prices_from_html(
        '<td id="used_price"><span class="price js-price">$12,345.67</span></td>')
    assert parsed["cells"]["used_price"] == 12345.67


def test_blank_and_dash_prices_yield_no_cells():
    parsed = indep.pricecharting_card_prices_from_html(BLANKS)
    assert parsed["blocked"] is False
    assert parsed["cells"] == {}                        # every cell is $- / empty


def test_page_number_extracted_from_h1():
    assert indep.pricecharting_page_number_from_html(CHARIZARD) == "199"


def test_page_number_none_when_absent():
    # the trimmed table-only fixture has no h1/title -> honest None (guard skipped)
    assert indep.pricecharting_page_number_from_html(UMBREON) is None
    assert indep.pricecharting_page_number_from_html("<div>no product name</div>") is None


# ---------------------------------------------------- wrong-slug guard (record boundary)

CHARIZARD_ASSET = {"asset_key": "charizard_ex_199_151_raw_nm", "asset_class": "raw",
                   "name": "Charizard ex 199", "set": "Scarlet & Violet 151",
                   "card_number": "199",
                   "pricecharting_slug": "pokemon-scarlet-&-violet-151/charizard-ex-199"}


def test_raw_adapter_correct_number_resolves_ok():
    q = indep.PriceChartingRawSource(session=_FakeSession(CHARIZARD)).fetch(
        CHARIZARD_ASSET, 1_700_000_000)
    assert q.status == "ok" and q.price == 399.99


def test_raw_adapter_wrong_slug_number_is_no_match():
    """An asset whose card_number is 199 pointed at the Umbreon (#161) page -> the page
    HAS a number and it differs -> no_match (wrong slug), never a wrong-card comp."""
    q = indep.PriceChartingRawSource(session=_FakeSession(UMBREON.replace(
        "<table", '<h1 id="product_name">Umbreon ex #161 Prismatic Evolutions</h1><table'))
    ).fetch(CHARIZARD_ASSET, 1_700_000_000)
    assert q.status == "no_match" and q.price is None
    assert "161" in q.detail and "199" in q.detail        # names both numbers


def test_graded_adapter_wrong_slug_number_is_no_match():
    graded = {**CHARIZARD_ASSET, "asset_key": "x", "asset_class": "graded",
              "grade_key": "psa10"}
    q = indep.PriceChartingGradedSource(session=_FakeSession(UMBREON.replace(
        "<table", '<h1 id="product_name">Umbreon ex #161</h1><table'))
    ).fetch(graded, 1_700_000_000)
    assert q.status == "no_match" and q.price is None


def test_no_card_number_skips_guard_resolves_ok():
    """No card_number on the asset -> the guard is skipped (never a false no_match)."""
    asset = {k: v for k, v in CHARIZARD_ASSET.items() if k != "card_number"}
    q = indep.PriceChartingRawSource(session=_FakeSession(CHARIZARD)).fetch(asset, 1_700_000_000)
    assert q.status == "ok" and q.price == 399.99


# ---------------------------------------------------- raw-condition recordability guard

def test_nm_raw_is_recordable():
    ok, _ = indep.raw_condition_recordable({"asset_class": "raw", "condition": "NM"})
    assert ok is True
    ok, _ = indep.raw_condition_recordable({"asset_class": "raw", "condition": ""})
    assert ok is True                                    # blank == NM-ish loose proxy


def test_lp_raw_is_not_recordable_off_ungraded():
    ok, reason = indep.raw_condition_recordable({"asset_class": "raw", "condition": "LP"})
    assert ok is False
    assert "condition" in reason.lower() and "ungraded" in reason.lower()


def test_graded_is_always_recordable_by_condition_rule():
    ok, _ = indep.raw_condition_recordable({"asset_class": "graded", "grade_key": "psa10"})
    assert ok is True                                    # the rule is raw-only


# ---------------------------------------------------------------- catalog (F.1 assets)

def test_real_assets_yaml_carries_f1_validation_set():
    """The committed asset catalog loads and carries the F.1 multi-set validation rows
    with verified slugs — a guard against a broken/edited YAML."""
    from scanner import config as cfg_mod
    from scanner.poke_api import catalog as catalog_mod

    assets = catalog_mod.load_assets(cfg_mod.ROOT / "data" / "poke" / "assets.yaml")
    for key in ("charizard_ex_199_151_raw_nm", "charizard_ex_199_151_psa10",
                "charizard_ex_199_151_cgc10", "pikachu_ex_238_ss_raw_nm",
                "pikachu_ex_238_ss_psa9", "sylveon_ex_156_raw_lp"):
        assert key in assets, key
    # exact verified slug, literal & preserved
    assert assets["charizard_ex_199_151_raw_nm"]["pricecharting_slug"] == \
        "pokemon-scarlet-&-violet-151/charizard-ex-199"
    # grade_key derivation across graders
    assert assets["charizard_ex_199_151_psa10"]["grade_key"] == "psa10"
    assert assets["charizard_ex_199_151_cgc10"]["grade_key"] == "cgc10"
    assert assets["pikachu_ex_238_ss_psa9"]["grade_key"] == "psa9"
    assert assets["sylveon_ex_156_raw_lp"]["condition"] == "LP"


def test_unsupported_grade_asset_degrades_to_no_match():
    """CGC 10 has no exact PriceCharting cell -> honest no_match (never a nearest guess),
    and it never even fetches (grade check precedes the network call)."""
    cgc10 = {"asset_class": "graded", "name": "Charizard ex 199",
             "set": "Scarlet & Violet 151", "card_number": "199", "grade_key": "cgc10",
             "pricecharting_slug": "pokemon-scarlet-&-violet-151/charizard-ex-199"}

    class _Boom:
        def get(self, *a, **k):
            raise AssertionError("unsupported grade must not hit the network")

    q = indep.PriceChartingGradedSource(session=_Boom()).fetch(cgc10, 1_700_000_000)
    assert q.status == "no_match" and q.price is None


# ---------------------------------------------------------------- batch record CLI

import json  # noqa: E402

from scanner.poke_api import edge_cli, history, router  # noqa: E402


class _FailingCardClient:
    """Any billed call is a test failure — proves the batch never touches the PPT client."""
    def raw_quote(self, asset, checked_at):
        raise AssertionError("record-asset-comps must not call the PPT card client")

    def graded_smart(self, asset, checked_at):
        raise AssertionError("record-asset-comps must not call the PPT card client")


_CHAR_RAW = {"asset_class": "raw", "name": "Charizard ex 199", "set": "Scarlet & Violet 151",
             "card_number": "199", "condition": "NM",
             "pricecharting_slug": "pokemon-scarlet-&-violet-151/charizard-ex-199"}
_PIKA_RAW = {"asset_class": "raw", "name": "Pikachu ex 238", "set": "Surging Sparks",
             "card_number": "238", "condition": "NM",
             "pricecharting_slug": "pokemon-surging-sparks/pikachu-ex-238"}
_SYL_LP = {"asset_class": "raw", "name": "Sylveon ex 156", "set": "Prismatic Evolutions",
           "card_number": "156", "condition": "LP",
           "pricecharting_slug": "pokemon-prismatic-evolutions/sylveon-ex-156"}


def _deps_indep(*, assets, ledger_path, independent_sources=True, today="2026-07-06"):
    cfg = config_mod.from_mapping({
        "locations": {"home": "A", "work": "B"},
        "poke": {"independent_sources": independent_sources}})
    return router.PokeApiDeps(
        products={}, assets=assets, read_observations=lambda: [],
        comp_provider=None, today=today, cfg=cfg, ledger_path=ledger_path,
        card_client=_FailingCardClient())


def _canned(source_price):
    """A resolver stub returning a pricecharting-sourced legacy row (never network)."""
    def _stub(asset, **k):
        return {"estimate": f"{source_price:.2f}", "confidence": "low",
                "sources": [{"source": "tcgplayer", "status": "blocked", "price": None},
                            {"source": "pricecharting", "status": "ok", "price": source_price}],
                "sourceUrl": "https://www.pricecharting.com/game/x",
                "compBasis": "PriceCharting Ungraded"}
    return _stub


def test_batch_dry_run_writes_nothing(tmp_path, monkeypatch, capsys):
    from scanner.poke_api import sources as s
    monkeypatch.setattr(s, "resolve_independent_asset_row", _canned(399.99))
    ledger = tmp_path / "price_history.jsonl"
    deps = _deps_indep(assets={"c": _CHAR_RAW, "p": _PIKA_RAW}, ledger_path=ledger)
    rc = edge_cli.main(["record-asset-comps", "--refresh-independent",
                        "--assets", "c,p", "--dry-run"], deps=deps)
    assert rc == 0
    assert not ledger.exists()                    # dry-run persists nothing
    out = capsys.readouterr().out.lower()
    assert "preview" in out or "would" in out


def test_batch_yes_persists_all_with_real_slug(tmp_path, monkeypatch):
    from scanner.poke_api import sources as s
    monkeypatch.setattr(s, "resolve_independent_asset_row", _canned(325.50))
    ledger = tmp_path / "price_history.jsonl"
    deps = _deps_indep(assets={"c": _CHAR_RAW, "p": _PIKA_RAW}, ledger_path=ledger)
    rc = edge_cli.main(["record-asset-comps", "--refresh-independent",
                        "--assets", "c,p", "--yes"], deps=deps)
    assert rc == 0
    rows = history.read_ledger(ledger).observations
    assert len(rows) == 2
    assert {r["source"] for r in rows} == {"pricecharting"}    # never ppt_cards/tcgplayer
    assert all(r["comp"] == 325.50 for r in rows)


def test_batch_no_yes_no_dry_run_is_preview(tmp_path, monkeypatch, capsys):
    from scanner.poke_api import sources as s
    monkeypatch.setattr(s, "resolve_independent_asset_row", _canned(399.99))
    ledger = tmp_path / "price_history.jsonl"
    deps = _deps_indep(assets={"c": _CHAR_RAW}, ledger_path=ledger)
    rc = edge_cli.main(["record-asset-comps", "--refresh-independent", "--assets", "c"], deps=deps)
    assert rc == 0
    assert not ledger.exists()                    # neither --yes nor --dry-run -> safe preview


def test_batch_gate_off_refuses(tmp_path):
    ledger = tmp_path / "price_history.jsonl"
    deps = _deps_indep(assets={"c": _CHAR_RAW}, ledger_path=ledger, independent_sources=False)
    rc = edge_cli.main(["record-asset-comps", "--refresh-independent",
                        "--assets", "c", "--yes"], deps=deps)
    assert rc == 2
    assert not ledger.exists()


def test_batch_skips_non_nm_raw_without_network(tmp_path, monkeypatch):
    """A raw LP asset must NOT be auto-recorded off Ungraded — the condition guard fires
    BEFORE any resolve/network call (records nothing)."""
    from scanner.poke_api import sources as s

    def _explode(asset, **k):
        raise AssertionError("LP raw must be skipped before the resolver/network")
    monkeypatch.setattr(s, "resolve_independent_asset_row", _explode)
    ledger = tmp_path / "price_history.jsonl"
    deps = _deps_indep(assets={"syl": _SYL_LP}, ledger_path=ledger)
    rc = edge_cli.main(["record-asset-comps", "--refresh-independent",
                        "--assets", "syl", "--yes"], deps=deps)
    assert rc == 0                                 # honest skip, not an error
    assert not ledger.exists()


def test_batch_json_reports_zero_credits(tmp_path, monkeypatch, capsys):
    from scanner.poke_api import sources as s
    monkeypatch.setattr(s, "resolve_independent_asset_row", _canned(399.99))
    ledger = tmp_path / "price_history.jsonl"
    deps = _deps_indep(assets={"c": _CHAR_RAW}, ledger_path=ledger)
    edge_cli.main(["record-asset-comps", "--refresh-independent", "--assets", "c",
                   "--dry-run", "--json"], deps=deps)
    data = json.loads(capsys.readouterr().out)
    assert data["credits_spent"] == 0
    assert data["results"][0]["source"] == "pricecharting"


def test_batch_requires_refresh_independent(tmp_path):
    ledger = tmp_path / "price_history.jsonl"
    deps = _deps_indep(assets={"c": _CHAR_RAW}, ledger_path=ledger)
    rc = edge_cli.main(["record-asset-comps", "--assets", "c", "--yes"], deps=deps)
    assert rc == 1                                 # batch supports only the independent path


def test_batch_unknown_asset_is_flagged(tmp_path, monkeypatch, capsys):
    from scanner.poke_api import sources as s
    monkeypatch.setattr(s, "resolve_independent_asset_row", _canned(399.99))
    ledger = tmp_path / "price_history.jsonl"
    deps = _deps_indep(assets={"c": _CHAR_RAW}, ledger_path=ledger)
    rc = edge_cli.main(["record-asset-comps", "--refresh-independent",
                        "--assets", "c,nope", "--yes"], deps=deps)
    assert rc == 1                                 # a mistyped key is surfaced
    out = capsys.readouterr().out
    assert "nope" in out
    rows = history.read_ledger(ledger).observations
    assert len(rows) == 1                          # the valid one still recorded


# ---------------------------------------------------------------- gap matrix (audit)

from scanner.poke_api import divergence as dv  # noqa: E402

_M_ASSETS = {
    "umb_psa10": {"asset_class": "graded", "name": "Umbreon ex 161",
                  "set": "Prismatic Evolutions", "card_number": "161",
                  "grader": "PSA", "grade": "10", "grade_key": "psa10"},
    "umb_psa9": {"asset_class": "graded", "name": "Umbreon ex 161",
                 "set": "Prismatic Evolutions", "card_number": "161",
                 "grader": "PSA", "grade": "9", "grade_key": "psa9"},
    "syl_lp": {"asset_class": "raw", "name": "Sylveon ex 156",
               "set": "Prismatic Evolutions", "card_number": "156", "condition": "LP"},
}


def _ik(key):
    return history.item_key_for_asset(_M_ASSETS[key])


def _obs(key, source, comp, date, conf="low"):
    return {"item_key": _ik(key), "kind": "market_comp", "comp": comp,
            "capture_date": date, "source": source, "comp_confidence": conf}


def _matrix_deps(observations):
    cfg = config_mod.from_mapping({"locations": {"home": "A", "work": "B"}})
    return router.PokeApiDeps(
        products={}, assets=_M_ASSETS, read_observations=lambda: list(observations),
        comp_provider=None, today="2026-07-06", cfg=cfg)


def test_matrix_row_has_all_required_fields_and_cross_source():
    obs = [_obs("umb_psa10", "pricecharting", 7013.08, "2026-07-06"),
           _obs("umb_psa10", "ppt_cards", 6925.50, "2026-07-05", conf="high")]
    res = dv.audit_matrix(_matrix_deps(obs), asset_keys=["umb_psa10"])
    r = res["rows"][0]
    for f in ("asset_key", "asset_class", "condition_or_grade_key", "ours", "ours_source",
              "ours_capture_date", "ppt_reference", "ppt_capture_date", "delta_pct",
              "classification", "cross_source_validated", "defensibility", "notes"):
        assert f in r, f
    assert r["classification"] == "agree"            # ~1.3% delta
    assert r["ours_source"] == "pricecharting"
    assert r["cross_source_validated"] is True
    assert r["asset_class"] == "graded"
    assert r["condition_or_grade_key"] == "psa10"
    assert res["failed"] is False and res["credits_spent"] == 0


def test_matrix_new_card_no_external_reference():
    obs = [_obs("umb_psa9", "pricecharting", 1554.05, "2026-07-06")]  # no ppt ref
    r = dv.audit_matrix(_matrix_deps(obs), asset_keys=["umb_psa9"])["rows"][0]
    assert r["classification"] == "no_external_reference"
    assert r["ppt_reference"] is None
    assert r["cross_source_validated"] is False


def test_matrix_no_independent_reference():
    obs = [_obs("umb_psa10", "ppt_cards", 6925.50, "2026-07-05")]     # only a PPT local
    r = dv.audit_matrix(_matrix_deps(obs), asset_keys=["umb_psa10"])["rows"][0]
    assert r["classification"] == "no_independent_reference"
    assert r["ours"] is None


def test_matrix_unexplained_material_fails():
    obs = [_obs("umb_psa10", "pricecharting", 5000.0, "2026-07-06", conf="high"),
           _obs("umb_psa10", "ppt_cards", 7000.0, "2026-07-06", conf="high")]  # ~40%, PSA-exact
    res = dv.audit_matrix(_matrix_deps(obs), asset_keys=["umb_psa10"])
    r = res["rows"][0]
    assert r["classification"] == "unexplained_material_divergence"
    assert res["failed"] is True                     # a material unexplained gap fails


def test_matrix_grade_mapping_difference_non_blocking():
    """Demonstrated via constructed observations: a grader-agnostic Grade-9 proxy diverging
    from a PSA-9-specific external number is an explained grade-mapping gap, not blocking."""
    obs = [_obs("umb_psa9", "pricecharting", 1000.0, "2026-07-06", conf="low"),
           _obs("umb_psa9", "ppt_cards", 1300.0, "2026-07-06", conf="low")]     # ~30%
    res = dv.audit_matrix(_matrix_deps(obs), asset_keys=["umb_psa9"])
    r = res["rows"][0]
    assert r["classification"] == "grade_mapping_difference"
    assert res["failed"] is False


def test_matrix_raw_condition_difference_non_blocking():
    """Demonstrated via constructed observations: an Ungraded-vs-condition gap on a non-NM
    raw is explained (condition), not blocking."""
    obs = [_obs("syl_lp", "pricecharting", 500.0, "2026-07-06", conf="low"),
           _obs("syl_lp", "ppt_cards", 650.0, "2026-07-06", conf="low")]        # ~30%
    res = dv.audit_matrix(_matrix_deps(obs), asset_keys=["syl_lp"])
    r = res["rows"][0]
    assert r["classification"] == "raw_condition_difference"
    assert res["failed"] is False


def test_matrix_tcgplayer_not_counted_independent():
    """TCGplayer's market number == PPT's (Phase F finding), so a tcgplayer comp agreeing
    with ppt_cards is NOT a genuine cross-source validation."""
    obs = [_obs("umb_psa10", "tcgplayer", 6925.50, "2026-07-06"),
           _obs("umb_psa10", "ppt_cards", 6925.50, "2026-07-06")]
    r = dv.audit_matrix(_matrix_deps(obs), asset_keys=["umb_psa10"])["rows"][0]
    assert r["classification"] == "agree"
    assert r["cross_source_validated"] is False      # tcgplayer correlated with PPT


def test_matrix_categories_cover_required_vocabulary():
    required = {"agree", "no_external_reference", "no_independent_reference",
                "source_policy_difference", "mapping_error", "grade_mapping_difference",
                "raw_condition_difference", "stale_local", "stale_external",
                "confidence_method_difference", "unexplained_material_divergence"}
    assert required <= set(dv.MATRIX_CATEGORIES)


def test_matrix_cli_flag_prints_rows(tmp_path, capsys):
    obs = [_obs("umb_psa10", "pricecharting", 7013.08, "2026-07-06"),
           _obs("umb_psa10", "ppt_cards", 6925.50, "2026-07-05", conf="high")]
    deps = _matrix_deps(obs)
    deps.ledger_path = tmp_path / "x.jsonl"
    rc = edge_cli.main(["divergence-audit", "--local", "--matrix",
                        "--assets", "umb_psa10", "--json"], deps=deps)
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["mode"] == "local-matrix"
    assert data["rows"][0]["cross_source_validated"] is True
