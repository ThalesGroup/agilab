#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path

import imageio.v3 as iio
import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parents[1]
THALES_ROOT = ROOT.parent / "thales_agilab"

W = 1920
H = 1080
FPS = 24

BG = ImageColor.getrgb("#07111d")
BG_2 = ImageColor.getrgb("#0e1e34")
SURFACE = ImageColor.getrgb("#122033")
SURFACE_2 = ImageColor.getrgb("#182b42")
INK = ImageColor.getrgb("#edf3fb")
MUTED = ImageColor.getrgb("#9caec4")
LINE = ImageColor.getrgb("#324963")
WHITE = ImageColor.getrgb("#ffffff")

ACT_COLORS = {
    "DATA": ImageColor.getrgb("#5ca0ff"),
    "ML": ImageColor.getrgb("#ff8e45"),
    "RL": ImageColor.getrgb("#79d7a6"),
}

PAGE_SHOTS = ROOT / "docs/source/_static/page-shots"
DATA_IMAGE = PAGE_SHOTS / "project-page.png"
ML_IMAGE = ROOT / "artifacts/demo_media/meteo_forecast/agilab_meteo_forecast_poster.png"
RL_IMAGE = THALES_ROOT / "FCAS/figures/ppo_training_loop_2020x1369.png"


@dataclass(frozen=True)
class Scene:
    key: str
    lane: str
    app_name: str
    title: str
    subtitle: str
    image: Path
    evidence: tuple[str, ...]
    footer: str
    seconds: float
    accent: tuple[int, int, int]
    zoom_start: float = 1.0
    zoom_end: float = 1.04


SCENES: tuple[Scene, ...] = (
    Scene(
        key="intro",
        lane="DATA  ->  ML  ->  RL",
        app_name="THREE-PROJECT TECHNICAL DEMO",
        title="AGILAB can host data, ML, and RL workflows in one reproducible shell.",
        subtitle="Synthetic composite built from real AGILAB and FCAS assets.",
        image=PAGE_SHOTS / "core-pages-overview.png",
        evidence=("PROJECT", "ORCHESTRATE", "PIPELINE", "ANALYSIS"),
        footer="One shell, three workflow classes, one operator narrative.",
        seconds=2.4,
        accent=ImageColor.getrgb("#c8d7ea"),
        zoom_start=1.0,
        zoom_end=1.03,
    ),
    Scene(
        key="data",
        lane="DATA",
        app_name="execution_pandas_project",
        title="Data workflow",
        subtitle="Generate, partition, and rerun compute without dropping into ad-hoc shell glue.",
        image=DATA_IMAGE,
        evidence=("nfile", "rows_per_file", "partitioned output", "replayable step"),
        footer="Evidence: generated dataset artifact and reusable compute path.",
        seconds=4.2,
        accent=ACT_COLORS["DATA"],
    ),
    Scene(
        key="ml",
        lane="ML",
        app_name="meteo_forecast_project",
        title="ML workflow",
        subtitle="Run a real forecast path and end on metrics plus observed-vs-predicted evidence.",
        image=ML_IMAGE,
        evidence=("station", "lag / horizon", "MAE / RMSE / MAPE", "prediction curve"),
        footer="Evidence: real forecast metrics, not a notebook-only result.",
        seconds=4.5,
        accent=ACT_COLORS["ML"],
    ),
    Scene(
        key="rl",
        lane="RL",
        app_name="sb3_trainer_project",
        title="RL workflow",
        subtitle="Show a real trainer path and policy-learning context instead of a generic training claim.",
        image=RL_IMAGE,
        evidence=("PPO-GNN", "Path Actor-Critic", "training loop", "policy artifact"),
        footer="Evidence: trainer choice, learning loop, and policy-side proof.",
        seconds=4.6,
        accent=ACT_COLORS["RL"],
    ),
    Scene(
        key="closing",
        lane="DATA  ->  ML  ->  RL",
        app_name="AGILAB",
        title="One reproducible workflow shell for data, ML, and RL.",
        subtitle="Use the broad one-app reel for onboarding, and this composite for technical proof.",
        image=PAGE_SHOTS / "analysis-page.png",
        evidence=("execution_pandas_project", "meteo_forecast_project", "sb3_trainer_project"),
        footer="Composite technical explainer built for channels where one app is not enough.",
        seconds=2.8,
        accent=ImageColor.getrgb("#d4dde8"),
        zoom_start=1.0,
        zoom_end=1.02,
    ),
)


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * clamp01(t)


