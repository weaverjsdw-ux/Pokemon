"""SQLite-backed dedupe + restock memory.

`should_alert` suppresses repeat alerts for the same (retailer, store,
product) until either the status changes or `cooldown_seconds` elapses.

`record_observation` keeps a longer-lived history per (retailer, store,
product): first/last seen, how many times it has come back in stock, and
when it was last in stock - so the dashboard is worth opening even when
nothing is live right now."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "state.db"
RUNTIME_DB_PATH = (
    Path(os.getenv("LOCALAPPDATA") or tempfile.gettempdir())
    / "PokemonScanner"
    / "state.runtime.db"
)

# Statuses that count as "you could buy this right now".
POSITIVE_STATUSES = frozenset({"IN_STOCK", "LIMITED", "ONLINE_IN_STOCK"})


class State:
    def __init__(
        self,
        cooldown_seconds: int = 6 * 3600,
        db_path: str | Path | None = None,
    ):
        self.cooldown = cooldown_seconds
        env_path = os.getenv("POKEMON_SCANNER_STATE_DB")
        path = Path(db_path) if db_path is not None else Path(env_path) if env_path else DB_PATH
        self.db_path = path
        try:
            self.db = self._connect(path)
        except sqlite3.OperationalError as exc:
            if db_path is not None or env_path:
                raise
            fallback = RUNTIME_DB_PATH
            print(
                f"  ! state db open failed ({exc}); using {fallback}",
                file=sys.stderr,
            )
            self.db_path = fallback
            self.db = self._connect(fallback)

    def _connect(self, path: Path) -> sqlite3.Connection:
        path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(path, timeout=30)
        try:
            self._init_schema(db)
        except Exception:
            db.close()
            raise
        return db

    def _init_schema(self, db: sqlite3.Connection) -> None:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS last_alert (
                retailer TEXT NOT NULL,
                store_id TEXT NOT NULL,
                product_key TEXT NOT NULL,
                status TEXT NOT NULL,
                ts INTEGER NOT NULL,
                PRIMARY KEY (retailer, store_id, product_key)
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS stock_history (
                retailer TEXT NOT NULL,
                store_id TEXT NOT NULL,
                product_key TEXT NOT NULL,
                first_seen INTEGER NOT NULL,
                last_seen INTEGER NOT NULL,
                last_status TEXT NOT NULL,
                last_in_stock_ts INTEGER,
                in_stock_count INTEGER NOT NULL DEFAULT 0,
                check_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (retailer, store_id, product_key)
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS source_health (
                slug TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                updated_ts INTEGER NOT NULL
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS comp_cache (
                item_key TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                fetched_at INTEGER NOT NULL
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_listings (
                source TEXT NOT NULL,
                listing_id TEXT NOT NULL,
                price REAL,
                status TEXT NOT NULL,
                first_seen INTEGER NOT NULL,
                last_seen INTEGER NOT NULL,
                PRIMARY KEY (source, listing_id)
            )
            """
        )
        db.commit()

    def should_alert(
        self, retailer: str, store_id: str, product_key: str, status: str
    ) -> bool:
        now = int(time.time())
        row = self.db.execute(
            "SELECT status, ts FROM last_alert WHERE retailer=? AND store_id=? AND product_key=?",
            (retailer, store_id, product_key),
        ).fetchone()
        if row is None:
            self._upsert(retailer, store_id, product_key, status, now)
            return True
        prev_status, prev_ts = row
        if prev_status != status or (now - prev_ts) >= self.cooldown:
            self._upsert(retailer, store_id, product_key, status, now)
            return True
        return False

    def _upsert(self, retailer: str, store_id: str, product_key: str, status: str, ts: int) -> None:
        self.db.execute(
            """
            INSERT INTO last_alert(retailer, store_id, product_key, status, ts)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(retailer, store_id, product_key)
            DO UPDATE SET status=excluded.status, ts=excluded.ts
            """,
            (retailer, store_id, product_key, status, ts),
        )
        self.db.commit()

    def record_listing(
        self,
        source: str,
        listing_id: str,
        price: float | None,
        status: str,
        ts: int | None = None,
    ) -> None:
        """Fold one discovered listing into seen_listings (dedupe + how long a
        listing has sat). First sighting timestamp is preserved forever."""
        now = ts if ts is not None else int(time.time())
        self.db.execute(
            """
            INSERT INTO seen_listings(source, listing_id, price, status, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, listing_id)
            DO UPDATE SET price=excluded.price, status=excluded.status,
                          last_seen=excluded.last_seen
            """,
            (source, listing_id, price, status, now, now),
        )
        self.db.commit()

    def listing_history(self, source: str, listing_id: str) -> dict[str, Any] | None:
        row = self.db.execute(
            "SELECT price, status, first_seen, last_seen FROM seen_listings "
            "WHERE source=? AND listing_id=?",
            (source, listing_id),
        ).fetchone()
        if row is None:
            return None
        return {"source": source, "listingId": listing_id, "price": row[0],
                "status": row[1], "firstSeen": row[2], "lastSeen": row[3]}

    def record_observation(
        self,
        retailer: str,
        store_id: str,
        product_key: str,
        status: str,
        ts: int | None = None,
    ) -> None:
        """Fold one stock check into the restock history.

        Counts a "restock" each time the status crosses from not-positive
        into positive, so `in_stock_count` reflects distinct comebacks
        rather than how often we happened to poll."""
        now = ts if ts is not None else int(time.time())
        positive = status in POSITIVE_STATUSES
        row = self.db.execute(
            "SELECT last_status, in_stock_count, last_in_stock_ts FROM stock_history "
            "WHERE retailer=? AND store_id=? AND product_key=?",
            (retailer, store_id, product_key),
        ).fetchone()
        if row is None:
            self.db.execute(
                """
                INSERT INTO stock_history(
                    retailer, store_id, product_key, first_seen, last_seen,
                    last_status, last_in_stock_ts, in_stock_count, check_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    retailer, store_id, product_key, now, now, status,
                    now if positive else None, 1 if positive else 0,
                ),
            )
        else:
            prev_status, prev_count, prev_last_in_stock = row
            became_in_stock = positive and prev_status not in POSITIVE_STATUSES
            self.db.execute(
                """
                UPDATE stock_history
                SET last_seen=?, last_status=?, check_count=check_count+1,
                    in_stock_count=?,
                    last_in_stock_ts=?
                WHERE retailer=? AND store_id=? AND product_key=?
                """,
                (
                    now,
                    status,
                    prev_count + (1 if became_in_stock else 0),
                    now if positive else prev_last_in_stock,
                    retailer,
                    store_id,
                    product_key,
                ),
            )
        self.db.commit()

    def history_for(
        self, retailer: str, store_id: str, product_key: str
    ) -> dict[str, Any] | None:
        row = self.db.execute(
            "SELECT first_seen, last_seen, last_status, last_in_stock_ts, "
            "in_stock_count, check_count FROM stock_history "
            "WHERE retailer=? AND store_id=? AND product_key=?",
            (retailer, store_id, product_key),
        ).fetchone()
        if row is None:
            return None
        return {
            "firstSeen": row[0],
            "lastSeen": row[1],
            "lastStatus": row[2],
            "lastInStockTs": row[3],
            "inStockCount": row[4],
            "checkCount": row[5],
        }

    def recent_restocks(self, limit: int = 25) -> list[dict[str, Any]]:
        """Products most recently seen in stock, newest first - the
        dashboard's "what showed up lately" view."""
        rows = self.db.execute(
            "SELECT retailer, store_id, product_key, last_in_stock_ts, "
            "in_stock_count, last_status FROM stock_history "
            "WHERE last_in_stock_ts IS NOT NULL "
            "ORDER BY last_in_stock_ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {
                "retailer": r[0],
                "storeId": r[1],
                "productKey": r[2],
                "lastInStockTs": r[3],
                "inStockCount": r[4],
                "lastStatus": r[5],
            }
            for r in rows
        ]

    def record_source_health_snapshot(
        self,
        rows: list[dict[str, Any]],
        ts: int | None = None,
    ) -> None:
        """Persist the latest per-retailer health rows for dashboard restarts."""
        now = ts if ts is not None else int(time.time())
        for row in rows:
            slug = str(row.get("slug") or "").strip()
            if not slug:
                continue
            self.db.execute(
                """
                INSERT INTO source_health(slug, payload_json, updated_ts)
                VALUES (?, ?, ?)
                ON CONFLICT(slug)
                DO UPDATE SET payload_json=excluded.payload_json,
                              updated_ts=excluded.updated_ts
                """,
                (slug, json.dumps(row, sort_keys=True), now),
            )
        self.db.commit()

    def source_health_snapshot(self) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT payload_json FROM source_health ORDER BY slug"
        ).fetchall()
        out: list[dict[str, Any]] = []
        for (payload_json,) in rows:
            try:
                payload = json.loads(payload_json)
            except (TypeError, ValueError):
                continue
            if isinstance(payload, dict):
                out.append(payload)
        return out

    def comp_cache_get(self, item_key: str) -> tuple[dict[str, Any], int] | None:
        row = self.db.execute(
            "SELECT payload_json, fetched_at FROM comp_cache WHERE item_key=?",
            (item_key,),
        ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row[0])
        except (TypeError, ValueError):
            return None
        return (payload, int(row[1])) if isinstance(payload, dict) else None

    def comp_cache_put(
        self, item_key: str, payload: dict[str, Any], ts: int | None = None
    ) -> None:
        now = ts if ts is not None else int(time.time())
        self.db.execute(
            """
            INSERT INTO comp_cache(item_key, payload_json, fetched_at)
            VALUES (?, ?, ?)
            ON CONFLICT(item_key)
            DO UPDATE SET payload_json=excluded.payload_json,
                          fetched_at=excluded.fetched_at
            """,
            (item_key, json.dumps(payload, sort_keys=True), now),
        )
        self.db.commit()
