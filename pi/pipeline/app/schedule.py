from __future__ import annotations

import json
import math
import threading
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from PIL import Image, ImageDraw

from shared.brand_overlay import (
    StatusCopy,
    cover_fit,
    draw_back_at_block,
    draw_live_clock,
    draw_site_badge,
    draw_status_overlay,
    format_back_at_lines,
    format_live_clock,
    plain_status_background,
    status_copy_from_mapping,
)

_DEFAULT_BASE = Path(__file__).resolve().parent / "assets" / "offline-base.jpg"

# Location (lat/lon/timezone) lives only in cameras/<id>/camera.yaml (Setup page).
# Schedule JSON stores window mode/offsets — never a second copy of coordinates.
_SITE_LOCATION_KEYS = frozenset({"timezone", "latitude", "longitude"})


def _parse_hhmm(value: str) -> time:
    parts = value.strip().split(":")
    return time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)


def sun_times(day: date, latitude: float, longitude: float, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """Approximate local sunrise/sunset (NOAA-style). Good enough for schedule offsets."""
    # Day of year
    n = day.timetuple().tm_yday
    lng_hour = longitude / 15.0
    # Sunrise
    t_rise = n + ((6 - lng_hour) / 24)
    t_set = n + ((18 - lng_hour) / 24)

    def _event(t: float, rising: bool) -> datetime:
        m = (0.9856 * t) - 3.289
        l = m + (1.916 * math.sin(math.radians(m))) + (0.020 * math.sin(math.radians(2 * m))) + 282.634
        l = l % 360
        ra = math.degrees(math.atan(0.91764 * math.tan(math.radians(l))))
        ra = ra % 360
        l_quad = math.floor(l / 90) * 90
        ra_quad = math.floor(ra / 90) * 90
        ra = ra + (l_quad - ra_quad)
        ra = ra / 15
        sin_dec = 0.39782 * math.sin(math.radians(l))
        cos_dec = math.cos(math.asin(sin_dec))
        cos_h = (math.cos(math.radians(90.833)) - (sin_dec * math.sin(math.radians(latitude)))) / (
            cos_dec * math.cos(math.radians(latitude))
        )
        cos_h = max(-1.0, min(1.0, cos_h))
        h = math.degrees(math.acos(cos_h))
        if rising:
            h = 360 - h
        h = h / 15
        t_local = h + ra - (0.06571 * t) - 6.622
        ut = (t_local - lng_hour) % 24
        # Build UTC then convert
        base = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        return (base + timedelta(hours=ut)).astimezone(tz)

    return _event(t_rise, True), _event(t_set, False)


@dataclass
class ScheduleStatus:
    public_online: bool
    mode: str
    reason: str
    back_at: datetime | None
    next_change_at: datetime | None
    now: datetime | None = None
    timezone: str | None = None
    sunrise: datetime | None = None
    sunset: datetime | None = None
    window_start: datetime | None = None
    window_stop: datetime | None = None
    status_text: StatusCopy | None = None

    def as_dict(self) -> dict[str, Any]:
        def _iso(dt: datetime | None) -> str | None:
            return dt.isoformat() if dt else None

        def _hm(dt: datetime | None) -> str | None:
            return dt.strftime("%H:%M") if dt else None

        # back_at = next public online (only meaningful while offline).
        # goes_offline_at = end of current public window (only while online).
        goes_offline_at = self.next_change_at if self.public_online else None
        goes_online_at = self.back_at if not self.public_online else None
        back_at_display: str | None = None

        if self.public_online:
            if goes_offline_at:
                summary = (
                    f"Public livestream is online until {_hm(goes_offline_at)} "
                    f"({self.timezone or 'local'})"
                )
            else:
                summary = f"Public livestream is online ({self.reason})"
        else:
            if goes_online_at:
                _label, time_line = format_back_at_lines(
                    goes_online_at,
                    now=self.now,
                    tz_name=self.timezone or "Europe/Berlin",
                    copy=self.status_text,
                )
                back_at_display = f"{_label} {time_line}"
                summary = (
                    f"Public livestream is offline — {back_at_display} "
                    f"({self.timezone or 'local'})"
                )
            else:
                summary = f"Public livestream is offline ({self.reason})"

        return {
            "public_online": self.public_online,
            "mode": self.mode,
            "reason": self.reason,
            "summary": summary,
            "now": _iso(self.now),
            "timezone": self.timezone,
            "back_at": _iso(self.back_at),
            "back_at_display": back_at_display,
            "goes_online_at": _iso(goes_online_at),
            "goes_offline_at": _iso(goes_offline_at),
            "next_change_at": _iso(self.next_change_at),
            "sunrise": _iso(self.sunrise),
            "sunset": _iso(self.sunset),
            "window_start": _iso(self.window_start),
            "window_stop": _iso(self.window_stop),
            "window": {
                "start": _iso(self.window_start),
                "stop": _iso(self.window_stop),
                "start_local": _hm(self.window_start),
                "stop_local": _hm(self.window_stop),
            },
            "sun": {
                "sunrise": _iso(self.sunrise),
                "sunset": _iso(self.sunset),
                "sunrise_local": _hm(self.sunrise),
                "sunset_local": _hm(self.sunset),
            },
            "scope": "public_live_only",
            "note": "Private LAN-only variants always use the live camera.",
        }


class PublicSchedule:
    """Gates public R2 livestream only. Private LAN-only variants stay live.

    Sunrise/sunset location comes from ``cameras/<id>/camera.yaml`` (Setup).
    Schedule config.json only stores mode, offsets, and placeholder options.
    """

    def __init__(self, repo_root: Path, camera_id: str = "") -> None:
        self.repo_root = repo_root
        self.camera_id = camera_id
        self.dir = repo_root / "data" / "schedule" / camera_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.dir / "config.json"
        self.custom_placeholder = self.dir / "placeholder.jpg"
        self._lock = threading.Lock()
        self._cfg = self._load_or_default()

    def _camera_yaml_path(self) -> Path:
        return self.repo_root / "cameras" / self.camera_id / "camera.yaml"

    def _read_site_location(self) -> dict[str, Any]:
        """Canonical place: Setup / cameras/<id>/camera.yaml."""
        out: dict[str, Any] = {
            "timezone": "UTC",
            "latitude": 0.0,
            "longitude": 0.0,
            "location_source": f"cameras/{self.camera_id}/camera.yaml" if self.camera_id else None,
            "location_set": False,
        }
        path = self._camera_yaml_path()
        if not path.is_file():
            return out
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            return out
        if not isinstance(raw, dict):
            return out
        if raw.get("timezone"):
            out["timezone"] = str(raw["timezone"])
        loc = raw.get("location") if isinstance(raw.get("location"), dict) else {}
        if loc.get("latitude") is not None and loc.get("longitude") is not None:
            out["latitude"] = float(loc["latitude"])
            out["longitude"] = float(loc["longitude"])
            out["location_set"] = True
        return out

    def _migrate_schedule_location_into_site(self, schedule_raw: dict[str, Any]) -> None:
        """One-shot: if Setup YAML lacks coords but old schedule JSON has real ones, copy them."""
        site = self._read_site_location()
        if site.get("location_set"):
            return
        try:
            lat = float(schedule_raw.get("latitude"))
            lon = float(schedule_raw.get("longitude"))
        except (TypeError, ValueError):
            return
        if lat == 0.0 and lon == 0.0:
            return
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            return
        try:
            from .site_settings import save_site

            patch: dict[str, Any] = {"latitude": lat, "longitude": lon}
            tz = schedule_raw.get("timezone")
            if tz and not site.get("timezone"):
                patch["timezone"] = str(tz)
            elif tz and site.get("timezone") in (None, "", "UTC") and str(tz) != "UTC":
                patch["timezone"] = str(tz)
            save_site(self.repo_root, self.camera_id, patch)
        except (ValueError, OSError, ImportError):
            # Missing camera.yaml or invalid — leave schedule evaluation on defaults.
            return

    def _schedule_defaults(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "mode": "solar",  # solar | fixed | always_on
            "solar": {
                "stop_offset_minutes_after_sunset": 30,
                "start_offset_minutes_before_sunrise": 30,
            },
            "fixed": {"start": "07:00", "stop": "21:30"},
            "placeholder": {"overlay_back_at": True},
        }

    def _strip_location(self, cfg: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in cfg.items() if k not in _SITE_LOCATION_KEYS}

    def _with_site_location(self, cfg: dict[str, Any]) -> dict[str, Any]:
        site = self._read_site_location()
        merged = dict(cfg)
        merged["timezone"] = site["timezone"]
        merged["latitude"] = site["latitude"]
        merged["longitude"] = site["longitude"]
        merged["location_source"] = site.get("location_source")
        merged["location_set"] = bool(site.get("location_set"))
        merged["location_ui"] = "GET /setup/ui"
        return merged

    def _load_or_default(self) -> dict[str, Any]:
        if self.config_path.exists():
            with self.config_path.open("r", encoding="utf-8") as fh:
                raw = json.load(fh) or {}
            if not isinstance(raw, dict):
                raw = {}
            self._migrate_schedule_location_into_site(raw)
            base = self._schedule_defaults()
            if "enabled" in raw:
                base["enabled"] = bool(raw["enabled"])
            if "mode" in raw:
                base["mode"] = raw["mode"]
            if "solar" in raw and isinstance(raw["solar"], dict):
                base["solar"] = {**base["solar"], **raw["solar"]}
            if "fixed" in raw and isinstance(raw["fixed"], dict):
                base["fixed"] = {**base["fixed"], **raw["fixed"]}
            if "placeholder" in raw and isinstance(raw["placeholder"], dict):
                base["placeholder"] = {**base["placeholder"], **raw["placeholder"]}
            # Drop legacy lat/lon/timezone from disk on next write
            if any(k in raw for k in _SITE_LOCATION_KEYS):
                self._write(base)
            return base
        cfg = self._schedule_defaults()
        self._write(cfg)
        return cfg

    def _write(self, cfg: dict[str, Any]) -> None:
        stored = self._strip_location(cfg)
        # Only persist schedule keys (defensive against accidental location bleed)
        clean: dict[str, Any] = {}
        for key in ("enabled", "mode", "solar", "fixed", "placeholder"):
            if key in stored:
                clean[key] = stored[key]
        tmp = self.config_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(clean, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.config_path)

    def get_config(self) -> dict[str, Any]:
        with self._lock:
            return self._with_site_location(json.loads(json.dumps(self._cfg)))

    def update_config(self, patch: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            cfg = json.loads(json.dumps(self._cfg))
            # Ignore location keys — Setup / camera.yaml is the only writer.
            for key in ("enabled", "mode"):
                if key in patch:
                    cfg[key] = patch[key]
            if "solar" in patch and isinstance(patch["solar"], dict):
                cfg["solar"] = {**cfg.get("solar", {}), **patch["solar"]}
            if "fixed" in patch and isinstance(patch["fixed"], dict):
                cfg["fixed"] = {**cfg.get("fixed", {}), **patch["fixed"]}
            if "placeholder" in patch and isinstance(patch["placeholder"], dict):
                cfg["placeholder"] = {**cfg.get("placeholder", {}), **patch["placeholder"]}
            if cfg.get("mode") not in ("solar", "fixed", "always_on"):
                raise ValueError("mode must be solar|fixed|always_on")
            self._cfg = self._strip_location(cfg)
            self._write(self._cfg)
            return self._with_site_location(json.loads(json.dumps(self._cfg)))

    def save_placeholder_jpeg(self, data: bytes) -> Path:
        if len(data) < 100 or data[:2] != b"\xff\xd8":
            raise ValueError("placeholder must be a JPEG")
        tmp = self.custom_placeholder.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(self.custom_placeholder)
        return self.custom_placeholder

    def clear_custom_placeholder(self) -> None:
        self.custom_placeholder.unlink(missing_ok=True)

    def placeholder_base_path(self) -> Path | None:
        """Photo behind the night slide, or None for a generated plain slide.

        A custom upload wins. Otherwise the text-free forest base, when that
        file is still installed. A copied project that deletes it gets a plain
        dark slide instead of the Example photo.
        """
        if self.custom_placeholder.exists():
            return self.custom_placeholder
        if _DEFAULT_BASE.is_file():
            return _DEFAULT_BASE
        return None

    def _status_copy(self) -> StatusCopy:
        path = self._camera_yaml_path()
        if not path.is_file():
            return StatusCopy.english()
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            return StatusCopy.english()
        if not isinstance(raw, dict):
            return StatusCopy.english()
        return status_copy_from_mapping(raw.get("status_text"))

    def evaluate(self, now: datetime | None = None) -> ScheduleStatus:
        with self._lock:
            cfg = self._with_site_location(self._cfg)
        tz_name = str(cfg.get("timezone") or "Europe/Berlin")
        tz = ZoneInfo(tz_name)
        now = (now or datetime.now(tz)).astimezone(tz)
        lat = float(cfg["latitude"])
        lon = float(cfg["longitude"])
        sunrise, sunset = sun_times(now.date(), lat, lon, tz)
        tomorrow = now.date() + timedelta(days=1)
        sunrise_tom, _sunset_tom = sun_times(tomorrow, lat, lon, tz)
        copy = self._status_copy()

        def _status(**kwargs: Any) -> ScheduleStatus:
            return ScheduleStatus(
                now=now,
                timezone=tz_name,
                status_text=copy,
                **kwargs,
            )

        if not cfg.get("enabled", True) or cfg.get("mode") == "always_on":
            return _status(
                public_online=True,
                mode=str(cfg.get("mode") or "always_on"),
                reason="schedule disabled or always_on",
                back_at=None,
                next_change_at=None,
                sunrise=sunrise,
                sunset=sunset,
            )

        mode = str(cfg.get("mode") or "solar")
        if mode == "fixed":
            start_t = _parse_hhmm(str((cfg.get("fixed") or {}).get("start") or "07:00"))
            stop_t = _parse_hhmm(str((cfg.get("fixed") or {}).get("stop") or "21:30"))
            start = datetime.combine(now.date(), start_t, tzinfo=tz)
            stop = datetime.combine(now.date(), stop_t, tzinfo=tz)
            if stop <= start:
                # overnight window e.g. 21:00–07:00 means online outside? We define online = [start, stop)
                pass
            online = start <= now < stop
            if online:
                return _status(
                    public_online=True,
                    mode=mode,
                    reason="within fixed public window",
                    back_at=None,
                    next_change_at=stop,
                    sunrise=sunrise,
                    sunset=sunset,
                    window_start=start,
                    window_stop=stop,
                )
            # offline: back at today's start if before start, else tomorrow's start
            back = start if now < start else start + timedelta(days=1)
            return _status(
                public_online=False,
                mode=mode,
                reason="outside fixed public window",
                back_at=back,
                next_change_at=back,
                sunrise=sunrise,
                sunset=sunset,
                window_start=start,
                window_stop=stop,
            )

        # solar: online from (sunrise - start_before) until (sunset + stop_after)
        solar = cfg.get("solar") or {}
        start_before = int(solar.get("start_offset_minutes_before_sunrise", 30))
        stop_after = int(solar.get("stop_offset_minutes_after_sunset", 30))
        start = sunrise - timedelta(minutes=start_before)
        stop = sunset + timedelta(minutes=stop_after)
        # If before today's start, we're still in yesterday's night → back_at = start
        if now < start:
            return _status(
                public_online=False,
                mode=mode,
                reason="before solar public window",
                back_at=start,
                next_change_at=start,
                sunrise=sunrise,
                sunset=sunset,
                window_start=start,
                window_stop=stop,
            )
        if now < stop:
            return _status(
                public_online=True,
                mode=mode,
                reason="within solar public window",
                back_at=None,
                next_change_at=stop,
                sunrise=sunrise,
                sunset=sunset,
                window_start=start,
                window_stop=stop,
            )
        # after stop → next morning
        start_tom = sunrise_tom - timedelta(minutes=start_before)
        return _status(
            public_online=False,
            mode=mode,
            reason="after solar public window",
            back_at=start_tom,
            next_change_at=start_tom,
            sunrise=sunrise,
            sunset=sunset,
            window_start=start,
            window_stop=stop,
        )

    def render_public_placeholder(
        self,
        status: ScheduleStatus,
        size: tuple[int, int] | None = None,
        *,
        site_badge: str | None = None,
        brand: str = "Webcam",
    ) -> Path:
        """Write a JPEG ready to publish (optional dynamic 'Wieder da ab').

        Cover-fit the photo first, then draw Nachts / Wieder-da / badge at the
        target pixel size — never anisotropically scale a text-baked layer.
        """
        copy = status.status_text or self._status_copy()
        custom = self.custom_placeholder.exists()
        src_path = self.placeholder_base_path()
        if src_path is None:
            target = (int(size[0]), int(size[1])) if size else (1920, 1080)
            base = plain_status_background(target)
            custom = False
        else:
            src = Image.open(src_path).convert("RGB")
            target = (int(size[0]), int(size[1])) if size else src.size
            base = cover_fit(src, target) if size and size != src.size else src.copy()
        cfg = self.get_config()
        overlay = bool((cfg.get("placeholder") or {}).get("overlay_back_at", True))
        draw = ImageDraw.Draw(base)
        back_label = back_time = None
        if overlay and status.back_at is not None:
            tz_name = cfg.get("timezone") or status.timezone or "Europe/Berlin"
            back_label, back_time = format_back_at_lines(
                status.back_at,
                now=status.now,
                tz_name=tz_name,
                copy=copy,
            )
        if not custom:
            draw_status_overlay(
                draw,
                width=base.width,
                height=base.height,
                title=copy.night_title,
                body=copy.night_body,
                brand=brand or "Webcam",
                back_at_label=back_label,
                back_at_time=back_time,
                back_at_panel=False,
            )
        elif back_label and back_time:
            # Custom upload or legacy text-baked asset: only burn dynamic Wieder-da.
            draw_back_at_block(
                draw,
                width=base.width,
                height=base.height,
                label=back_label,
                time_line=back_time,
                y_frac=0.54,
                panel=True,
            )
        badge = (site_badge or "").strip()
        if badge:
            draw_site_badge(draw, text=badge, width=base.width, height=base.height)
        # Wall clock (not „Wieder da“) so the public live key keeps ticking overnight.
        tz_name = str(cfg.get("timezone") or status.timezone or "Europe/Berlin")
        clock = format_live_clock(status.now, tz_name=tz_name)
        draw_live_clock(draw, text=clock, width=base.width, height=base.height)
        out = self.dir / "placeholder-live.jpg"
        base.save(out, format="JPEG", quality=85, optimize=True)
        return out