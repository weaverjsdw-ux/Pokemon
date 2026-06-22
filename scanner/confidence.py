"""Source-Confidence model - the single backbone every panel reads from.

The codebase already knows two separate things about a retailer that nobody had
joined up:

  * configuration readiness  (enabled / supported / api-key / has-IDs) from
    :mod:`scanner.coverage`
  * runtime health           (healthy / degraded / blocked / no-data) from
    :mod:`scanner.health`

The operator's real question - "what, if anything, do I do about this source?" -
is the *union* of those. :func:`source_state` collapses both (plus the ID
Doctor's provenance verdicts) into one state by strict precedence, so the
summary badge, the board verdict line, the work queue, and the alert annotation
all read from the same truth instead of drifting.

This module is pure: it takes plain dict inputs and returns plain dicts. No I/O,
no globals, no network - which is what makes it trivial to test and safe to call
anywhere.
"""
from __future__ import annotations

from typing import Any

# States, in precedence order (first match wins). A retailer is in exactly one.
NOT_IMPLEMENTED = "NOT_IMPLEMENTED"   # adapter is a declared placeholder
DISABLED = "DISABLED"                 # supported, but turned off
NEEDS_API_KEY = "NEEDS_API_KEY"       # enabled, needs a key it doesn't have
NEEDS_ID = "NEEDS_ID"                 # enabled + ready, but 0 product IDs
BLOCKED = "BLOCKED"                   # 403/429 - not your fault, back off
PARSER_SUSPECT = "PARSER_SUSPECT"     # HTTP 200 but 0 rows - needs a code fix
ID_SUSPECT = "ID_SUSPECT"             # an ID failed verification - re-check it
DEGRADED = "DEGRADED"                 # transient errors / staleness
READY = "READY"                       # configured + has IDs, no result yet
WORKING = "WORKING"                   # healthy and producing rows

# How loud each state is. Higher = more operator attention. Drives the work
# queue ordering and the summary roll-up.
SEVERITY = {
    PARSER_SUSPECT: 80,
    BLOCKED: 70,
    ID_SUSPECT: 65,
    NEEDS_ID: 60,
    NEEDS_API_KEY: 55,
    DEGRADED: 40,
    DISABLED: 20,
    READY: 10,
    WORKING: 0,
    NOT_IMPLEMENTED: 0,
}

# States that are an operator to-do (have an actionable next step).
ACTIONABLE = frozenset(
    {NEEDS_ID, NEEDS_API_KEY, BLOCKED, PARSER_SUSPECT, ID_SUSPECT, DISABLED}
)


def source_state(
    slug: str,
    *,
    supported: bool,
    enabled: bool,
    online_only: bool = False,
    api_key_required: bool = False,
    api_key_set: bool = False,
    with_id: int = 0,
    total: int = 0,
    health_row: dict[str, Any] | None = None,
    id_suspect: bool = False,
    unsupported_reason: str = "",
) -> dict[str, Any]:
    """Return ``{state, label, detail, action, severity}`` for one retailer.

    ``health_row`` is a row from :func:`scanner.health.snapshot` (or ``None``).
    ``id_suspect`` is True when any of this retailer's IDs failed verification.
    """
    health_row = health_row or {}
    last_status = str(health_row.get("last_status") or "")
    hstate = str(health_row.get("state") or "unknown")
    http_status = health_row.get("last_http_status")
    has_run = bool(health_row.get("last_check_ts"))

    state, action = _classify(
        slug, supported, enabled, api_key_required, api_key_set, with_id,
        last_status, hstate, http_status, id_suspect, has_run,
    )
    return {
        "slug": slug,
        "state": state,
        "label": _LABELS[state],
        "detail": _detail(state, slug, with_id, total, http_status, unsupported_reason),
        "action": action,
        "severity": SEVERITY.get(state, 0),
        "actionable": state in ACTIONABLE,
        "onlineOnly": online_only,
        "withId": with_id,
        "total": total,
    }


