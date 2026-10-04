"""Local daylight archive and timelapse encode. Nothing is uploaded."""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from datetime import datetime
from http.server import ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from PIL import Image

REPO = Path(__file__).resolve().parents[3]
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(ROOT))

from app.state import PipelineState  # noqa: E402
from app.serve_private import make_handler  # noqa: E402
from app.timelapse import TimelapseArchive, local_time  # noqa: E402


def _jpeg(path: Path, color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 24), color).save(path, format="JPEG")


def test_maybe_store_keeps_two_minute_gaps_in_local_time(tmp_path: Path):
    archive = TimelapseArchive(tmp_path / "tl", timezone="Europe/Berlin", min_interval_seconds=120)
    src = tmp_path / "live.jpg"
    _jpeg(src, (10, 20, 30))
    # 2026-10-01 12:00:00 Berlin
    noon = datetime(2026, 10, 1, 12, 0, tzinfo=ZoneInfo("Europe/Berlin")).timestamp()
    first = archive.maybe_store(src, noon)
    assert first is not None
    assert first.parent.name == "2026-10-01"
    assert first.name == "120000.jpg"
    assert archive.maybe_store(src, noon + 60) is None
    second = archive.maybe_store(src, noon + 120)
    assert second is not None and second.name == "120200.jpg"
    assert local_time(noon, "Europe/Berlin").strftime("%H%M%S") == "120000"


def test_build_uses_ffmpeg_and_marks_the_file_fresh(tmp_path: Path):
    archive = TimelapseArchive(tmp_path / "tl", timezone="UTC", min_interval_seconds=30)
    day = archive.frames / "2026-10-01"
    _jpeg(day / "120000.jpg", (1, 2, 3))
    _jpeg(day / "120200.jpg", (4, 5, 6))
    seen: list[list[str]] = []

    def runner(cmd: list[str]):
        seen.append(cmd)
        Path(cmd[-1]).write_bytes(b"mp4")
        class Done:
            returncode = 0
            stderr = ""
            stdout = ""
        return Done()

    out = archive.build("2026-10-01", "mp4", runner=runner)
    assert out.read_bytes() == b"mp4"
    assert seen and seen[0][0] == "ffmpeg"
    assert archive.describe("2026-10-01")["mp4"] is True
    assert archive.describe("2026-10-01")["frames"] == 2


def test_delete_day_removes_frames_and_exports_only(tmp_path: Path):
    archive = TimelapseArchive(tmp_path / "tl", timezone="UTC")
    keep = archive.frames / "2026-09-02"
    drop = archive.frames / "2026-09-01"
    _jpeg(keep / "120000.jpg", (1, 1, 1))
    _jpeg(drop / "120000.jpg", (2, 2, 2))
    _jpeg(drop / "120200.jpg", (3, 3, 3))
    archive.exports.mkdir(parents=True, exist_ok=True)
    (archive.exports / "2026-09-01.mp4").write_bytes(b"mp4")
    (archive.exports / "2026-09-01.mp4.stamp").write_text("stamp", encoding="utf-8")
    (archive.exports / "2026-09-01.gif").write_bytes(b"gif")
    (archive.exports / "2026-09-02.mp4").write_bytes(b"keep")
    result = archive.delete_day("2026-09-01")
    assert result["ok"] is True
    assert result["deleted"] == "2026-09-01"
    assert not drop.exists()
    assert not (archive.exports / "2026-09-01.mp4").exists()
    assert not (archive.exports / "2026-09-01.mp4.stamp").exists()
    assert not (archive.exports / "2026-09-01.gif").exists()
    assert keep.is_dir()
    assert (archive.exports / "2026-09-02.mp4").read_bytes() == b"keep"
    try:
        archive.delete_day("../2026-09-02")
        raise AssertionError("expected invalid day")
    except Exception as exc:
        assert "day must be YYYY-MM-DD" in str(exc)


def test_prune_drops_oldest_days_when_over_max_bytes(tmp_path: Path):
    archive = TimelapseArchive(
        tmp_path / "tl",
        timezone="UTC",
        retention_days=400,
        max_bytes=2500,
    )
    for day, color in (("2026-09-01", (1, 1, 1)), ("2026-09-02", (2, 2, 2)), ("2026-09-03", (3, 3, 3))):
        day_dir = archive.frames / day
        _jpeg(day_dir / "120000.jpg", color)
        _jpeg(day_dir / "120200.jpg", color)
        export = archive.exports / f"{day}.mp4"
        export.parent.mkdir(parents=True, exist_ok=True)
        export.write_bytes(b"x" * 800)
    removed = archive.prune()
    assert "2026-09-01" in removed
    assert not (archive.frames / "2026-09-01").exists()
    assert not (archive.exports / "2026-09-01.mp4").exists()
    assert (archive.frames / "2026-09-03").is_dir()
    info = archive.storage_info()
    assert info["used_bytes"] <= archive.max_bytes
    assert info["max_bytes"] == 2500


