from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.schedule import PublicSchedule, sun_times


def _seed_schellbronn(tmp_path: Path) -> None:
    """Solar tests opt into this place. The code default is UTC / 0,0."""
    cam = tmp_path / "cameras" / "schellbronn"
    cam.mkdir(parents=True, exist_ok=True)
    (cam / "camera.yaml").write_text(
        "id: schellbronn\ntimezone: Europe/Berlin\nlocation:\n  latitude: 48.7855\n  longitude: 8.7490\n",
        encoding="utf-8",
    )


def test_sun_times_schellbronn_summer():
    tz = ZoneInfo("Europe/Berlin")
    # mid-June: long day
    sunrise, sunset = sun_times(datetime(2026, 6, 21).date(), 48.7855, 8.7490, tz)
    assert sunrise.hour < 7
    assert sunset.hour >= 20


def test_schedule_solar_offline_night(tmp_path: Path):
    _seed_schellbronn(tmp_path)
    sched = PublicSchedule(tmp_path, "schellbronn")
    tz = ZoneInfo("Europe/Berlin")
    # 23:00 local — after sunset window
    night = datetime(2026, 6, 21, 23, 0, tzinfo=tz)
    status = sched.evaluate(now=night)
    assert status.public_online is False
    assert status.back_at is not None
    assert status.back_at > night


def test_schedule_solar_online_day(tmp_path: Path):
    _seed_schellbronn(tmp_path)
    sched = PublicSchedule(tmp_path, "schellbronn")
    tz = ZoneInfo("Europe/Berlin")
    noon = datetime(2026, 6, 21, 12, 0, tzinfo=tz)
    status = sched.evaluate(now=noon)
    assert status.public_online is True
    assert status.back_at is None
    assert status.next_change_at is not None
    d = status.as_dict()
    assert d["goes_offline_at"] is not None
    assert d["goes_online_at"] is None
    assert d["back_at"] is None
    assert "Public livestream is online until" in d["summary"]
    assert d["window"]["start_local"]
    assert d["sun"]["sunrise_local"]
    assert d["timezone"] == "Europe/Berlin"
    assert d["now"]


def test_schedule_status_offline_fills_back_at(tmp_path: Path):
    _seed_schellbronn(tmp_path)
    sched = PublicSchedule(tmp_path, "schellbronn")
    tz = ZoneInfo("Europe/Berlin")
    night = datetime(2026, 6, 21, 23, 0, tzinfo=tz)
    d = sched.evaluate(now=night).as_dict()
    assert d["public_online"] is False
    assert d["back_at"] is not None
    assert d["goes_online_at"] == d["back_at"]
    assert d["goes_offline_at"] is None
    assert "Public livestream is offline" in d["summary"]
    assert "Back at" in d["summary"]
    assert "tomorrow" in d["summary"] or "today" in d["summary"]


def test_schedule_fixed_window(tmp_path: Path):
    _seed_schellbronn(tmp_path)
    sched = PublicSchedule(tmp_path, "schellbronn")
    sched.update_config({"mode": "fixed", "fixed": {"start": "08:00", "stop": "20:00"}})
    tz = ZoneInfo("Europe/Berlin")
    assert sched.evaluate(now=datetime(2026, 1, 10, 9, 0, tzinfo=tz)).public_online is True
    assert sched.evaluate(now=datetime(2026, 1, 10, 21, 0, tzinfo=tz)).public_online is False


def test_placeholder_render(tmp_path: Path):
    _seed_schellbronn(tmp_path)
    sched = PublicSchedule(tmp_path, "schellbronn")
    status = sched.evaluate(now=datetime(2026, 1, 10, 23, 0, tzinfo=ZoneInfo("Europe/Berlin")))
    path = sched.render_public_placeholder(
        status,
        size=(800, 450),
        site_badge="ferienpark-schellbronn.de  ·  12,4 °C",
    )
    data = path.read_bytes()
    assert data[:2] == b"\xff\xd8"
    assert len(data) > 1000
    from PIL import Image

    with Image.open(path) as im:
        assert im.size == (800, 450)
        # Bottom-left wall clock (date+time) — not a frozen capture stamp.
        assert im.getpixel((24, 420)) != im.getpixel((400, 200))


