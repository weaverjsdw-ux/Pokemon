"""Interactive dashboard. Stdlib only — no FastAPI, no extra install.

Launch with:

    python -m scanner.dashboard

then open http://127.0.0.1:8765/ in a browser. Shows recent hits from
hit_log, per-retailer health, and the configured product catalog. POST
endpoints let you:

    - mute / unmute a product without editing products.yaml
    - mark "I bought it" on a recent alert (suppresses further alerts
      for that retailer+product+store for 6h, records 'bought' feedback)
    - mark an alert as false/too-slow/missed for the analytics ranker

Listens on 127.0.0.1 by default. If you bind externally (--host 0.0.0.0),
set `dashboard.token` in config.yaml; write endpoints require an
`X-Dashboard-Token` header matching that value. Read endpoints stay open
since nothing on them is sensitive (no addresses, no webhooks).
"""
from __future__ import annotations

import argparse
import html
import json
import sqlite3
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import analytics
from . import config as cfg_mod
from . import state as state_mod
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
    .pill.muted { background: #1e1b4b; color: #c4b5fd; }
    code { font-family: ui-monospace, SF Mono, Menlo, monospace; color: #aaa; }
    a { color: #9cf; }
    button { background: #2563eb; color: white; border: 0; padding: 4px 10px; border-radius: 4px;
             cursor: pointer; font-size: 12px; margin-right: 4px; }
    button.danger { background: #7f1d1d; }
    button.ghost { background: #333; color: #ccc; }
    form { display: inline; }
    .ok-flash  { background: #052e16; color: #4ade80; padding: 6px 12px; border-radius: 4px; margin: 8px 0; }
    .err-flash { background: #450a0a; color: #f87171; padding: 6px 12px; border-radius: 4px; margin: 8px 0; }
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
        "SELECT id, retailer, store_id, product_key, status, tier, url, price_cents, ts "
        "FROM hit_log ORDER BY ts DESC LIMIT ?",
        (limit,),
    ).fetchall()
    if not rows:
        return "<p class=sub>No alerts logged yet.</p>"
    out = ["<table><tr><th>When</th><th>Retailer</th><th>Store</th><th>Product</th>",
           "<th>Status</th><th>Tier</th><th>Price</th><th>Action</th></tr>"]
    now = time.time()
    for hit_id, retailer, store_id, product_key, status, tier, url, price_cents, ts in rows:
        age = _ago(now - ts)
        price = f"${price_cents/100:.2f}" if price_cents is not None else "—"
        link = f'<a href="{html.escape(url or "")}" target=_blank rel=noopener>open</a>' if url else ""
        actions = (
            f'<form method=post action=/actions/bought>'
            f'<input type=hidden name=hit_id value="{hit_id}">'
            f'<input type=hidden name=retailer value="{html.escape(retailer)}">'
            f'<input type=hidden name=product_key value="{html.escape(product_key)}">'
            f'<input type=hidden name=store_id value="{html.escape(store_id)}">'
            f'<button>Bought it</button></form>'
            f'<form method=post action=/actions/false>'
            f'<input type=hidden name=hit_id value="{hit_id}">'
            f'<button class=ghost>False alert</button></form>'
        )
        out.append(
            f"<tr><td>{age}</td><td>{html.escape(retailer)}</td>"
            f"<td>{html.escape(store_id)}</td><td><code>{html.escape(product_key)}</code></td>"
            f"<td>{html.escape(status)}</td><td>{html.escape(tier)}</td>"
            f"<td>{price}</td><td>{link} {actions}</td></tr>"
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


def _render_products(cfg, db: sqlite3.Connection) -> str:
    selected = cfg_mod.selected_products(cfg)
    if not selected:
        return "<p class=sub>No products selected.</p>"
    out = ["<table><tr><th>Key</th><th>Name</th><th>Set</th><th>Type</th><th>Tier</th>",
           "<th>Mute</th><th>Action</th></tr>"]
    for key, prod in sorted(selected.items()):
        tier = prod.get("priority", "nice_to_have")
        static_mute = bool(prod.get("mute"))
        runtime_mute = state_mod.is_runtime_muted(db, key)
        if static_mute:
            mute_pill = '<span class="pill muted">file</span>'
            action = '<span class=sub>edit products.yaml</span>'
        elif runtime_mute:
            mute_pill = '<span class="pill muted">dashboard</span>'
            action = (
                f'<form method=post action=/actions/unmute>'
                f'<input type=hidden name=product_key value="{html.escape(key)}">'
                f'<button class=ghost>Unmute</button></form>'
            )
        else:
            mute_pill = ""
            action = (
                f'<form method=post action=/actions/mute>'
                f'<input type=hidden name=product_key value="{html.escape(key)}">'
                f'<button class=danger>Mute</button></form>'
            )
        out.append(
            f"<tr><td><code>{html.escape(key)}</code></td>"
            f"<td>{html.escape(str(prod.get('name', '')))}</td>"
            f"<td>{html.escape(str(prod.get('set', '')))}</td>"
            f"<td>{html.escape(str(prod.get('type', '')))}</td>"
            f"<td>{html.escape(tier)}</td><td>{mute_pill}</td><td>{action}</td></tr>"
        )
    out.append("</table>")
    return "".join(out)


def _render_drop_pattern_suggestions(db: sqlite3.Connection, tz: str) -> str:
    suggestions = analytics.suggest_drop_windows(db, tz=tz)
    if not suggestions:
        return ("<p class=sub>Not enough alert history yet to suggest drop "
                "windows. Come back after a week or two of running.</p>")
    by_retailer: dict[str, list] = {}
    for s in suggestions:
        by_retailer.setdefault(s.retailer, []).append(s)
    out = ["<p class=sub>Detected from hit_log over the last 30 days. "
           "Promote into <code>drop_windows:</code> in config.yaml.</p>",
           "<pre style='background:#000;padding:12px;border-radius:6px;overflow:auto'>"]
    for retailer, windows in by_retailer.items():
        out.append(f"# {retailer}")
        # Group consecutive days with identical hours
        for w in windows:
            day = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][w.weekday]
            out.append(
                f"- retailers: [{retailer}]\n"
                f"  days:      [{day}]\n"
                f"  start:     '{w.start_hour:02d}:00'\n"
                f"  end:       '{w.end_hour:02d}:00'\n"
                f"  poll_interval_seconds: 60   # samples: {w.sample_count}\n"
            )
    out.append("</pre>")
    return "".join(out)


def _render_per_store(db: sqlite3.Connection) -> str:
    stats = analytics.per_store_hit_rate(db, limit=20)
    if not stats:
        return "<p class=sub>No store-level history yet.</p>"
    out = ["<table><tr><th>Retailer</th><th>Store</th><th>Hits (90d)</th>",
           "<th>Bought</th><th>Last hit</th></tr>"]
    now = time.time()
    for s in stats:
        out.append(
            f"<tr><td>{html.escape(s.retailer)}</td>"
            f"<td>{html.escape(s.store_id)}</td>"
            f"<td>{s.hits}</td><td>{s.bought}</td>"
            f"<td>{_ago(now - s.last_hit_ts)}</td></tr>"
        )
    out.append("</table>")
    return "".join(out)


def _render_feedback_quality(db: sqlite3.Connection) -> str:
    q = analytics.feedback_quality(db)
    if not q:
        return "<p class=sub>No alerts in the last 30 days.</p>"
    out = ["<table><tr><th>Retailer</th><th>Alerts (30d)</th>",
           "<th>Bought</th><th>False</th><th>Buy rate</th></tr>"]
    for retailer, s in sorted(q.items(), key=lambda kv: -kv[1]["alerts"]):
        rate = f"{s['ratio'] * 100:.0f}%" if s["alerts"] else "—"
        out.append(
            f"<tr><td>{html.escape(retailer)}</td>"
            f"<td>{s['alerts']}</td><td>{s['bought']}</td>"
            f"<td>{s['false']}</td><td>{rate}</td></tr>"
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
    cfg: Any = None
    token: str = ""

    def log_message(self, fmt: str, *args: Any) -> None:
        log.debug("HTTP %s - %s", self.address_string(), fmt % args)

    # --- routing ---

    def do_GET(self) -> None:
        if self.path == "/" or self.path.startswith("/?"):
            flash = ""
            qs = parse_qs(urlparse(self.path).query)
            if "ok" in qs:
                flash = f'<div class=ok-flash>{html.escape(qs["ok"][0])}</div>'
            elif "err" in qs:
                flash = f'<div class=err-flash>{html.escape(qs["err"][0])}</div>'
            return self._render_index(flash)
        if self.path == "/healthz":
            return self._json({"ok": True})
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        if not self._authorized():
            self._redirect("/?err=Forbidden")
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8") if length else ""
        form = {k: v[0] for k, v in parse_qs(body).items()}
        path = urlparse(self.path).path
        try:
            if path == "/actions/mute":
                self._action_mute(form, muted=True)
            elif path == "/actions/unmute":
                self._action_mute(form, muted=False)
            elif path == "/actions/bought":
                self._action_bought(form)
            elif path == "/actions/false":
                self._action_feedback(form, verdict="false")
            elif path == "/actions/missed":
                self._action_feedback(form, verdict="missed")
            elif path == "/actions/too_slow":
                self._action_feedback(form, verdict="too_slow")
            else:
                self._redirect("/?err=Unknown%20action")
        except Exception as exc:
            log.exception("dashboard action failed: %s", path)
            self._redirect(f"/?err={html.escape(str(exc))}")

    # --- pages ---

    def _render_index(self, flash: str = "") -> None:
        try:
            db = sqlite3.connect(DB_PATH)
            recent = _render_recent_hits(db)
            products = _render_products(self.cfg, db)
            store_stats = _render_per_store(db)
            quality = _render_feedback_quality(db)
            suggestions = _render_drop_pattern_suggestions(db, self.cfg.timezone)
            db.close()
        except sqlite3.Error as exc:
            recent = f"<p class=err>DB error: {html.escape(str(exc))}</p>"
            products = ""
            store_stats = ""
            quality = ""
            suggestions = ""

        health = _render_health(default_client.health_snapshot())
        body = (
            "<p class=sub>Click 'Mute' to silence a product. Click 'Bought it' on a recent alert to suppress further alerts for the same retailer+product+store for 6h.</p>"
            + flash +
            "<h2>Per-retailer health</h2>" + health +
            "<h2>Recent alerts</h2>" + recent +
            "<h2>Per-retailer alert quality (30d)</h2>" + quality +
            "<h2>Top stores (90d)</h2>" + store_stats +
            "<h2>Suggested drop windows</h2>" + suggestions +
            "<h2>Tracked products</h2>" + products
        )
        page = _page("Pokémon Scanner", body)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)

    # --- actions ---

    def _action_mute(self, form: dict, *, muted: bool) -> None:
        key = (form.get("product_key") or "").strip()
        if not key:
            return self._redirect("/?err=Missing%20product_key")
        with sqlite3.connect(DB_PATH) as db:
            state_mod.set_runtime_mute(db, key, muted)
        verb = "muted" if muted else "unmuted"
        self._redirect(f"/?ok=Product%20{html.escape(key)}%20{verb}")

    def _action_bought(self, form: dict) -> None:
        retailer = (form.get("retailer") or "").strip()
        product_key = (form.get("product_key") or "").strip()
        store_id = (form.get("store_id") or "").strip()
        hit_id = form.get("hit_id")
        if not (retailer and product_key and store_id):
            return self._redirect("/?err=Missing%20fields")
        with sqlite3.connect(DB_PATH) as db:
            state_mod.suppress_drop(
                db, retailer, product_key, store_id,
                duration_seconds=6 * 3600, reason="bought via dashboard",
            )
            state_mod.record_feedback(
                db, hit_id=int(hit_id) if hit_id else None,
                verdict="bought", note="dashboard",
            )
        self._redirect("/?ok=Suppressed%20further%20alerts%20for%206h")

    def _action_feedback(self, form: dict, *, verdict: str) -> None:
        hit_id = form.get("hit_id")
        if not hit_id:
            return self._redirect("/?err=Missing%20hit_id")
        with sqlite3.connect(DB_PATH) as db:
            state_mod.record_feedback(
                db, hit_id=int(hit_id), verdict=verdict, note="dashboard",
            )
        self._redirect(f"/?ok=Recorded%20{verdict}")

    # --- helpers ---

    def _authorized(self) -> bool:
        if not self.token:
            return True
        return self.headers.get("X-Dashboard-Token", "") == self.token

    def _redirect(self, location: str) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()

    def _json(self, payload: Any, status: int = 200) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Interactive scanner dashboard.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    configure_logging("INFO")
    _Handler.cfg = cfg_mod.load()
    _Handler.token = str((getattr(_Handler.cfg, "dashboard", None) or {}).get("token", "")).strip()
    srv = HTTPServer((args.host, args.port), _Handler)
    log.info(
        "dashboard listening on http://%s:%d/ (token=%s)",
        args.host, args.port, "set" if _Handler.token else "open (localhost only)",
    )
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
