"""Read-only dashboard. Stdlib only — no FastAPI, no extra install.

Launch with:

    python -m scanner.dashboard

then open http://127.0.0.1:8765/ in a browser. Shows recent hits from
hit_log, per-retailer health, and the configured product catalog.

Intentionally read-only: no editing config or muting products from the
browser. That's a Phase 3 add. The point is at-a-glance "is this thing
working and what has it caught lately." HTML is rendered server-side
and refreshes every 30s via a meta tag — no JS, no build step."""
from __future__ import annotations

import argparse
import html
import sqlite3
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from . import config as cfg_mod
from .http import default_client
from .log import configure as configure_logging, get_logger
from .state import DB_PATH

log = get_logger(__name__)


def _page(title: str, body: str) -> bytes:
    css = """
    body { font: 14px/1.5 -apple-system, system-ui, sans-serif; background: #111; color: #eee;
           margin: 0; padding: 24px; }
    h1 { font-size: 22px; margin: 0 0 6px; }
    h2 { font-size: 16px; margin: 28px 0 8px; color: #9cf; border-bottom: 1px solid #333; padding-bottom: 4px; }
    .sub { color: #888; font-size: 12px; margin-bottom: 16px; }
    table { width: 100%; border-collapse: collapse; margin-top: 4px; }
    th, td { padding: 6px 10px; text-align: left; border-bottom: 1px solid #222; vertical-align: top; }
    th { color: #9cf; font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }
    tr:hover { background: #1a1a1a; }
    .ok      { color: #4ade80; }
    .warn    { color: #fbbf24; }
    .err     { color: #f87171; }
    .pill    { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; }
    .pill.ok  { background: #052e16; color: #4ade80; }
    .pill.err { background: #450a0a; color: #f87171; }
    code { font-family: ui-monospace, SF Mono, Menlo, monospace; color: #aaa; }
    a { color: #9cf; }
    """
    return (
        "<!doctype html><html><head>"
        "<meta http-equiv=refresh content=30>"
        f"<title>{html.escape(title)}</title>"
        f"<style>{css}</style>"
        "</head><body>"
        f"<h1>{html.escape(title)}</h1>"
        f"{body}"
        "</body></html>"
    ).encode("utf-8")


def _render_recent_hits(db: sqlite3.Connection, limit: int = 40) -> str:
    rows = db.execute(
        "SELECT retailer, store_id, product_key, status, tier, url, price_cents, ts "
        "FROM hit_log ORDER BY ts DESC LIMIT ?",
        (limit,),
    ).fetchall()
    if not rows:
        return "<p class=sub>No alerts logged yet.</p>"
    out = ["<table><tr><th>When</th><th>Retailer</th><th>Store</th><th>Product</th>",
           "<th>Status</th><th>Tier</th><th>Price</th><th></th></tr>"]
    now = time.time()
    for retailer, store_id, product_key, status, tier, url, price_cents, ts in rows:
        age = _ago(now - ts)
        price = f"${price_cents/100:.2f}" if price_cents is not None else "—"
        link = f'<a href="{html.escape(url or "")}" target=_blank rel=noopener>open</a>' if url else ""
        out.append(
            f"<tr><td>{age}</td><td>{html.escape(retailer)}</td>"
            f"<td>{html.escape(store_id)}</td><td><code>{html.escape(product_key)}</code></td>"
            f"<td>{html.escape(status)}</td><td>{html.escape(tier)}</td>"
            f"<td>{price}</td><td>{link}</td></tr>"
        )
    out.append("</table>")
    return "".join(out)


def _render_health(snapshot: dict[str, dict[str, Any]]) -> str:
    if not snapshot:
        return "<p class=sub>No retailer activity yet (scanner may not be running).</p>"
    out = ["<table><tr><th>Retailer</th><th>Status</th><th>Requests/hour</th><th>Consecutive fails</th></tr>"]
    for retailer, h in sorted(snapshot.items()):
        pill = "<span class='pill err'>DISABLED</span>" if h.get("disabled") else "<span class='pill ok'>OK</span>"
        out.append(
            f"<tr><td>{html.escape(retailer)}</td><td>{pill}</td>"
            f"<td>{h.get('requests_last_hour', 0)}</td>"
            f"<td>{h.get('fails', 0)}</td></tr>"
        )
    out.append("</table>")
    return "".join(out)


def _render_products(cfg) -> str:
    selected = cfg_mod.selected_products(cfg)
    if not selected:
        return "<p class=sub>No products selected.</p>"
    out = ["<table><tr><th>Key</th><th>Name</th><th>Set</th><th>Type</th><th>Tier</th><th>Muted</th></tr>"]
    for key, prod in sorted(selected.items()):
        tier = prod.get("priority", "nice_to_have")
        muted = "yes" if prod.get("mute") else ""
        out.append(
            f"<tr><td><code>{html.escape(key)}</code></td>"
            f"<td>{html.escape(str(prod.get('name', '')))}</td>"
            f"<td>{html.escape(str(prod.get('set', '')))}</td>"
            f"<td>{html.escape(str(prod.get('type', '')))}</td>"
            f"<td>{html.escape(tier)}</td><td>{muted}</td></tr>"
        )
    out.append("</table>")
    return "".join(out)


def _ago(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


class _Handler(BaseHTTPRequestHandler):
    cfg: Any = None  # filled by main()

    def log_message(self, fmt: str, *args: Any) -> None:
        log.debug("HTTP %s - %s", self.address_string(), fmt % args)

    def do_GET(self) -> None:
        if self.path != "/":
            self.send_response(404)
            self.end_headers()
            return
        try:
            db = sqlite3.connect(DB_PATH)
            recent = _render_recent_hits(db)
            db.close()
        except sqlite3.Error as exc:
            recent = f"<p class=err>DB error: {html.escape(str(exc))}</p>"

        health = _render_health(default_client.health_snapshot())
        products = _render_products(self.cfg)

        body = (
            "<p class=sub>Read-only — refreshes every 30s.</p>"
            "<h2>Per-retailer health</h2>" + health +
            "<h2>Recent alerts</h2>" + recent +
            "<h2>Tracked products</h2>" + products
        )
        page = _page("Pokémon Scanner", body)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only scanner dashboard.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    configure_logging("INFO")
    _Handler.cfg = cfg_mod.load()
    srv = HTTPServer((args.host, args.port), _Handler)
    log.info("dashboard listening on http://%s:%d/", args.host, args.port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
