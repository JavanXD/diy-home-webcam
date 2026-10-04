from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter

from shared.brand_overlay import (
    DEFAULT_OVERLAY_STROKE_WIDTH,
    DEFAULT_OVERLAY_SUPERSAMPLE,
    DEFAULT_TIMESTAMP_FORMAT,
    StatusCopy,
    cover_fit,
    draw_live_clock,
    draw_site_badge_on_image,
    draw_status_overlay,
    format_live_clock,
    format_site_badge,
    format_wall_clock,
    load_font,
    overlay_stroke_width,
    plain_status_background,
)

# Text-free Wartung slide (cover-fit + redraw glyphs at variant size).
_MAINTENANCE_BASE = (
    Path(__file__).resolve().parents[2] / "camera" / "app" / "assets" / "maintenance-base.jpg"
)


def format_burnin_timestamp(
    captured_at: float,
    timezone_name: str,
    fmt: str | None = None,
) -> str:
    """Format a Unix capture time in the camera timezone for image burn-in.

    Same canonical format as Wartung/Nacht ``format_live_clock`` /
    ``format_wall_clock`` (``DEFAULT_TIMESTAMP_FORMAT``).
    """
    return format_wall_clock(captured_at, tz_name=timezone_name, fmt=fmt)


@dataclass
class RenderedVariant:
    name: str
    visibility: str
    path: Path
    changed: bool
    r2_live_key: str | None = None
    r2_history_variant: str | None = None
    publish_enabled: bool = True


def _norm_box(crop: dict[str, Any], width: int, height: int) -> tuple[int, int, int, int]:
    """Compute crop box from YAML. Supports mode=full|centered|arbitrary, zoom, aspect_ratio."""
    mode = str(crop.get("mode") or "").lower()
    zoom = float(crop.get("zoom") or 1.0)
    zoom = max(1.0, zoom)

    # Infer mode if unset
    if not mode:
        if any(crop.get(k) is not None for k in ("left", "top", "right", "bottom")):
            mode = "arbitrary"
        elif crop.get("width_frac") or crop.get("height_frac") or zoom > 1.0:
            mode = "centered"
        else:
            mode = "full"

    def edge(val: Any, full: int, default: float) -> int:
        if val is None:
            return int(default * full)
        return int(float(val) * full)

    if mode == "full":
        left, top, right, bottom = 0, 0, width, height
    elif mode == "centered":
        wf = float(crop.get("width_frac") or 1.0) / zoom
        hf = float(crop.get("height_frac") or 1.0) / zoom
        wf = min(1.0, max(0.05, wf))
        hf = min(1.0, max(0.05, hf))
        cw, ch = int(width * wf), int(height * hf)
        left = (width - cw) // 2
        top = (height - ch) // 2
        right = left + cw
        bottom = top + ch
    else:  # arbitrary
        left = edge(crop.get("left"), width, 0.0)
        top = edge(crop.get("top"), height, 0.0)
        right = edge(crop.get("right"), width, 1.0)
        bottom = edge(crop.get("bottom"), height, 1.0)
        if zoom > 1.0:
            # Zoom into center of the arbitrary box
            bw, bh = right - left, bottom - top
            nw, nh = int(bw / zoom), int(bh / zoom)
            cx, cy = (left + right) // 2, (top + bottom) // 2
            left, top = cx - nw // 2, cy - nh // 2
            right, bottom = left + nw, top + nh

    # Optional aspect_ratio "W:H" — shrink box to fit ratio, centered within current box
    ar = crop.get("aspect_ratio")
    if ar:
        try:
            if isinstance(ar, (int, float)):
                ratio = float(ar)
            else:
                parts = str(ar).replace("/", ":").split(":")
                ratio = float(parts[0]) / float(parts[1])
            bw, bh = max(1, right - left), max(1, bottom - top)
            cur = bw / bh
            if cur > ratio:
                # too wide
                nw = int(bh * ratio)
                left = left + (bw - nw) // 2
                right = left + nw
            elif cur < ratio:
                nh = int(bw / ratio)
                top = top + (bh - nh) // 2
                bottom = top + nh
        except (ValueError, ZeroDivisionError, IndexError):
            pass

    left = max(0, min(left, width - 1))
    top = max(0, min(top, height - 1))
    right = max(left + 1, min(right, width))
    bottom = max(top + 1, min(bottom, height))
    return left, top, right, bottom


