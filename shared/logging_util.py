"""Shared logging helpers — consistent, readable operational output."""

from __future__ import annotations

import logging
import sys
from typing import Any


class PlainFormatter(logging.Formatter):
    """Compact timestamps + level for journald / terminal reading."""

    def format(self, record: logging.LogRecord) -> str:
        # Ensure message is formatted first
        msg = super().format(record)
        return msg


def setup_logging(level: str = "INFO", *, name: str | None = None) -> logging.Logger:
    root = logging.getLogger()
    # Avoid duplicate handlers when reloading
    if not root.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            PlainFormatter(
                fmt="%(asctime)s %(levelname)-5s %(name)s | %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        )
        root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    # Quiet noisy HTTP client by default
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    return logging.getLogger(name) if name else root


def fmt_bytes(n: int | None) -> str:
    if n is None:
        return "?"
    if n < 1024:
        return f"{n}B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f}KiB"
    return f"{n / (1024 * 1024):.2f}MiB"


def fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    return f"{seconds:.2f}s"


def iso_utc(ts: float | None) -> str | None:
    if ts is None:
        return None
    import time

    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def banner(title: str, fields: dict[str, Any]) -> str:
    lines = [f"=== {title} ==="]
    width = max((len(str(k)) for k in fields), default=8)
    for key, value in fields.items():
        lines.append(f"  {str(key).ljust(width)}  {value}")
    return "\n".join(lines)
