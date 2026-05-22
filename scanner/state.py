"""SQLite-backed dedupe.

Suppresses repeat alerts for the same (retailer, store, product) until
either the status changes or `cooldown_seconds` elapses.

Backups: SQLite's online backup API copies the DB to data/backups/ on a
configurable cadence. Default is daily; the most recent N copies are
kept and older ones are pruned. Backups happen in-process before the
scan loop sleeps, so they always reflect a quiesced state."""
from __future__ import annotations

import shutil
import sqlite3
import time
from pathlib import Path

from .log import get_logger

log = get_logger(__name__)

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "state.db"
BACKUP_DIR = Path(__file__).resolve().parent.parent / "data" / "backups"


class State:
    def __init__(self, cooldown_seconds: int = 6 * 3600):
        from . import migrations
        self.cooldown = cooldown_seconds
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(DB_PATH)
        migrations.apply(self.db)

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

    def record_price(
        self,
        retailer: str,
        product_key: str,
        store_id: str,
        price_cents: int | None,
        ts: int | None = None,
    ) -> None:
        """Append a price observation. Used by the at-or-below-MSRP filter
        and Phase 3 trend detection."""
        self.db.execute(
            "INSERT OR IGNORE INTO price_history(retailer, product_key, store_id, price_cents, ts) "
            "VALUES (?, ?, ?, ?, ?)",
            (retailer, product_key, store_id, price_cents, ts or int(time.time())),
        )
        self.db.commit()

    def signal_should_alert(self, source: str, external_id: str) -> bool:
        """First time we've seen this (source, external_id) -> True (and remember).
        Subsequent passes -> False."""
        row = self.db.execute(
            "SELECT 1 FROM signal_seen WHERE source=? AND external_id=?",
            (source, external_id),
        ).fetchone()
        if row is not None:
            return False
        self.db.execute(
            "INSERT INTO signal_seen(source, external_id, ts) VALUES (?, ?, ?)",
            (source, external_id, int(time.time())),
        )
        self.db.commit()
        return True

    def record_hit(
        self,
        retailer: str,
        store_id: str,
        product_key: str,
        status: str,
        tier: str,
        url: str,
        price_cents: int | None,
        ts: int | None = None,
    ) -> None:
        """Append-only log of every alert we send. Powers analytics; not
        consulted by the dedupe path."""
        self.db.execute(
            "INSERT INTO hit_log(retailer, store_id, product_key, status, tier, url, price_cents, ts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (retailer, store_id, product_key, status, tier, url, price_cents, ts or int(time.time())),
        )
        self.db.commit()

    def maybe_backup(
        self,
        *,
        interval_seconds: int = 24 * 3600,
        keep: int = 7,
        backup_dir: Path | None = None,
    ) -> Path | None:
        """If at least `interval_seconds` has elapsed since the most recent
        backup, write a fresh one and prune to the last `keep` copies.
        Returns the new backup path, or None if a backup wasn't due.

        Uses SQLite's online backup API so the running scanner doesn't
        need to pause."""
        bdir = backup_dir or BACKUP_DIR
        bdir.mkdir(parents=True, exist_ok=True)
        existing = sorted(bdir.glob("state-*.db"))
        now = time.time()
        if existing and interval_seconds > 0:
            most_recent = existing[-1].stat().st_mtime
            if now - most_recent < interval_seconds:
                return None
        path = bdir / f"state-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime(now))}.db"
        try:
            with sqlite3.connect(path) as dst:
                self.db.backup(dst)
        except sqlite3.Error as exc:
            log.warning("state backup failed: %s", exc)
            # Drop the partial file so the next attempt isn't gated by it.
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            return None
        log.info("state backup written: %s", path.name)
        # Prune oldest, keeping `keep`. Re-glob since `path` is new.
        kept = sorted(bdir.glob("state-*.db"))
        for old in kept[:-keep]:
            try:
                old.unlink()
                log.debug("pruned old state backup: %s", old.name)
            except OSError as exc:
                log.warning("could not prune %s: %s", old.name, exc)
        return path


def is_runtime_muted(db: sqlite3.Connection, product_key: str) -> bool:
    """True if the dashboard has muted this product. Independent of
    products.yaml's static `mute: true`."""
    row = db.execute(
        "SELECT muted FROM runtime_mute WHERE product_key=?", (product_key,)
    ).fetchone()
    return bool(row and row[0])


def set_runtime_mute(db: sqlite3.Connection, product_key: str, muted: bool) -> None:
    db.execute(
        "INSERT INTO runtime_mute(product_key, muted, ts) VALUES (?, ?, ?) "
        "ON CONFLICT(product_key) DO UPDATE SET muted=excluded.muted, ts=excluded.ts",
        (product_key, 1 if muted else 0, int(time.time())),
    )
    db.commit()


def suppress_drop(
    db: sqlite3.Connection,
    retailer: str,
    product_key: str,
    store_id: str,
    *,
    duration_seconds: int = 6 * 3600,
    reason: str = "",
) -> int:
    """Mark a specific (retailer, product, store) as 'I'm not interested
    in any more alerts about this drop' — typically because the user just
    bought it. Default 6h suppression covers the rest of a drop window."""
    until = int(time.time()) + duration_seconds
    db.execute(
        "INSERT OR REPLACE INTO suppressed_drop(retailer, product_key, store_id, until_ts, reason) "
        "VALUES (?, ?, ?, ?, ?)",
        (retailer, product_key, store_id, until, reason),
    )
    db.commit()
    return until


def is_suppressed(
    db: sqlite3.Connection,
    retailer: str,
    product_key: str,
    store_id: str,
) -> bool:
    row = db.execute(
        "SELECT until_ts FROM suppressed_drop "
        "WHERE retailer=? AND product_key=? AND store_id=?",
        (retailer, product_key, store_id),
    ).fetchone()
    if not row:
        return False
    return int(row[0]) > int(time.time())


def record_feedback(
    db: sqlite3.Connection,
    *,
    hit_id: int | None,
    verdict: str,
    note: str = "",
) -> None:
    """Record a per-alert verdict. Verdicts:
        bought    - 'got it, stop pinging me about this drop'
        missed    - 'gone by the time I got there / sold out'
        false     - 'no actual stock, alert was wrong'
        too_slow  - 'alert came after the drop ended'"""
    db.execute(
        "INSERT INTO feedback(hit_id, verdict, note, ts) VALUES (?, ?, ?, ?)",
        (hit_id, verdict, note, int(time.time())),
    )
    db.commit()


def restore_latest(target: Path | None = None, *, backup_dir: Path | None = None) -> Path:
    """Replace state.db with the most recent backup. Returns the source path.

    Manual operation — not used in the normal loop. Useful when the live
    DB is corrupted or a recent change to dedupe logic produced bad
    state and you want a known-good baseline."""
    bdir = backup_dir or BACKUP_DIR
    tgt = target or DB_PATH
    backups = sorted(bdir.glob("state-*.db"))
    if not backups:
        raise FileNotFoundError(f"No backups found in {bdir}")
    src = backups[-1]
    shutil.copy2(src, tgt)
    return src
