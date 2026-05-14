#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageFont

from build_product_demo_reel import FPS, H, W, background, build as build_variant, load_font


ROOT = Path(__file__).resolve().parents[1]

INK = ImageColor.getrgb("#edf3fb")
MUTED = ImageColor.getrgb("#9eb0c5")
SURFACE = ImageColor.getrgb("#162538")
LINE = ImageColor.getrgb("#334763")
WHITE = ImageColor.getrgb("#ffffff")
DATA = ImageColor.getrgb("#5ca0ff")
ML = ImageColor.getrgb("#ff8e45")
RL = ImageColor.getrgb("#6ad3a8")

DEMO_SLUG = "agilab-mission-decision"
DEMO_FILE_STEM = "agilab_mission_decision"
MISSION_TITLE = "Mission Decision: Mission Data -> Decision Engine."
MISSION_SUBTITLE = (
    "AGILAB ingests mission signals, distributes computation, adapts to constraints, "
    "and returns an executable routing decision."
)
MISSION_OUTRO_TITLE = "From raw mission data to an optimized decision."
MISSION_OUTRO_SUBTITLE = (
    "Use this composite when the audience needs impact and execution: ingest data, "
    "predict constraints, optimize routing, inject failure, and show the new decision."
)
DEFAULT_OUTPUT_ROOT = Path("artifacts/demo_media") / DEMO_SLUG / "edited"
DEFAULT_GIF = str(DEFAULT_OUTPUT_ROOT / f"{DEMO_FILE_STEM}_synthetic.gif")
DEFAULT_MP4 = str(DEFAULT_OUTPUT_ROOT / f"{DEMO_FILE_STEM}_synthetic.mp4")
DEFAULT_POSTER = str(DEFAULT_OUTPUT_ROOT / f"{DEMO_FILE_STEM}_synthetic_poster.png")

FONT_BADGE = load_font(24, bold=True)
FONT_TITLE = load_font(68, bold=True)
FONT_BODY = load_font(30)
FONT_FOOTER = load_font(24, bold=True)
FONT_CHIP = load_font(22, bold=True)


def ffmpeg_bin() -> str:
    return shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> str:
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join(current + [word]).strip()
        if not candidate:
            continue
        bbox = draw.multiline_textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] <= max_width or not current:
            current.append(word)
        else:
            lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    return "\n".join(lines)


def render_card(
    *,
    title: str,
    subtitle: str,
    footer: str,
    chips: list[tuple[str, tuple[int, int, int]]],
    act_hint: str | None = None,
) -> Image.Image:
    img = background()
    draw = ImageDraw.Draw(img)

    x = 110
    y = 88
    for label, color in chips:
        bbox = draw.textbbox((0, 0), label, font=FONT_BADGE)
        width = bbox[2] - bbox[0] + 36
        draw.rounded_rectangle((x, y, x + width, y + 44), radius=18, fill=color + (255,), outline=WHITE, width=2)
        draw.text((x + 18, y + 9), label, font=FONT_BADGE, fill=WHITE)
        x += width + 16

    if act_hint:
        draw.text((110, 170), act_hint, font=FONT_BADGE, fill=ML)

    wrapped_title = wrap_text(draw, title, FONT_TITLE, 980)
    wrapped_subtitle = wrap_text(draw, subtitle, FONT_BODY, 900)
    draw.multiline_text((110, 220), wrapped_title, font=FONT_TITLE, fill=INK, spacing=6)
    title_bbox = draw.multiline_textbbox((110, 220), wrapped_title, font=FONT_TITLE, spacing=6)
    subtitle_y = title_bbox[3] + 28
    draw.multiline_text((110, subtitle_y), wrapped_subtitle, font=FONT_BODY, fill=MUTED, spacing=8)

    panel = (1080, 198, 1770, 770)
    px0, py0, px1, py1 = panel
    draw.rounded_rectangle(panel, radius=36, fill=SURFACE, outline=(255, 255, 255, 42), width=2)
    draw.text((px0 + 34, py0 + 34), "Decision flow", font=FONT_FOOTER, fill=INK)

    rails = [
        ("INGEST", "mission data ingestion", DATA),
        ("PREDICT", "constraint prediction", ML),
        ("DECIDE", "routing decision loop", RL),
    ]
    row_y = py0 + 112
    for label, name, color in rails:
        label_bbox = draw.textbbox((0, 0), label, font=FONT_BADGE)
        badge_width = max(126, label_bbox[2] - label_bbox[0] + 44)
        badge_x1 = px0 + 34 + badge_width
        draw.rounded_rectangle((px0 + 34, row_y, badge_x1, row_y + 42), radius=16, fill=color, outline=WHITE, width=2)
        draw.text((px0 + 34 + badge_width / 2, row_y + 21), label, font=FONT_BADGE, fill=WHITE, anchor="mm")
        name_x0 = badge_x1 + 20
        draw.rounded_rectangle((name_x0, row_y, px1 - 34, row_y + 42), radius=16, fill=(12, 28, 44), outline=LINE, width=2)
        draw.text((name_x0 + 24, row_y + 9), name, font=FONT_CHIP, fill=INK)
        row_y += 66

    draw.rounded_rectangle((px0 + 34, py1 - 92, px1 - 34, py1 - 34), radius=20, fill=(12, 28, 44), outline=LINE, width=2)
    draw.text((px0 + 60, py1 - 74), "PROJECT -> ORCHESTRATE -> WORKFLOW -> ANALYSIS", font=FONT_FOOTER, fill=INK)

    footer_y = 968
    draw.rounded_rectangle((110, footer_y - 14, 1810, footer_y + 42), radius=22, fill=SURFACE, outline=LINE, width=2)
    draw.text((960, footer_y + 2), footer, font=FONT_FOOTER, fill=INK, anchor="mm")
    return img.convert("RGB")