def ease_in_out(t: float) -> float:
    t = clamp01(t)
    return 0.5 - 0.5 * math.cos(math.pi * t)


def ease_out(t: float) -> float:
    t = clamp01(t)
    return 1.0 - (1.0 - t) ** 3


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates: list[tuple[str, int | None]] = [
        ("/System/Library/Fonts/Supplemental/Avenir Next.ttc", 1 if bold else 0),
        ("/System/Library/Fonts/HelveticaNeue.ttc", 1 if bold else 0),
        ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", None if bold else None),
        ("/System/Library/Fonts/Supplemental/Arial.ttf", None if not bold else None),
        ("/Library/Fonts/Arial.ttf", None),
    ]
    for path, index in candidates:
        if not Path(path).exists():
            continue
        try:
            if index is None:
                return ImageFont.truetype(path, size=size)
            return ImageFont.truetype(path, size=size, index=index)
        except Exception:
            continue
    return ImageFont.load_default()


FONT_BADGE = load_font(24, bold=True)
FONT_APP = load_font(28, bold=True)
FONT_TITLE = load_font(64, bold=True)
FONT_BODY = load_font(28)
FONT_CHIP = load_font(22, bold=True)
FONT_FOOTER = load_font(24, bold=True)


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


def background() -> Image.Image:
    img = Image.new("RGBA", (W, H), BG + (255,))
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for i in range(20):
        y0 = int(i * H / 20)
        y1 = int((i + 1) * H / 20)
        t = i / 19
        color = tuple(int(lerp(a, b, t)) for a, b in zip(BG, BG_2))
        draw.rectangle((0, y0, W, y1), fill=color + (255,))
    draw.ellipse((-280, -180, 660, 520), fill=(18, 42, 74, 150))
    draw.ellipse((1120, 420, 2100, 1320), fill=(9, 27, 48, 180))
    overlay = overlay.filter(ImageFilter.GaussianBlur(52))
    img.alpha_composite(overlay)
    grid = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(grid)
    for x in range(0, W, 96):
        gdraw.line((x, 0, x, H), fill=(255, 255, 255, 8), width=1)
    for y in range(0, H, 96):
        gdraw.line((0, y, W, y), fill=(255, 255, 255, 8), width=1)
    img.alpha_composite(grid)
    return img


