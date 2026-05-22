"""Analytics over hit_log + feedback.

The scan loop is dumb on its own — same cadence regardless of when drops
actually happen for the retailers you watch. After a few weeks of data
in hit_log, we can ask the obvious question: when did alerts *actually*
fire? Group by (retailer, weekday, hour-of-day) and the natural drop
windows fall out.

This module produces:

  - drop_pattern_histogram(): per-retailer 7×24 grid of alert counts.
  - suggest_drop_windows():   collapses dense cells into proposed
    drop_window config entries the user can paste into config.yaml.
  - per_store_hit_rate():     per (retailer, store_id) hit counts and
    feedback-bought counts. Used by the dashboard's 'best stores' panel
    and (Phase 3 next item) by the scheduler to poll productive stores
    more often.
  - feedback_quality():       per-retailer 'bought' / total ratio.
    A retailer with lots of alerts and no buys is producing noise.

Everything here is read-only; the scan loop doesn't depend on it.
The user (or a future Phase 3 commit) can promote suggestions into
config.yaml manually."""
from __future__ import annotations

import sqlite3
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

_WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def drop_pattern_histogram(
    db: sqlite3.Connection,
    *,
    days_back: int = 30,
    tz: str = "UTC",
) -> dict[str, list[list[int]]]:
    """Per-retailer 7×24 grid (rows = weekday Mon..Sun, cols = hour 0..23)
    of alert counts. Timestamps are converted to the supplied timezone
    before bucketing — drop windows are local concepts."""
    cutoff = int(time.time()) - days_back * 86400
    rows = db.execute(
        "SELECT retailer, ts FROM hit_log WHERE ts >= ?",
        (cutoff,),
    ).fetchall()
    out: dict[str, list[list[int]]] = {}
    zone = ZoneInfo(tz)
    for retailer, ts in rows:
        grid = out.setdefault(retailer, [[0] * 24 for _ in range(7)])
        dt = datetime.fromtimestamp(ts, zone)
        grid[dt.weekday()][dt.hour] += 1
    return out


@dataclass
class SuggestedWindow:
    retailer: str
    weekday: int        # 0..6, Mon..Sun
    start_hour: int     # inclusive
    end_hour: int       # exclusive
    sample_count: int


def suggest_drop_windows(
    db: sqlite3.Connection,
    *,
    days_back: int = 30,
    tz: str = "UTC",
    min_samples_per_cell: int = 2,
    min_window_samples: int = 4,
) -> list[SuggestedWindow]:
    """Collapse dense cells in the histogram into contiguous (weekday,
    start, end) blocks. A cell qualifies when it had at least
    `min_samples_per_cell` alerts; a window is only emitted when its
    total alert count crosses `min_window_samples`.

    The thresholds err on the side of *fewer* suggestions — false
    positives here would lead the user to poll the wrong window faster
    than the global cadence."""
    grids = drop_pattern_histogram(db, days_back=days_back, tz=tz)
    out: list[SuggestedWindow] = []
    for retailer, grid in grids.items():
        for weekday, row in enumerate(grid):
            i = 0
            while i < 24:
                if row[i] < min_samples_per_cell:
                    i += 1
                    continue
                start = i
                while i < 24 and row[i] >= min_samples_per_cell:
                    i += 1
                total = sum(row[start:i])
                if total >= min_window_samples:
                    out.append(SuggestedWindow(
                        retailer=retailer,
                        weekday=weekday,
                        start_hour=start,
                        end_hour=i,
                        sample_count=total,
                    ))
    return out


@dataclass
class StoreStats:
    retailer: str
    store_id: str
    hits: int
    bought: int       # feedback rows with verdict='bought'
    last_hit_ts: int  # unix


def per_store_hit_rate(
    db: sqlite3.Connection, *, days_back: int = 90, limit: int = 50,
) -> list[StoreStats]:
    cutoff = int(time.time()) - days_back * 86400
    counts = db.execute(
        "SELECT retailer, store_id, COUNT(*), MAX(ts) "
        "FROM hit_log WHERE ts >= ? GROUP BY retailer, store_id",
        (cutoff,),
    ).fetchall()
    bought_by_key: dict[tuple[str, str], int] = defaultdict(int)
    for row in db.execute(
        "SELECT h.retailer, h.store_id, COUNT(*) "
        "FROM feedback f JOIN hit_log h ON f.hit_id = h.id "
        "WHERE f.verdict = 'bought' AND h.ts >= ? "
        "GROUP BY h.retailer, h.store_id",
        (cutoff,),
    ):
        bought_by_key[(row[0], row[1])] = row[2]
    stats = [
        StoreStats(
            retailer=retailer,
            store_id=store_id,
            hits=hits,
            bought=bought_by_key.get((retailer, store_id), 0),
            last_hit_ts=last_ts,
        )
        for retailer, store_id, hits, last_ts in counts
    ]
    stats.sort(key=lambda s: (-s.bought, -s.hits))
    return stats[:limit]


def feedback_quality(
    db: sqlite3.Connection, *, days_back: int = 30,
) -> dict[str, dict[str, Any]]:
    """Per-retailer summary: alert volume + bought/total ratio.

    A retailer producing lots of alerts and no 'bought' verdicts is
    probably surfacing noise the user finds useless. The scanner doesn't
    act on this automatically — the user reads it on the dashboard and
    decides whether to disable / mute / tighten that adapter."""
    cutoff = int(time.time()) - days_back * 86400
    hits = {
        row[0]: {"alerts": row[1], "bought": 0, "false": 0, "ratio": 0.0}
        for row in db.execute(
            "SELECT retailer, COUNT(*) FROM hit_log WHERE ts >= ? GROUP BY retailer",
            (cutoff,),
        )
    }
    for row in db.execute(
        "SELECT h.retailer, f.verdict, COUNT(*) "
        "FROM feedback f JOIN hit_log h ON f.hit_id = h.id "
        "WHERE h.ts >= ? GROUP BY h.retailer, f.verdict",
        (cutoff,),
    ):
        retailer, verdict, n = row
        if retailer not in hits:
            continue
        if verdict == "bought":
            hits[retailer]["bought"] = n
        elif verdict == "false":
            hits[retailer]["false"] = n
    for retailer, stats in hits.items():
        total = stats["alerts"]
        stats["ratio"] = (stats["bought"] / total) if total else 0.0
    return hits