def test_placeholder_clock_changes_with_minute(tmp_path: Path):
    _seed_schellbronn(tmp_path)
    """Night placeholder must not burn a multi-hour-stale clock."""
    from shared.brand_overlay import format_live_clock

    sched = PublicSchedule(tmp_path, "schellbronn")
    tz = ZoneInfo("Europe/Berlin")
    a = sched.evaluate(now=datetime(2026, 1, 10, 23, 0, tzinfo=tz))
    b = sched.evaluate(now=datetime(2026, 1, 10, 23, 1, tzinfo=tz))
    assert format_live_clock(a.now) == "2026-01-10 23:00"
    assert format_live_clock(b.now) == "2026-01-10 23:01"
    path_a = sched.render_public_placeholder(a, size=(800, 450))
    bytes_a = path_a.read_bytes()
    path_b = sched.render_public_placeholder(b, size=(800, 450))
    bytes_b = path_b.read_bytes()
    assert bytes_a != bytes_b
    assert bytes_a[:2] == b"\xff\xd8"
    assert bytes_b[:2] == b"\xff\xd8"

def test_placeholder_cover_fit_no_stretch(tmp_path: Path):
    _seed_schellbronn(tmp_path)
    """Wide variant size must cover-crop 16:9 base — never stretch."""
    from PIL import Image

    from shared.brand_overlay import StatusCopy, cover_fit, format_back_at_lines

    label, time_line = format_back_at_lines(
        datetime(2026, 6, 22, 5, 30, tzinfo=ZoneInfo("Europe/Berlin")),
        now=datetime(2026, 6, 21, 23, 0, tzinfo=ZoneInfo("Europe/Berlin")),
    )
    assert label == "Back at"
    assert time_line == "tomorrow 05:30"
    de_label, de_time = format_back_at_lines(
        datetime(2026, 6, 22, 5, 30, tzinfo=ZoneInfo("Europe/Berlin")),
        now=datetime(2026, 6, 21, 23, 0, tzinfo=ZoneInfo("Europe/Berlin")),
        copy=StatusCopy.german(),
    )
    assert de_label == "Wieder da ab"
    assert de_time == "morgen 05:30"

    # Synthetic checker: cover to wider AR keeps height crop, not stretch
    src = Image.new("RGB", (1920, 1080), (40, 80, 40))
    out = cover_fit(src, (1600, 750))
    assert out.size == (1600, 750)

    sched = PublicSchedule(tmp_path, "schellbronn")
    status = sched.evaluate(now=datetime(2026, 1, 10, 23, 0, tzinfo=ZoneInfo("Europe/Berlin")))
    path = sched.render_public_placeholder(status, size=(1600, 750))
    with Image.open(path) as im:
        assert im.size == (1600, 750)


def test_schedule_without_camera_yaml_is_neutral(tmp_path: Path):
    cfg = PublicSchedule(tmp_path, "shed").get_config()
    assert cfg["timezone"] == "UTC"
    assert cfg["latitude"] == 0.0
    assert cfg["longitude"] == 0.0


def test_new_schedule_reads_camera_yaml_location(tmp_path: Path):
    cam = tmp_path / "cameras" / "example"
    cam.mkdir(parents=True)
    (cam / "camera.yaml").write_text(
        "id: example\ntimezone: Pacific/Auckland\nlocation:\n  latitude: -36.85\n  longitude: 174.76\n",
        encoding="utf-8",
    )
    sched = PublicSchedule(tmp_path, "example")
    cfg = sched.get_config()
    assert cfg["timezone"] == "Pacific/Auckland"
    assert cfg["latitude"] == -36.85
    assert cfg["longitude"] == 174.76
    assert cfg["location_set"] is True
    assert "camera.yaml" in (cfg.get("location_source") or "")


