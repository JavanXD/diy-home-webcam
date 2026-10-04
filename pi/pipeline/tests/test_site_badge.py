"""Public site badge + weather helpers."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(ROOT))

from app.render import render_one, render_variants  # noqa: E402
from app.weather import WeatherCache  # noqa: E402
from shared.brand_overlay import (  # noqa: E402
    StatusCopy,
    format_live_clock,
    format_site_badge,
    format_temp_c_de,
)


def test_format_temp_german():
    assert format_temp_c_de(12.4) == "12,4 °C"
    assert format_temp_c_de(17.0) == "17,0 °C"
    assert format_temp_c_de(-1.25) == "-1,2 °C"


def test_format_site_badge():
    assert format_site_badge("ferienpark-schellbronn.de") == "ferienpark-schellbronn.de"
    assert (
        format_site_badge("ferienpark-schellbronn.de", 12.4)
        == "ferienpark-schellbronn.de  ·  12,4 °C"
    )


def test_format_live_clock():
    dt = datetime(2026, 9, 30, 9, 15, tzinfo=ZoneInfo("Europe/Berlin"))
    assert format_live_clock(dt) == "2026-09-30 09:15"
    assert format_live_clock(dt.timestamp(), tz_name="Europe/Berlin") == "2026-09-30 09:15"


def test_overlay_corner_pad_default_larger_than_legacy():
    from shared.brand_overlay import DEFAULT_OVERLAY_MARGIN, overlay_corner_pad

    assert DEFAULT_OVERLAY_MARGIN == 28
    # Explicit margin wins.
    assert overlay_corner_pad(1080, 14) == 14
    # Default floor is higher than the old ≈12–16px inset.
    assert overlay_corner_pad(1080) == 28
    assert overlay_corner_pad(900) >= 24
    assert overlay_corner_pad(450) >= 24


def test_draw_halo_text_even_outline_not_offset_shadow():
    """Badge/clock use Pillow stroke (even halo), not a bottom-right-biased drop shadow."""
    from shared.brand_overlay import (
        DEFAULT_OVERLAY_FONT_SIZE,
        DEFAULT_OVERLAY_STROKE_WIDTH,
        VEIL,
        draw_halo_text,
        draw_site_badge,
        load_font,
        overlay_font_size,
    )

    assert DEFAULT_OVERLAY_FONT_SIZE == 26
    assert DEFAULT_OVERLAY_STROKE_WIDTH == 2
    assert overlay_font_size(1080) == 26
    assert overlay_font_size(900, 26) == 26

    # On a bright field, stroke places dark ink above/left of the fill — not only SE.
    img = Image.new("RGB", (400, 120), (220, 230, 240))
    draw = ImageDraw.Draw(img)
    font = load_font(36, bold=False)
    x, y = 60, 40
    draw_halo_text(draw, (x, y), "H", font, stroke_width=3)
    bbox = draw.textbbox((x, y), "H", font=font, stroke_width=3)
    # Scan a thin band just outside the fill toward the top-left of the glyph box.
    dark = 0
    for py in range(bbox[1], min(bbox[1] + 6, bbox[3])):
        for px in range(bbox[0], min(bbox[0] + 6, bbox[2])):
            r, g, b = img.getpixel((px, py))
            if r < 80 and g < 80 and b < 80:
                dark += 1
    assert dark >= 3, "expected dark stroke pixels near top-left of glyph"
    # Stroke color is VEIL-ish (near-black green), not a pure offset clone of fill.
    assert VEIL[0] < 40

    badge_img = Image.new("RGB", (800, 450), (40, 80, 120))
    draw_site_badge(
        ImageDraw.Draw(badge_img),
        text="example.com",
        width=800,
        height=450,
        font_size=26,
        stroke_width=2,
        margin=28,
    )
    # Cream fill and dark stroke both present near the top-left pad.
    creamish = darkish = 0
    for py in range(24, 56):
        for px in range(24, 220):
            r, g, b = badge_img.getpixel((px, py))
            if r > 200 and g > 190 and b > 180:
                creamish += 1
            if r < 40 and g < 40 and b < 40:
                darkish += 1
    assert creamish >= 20, f"expected cream fill pixels, got {creamish}"
    assert darkish >= 20, f"expected dark stroke pixels, got {darkish}"


def test_validate_site_badge_stroke_width():
    from app.variants_editor import validate_site_badge, validate_timestamp
    import pytest

    assert validate_site_badge({"stroke_width": 2})["stroke_width"] == 2
    assert validate_timestamp({"stroke_width": 0})["stroke_width"] == 0
    with pytest.raises(ValueError, match="stroke_width"):
        validate_site_badge({"stroke_width": 99})


def test_weather_cache_parses_and_fails_soft(tmp_path: Path):
    payload = json.dumps(
        {"current": {"temp_c": 12.4, "recorded_at": "2026-09-29T12:00:00Z"}}
    ).encode()

    class _Resp:
        def read(self):
            return payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    cache = WeatherCache(url="https://example.test/api/weather", ttl_seconds=60)
    with patch("urllib.request.urlopen", return_value=_Resp()):
        snap = cache.get(force=True)
    assert snap.temp_c == 12.4
    assert snap.source == "live"

    with patch("urllib.request.urlopen", side_effect=OSError("down")):
        stale = cache.get(force=True)
    assert stale.temp_c == 12.4
    assert stale.source == "stale"

    empty = WeatherCache(url="https://example.test/api/weather", ttl_seconds=60)
    with patch("urllib.request.urlopen", side_effect=OSError("down")):
        none = empty.get(force=True)
    assert none.temp_c is None
    assert none.source == "none"


def test_render_one_maintenance_no_anisotropic_stretch():
    """Wartung glyphs must not go through live crop + non-uniform resize."""
    from shared.brand_overlay import compose_slide_background

    photo = Image.new("RGB", (1920, 1080), (30, 60, 40))
    base = compose_slide_background(photo, (1920, 1080))
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        asset = root / "pi/camera/app/assets/maintenance-base.jpg"
        asset.parent.mkdir(parents=True)
        base.save(asset, quality=90)
        variant = {
            "name": "landscape",
            "visibility": "public",
            "crop": {"mode": "arbitrary", "left": 0.05, "top": 0.0, "right": 0.95, "bottom": 0.75},
            "artistic": {"horizontal_stretch": 1.06},
            "output": {"width": 1600, "height": 900},
            "site_badge": {
                "enabled": True,
                "site": "ferienpark-schellbronn.de",
                "font_size": 22,
                "margin": 28,
            },
            "watermark": {"enabled": False},
            "timestamp": {"enabled": True},
        }
        live = render_one(
            base, variant, 1_700_000_000, "Europe/Berlin", repo_root=root, temp_c=12.4
        )
        fixed = render_one(
            base,
            variant,
            1_700_000_000,
            "Europe/Berlin",
            repo_root=root,
            temp_c=12.4,
            maintenance=True,
            status=StatusCopy.german(),
        )
        assert fixed.size == (1600, 900)
        assert live.size == (1600, 900)
        # Maintenance bypasses crop/artistic — different pixels than live path.
        assert fixed.tobytes() != live.tobytes()
        # Title band (cream serif) should lighten the dimmed forest mid-upper area.
        title_y = int(900 * 0.28)
        assert sum(fixed.getpixel((800, title_y))) > sum(fixed.getpixel((800, 700)))
        # Bottom-left wall-clock burn-in (not the frozen capture timestamp).
        with patch("app.render.format_live_clock", return_value="2026-09-30 09:15"):
            a = render_one(
                base,
                variant,
                1_700_000_000,
                "Europe/Berlin",
                repo_root=root,
                temp_c=12.4,
                maintenance=True,
            )
        with patch("app.render.format_live_clock", return_value="2026-09-30 21:45"):
            b = render_one(
                base,
                variant,
                1_700_000_000,
                "Europe/Berlin",
                repo_root=root,
                temp_c=12.4,
                maintenance=True,
            )
        assert a.tobytes() != b.tobytes()
        assert a.size == (1600, 900)


def test_render_one_live_cover_fit_no_anisotropic_stretch():
    """Live path must cover-fit into output WxH — never squash a circle into an oval."""
    # Checker: red circle on blue so stretch would distort the bounding box.
    original = Image.new("RGB", (2000, 1500), (20, 40, 180))  # 4:3
    draw = ImageDraw.Draw(original)
    # Perfect circle in the upper portion (landscape crop region).
    draw.ellipse((700, 100, 1300, 700), fill=(220, 40, 40))
    variant = {
        "name": "landscape",
        "visibility": "public",
        # Crop AR ≈ 16:10 into 16:9 output — old path stretched ~11% vertically.
        "crop": {
            "mode": "arbitrary",
            "left": 0.05,
            "top": 0.0,
            "right": 0.95,
            "bottom": 0.75,
        },
        "output": {"width": 1600, "height": 900},
        "watermark": {"enabled": False},
        "timestamp": {"enabled": False},
        "site_badge": {"enabled": False},
    }
    out = render_one(original, variant, 1_700_000_000, "Europe/Berlin")
    assert out.size == (1600, 900)
    # Sample red pixels: find bbox of red-ish region; width≈height within tolerance.
    xs, ys = [], []
    for y in range(0, 900, 4):
        for x in range(0, 1600, 4):
            r, g, b = out.getpixel((x, y))
            if r > 180 and g < 80 and b < 80:
                xs.append(x)
                ys.append(y)
    assert xs and ys, "expected red circle pixels in output"
    bw, bh = max(xs) - min(xs), max(ys) - min(ys)
    # Cover-fit keeps circle; anisotropic stretch would make bh/bw differ by ~11%+.
    ratio = bw / max(1, bh)
    assert 0.92 <= ratio <= 1.08, f"circle bbox stretched: {bw}×{bh} ratio={ratio:.3f}"


def test_render_variants_maintenance_clock_minute_busts_cache(tmp_path: Path):
    """Wartung frames must rebuild when the wall-clock minute changes."""
    from shared.brand_overlay import compose_slide_background

    photo = compose_slide_background(Image.new("RGB", (800, 450), (20, 40, 30)), (800, 450))
    original = tmp_path / "original.jpg"
    photo.save(original, quality=90)
    asset = tmp_path / "pi/camera/app/assets/maintenance-base.jpg"
    asset.parent.mkdir(parents=True)
    photo.save(asset, quality=90)
    variants_dir = tmp_path / "variants"
    variant = {
        "name": "landscape",
        "visibility": "public",
        "crop": {"mode": "full"},
        "output": {"width": 400, "height": 225, "filename": "landscape.jpg"},
        "site_badge": {"enabled": True, "site": "ferienpark-schellbronn.de"},
        "watermark": {"enabled": False},
        "timestamp": {"enabled": False},
        "publish": True,
    }
    with patch("app.render.format_live_clock", return_value="2026-09-30 09:15"):
        first = render_variants(
            original_path=original,
            source_sha="abc",
            captured_at=1_700_000_000,
            timezone_name="Europe/Berlin",
            variant_configs=[variant],
            variants_dir=variants_dir,
            repo_root=tmp_path,
            temp_c=12.4,
            maintenance=True,
        )
    assert first[0].changed is True
    with patch("app.render.format_live_clock", return_value="2026-09-30 09:15"):
        same = render_variants(
            original_path=original,
            source_sha="abc",
            captured_at=1_700_000_000,
            timezone_name="Europe/Berlin",
            variant_configs=[variant],
            variants_dir=variants_dir,
            repo_root=tmp_path,
            temp_c=12.4,
            maintenance=True,
        )
    assert same[0].changed is False
    with patch("app.render.format_live_clock", return_value="2026-09-30 09:16"):
        next_min = render_variants(
            original_path=original,
            source_sha="abc",
            captured_at=1_700_000_000,
            timezone_name="Europe/Berlin",
            variant_configs=[variant],
            variants_dir=variants_dir,
            repo_root=tmp_path,
            temp_c=12.4,
            maintenance=True,
        )
    assert next_min[0].changed is True


def test_render_one_site_badge_public_only():
    original = Image.new("RGB", (800, 450), (40, 80, 120))
    public = {
        "name": "landscape",
        "visibility": "public",
        "crop": {"mode": "full"},
        "output": {"width": 400, "height": 225},
        "site_badge": {"enabled": True, "site": "ferienpark-schellbronn.de"},
        "watermark": {"enabled": False},
        "timestamp": {"enabled": False},
    }
    private = {
        "name": "private",
        "visibility": "private",
        "crop": {"mode": "full"},
        "output": {"width": 400, "height": 225},
        "watermark": {"enabled": False},
        "timestamp": {"enabled": False},
    }
    pub_img = render_one(original, public, 1_700_000_000, "Europe/Berlin", temp_c=12.4)
    priv_img = render_one(original, private, 1_700_000_000, "Europe/Berlin", temp_c=12.4)
    # Glyph ink sits near the shared overlay pad (~24–28px); cream ≈ brand crème.
    assert pub_img.getpixel((32, 32)) != (40, 80, 120)
    assert priv_img.getpixel((32, 32)) == (40, 80, 120)
    assert pub_img.tobytes() != priv_img.tobytes()
