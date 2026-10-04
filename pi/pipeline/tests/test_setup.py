"""Setup page: camera.yaml project fields and Wi-Fi list parsing."""

from __future__ import annotations

import json
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(ROOT))

import os
import shutil

from app.publish_settings import probe_publish_connection, save_publish  # noqa: E402
from app.serve_private import make_handler  # noqa: E402
from app.site_settings import create_camera, read_site, save_site  # noqa: E402
from app.state import PipelineState  # noqa: E402
from app.wifi_nm import parse_wifi_list, wifi_connect  # noqa: E402


def _write_camera(root: Path) -> None:
    cam = root / "cameras" / "example"
    cam.mkdir(parents=True)
    (cam / "camera.yaml").write_text(
        "id: example\n"
        "display_name: Example Webcam\n"
        "source:\n  url: http://127.0.0.1:8080/raw.jpg\n"
        "publish:\n  enabled: true\n"
        "  public_live_key: live/example-live-webcam.jpg\n"
        "timezone: Europe/Berlin\n"
        "weather:\n"
        "  url: https://example.com/api/weather\n"
        "  ttl_seconds: 300\n"
        "  timeout_seconds: 4\n"
        "location:\n"
        "  latitude: 48.7855\n"
        "  longitude: 8.749\n",
        encoding="utf-8",
    )


def test_save_site_keeps_publish_and_updates_weather(tmp_path: Path):
    _write_camera(tmp_path)
    before = read_site(tmp_path, "example")
    assert before["weather_url"] == "https://example.com/api/weather"
    assert before["display_name"] == "Example Webcam"
    assert before["status_language"] == "english"
    assert before["poll_interval_seconds"] == 60
    saved = save_site(
        tmp_path,
        "example",
        {
            "display_name": "Example Webcam",
            "timezone": "Europe/Berlin",
            "latitude": 48.7855,
            "longitude": 8.749,
            "weather_url": "https://example.com/api/weather",
            "weather_ttl_seconds": 300,
            "weather_timeout_seconds": 4,
            "poll_interval_seconds": 45,
            "status_language": "german",
        },
    )
    assert saved["weather_url"] == "https://example.com/api/weather"
    assert saved["poll_interval_seconds"] == 45
    assert saved["status_language"] == "german"
    raw = yaml.safe_load((tmp_path / "cameras/example/camera.yaml").read_text())
    assert raw["publish"]["public_live_key"] == "live/example-live-webcam.jpg"
    assert raw["poll_interval_seconds"] == 45
    assert raw["status_text"]["night_title"] == "Nachts offline"
    assert "password" not in (tmp_path / "cameras/example/camera.yaml").read_text()
    english = save_site(tmp_path, "example", {"status_language": "english"})
    assert english["status_language"] == "english"
    raw2 = yaml.safe_load((tmp_path / "cameras/example/camera.yaml").read_text())
    assert "status_text" not in raw2


def test_save_site_rejects_bad_weather_url(tmp_path: Path):
    _write_camera(tmp_path)
    try:
        save_site(tmp_path, "example", {"weather_url": "ftp://nope"})
    except ValueError as exc:
        assert "http" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_wifi_list_parser_and_connect_does_not_echo_secret():
    rows = parse_wifi_list("*:Home Net:80:WPA2\n :Cafe:40:WPA2\n :Home Net:20:WPA2\n")
    assert rows[0]["ssid"] == "Home Net"
    assert rows[0]["in_use"] is True
    assert rows[0]["signal"] == 80
    seen: list[list[str]] = []

    def runner(args: list[str]) -> tuple[int, str, str]:
        seen.append(args)
        if "connect" in args:
            return 1, "", "password secret-pass failed"
        return 0, "wlan0:wifi:connected:Home Net\n", ""

    try:
        wifi_connect("Home Net", "secret-pass", runner=runner)
    except ValueError as exc:
        assert "secret-pass" not in str(exc)
        assert "••••" in str(exc)
    else:
        raise AssertionError("expected WifiError")
    assert any("secret-pass" in part for part in seen[-1])