def test_schedule_update_ignores_location_patch(tmp_path: Path):
    _seed_schellbronn(tmp_path)
    sched = PublicSchedule(tmp_path, "schellbronn")
    before = sched.get_config()
    out = sched.update_config(
        {
            "latitude": 1.0,
            "longitude": 2.0,
            "timezone": "UTC",
            "mode": "fixed",
            "fixed": {"start": "09:00", "stop": "18:00"},
        }
    )
    assert out["mode"] == "fixed"
    assert out["latitude"] == before["latitude"]
    assert out["longitude"] == before["longitude"]
    assert out["timezone"] == "Europe/Berlin"
    stored = (tmp_path / "data" / "schedule" / "schellbronn" / "config.json").read_text()
    assert "latitude" not in stored
    assert "longitude" not in stored
    assert "timezone" not in stored


def test_schedule_migrates_legacy_location_into_camera_yaml(tmp_path: Path):
    cam = tmp_path / "cameras" / "shed"
    cam.mkdir(parents=True)
    (cam / "camera.yaml").write_text(
        "id: shed\ndisplay_name: Shed\ntimezone: UTC\n",
        encoding="utf-8",
    )
    sched_dir = tmp_path / "data" / "schedule" / "shed"
    sched_dir.mkdir(parents=True)
    (sched_dir / "config.json").write_text(
        '{"enabled": true, "mode": "solar", "timezone": "Europe/Berlin",'
        ' "latitude": 48.78, "longitude": 8.75,'
        ' "solar": {"start_offset_minutes_before_sunrise": 30,'
        ' "stop_offset_minutes_after_sunset": 30},'
        ' "fixed": {"start": "07:00", "stop": "21:30"},'
        ' "placeholder": {"overlay_back_at": true}}\n',
        encoding="utf-8",
    )
    sched = PublicSchedule(tmp_path, "shed")
    cfg = sched.get_config()
    assert cfg["latitude"] == 48.78
    assert cfg["longitude"] == 8.75
    assert cfg["timezone"] == "Europe/Berlin"
    yaml_text = (cam / "camera.yaml").read_text()
    assert "48.78" in yaml_text
    assert "8.75" in yaml_text
    stored = (sched_dir / "config.json").read_text()
    assert "latitude" not in stored
    assert "longitude" not in stored


def test_german_status_text_and_plain_night_slide(tmp_path: Path, monkeypatch):
    import app.schedule as sched_mod
    from PIL import Image

    from shared.brand_overlay import status_copy_from_mapping

    assert status_copy_from_mapping(None).maintenance_title == "Maintenance"
    assert status_copy_from_mapping(None).back_at_label == "Back at"

    monkeypatch.setattr(sched_mod, "_DEFAULT_BASE", tmp_path / "missing-offline-base.jpg")
    cam = tmp_path / "cameras" / "shed"
    cam.mkdir(parents=True)
    (cam / "camera.yaml").write_text(
        "id: shed\ntimezone: Europe/Berlin\n"
        "location:\n  latitude: 48.7855\n  longitude: 8.7490\n"
        "status_text:\n"
        "  night_title: Nachts offline\n"
        "  back_at_label: Wieder da ab\n"
        "  today: heute\n"
        "  tomorrow: morgen\n",
        encoding="utf-8",
    )
    sched = PublicSchedule(tmp_path, "shed")
    night = datetime(2026, 6, 21, 23, 0, tzinfo=ZoneInfo("Europe/Berlin"))
    status = sched.evaluate(now=night)
    assert "Wieder da ab" in status.as_dict()["summary"]
    assert "morgen" in status.as_dict()["summary"] or "heute" in status.as_dict()["summary"]
    path = sched.render_public_placeholder(status, size=(320, 180))
    with Image.open(path) as im:
        assert im.size == (320, 180)
        corner = im.getpixel((2, 2))
        assert corner[0] < 40
        assert corner[2] >= corner[0]
