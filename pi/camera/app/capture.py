from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class CaptureBackend(ABC):
    name: str

    @abstractmethod
    def capture(self) -> bytes:
        ...

    @abstractmethod
    def info(self) -> dict[str, Any]:
        ...

    def close(self) -> None:
        return None


class SimulationBackend(CaptureBackend):
    """Internal fixture backend for local/CI tests (not operator-documented)."""

    name = "simulation"

    def __init__(self, image_path: Path) -> None:
        if not image_path.exists():
            raise FileNotFoundError(f"fixture image missing: {image_path}")
        self.image_path = image_path

    def capture(self) -> bytes:
        data = self.image_path.read_bytes()
        if len(data) < 100 or data[:2] != b"\xff\xd8":
            raise ValueError("fixture image is not a valid JPEG")
        return data

    def info(self) -> dict[str, Any]:
        return {
            "detected": True,
            "model": "fixture",
            "path": str(self.image_path),
        }


def _apply_picamera2_controls(cam: Any, exposure_mode: str | None, awb_mode: str | None) -> dict[str, Any]:
    """Best-effort Ae/Awb controls; ignore unknown modes on older stacks."""
    applied: dict[str, Any] = {}
    controls: dict[str, Any] = {}
    # libcamera / picamera2: AeEnable / AwbEnable + optional AwbMode enum
    if exposure_mode:
        mode = str(exposure_mode).lower()
        if mode in ("auto", "normal"):
            controls["AeEnable"] = True
            applied["exposure_mode"] = "auto"
        elif mode in ("off", "manual"):
            controls["AeEnable"] = False
            applied["exposure_mode"] = "off"
        else:
            applied["exposure_mode"] = f"unsupported:{mode}"
    if awb_mode:
        mode = str(awb_mode).lower()
        if mode in ("auto", "normal"):
            controls["AwbEnable"] = True
            applied["awb_mode"] = "auto"
        elif mode in ("off", "manual"):
            controls["AwbEnable"] = False
            applied["awb_mode"] = "off"
        else:
            # Named AWB modes vary by firmware; try string passthrough via controls if present
            applied["awb_mode"] = mode
            try:
                from libcamera import controls as lcontrols  # type: ignore

                mapping = {
                    "daylight": getattr(lcontrols.AwbModeEnum, "Daylight", None),
                    "cloudy": getattr(lcontrols.AwbModeEnum, "Cloudy", None),
                    "tungsten": getattr(lcontrols.AwbModeEnum, "Tungsten", None),
                    "fluorescent": getattr(lcontrols.AwbModeEnum, "Fluorescent", None),
                    "indoor": getattr(lcontrols.AwbModeEnum, "Indoor", None),
                }
                enum_val = mapping.get(mode)
                if enum_val is not None:
                    controls["AwbEnable"] = True
                    controls["AwbMode"] = enum_val
            except Exception:  # noqa: BLE001
                pass
    if controls:
        try:
            cam.set_controls(controls)
            applied["controls_set"] = True
        except Exception as exc:  # noqa: BLE001
            applied["controls_set"] = False
            applied["controls_error"] = str(exc)
    return applied


class Picamera2Backend(CaptureBackend):
    name = "picamera2"

    def __init__(
        self,
        width: int,
        height: int,
        jpeg_quality: int,
        *,
        exposure_mode: str | None = "auto",
        awb_mode: str | None = "auto",
    ) -> None:
        from picamera2 import Picamera2  # type: ignore

        self.width = width
        self.height = height
        self.jpeg_quality = jpeg_quality
        self.exposure_mode = exposure_mode
        self.awb_mode = awb_mode
        self.cam = Picamera2()
        config = self.cam.create_still_configuration(
            main={"size": (width, height)},
        )
        self.cam.configure(config)
        self.cam.start()
        time.sleep(0.3)
        self.controls_applied = _apply_picamera2_controls(self.cam, exposure_mode, awb_mode)
        time.sleep(0.2)

    def capture(self) -> bytes:
        import io

        from PIL import Image

        arr = self.cam.capture_array("main")
        img = Image.fromarray(arr)
        if img.mode != "RGB":
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=int(self.jpeg_quality), optimize=True)
        data = buf.getvalue()
        if len(data) < 100 or data[:2] != b"\xff\xd8":
            raise ValueError("picamera2 produced invalid JPEG")
        return data

    def info(self) -> dict[str, Any]:
        props = {}
        try:
            props = dict(self.cam.camera_properties)
        except Exception:  # noqa: BLE001
            props = {}
        model = props.get("Model") or props.get("model") or "picamera2"
        return {
            "detected": True,
            "model": str(model),
            "width": self.width,
            "height": self.height,
            "jpeg_quality": self.jpeg_quality,
            "exposure_mode": self.exposure_mode,
            "awb_mode": self.awb_mode,
            "controls_applied": getattr(self, "controls_applied", {}),
        }

    def close(self) -> None:
        try:
            self.cam.stop()
            self.cam.close()
        except Exception:  # noqa: BLE001
            pass


