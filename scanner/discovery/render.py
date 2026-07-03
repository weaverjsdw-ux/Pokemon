"""Render a /poke sweep dict into the self-contained dashboard HTML.

Runs the STOP gate before producing any HTML — a bad row halts the render
rather than shipping a dashboard that overstates confidence.
"""
from __future__ import annotations

import html as html_lib
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from .schema import assert_sweep, row_from_dict

TEMPLATE_PATH = Path(__file__).with_name("template.html")


def _esc(value) -> str:
    return html_lib.escape(str(value), quote=True)


def _safe_href(url) -> str:
    """Escaped URL only when it is http(s); otherwise empty.

    Sweep data is untrusted (web-scraped / AI-derived), so a `javascript:` or
    `data:` source_url must never become a clickable href in the dashboard a
    human opens. Scheme allowlist before emit.
    """
    try:
        scheme = urlparse(str(url)).scheme.lower()
    except ValueError:
        return ""
    return _esc(url) if scheme in ("http", "https") else ""


def _badges_html(badges: list[str]) -> str:
    cls = {"STEAL": "badge-steal", "WARN": "badge-warn", "EST": "badge-est"}
    return "".join(
        f'<span class="badge {cls.get(b, "badge-est")}">{_esc(b)}</span>' for b in badges
    )


def _lens_html(tags: list[str]) -> str:
    return "".join(f'<span class="lens">{_esc(t)}</span>' for t in tags)


_POSITIVE_STOCK = {"in_stock", "limited"}


def _stock_html(d: dict) -> str:
    """Stock evidence cell: status + when it was checked + the buy link.

    Everything here is untrusted sweep data — evidence is escaped, buy_url
    goes through the same scheme allowlist as source_url. The operator can
    see *why* a row is (or is not) buyable without leaving the board.
    """
    status = str(d.get("stock_status") or "unknown")
    label = _esc(status.replace("_", " "))
    evidence = str(d.get("stock_evidence") or "")
    checked = str(d.get("stock_checked_at") or "")
    if status == "unknown" and not evidence:
        return f'<span class="muted stock-unknown">{label}</span>'
    bits = [f'<span class="stock stock-{_esc(status)}" '
            f'title="{_esc(evidence)}">{label}</span>']
    if status in _POSITIVE_STOCK:
        buy = _safe_href(d.get("buy_url", ""))
        if buy:
            bits.append(f'<a href="{buy}">buy</a>')
    if checked:
        bits.append(f'<span class="muted">{_esc(checked)}</span>')
    if evidence:
        bits.append(f'<span class="muted">{_esc(evidence)}</span>')
    return " ".join(bits)


def _deal_row_html(d: dict) -> str:
    comp = d.get("market_comp")
    comp_html = f'<span class="orig">${_esc(comp)}</span>' if comp is not None else ""
    pct = d.get("pct_off")
    pct_html = f"{_esc(pct)}%" if pct is not None else ""
    return (
        f'<tr data-source-url="{_safe_href(d.get("source_url",""))}" '
        f'data-captured-at="{_esc(d.get("captured_at",""))}">'
        f'<td>{_esc(d.get("item",""))}{_lens_html(d.get("lens_tags",[]))}'
        f'{_badges_html(d.get("badges",[]))}</td>'
        f'<td class="deal-price">${_esc(d.get("deal_price",""))}</td>'
        f'<td>{comp_html}</td><td>{pct_html}</td>'
        f'<td><a href="{_safe_href(d.get("source_url",""))}">{_esc(d.get("retailer",""))}</a> '
        f'<span class="muted">{_esc(d.get("captured_at",""))}</span></td>'
        f'<td>{_stock_html(d)}</td>'
        f'<td>{_esc(d.get("scanner_verdict",""))}</td></tr>'
    )


def _table(rows: list[dict]) -> str:
    if not rows:
        return '<div class="muted">None this sweep.</div>'
    body = "".join(_deal_row_html(d) for d in rows)
    return (
        "<table><thead><tr><th>Item</th><th>Deal</th><th>Market</th>"
        "<th>% Off</th><th>Retailer</th><th>Stock</th><th>Scanner</th></tr></thead>"
        f"<tbody>{body}</tbody></table>"
    )


def _category_key(d: dict) -> str:
    return str(d.get("category") or d.get("asset_class") or "other")


