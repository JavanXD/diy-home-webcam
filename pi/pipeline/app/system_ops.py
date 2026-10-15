"""System power + read-only host status for the LAN Pipeline home.

Mutations (reboot / power-off / restart) go through systemd + polkit rule
``50-webcam-system.rules`` — fixed actions only, no unbound root shell.

Reads (``/system/status``, ``/system/logs``) use world-readable sysfs, nmcli,
``systemctl`` status queries, and ``journalctl`` for a fixed unit allow-list.
Journal access needs the ``webcam`` user in group ``systemd-journal``
(provision/deploy).

Host + timing samples roll in a short in-process history for System health
charts on Pipeline home (CPU, temp, frame age, capture/cycle timing, …).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse, urlunparse

Runner = Callable[[list[str]], tuple[int, str, str]]
TimingProvider = Callable[[], dict[str, Any]]

_SYSTEMCTL_TIMEOUT = 30
_JOURNAL_TIMEOUT = 15
_ACTION_DELAY_SEC = 1.0
_DEFAULT_LOG_LINES = 40
_MAX_LOG_LINES = 120
_DEFAULT_METRICS_INTERVAL = 5.0
_DEFAULT_METRICS_HISTORY_SEC = 600.0
# Pi 5–oriented gauge bands (warn / bad). UI paints green below warn, orange to bad, red above.
# Keys match System Info gauges; ``higher_is_bad`` false means low values are worse (disk free %).
GAUGE_THRESHOLDS: dict[str, dict[str, Any]] = {
    "cpu_percent": {
        "max": 100,
        "warn": 70,
        "bad": 90,
        "unit": "%",
        "label": "CPU",
        "higher_is_bad": True,
    },
    "temperature_c": {
        "max": 90,
        "warn": 65,
        "bad": 75,
        "unit": "°C",
        "label": "SoC temp",
        "higher_is_bad": True,
    },
    "mem_used_pct": {
        "max": 100,
        "warn": 75,
        "bad": 90,
        "unit": "%",
        "label": "Memory",
        "higher_is_bad": True,
    },
    "swap_used_pct": {
        "max": 100,
        "warn": 10,
        "bad": 40,
        "unit": "%",
        "label": "Swap",
        "higher_is_bad": True,
    },
    # Load as % of one full core-set (value = load1 / cpu_count * 100).
    "load_pct": {
        "max": 150,
        "warn": 70,
        "bad": 100,
        "unit": "%",
        "label": "Load",
        "higher_is_bad": True,
    },
    "disk_free_pct": {
        "max": 100,
        "warn": 20,
        "bad": 10,
        "unit": "%",
        "label": "Disk free",
        "higher_is_bad": False,
    },
    # Sustained write pressure (MB/s); capture@1s can be a few MB/s.
    "disk_write_mib_s": {
        "max": 40,
        "warn": 8,
        "bad": 20,
        "unit": "MiB/s",
        "label": "Disk write",
        "higher_is_bad": True,
    },
    # Relative to capture.interval_seconds (default 1s): green ≤2×, orange ≤5×.
    "frame_age_seconds": {
        "max": 10,
        "warn": 2,
        "bad": 5,
        "unit": "s",
        "label": "Frame age",
        "higher_is_bad": True,
    },
    "capture_duration_seconds": {
        "max": 2,
        "warn": 0.8,
        "bad": 1.0,
        "unit": "s",
        "label": "Capture",
        "higher_is_bad": True,
    },
    "pipeline_cycle_seconds": {
        "max": 60,
        "warn": 15,
        "bad": 40,
        "unit": "s",
        "label": "Pipeline cycle",
        "higher_is_bad": True,
    },
    "stream_lag_seconds": {
        "max": 5,
        "warn": 1.0,
        "bad": 3.0,
        "unit": "s",
        "label": "Stream lag",
        "higher_is_bad": True,
    },
}
_PROC_STAT = Path("/proc/stat")
_PROC_MEMINFO = Path("/proc/meminfo")
_PROC_DISKSTATS = Path("/proc/diskstats")
_THROTTLE_PATHS = (
    Path("/sys/devices/platform/soc/soc:firmware/get_throttled"),
    Path("/sys/devices/platform/firmware/raspberrypi/get_throttled"),
)
_SERVICE_CPU_UNITS = (
    "webcam-camera.service",
    "webcam-pipeline.service",
    "webcam-stream.service",
)
_TIMING_HTTP_TIMEOUT = 0.45

# Process-wide sampler started from pipeline main (optional in tests).
_host_metrics: "HostMetrics | None" = None
_host_metrics_lock = threading.Lock()

# Fixed allow-list — never accept unit names from the HTTP client.
_RESTART_UNITS = (
    "webcam-camera.service",
    "webcam-pipeline.service",
    "webcam-stream.service",
    "nginx.service",
)
_STATUS_UNITS = _RESTART_UNITS
_LOG_UNITS = (
    "webcam-camera.service",
    "webcam-pipeline.service",
    "webcam-stream.service",
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
    """Restart webcam-camera, webcam-pipeline, webcam-stream, and nginx (if installed)."""
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


def get_host_metrics() -> "HostMetrics | None":
    with _host_metrics_lock:
        return _host_metrics


def start_host_metrics(
    *,
    sample_interval_seconds: float = _DEFAULT_METRICS_INTERVAL,
    history_seconds: float = _DEFAULT_METRICS_HISTORY_SEC,
    timing_provider: TimingProvider | None = None,
) -> "HostMetrics":
    """Start (or return) the process-wide host metrics sampler."""
    global _host_metrics
    with _host_metrics_lock:
        if _host_metrics is None:
            _host_metrics = HostMetrics(
                sample_interval_seconds=sample_interval_seconds,
                history_seconds=history_seconds,
                timing_provider=timing_provider,
            )
            _host_metrics.start()
        elif timing_provider is not None:
            _host_metrics.set_timing_provider(timing_provider)
        return _host_metrics


def stop_host_metrics() -> None:
    global _host_metrics
    with _host_metrics_lock:
        if _host_metrics is not None:
            _host_metrics.stop()
            _host_metrics = None


class HostMetrics:
    """Rolling host + timing samples for ``GET /system/status``."""

    def __init__(
        self,
        *,
        sample_interval_seconds: float = _DEFAULT_METRICS_INTERVAL,
        history_seconds: float = _DEFAULT_METRICS_HISTORY_SEC,
        now_fn: Callable[[], float] | None = None,
        timing_provider: TimingProvider | None = None,
        runner: Runner | None = None,
    ) -> None:
        self.sample_interval_seconds = max(1.0, float(sample_interval_seconds))
        self.history_seconds = max(self.sample_interval_seconds, float(history_seconds))
        self._max_points = max(
            2, int(self.history_seconds / self.sample_interval_seconds) + 1
        )
        self._now_fn = now_fn or time.time
        self._timing_provider = timing_provider
        self._runner = runner
        self._lock = threading.Lock()
        self._history: deque[dict[str, Any]] = deque(maxlen=self._max_points)
        self._latest_extra: dict[str, Any] = {}
        self._prev_cpu: tuple[int, int] | None = None  # idle, total
        self._prev_disk: tuple[float, int] | None = None  # ts, sectors_written
        self._prev_svc: dict[str, tuple[int, int]] = {}  # name -> (utime+stime, total_jiffies)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def set_timing_provider(self, provider: TimingProvider | None) -> None:
        self._timing_provider = provider

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self.sample_once()
        self._thread = threading.Thread(
            target=self._loop, name="host-metrics", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=self.sample_interval_seconds + 1.0)
        self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(self.sample_interval_seconds):
            try:
                self.sample_once()
            except Exception:  # noqa: BLE001 — sampler must not kill the process
                pass

    def sample_once(self) -> dict[str, Any]:
        ts = float(self._now_fn())
        cpu_pct = self._cpu_percent()
        load1, load5, load15 = self._loadavg()
        mem = self._meminfo()
        temp_c = read_soc_temperature_c()
        throttle = read_throttle_status(runner=self._runner)
        disk_write_bps = self._disk_write_bps(ts)
        svc_cpu = self._service_cpu_percents()
        timing = self._collect_timing()

        point: dict[str, Any] = {
            "t": round(ts, 1),
            "cpu": cpu_pct,
            "load1": load1,
            "mem_pct": mem.get("used_pct"),
            "swap_pct": mem.get("swap_used_pct"),
            "temp": temp_c,
            "throttled": throttle.get("throttled"),
            "disk_write_bps": disk_write_bps,
            "capture_s": timing.get("capture_duration_seconds"),
            "frame_age": timing.get("frame_age_seconds"),
            "cycle_s": timing.get("pipeline_cycle_seconds"),
            "stream_lag": timing.get("stream_lag_seconds"),
            "failed_captures": timing.get("failed_captures"),
            "svc_camera": svc_cpu.get("webcam-camera"),
            "svc_pipeline": svc_cpu.get("webcam-pipeline"),
            "svc_stream": svc_cpu.get("webcam-stream"),
        }
        extra = {
            "load5": load5,
            "load15": load15,
            "mem_total_bytes": mem.get("total_bytes"),
            "mem_available_bytes": mem.get("available_bytes"),
            "mem_used_pct": mem.get("used_pct"),
            "swap_total_bytes": mem.get("swap_total_bytes"),
            "swap_used_pct": mem.get("swap_used_pct"),
            "temperature_c": temp_c,
            "throttled": throttle.get("throttled"),
            "throttle_hex": throttle.get("hex"),
            "throttle_flags": throttle.get("flags"),
            "disk_write_bps": disk_write_bps,
            "capture_duration_seconds": timing.get("capture_duration_seconds"),
            "frame_age_seconds": timing.get("frame_age_seconds"),
            "pipeline_cycle_seconds": timing.get("pipeline_cycle_seconds"),
            "stream_lag_seconds": timing.get("stream_lag_seconds"),
            "stream_frame_age_seconds": timing.get("stream_frame_age_seconds"),
            "failed_captures": timing.get("failed_captures"),
            "service_cpu": svc_cpu,
        }
        with self._lock:
            self._history.append(point)
            self._latest_extra = extra
            latest = dict(point)
        latest.update(extra)
        return latest

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            history = [dict(p) for p in self._history]
            extra = dict(self._latest_extra)
        latest = history[-1] if history else {}
        load1, load5, load15 = self._loadavg()
        mem = self._meminfo()
        temp_c = extra.get("temperature_c")
        if temp_c is None:
            temp_c = read_soc_temperature_c()
        return {
            "percent": latest.get("cpu"),
            "load_1": load1 if load1 is not None else latest.get("load1"),
            "load_5": load5 if load5 is not None else extra.get("load5"),
            "load_15": load15 if load15 is not None else extra.get("load15"),
            "mem_used_pct": mem.get("used_pct", latest.get("mem_pct")),
            "mem_total_bytes": mem.get("total_bytes"),
            "mem_available_bytes": mem.get("available_bytes"),
            "swap_used_pct": mem.get("swap_used_pct", latest.get("swap_pct")),
            "swap_total_bytes": mem.get("swap_total_bytes"),
            "temperature_c": temp_c if temp_c is not None else latest.get("temp"),
            "throttled": extra.get("throttled", latest.get("throttled")),
            "throttle_hex": extra.get("throttle_hex"),
            "throttle_flags": extra.get("throttle_flags") or [],
            "disk_write_bps": extra.get("disk_write_bps", latest.get("disk_write_bps")),
            "capture_duration_seconds": extra.get(
                "capture_duration_seconds", latest.get("capture_s")
            ),
            "frame_age_seconds": extra.get("frame_age_seconds", latest.get("frame_age")),
            "pipeline_cycle_seconds": extra.get(
                "pipeline_cycle_seconds", latest.get("cycle_s")
            ),
            "stream_lag_seconds": extra.get("stream_lag_seconds", latest.get("stream_lag")),
            "stream_frame_age_seconds": extra.get("stream_frame_age_seconds"),
            "failed_captures": extra.get(
                "failed_captures", latest.get("failed_captures")
            ),
            "service_cpu": dict(extra.get("service_cpu") or {}),
            "sample_interval_seconds": self.sample_interval_seconds,
            "history_seconds": self.history_seconds,
            "history": history,
        }

    def _collect_timing(self) -> dict[str, Any]:
        if self._timing_provider is None:
            return {}
        try:
            raw = self._timing_provider() or {}
        except Exception:  # noqa: BLE001
            return {}
        out: dict[str, Any] = {}
        for key in (
            "capture_duration_seconds",
            "frame_age_seconds",
            "pipeline_cycle_seconds",
            "stream_lag_seconds",
            "stream_frame_age_seconds",
            "failed_captures",
        ):
            if key in raw and raw[key] is not None:
                try:
                    out[key] = float(raw[key]) if key != "failed_captures" else int(raw[key])
                except (TypeError, ValueError):
                    pass
        return out

    def _cpu_percent(self) -> float | None:
        idle_total = _read_proc_stat_cpu()
        if idle_total is None:
            return None
        idle, total = idle_total
        prev = self._prev_cpu
        self._prev_cpu = (idle, total)
        if prev is None:
            return None
        d_idle = idle - prev[0]
        d_total = total - prev[1]
        if d_total <= 0:
            return None
        busy = 1.0 - (d_idle / float(d_total))
        return round(max(0.0, min(100.0, busy * 100.0)), 1)

    def _disk_write_bps(self, ts: float) -> float | None:
        sectors = _read_disk_sectors_written()
        if sectors is None:
            return None
        prev = self._prev_disk
        self._prev_disk = (ts, sectors)
        if prev is None:
            return None
        dt = ts - prev[0]
        if dt <= 0:
            return None
        # Linux diskstats sectors are typically 512 bytes.
        return round(max(0.0, (sectors - prev[1]) * 512.0 / dt), 1)

    def _service_cpu_percents(self) -> dict[str, float | None]:
        idle_total = _read_proc_stat_cpu()
        if idle_total is None:
            return {}
        _idle, total = idle_total
        run = self._runner or _run
        out: dict[str, float | None] = {}
        for unit in _SERVICE_CPU_UNITS:
            name = unit.removesuffix(".service")
            code, stdout, _err = run(
                ["systemctl", "show", unit, "-p", "MainPID", "--value"]
            )
            if code != 0:
                out[name] = None
                continue
            try:
                pid = int((stdout or "").strip().splitlines()[0])
            except (ValueError, IndexError):
                out[name] = None
                continue
            if pid <= 0:
                out[name] = None
                continue
            ticks = _read_proc_pid_cpu_ticks(pid)
            if ticks is None:
                out[name] = None
                continue
            prev = self._prev_svc.get(name)
            self._prev_svc[name] = (ticks, total)
            if prev is None:
                out[name] = None
                continue
            d_ticks = ticks - prev[0]
            d_total = total - prev[1]
            if d_total <= 0:
                out[name] = None
                continue
            out[name] = round(max(0.0, min(100.0, (d_ticks / float(d_total)) * 100.0)), 1)
        return out

    @staticmethod
    def _loadavg() -> tuple[float | None, float | None, float | None]:
        try:
            one, five, fifteen = os.getloadavg()
            return round(float(one), 2), round(float(five), 2), round(float(fifteen), 2)
        except (OSError, AttributeError):
            return None, None, None

    @staticmethod
    def _meminfo() -> dict[str, Any]:
        return _read_proc_meminfo()


def make_timing_provider(
    *,
    state: Any,
    camera_health_url: str | None = None,
    stream_health_url: str = "http://127.0.0.1:8081/health",
) -> TimingProvider:
    """Build a cheap timing snapshot from pipeline state + local health JSON."""

    def _provider() -> dict[str, Any]:
        out: dict[str, Any] = {
            "pipeline_cycle_seconds": getattr(state, "last_cycle_duration_seconds", None),
        }
        if camera_health_url:
            cam = _fetch_json(camera_health_url)
            if cam:
                if cam.get("last_capture_duration_seconds") is not None:
                    out["capture_duration_seconds"] = cam.get(
                        "last_capture_duration_seconds"
                    )
                if cam.get("image_age_seconds") is not None:
                    out["frame_age_seconds"] = cam.get("image_age_seconds")
                if cam.get("total_failed_captures") is not None:
                    out["failed_captures"] = cam.get("total_failed_captures")
        stream = _fetch_json(stream_health_url)
        if stream:
            frame = stream.get("frame") or {}
            if frame.get("ingest_lag_seconds") is not None:
                out["stream_lag_seconds"] = frame.get("ingest_lag_seconds")
            elif frame.get("age_seconds") is not None:
                # Fallback: buffer age ≈ time since Extra last ingested a still.
                out["stream_lag_seconds"] = frame.get("age_seconds")
            if frame.get("age_seconds") is not None:
                out["stream_frame_age_seconds"] = frame.get("age_seconds")
        return out

    return _provider


def health_url_from_source(source_url: str | None, health_url: str | None = None) -> str | None:
    if health_url:
        return str(health_url)
    if not source_url:
        return None
    parsed = urlparse(source_url)
    if not parsed.scheme or not parsed.netloc:
        return None
    return urlunparse((parsed.scheme, parsed.netloc, "/health", "", "", ""))


def _fetch_json(url: str, *, timeout: float = _TIMING_HTTP_TIMEOUT) -> dict[str, Any] | None:
    try:
        req = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "webcam-pipeline-metrics/1"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError, TimeoutError):
        return None


def _read_proc_stat_cpu(
    path: Path = _PROC_STAT,
) -> tuple[int, int] | None:
    try:
        line = path.read_text(encoding="utf-8").splitlines()[0]
    except (OSError, IndexError):
        return None
    if not line.startswith("cpu "):
        return None
    parts = line.split()
    try:
        vals = [int(x) for x in parts[1:8]]
    except (ValueError, IndexError):
        return None
    if len(vals) < 4:
        return None
    # user nice system idle iowait irq softirq
    idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
    total = sum(vals)
    return idle, total


def _read_proc_pid_cpu_ticks(pid: int) -> int | None:
    try:
        # /proc/<pid>/stat: after ") ", fields 14/15 (1-indexed) are utime/stime.
        text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        close = text.rfind(")")
        if close < 0:
            return None
        rest = text[close + 2 :].split()
        utime = int(rest[11])
        stime = int(rest[12])
        return utime + stime
    except (OSError, ValueError, IndexError):
        return None


def _read_proc_meminfo(path: Path = _PROC_MEMINFO) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    fields: dict[str, int] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, rest = line.split(":", 1)
        bits = rest.strip().split()
        if not bits:
            continue
        try:
            kib = int(bits[0])
        except ValueError:
            continue
        fields[key] = kib * 1024
    total = fields.get("MemTotal")
    available = fields.get("MemAvailable")
    if total is None:
        return {}
    if available is None:
        free = fields.get("MemFree", 0)
        buffers = fields.get("Buffers", 0)
        cached = fields.get("Cached", 0)
        available = free + buffers + cached
    used = max(0, total - available)
    used_pct = round((used / total) * 100.0, 1) if total else None
    swap_total = fields.get("SwapTotal") or 0
    swap_free = fields.get("SwapFree") or 0
    swap_used = max(0, swap_total - swap_free)
    swap_pct = (
        round((swap_used / swap_total) * 100.0, 1) if swap_total > 0 else 0.0
    )
    return {
        "total_bytes": total,
        "available_bytes": available,
        "used_pct": used_pct,
        "swap_total_bytes": swap_total,
        "swap_used_pct": swap_pct,
    }


def _read_disk_sectors_written(path: Path = _PROC_DISKSTATS) -> int | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    best: tuple[int, int] | None = None  # (priority, sectors)
    for line in lines:
        parts = line.split()
        if len(parts) < 10:
            continue
        name = parts[2]
        try:
            sectors = int(parts[9])
        except ValueError:
            continue
        # Prefer whole-disk nodes; skip partitions (mmcblk0p1, nvme0n1p2, sda1).
        if name.startswith("loop") or name.startswith("ram"):
            continue
        if name[-1:].isdigit() and (
            "p" in name
            or (name.startswith("sd") and len(name) > 3)
            or (name.startswith("vd") and len(name) > 3)
        ):
            # partitions — skip when a parent may exist
            if "p" in name or (name.startswith(("sd", "vd", "hd")) and name[-1].isdigit()):
                continue
        prio = 0
        if name.startswith("mmcblk") and "p" not in name:
            prio = 3
        elif name.startswith("nvme") and "p" not in name:
            prio = 3
        elif name.startswith(("sd", "vd")) and not name[-1].isdigit():
            prio = 2
        else:
            prio = 1
        if best is None or prio > best[0] or (prio == best[0] and sectors > best[1]):
            best = (prio, sectors)
    return None if best is None else best[1]


def read_throttle_status(*, runner: Runner | None = None) -> dict[str, Any]:
    """Pi firmware throttle bitmask when available (sysfs or vcgencmd)."""
    raw_hex: str | None = None
    for path in _THROTTLE_PATHS:
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if text:
            raw_hex = text.split()[0]
            break
    if raw_hex is None:
        run = runner or _run
        code, out, _err = run(["vcgencmd", "get_throttled"])
        if code == 0 and out:
            # throttled=0x50000
            for part in out.replace("\n", " ").split():
                if part.startswith("throttled="):
                    raw_hex = part.split("=", 1)[1]
                    break
                if part.startswith("0x") or part.startswith("0X"):
                    raw_hex = part
                    break
    if not raw_hex:
        return {"throttled": None, "hex": None, "flags": []}
    try:
        value = int(raw_hex, 0)
    except ValueError:
        return {"throttled": None, "hex": raw_hex, "flags": []}
    flags: list[str] = []
    mapping = (
        (1 << 0, "under-voltage"),
        (1 << 1, "arm-freq-capped"),
        (1 << 2, "throttled"),
        (1 << 3, "soft-temp-limit"),
        (1 << 16, "under-voltage-occurred"),
        (1 << 17, "arm-freq-capped-occurred"),
        (1 << 18, "throttled-occurred"),
        (1 << 19, "soft-temp-limit-occurred"),
    )
    for bit, label in mapping:
        if value & bit:
            flags.append(label)
    return {
        "throttled": bool(value & 0xF) or bool(flags),
        "hex": f"0x{value:x}",
        "flags": flags,
    }


def collect_system_status(
    *,
    data_path: Path | None = None,
    publish: dict[str, Any] | None = None,
    network: list[dict[str, Any]] | None = None,
    runner: Runner | None = None,
    now: float | None = None,
    metrics: HostMetrics | None = None,
) -> dict[str, Any]:
    """Read-only host glance for Pipeline home (disk, temp, units, clock, publish, metrics)."""
    ts = time.time() if now is None else float(now)
    disks = collect_disks(data_path=data_path)
    temp_c = read_soc_temperature_c()
    units = collect_unit_states(runner=runner)
    clock = collect_clock(runner=runner, now=ts)
    pub = summarize_publish(publish, now=ts)
    sampler = metrics if metrics is not None else get_host_metrics()
    snap = sampler.snapshot() if sampler is not None else _empty_metrics_snapshot()
    if snap.get("temperature_c") is None:
        snap["temperature_c"] = temp_c
    cores = os.cpu_count() or 4
    load1 = snap.get("load_1")
    if load1 is not None and cores > 0:
        snap["load_pct"] = round(min(150.0, (float(load1) / float(cores)) * 100.0), 1)
    else:
        snap["load_pct"] = None
    snap["cpu_count"] = cores
    if snap.get("disk_write_bps") is not None:
        snap["disk_write_mib_s"] = round(float(snap["disk_write_bps"]) / (1024.0 * 1024.0), 2)
    else:
        snap["disk_write_mib_s"] = None
    root_free = None
    for d in disks:
        if d.get("label") == "root" and d.get("free_pct") is not None:
            root_free = d.get("free_pct")
            break
    if root_free is None and disks:
        root_free = disks[0].get("free_pct")
    snap["disk_free_pct"] = root_free
    snap["thresholds"] = {k: dict(v) for k, v in GAUGE_THRESHOLDS.items()}
    return {
        "ok": True,
        "disks": disks,
        "temperature_c": snap.get("temperature_c", temp_c),
        "units": units,
        "clock": clock,
        "publish": pub,
        "network": list(network or []),
        "cpu": snap,  # expanded metrics object (history + host + timing + gauges)
        "metrics": snap,
        "thresholds": snap["thresholds"],
    }


def _empty_metrics_snapshot() -> dict[str, Any]:
    return {
        "percent": None,
        "load_1": None,
        "load_5": None,
        "load_15": None,
        "mem_used_pct": None,
        "mem_total_bytes": None,
        "mem_available_bytes": None,
        "swap_used_pct": None,
        "swap_total_bytes": None,
        "temperature_c": None,
        "throttled": None,
        "throttle_hex": None,
        "throttle_flags": [],
        "disk_write_bps": None,
        "capture_duration_seconds": None,
        "frame_age_seconds": None,
        "pipeline_cycle_seconds": None,
        "stream_lag_seconds": None,
        "stream_frame_age_seconds": None,
        "failed_captures": None,
        "service_cpu": {},
        "sample_interval_seconds": _DEFAULT_METRICS_INTERVAL,
        "history_seconds": _DEFAULT_METRICS_HISTORY_SEC,
        "history": [],
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
