"""Daylight frames kept on the Pi, and the video made from one day.

The current live JPEG can still publish. These files never go to the bucket.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

DAY_RE_SRC = r"^\d{4}-\d{2}-\d{2}$"

# One stored frame every 2 minutes, played at 12 fps → about 30s for a 12-hour day.
MP4_FPS = 12
MP4_WIDTH = 1280
GIF_FPS = 8
GIF_WIDTH = 640

Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]

_jobs_lock = threading.Lock()
_jobs: dict[tuple[str, str, str], dict[str, Any]] = {}


class TimelapseError(ValueError):
    pass


def archive_root(repo_root: Path, camera_id: str) -> Path:
    return repo_root / "data" / camera_id / "timelapse"


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def local_time(timestamp: float, timezone_name: str) -> datetime:
    return datetime.fromtimestamp(timestamp, _zone(timezone_name))


# Default budget for data/<cam>/timelapse/ (frames + exports). Retention days still apply.
# Tuned for a ~500 GB NVMe Pi; override per camera with timelapse.max_gb in camera.yaml.
DEFAULT_MAX_GB = 40.0


class TimelapseArchive:
    def __init__(
        self,
        root: Path,
        *,
        timezone: str = "UTC",
        min_interval_seconds: int = 120,
        retention_days: int = 400,
        max_bytes: int | None = None,
        enabled: bool = True,
    ) -> None:
        self.root = root
        self.frames = root / "frames"
        self.exports = root / "exports"
        self.timezone = timezone
        self.min_interval_seconds = max(30, int(min_interval_seconds))
        self.retention_days = int(retention_days)
        if max_bytes is None:
            self.max_bytes = int(DEFAULT_MAX_GB * 1024**3)
        else:
            self.max_bytes = max(0, int(max_bytes))
        self.enabled = enabled

    def maybe_store(self, src: Path, captured_at: float) -> Path | None:
        """Copy a daylight JPEG if the interval has elapsed. Night frames are not passed in."""
        if not self.enabled or not src.is_file():
            return None
        data = src.read_bytes()
        if len(data) < 100 or data[:2] != b"\xff\xd8":
            return None
        when = local_time(captured_at, self.timezone)
        day = when.strftime("%Y-%m-%d")
        day_dir = self.frames / day
        latest = _latest_frame(day_dir)
        if latest is not None:
            stamp = _frame_clock(day, latest.name, self.timezone)
            if stamp is not None and (when - stamp).total_seconds() < self.min_interval_seconds:
                return None
        day_dir.mkdir(parents=True, exist_ok=True)
        dest = day_dir / f"{when.strftime('%H%M%S')}.jpg"
        _write_bytes(dest, data)
        self.prune(when)
        return dest

    def list_days(self) -> list[dict[str, Any]]:
        self.prune()
        if not self.frames.is_dir():
            return []
        days = []
        for day_dir in sorted(self.frames.iterdir(), reverse=True):
            if not day_dir.is_dir() or not _is_day(day_dir.name):
                continue
            info = self.describe(day_dir.name)
            if info["frames"]:
                days.append(info)
        return days

    def storage_info(self) -> dict[str, Any]:
        """Bytes under this archive (frames + exports). Never uploaded."""
        used = _dir_size(self.root)
        limit = self.max_bytes
        pct = (100.0 * used / limit) if limit > 0 else None
        if pct is not None:
            pct = round(pct, 2) if pct < 1 else round(pct, 1)
        return {
            "used_bytes": used,
            "max_bytes": limit if limit > 0 else None,
            "used_human": _fmt_bytes(used),
            "max_human": _fmt_bytes(limit) if limit > 0 else None,
            "used_pct": pct,
            "max_gb": round(limit / 1024**3, 3) if limit > 0 else None,
            "retention_days": self.retention_days,
            "local_only": True,
        }

    def describe(self, day: str) -> dict[str, Any]:
        day = _require_day(day)
        frames = _frames(self.frames / day)
        first = _clock_label(frames[0].name) if frames else None
        last = _clock_label(frames[-1].name) if frames else None
        return {
            "day": day,
            "frames": len(frames),
            "first": first,
            "last": last,
            "mp4": self._fresh(day, "mp4"),
            "gif": self._fresh(day, "gif"),
            "building": _building(self.root, day),
            "interval_seconds": self.min_interval_seconds,
            "mp4_fps": MP4_FPS,
            "local_only": True,
        }

    def export_path(self, day: str, kind: str) -> Path:
        day = _require_day(day)
        kind = _require_kind(kind)
        return self.exports / f"{day}.{kind}"

    def thumb_path(self, day: str) -> Path | None:
        frames = _frames(self.frames / _require_day(day))
        return frames[-1] if frames else None

    def build(self, day: str, kind: str, *, runner: Runner | None = None) -> Path:
        day = _require_day(day)
        kind = _require_kind(kind)
        frames = _frames(self.frames / day)
        if len(frames) < 2:
            raise TimelapseError("need at least 2 frames")
        if shutil.which("ffmpeg") is None and runner is None:
            raise TimelapseError("ffmpeg is not installed on this Pi")
        self.exports.mkdir(parents=True, exist_ok=True)
        work = self.exports / f".work-{day}-{kind}"
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True)
        try:
            for index, src in enumerate(frames, start=1):
                dest = work / f"{index:05d}.jpg"
                try:
                    os.link(src, dest)
                except OSError:
                    shutil.copy2(src, dest)
            out = self.export_path(day, kind)
            cmd = _ffmpeg_cmd(work, out, kind)
            completed = (runner or _run_ffmpeg)(cmd)
            if completed.returncode != 0 or not out.is_file():
                detail = (completed.stderr or completed.stdout or "ffmpeg failed").strip()
                raise TimelapseError(detail[-400:] or "ffmpeg failed")
            _write_bytes(out.with_suffix(out.suffix + ".stamp"), _fingerprint(frames).encode())
            self.prune()
            return out
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _fresh(self, day: str, kind: str) -> bool:
        path = self.exports / f"{day}.{kind}"
        stamp = Path(str(path) + ".stamp")
        if not path.is_file() or not stamp.is_file():
            return False
        frames = _frames(self.frames / day)
        return stamp.read_text(encoding="utf-8") == _fingerprint(frames)

    def prune(self, today: datetime | None = None) -> list[str]:
        """Drop days past retention_days, then oldest days until under max_bytes."""
        removed: list[str] = []
        if not self.frames.is_dir():
            return removed
        when = today or local_time(time.time(), self.timezone)
        if self.retention_days > 0:
            cutoff = (when.date() - timedelta(days=self.retention_days)).isoformat()
            for day_dir in sorted(self.frames.iterdir()):
                if day_dir.is_dir() and _is_day(day_dir.name) and day_dir.name < cutoff:
                    self._delete_day(day_dir.name)
                    removed.append(day_dir.name)
        if self.max_bytes > 0:
            while _dir_size(self.root) > self.max_bytes:
                oldest = self._oldest_day()
                if oldest is None:
                    break
                self._delete_day(oldest)
                removed.append(oldest)
        return removed

    def _oldest_day(self) -> str | None:
        days = sorted(
            p.name for p in self.frames.iterdir() if p.is_dir() and _is_day(p.name)
        )
        return days[0] if days else None

    def delete_day(self, day: str) -> dict[str, Any]:
        """Remove one day's frames + rendered exports. Safe day id only (YYYY-MM-DD)."""
        day = _require_day(day)
        if _building(self.root, day):
            raise TimelapseError("cannot delete while a video is building for this day")
        day_dir = self.frames / day
        existed = day_dir.is_dir() or any(
            (self.exports / f"{day}.{kind}").is_file() for kind in ("mp4", "gif")
        )
        self._delete_day(day)
        _clear_jobs(self.root, day)
        return {
            "ok": True,
            "deleted": day,
            "existed": existed,
            "local_only": True,
            "storage": self.storage_info(),
        }

    def _delete_day(self, day: str) -> None:
        day = _require_day(day)
        # Paths are only under this archive root; day is validated YYYY-MM-DD (no .. / slashes).
        day_dir = (self.frames / day).resolve()
        frames_root = self.frames.resolve()
        if day_dir != frames_root / day:
            raise TimelapseError("invalid day path")
        if day_dir.is_dir():
            shutil.rmtree(day_dir, ignore_errors=True)
        if self.exports.is_dir():
            exports_root = self.exports.resolve()
            for kind in ("mp4", "gif"):
                export = (self.exports / f"{day}.{kind}").resolve()
                if export.parent != exports_root:
                    continue
                export.unlink(missing_ok=True)
                Path(str(export) + ".stamp").unlink(missing_ok=True)
            for leftover in self.exports.glob(f".work-{day}-*"):
                work = leftover.resolve()
                if work.parent == exports_root:
                    shutil.rmtree(work, ignore_errors=True)


