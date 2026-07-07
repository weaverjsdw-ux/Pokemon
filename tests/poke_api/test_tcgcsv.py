from scanner.poke_api import tcgcsv


def test_card_number_of_reads_extended_data():
    product = {"productId": 1, "name": "Umbreon ex",
               "extendedData": [{"name": "Number", "value": "161/131"},
                                {"name": "Rarity", "value": "SIR"}]}
    assert tcgcsv.card_number_of(product) == "161/131"


def test_card_number_of_missing_returns_none():
    assert tcgcsv.card_number_of({"productId": 1, "extendedData": []}) is None


def test_pick_market_price_exact_subtype():
    rows = [{"productId": 5, "subTypeName": "Holofoil", "marketPrice": 12.5},
            {"productId": 5, "subTypeName": "Reverse Holofoil", "marketPrice": 20.0}]
    assert tcgcsv.pick_market_price(5, "Holofoil", rows) == 12.5


def test_pick_market_price_ambiguous_returns_none():
    rows = [{"productId": 5, "subTypeName": "Holofoil", "marketPrice": 12.5},
            {"productId": 5, "subTypeName": "Reverse Holofoil", "marketPrice": 20.0}]
    assert tcgcsv.pick_market_price(5, None, rows) is None  # never guess which printing


def test_pick_market_price_single_row_no_subtype_ok():
    rows = [{"productId": 9, "subTypeName": "Unopened", "marketPrice": 99.0}]
    assert tcgcsv.pick_market_price(9, None, rows) == 99.0


def test_pick_market_price_null_market_returns_none():
    rows = [{"productId": 5, "subTypeName": "Holofoil", "marketPrice": None}]
    assert tcgcsv.pick_market_price(5, "Holofoil", rows) is None


from unittest.mock import patch


class _Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


def test_fetch_products_returns_results():
    body = {"success": True, "results": [{"productId": 1, "name": "X"}]}
    with patch("scanner.poke_api.tcgcsv.requests.get", return_value=_Resp(200, body)):
        assert tcgcsv.fetch_products(3170) == [{"productId": 1, "name": "X"}]


def test_fetch_prices_degrades_on_non_200():
    with patch("scanner.poke_api.tcgcsv.requests.get", return_value=_Resp(403, None)):
        assert tcgcsv.fetch_prices(3170) == []


def test_fetch_groups_degrades_on_network_error():
    import requests as _rq
    with patch("scanner.poke_api.tcgcsv.requests.get", side_effect=_rq.RequestException):
        assert tcgcsv.fetch_groups() == []