def _classify(
    slug, supported, enabled, api_key_required, api_key_set, with_id,
    last_status, hstate, http_status, id_suspect, has_run,
):
    if not supported:
        return NOT_IMPLEMENTED, ""
    if not enabled:
        action = "Enable this source" if with_id else "Add IDs, then enable it"
        return DISABLED, action
    if api_key_required and not api_key_set:
        return NEEDS_API_KEY, "Add a free API key"
    if with_id == 0:
        return NEEDS_ID, "Add product IDs"
    if last_status == "BLOCKED" or http_status in (403, 429):
        action = "Back off; retries automatically"
        if slug == "target":
            action = "Back off; if it persists, RedSky key may be rotated (set TARGET_API_KEY)"
        return BLOCKED, action
    if last_status == "NO_DATA":
        return PARSER_SUSPECT, "Adapter likely needs a code fix"
    if id_suspect:
        return ID_SUSPECT, "Re-verify the flagged ID"
    if last_status in ("ERROR", "DISCOVERY_FAILED") or hstate in ("down", "degraded"):
        return DEGRADED, "Self-heals; watch it"
    if hstate == "healthy" or last_status == "OK":
        return WORKING, ""
    if not has_run:
        return READY, ""
    return WORKING, ""


_LABELS = {
    NOT_IMPLEMENTED: "not implemented",
    DISABLED: "disabled",
    NEEDS_API_KEY: "needs API key",
    NEEDS_ID: "needs IDs",
    BLOCKED: "blocked",
    PARSER_SUSPECT: "parser suspect",
    ID_SUSPECT: "ID suspect",
    DEGRADED: "degraded",
    READY: "ready",
    WORKING: "working",
}


def _detail(state, slug, with_id, total, http_status, unsupported_reason):
    if state == NOT_IMPLEMENTED:
        return unsupported_reason or "live checks need a dedicated adapter"
    if state == DISABLED:
        return f"{with_id}/{total} IDs ready" if with_id else "0 IDs; off"
    if state == NEEDS_API_KEY:
        return f"{with_id}/{total} IDs ready; add the key to activate"
    if state == NEEDS_ID:
        return f"0/{total} products have an ID for this source"
    if state == BLOCKED:
        code = f" (HTTP {http_status})" if http_status in (403, 429) else ""
        return f"endpoint blocked or rate-limited{code}"
    if state == PARSER_SUSPECT:
        return "HTTP 200 but no inventory rows parsed"
    if state == ID_SUSPECT:
        return "an ID failed verification; run the ID Doctor"
    if state == DEGRADED:
        return "recent errors or stale data"
    if state == READY:
        return f"{with_id}/{total} IDs ready; no scan result yet"
    return f"{with_id}/{total} IDs producing results"


def confidence_report(
    coverage: dict[str, Any],
    health_rows: list[dict[str, Any]],
    id_suspect_by_slug: dict[str, bool] | None = None,
) -> list[dict[str, Any]]:
    """Per-retailer confidence from already-computed payloads.

    ``coverage`` is :func:`scanner.coverage.coverage_report` output;
    ``health_rows`` is :func:`scanner.health.snapshot`; ``id_suspect_by_slug``
    flags retailers with a failed-verification ID (from the product payload).
    """
    health_by_slug = {row.get("slug"): row for row in health_rows}
    id_suspect_by_slug = id_suspect_by_slug or {}
    rows: list[dict[str, Any]] = []
    for r in coverage.get("retailers", []):
        slug = r["slug"]
        rows.append(
            source_state(
                slug,
                supported=bool(r.get("supported", True)),
                enabled=bool(r.get("enabled")),
                online_only=bool(r.get("onlineOnly")),
                api_key_required=bool(r.get("apiKeyRequired")),
                api_key_set=bool(r.get("apiKeySet")),
                with_id=int(r.get("withId") or 0),
                total=int(r.get("total") or 0),
                health_row=health_by_slug.get(slug),
                id_suspect=bool(id_suspect_by_slug.get(slug)),
            )
            | {"name": r.get("name", slug)}
        )
    return rows
