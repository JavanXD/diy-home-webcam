"""Opt-in appliance updates from the public DIY GitHub repo.

v1: overnight *check* (notify in LAN UI) + manual Apply. No silent auto-deploy.
OS apt upgrades are separate (see docs/diy/SECURITY.md).

Default remote is the public ``JavanXD/diy-home-webcam`` tree. Example ops
should leave overnight check off and keep Mac ``sync-to-pi.sh`` — do not put a
private remote URL in the public image.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

Runner = Callable[[list[str]], tuple[int, str, str]]

_DEFAULT_STATE_DIR = Path("/var/lib/webcam-pipeline")
_PREF_NAME = "updates.json"
_STATE_NAME = "updates-state.json"
_INSTALLED_REV_NAME = "installed-rev"

DEFAULT_REMOTE = "https://github.com/JavanXD/diy-home-webcam.git"
DEFAULT_REF = "main"
_GITHUB_API = "https://api.github.com/repos/JavanXD/diy-home-webcam/commits/{ref}"
_TARBALL_URL = "https://github.com/JavanXD/diy-home-webcam/archive/refs/heads/{ref}.tar.gz"

_INSTALL_ROOT_DEFAULT = Path("/opt/home-webcam-pipeline")

# Code trees only — never cameras/, data/, /etc secrets, or private overlays.
_SYNC_REL_PATHS = (
    "pi/camera/app",
    "pi/camera/scripts",
    "pi/camera/systemd",
    "pi/pipeline/app",
    "pi/pipeline/scripts",
    "pi/pipeline/systemd",
    "pi/pipeline/requirements.txt",
    "pi/scripts",
    "pi/host/systemd",
    "pi/provision.sh",
    "shared",
)

_HTTP_TIMEOUT = 45
_GIT_TIMEOUT = 60


class UpdatesError(ValueError):
    pass


def state_dir() -> Path:
    raw = os.environ.get("WEBCAM_UPDATES_DIR", "").strip()
    return Path(raw) if raw else _DEFAULT_STATE_DIR


def install_root() -> Path:
    raw = os.environ.get("INSTALL_ROOT", "").strip()
    return Path(raw) if raw else _INSTALL_ROOT_DEFAULT


def pref_path(base: Path | None = None) -> Path:
    return (base or state_dir()) / _PREF_NAME


def state_path(base: Path | None = None) -> Path:
    return (base or state_dir()) / _STATE_NAME


def installed_rev_path(base: Path | None = None) -> Path:
    return (base or state_dir()) / _INSTALLED_REV_NAME


def default_prefs() -> dict[str, Any]:
    return {
        "check_overnight": False,
        "remote": DEFAULT_REMOTE,
        "ref": DEFAULT_REF,
    }


def read_prefs(base: Path | None = None) -> dict[str, Any]:
    path = pref_path(base)
    out = default_prefs()
    if not path.is_file():
        return out
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return out
    if not isinstance(raw, dict):
        return out
    if "check_overnight" in raw:
        out["check_overnight"] = bool(raw["check_overnight"])
    remote = str(raw.get("remote") or "").strip()
    if remote.startswith("https://github.com/") and remote.endswith(".git"):
        # Only allow public GitHub HTTPS remotes (no private tokens in URL).
        out["remote"] = remote
    ref = str(raw.get("ref") or "").strip()
    if ref and all(c.isalnum() or c in "._/-" for c in ref) and ".." not in ref:
        out["ref"] = ref
    return out


def write_prefs(prefs: dict[str, Any], base: Path | None = None) -> dict[str, Any]:
    merged = default_prefs()
    merged["check_overnight"] = bool(prefs.get("check_overnight", False))
    remote = str(prefs.get("remote") or merged["remote"]).strip()
    if remote.startswith("https://github.com/") and remote.endswith(".git"):
        merged["remote"] = remote
    ref = str(prefs.get("ref") or merged["ref"]).strip()
    if ref and all(c.isalnum() or c in "._/-" for c in ref) and ".." not in ref:
        merged["ref"] = ref
    path = pref_path(base)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    try:
        path.chmod(0o644)
    except OSError:
        pass
    return merged


def read_state(base: Path | None = None) -> dict[str, Any]:
    path = state_path(base)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def write_state(state: dict[str, Any], base: Path | None = None) -> None:
    path = state_path(base)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    try:
        path.chmod(0o644)
    except OSError:
        pass


def read_installed_rev(base: Path | None = None) -> str:
    path = installed_rev_path(base)
    if path.is_file():
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""
    return ""


def write_installed_rev(rev: str, base: Path | None = None) -> None:
    path = installed_rev_path(base)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text((rev or "").strip() + "\n", encoding="utf-8")
    try:
        path.chmod(0o644)
    except OSError:
        pass


def local_version(repo: Path | None = None) -> str:
    root = repo or install_root()
    version_py = root / "shared" / "version.py"
    if not version_py.is_file():
        # Running from a checkout where shared/ is on PYTHONPATH
        try:
            from shared.version import __version__  # type: ignore

            return str(__version__)
        except Exception:  # noqa: BLE001
            return ""
    try:
        text = version_py.read_text(encoding="utf-8")
    except OSError:
        return ""
    for line in text.splitlines():
        if line.strip().startswith("__version__"):
            part = line.split("=", 1)[-1].strip().strip("'\"")
            return part
    return ""


def status(*, base: Path | None = None, repo: Path | None = None) -> dict[str, Any]:
    prefs = read_prefs(base)
    st = read_state(base)
    local_rev = read_installed_rev(base)
    remote_rev = str(st.get("remote_rev") or "")
    update_available = bool(st.get("update_available"))
    if local_rev and remote_rev:
        update_available = local_rev != remote_rev
    return {
        "ok": True,
        "check_overnight": bool(prefs["check_overnight"]),
        "remote": prefs["remote"],
        "ref": prefs["ref"],
        "local_rev": local_rev,
        "local_version": local_version(repo),
        "remote_rev": remote_rev,
        "update_available": update_available,
        "last_check_at": st.get("last_check_at"),
        "last_check_ok": st.get("last_check_ok"),
        "last_error": st.get("last_error"),
        "last_apply_at": st.get("last_apply_at"),
        "message": st.get("message") or _status_message(prefs, st, local_rev, update_available),
        "channel": "diy-home-webcam",
        "note": (
            "Opt-in overnight check against the public DIY repo. "
            "Does not change OS packages (apt). "
            "Ops Pis that sync from a private checkout should leave this off."
        ),
    }


def _status_message(
    prefs: dict[str, Any],
    st: dict[str, Any],
    local_rev: str,
    update_available: bool,
) -> str:
    if st.get("last_error"):
        return str(st["last_error"])
    if not st.get("last_check_at"):
        if prefs.get("check_overnight"):
            return "Overnight check enabled — waiting for the first nightly run (or Check now)."
        return "Overnight check is off (default). Turn it on to look for DIY code updates each night."
    if update_available:
        short = (st.get("remote_rev") or "")[:12]
        return f"Update available{(' · ' + short) if short else ''}. Review then Apply when ready."
    if local_rev:
        return "Appliance code matches the last checked remote revision."
    return "Checked remote; local revision not stamped yet — Apply once to pin a revision."


def set_check_overnight(enabled: bool, *, base: Path | None = None) -> dict[str, Any]:
    prefs = read_prefs(base)
    prefs["check_overnight"] = bool(enabled)
    write_prefs(prefs, base)
    return status(base=base)


def fetch_remote_rev(
    *,
    remote: str | None = None,
    ref: str | None = None,
    opener: Callable[[str], dict[str, Any]] | None = None,
) -> str:
    """Return remote commit SHA for ref (GitHub API; no credentials for public repos)."""
    prefs_ref = ref or DEFAULT_REF
    # Prefer API when remote is the default public repo (no git required).
    rem = (remote or DEFAULT_REMOTE).rstrip("/")
    if rem in (DEFAULT_REMOTE, DEFAULT_REMOTE.removesuffix(".git")):
        url = _GITHUB_API.format(ref=prefs_ref)
        data = (opener or _http_json)(url)
        sha = str(data.get("sha") or "").strip()
        if len(sha) >= 7 and all(c in "0123456789abcdef" for c in sha.lower()):
            return sha
        raise UpdatesError("GitHub API response missing commit sha")
    # Fallback: git ls-remote for a custom https GitHub remote.
    return _ls_remote(rem if rem.endswith(".git") else rem + ".git", prefs_ref)


def run_check(
    *,
    base: Path | None = None,
    repo: Path | None = None,
    force: bool = False,
    opener: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compare installed rev to remote. Honors opt-in unless force=True (Check now)."""
    prefs = read_prefs(base)
    if not force and not prefs.get("check_overnight"):
        # Timer no-op: leave prior notify state intact.
        return status(base=base, repo=repo)

    now = _utc_now()
    st = read_state(base)
    try:
        remote_rev = fetch_remote_rev(
            remote=str(prefs["remote"]),
            ref=str(prefs["ref"]),
            opener=opener,
        )
    except Exception as exc:  # noqa: BLE001
        st.update(
            {
                "last_check_at": now,
                "last_check_ok": False,
                "last_error": _public_err(exc),
                "message": _public_err(exc),
            }
        )
        write_state(st, base)
        out = status(base=base, repo=repo)
        out["ok"] = False
        return out

    local_rev = read_installed_rev(base)
    available = bool(remote_rev) and (not local_rev or local_rev != remote_rev)
    st.update(
        {
            "last_check_at": now,
            "last_check_ok": True,
            "last_error": None,
            "remote_rev": remote_rev,
            "update_available": available,
            "message": (
                f"Update available · {remote_rev[:12]}"
                if available
                else f"Up to date · {remote_rev[:12]}"
            ),
        }
    )
    write_state(st, base)
    return status(base=base, repo=repo)


