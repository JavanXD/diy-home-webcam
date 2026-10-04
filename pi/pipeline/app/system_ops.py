"""System power + read-only host status for the LAN Pipeline home.

Mutations (reboot / power-off / restart) go through systemd + polkit rule
``50-webcam-system.rules`` — fixed actions only, no unbound root shell.

Reads (``/system/status``, ``/system/logs``) use world-readable sysfs, nmcli,
``systemctl`` status queries, and ``journalctl`` for a fixed unit allow-list.
Journal access needs the ``webcam`` user in group ``systemd-journal``
(provision/deploy).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

Runner = Callable[[list[str]], tuple[int, str, str]]

_SYSTEMCTL_TIMEOUT = 30
_JOURNAL_TIMEOUT = 15
_ACTION_DELAY_SEC = 1.0
_DEFAULT_LOG_LINES = 40
_MAX_LOG_LINES = 120

# Fixed allow-list — never accept unit names from the HTTP client.
_RESTART_UNITS = (
    "webcam-camera.service",
    "webcam-pipeline.service",
    "nginx.service",
)
_STATUS_UNITS = _RESTART_UNITS
_LOG_UNITS = (
    "webcam-camera.service",
    "webcam-pipeline.service",
)

_THERMAL_PATHS = (
    Path("/sys/class/thermal/thermal_zone0/temp"),
    Path("/sys/class/hwmon/hwmon0/temp1_input"),
)


class SystemOpsError(ValueError):
    pass


def require_confirm(body: dict[str, Any] | None) -> None:
    raw = (body or {}).get("confirm")
    if raw is True or (isinstance(raw, str) and raw.strip().lower() in ("1", "true", "yes")):
        return
    raise SystemOpsError('JSON body must include "confirm": true')


def schedule_power(action: str, *, runner: Runner | None = None, delay: float = _ACTION_DELAY_SEC) -> dict[str, Any]:
    """Queue reboot or poweroff after the HTTP response can flush."""
    act = str(action or "").strip().lower()
    if act not in ("reboot", "poweroff"):
        raise SystemOpsError("action must be reboot or poweroff")
    label = "reboot" if act == "reboot" else "shut down"
    _schedule(lambda: _run_systemctl([act], runner=runner), delay=delay)
    return {
        "ok": True,
        "accepted": True,
        "action": act,
        "message": f"Pi will {label} in about {delay:.0f}s. This page will disconnect.",
        "delay_seconds": delay,
    }


def schedule_restart_services(
    *, runner: Runner | None = None, delay: float = _ACTION_DELAY_SEC
) -> dict[str, Any]:
    """Restart webcam-camera, webcam-pipeline, and nginx (if installed)."""
    units = list_restart_units(runner=runner)
    if not units:
        raise SystemOpsError("no webcam stack units found to restart")
    names = [u.removesuffix(".service") for u in units]

    def _do() -> None:
        _run_systemctl(["restart", *units], runner=runner)

    _schedule(_do, delay=delay)
    return {
        "ok": True,
        "accepted": True,
        "action": "restart-services",
        "units": units,
        "message": (
            "Restarting "
            + ", ".join(names)
            + f" in about {delay:.0f}s. The LAN UI will disconnect briefly."
        ),
        "delay_seconds": delay,
    }


def list_restart_units(*, runner: Runner | None = None) -> list[str]:
    """Units that exist on this host from the fixed allow-list."""
    run = runner or _run
    found: list[str] = []
    for unit in _RESTART_UNITS:
        code, _out, _err = run(["systemctl", "cat", unit])
        if code == 0:
            found.append(unit)
    return found


def collect_system_status(
    *,
    data_path: Path | None = None,
    publish: dict[str, Any] | None = None,
    network: list[dict[str, Any]] | None = None,
    runner: Runner | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Read-only host glance for Pipeline home (disk, temp, units, clock, publish)."""
    ts = time.time() if now is None else float(now)
    disks = collect_disks(data_path=data_path)
    temp_c = read_soc_temperature_c()
    units = collect_unit_states(runner=runner)
    clock = collect_clock(runner=runner, now=ts)
    pub = summarize_publish(publish, now=ts)
    return {
        "ok": True,
        "disks": disks,
        "temperature_c": temp_c,
        "units": units,
        "clock": clock,
        "publish": pub,
        "network": list(network or []),
    }


def collect_disks(*, data_path: Path | None = None) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    root = _disk_entry("/", label="root")
    if root:
        entries.append(root)
    if data_path is not None:
        try:
            resolved = Path(data_path).resolve()
        except OSError:
            resolved = Path(data_path)
        if resolved.exists():
            try:
                same = os.stat("/").st_dev == os.stat(resolved).st_dev
            except OSError:
                same = True
            if not same:
                data = _disk_entry(str(resolved), label="data")
                if data:
                    entries.append(data)
    return entries


def _disk_entry(path: str, *, label: str) -> dict[str, Any] | None:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    total = int(usage.total)
    free = int(usage.free)
    used = max(0, total - free)
    free_pct = round((free / total) * 100.0, 1) if total else None
    used_pct = round((used / total) * 100.0, 1) if total else None
    return {
        "label": label,
        "path": path,
        "total_bytes": total,
        "free_bytes": free,
        "used_bytes": used,
        "free_pct": free_pct,
        "used_pct": used_pct,
    }


def read_soc_temperature_c() -> float | None:
    for path in _THERMAL_PATHS:
        try:
            raw = path.read_text(encoding="utf-8").strip()
            milli = int(raw)
        except (OSError, ValueError):
            continue
        # hwmon sometimes reports millidegrees; zone0 always does on Pi.
        if milli > 1000:
            return round(milli / 1000.0, 1)
        return float(milli)
    return None