def render_image_card(image_path: Path, t: float, zoom_start: float, zoom_end: float) -> Image.Image:
    image = Image.open(image_path).convert("RGB")
    width = 920
    height = 560
    scale = max(width / image.width, height / image.height) * lerp(zoom_start, zoom_end, ease_in_out(t))
    rw = int(image.width * scale)
    rh = int(image.height * scale)
    resized = image.resize((rw, rh), Image.Resampling.LANCZOS)
    left = max(0, (rw - width) // 2)
    top = max(0, (rh - height) // 2)
    card = resized.crop((left, top, left + width, top + height)).convert("RGBA")
    darkener = Image.new("RGBA", (width, height), (7, 13, 20, 52))
    card.alpha_composite(darkener)
    return card


def draw_chip(draw: ImageDraw.ImageDraw, x: int, y: int, text: str, accent: tuple[int, int, int]) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=FONT_CHIP)
    width = bbox[2] - bbox[0] + 34
    height = 42
    draw.rounded_rectangle((x, y, x + width, y + height), radius=18, fill=accent + (255,), outline=WHITE, width=2)
    draw.text((x + 17, y + 9), text, font=FONT_CHIP, fill=WHITE)
    return width, height


def lane_badges(draw: ImageDraw.ImageDraw, lane: str, accent: tuple[int, int, int], alpha: int) -> None:
    labels = [token.strip() for token in lane.split("->")]
    x = 110
    y = 88
    for idx, label in enumerate(labels):
        fill = ACT_COLORS.get(label, accent) if label in ACT_COLORS else accent
        bbox = draw.textbbox((0, 0), label, font=FONT_BADGE)
        width = bbox[2] - bbox[0] + 36
        draw.rounded_rectangle((x, y, x + width, y + 44), radius=18, fill=fill + (alpha,), outline=WHITE + (alpha,), width=2)
        draw.text((x + 18, y + 9), label, font=FONT_BADGE, fill=WHITE + (alpha,))
        x += width + 16


def render_scene(scene: Scene, t: float) -> Image.Image:
    frame = background()
    draw = ImageDraw.Draw(frame)

    entry = ease_out(min(1.0, t / 0.25))
    alpha = int(lerp(0, 255, entry))
    text_x = int(lerp(160, 110, entry))
    image_x = int(lerp(1040, 920, entry))
    image_y = int(lerp(190, 160, entry))

    lane_badges(draw, scene.lane, scene.accent, alpha)

    draw.text((text_x, 164), scene.app_name, font=FONT_APP, fill=scene.accent + (alpha,))
    title = wrap_text(draw, scene.title, FONT_TITLE, 660)
    subtitle = wrap_text(draw, scene.subtitle, FONT_BODY, 620)
    draw.multiline_text((text_x, 214), title, font=FONT_TITLE, fill=INK + (alpha,), spacing=4)
    title_box = draw.multiline_textbbox((text_x, 214), title, font=FONT_TITLE, spacing=4)
    subtitle_y = title_box[3] + 28
    draw.multiline_text((text_x, subtitle_y), subtitle, font=FONT_BODY, fill=MUTED + (alpha,), spacing=8)

    card_shadow = Image.new("RGBA", (980, 620), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(card_shadow)
    sdraw.rounded_rectangle((20, 20, 960, 600), radius=42, fill=(0, 0, 0, 95))
    card_shadow = card_shadow.filter(ImageFilter.GaussianBlur(14))
    frame.alpha_composite(card_shadow, (image_x - 30, image_y - 10))

    card = Image.new("RGBA", (920, 560), (0, 0, 0, 0))
    card.alpha_composite(render_image_card(scene.image, t, scene.zoom_start, scene.zoom_end))
    mask = Image.new("L", (920, 560), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, 919, 559), radius=34, fill=255)
    rounded = Image.new("RGBA", (920, 560), (0, 0, 0, 0))
    rounded.paste(card, (0, 0), mask)
    border = Image.new("RGBA", (920, 560), (0, 0, 0, 0))
    bdraw = ImageDraw.Draw(border)
    bdraw.rounded_rectangle((1, 1, 918, 558), radius=34, outline=WHITE + (60,), width=2)
    rounded.alpha_composite(border)
    frame.alpha_composite(rounded, (image_x, image_y))

    chips_y = max(subtitle_y + 180, 618)
    chips_x = text_x
    for idx, chip in enumerate(scene.evidence):
        width, _ = draw_chip(draw, chips_x, chips_y, chip, scene.accent)
        chips_x += width + 12
        if idx == 1:
            chips_x = text_x
            chips_y += 58

    footer_y = 972
    draw.rounded_rectangle((110, footer_y - 14, 1810, footer_y + 42), radius=22, fill=SURFACE_2 + (225,), outline=LINE, width=2)
    draw.text((960, footer_y + 2), scene.footer, font=FONT_FOOTER, fill=INK, anchor="mm")
    return frame.convert("RGB")


def build_animation(out_gif: Path, out_mp4: Path, out_poster: Path, fps: int = FPS) -> None:
    frames: list[np.ndarray] = []
    poster_frames: list[np.ndarray] = []
    for scene in SCENES:
        count = max(2, int(scene.seconds * fps))
        local = [np.array(render_scene(scene, idx / (count - 1))) for idx in range(count)]
        frames.extend(local)
        if scene.key == "closing":
            poster_frames = local

    out_gif.parent.mkdir(parents=True, exist_ok=True)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    out_poster.parent.mkdir(parents=True, exist_ok=True)
    iio.imwrite(out_gif, frames, duration=1000 / fps, loop=0)
    iio.imwrite(out_mp4, frames, fps=fps, codec="libx264", pixelformat="yuv420p", macro_block_size=1)
    if not poster_frames:
        poster_frames = [frames[-1]]
    poster_index = min(len(poster_frames) - 1, int(len(poster_frames) * 0.45))
    Image.fromarray(poster_frames[poster_index]).save(out_poster)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a synthetic AGILAB three-project technical demo reel.")
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
    parser.add_argument("--fps", type=int, default=FPS)
    args = parser.parse_args()

    build_animation(Path(args.gif), Path(args.mp4), Path(args.poster), fps=args.fps)
    print(Path(args.gif).resolve())
    print(Path(args.mp4).resolve())
    print(Path(args.poster).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