def test_setup_http_roundtrip(tmp_path: Path):
    _write_camera(tmp_path)
    state = PipelineState(
        version="test",
        config={"cameras": ["example"], "publish": {"enabled": False}},
        repo_root=tmp_path,
    )
    handler = make_handler(state, tmp_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/setup/ui") as resp:
            html = resp.read().decode()
        assert "<title>Webcam — Setup</title>" in html
        assert "Example Webcam" not in html
        assert "Public slide language" in html
        assert "Refresh interval" in html
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/setup?camera=example"
        ) as resp:
            body = json.loads(resp.read().decode())
        assert body["weather_url"] == "https://example.com/api/weather"
        assert body["status_language"] == "english"
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/setup?camera=example",
            data=json.dumps(
                {
                    "weather_url": "https://example.com/api/weather",
                    "weather_ttl_seconds": 120,
                }
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            saved = json.loads(resp.read().decode())
        assert saved["weather_url"] == "https://example.com/api/weather"
        text = (tmp_path / "cameras/example/camera.yaml").read_text()
        assert "https://example.com/api/weather" in text
        assert "public_live_key" in text
    finally:
        server.shutdown()


def test_create_camera_keeps_existing_and_rewrites_example_tokens(tmp_path: Path):
    src = REPO / "examples" / "cameras" / "example"
    shutil.copytree(src, tmp_path / "examples" / "cameras" / "example")
    pipe = tmp_path / "pi" / "pipeline" / "config" / "pipeline.yaml"
    pipe.parent.mkdir(parents=True)
    pipe.write_text("cameras:\n  - example\n", encoding="utf-8")
    created = create_camera(tmp_path, "shed", "Shed webcam", config_paths=[pipe])
    assert created["camera_id"] == "shed"
    assert created["display_name"] == "Shed webcam"
    assert created["public_live_key"] == "live/shed-live-webcam.jpg"
    assert not (tmp_path / "cameras" / "example").exists()
    listed = yaml.safe_load(pipe.read_text())["cameras"]
    assert listed == ["example", "shed"]
    text = (tmp_path / "cameras" / "shed" / "camera.yaml").read_text()
    assert "id: shed" in text
    assert "data/shed" in text


def test_publish_secret_stays_in_env_file(tmp_path: Path):
    env = tmp_path / "env"
    pipe = tmp_path / "pipeline.yaml"
    pipe.write_text(
        "cameras:\n  - example\npublish:\n  enabled: false\n  r2:\n    bucket: old\n",
        encoding="utf-8",
    )
    cfg = yaml.safe_load(pipe.read_text())
    keys = (
        "R2_BUCKET",
        "S3_BUCKET",
        "AWS_ENDPOINT_URL",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "CLOUDFLARE_ACCOUNT_ID",
    )
    previous = {key: os.environ.get(key) for key in keys}
    try:
        saved = save_publish(
            cfg,
            env,
            {
                "provider": "r2",
                "account_id": "abc123",
                "bucket": "example-webcam",
                "endpoint_url": "",
                "access_key_id": "key-id",
                "secret_access_key": "super-secret",
            },
            yaml_paths=[pipe],
        )
        assert saved["secret_set"] is True
        assert saved["provider"] == "r2"
        assert saved["endpoint_url"] == "https://abc123.r2.cloudflarestorage.com"
        assert "super-secret" not in str(saved)
        assert "super-secret" not in pipe.read_text()
        assert "super-secret" in env.read_text()
        assert "S3_BUCKET=example-webcam" in env.read_text()
        raw = yaml.safe_load(pipe.read_text())
        assert raw["publish"]["backend"] == "s3"
        assert raw["publish"]["s3"]["bucket"] == "example-webcam"
        save_publish(cfg, env, {"secret_access_key": ""}, yaml_paths=[pipe])
        assert "super-secret" in env.read_text()
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_publish_provider_off_and_local(tmp_path: Path):
    env = tmp_path / "env"
    pipe = tmp_path / "pipeline.yaml"
    pipe.write_text("cameras:\n  - example\npublish:\n  enabled: true\n  backend: s3\n", encoding="utf-8")
    cfg = yaml.safe_load(pipe.read_text())
    saved = save_publish(cfg, env, {"provider": "off"}, yaml_paths=[pipe])
    assert saved["provider"] == "off"
    assert saved["enabled"] is False
    local = save_publish(cfg, env, {"provider": "local"}, yaml_paths=[pipe])
    assert local["provider"] == "local"
    assert local["enabled"] is True
    assert yaml.safe_load(pipe.read_text())["publish"]["backend"] == "local"
    probe = probe_publish_connection(cfg, env, {"provider": "local"})
    assert probe["ok"] is True
    assert "outbox" in probe["detail"]


def test_setup_ui_mentions_s3_providers():
    from app.setup_page import setup_ui

    html = setup_ui()
    assert "Cloudflare R2" in html
    assert "Custom S3-compatible" in html
    assert "Test connection" in html
    assert "/setup/publish/test" in html
    assert "hotlink" in html.lower() or "Worker landing page is optional" in html
    assert "Find this Pi" in html
    assert "find-pi-kv" in html
    assert "*.local" in html or "mDNS" in html


def test_wifi_status_exposes_hostname_and_last_lan(tmp_path: Path):
    from app.wifi_nm import remember_last_lan_ipv4, wifi_status

    last = tmp_path / "last-lan.json"
    remember_last_lan_ipv4("192.168.1.50", path=last)

    def run(args: list[str]) -> tuple[int, str, str]:
        if args[:3] == ["nmcli", "-t", "-f"] and "DEVICE,TYPE,STATE,CONNECTION" in args[3]:
            return 0, "wlan0:wifi:connected:webcam-setup-ap\n", ""
        if args[:3] == ["nmcli", "-g", "IP4.ADDRESS"]:
            return 0, "10.42.0.1/24\n", ""
        if args[:3] == ["nmcli", "-t", "-f"] and "NAME,TYPE,DEVICE" in args[3]:
            return 0, "webcam-setup-ap:802-11-wireless:wlan0\n", ""
        if args[:3] == ["nmcli", "-t", "-f"] and "IN-USE,SSID" in args[3]:
            return 0, "*:Webcam-Setup\n", ""
        return 0, "", ""

    status = wifi_status(runner=run, last_lan_path=last)
    assert status["setup_ap"] is True
    assert status["hostname"]
    assert status["mdns"].endswith(".local")
    assert status["last_lan_ipv4"] == "192.168.1.50"
    assert "mdns_camera" in status["lan_urls"]