class RpicamBackend(CaptureBackend):
    """Fallback using rpicam-still CLI."""

    name = "rpicam"

    def __init__(
        self,
        width: int,
        height: int,
        jpeg_quality: int,
        timeout_ms: int,
        *,
        exposure_mode: str | None = "auto",
        awb_mode: str | None = "auto",
    ) -> None:
        if not shutil.which("rpicam-still"):
            raise RuntimeError("rpicam-still not found on PATH")
        self.width = width
        self.height = height
        self.jpeg_quality = jpeg_quality
        self.timeout_ms = timeout_ms
        self.exposure_mode = exposure_mode
        self.awb_mode = awb_mode

    def capture(self) -> bytes:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            path = Path(tmp.name)
        try:
            cmd = [
                "rpicam-still",
                "-n",
                "-o",
                str(path),
                "--width",
                str(self.width),
                "--height",
                str(self.height),
                "-q",
                str(self.jpeg_quality),
                "-t",
                str(self.timeout_ms),
            ]
            # rpicam-still metering / AWB flags (best-effort; ignored if unsupported)
            if self.awb_mode and str(self.awb_mode).lower() not in ("auto", "normal", ""):
                cmd.extend(["--awb", str(self.awb_mode).lower()])
            if self.exposure_mode and str(self.exposure_mode).lower() in ("off", "manual"):
                cmd.extend(["--shutter", "10000"])  # fixed shutter hint when AE off
            subprocess.run(cmd, check=True, capture_output=True, timeout=self.timeout_ms / 1000 + 30)
            data = path.read_bytes()
        finally:
            path.unlink(missing_ok=True)
        if len(data) < 100 or data[:2] != b"\xff\xd8":
            raise ValueError("rpicam-still produced invalid JPEG")
        return data

    def info(self) -> dict[str, Any]:
        return {
            "detected": True,
            "model": "rpicam-still",
            "width": self.width,
            "height": self.height,
            "jpeg_quality": self.jpeg_quality,
            "exposure_mode": self.exposure_mode,
            "awb_mode": self.awb_mode,
        }


def _create_hardware_backend(kind: str, cfg: dict[str, Any], root: Path) -> CaptureBackend:
    """Instantiate picamera2 / rpicam immediately (may raise if no camera)."""
    del root  # unused; kept for call-site symmetry
    cap = cfg["capture"]
    width = int(cap["width"])
    height = int(cap["height"])
    quality = int(cap["jpeg_quality"])
    timeout_s = float(cap.get("timeout_seconds", 15))
    exposure = cap.get("exposure_mode")
    awb = cap.get("awb_mode")
    if kind == "picamera2":
        return Picamera2Backend(
            width, height, quality, exposure_mode=exposure, awb_mode=awb
        )
    if kind == "rpicam":
        return RpicamBackend(
            width,
            height,
            quality,
            int(timeout_s * 1000),
            exposure_mode=exposure,
            awb_mode=awb,
        )
    raise ValueError(f"unknown hardware capture_backend: {kind}")


class HardwareCaptureBackend(CaptureBackend):
    """Open picamera2/rpicam with retry; missing hardware → open_error, not a fixture backend."""

    def __init__(self, kind: str, cfg: dict[str, Any], root: Path) -> None:
        self.kind = kind
        self.name = kind
        self.cfg = cfg
        self.root = root
        self._inner: CaptureBackend | None = None
        self._open_error: str | None = None
        self._open_attempts = 0
        self.try_open()

    def try_open(self) -> bool:
        if self._inner is not None:
            return True
        self._open_attempts += 1
        try:
            self._inner = _create_hardware_backend(self.kind, self.cfg, self.root)
            self._open_error = None
            return True
        except Exception as exc:  # noqa: BLE001 — keep appliance up; auto-maintenance covers this
            self._open_error = str(exc)
            self._inner = None
            return False

    def capture(self) -> bytes:
        if not self.try_open():
            raise RuntimeError(f"camera open failed: {self._open_error}")
        assert self._inner is not None
        return self._inner.capture()

    def info(self) -> dict[str, Any]:
        if self._inner is not None:
            return self._inner.info()
        return {
            "detected": False,
            "model": f"{self.kind}-unavailable",
            "open_error": self._open_error,
            "open_attempts": self._open_attempts,
        }

    def close(self) -> None:
        if self._inner is not None:
            try:
                self._inner.close()
            finally:
                self._inner = None


def create_backend(cfg: dict[str, Any], root: Path) -> CaptureBackend:
    """Build capture backend. Fixture backend only when explicitly configured."""
    kind = str(cfg["capture_backend"]).lower()

    if kind == "simulation":
        rel = cfg.get("simulation_image", "tests/fixtures/sample.jpg")
        return SimulationBackend(root / rel)
    if kind in ("picamera2", "rpicam"):
        return HardwareCaptureBackend(kind, cfg, root)
    raise ValueError(f"unknown capture_backend: {kind}")