def _apply_artistic(img: Image.Image, artistic: dict[str, Any]) -> Image.Image:
    """Mild free-form looks (no heavy deps). Used for wide/artistic variants."""
    if not artistic:
        return img
    stretch = float(artistic.get("horizontal_stretch") or 1.0)
    if stretch != 1.0 and stretch > 0:
        stretch = min(1.25, max(0.85, stretch))
        img = img.resize(
            (max(1, int(img.width * stretch)), img.height),
            Image.Resampling.LANCZOS,
        )
    # Optional slight vertical compress for panoramic feel
    v = float(artistic.get("vertical_compress") or 1.0)
    if v != 1.0 and v > 0:
        v = min(1.0, max(0.85, v))
        img = img.resize(
            (img.width, max(1, int(img.height * v))),
            Image.Resampling.LANCZOS,
        )
    return img


def _apply_mask(img: Image.Image, mask: dict[str, Any]) -> None:
    w, h = img.size
    mode = mask.get("mode", "blur")
    strength = int(mask.get("strength", 12))
    mtype = mask.get("type", "rect")

    if mtype == "rect":
        box = _norm_box(mask, w, h)
        region = img.crop(box)
        region = _obscure(region, mode, strength)
        img.paste(region, box[:2])
        return

    if mtype == "polygon":
        points = mask.get("points") or []
        abs_points = [(int(float(x) * w), int(float(y) * h)) for x, y in points]
        if len(abs_points) < 3:
            return
        xs = [p[0] for p in abs_points]
        ys = [p[1] for p in abs_points]
        box = (min(xs), min(ys), max(xs), max(ys))
        region = img.crop(box)
        obscured = _obscure(region.copy(), mode, strength)
        poly_mask = Image.new("L", region.size, 0)
        draw = ImageDraw.Draw(poly_mask)
        local = [(x - box[0], y - box[1]) for x, y in abs_points]
        draw.polygon(local, fill=255)
        region = Image.composite(obscured, region, poly_mask)
        img.paste(region, box[:2])
        return


