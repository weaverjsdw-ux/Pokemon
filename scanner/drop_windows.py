"""Adaptive polling around known drop windows.

Most restocks happen at predictable times — Target Tuesday/Friday
mornings, Walmart Wednesday, Pokémon Center 1pm ET. Polling at the
default cadence misses the front edge of those windows; polling at the
window cadence all the time wastes traffic and trips rate limits.

Config schema (in config.yaml):

    drop_windows:
      - retailers: ["target"]
        days: [tue, fri]                  # weekday names (mon..sun) or "all"
        start: "06:00"
        end:   "10:00"
        poll_interval_seconds: 60         # override global cadence inside window
      - retailers: ["pokemoncenter"]
        days: ["mon", "tue", "wed", "thu", "fri"]
        start: "13:00"
        end:   "13:30"
        poll_interval_seconds: 30

Resolution at each scan tick is straightforward: pick the smallest
override across windows that are currently active for any enabled
retailer. If none are active, fall back to the global poll_interval."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time as dtime
from typing import Any
from zoneinfo import ZoneInfo

_WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


@dataclass
class DropWindow:
    retailers: list[str]
    days: set[int]           # 0=Mon..6=Sun; full set == "all"
    start: dtime
    end: dtime
    poll_interval_seconds: int

    def active_at(self, dt: datetime) -> bool:
        if dt.weekday() not in self.days:
            return False
        t = dt.time()
        if self.start <= self.end:
            return self.start <= t < self.end
        return t >= self.start or t < self.end


def _parse_hhmm(val: Any, field: str) -> dtime:
    s = str(val).strip()
    try:
        h, m = s.split(":")
        return dtime(int(h), int(m))
    except (ValueError, IndexError):
        raise SystemExit(f"config.yaml: drop_windows.{field} expects 'HH:MM', got {val!r}")


def _parse_days(raw: Any) -> set[int]:
    if raw in (None, "all", ["all"]):
        return set(range(7))
    if not isinstance(raw, list):
        raise SystemExit(f"config.yaml: drop_windows.days expects a list, got {raw!r}")
    out: set[int] = set()
    for d in raw:
        key = str(d).strip().lower()[:3]
        if key not in _WEEKDAYS:
            raise SystemExit(
                f"config.yaml: drop_windows.days has unknown day {d!r}; "
                f"use mon/tue/wed/thu/fri/sat/sun or 'all'."
            )
        out.add(_WEEKDAYS[key])
    return out


def parse(raw: Any) -> list[DropWindow]:
    if not raw:
        return []
    if not isinstance(raw, list):
        raise SystemExit("config.yaml: drop_windows must be a list of windows")
    out: list[DropWindow] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise SystemExit(f"config.yaml: drop_windows[{i}] must be a mapping")
        retailers = entry.get("retailers") or []
        if not isinstance(retailers, list) or not retailers:
            raise SystemExit(f"config.yaml: drop_windows[{i}].retailers required (non-empty list)")
        try:
            interval = int(entry.get("poll_interval_seconds", 0))
        except (TypeError, ValueError):
            raise SystemExit(f"config.yaml: drop_windows[{i}].poll_interval_seconds must be an int")
        if interval <= 0:
            raise SystemExit(
                f"config.yaml: drop_windows[{i}].poll_interval_seconds must be > 0"
            )
        out.append(
            DropWindow(
                retailers=[str(r).strip().lower() for r in retailers],
                days=_parse_days(entry.get("days")),
                start=_parse_hhmm(entry.get("start", "00:00"), "start"),
                end=_parse_hhmm(entry.get("end", "00:00"), "end"),
                poll_interval_seconds=interval,
            )
        )
    return out


def effective_interval(
    windows: list[DropWindow],
    enabled_retailers: list[str],
    default_seconds: int,
    *,
    now: datetime,
) -> tuple[int, list[str]]:
    """Return (seconds_until_next_pass, reason_tags).

    The reason tags name which window(s) are currently active so the
    scanner can log *why* it's polling faster than usual."""
    candidates: list[tuple[int, str]] = []
    enabled_set = {r.lower() for r in enabled_retailers}
    for w in windows:
        if not w.active_at(now):
            continue
        if not (set(w.retailers) & enabled_set):
            continue
        tag = "+".join(sorted(set(w.retailers) & enabled_set))
        candidates.append((w.poll_interval_seconds, tag))
    if not candidates:
        return default_seconds, []
    candidates.sort()
    fastest = candidates[0][0]
    tags = [tag for sec, tag in candidates if sec == fastest]
    return fastest, tags
