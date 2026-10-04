"""Wi-Fi join via NetworkManager. The password is not written to the repo.

``nmcli`` talks to NetworkManager over D-Bus. On the Pi, polkit rule
``50-webcam-network.rules`` lets the ``webcam`` service user scan and connect.

Setup AP (``Webcam-Setup``) is started by ``pi/scripts/webcam-setup-ap.sh`` only
when no home Wi-Fi profile exists. After a successful join from Setup, this
module tears the AP down so the radio can stay on the home network.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Any, Callable

Runner = Callable[[list[str]], tuple[int, str, str]]

_NMCLI_TIMEOUT = 25

# Keep in sync with pi/host/setup-ap.env
SETUP_AP_CONNECTION = "webcam-setup-ap"
SETUP_AP_SSID = "Webcam-Setup"
SETUP_AP_GATEWAY = "10.42.0.1"
_SETUP_AP_NAMES = frozenset({SETUP_AP_CONNECTION, "Hotspot"})


class WifiError(ValueError):
    pass


def wifi_status(*, runner: Runner | None = None) -> dict[str, Any]:
    run = runner or _run
    if shutil.which("nmcli") is None and runner is None:
        return {"available": False, "message": "NetworkManager (nmcli) is not installed"}
    code, out, err = run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"])
    if code != 0:
        return {"available": False, "message": _public_error(err or out)}
    wifi = _wifi_device(out)
    ipv4 = ""
    if wifi.get("device"):
        code2, out2, _err2 = run(["nmcli", "-g", "IP4.ADDRESS", "device", "show", str(wifi["device"])])
        if code2 == 0:
            ipv4 = (out2.splitlines() or [""])[0].split("/")[0].strip()
    ap_active = setup_ap_active(runner=run)
    ssid = wifi.get("ssid") or ""
    # When associated to our AP, surface the AP SSID (connection name ≠ SSID).
    if ap_active and (not ssid or ssid in _SETUP_AP_NAMES):
        ssid = SETUP_AP_SSID
    return {
        "available": True,
        "device": wifi.get("device") or "",
        "state": wifi.get("state") or "",
        "ssid": ssid,
        "ipv4": ipv4,
        "setup_ap": ap_active,
        "setup_ap_ssid": SETUP_AP_SSID if ap_active else "",
        "setup_ap_gateway": SETUP_AP_GATEWAY if ap_active else "",
        "setup_ap_url": f"http://{SETUP_AP_GATEWAY}:8090/setup/ui" if ap_active else "",
    }


def network_glance(*, runner: Runner | None = None) -> dict[str, Any]:
    """Ethernet + Wi‑Fi reachability (up/down, IPv4, gateway) for Pipeline home."""
    run = runner or _run
    if shutil.which("nmcli") is None and runner is None:
        return {"available": False, "interfaces": [], "message": "NetworkManager (nmcli) is not installed"}
    code, out, err = run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"])
    if code != 0:
        return {"available": False, "interfaces": [], "message": _public_error(err or out)}
    interfaces: list[dict[str, Any]] = []
    wifi_ssid = _active_wifi_ssid(run)
    for line in out.splitlines():
        parts = _split_terse(line)
        if len(parts) < 3:
            continue
        device, kind, state = parts[0], parts[1], parts[2]
        if kind not in ("ethernet", "wifi"):
            continue
        connection = parts[3] if len(parts) > 3 else ""
        ipv4 = ""
        gateway = ""
        code2, out2, _err2 = run(["nmcli", "-g", "IP4.ADDRESS", "device", "show", device])
        if code2 == 0:
            ipv4 = (out2.splitlines() or [""])[0].split("/")[0].strip()
        code3, out3, _err3 = run(["nmcli", "-g", "IP4.GATEWAY", "device", "show", device])
        if code3 == 0:
            gateway = (out3.splitlines() or [""])[0].strip()
        ssid = ""
        if kind == "wifi" and state == "connected":
            ssid = wifi_ssid or connection
        interfaces.append(
            {
                "device": device,
                "type": kind,
                "state": state,
                "connection": connection,
                "ssid": ssid,
                "ipv4": ipv4,
                "gateway": gateway,
                "up": state == "connected",
            }
        )
    # Prefer eth then wifi, then device name — stable operator scan order.
    rank = {"ethernet": 0, "wifi": 1}
    interfaces.sort(key=lambda row: (rank.get(str(row["type"]), 9), str(row["device"])))
    return {"available": True, "interfaces": interfaces, "message": None}


def wifi_scan(*, runner: Runner | None = None) -> dict[str, Any]:
    run = runner or _run
    code, out, err = run(
        ["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list", "--rescan", "yes"]
    )
    if code != 0:
        raise WifiError(_public_error(err or out))
    return {"networks": parse_wifi_list(out)}


def wifi_connect(ssid: str, password: str, *, runner: Runner | None = None) -> dict[str, Any]:
    run = runner or _run
    name = str(ssid or "").strip()
    secret = str(password or "")
    if not name or len(name) > 32 or any(c in name for c in "\r\n\x00"):
        raise WifiError("SSID must be 1–32 characters on one line")
    if any(c in secret for c in "\r\n\x00") or len(secret) > 64:
        raise WifiError("password must be at most 64 characters on one line")
    if name == SETUP_AP_SSID:
        raise WifiError("Pick your home Wi-Fi, not the Webcam-Setup access point")
    # Free the radio before joining home Wi-Fi.
    stop_setup_ap(runner=run)
    args = ["nmcli", "-w", "25", "device", "wifi", "connect", name]
    if secret:
        args.extend(["password", secret])
    code, out, err = run(args)
    if code != 0:
        raise WifiError(_public_error(err or out, secret=secret))
    # Ensure the setup hotspot does not autoconnect again.
    stop_setup_ap(runner=run)
    status = wifi_status(runner=run)
    return {
        "ok": True,
        "ssid": name,
        "ipv4": status.get("ipv4") or "",
        "message": "Connected. Leave Webcam-Setup on your phone; use the Pi’s new LAN address.",
        "setup_ap_stopped": True,
    }


def setup_ap_active(*, runner: Runner | None = None) -> bool:
    """True when the DIY setup hotspot connection is activated."""
    run = runner or _run
    code, out, _err = run(["nmcli", "-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active"])
    if code != 0:
        return False
    for line in out.splitlines():
        parts = _split_terse(line)
        if len(parts) < 2:
            continue
        name, kind = parts[0], parts[1]
        if name in _SETUP_AP_NAMES and "wireless" in kind:
            return True
    # Fallback: device associated to our connection name
    code2, out2, _err2 = run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"])
    if code2 != 0:
        return False
    for line in out2.splitlines():
        parts = _split_terse(line)
        if len(parts) < 4:
            continue
        if parts[1] == "wifi" and parts[2] == "connected" and parts[3] in _SETUP_AP_NAMES:
            return True
    return False


def stop_setup_ap(*, runner: Runner | None = None) -> dict[str, Any]:
    """Down + delete the setup AP profile. Safe when it is already gone."""
    run = runner or _run
    removed: list[str] = []
    for name in (SETUP_AP_CONNECTION, "Hotspot"):
        code, _out, _err = run(["nmcli", "connection", "show", name])
        if code != 0:
            continue
        if name == "Hotspot":
            code_s, ssid_out, _e = run(["nmcli", "-g", "802-11-wireless.ssid", "connection", "show", name])
            if code_s != 0 or (ssid_out.splitlines() or [""])[0].strip() != SETUP_AP_SSID:
                continue
        run(["nmcli", "connection", "down", name])
        code_del, _o2, _err2 = run(["nmcli", "connection", "delete", name])
        if code_del == 0:
            removed.append(name)
    return {"ok": True, "removed": removed}


def home_wifi_profile_names(*, runner: Runner | None = None) -> list[str]:
    """Saved Wi-Fi client profiles, excluding the setup hotspot."""
    run = runner or _run
    code, out, _err = run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"])
    if code != 0:
        return []
    names: list[str] = []
    for line in out.splitlines():
        parts = _split_terse(line)
        if len(parts) < 2:
            continue
        name, kind = parts[0], parts[1]
        if kind != "802-11-wireless":
            continue
        if name in _SETUP_AP_NAMES:
            continue
        names.append(name)
    return names


def should_start_setup_ap(
    *,
    runner: Runner | None = None,
    disabled_marker: bool = False,
    enabled: bool = True,
) -> tuple[bool, str]:
    """Pure decision helper (also used by tests). Matches webcam-setup-ap.sh rules."""
    if disabled_marker:
        return False, "disabled marker present"
    if not enabled:
        return False, "SETUP_AP_ENABLED is off"
    run = runner or _run
    code, out, err = run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"])
    if code != 0:
        return False, _public_error(err or out)
    if _ethernet_has_ipv4(out, run):
        return False, "ethernet has IPv4"
    if _wifi_home_associated(out):
        return False, "Wi-Fi already associated"
    if home_wifi_profile_names(runner=run):
        return False, "saved home Wi-Fi profile(s) exist"
    return True, "no home Wi-Fi configured"


def parse_wifi_list(text: str) -> list[dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = _split_terse(line)
        if len(parts) < 2:
            continue
        in_use = parts[0].strip() in ("*", "yes")
        ssid = parts[1].strip()
        if not ssid:
            continue
        try:
            signal = int(parts[2]) if len(parts) > 2 and parts[2].strip() else 0
        except ValueError:
            signal = 0
        security = parts[3].strip() if len(parts) > 3 else ""
        row = {
            "ssid": ssid,
            "signal": signal,
            "security": security,
            "in_use": in_use,
        }
        prev = best.get(ssid)
        if prev is None or signal > int(prev["signal"]) or in_use:
            if prev and prev.get("in_use"):
                row["in_use"] = True
            best[ssid] = row
    rows = list(best.values())
    rows.sort(key=lambda item: (-int(item["in_use"]), -int(item["signal"]), str(item["ssid"]).lower()))
    return rows


def _wifi_device(text: str) -> dict[str, str]:
    for line in text.splitlines():
        parts = _split_terse(line)
        if len(parts) < 3:
            continue
        device, kind, state = parts[0], parts[1], parts[2]
        if kind != "wifi":
            continue
        ssid = parts[3] if len(parts) > 3 else ""
        return {"device": device, "state": state, "ssid": ssid}
    return {}


def _ethernet_has_ipv4(device_status: str, run: Runner) -> bool:
    for line in device_status.splitlines():
        parts = _split_terse(line)
        if len(parts) < 3:
            continue
        device, kind, state = parts[0], parts[1], parts[2]
        if kind != "ethernet" or state != "connected":
            continue
        code, out, _err = run(["nmcli", "-g", "IP4.ADDRESS", "device", "show", device])
        if code == 0 and (out.splitlines() or [""])[0].strip():
            return True
    return False


def _wifi_home_associated(device_status: str) -> bool:
    for line in device_status.splitlines():
        parts = _split_terse(line)
        if len(parts) < 3:
            continue
        kind, state = parts[1], parts[2]
        conn = parts[3] if len(parts) > 3 else ""
        if kind != "wifi" or state != "connected":
            continue
        if conn in _SETUP_AP_NAMES:
            continue
        return True
    return False


def _active_wifi_ssid(run: Runner) -> str:
    """Return the in-use Wi‑Fi SSID (not the NM connection profile name)."""
    code, out, _err = run(["nmcli", "-t", "-f", "IN-USE,SSID", "device", "wifi", "list"])
    if code != 0:
        return ""
    for line in out.splitlines():
        parts = _split_terse(line)
        if len(parts) < 2:
            continue
        if parts[0].strip() in ("*", "yes"):
            return parts[1].strip()
    return ""


def _split_terse(line: str) -> list[str]:
    out: list[str] = []
    buf: list[str] = []
    escaped = False
    for ch in line:
        if escaped:
            buf.append(ch)
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == ":":
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    out.append("".join(buf))
    return out


def _public_error(text: str, *, secret: str = "") -> str:
    msg = " ".join((text or "").split())
    if secret and secret in msg:
        msg = msg.replace(secret, "••••")
    if not msg:
        return "NetworkManager refused the request"
    if "Not authorized" in msg or "Insufficient privileges" in msg:
        return (
            "NetworkManager refused the request. Install "
            "pi/pipeline/systemd/50-webcam-network.rules and try again."
        )
    return msg[:300]


def _run(args: list[str]) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=_NMCLI_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)
    return proc.returncode, proc.stdout or "", proc.stderr or ""