def schedule_apply(
    *,
    runner: Runner | None = None,
    delay: float = 1.0,
) -> dict[str, Any]:
    """Queue oneshot apply unit (polkit-limited start)."""

    def _do() -> None:
        run = runner or _run
        code, _out, err = run(["systemctl", "start", "webcam-update-apply.service"])
        if code != 0:
            # Best-effort record; UI can re-check status.
            try:
                st = read_state()
                st["last_error"] = _public_err(err or "systemctl start failed")
                st["message"] = st["last_error"]
                write_state(st)
            except OSError:
                pass

    _schedule(_do, delay=delay)
    return {
        "ok": True,
        "accepted": True,
        "action": "apply-update",
        "message": (
            "Applying appliance code from the public DIY repo in about "
            f"{delay:.0f}s. Services will restart; the LAN UI disconnects briefly. "
            "Camera YAML, private overlays, and /etc secrets are not overwritten."
        ),
        "delay_seconds": delay,
    }


def apply_from_tarball(
    *,
    base: Path | None = None,
    repo: Path | None = None,
    ref: str | None = None,
    remote_rev: str | None = None,
    download: Callable[[str, Path], None] | None = None,
) -> dict[str, Any]:
    """Download public branch tarball and sync allowlisted code paths into install root.

    Intended to run as root from ``webcam-update-apply.service``.
    """
    prefs = read_prefs(base)
    use_ref = ref or str(prefs["ref"])
    root = Path(repo or install_root())
    root.mkdir(parents=True, exist_ok=True)
    sha = remote_rev or fetch_remote_rev(remote=str(prefs["remote"]), ref=use_ref)
    url = _TARBALL_URL.format(ref=use_ref)

    with tempfile.TemporaryDirectory(prefix="webcam-update-") as tmp:
        tmp_path = Path(tmp)
        archive = tmp_path / "src.tar.gz"
        (download or _download)(url, archive)
        extract_dir = tmp_path / "extract"
        extract_dir.mkdir()
        subprocess.run(
            ["tar", "-xzf", str(archive), "-C", str(extract_dir)],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        children = [p for p in extract_dir.iterdir() if p.is_dir()]
        if not children:
            raise UpdatesError("tarball extract produced no directory")
        src_root = children[0]
        for rel in _SYNC_REL_PATHS:
            src = src_root / rel
            dst = root / rel
            if not src.exists():
                continue
            if src.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [
                    "rsync",
                    "-a",
                    "--delete",
                    "--exclude",
                    "__pycache__",
                    "--exclude",
                    ".pytest_cache",
                    f"{src}/",
                    f"{dst}/",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )

        req = root / "pi" / "pipeline" / "requirements.txt"
        venv_pip = root / "pi" / "pipeline" / ".venv" / "bin" / "pip"
        if req.is_file() and venv_pip.is_file():
            subprocess.run(
                [str(venv_pip), "install", "-r", str(req)],
                check=False,
                capture_output=True,
                text=True,
                timeout=600,
            )

        # Refresh unit files if present (idempotent; skip when /etc not writable).
        _install_unit_files(root)

        _systemctl(["daemon-reload"])
        _systemctl(["restart", "webcam-camera.service", "webcam-pipeline.service"])

    write_installed_rev(sha, base)
    st = read_state(base)
    st.update(
        {
            "last_apply_at": _utc_now(),
            "last_error": None,
            "remote_rev": sha,
            "update_available": False,
            "message": f"Applied {sha[:12]} — services restarted.",
            "last_check_ok": True,
        }
    )
    write_state(st, base)
    _chown_webcam(pref_path(base), state_path(base), installed_rev_path(base))
    return status(base=base, repo=root)


def maybe_overnight_check(*, base: Path | None = None) -> dict[str, Any]:
    """Entry for the systemd timer — no-op when opt-in is off."""
    return run_check(base=base, force=False)


def _require_https(url: str) -> None:
    if not url.startswith("https://"):
        raise UpdatesError("refusing non-HTTPS update URL")


def _http_json(url: str) -> dict[str, Any]:
    _require_https(url)
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "home-webcam-pipeline-updates",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:  # nosec B310
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise UpdatesError(f"GitHub API HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise UpdatesError(f"network error: {exc.reason}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UpdatesError("invalid JSON from GitHub API") from exc
    if not isinstance(data, dict):
        raise UpdatesError("unexpected GitHub API payload")
    return data


def _download(url: str, dest: Path) -> None:
    _require_https(url)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "home-webcam-pipeline-updates"},
    )
    with urllib.request.urlopen(req, timeout=180) as resp, dest.open("wb") as fh:  # nosec B310
        shutil.copyfileobj(resp, fh)


