#!/usr/bin/env python3
"""Build a timelapse GIF or animated PNG from history JPEG frames.

Works offline against the local outbox / data tree (or any folder of JPEGs).

Examples:
  # From local smoke outbox history
  python3 scripts/make-timelapse.py \\
    --input data/outbox/history/example/landscape \\
    --output data/timelapse/example-landscape.gif

  # APNG, every 2nd frame, max 240 frames, 200ms delay
  python3 scripts/make-timelapse.py \\
    --input data/outbox/history/example/landscape \\
    --output data/timelapse/day.png --format apng \\
    --stride 2 --max-frames 240 --delay-ms 200 --width 960
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image


def collect_frames(root: Path) -> list[Path]:
    files = sorted(root.rglob("*.jpg")) + sorted(root.rglob("*.jpeg"))
    # de-dupe while preserving order
    seen: set[Path] = set()
    out: list[Path] = []
    for p in files:
        rp = p.resolve()
        if rp in seen:
            continue
        seen.add(rp)
        out.append(p)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Make webcam timelapse GIF/APNG from history JPEGs")
    parser.add_argument("--input", "-i", required=True, type=Path, help="Directory of history JPEGs")
    parser.add_argument("--output", "-o", required=True, type=Path, help="Output .gif or .png")
    parser.add_argument("--format", choices=("gif", "apng", "auto"), default="auto")
    parser.add_argument("--delay-ms", type=int, default=150, help="Frame delay in milliseconds")
    parser.add_argument("--stride", type=int, default=1, help="Use every Nth frame")
    parser.add_argument("--max-frames", type=int, default=300, help="Cap frames (keeps Free/local CPU sane)")
    parser.add_argument("--width", type=int, default=0, help="Optional resize width (keep aspect)")
    parser.add_argument("--loop", type=int, default=0, help="GIF/APNG loop count (0 = forever)")
    args = parser.parse_args(argv)

    if not args.input.is_dir():
        print(f"input not a directory: {args.input}", file=sys.stderr)
        return 1

    paths = collect_frames(args.input)
    if args.stride > 1:
        paths = paths[:: args.stride]
    if args.max_frames > 0:
        paths = paths[: args.max_frames]
    if not paths:
        print(f"no JPEG frames under {args.input}", file=sys.stderr)
        return 1

    fmt = args.format
    if fmt == "auto":
        suffix = args.output.suffix.lower()
        fmt = "apng" if suffix == ".png" else "gif"

    print(f"loading {len(paths)} frames from {args.input} → {fmt}")
    frames: list[Image.Image] = []
    for p in paths:
        img = Image.open(p).convert("RGB")
        if args.width and img.width > args.width:
            ratio = args.width / img.width
            img = img.resize((args.width, max(1, int(img.height * ratio))), Image.Resampling.LANCZOS)
        frames.append(img)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    duration = max(20, int(args.delay_ms))

    if fmt == "gif":
        frames[0].save(
            args.output,
            save_all=True,
            append_images=frames[1:],
            duration=duration,
            loop=args.loop,
            optimize=True,
        )
    else:
        # APNG via Pillow PNG save_all
        frames[0].save(
            args.output,
            save_all=True,
            append_images=frames[1:],
            duration=duration,
            loop=args.loop,
            format="PNG",
        )

    size = args.output.stat().st_size
    print(f"wrote {args.output} ({size} bytes, {len(frames)} frames, {duration}ms)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
