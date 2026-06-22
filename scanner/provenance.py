"""ID provenance sidecar.

The product catalog (``data/products.yaml``) stays flat and human-editable so
the single-line rewriter in :mod:`scanner.identifiers` keeps working. Anything
*about* an identifier - where it came from, when it was last verified, and the
verifier's verdict - lives here instead, keyed by ``"<product_key>.<field>"``.

This is what lets "verified" be a maintained property rather than a one-time
human claim: :mod:`scanner.verify_ids` writes a verdict + timestamp here, and
``add_id`` / the web "Add Product ID" form record the source URL a value came
from. Reads tolerate a missing or corrupt file (return ``{}``) so a bad sidecar
can never break a scan or the dashboard.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
PROVENANCE_PATH = ROOT / "data" / "id_provenance.json"

# Verdict vocabulary shared with scanner.verify_ids and scanner.confidence.
CONFIRMED = "CONFIRMED"
NOT_FOUND = "NOT_FOUND"
BLOCKED = "BLOCKED"
AMBIGUOUS = "AMBIGUOUS"
SUSPECT_FORMAT = "SUSPECT_FORMAT"
NO_KEY = "NO_KEY"
UNCHECKED = "UNCHECKED"
ERROR = "ERROR"

# Verdicts that mean "this ID should not be trusted until a human looks" -
# consumed by confidence (ID_SUSPECT) and the work queue.
SUSPECT_STATUSES = frozenset({NOT_FOUND, AMBIGUOUS, SUSPECT_FORMAT})


def key(product_key: str, field: str) -> str:
    return f"{product_key}.{field}"


def load(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Return the whole sidecar, or ``{}`` if missing/unreadable."""
    path = path or PROVENANCE_PATH
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(data: dict[str, dict[str, Any]], path: Path | None = None) -> None:
    path = path or PROVENANCE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def get(product_key: str, field: str, path: Path | None = None) -> dict[str, Any] | None:
    return load(path).get(key(product_key, field))


def record(
    product_key: str,
    field: str,
    *,
    source_url: str | None = None,
    status: str | None = None,
    verified_at: int | None = None,
    detail: str | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Merge the provided fields into one entry, preserving everything else.

    Only non-``None`` arguments are written, so recording a verification verdict
    never clobbers a previously stored ``sourceUrl`` and vice versa.
    """
    data = load(path)
    entry = dict(data.get(key(product_key, field)) or {})
    if source_url is not None:
        entry["sourceUrl"] = source_url
    if status is not None:
        entry["status"] = status
    if verified_at is not None:
        entry["verifiedAt"] = verified_at
    if detail is not None:
        entry["detail"] = detail
    data[key(product_key, field)] = entry
    save(data, path)
    return entry


def is_suspect(entry: dict[str, Any] | None) -> bool:
    return bool(entry) and entry.get("status") in SUSPECT_STATUSES
