"""Structured logging with rotating file output.

One module-level logger named "scanner". All other modules call
`get_logger(__name__)` which returns a child logger. Output goes to
stdout (for interactive runs) and to a rotating file under `logs/`
(for long-running daemonized scans).

Format is intentionally line-oriented and grep-friendly:

    2026-05-21T14:03:11Z INFO  scanner.main      stores corridor=12 retailer=target
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_FILE = LOG_DIR / "scanner.log"

_FMT = "%(asctime)s %(levelname)-5s %(name)-22s %(message)s"
_DATEFMT = "%Y-%m-%dT%H:%M:%SZ"


class _UTCFormatter(logging.Formatter):
    converter = staticmethod(__import__("time").gmtime)


_configured = False


def configure(level: str = "INFO") -> None:
    """Idempotently install handlers on the root scanner logger.

    Honors LOG_LEVEL env var if set; otherwise uses the passed `level`.
    """
    global _configured
    if _configured:
        return
    _configured = True

    root = logging.getLogger("scanner")
    root.setLevel(os.environ.get("LOG_LEVEL", level).upper())
    root.propagate = False

    fmt = _UTCFormatter(_FMT, datefmt=_DATEFMT)

    stream = logging.StreamHandler(stream=sys.stdout)
    stream.setFormatter(fmt)
    root.addHandler(stream)

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        rot = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=5_000_000, backupCount=5, encoding="utf-8"
        )
        rot.setFormatter(fmt)
        root.addHandler(rot)
    except OSError as exc:
        # Filesystem might be read-only (containers, CI). Keep going with stdout.
        root.warning("file logging disabled: %s", exc)


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the `scanner` hierarchy.

    Modules pass `__name__` (e.g. "scanner.retailers.target") and get a
    properly namespaced logger without each needing to call configure().
    """
    if not name.startswith("scanner"):
        name = f"scanner.{name}"
    return logging.getLogger(name)
