"""LAN image pipeline — acquire, render, publish, private HTTP."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any

from . import __version__
from .acquire import (
    acquire_image,
    fetch_maintenance_flag,
    maintenance_api_url,
)
from .camera_profile import load_camera_profile, public_site_label
from .config import load_pipeline_config, resolve_repo_root
from .publish_r2 import Publisher
from .public_live import PublicLiveSelection, publish_live_key_for_variant
from .render import render_variants
from .schedule import PublicSchedule
from .serve_private import make_handler
from .timelapse import archive_for
from .state import PipelineState
from .store import OriginalStore, SaveResult
from .weather import DEFAULT_WEATHER_URL, get_weather_cache
from shared.brand_overlay import format_site_badge

log = logging.getLogger("pipeline")

# Log Wartung ON/OFF once per transition (not every 60s cycle).
_last_maintenance_log: dict[str, bool] = {}


def setup_logging(level: str) -> None:
    root = Path(__file__).resolve().parents[3]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from shared.logging_util import setup_logging as _setup

    _setup(level, name="pipeline")


def process_camera(
    camera_id: str,
    repo_root: Path,
    state: PipelineState,
    publisher: Publisher,
    *,
    force: bool = False,
    skip_acquire: bool = False,
) -> dict[str, Any]:
    """Run one acquire→store→render→publish cycle. Never deletes last-good data on failure.

    force: ignore 304 / always re-render even if source SHA unchanged.
    skip_acquire: regenerate variants from the stored original only (no Pi pull).
    """
    stages: dict[str, Any] = {}
    t_cycle = time.monotonic()
    log.info("[%s] ——— cycle start ———", camera_id)

    try:
        profile = load_camera_profile(repo_root, camera_id)
    except Exception as exc:  # noqa: BLE001
        summary = f"config error: {exc}"
        log.error("[%s] %s", camera_id, summary)
        state.record_cycle(
            camera_id,
            ok=False,
            summary=summary,
            stages={"config": {"ok": False, "error": str(exc)}},
            error=str(exc),
            next_steps=[
                f"Check cameras/{camera_id}/camera.yaml and variants/*.yaml",
                "Validate YAML indentation",
            ],
        )
        return {"ok": False, "summary": summary}

    # --- acquire (conditional GET when we already have validators) ---
    t0 = time.monotonic()
    store = OriginalStore(
        original_dir=repo_root / profile.storage["original_dir"],
        keep_history=int(profile.storage.get("keep_original_history", 0)),
    )
    meta = store.read_meta()
    maintenance = False

    if skip_acquire:
        if not store.latest_path.exists() or not meta.get("sha256"):
            summary = "render-only requested but no stored original"
            log.warning("[%s] %s", camera_id, summary)
            state.record_cycle(
                camera_id,
                ok=False,
                summary=summary,
                stages={"acquire": {"ok": False, "skipped": True, "error": summary}},
                error=summary,
                next_steps=["POST /refresh with acquire first", "Wait for a normal poll cycle"],
            )
            return {"ok": False, "summary": summary}
        saved = SaveResult(
            path=store.latest_path,
            sha256=str(meta["sha256"]),
            changed=bool(force),
            captured_at=float(meta.get("captured_at") or store.latest_path.stat().st_mtime),
        )
        stages["acquire"] = {"ok": True, "skipped": True, "force": force}
        stages["store"] = {"ok": True, "skipped": True, "path": str(saved.path)}
        maintenance = bool(meta.get("maintenance"))
        log.info("[%s] [acquire] skipped — regenerating from stored original", camera_id)
    else:
        log.info("[%s] [acquire] GET %s (timeout=%.0fs)", camera_id, profile.source_url, profile.timeout_seconds)
        result = acquire_image(
            profile.source_url,
            timeout=profile.timeout_seconds,
            etag=None if force else meta.get("etag"),
            last_modified=None if force else meta.get("last_modified"),
        )
        # /raw.jpg never sets X-Webcam-Maintenance — probe GET /maintenance (or /health).
        maint_url = maintenance_api_url(
            source_url=profile.source_url,
            health_url=profile.health_url,
        )
        api_maint = fetch_maintenance_flag(
            maintenance_url=maint_url,
            health_url=profile.health_url,
            timeout=min(5.0, float(profile.timeout_seconds)),
        )
        if api_maint is not None:
            maintenance = api_maint
        else:
            maintenance = result.maintenance
        stages["acquire"] = {
            "ok": result.ok,
            "duration_seconds": round(time.monotonic() - t0, 3),
            "url": profile.source_url,
            "error": result.error,
            "not_modified": result.not_modified,
            "force": force,
            "maintenance": maintenance,
            "maintenance_source": (
                "api" if api_maint is not None else ("header" if result.maintenance else "none")
            ),
            "bytes": len(result.data) if result.ok and not result.not_modified else 0,
            "sha256_prefix": (result.sha256[:12] if result.sha256 else None),
        }
        if not result.ok:
            summary = f"acquire failed: {result.error}"
            log.warning("[%s] [acquire] FAILED: %s", camera_id, result.error)
            log.warning(
                "[%s] [acquire] fail-safe: keeping last original + variants; not publishing",
                camera_id,
            )
            state.record_cycle(
                camera_id,
                ok=False,
                summary=summary,
                stages=stages,
                error=result.error,
                next_steps=[
                    f"curl -sS -D- -o /tmp/cam.jpg '{profile.source_url}' | head",
                    f"curl -sS '{profile.health_url or profile.source_url.rsplit('/', 1)[0] + '/health'}' | jq .",
                    "Confirm Pi service: systemctl status webcam-camera",
                ],
                fail_safe={
                    "keeping_last_original": True,
                    "keeping_last_variants": True,
                    "note": "Previous files left untouched; private HTTP still serves last good variants if present.",
                },
            )
            return {"ok": False, "summary": summary}

        if result.not_modified and not force:
            if not store.latest_path.exists() or not meta.get("sha256"):
                summary = "304 Not Modified but no stored original"
                log.warning("[%s] [acquire] %s", camera_id, summary)
                state.record_cycle(
                    camera_id,
                    ok=False,
                    summary=summary,
                    stages=stages,
                    error=summary,
                    next_steps=["Force refresh once to seed original"],
                )
                return {"ok": False, "summary": summary}
            # Keep going: site-badge temp can change without a new camera frame.
            if bool(meta.get("maintenance")) != maintenance:
                meta = dict(meta)
                meta["maintenance"] = maintenance
                store.meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            saved = SaveResult(
                path=store.latest_path,
                sha256=str(meta["sha256"]),
                changed=False,
                captured_at=float(meta.get("captured_at") or store.latest_path.stat().st_mtime),
            )
            stages["store"] = {"ok": True, "skipped": True, "path": str(saved.path), "not_modified": True}
            log.info(
                "[%s] [acquire] 304 Not Modified — reuse original; may refresh public badge",
                camera_id,
            )
        else:
            prev_maint = _last_maintenance_log.get(camera_id)
            if maintenance and prev_maint is not True:
                log.info(
                    "[%s] [acquire] camera maintenance ON — public variants use "
                    "Wartung while schedule is online (night/offline schedule wins); "
                    "private LAN-only stays on raw live",
                    camera_id,
                )
                _last_maintenance_log[camera_id] = True
            elif not maintenance and prev_maint is True:
                log.info(
                    "[%s] [acquire] camera maintenance OFF — public variants use live again",
                    camera_id,
                )
                _last_maintenance_log[camera_id] = False

            log.info(
                "[%s] [acquire] ok bytes=%s sha=%s… (%.0fms)",
                camera_id,
                len(result.data),
                result.sha256[:12],
                stages["acquire"]["duration_seconds"] * 1000,
            )

            # --- store ---
            t0 = time.monotonic()
            saved = store.save_if_changed(
                result.data,
                result.sha256,
                etag=result.etag,
                last_modified=result.last_modified,
                maintenance=maintenance,
            )
            stages["store"] = {
                "ok": True,
                "duration_seconds": round(time.monotonic() - t0, 3),
                "changed": saved.changed,
                "path": str(saved.path),
                "sha256_prefix": saved.sha256[:12],
            }
            if saved.changed:
                log.info("[%s] [store] NEW original saved → %s", camera_id, saved.path)
            else:
                log.info("[%s] [store] unchanged (sha match) — will skip re-render if cache warm", camera_id)

    # --- weather (public site badge; fail-soft) ---
    wx_cfg = profile.weather or {}
    weather = get_weather_cache(
        url=str(wx_cfg.get("url") or DEFAULT_WEATHER_URL),
        ttl_seconds=float(wx_cfg.get("ttl_seconds", 300)),
        timeout_seconds=float(wx_cfg.get("timeout_seconds", 4)),
    )
    snap = weather.get()
    stages["weather"] = snap.as_dict()
    if snap.temp_c is not None:
        log.info(
            "[%s] [weather] temp_c=%s source=%s",
            camera_id,
            snap.temp_c,
            snap.source,
        )
    else:
        log.info("[%s] [weather] no temperature (%s)", camera_id, snap.error or snap.source)

    # --- render ---
    t0 = time.monotonic()
    variants_dir = repo_root / profile.storage["variants_dir"]
    try:
        rendered = render_variants(
            original_path=saved.path,
            source_sha=saved.sha256,
            captured_at=saved.captured_at,
            timezone_name=profile.timezone,
            variant_configs=profile.variants,
            variants_dir=variants_dir,
            force=force or saved.changed,
            repo_root=repo_root,
            temp_c=snap.temp_c,
            maintenance=maintenance,
            brand=profile.display_name or "Webcam",
            status=profile.status_text,
        )
        state.record_render(camera_id, rendered)
        stages["render"] = {
            "ok": True,
            "duration_seconds": round(time.monotonic() - t0, 3),
            "variants": [
                {
                    "name": r.name,
                    "visibility": r.visibility,
                    "changed": r.changed,
                    "path": str(r.path),
                    "bytes": r.path.stat().st_size if r.path.exists() else 0,
                }
                for r in rendered
            ],
        }
        changed_names = [r.name for r in rendered if r.changed]
        cached_names = [r.name for r in rendered if not r.changed]
        log.info(
            "[%s] [render] done in %.0fms | rebuilt=%s | cached=%s",
            camera_id,
            stages["render"]["duration_seconds"] * 1000,
            changed_names or "—",
            cached_names or "—",
        )
    except Exception as exc:  # noqa: BLE001
        summary = f"render failed: {exc}"
        log.exception("[%s] [render] FAILED: %s", camera_id, exc)
        stages["render"] = {"ok": False, "error": str(exc), "duration_seconds": round(time.monotonic() - t0, 3)}
        state.record_cycle(
            camera_id,
            ok=False,
            summary=summary,
            stages=stages,
            error=str(exc),
            source_sha=saved.sha256,
            changed=saved.changed,
            original_path=str(saved.path),
            next_steps=[
                "Check Pillow / variant YAML crops and masks",
                f"Inspect original: {saved.path}",
            ],
            fail_safe={
                "keeping_last_variants": True,
                "note": "Render failure does not delete prior variant files.",
            },
        )
        return {"ok": False, "summary": summary}

    # --- publish (selected public_live → fixed live key; optional secondary keys) ---
    # Public live precedence (fixed R2/outbox live key):
    #   1. Schedule offline (public_online=False) → night/offline placeholder
    #      even if camera maintenance / Wartungsbild is on
    #   2. Else maintenance on → rendered Wartung frame (history skipped)
    #   3. Else normal live variant from raw original
    # Private HA is not published here; private variants always render from /raw.jpg
    # (never schedule placeholder, never Wartungsbild).
    t0 = time.monotonic()
    publish_results = []
    schedule = PublicSchedule(repo_root, camera_id)
    sched_status = schedule.evaluate()
    stages["schedule"] = sched_status.as_dict()
    public_live = PublicLiveSelection(repo_root, camera_id)
    live_variant = public_live.variant_name(profile)
    fixed_live_key = public_live.live_key()
    force_live_switch = public_live.consume_force_publish()
    stages["public_live"] = {
        "variant": live_variant,
        "live_key": fixed_live_key,
        "force_publish": force_live_switch,
    }
    marker = schedule.dir / "last_public_online"
    was_online = marker.read_text().strip() == "1" if marker.exists() else True
    force_public = (not was_online) and sched_status.public_online
    if not sched_status.public_online:
        log.info(
            "[%s] [schedule] public offline (%s) — placeholder until %s%s",
            camera_id,
            sched_status.reason,
            sched_status.back_at,
            " (overrides maintenance)" if maintenance else "",
        )
    elif force_public:
        log.info("[%s] [schedule] public window opened — forcing live publish", camera_id)
    if force_live_switch:
        log.info(
            "[%s] [public_live] switch → variant=%s key=%s (force publish)",
            camera_id,
            live_variant,
            fixed_live_key,
        )

    # Daylight stills for the LAN timelapse. Not uploaded. Night and Wartung are skipped.
    if sched_status.public_online and not maintenance:
        live_item = next((item for item in rendered if item.name == live_variant), None)
        if live_item is not None and live_item.path.is_file():
            try:
                stored = archive_for(repo_root, camera_id, profile).maybe_store(
                    live_item.path, saved.captured_at
                )
                if stored is not None:
                    log.info("[%s] [timelapse] stored %s", camera_id, stored.name)
            except Exception as exc:  # noqa: BLE001 — archive must not fail the live publish
                log.error("[%s] [timelapse] store failed: %s", camera_id, exc)

    for item in rendered:
        target_key = publish_live_key_for_variant(
            variant_name=item.name,
            visibility=item.visibility,
            publish_enabled=item.publish_enabled,
            variant_r2_live_key=item.r2_live_key,
            public_live_variant=live_variant,
            fixed_live_key=fixed_live_key,
        )
        if not target_key:
            log.debug(
                "[%s] [publish] skip variant=%s (not public_live / no secondary key)",
                camera_id,
                item.name,
            )
            continue
        is_public_live = item.name == live_variant

        # (1) Schedule offline wins over maintenance for the public live key.
        if not sched_status.public_online:
            try:
                size = None
                if item.path.exists():
                    from PIL import Image

                    with Image.open(item.path) as im:
                        size = im.size
                site = public_site_label(profile)
                badge = format_site_badge(site, snap.temp_c) if site else None
                placeholder = schedule.render_public_placeholder(
                    sched_status,
                    size=size,
                    site_badge=badge,
                    brand=profile.display_name or "Webcam",
                )
            except Exception as exc:  # noqa: BLE001
                log.error("[%s] [schedule] placeholder render failed: %s", camera_id, exc)
                publish_results.append(
                    {"variant": item.name, "ok": False, "detail": f"placeholder failed: {exc}"}
                )
                continue
            # Minute clock + temp badge change the JPEG; skip identical re-uploads.
            ph_bytes = placeholder.read_bytes()
            ph_sha = hashlib.sha256(ph_bytes).hexdigest()
            sha_marker = schedule.dir / f"last_placeholder_sha_{item.name}"
            prev_sha = sha_marker.read_text().strip() if sha_marker.exists() else ""
            if ph_sha == prev_sha and not force_public and not force_live_switch:
                log.debug(
                    "[%s] [publish] skip unchanged offline placeholder variant=%s",
                    camera_id,
                    item.name,
                )
                continue
            pr = publisher.publish_public(
                camera_id=camera_id,
                variant_name=item.name,
                local_path=placeholder,
                live_key=target_key,
                history_variant=item.r2_history_variant,
                history_cfg=profile.history,
                captured_at=saved.captured_at,
                skip_history=True,
                skip_history_reason="schedule/offline placeholder",
            )
            state.record_publish(
                camera_id,
                variant=item.name,
                ok=pr.ok,
                detail=f"schedule offline: {pr.detail}",
                live_key=pr.live_key,
                history_key=None,
            )
            publish_results.append(
                {
                    "variant": item.name,
                    **pr.__dict__,
                    "public_live": is_public_live,
                    "schedule_offline": True,
                    "maintenance_overridden": bool(maintenance),
                    "back_at": sched_status.back_at.isoformat() if sched_status.back_at else None,
                }
            )
            if pr.ok:
                sha_marker.write_text(ph_sha + "\n", encoding="utf-8")
                log.info("[%s] [publish] offline placeholder → %s", camera_id, pr.live_key)
            else:
                log.error("[%s] [publish] offline placeholder FAILED: %s", camera_id, pr.detail)
            continue

        # (2)/(3) Schedule online: Wartung frame (maintenance) or normal live.
        # Publish when variant rebuilt (new frame / temp / Wartung clock minute).
        if not item.changed and not force_public and not (
            is_public_live and force_live_switch
        ):
            log.debug("[%s] [publish] skip unchanged public variant=%s", camera_id, item.name)
            continue
        pr = publisher.publish_public(
            camera_id=camera_id,
            variant_name=item.name,
            local_path=item.path,
            live_key=target_key,
            history_variant=item.r2_history_variant,
            history_cfg=profile.history,
            captured_at=saved.captured_at,
            skip_history=maintenance,
            skip_history_reason="maintenance placeholder" if maintenance else "placeholder",
        )
        state.record_publish(
            camera_id,
            variant=item.name,
            ok=pr.ok,
            detail=pr.detail,
            live_key=pr.live_key,
            history_key=pr.history_key,
        )
        publish_results.append(
            {"variant": item.name, "public_live": is_public_live, **pr.__dict__}
        )
        if pr.ok:
            log.info("[%s] [publish] %s → %s", camera_id, item.name, pr.live_key or pr.detail)
        else:
            log.error("[%s] [publish] %s FAILED: %s", camera_id, item.name, pr.detail)

    marker.write_text("1\n" if sched_status.public_online else "0\n", encoding="utf-8")

    stages["publish"] = {
        "ok": all(p.get("ok", True) for p in publish_results) if publish_results else True,
        "duration_seconds": round(time.monotonic() - t0, 3),
        "backend": publisher.backend if publisher.enabled else "disabled",
        "results": publish_results,
    }

    publish_ok = stages["publish"]["ok"]
    elapsed = time.monotonic() - t_cycle
    if publish_ok:
        summary = (
            f"ok changed={saved.changed} variants={len(rendered)} "
            f"published={len(publish_results)} in {elapsed:.2f}s"
        )
        log.info("[%s] ——— cycle OK ——— %s", camera_id, summary)
        state.record_cycle(
            camera_id,
            ok=True,
            summary=summary,
            stages=stages,
            source_sha=saved.sha256,
            changed=saved.changed,
            original_path=str(saved.path),
            next_steps=["No action needed"],
        )
        return {"ok": True, "summary": summary}

    summary = f"partial: acquire/render ok but publish had errors ({elapsed:.2f}s)"
    log.warning("[%s] ——— cycle DEGRADED ——— %s", camera_id, summary)
    state.record_cycle(
        camera_id,
        ok=False,
        summary=summary,
        stages=stages,
        error="publish errors — see stages.publish",
        source_sha=saved.sha256,
        changed=saved.changed,
        original_path=str(saved.path),
        next_steps=[
            "Check AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_ENDPOINT_URL",
            "Or set publish.backend: local and inspect data/outbox/",
            "Local variants remain available on the LAN (e.g. Home Assistant)",
        ],
        fail_safe={
            "keeping_last_variants": True,
            "note": "Publish failure does not remove local private/public JPEGs.",
        },
    )
    return {"ok": False, "summary": summary}


def loop(
    cfg: dict,
    repo_root: Path,
    state: PipelineState,
    publisher: Publisher,
    stop: threading.Event,
) -> None:
    cameras = list(cfg["cameras"])
    default_interval = float(cfg.get("poll_interval_seconds", 30))
    cycle_num = 0
    while not stop.is_set():
        cycle_num += 1
        log.info("======== pipeline poll #%s cameras=%s ========", cycle_num, cameras)
        for camera_id in cameras:
            if stop.is_set():
                break
            try:
                process_camera(camera_id, repo_root, state, publisher)
            except Exception as exc:  # noqa: BLE001
                log.exception("[%s] unexpected pipeline error: %s", camera_id, exc)
                state.record_cycle(
                    camera_id,
                    ok=False,
                    summary=f"unexpected error: {exc}",
                    stages={"error": {"ok": False, "error": str(exc)}},
                    error=str(exc),
                    next_steps=["Check logs above for stack trace", "GET /debug"],
                )
        interval = default_interval
        try:
            profile = load_camera_profile(repo_root, cameras[0])
            interval = float(profile.poll_interval_seconds)
        except Exception:  # noqa: BLE001
            pass
        health = state.health()
        log.info(
            "======== poll #%s done | overall=%s | next in %.0fs | %s ========",
            cycle_num,
            health["status"],
            interval,
            health["summary"],
        )
        stop.wait(interval)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Home webcam LAN pipeline")
    parser.add_argument(
        "--config",
        default=str(Path(__file__).resolve().parents[1] / "config" / "pipeline.yaml"),
    )
    parser.add_argument("--once", action="store_true", help="Process once and exit")
    parser.add_argument("--verbose", action="store_true", help="DEBUG logging")
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    if not config_path.exists():
        example = config_path.with_name("pipeline.example.yaml")
        if example.exists():
            config_path = example
            print(f"pipeline.yaml missing; using {example}", file=sys.stderr)
        else:
            print(f"Config not found: {config_path}", file=sys.stderr)
            return 1

    cfg = load_pipeline_config(config_path)
    level = "DEBUG" if args.verbose else cfg.get("logging", {}).get("level", "INFO")
    setup_logging(level)
    repo_root = resolve_repo_root(cfg, config_path)

    log.info("starting webcam-pipeline version=%s", __version__)
    log.info("config=%s repo_root=%s cameras=%s", config_path, repo_root, cfg.get("cameras"))

    state = PipelineState(version=__version__, config=cfg, repo_root=repo_root)
    publisher = Publisher(cfg.get("publish") or {}, repo_root=repo_root)
    state.set_publish_info(**publisher.info())

    stop = threading.Event()

    def on_signal(signum, _frame):
        log.info("[shutdown] signal %s", signum)
        stop.set()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    if args.once:
        exit_ok = True
        for camera_id in cfg["cameras"]:
            result = process_camera(camera_id, repo_root, state, publisher)
            if not result.get("ok"):
                exit_ok = False
        health = state.health()
        log.info("[once] finished overall=%s — %s", health["status"], health["summary"])
        return 0 if exit_ok or health["status"] == "DEGRADED" else 1

    worker = threading.Thread(
        target=loop,
        args=(cfg, repo_root, state, publisher, stop),
        name="pipeline-loop",
        daemon=True,
    )
    worker.start()

    handler = make_handler(
        state,
        repo_root,
        refresh_fn=lambda camera_id, force=False, skip_acquire=False: process_camera(
            camera_id,
            repo_root,
            state,
            publisher,
            force=force,
            skip_acquire=skip_acquire,
        ),
        refresh_min_interval=float((cfg.get("http") or {}).get("refresh_min_interval_seconds", 5)),
    )
    host = cfg.get("bind_host", "0.0.0.0")
    port = int(cfg.get("bind_port", 8090))
    root = Path(__file__).resolve().parents[3]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from shared.http_server import QuietThreadingHTTPServer

    server = QuietThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    http_thread = threading.Thread(target=server.serve_forever, name="http", daemon=True)
    http_thread.start()
    log.info(
        "[startup] private HTTP http://%s:%s/  (/health /schedule/ui /variants/ui /cameras/...)",
        host,
        port,
    )

    try:
        while not stop.is_set():
            stop.wait(0.5)
    finally:
        stop.set()
        server.shutdown()
        log.info("[shutdown] stopped cleanly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
