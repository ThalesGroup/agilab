#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path


def build_crop_filter(crop: str | None) -> str:
    if not crop:
        return ""
    parts = crop.split(":")
    if len(parts) != 4 or not all(part.strip() for part in parts):
        raise ValueError("--crop must be x:y:w:h")
    x, y, w, h = parts
    return f"crop={w}:{h}:{x}:{y},"


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export an AGILAB screen recording to shareable MP4 and GIF assets."
    )
    parser.add_argument("--input", required=True, help="Source screen recording file, typically a .mov")
    parser.add_argument("--mp4", help="Output MP4 path")
    parser.add_argument("--gif", help="Output GIF path")
    parser.add_argument("--start", type=float, default=0.0, help="Trim start in seconds")
    parser.add_argument("--duration", type=float, help="Trim duration in seconds")
    parser.add_argument("--crop", help="Crop rectangle as x:y:w:h")
    parser.add_argument("--mp4-width", type=int, default=1280, help="Target width for MP4 export")
    parser.add_argument("--gif-width", type=int, default=960, help="Target width for GIF export")
    parser.add_argument("--gif-fps", type=int, default=10, help="Target GIF frame rate")
    parser.add_argument("--crf", type=int, default=22, help="H.264 quality factor for MP4 export")
    parser.add_argument("--print-only", action="store_true", help="Show ffmpeg commands without running them")
    args = parser.parse_args()

    src = Path(args.input).expanduser().resolve()
    if not src.exists():
        raise SystemExit(f"Input file not found: {src}")

    stem = src.with_suffix("")
    mp4_path = Path(args.mp4).expanduser().resolve() if args.mp4 else stem.with_suffix(".mp4")
    gif_path = Path(args.gif).expanduser().resolve() if args.gif else stem.with_suffix(".gif")
    mp4_path.parent.mkdir(parents=True, exist_ok=True)
    gif_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        import imageio_ffmpeg  # type: ignore
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Missing dependency: imageio-ffmpeg. Run this script with:\n"
            "  uv --preview-features extra-build-dependencies run --with imageio-ffmpeg "
            f"python {Path(__file__).name} ..."
        ) from exc

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    crop_filter = build_crop_filter(args.crop)
    trim_args: list[str] = []
    if args.start > 0:
        trim_args += ["-ss", f"{args.start:g}"]
    if args.duration is not None:
        trim_args += ["-t", f"{args.duration:g}"]

    mp4_filter = f"{crop_filter}scale={args.mp4_width}:-2:flags=lanczos"
    gif_filter = (
        f"{crop_filter}fps={args.gif_fps},scale={args.gif_width}:-1:flags=lanczos,"
        "split[s0][s1];[s0]palettegen=max_colors=256[p];[s1][p]paletteuse=dither=bayer:bayer_scale=3"
    )

    mp4_cmd = [
        ffmpeg,
        "-y",
        *trim_args,
        "-i",
        str(src),
        "-vf",
        mp4_filter,
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "slow",
        "-crf",
        str(args.crf),
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(mp4_path),
    ]

    gif_cmd = [
        ffmpeg,
        "-y",
        *trim_args,
        "-i",
        str(src),
        "-filter_complex",
        gif_filter,
        "-loop",
        "0",
        str(gif_path),
    ]

    print("MP4 command:")
    print("  " + shlex.join(mp4_cmd))
    print("GIF command:")
    print("  " + shlex.join(gif_cmd))

    if args.print_only:
        return 0

    run(mp4_cmd)
    run(gif_cmd)
    print(f"Wrote {mp4_path}")
    print(f"Wrote {gif_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
