"""Tests for LAN System card power / service restart helpers + host status."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(ROOT))

from app.system_ops import (  # noqa: E402
    SystemOpsError,
    collect_system_status,
    collect_unit_logs,
    collect_unit_states,
    list_restart_units,
    require_confirm,
    schedule_power,
    schedule_restart_services,
    summarize_publish,
)
from app.wifi_nm import network_glance  # noqa: E402


def test_require_confirm_rejects_missing():
    with pytest.raises(SystemOpsError, match="confirm"):
        require_confirm({})
    with pytest.raises(SystemOpsError, match="confirm"):
        require_confirm({"confirm": False})
    require_confirm({"confirm": True})
    require_confirm({"confirm": "yes"})


def test_schedule_power_calls_systemctl():
    calls: list[list[str]] = []

    def runner(args: list[str]) -> tuple[int, str, str]:
        calls.append(list(args))
        return 0, "", ""

    out = schedule_power("reboot", runner=runner, delay=0.05)
    assert out["ok"] is True
    assert out["action"] == "reboot"
    deadline = time.time() + 2
    while time.time() < deadline and not calls:
        time.sleep(0.02)
    assert calls == [["systemctl", "reboot"]]


def test_schedule_restart_services_allowlist_only():
    calls: list[list[str]] = []

    def runner(args: list[str]) -> tuple[int, str, str]:
        calls.append(list(args))
        if args[:2] == ["systemctl", "cat"]:
            unit = args[2]
            if unit in ("webcam-camera.service", "webcam-pipeline.service"):
                return 0, "# unit", ""
            return 1, "", "not found"
        return 0, "", ""

    units = list_restart_units(runner=runner)
    assert units == ["webcam-camera.service", "webcam-pipeline.service"]
    assert "nginx.service" not in units

    out = schedule_restart_services(runner=runner, delay=0.05)
    assert out["action"] == "restart-services"
    assert out["units"] == units
    deadline = time.time() + 2
    while time.time() < deadline and not any(c[:2] == ["systemctl", "restart"] for c in calls):
        time.sleep(0.02)
    restart = [c for c in calls if c[:2] == ["systemctl", "restart"]]
    assert restart == [
        ["systemctl", "restart", "webcam-camera.service", "webcam-pipeline.service"]
    ]


def test_schedule_power_rejects_unknown_action():
    with pytest.raises(SystemOpsError):
        schedule_power("halt", runner=lambda _a: (0, "", ""))


def test_collect_unit_states_fixed_allowlist():
    def runner(args: list[str]) -> tuple[int, str, str]:
        if args[:2] == ["systemctl", "cat"]:
            unit = args[2]
            if unit == "nginx.service":
                return 1, "", "missing"
            return 0, "# ok", ""
        if args[:2] == ["systemctl", "is-active"]:
            return 0, "active\n", ""
        if args[:2] == ["systemctl", "show"]:
            return 0, "running\n", ""
        return 1, "", "unexpected"

    units = collect_unit_states(runner=runner)
    names = [u["name"] for u in units]
    assert names == ["webcam-camera", "webcam-pipeline", "nginx"]
    assert units[0]["ok"] is True
    assert units[2]["installed"] is False
    assert units[2]["ok"] is False


def test_collect_unit_logs_fixed_units_only():
    def runner(args: list[str]) -> tuple[int, str, str]:
        assert args[0] == "journalctl"
        assert "-u" in args
        units = [args[i + 1] for i, a in enumerate(args) if a == "-u"]
        assert units == ["webcam-camera.service", "webcam-pipeline.service"]
        assert "nginx.service" not in units
        return 0, "2026-10-01T12:00:00+00:00 webcam-pipeline[1]: hello\n", ""

    out = collect_unit_logs(lines=40, runner=runner)
    assert out["ok"] is True
    assert "hello" in out["text"]
    assert out["units"] == ["webcam-camera", "webcam-pipeline"]


def test_summarize_publish_age():
    now = 1_700_000_100.0
    info = summarize_publish(
        {"enabled": True, "backend": "r2", "last_success_at": "2023-11-14T22:13:20Z"},
        now=now,
    )
    assert info["enabled"] is True
    assert info["last_success_age_seconds"] == pytest.approx(100.0)


def test_collect_system_status_shape(tmp_path: Path):
    def runner(args: list[str]) -> tuple[int, str, str]:
        if args[:2] == ["systemctl", "cat"]:
            return 0, "#", ""
        if args[:2] == ["systemctl", "is-active"]:
            return 0, "active\n", ""
        if args[:2] == ["systemctl", "show"]:
            return 0, "running\n", ""
        if args[:3] == ["timedatectl", "show", "-p"] and args[3] == "NTPSynchronized":
            return 0, "yes\n", ""
        if args[:3] == ["timedatectl", "show", "-p"] and args[3] == "Timezone":
            return 0, "Europe/Berlin\n", ""
        return 1, "", "no"

    status = collect_system_status(
        data_path=tmp_path,
        publish={"enabled": True, "last_success_at": None},
        network=[{"device": "wlan0", "type": "wifi", "up": True, "ipv4": "10.0.0.2"}],
        runner=runner,
        now=1_700_000_000.0,
    )
    assert status["ok"] is True
    assert status["disks"]
    assert status["disks"][0]["label"] == "root"
    assert status["clock"]["ntp_synchronized"] is True
    assert status["clock"]["timezone"] == "Europe/Berlin"
    assert status["network"][0]["ipv4"] == "10.0.0.2"
    assert len(status["units"]) == 3


def test_network_glance_eth_and_wifi():
    def runner(args: list[str]) -> tuple[int, str, str]:
        if args[:3] == ["nmcli", "-t", "-f"] and "DEVICE,TYPE,STATE,CONNECTION" in args[3]:
            return (
                0,
                "eth0:ethernet:connected:Wired\n"
                "wlan0:wifi:connected:HomeNet\n"
                "lo:loopback:unmanaged:\n",
                "",
            )
        if args[:3] == ["nmcli", "-t", "-f"] and args[3] == "IN-USE,SSID":
            return 0, "*:HomeNet\n :Other\n", ""
        if args[:3] == ["nmcli", "-g", "IP4.ADDRESS"]:
            dev = args[-1]
            if dev == "eth0":
                return 0, "192.168.178.151/24\n", ""
            return 0, "192.168.178.150/24\n", ""
        if args[:3] == ["nmcli", "-g", "IP4.GATEWAY"]:
            return 0, "192.168.178.1\n", ""
        return 1, "", "unexpected"

    out = network_glance(runner=runner)
    assert out["available"] is True
    assert [i["device"] for i in out["interfaces"]] == ["eth0", "wlan0"]
    assert out["interfaces"][0]["ipv4"] == "192.168.178.151"
    assert out["interfaces"][1]["ssid"] == "HomeNet"
    assert out["interfaces"][1]["gateway"] == "192.168.178.1"
