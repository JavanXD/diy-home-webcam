#!/usr/bin/env python3
"""Generate camera fixture + Wartung/Nacht placeholder JPEGs from a real forest photo.

Source (prefer in order):
  1. --source PATH
  2. PLACEHOLDER_PHOTO_SOURCE env
  3. pi/scripts/assets/example-forest-source.jpg (vendored landscape crop)
  4. ~/Projects/Ferienhaus/docs/photos/gallery-forest.jpg (gallery master)

Outputs:
  - pi/camera/tests/fixtures/sample.jpg          (IMX477-ish still size)
  - pi/pipeline/tests/fixtures/sample.jpg        (same bytes)
  - pi/camera/app/assets/maintenance-base.jpg    (dimmed photo, no text)
  - pi/camera/app/assets/maintenance.jpg         (photo + Wartung overlay)
  - pi/pipeline/app/assets/offline-base.jpg      (dimmed photo, no text)
  - pi/pipeline/app/assets/offline-placeholder.jpg (photo + Nachts overlay)

Typography is drawn at the final slide pixel size after cover_fit — never baked
into a layer that later gets an anisotropic resize.

Run from repo root:
  python3 pi/scripts/generate-placeholders.py
  python3 pi/scripts/generate-placeholders.py --source /path/to/photo.jpg
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.brand_overlay import (  # noqa: E402
    NACHT_BODY,
    NACHT_TITLE,
    WARTUNG_BODY,
    WARTUNG_TITLE,
    compose_slide_background,
    compose_status_slide,
    cover_fit,
    format_back_at_sample,
)

ASSETS = Path(__file__).resolve().parent / "assets"
VENDOR_SOURCE = ASSETS / "example-forest-source.jpg"
FERIENHAUS_MASTER = (
    Path.home() / "Projects/Ferienhaus/docs/photos/gallery-forest.jpg"
)

CAMERA_SAMPLE = ROOT / "pi/camera/tests/fixtures/sample.jpg"
PIPELINE_SAMPLE = ROOT / "pi/pipeline/tests/fixtures/sample.jpg"
MAINT_BASE = ROOT / "pi/camera/app/assets/maintenance-base.jpg"
MAINT = ROOT / "pi/camera/app/assets/maintenance.jpg"
OFFLINE_BASE = ROOT / "pi/pipeline/app/assets/offline-base.jpg"
OFFLINE = ROOT / "pi/pipeline/app/assets/offline-placeholder.jpg"

# Match pi/camera config (IMX477 still) and public-style 16:9 slides
CAPTURE_SIZE = (4056, 3040)  # 4:3 landscape
SLIDE_SIZE = (1920, 1080)  # 16:9
CAPTURE_QUALITY = 88
SLIDE_QUALITY = 90


def _resolve_source(explicit: Path | None) -> Path:
    if explicit is not None:
        if not explicit.is_file():
            raise FileNotFoundError(f"--source not found: {explicit}")
        return explicit
    env = os.environ.get("PLACEHOLDER_PHOTO_SOURCE", "").strip()
    if env:
        p = Path(env).expanduser()
        if not p.is_file():
            raise FileNotFoundError(f"PLACEHOLDER_PHOTO_SOURCE not found: {p}")
        return p
    if VENDOR_SOURCE.is_file():
        return VENDOR_SOURCE
    if FERIENHAUS_MASTER.is_file():
        return FERIENHAUS_MASTER
    raise FileNotFoundError(
        "No forest photo source. Pass --source, set PLACEHOLDER_PHOTO_SOURCE, "
        f"or place {VENDOR_SOURCE.relative_to(ROOT)}"
    )


def _save_jpeg(im: Image.Image, path: Path, *, quality: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, format="JPEG", quality=quality, optimize=True, progressive=True)
    print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size} bytes, {im.size[0]}×{im.size[1]})")


def make_vendor_source(master: Path) -> Path:
    """Store a landscape crop of the gallery master for offline regeneration."""
    im = ImageOps.exif_transpose(Image.open(master).convert("RGB"))
    # Native cover toward capture aspect without upscaling beyond master width
    target_ar = CAPTURE_SIZE[0] / CAPTURE_SIZE[1]
    w, h = im.size
    if w / h > target_ar:
        nw = int(h * target_ar)
        left = (w - nw) // 2
        crop = im.crop((left, 0, left + nw, h))
    else:
        nh = int(w / target_ar)
        # Bias slightly upward so path + canopy stay in frame for portrait masters
        top = max(0, int((h - nh) * 0.35))
        crop = im.crop((0, top, w, top + nh))
    ASSETS.mkdir(parents=True, exist_ok=True)
    _save_jpeg(crop, VENDOR_SOURCE, quality=92)
    source_txt = ASSETS / "SOURCE.txt"
    source_txt.write_text(
        "DIY placeholder source\n"
        "=====================================\n"
        "Master: Ferienhaus/docs/photos/gallery-forest.jpg\n"
        "  (example.com gallery key \"forest\")\n"
        "This file is a landscape center/upper crop for cover-fit to\n"
        f"camera still {CAPTURE_SIZE[0]}×{CAPTURE_SIZE[1]} and 16:9 slides.\n"
        "Regenerate outputs: python3 pi/scripts/generate-placeholders.py\n"
        "All fits use ImageOps.fit (crop then scale) — never stretch.\n"
        "Slide text is drawn after cover_fit at final pixel size.\n",
        encoding="utf-8",
    )
    print(f"wrote {source_txt.relative_to(ROOT)}")
    return VENDOR_SOURCE


def make_capture_samples(photo: Image.Image) -> None:
    still = cover_fit(photo, CAPTURE_SIZE)
    _save_jpeg(still, CAMERA_SAMPLE, quality=CAPTURE_QUALITY)
    PIPELINE_SAMPLE.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CAMERA_SAMPLE, PIPELINE_SAMPLE)
    print(f"wrote {PIPELINE_SAMPLE.relative_to(ROOT)} (copy)")


def make_maintenance(photo: Image.Image) -> None:
    base = compose_slide_background(photo, SLIDE_SIZE)
    _save_jpeg(base, MAINT_BASE, quality=SLIDE_QUALITY)
    img = compose_status_slide(
        photo,
        SLIDE_SIZE,
        title=WARTUNG_TITLE,
        body=WARTUNG_BODY,
        back_at_label=None,
        back_at_time=None,
    )
    _save_jpeg(img, MAINT, quality=SLIDE_QUALITY)


def make_offline(photo: Image.Image) -> None:
    base = compose_slide_background(photo, SLIDE_SIZE)
    _save_jpeg(base, OFFLINE_BASE, quality=SLIDE_QUALITY)
    label, time_line = format_back_at_sample()
    img = compose_status_slide(
        photo,
        SLIDE_SIZE,
        title=NACHT_TITLE,
        body=NACHT_BODY,
        back_at_label=label,
        back_at_time=time_line,
        back_at_panel=False,
    )
    _save_jpeg(img, OFFLINE, quality=SLIDE_QUALITY)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=None, help="Forest photo JPEG/PNG")
    parser.add_argument(
        "--refresh-vendor",
        action="store_true",
        help="Rebuild pi/scripts/assets/example-forest-source.jpg from your source photo / --source",
    )
    args = parser.parse_args()

    if args.refresh_vendor:
        master = args.source or (FERIENHAUS_MASTER if FERIENHAUS_MASTER.is_file() else None)
        if master is None:
            raise SystemExit("Need Ferienhaus gallery-forest.jpg or --source for --refresh-vendor")
        make_vendor_source(master)
        source = VENDOR_SOURCE
    else:
        source = _resolve_source(args.source)
        # First run: vendor a crop if we only have the external master
        if source == FERIENHAUS_MASTER and not VENDOR_SOURCE.is_file():
            source = make_vendor_source(source)

    print(f"source: {source}")
    photo = ImageOps.exif_transpose(Image.open(source).convert("RGB"))
    make_capture_samples(photo)
    make_maintenance(photo)
    make_offline(photo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