def request_build(archive: TimelapseArchive, day: str, kind: str) -> dict[str, Any]:
    """Start one encode if this day is not already building. Returns status."""
    day = _require_day(day)
    kind = _require_kind(kind)
    key = (str(archive.root), day, kind)
    with _jobs_lock:
        job = _jobs.get(key)
        if job and job.get("state") == "running":
            return archive.describe(day)
        if archive._fresh(day, kind):
            return archive.describe(day)
        _jobs[key] = {"state": "running", "error": ""}

    def _run() -> None:
        try:
            archive.build(day, kind)
            state, error = "ready", ""
        except Exception as exc:  # noqa: BLE001 — surfaced in the LAN UI
            state, error = "error", str(exc)
        with _jobs_lock:
            _jobs[key] = {"state": state, "error": error}

    threading.Thread(target=_run, name=f"timelapse-{day}-{kind}", daemon=True).start()
    info = archive.describe(day)
    info["building"] = kind
    return info


def archive_for(repo_root: Path, camera_id: str, profile: Any) -> TimelapseArchive:
    cfg = getattr(profile, "timelapse", None) or {}
    return TimelapseArchive(
        archive_root(repo_root, camera_id),
        timezone=getattr(profile, "timezone", None) or "UTC",
        min_interval_seconds=int(cfg.get("min_interval_seconds", 120)),
        retention_days=int(cfg.get("retention_days", 400)),
        max_bytes=_max_bytes_from_cfg(cfg),
        enabled=bool(cfg.get("enabled", True)),
    )