def _ls_remote(remote: str, ref: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "ls-remote", remote, f"refs/heads/{ref}"],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise UpdatesError(str(exc)) from exc
    if proc.returncode != 0:
        raise UpdatesError((proc.stderr or proc.stdout or "git ls-remote failed")[:200])
    line = (proc.stdout or "").strip().splitlines()
    if not line:
        raise UpdatesError(f"no remote ref for {ref}")
    sha = line[0].split()[0].strip()
    if len(sha) < 7:
        raise UpdatesError("invalid ls-remote sha")
    return sha


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _public_err(exc: Any) -> str:
    msg = str(exc or "").strip() or "update check failed"
    return msg[:300]


def _schedule(fn: Callable[[], None], *, delay: float) -> None:
    def _worker() -> None:
        time.sleep(max(0.0, float(delay)))
        try:
            fn()
        except Exception:  # noqa: BLE001
            pass

    import threading

    threading.Thread(target=_worker, name="webcam-updates", daemon=True).start()


def _run(args: list[str]) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _chown_webcam(*paths: Path) -> None:
    """Best-effort: LAN UI (user webcam) must keep writing prefs/state."""
    try:
        import pwd

        pw = pwd.getpwnam("webcam")
    except (KeyError, ImportError, OSError):
        return
    for path in paths:
        try:
            if path.is_file():
                os.chown(path, pw.pw_uid, pw.pw_gid)
        except OSError:
            pass


