"""Setup AP decision helpers — must never start when a home Wi-Fi profile exists."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(ROOT))

from app.wifi_nm import (  # noqa: E402
    SETUP_AP_CONNECTION,
    SETUP_AP_SSID,
    home_wifi_profile_names,
    should_start_setup_ap,
    stop_setup_ap,
    wifi_connect,
    wifi_status,
)


def _runner(responses: dict[tuple[str, ...], tuple[int, str, str]]):
    def run(args: list[str]) -> tuple[int, str, str]:
        key = tuple(args)
        for prefix, value in responses.items():
            if key[: len(prefix)] == prefix:
                return value
        # Default success empty
        return 0, "", ""

    return run


def test_should_not_start_when_home_profile_exists():
    run = _runner(
        {
            ("nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"): (
                0,
                "wlan0:wifi:disconnected:\neth0:ethernet:unavailable:\n",
                "",
            ),
            ("nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"): (
                0,
                f"{SETUP_AP_CONNECTION}:802-11-wireless\nHomeLAN:802-11-wireless\n",
                "",
            ),
        }
    )
    ok, reason = should_start_setup_ap(runner=run, enabled=True, disabled_marker=False)
    assert ok is False
    assert "profile" in reason


def test_should_not_start_when_ethernet_up():
    def run(args: list[str]) -> tuple[int, str, str]:
        if args[:3] == ["nmcli", "-t", "-f"] and "DEVICE,TYPE,STATE,CONNECTION" in args[3]:
            return 0, "eth0:ethernet:connected:Wired\nwlan0:wifi:disconnected:\n", ""
        if args[:3] == ["nmcli", "-g", "IP4.ADDRESS"]:
            return 0, "192.168.1.10/24\n", ""
        if args[:3] == ["nmcli", "-t", "-f"] and args[3] == "NAME,TYPE":
            return 0, "", ""
        return 0, "", ""

    ok, reason = should_start_setup_ap(runner=run)
    assert ok is False
    assert "ethernet" in reason


def test_should_not_start_when_wifi_associated():
    run = _runner(
        {
            ("nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"): (
                0,
                "wlan0:wifi:connected:HomeLAN\n",
                "",
            ),
            ("nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"): (
                0,
                "HomeLAN:802-11-wireless\n",
                "",
            ),
        }
    )
    ok, reason = should_start_setup_ap(runner=run)
    assert ok is False
    assert "associated" in reason or "profile" in reason


def test_should_start_when_bare():
    run = _runner(
        {
            ("nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"): (
                0,
                "wlan0:wifi:disconnected:\n",
                "",
            ),
            ("nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"): (
                0,
                f"{SETUP_AP_CONNECTION}:802-11-wireless\n",
                "",
            ),
        }
    )
    ok, reason = should_start_setup_ap(runner=run)
    assert ok is True
    assert "no home" in reason


def test_disabled_marker_and_enabled_flag():
    ok, _ = should_start_setup_ap(disabled_marker=True)
    assert ok is False
    ok, _ = should_start_setup_ap(enabled=False)
    assert ok is False


def test_home_wifi_profile_names_skips_setup_ap():
    run = _runner(
        {
            ("nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"): (
                0,
                f"{SETUP_AP_CONNECTION}:802-11-wireless\nHotspot:802-11-wireless\nCafe:802-11-wireless\n",
                "",
            ),
        }
    )
    assert home_wifi_profile_names(runner=run) == ["Cafe"]


def test_wifi_connect_stops_setup_ap_first(tmp_path):
    seen: list[list[str]] = []
    last = tmp_path / "last-lan.json"

    def run(args: list[str]) -> tuple[int, str, str]:
        seen.append(args)
        if args[:2] == ["nmcli", "connection"] and args[2] == "show" and len(args) >= 4:
            if args[3] == SETUP_AP_CONNECTION:
                return 0, "yes\n", ""
            return 1, "", "not found"
        if "connect" in args:
            return 0, "connected\n", ""
        if args[:3] == ["nmcli", "-t", "-f"] and "DEVICE,TYPE,STATE,CONNECTION" in args[3]:
            return 0, "wlan0:wifi:connected:HomeNet\n", ""
        if args[:3] == ["nmcli", "-g", "IP4.ADDRESS"]:
            return 0, "10.0.0.5/24\n", ""
        if args[:3] == ["nmcli", "-g", "IP4.GATEWAY"]:
            return 0, "10.0.0.1\n", ""
        if args[:3] == ["nmcli", "-t", "-f"] and "NAME,TYPE,DEVICE" in args[3]:
            return 0, "", ""
        if args[:3] == ["nmcli", "-t", "-f"] and "IN-USE,SSID" in args[3]:
            return 0, "*:HomeNet\n", ""
        return 0, "", ""

    result = wifi_connect("HomeNet", "secret", runner=run, last_lan_path=last)
    assert result["ok"] is True
    assert result["setup_ap_stopped"] is True
    assert result["ipv4"] == "10.0.0.5"
    assert result["mdns"].endswith(".local")
    assert "10.0.0.5" in (result.get("message") or "")
    assert last.read_text(encoding="utf-8").find("10.0.0.5") >= 0
    assert any(a[:3] == ["nmcli", "connection", "down"] for a in seen)
    assert any(a[:3] == ["nmcli", "connection", "delete"] for a in seen)
    assert any("connect" in a and "HomeNet" in a for a in seen)


def test_wifi_connect_rejects_setup_ssid():
    try:
        wifi_connect(SETUP_AP_SSID, "x", runner=lambda _a: (0, "", ""))
    except ValueError as exc:
        assert "Webcam-Setup" in str(exc) or "home" in str(exc).lower()
    else:
        raise AssertionError("expected WifiError")


def test_wifi_status_flags_setup_ap(tmp_path):
    def run(args: list[str]) -> tuple[int, str, str]:
        if args[:3] == ["nmcli", "-t", "-f"] and "DEVICE,TYPE,STATE,CONNECTION" in args[3]:
            return 0, f"wlan0:wifi:connected:{SETUP_AP_CONNECTION}\n", ""
        if args[:3] == ["nmcli", "-g", "IP4.ADDRESS"]:
            return 0, "10.42.0.1/24\n", ""
        if args[:3] == ["nmcli", "-g", "IP4.GATEWAY"]:
            return 0, "\n", ""
        if args[:3] == ["nmcli", "-t", "-f"] and "NAME,TYPE,DEVICE" in args[3]:
            return 0, f"{SETUP_AP_CONNECTION}:802-11-wireless:wlan0\n", ""
        if args[:3] == ["nmcli", "-t", "-f"] and "IN-USE,SSID" in args[3]:
            return 0, "*:Webcam-Setup\n", ""
        return 0, "", ""

    status = wifi_status(runner=run, last_lan_path=tmp_path / "last-lan.json")
    assert status["setup_ap"] is True
    assert status["setup_ap_ssid"] == SETUP_AP_SSID
    assert "setup/ui" in status["setup_ap_url"]
    assert status["mdns"].endswith(".local")
    assert status["last_lan_ipv4"] == ""


def test_stop_setup_ap_idempotent():
    def run(args: list[str]) -> tuple[int, str, str]:
        if args[:3] == ["nmcli", "connection", "show"]:
            return 1, "", "no"
        return 0, "", ""

    assert stop_setup_ap(runner=run)["removed"] == []
