"""Opt-in overnight DIY update check + notify status."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(ROOT))

from app.updates import (  # noqa: E402
    DEFAULT_REMOTE,
    apply_from_tarball,
    default_prefs,
    read_prefs,
    run_check,
    set_check_overnight,
    status,
    write_installed_rev,
    write_prefs,
)


def test_default_prefs_opt_in_off():
    prefs = default_prefs()
    assert prefs["check_overnight"] is False
    assert prefs["remote"] == DEFAULT_REMOTE
    assert prefs["ref"] == "main"


def test_write_read_prefs(tmp_path: Path):
    write_prefs({"check_overnight": True}, base=tmp_path)
    prefs = read_prefs(base=tmp_path)
    assert prefs["check_overnight"] is True
    # Reject non-GitHub remotes (no private token URLs).
    write_prefs(
        {
            "check_overnight": False,
            "remote": "https://evil.example/repo.git",
        },
        base=tmp_path,
    )
    assert read_prefs(base=tmp_path)["remote"] == DEFAULT_REMOTE


def test_set_check_overnight(tmp_path: Path):
    out = set_check_overnight(True, base=tmp_path)
    assert out["check_overnight"] is True
    out = set_check_overnight(False, base=tmp_path)
    assert out["check_overnight"] is False


def test_run_check_skips_when_opt_out(tmp_path: Path):
    write_prefs({"check_overnight": False}, base=tmp_path)
    write_installed_rev("aaa111", base=tmp_path)

    def boom(_url: str) -> dict:
        raise AssertionError("should not hit network when overnight off")

    out = run_check(base=tmp_path, force=False, opener=boom)
    assert out["ok"] is True
    assert out["check_overnight"] is False


def test_run_check_force_compares_revs(tmp_path: Path):
    write_prefs({"check_overnight": False}, base=tmp_path)
    write_installed_rev("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", base=tmp_path)

    def fake_api(_url: str) -> dict:
        return {"sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}

    out = run_check(base=tmp_path, force=True, opener=fake_api)
    assert out["ok"] is True
    assert out["update_available"] is True
    assert out["remote_rev"].startswith("bbbb")


def test_run_check_up_to_date(tmp_path: Path):
    sha = "cccccccccccccccccccccccccccccccccccccccc"
    write_prefs({"check_overnight": True}, base=tmp_path)
    write_installed_rev(sha, base=tmp_path)

    def fake_api(_url: str) -> dict:
        return {"sha": sha}

    out = run_check(base=tmp_path, force=False, opener=fake_api)
    assert out["update_available"] is False
    assert out["last_check_ok"] is True


def test_apply_syncs_allowlist_only(tmp_path: Path):
    """Apply copies code paths; leaves cameras/ and a secret marker alone."""
    install = tmp_path / "opt"
    cameras = install / "cameras" / "example"
    cameras.mkdir(parents=True)
    (cameras / "camera.yaml").write_text("keep: me\n", encoding="utf-8")
    secret_marker = install / "do-not-touch.txt"
    secret_marker.write_text("secret\n", encoding="utf-8")

    # Fake tarball layout under a temp extract via custom download.
    def fake_download(_url: str, dest: Path) -> None:
        import io
        import tarfile

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            def add(name: str, data: bytes) -> None:
                info = tarfile.TarInfo(name=name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))

            base = "diy-home-webcam-main"
            add(f"{base}/shared/version.py", b'__version__ = "0.1.1"\n')
            add(f"{base}/pi/pipeline/app/hello.py", b"# new\n")
            add(f"{base}/cameras/example/camera.yaml", b"wipe: bad\n")
        dest.write_bytes(buf.getvalue())

    state = tmp_path / "state"
    state.mkdir()
    write_prefs({"check_overnight": False}, base=state)

    # Avoid systemctl / pip side effects: stub by only testing sync paths via
    # a thin wrapper — call apply with download but monkeypatch subprocess for
    # systemctl restart by ensuring those paths are optional when missing.
    # Here we patch apply internals by running with INSTALL_ROOT and catching
    # systemctl failures (check=False already).
    import os

    os.environ["INSTALL_ROOT"] = str(install)
    try:
        out = apply_from_tarball(
            base=state,
            repo=install,
            remote_rev="dddddddddddddddddddddddddddddddddddddddd",
            download=fake_download,
        )
    finally:
        os.environ.pop("INSTALL_ROOT", None)

    assert (install / "shared" / "version.py").read_text(encoding="utf-8").startswith(
        "__version__"
    )
    assert (install / "pi" / "pipeline" / "app" / "hello.py").is_file()
    # cameras/ must not be overwritten from the tarball allowlist
    assert (cameras / "camera.yaml").read_text(encoding="utf-8") == "keep: me\n"
    assert secret_marker.read_text(encoding="utf-8") == "secret\n"
    assert out["local_rev"].startswith("dddd")
    assert out["update_available"] is False


def test_status_message_default(tmp_path: Path):
    st = status(base=tmp_path)
    assert st["check_overnight"] is False
    assert "off" in (st["message"] or "").lower() or "Overnight" in (st["message"] or "")