def _systemctl(args: list[str]) -> None:
    """Best-effort systemctl (absent on macOS unit tests)."""
    try:
        subprocess.run(
            ["systemctl", *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def _install_unit_files(root: Path) -> None:
    try:
        etc_sys = Path("/etc/systemd/system")
        if not etc_sys.is_dir() or not os.access(etc_sys, os.W_OK):
            return
        for unit in (
            root / "pi" / "pipeline" / "systemd" / "webcam-pipeline.service",
            root / "pi" / "camera" / "systemd" / "webcam-camera.service",
        ):
            if unit.is_file():
                shutil.copy2(unit, etc_sys / unit.name)
        host_units = root / "pi" / "host" / "systemd"
        if host_units.is_dir():
            for unit in host_units.glob("webcam-update-*.service"):
                shutil.copy2(unit, etc_sys / unit.name)
            for unit in host_units.glob("webcam-update-*.timer"):
                shutil.copy2(unit, etc_sys / unit.name)
        for rules in (
            root / "pi" / "pipeline" / "systemd" / "50-webcam-system.rules",
            root / "pi" / "pipeline" / "systemd" / "50-webcam-network.rules",
        ):
            if rules.is_file():
                dest = Path("/etc/polkit-1/rules.d") / rules.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(rules, dest)
    except OSError:
        return