def _obscure(region: Image.Image, mode: str, strength: int) -> Image.Image:
    if mode == "pixelate":
        scale = max(2, strength)
        small = region.resize(
            (max(1, region.width // scale), max(1, region.height // scale)),
            Image.Resampling.BILINEAR,
        )
        return small.resize(region.size, Image.Resampling.NEAREST)
    # default blur
    radius = max(1, strength)
    return region.filter(ImageFilter.GaussianBlur(radius=radius))


def _draw_text(
    img: Image.Image,
    text: str,
    position: str,
    opacity: float,
    font_size: int,
    margin: int,
    stroke_width: int | None = None,
) -> None:
    """Live timestamp / watermark text with an even dark halo (matches site badge)."""
    if not text:
        return

    sw = overlay_stroke_width(stroke_width)
    font = load_font(font_size, bold=False)
    ss = DEFAULT_OVERLAY_SUPERSAMPLE
    alpha = int(max(0, min(1, opacity)) * 255)
    fill = (247, 243, 236, alpha)
    stroke_fill = (16, 24, 20, min(255, alpha + 40))  # stroke slightly more opaque

    big_font = load_font(font_size * ss, bold=False)
    big_sw = sw * ss
    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    bbox = scratch.textbbox((0, 0), text, font=big_font, stroke_width=big_sw)
    pad = max(2, big_sw + 2)
    tile_w = max(1, (bbox[2] - bbox[0]) + pad * 2)
    tile_h = max(1, (bbox[3] - bbox[1]) + pad * 2)
    tile = Image.new("RGBA", (tile_w, tile_h), (0, 0, 0, 0))
    tile_draw = ImageDraw.Draw(tile)
    ox, oy = pad - bbox[0], pad - bbox[1]
    if big_sw > 0:
        tile_draw.text(
            (ox, oy),
            text,
            font=big_font,
            fill=fill,
            stroke_width=big_sw,
            stroke_fill=stroke_fill,
        )
    else:
        tile_draw.text((ox, oy), text, font=big_font, fill=fill)
    out_w = max(1, (tile_w + ss - 1) // ss)
    out_h = max(1, (tile_h + ss - 1) // ss)
    small = tile.resize((out_w, out_h), Image.Resampling.LANCZOS)

    bbox1 = scratch.textbbox((0, 0), text, font=font, stroke_width=sw)
    tw, th = bbox1[2] - bbox1[0], bbox1[3] - bbox1[1]
    positions = {
        "bottom-right": (img.width - tw - margin, img.height - th - margin),
        "bottom-left": (margin, img.height - th - margin),
        "top-right": (img.width - tw - margin, margin),
        "top-left": (margin, margin),
    }
    xy = positions.get(position, positions["bottom-right"])
    dest = (xy[0] + bbox1[0] - (pad // ss), xy[1] + bbox1[1] - (pad // ss))
    rgba = img.convert("RGBA")
    rgba.alpha_composite(small, dest=dest)
    img.paste(rgba.convert("RGB"))


def _draw_logo(
    img: Image.Image,
    logo_path: Path,
    *,
    position: str = "bottom-right",
    opacity: float = 0.72,
    max_width_px: int | None = 160,
    max_width_frac: float | None = None,
    margin: int = 16,
) -> None:
    """Composite a PNG (with alpha) onto the image. Free-plan safe — runs on LAN pipeline."""
    if not logo_path.exists():
        raise FileNotFoundError(f"logo not found: {logo_path}")
    logo = Image.open(logo_path).convert("RGBA")
    target_w = max_width_px
    if max_width_frac is not None:
        target_w = max(1, int(img.width * float(max_width_frac)))
    if target_w and logo.width > target_w:
        ratio = target_w / logo.width
        logo = logo.resize(
            (target_w, max(1, int(logo.height * ratio))),
            Image.Resampling.LANCZOS,
        )
    if opacity < 1.0:
        r, g, b, a = logo.split()
        a = a.point(lambda p: int(p * max(0.0, min(1.0, opacity))))
        logo = Image.merge("RGBA", (r, g, b, a))

    lw, lh = logo.size
    positions = {
        "bottom-right": (img.width - lw - margin, img.height - lh - margin),
        "bottom-left": (margin, img.height - lh - margin),
        "top-right": (img.width - lw - margin, margin),
        "top-left": (margin, margin),
    }
    xy = positions.get(position, positions["bottom-right"])
    base = img.convert("RGBA")
    base.alpha_composite(logo, dest=xy)
    img.paste(base.convert("RGB"))


def _resolve_logo_path(image_path: str | None, repo_root: Path | None) -> Path | None:
    if not image_path:
        return None
    path = Path(image_path)
    if path.is_absolute():
        return path
    if repo_root is not None:
        return (repo_root / path).resolve()
    return path.resolve()


def _site_badge_text(
    variant: dict[str, Any],
    *,
    temp_c: float | None = None,
) -> str | None:
    """Build public top-left micro label when site_badge.enabled."""
    cfg = variant.get("site_badge") or {}
    if not cfg.get("enabled"):
        return None
    site = str(cfg.get("site") or "").strip()
    if not site:
        return None
    include_temp = cfg.get("temperature", True)
    return format_site_badge(site, temp_c if include_temp else None)


def _output_size(variant: dict[str, Any]) -> tuple[int | None, int | None]:
    out = variant.get("output") or {}
    width, height = out.get("width"), out.get("height")
    if width and not height and out.get("aspect_ratio"):
        try:
            parts = str(out["aspect_ratio"]).replace("/", ":").split(":")
            ratio = float(parts[0]) / float(parts[1])
            height = int(int(width) / ratio)
        except (ValueError, ZeroDivisionError, IndexError):
            height = None
    return (
        int(width) if width else None,
        int(height) if height else None,
    )


def _maintenance_base_path(repo_root: Path | None) -> Path | None:
    """Text-free Wartung background, if present."""
    candidates: list[Path] = []
    if repo_root is not None:
        candidates.append(repo_root / "pi/camera/app/assets/maintenance-base.jpg")
    candidates.append(_MAINTENANCE_BASE)
    for path in candidates:
        if path.is_file():
            return path
    return None


def render_one(
    original: Image.Image,
    variant: dict[str, Any],
    captured_at: float,
    timezone_name: str,
    *,
    repo_root: Path | None = None,
    temp_c: float | None = None,
    maintenance: bool = False,
    brand: str = "Webcam",
    status: StatusCopy | None = None,
) -> Image.Image:
    width, height = _output_size(variant)
    copy = status or StatusCopy.english()

    if maintenance and width and height:
        # Cover-fit the photo, then draw the words at output pixels.
        # No photo installed → a plain dark slide (a copied project deletes
        # shipped forest placeholder assets).
        base_path = _maintenance_base_path(repo_root)
        if base_path is not None:
            photo = Image.open(base_path).convert("RGB")
            img = cover_fit(photo, (width, height))
        else:
            img = plain_status_background((width, height))
        draw_status_overlay(
            ImageDraw.Draw(img),
            width=width,
            height=height,
            title=copy.maintenance_title,
            body=copy.maintenance_body,
            brand=brand or "Webcam",
        )
        # Wall clock (not frozen capture time) — proves public live is still updating.
        ts_cfg = variant.get("timestamp") or {}
        draw_live_clock(
            ImageDraw.Draw(img),
            text=format_live_clock(tz_name=timezone_name),
            width=img.width,
            height=img.height,
            margin=int(ts_cfg["margin"]) if ts_cfg.get("margin") is not None else None,
            font_size=int(ts_cfg["font_size"]) if ts_cfg.get("font_size") is not None else None,
            stroke_width=int(ts_cfg["stroke_width"])
            if ts_cfg.get("stroke_width") is not None
            else None,
        )
    else:
        crop = variant.get("crop") or {}
        box = _norm_box(crop, original.width, original.height)
        img = original.crop(box).copy()

        artistic = variant.get("artistic") or {}
        img = _apply_artistic(img, artistic)

        for mask in (variant.get("privacy") or {}).get("masks") or []:
            _apply_mask(img, mask)

        # Cover-fit into output WxH — never anisotropic stretch (same class of bug as
        # Wartung glyphs: crop AR ≠ output AR used to squash circles / text).
        # Optional artistic.* may still distort intentionally before this step.
        if width and height:
            img = cover_fit(img, (width, height))

        ts_cfg = variant.get("timestamp") or {}
        if ts_cfg.get("enabled"):
            text = format_burnin_timestamp(
                captured_at,
                timezone_name,
                ts_cfg.get("format") or DEFAULT_TIMESTAMP_FORMAT,
            )
            _draw_text(
                img,
                text,
                ts_cfg.get("position", "bottom-left"),
                float(ts_cfg.get("opacity", 0.85)),
                int(ts_cfg.get("font_size", 24)),
                int(ts_cfg.get("margin", 28)),
                int(ts_cfg["stroke_width"])
                if ts_cfg.get("stroke_width") is not None
                else DEFAULT_OVERLAY_STROKE_WIDTH,
            )

    wm = variant.get("watermark") or {}
    if wm.get("enabled"):
        logo_path = _resolve_logo_path(wm.get("image"), repo_root)
        if logo_path is not None:
            _draw_logo(
                img,
                logo_path,
                position=str(wm.get("position") or "bottom-right"),
                opacity=float(wm.get("opacity", 0.72)),
                max_width_px=int(wm["max_width_px"]) if wm.get("max_width_px") is not None else None,
                max_width_frac=float(wm["max_width_frac"]) if wm.get("max_width_frac") is not None else None,
                margin=int(wm.get("margin", 16)),
            )
        text = str(wm.get("text") or "")
        if text:
            # If both logo + text: put text on bottom-left by default when logo is bottom-right
            text_pos = wm.get("text_position") or (
                "bottom-left" if logo_path is not None and wm.get("position", "bottom-right") == "bottom-right" else wm.get("position", "bottom-right")
            )
            _draw_text(
                img,
                text,
                str(text_pos),
                float(wm.get("text_opacity", wm.get("opacity", 0.5))),
                int(wm.get("font_size", 24)),
                int(wm.get("margin", 16)),
            )

    badge = _site_badge_text(variant, temp_c=temp_c)
    if badge:
        badge_cfg = variant.get("site_badge") or {}
        img = draw_site_badge_on_image(
            img,
            badge,
            margin=int(badge_cfg["margin"]) if badge_cfg.get("margin") is not None else None,
            font_size=int(badge_cfg["font_size"]) if badge_cfg.get("font_size") is not None else None,
            stroke_width=int(badge_cfg["stroke_width"])
            if badge_cfg.get("stroke_width") is not None
            else None,
        )
    return img


def render_variants(
    *,
    original_path: Path,
    source_sha: str,
    captured_at: float,
    timezone_name: str,
    variant_configs: list[dict[str, Any]],
    variants_dir: Path,
    force: bool = False,
    repo_root: Path | None = None,
    temp_c: float | None = None,
    maintenance: bool = False,
    brand: str = "Webcam",
    status: StatusCopy | None = None,
) -> list[RenderedVariant]:
    variants_dir.mkdir(parents=True, exist_ok=True)
    cache_path = variants_dir / ".render-cache.json"
    cache: dict[str, Any] = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            cache = {}

    original = Image.open(original_path).convert("RGB")
    results: list[RenderedVariant] = []

    for variant in variant_configs:
        name = str(variant.get("name") or "unnamed")
        visibility = str(variant.get("visibility") or "private").strip().lower()
        out = variant.get("output") or {}
        filename = out.get("filename") or f"{name}.jpg"
        dest = variants_dir / filename
        prev = cache.get(name) or {}
        badge = _site_badge_text(variant, temp_c=temp_c) or ""
        badge_cfg = variant.get("site_badge") or {}
        badge_style = {
            "font_size": badge_cfg.get("font_size"),
            "margin": badge_cfg.get("margin"),
            "stroke_width": badge_cfg.get("stroke_width"),
        }
        ts_cfg = variant.get("timestamp") or {}
        ts_style = {
            "font_size": ts_cfg.get("font_size"),
            "margin": ts_cfg.get("margin"),
            "stroke_width": ts_cfg.get("stroke_width"),
            "opacity": ts_cfg.get("opacity"),
            "position": ts_cfg.get("position"),
            "enabled": ts_cfg.get("enabled"),
        }
        # Private (HA) always renders from the raw original — never Wartungsbild.
        # Public variants use Wartung only when maintenance is on (schedule may
        # still replace the published live key with the night placeholder).
        use_maint = bool(maintenance) and visibility == "public"
        # Minute-granularity wall clock — refresh Wartung frames at least every minute.
        live_clock = format_live_clock(tz_name=timezone_name) if use_maint else ""
        status_fp = ""
        if use_maint:
            shown = status or StatusCopy.english()
            status_fp = shown.maintenance_title + "\n" + shown.maintenance_body
        needs = (
            force
            or prev.get("source_sha") != source_sha
            or prev.get("site_badge") != badge
            or prev.get("site_badge_style") != badge_style
            or prev.get("timestamp_style") != ts_style
            or prev.get("maintenance") != use_maint
            or (use_maint and prev.get("live_clock") != live_clock)
            or (use_maint and prev.get("status_text") != status_fp)
            or not dest.exists()
        )

        if needs:
            img = render_one(
                original,
                variant,
                captured_at,
                timezone_name,
                repo_root=repo_root,
                temp_c=temp_c,
                maintenance=use_maint,
                brand=brand,
                status=status,
            )
            quality = int(out.get("jpeg_quality", 85))
            tmp = dest.with_suffix(dest.suffix + ".tmp")
            img.save(tmp, "JPEG", quality=quality, optimize=True)
            tmp.replace(dest)
            cache[name] = {
                "source_sha": source_sha,
                "path": str(dest),
                "rendered_at": time.time(),
                "visibility": visibility,
                "site_badge": badge,
                "site_badge_style": badge_style,
                "timestamp_style": ts_style,
                "maintenance": use_maint,
                "live_clock": live_clock,
                "status_text": status_fp,
            }
            changed = True
        else:
            changed = False

        results.append(
            RenderedVariant(
                name=name,
                visibility=visibility,
                path=dest,
                changed=changed,
                r2_live_key=out.get("r2_live_key") or None,
                r2_history_variant=out.get("r2_history_variant") or name,
                publish_enabled=bool(variant.get("publish", True)) and visibility == "public",
            )
        )

    cache_path.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    return results
