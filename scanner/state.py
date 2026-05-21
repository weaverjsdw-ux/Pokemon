"""SQLite-backed dedupe.

Suppresses repeat alerts for the same (retailer, store, product) until
either the status changes or `cooldown_seconds` elapses."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "state.db"


class State:
    def __init__(self, cooldown_seconds: int = 6 * 3600):
        self.cooldown = cooldown_seconds
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(DB_PATH)
        self.db.execute(
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
        self.db.commit()

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