def write_loop_mp4(image: Image.Image, seconds: float, out_mp4: Path) -> None:
    ffmpeg = ffmpeg_bin()
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="agilab_demo_card_") as tmp:
        still = Path(tmp) / "card.png"
        image.save(still)
        cmd = [
            ffmpeg,
            "-y",
            "-loop",
            "1",
            "-framerate",
            str(FPS),
            "-t",
            f"{seconds:.3f}",
            "-i",
            str(still),
            "-c:v",
            "libx264",
            "-preset",
            "slow",
            "-crf",
            "15",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(out_mp4),
        ]
        subprocess.run(cmd, check=True)


def concat_mp4s(inputs: list[Path], out_mp4: Path) -> None:
    ffmpeg = ffmpeg_bin()
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="agilab_demo_concat_") as tmp:
        list_file = Path(tmp) / "concat.txt"
        list_file.write_text("".join(f"file '{p.resolve()}'\n" for p in inputs), encoding="utf-8")
        cmd = [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c",
            "copy",
            str(out_mp4),
        ]
        subprocess.run(cmd, check=True)


def build_gif(mp4: Path, gif: Path) -> None:
    ffmpeg = ffmpeg_bin()
    gif.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(mp4),
        "-vf",
        "fps=10,scale=1280:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse",
        str(gif),
    ]
    subprocess.run(cmd, check=True)


def build_three_project_demo(mp4: Path, gif: Path, poster: Path) -> None:
    intro = render_card(
        title=MISSION_TITLE,
        subtitle=MISSION_SUBTITLE,
        footer="Technical composite for mission-data audiences.",
        chips=[("INGEST", DATA), ("PREDICT", ML), ("DECIDE", RL)],
        act_hint="AUTONOMOUS DECISION DEMO",
    )
    outro = render_card(
        title=MISSION_OUTRO_TITLE,
        subtitle=MISSION_OUTRO_SUBTITLE,
        footer="ingest -> predict -> optimize -> adapt -> decide",
        chips=[("LATENCY", DATA), ("COST", ML), ("RELIABILITY", RL)],
        act_hint="CLOSING DECISION",
    )

    poster.parent.mkdir(parents=True, exist_ok=True)
    outro.save(poster)

    with tempfile.TemporaryDirectory(prefix="agilab_three_project_") as tmp:
        tmpdir = Path(tmp)
        intro_mp4 = tmpdir / "intro.mp4"
        data_mp4 = tmpdir / "data.mp4"
        ml_mp4 = tmpdir / "ml.mp4"
        rl_mp4 = tmpdir / "rl.mp4"
        outro_mp4 = tmpdir / "outro.mp4"

        write_loop_mp4(intro, 2.0, intro_mp4)
        build_variant(data_mp4, tmpdir / "data.gif", tmpdir / "data_poster.png", variant_key="execution_pandas")
        build_variant(ml_mp4, tmpdir / "ml.gif", tmpdir / "ml_poster.png", variant_key="meteo_forecast")
        build_variant(rl_mp4, tmpdir / "rl.gif", tmpdir / "rl_poster.png", variant_key="uav_queue")
        write_loop_mp4(outro, 2.4, outro_mp4)

        concat_mp4s([intro_mp4, data_mp4, ml_mp4, rl_mp4, outro_mp4], mp4)
        build_gif(mp4, gif)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the Mission Decision AGILAB autonomous decision demo reel.")
    parser.add_argument(
        "--gif",
        default=DEFAULT_GIF,
    )
    parser.add_argument(
        "--mp4",
        default=DEFAULT_MP4,
    )
    parser.add_argument(
        "--poster",
        default=DEFAULT_POSTER,
    )
    args = parser.parse_args()

    build_three_project_demo(Path(args.mp4), Path(args.gif), Path(args.poster))
    print(Path(args.gif).resolve())
    print(Path(args.mp4).resolve())
    print(Path(args.poster).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