def test_timelapse_page_lists_a_day_and_does_not_upload(tmp_path: Path):
    cam = tmp_path / "cameras" / "shed"
    cam.mkdir(parents=True)
    (cam / "camera.yaml").write_text(
        "id: shed\ndisplay_name: Shed\ntimezone: Europe/Berlin\n"
        "source:\n  url: http://127.0.0.1/raw.jpg\n"
        "timelapse:\n  enabled: true\n  min_interval_seconds: 120\n  max_gb: 40\n",
        encoding="utf-8",
    )
    (cam / "variants").mkdir()
    archive = TimelapseArchive(
        tmp_path / "data" / "shed" / "timelapse",
        timezone="Europe/Berlin",
    )
    day = archive.frames / "2026-10-01"
    _jpeg(day / "080000.jpg", (8, 8, 8))
    _jpeg(day / "080200.jpg", (9, 9, 9))
    archive.exports.mkdir(parents=True, exist_ok=True)
    (archive.exports / "2026-10-01.gif").write_bytes(b"GIF89a" + b"\x00" * 20)
    (archive.exports / "2026-10-01.gif.stamp").write_text(
        f"2:080200.jpg:{(day / '080200.jpg').stat().st_size}", encoding="utf-8"
    )
    state = PipelineState(version="test", config={"cameras": ["shed"]}, repo_root=tmp_path)
    handler = make_handler(state, tmp_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/timelapse/ui") as resp:
            html = resp.read().decode()
        assert "<title>Webcam — Timelapse</title>" in html
        assert "Neither file is uploaded" in html or "not uploaded" in html.lower()
        assert "WhatsApp" not in html
        assert "Download GIF" in html
        assert "tl-storage" in html
        assert "tl-meter-fill" in html
        assert "tl-max-gb" in html
        assert "Save archive settings" in html
        assert "camera.yaml" in html and "timelapse" in html
        assert "Storage on this Pi" in html
        assert "History" in html
        assert "tl-day-list" in html
        assert "tl-day-row" in html
        assert "Newest first" in html
        assert "Delete day…" in html
        assert "lanUi.confirm" in html
        assert "/delete" in html
        assert "confirm: true" in html
        # Storage + export tip on archive card; day card has actions only.
        assert html.index("tl-storage") < html.index("id=\"tl-meta\"")
        assert html.index("Neither file is uploaded") < html.index("id=\"tl-meta\"")
        assert html.index("Neither file is uploaded") > html.index("tl-storage")
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/timelapse?camera=shed") as resp:
            payload = json.loads(resp.read().decode())
        assert payload["local_only"] is True
        assert payload["days"][0]["day"] == "2026-10-01"
        assert payload["days"][0]["frames"] == 2
        assert payload["storage"]["max_bytes"] == 40 * 1024**3
        assert payload["storage"]["used_bytes"] > 0
        assert "used_pct" in payload["storage"]
        assert payload["settings"]["enabled"] is True
        assert payload["settings"]["max_gb"] == 40
        assert payload["settings"]["min_interval_seconds"] == 120
        body = json.dumps(
            {
                "timelapse_enabled": True,
                "timelapse_max_gb": 12,
                "timelapse_retention_days": 90,
                "timelapse_min_interval_seconds": 180,
            }
        ).encode()
        req_set = urllib.request.Request(
            f"http://127.0.0.1:{port}/timelapse/settings?camera=shed",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req_set) as resp:
            saved = json.loads(resp.read().decode())
        assert saved["ok"] is True
        assert saved["settings"]["max_gb"] == 12
        assert saved["settings"]["retention_days"] == 90
        assert saved["settings"]["min_interval_seconds"] == 180
        disk = yaml.safe_load((cam / "camera.yaml").read_text(encoding="utf-8"))
        assert disk["timelapse"]["max_gb"] == 12
        assert disk["timelapse"]["retention_days"] == 90
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/timelapse/2026-10-01/gif?camera=shed&download=1"
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.headers.get("Content-Disposition", "").startswith("attachment;")
            assert "timelapse-2026-10-01.gif" in (resp.headers.get("Content-Disposition") or "")
            assert resp.headers.get_content_type() == "image/gif"
        # Delete without confirm is rejected; with confirm removes only that day.
        bad = urllib.request.Request(
            f"http://127.0.0.1:{port}/timelapse/2026-10-01/delete?camera=shed",
            data=b"{}",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(bad)
            raise AssertionError("expected 400 without confirm")
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
            assert b"confirm" in exc.read()
        other = archive.frames / "2026-10-02"
        _jpeg(other / "090000.jpg", (1, 1, 1))
        good = urllib.request.Request(
            f"http://127.0.0.1:{port}/timelapse/2026-10-01/delete?camera=shed",
            data=json.dumps({"confirm": True}).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(good) as resp:
            deleted = json.loads(resp.read().decode())
        assert deleted["ok"] is True
        assert deleted["deleted"] == "2026-10-01"
        assert not day.exists()
        assert not (archive.exports / "2026-10-01.gif").exists()
        assert other.is_dir()
        assert any(item["day"] == "2026-10-02" for item in deleted["days"])
    finally:
        server.shutdown()
