"""Append-only observation ledger for /poke sweeps.

One immutable JSON object per line. Idempotent: a re-observed (kind, identity,
source, date) adds nothing. Corrections are appended as new lines, never edits.
This is the MARKET-OBSERVATION ledger; it is NOT the Phase-2 inventory ledger.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

VALID_KINDS = {"deal", "market_comp", "listing"}


def item_key(obs: dict) -> str:
    parts = [obs.get("set", ""), obs.get("item", ""), obs.get("variant", ""),
             obs.get("grade", ""), obs.get("condition", "")]
    return "|".join(str(p).strip().lower() for p in parts)


def entry_id(kind: str, ikey: str, source_url: str, capture_date: str) -> str:
    raw = f"{kind}|{ikey}|{source_url}|{capture_date}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def existing_ids(path) -> set[str]:
    path = Path(path)
    if not path.exists():
        return set()
    ids: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ids.add(json.loads(line)["entry_id"])
        except (json.JSONDecodeError, KeyError):
            continue
    return ids


def append_observation(path, obs: dict) -> bool:
    kind = obs.get("kind")
    if kind not in VALID_KINDS:
        raise ValueError(f"obs.kind must be one of {sorted(VALID_KINDS)}, got {kind!r}")
    path = Path(path)
    ikey = item_key(obs)
    eid = entry_id(kind, ikey, obs.get("source_url", ""), obs.get("capture_date", ""))
    if eid in existing_ids(path):
        return False
    record = {"entry_id": eid, "item_key": ikey, **obs}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return True