def render_sweep(sweep: dict, template: str | None = None) -> str:
    deals = sweep.get("deals", [])
    assert_sweep([row_from_dict(d) for d in deals])  # STOP gate before render

    tpl = template if template is not None else TEMPLATE_PATH.read_text(encoding="utf-8")

    steals = [d for d in deals if "STEAL" in d.get("badges", [])]
    watch_out = [d for d in deals if d.get("authenticity_risk") or d.get("warn_reason")]
    # Buyable now: only rows with VERIFIED positive stock evidence + a buy link.
    # Weak-comp rows qualify (they are genuinely buyable) and are shown, labeled,
    # not hidden. Unknown/negative/unverifiable stock stays in the reference
    # sections below. The STOP gate already guarantees a positive-stock row
    # carries evidence; this filter + the golden check are belt-and-suspenders.
    buyable = [d for d in deals
               if str(d.get("stock_status") or "") in _POSITIVE_STOCK
               and d.get("stock_evidence") and d.get("buy_url")]

    # category sections (every section id used in nav must exist)
    cats: dict[str, list[dict]] = {}
    for d in deals:
        cats.setdefault(_category_key(d), []).append(d)
    cat_sections = []
    cat_nav = []
    for key in sorted(cats):
        anchor = "cat-" + re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-")
        cat_nav.append(anchor)
        cat_sections.append(
            f'<section id="{anchor}"><h2>{_esc(key)}</h2>{_table(cats[key])}</section>'
        )

    nav_ids = ["freshness", "buyable-now", "watchlist", "top-steals", *cat_nav,
               "promo-codes", "bundled-offers", "watch-out", "sources"]
    nav_html = "".join(f'<a href="#{a}">{a.replace("-", " ").title()}</a>' for a in nav_ids)

    wl = sweep.get("watchlist_results", [])
    wl_html = "".join(
        f'<div>{_esc(w.get("item",""))} — '
        f'{"TARGET HIT" if w.get("hit") else "tracked"} '
        f'(target ${_esc(w.get("target_price",""))})</div>' for w in wl
    ) or '<div class="muted">No watchlist targets hit this sweep.</div>'

    promos = sweep.get("promo_codes", [])
    promo_html = "".join(
        f'<div><strong>{_esc(p.get("code",""))}</strong> — {_esc(p.get("desc",""))} '
        f'@ {_esc(p.get("retailer",""))} '
        f'(<a href="{_safe_href(p.get("source_url",""))}">src</a>)</div>' for p in promos
    ) or '<div class="muted">None.</div>'

    bundles = sweep.get("bundled_offers", [])
    bundle_html = "".join(
        f'<div>{_esc(b.get("title",""))} @ {_esc(b.get("retailer",""))} '
        f'(<a href="{_safe_href(b.get("source_url",""))}">src</a>)</div>' for b in bundles
    ) or '<div class="muted">None.</div>'

    watch_out_html = "".join(
        f'<div><strong>{_esc(d.get("item",""))}</strong> — '
        f'{_esc(d.get("warn_reason","flagged"))} '
        f'(<a href="{_safe_href(d.get("source_url",""))}">src</a>)</div>' for d in watch_out
    ) or '<div class="muted">Nothing flagged this sweep.</div>'

    sources = sweep.get("sources", [])
    sources_html = "".join(
        f'<div>{_esc(s.get("name",""))} — {_esc(s.get("tier",""))}/'
        f'{_esc(s.get("status",""))} <span class="muted">{_esc(s.get("note",""))}</span></div>'
        for s in sources
    ) or '<div class="muted">No sources recorded.</div>'

    freshness = (
        f'sweep {_esc(sweep.get("sweep_id",""))} · {len(deals)} items · '
        f'{len(steals)} steals · {_esc(sweep.get("notes",""))}'
    )

    out = tpl
    replacements = {
        "{{EVENT_TITLE}}": _esc(sweep.get("event", "")),
        "{{LAST_UPDATED}}": _esc(sweep.get("captured_window", "")),
        "{{SWEEP_ID}}": _esc(sweep.get("sweep_id", "")),
        "{{FRESHNESS}}": freshness,
    }
    for k, v in replacements.items():
        out = out.replace(k, v)
    injects = {
        "<!-- INJECT: NAV -->": nav_html,
        "<!-- INJECT: BUYABLE_NOW -->": _table(buyable),
        "<!-- INJECT: WATCHLIST -->": wl_html,
        "<!-- INJECT: TOP_STEALS -->": _table(steals),
        "<!-- INJECT: CATEGORY_SECTIONS -->": "".join(cat_sections),
        "<!-- INJECT: PROMO_CODES -->": promo_html,
        "<!-- INJECT: BUNDLED_OFFERS -->": bundle_html,
        "<!-- INJECT: WATCH_OUT -->": watch_out_html,
        "<!-- INJECT: SOURCES -->": sources_html,
    }
    for marker, value in injects.items():
        out = out.replace(marker, value)
    return out


def section_html(html: str, section_id: str) -> str:
    """Inner HTML of <section id="section_id">...</section> ("" if absent).
    Lets golden inspect a single section (e.g. buyable-now) in isolation."""
    m = re.search(rf'<section id="{re.escape(section_id)}">(.*?)</section>',
                  html, re.DOTALL)
    return m.group(1) if m else ""


def nav_anchors(html: str) -> list[str]:
    return re.findall(r'href="#([A-Za-z0-9\-_]+)"', html)


def element_ids(html: str) -> list[str]:
    return re.findall(r'id="([A-Za-z0-9\-_]+)"', html)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: python -m scanner.discovery.render <sweep.json> [-o out.html]")
        return 2
    sweep_path = Path(argv[0])
    out_path = None
    if "-o" in argv:
        out_path = Path(argv[argv.index("-o") + 1])
    sweep = json.loads(sweep_path.read_text(encoding="utf-8"))
    html = render_sweep(sweep)
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(html, encoding="utf-8")
        print(f"wrote {out_path}")
    else:
        sys.stdout.write(html)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
