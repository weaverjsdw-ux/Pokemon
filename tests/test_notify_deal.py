"""DealAlert payload + Notifier.send_deal (console line + Discord embed + ntfy).

The deal alert is the user-facing output of the verified-buyable pipeline: it
must carry the buy link, the verified price, the comp + its confidence, the
fee-adjusted verdict, and the stock-evidence timestamp - so a human can act
without guessing. Quiet hours suppress the ntfy push only (Discord stays a
silent history)."""
from __future__ import annotations

import json

from scanner.notify import DealAlert, Notifier


def _deal(**kw):
    base = dict(
        item="Prismatic Evolutions ETB",
        retailer="Marketplace seller",
        source_adapter="ebay_browse",
        listing_id="v1|123",
        buy_url="https://www.ebay.com/itm/123",
        verified_price=39.99,
        msrp=49.99,
        comp=72.00,
        comp_confidence="high",
        comp_basis="min(tcgplayer,pricecharting) agree@20%",
        pct_off=44,
        verdict_headline="BUY · +$18.00 net, 42% ROI",
        stock_status="in_stock",
        stock_evidence="availability=InStock price=39.99",
        checked_at="2026-07-03T12:00:00+00:00",
        badges=["STEAL"],
        warn_flags=[],
    )
    base.update(kw)
    return DealAlert(**base)


class _PostSpy:
    def __init__(self):
        self.posts = []

    def __call__(self, url, data=None, headers=None, timeout=None):
        self.posts.append({"url": url, "data": data, "headers": headers})

        class R:
            status_code = 200
        return R()

    def to(self, needle):
        return [p for p in self.posts if needle in p["url"]]


def test_line_carries_buy_price_comp_verdict_and_timestamp():
    line = _deal().line()
    assert "https://www.ebay.com/itm/123" in line      # buy URL
    assert "39.99" in line                              # verified price
    assert "high" in line                               # comp confidence
    assert "BUY · +$18.00 net, 42% ROI" in line         # verdict
    assert "2026-07-03T12:00:00+00:00" in line          # evidence timestamp


def test_discord_embed_carries_buy_price_comp_confidence_verdict_timestamp(monkeypatch):
    spy = _PostSpy()
    monkeypatch.setattr("scanner.notify.requests.post", spy)
    Notifier(discord_webhook="https://discord.test/hook").send_deal(_deal())
    payload = json.loads(spy.to("discord.test")[0]["data"])
    embed = payload["embeds"][0]
    blob = json.dumps(embed)
    assert embed["url"] == "https://www.ebay.com/itm/123"
    assert "39.99" in blob                               # verified price
    assert "72" in blob                                  # comp
    assert "high" in blob                                # comp confidence
    assert "BUY" in blob                                 # verdict
    assert "2026-07-03T12:00:00+00:00" in blob           # checked timestamp


def test_ntfy_body_carries_deal_details(monkeypatch):
    spy = _PostSpy()
    monkeypatch.setattr("scanner.notify.requests.post", spy)
    Notifier(ntfy_topic="poke-deals").send_deal(_deal(), push=True)
    ntfy = spy.to("ntfy.sh")
    assert len(ntfy) == 1
    body = ntfy[0]["data"].decode("utf-8") if isinstance(ntfy[0]["data"], bytes) else ntfy[0]["data"]
    assert "39.99" in body and "https://www.ebay.com/itm/123" in body


def test_quiet_hours_push_false_suppresses_ntfy_but_keeps_discord(monkeypatch):
    spy = _PostSpy()
    monkeypatch.setattr("scanner.notify.requests.post", spy)
    n = Notifier(discord_webhook="https://discord.test/hook", ntfy_topic="poke-deals")
    n.send_deal(_deal(), push=False)
    assert len(spy.to("discord.test")) == 1      # Discord still posts (silent history)
    assert spy.to("ntfy.sh") == []               # ntfy push suppressed


def test_push_true_sends_both_channels(monkeypatch):
    spy = _PostSpy()
    monkeypatch.setattr("scanner.notify.requests.post", spy)
    n = Notifier(discord_webhook="https://discord.test/hook", ntfy_topic="poke-deals")
    n.send_deal(_deal(), push=True)
    assert len(spy.to("discord.test")) == 1
    assert len(spy.to("ntfy.sh")) == 1


def test_unsafe_buy_url_filtered_from_embed_and_ntfy(monkeypatch):
    spy = _PostSpy()
    monkeypatch.setattr("scanner.notify.requests.post", spy)
    n = Notifier(discord_webhook="https://discord.test/hook", ntfy_topic="poke-deals")
    n.send_deal(_deal(buy_url="javascript:alert(1)"), push=True)
    discord_blob = spy.to("discord.test")[0]["data"]
    assert "javascript:alert" not in discord_blob
    ntfy_headers = json.dumps(spy.to("ntfy.sh")[0]["headers"])
    assert "javascript:alert" not in ntfy_headers


def test_console_only_when_no_channels_configured(monkeypatch, capsys):
    spy = _PostSpy()
    monkeypatch.setattr("scanner.notify.requests.post", spy)
    Notifier().send_deal(_deal())
    assert spy.posts == []                        # no network sinks configured
    assert "Prismatic Evolutions ETB" in capsys.readouterr().out