def _max_bytes_from_cfg(cfg: dict[str, Any]) -> int:
    if cfg.get("max_bytes") is not None:
        return max(0, int(cfg["max_bytes"]))
    if cfg.get("max_gb") is not None:
        return max(0, int(float(cfg["max_gb"]) * 1024**3))
    return int(DEFAULT_MAX_GB * 1024**3)


def _dir_size(root: Path) -> int:
    if not root.exists():
        return 0
    total = 0
    for path in root.rglob("*"):
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            continue
    return total


def _fmt_bytes(n: int) -> str:
    value = float(max(0, int(n)))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{int(n)} B"


def _ffmpeg_cmd(work: Path, out: Path, kind: str) -> list[str]:
    pattern = str(work / "%05d.jpg")
    if kind == "mp4":
        return [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-framerate", str(MP4_FPS), "-i", pattern,
            "-vf", f"scale={MP4_WIDTH}:-2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(out),
        ]
    return [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-framerate", str(GIF_FPS), "-i", pattern,
        "-filter_complex",
        f"scale={GIF_WIDTH}:-2:flags=lanczos,split[s0][s1];[s0]palettegen=stats_mode=diff[p];[s1][p]paletteuse",
        str(out),
    ]


def _run_ffmpeg(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=900, check=False)


def _frames(day_dir: Path) -> list[Path]:
    if not day_dir.is_dir():
        return []
    return sorted(p for p in day_dir.glob("*.jpg") if p.is_file())


def _latest_frame(day_dir: Path) -> Path | None:
    frames = _frames(day_dir)
    return frames[-1] if frames else None


def _frame_clock(day: str, name: str, timezone_name: str) -> datetime | None:
    stem = Path(name).stem
    if len(stem) != 6 or not stem.isdigit():
        return None
    try:
        return datetime.strptime(f"{day} {stem}", "%Y-%m-%d %H%M%S").replace(tzinfo=_zone(timezone_name))
    except ValueError:
        return None


def _clock_label(name: str) -> str:
    stem = Path(name).stem
    if len(stem) == 6 and stem.isdigit():
        return f"{stem[0:2]}:{stem[2:4]}:{stem[4:6]}"
    return stem


def _is_day(value: str) -> bool:
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        return False
    return value.replace("-", "").isdigit()


def _require_day(day: str) -> str:
    if not _is_day(day):
        raise TimelapseError("day must be YYYY-MM-DD")
    return day


def _require_kind(kind: str) -> str:
    if kind not in ("mp4", "gif"):
        raise TimelapseError("format must be mp4 or gif")
    return kind


def _fingerprint(frames: list[Path]) -> str:
    last = frames[-1]
    return f"{len(frames)}:{last.name}:{last.stat().st_size}"


def _building(root: Path, day: str) -> str | None:
    with _jobs_lock:
        for (_root, job_day, kind), job in _jobs.items():
            if _root == str(root) and job_day == day and job.get("state") == "running":
                return kind
    return None


def job_error(root: Path, day: str) -> str:
    with _jobs_lock:
        for (_root, job_day, _kind), job in _jobs.items():
            if _root == str(root) and job_day == day and job.get("state") == "error":
                return str(job.get("error") or "")
    return ""


def _clear_jobs(root: Path, day: str) -> None:
    with _jobs_lock:
        for key in list(_jobs):
            if key[0] == str(root) and key[1] == day:
                _jobs.pop(key, None)


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