def collect_unit_states(*, runner: Runner | None = None) -> list[dict[str, Any]]:
    run = runner or _run
    out: list[dict[str, Any]] = []
    for unit in _STATUS_UNITS:
        code_cat, _o, _e = run(["systemctl", "cat", unit])
        installed = code_cat == 0
        active = "not-found"
        sub = ""
        if installed:
            _code_a, out_a, _ea = run(["systemctl", "is-active", unit])
            active = (out_a or "").strip() or "unknown"
            code_s, out_s, _es = run(
                ["systemctl", "show", unit, "-p", "SubState", "--value"]
            )
            if code_s == 0:
                sub = (out_s or "").strip()
        out.append(
            {
                "unit": unit,
                "name": unit.removesuffix(".service"),
                "installed": installed,
                "active": active,
                "sub_state": sub,
                "ok": installed and active == "active",
            }
        )
    return out


def collect_clock(*, runner: Runner | None = None, now: float | None = None) -> dict[str, Any]:
    ts = time.time() if now is None else float(now)
    run = runner or _run
    ntp_ok: bool | None = None
    timezone_name = ""
    code_n, out_n, _err_n = run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"])
    if code_n == 0:
        flag = (out_n or "").strip().splitlines()
        flag0 = (flag[0] if flag else "").lower()
        if flag0 in ("yes", "true", "1"):
            ntp_ok = True
        elif flag0 in ("no", "false", "0"):
            ntp_ok = False
    code_z, out_z, _err_z = run(["timedatectl", "show", "-p", "Timezone", "--value"])
    if code_z == 0:
        lines = [ln.strip() for ln in (out_z or "").splitlines() if ln.strip()]
        if lines:
            timezone_name = lines[0]
    if ntp_ok is None:
        # Fallback marker written by systemd-timesyncd when sync succeeds.
        synced = Path("/run/systemd/timesync/synchronized").exists()
        ntp_ok = True if synced else None
    tz_fallback = time.tzname[0] if time.tzname else ""
    return {
        "utc": datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ntp_synchronized": ntp_ok,
        "timezone": timezone_name or tz_fallback,
        "ok": ntp_ok is not False,
    }


def summarize_publish(publish: dict[str, Any] | None, *, now: float | None = None) -> dict[str, Any]:
    info = dict(publish or {})
    ts = time.time() if now is None else float(now)
    last_at = info.get("last_success_at")
    age: float | None = None
    if isinstance(last_at, str) and last_at:
        parsed = _parse_iso_z(last_at)
        if parsed is not None:
            age = max(0.0, round(ts - parsed, 1))
    return {
        "enabled": bool(info.get("enabled")),
        "backend": info.get("backend"),
        "last_success_at": last_at,
        "last_success_age_seconds": age,
        "last_error": info.get("last_error"),
    }


def collect_unit_logs(
    *,
    lines: int = _DEFAULT_LOG_LINES,
    runner: Runner | None = None,
) -> dict[str, Any]:
    """Last N journal lines for fixed webcam units only (read-only)."""
    n = int(lines)
    if n < 1:
        n = _DEFAULT_LOG_LINES
    n = min(n, _MAX_LOG_LINES)
    run = runner or _run
    args = [
        "journalctl",
        "--no-pager",
        "-o",
        "short-iso",
        "-n",
        str(n),
    ]
    for unit in _LOG_UNITS:
        args.extend(["-u", unit])
    code, out, err = run(args)
    text = (out or "").rstrip()
    if code != 0 and not text:
        msg = _public_journal_error(err or out)
        return {
            "ok": False,
            "lines": n,
            "units": [u.removesuffix(".service") for u in _LOG_UNITS],
            "text": "",
            "error": msg,
        }
    return {
        "ok": True,
        "lines": n,
        "units": [u.removesuffix(".service") for u in _LOG_UNITS],
        "text": text,
        "error": None if code == 0 else _public_journal_error(err or out),
    }


def _parse_iso_z(value: str) -> float | None:
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw).timestamp()
    except ValueError:
        return None


def _schedule(fn: Callable[[], None], *, delay: float) -> None:
    def _worker() -> None:
        time.sleep(max(0.0, float(delay)))
        try:
            fn()
        except Exception:  # noqa: BLE001 — fire-and-forget after HTTP accept
            pass

    threading.Thread(target=_worker, name="system-ops", daemon=True).start()


def _run_systemctl(args: list[str], *, runner: Runner | None = None) -> None:
    run = runner or _run
    if shutil.which("systemctl") is None and runner is None:
        raise SystemOpsError("systemctl is not available on this host")
    code, out, err = run(["systemctl", *args])
    if code != 0:
        raise SystemOpsError(_public_error(err or out))


def _public_error(text: str) -> str:
    msg = " ".join((text or "").split())
    if not msg:
        return "systemctl refused the request"
    if "Access denied" in msg or "Not authorized" in msg or "Interactive authentication required" in msg:
        return (
            "Permission denied. Install pi/pipeline/systemd/50-webcam-system.rules "
            "(provision/deploy) and try again."
        )
    return msg[:300]


def _public_journal_error(text: str) -> str:
    msg = " ".join((text or "").split())
    if not msg:
        return "journalctl refused the request"
    if "No journal files" in msg or "Failed to open" in msg or "Permission denied" in msg:
        return (
            "Cannot read journals. Add user webcam to group systemd-journal "
            "(provision/deploy) and restart webcam-pipeline."
        )
    return msg[:300]


def _run(args: list[str]) -> tuple[int, str, str]:
    timeout = _JOURNAL_TIMEOUT if args and args[0] == "journalctl" else _SYSTEMCTL_TIMEOUT
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)
    return proc.returncode, proc.stdout or "", proc.stderr or ""
