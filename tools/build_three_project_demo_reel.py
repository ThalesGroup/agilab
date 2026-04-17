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
    draw.text((px0 + 34, py0 + 34), "Act flow", font=FONT_FOOTER, fill=INK)

    rails = [
        ("DATA", "execution_pandas_project", DATA),
        ("ML", "meteo_forecast_project", ML),
        ("RL", "sb3_trainer_project", RL),
    ]
    row_y = py0 + 112
    for label, name, color in rails:
        draw.rounded_rectangle((px0 + 34, row_y, px0 + 138, row_y + 42), radius=16, fill=color, outline=WHITE, width=2)
        draw.text((px0 + 58, row_y + 9), label, font=FONT_BADGE, fill=WHITE)
        draw.rounded_rectangle((px0 + 158, row_y, px1 - 34, row_y + 42), radius=16, fill=(12, 28, 44), outline=LINE, width=2)
        draw.text((px0 + 182, row_y + 9), name, font=FONT_CHIP, fill=INK)
        row_y += 66

    draw.rounded_rectangle((px0 + 34, py1 - 92, px1 - 34, py1 - 34), radius=20, fill=(12, 28, 44), outline=LINE, width=2)
    draw.text((px0 + 60, py1 - 74), "PROJECT -> ORCHESTRATE -> PIPELINE -> ANALYSIS", font=FONT_FOOTER, fill=INK)

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
        title="AGILAB technical demo: data, ML, and RL in one reproducible shell.",
        subtitle="A consistent three-act reel built from the same AGILAB scene system, with RL evidence backed by FCAS routing assets.",
        footer="Technical composite for channels where one app is not enough.",
        chips=[("DATA", DATA), ("ML", ML), ("RL", RL)],
        act_hint="THREE-PROJECT DEMO",
    )
    outro = render_card(
        title="One shell. Three workflow classes. One reproducible operator story.",
        subtitle="Use the one-app reel for onboarding. Use this composite when the audience needs concrete data, ML, and RL proof in one video.",
        footer="execution_pandas_project -> meteo_forecast_project -> sb3_trainer_project",
        chips=[("DATA", DATA), ("ML", ML), ("RL", RL)],
        act_hint="CLOSING",
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
        build_variant(rl_mp4, tmpdir / "rl.gif", tmpdir / "rl_poster.png", variant_key="sb3_routing")
        write_loop_mp4(outro, 2.4, outro_mp4)

        concat_mp4s([intro_mp4, data_mp4, ml_mp4, rl_mp4, outro_mp4], mp4)
        build_gif(mp4, gif)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a consistent three-act AGILAB technical demo reel.")
    parser.add_argument(
        "--gif",
        default="artifacts/demo_media/agilab-data-ml-rl/edited/agilab_data_ml_rl_synthetic.gif",
    )
    parser.add_argument(
        "--mp4",
        default="artifacts/demo_media/agilab-data-ml-rl/edited/agilab_data_ml_rl_synthetic.mp4",
    )
    parser.add_argument(
        "--poster",
        default="artifacts/demo_media/agilab-data-ml-rl/edited/agilab_data_ml_rl_synthetic_poster.png",
    )
    args = parser.parse_args()

    build_three_project_demo(Path(args.mp4), Path(args.gif), Path(args.poster))
    print(Path(args.gif).resolve())
    print(Path(args.mp4).resolve())
    print(Path(args.poster).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
