"""Host system uptime (distinct from process/app uptime)."""

from __future__ import annotations


def system_uptime_seconds() -> float | None:
    """Seconds since boot from ``/proc/uptime``, or ``None`` if unavailable."""
    try:
        with open("/proc/uptime", encoding="utf-8") as fh:
            return float(fh.read().split()[0])
    except (OSError, ValueError, IndexError):
        return None
