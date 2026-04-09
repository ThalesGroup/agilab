#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageFont


W = 1920
H = 1080
FPS = 30

ROOT = Path(__file__).resolve().parents[1]
PAGE_SHOTS = ROOT / "docs/source/_static/page-shots"

BG = ImageColor.getrgb("#07111d")
BG_2 = ImageColor.getrgb("#0d1b2f")
BG_3 = ImageColor.getrgb("#102543")
SURFACE = ImageColor.getrgb("#111b29")
SURFACE_2 = ImageColor.getrgb("#162538")
INK = ImageColor.getrgb("#edf3fb")
MUTED = ImageColor.getrgb("#9eb0c5")
LINE = ImageColor.getrgb("#334763")
ACCENT = ImageColor.getrgb("#5ca0ff")
ACCENT_WARM = ImageColor.getrgb("#ff8e45")
GREEN = ImageColor.getrgb("#6ad3a8")
WHITE = ImageColor.getrgb("#ffffff")

CARD_X = 760
CARD_Y = 150
CARD_W = 1040
CARD_H = 640
DIAGRAMS = ROOT / "docs/source/diagrams"


@dataclass(frozen=True)
class Scene:
    name: str
    image: Path
    stage: str
    title: str
    body: str
    seconds: float
    active_step: int
    focus: tuple[float, float]
    zoom_start: float
    zoom_end: float
    highlight: tuple[float, float, float, float] | None = None
    highlight_label: str | None = None
    footer: str = "flight_project"
    overlay: str | None = None


@dataclass(frozen=True)
class Variant:
    key: str
    app_badge: str
    scenes: tuple[Scene, ...]


FLIGHT_SCENES: tuple[Scene, ...] = (
    Scene(
        name="intro",
        image=PAGE_SHOTS / "core-pages-overview.png",
        stage="AGILAB",
        title="From project to evidence.",
        body="One workspace keeps setup, execution, replay, and analysis aligned.",
        seconds=2.2,
        active_step=-1,
        focus=(0.56, 0.52),
        zoom_start=1.0,
        zoom_end=1.05,
        highlight=None,
        highlight_label=None,
    ),
    Scene(
        name="project",
        image=PAGE_SHOTS / "project-page.png",
        stage="PROJECT",
        title="Select the app once.",
        body="Keep project files, arguments, and code context in one place.",
        seconds=2.8,
        active_step=0,
        focus=(0.54, 0.46),
        zoom_start=1.0,
        zoom_end=1.04,
        highlight=(0.01, 0.43, 0.18, 0.67),
        highlight_label="App context",
    ),
    Scene(
        name="orchestrate",
        image=PAGE_SHOTS / "orchestrate-page.png",
        stage="ORCHESTRATE",
        title="Generate the run path.",
        body="Produce the runnable deployment snippet, then keep the same flow tractable as data volume grows.",
        seconds=3.2,
        active_step=1,
        focus=(0.60, 0.44),
        zoom_start=1.0,
        zoom_end=1.03,
        highlight=(0.23, 0.20, 0.95, 0.77),
        highlight_label="Deployment snippet",
        overlay="distribution_tree",
    ),
    Scene(
        name="pipeline",
        image=PAGE_SHOTS / "pipeline-page.png",
        stage="PIPELINE",
        title="Replay the same flow.",
        body="Turn the execution into an explicit, inspectable, and reusable step.",
        seconds=3.2,
        active_step=2,
        focus=(0.60, 0.48),
        zoom_start=1.0,
        zoom_end=1.03,
        highlight=(0.22, 0.39, 0.95, 0.80),
        highlight_label="Replayable step",
        overlay="pipeline_snippet",
    ),
    Scene(
        name="finale",
        image=PAGE_SHOTS / "analysis-page.png",
        stage="ANALYSIS",
        title="Finish on view_maps.",
        body="Land on an operator-facing map view instead of a raw infrastructure endpoint.",
        seconds=3.0,
        active_step=3,
        focus=(0.54, 0.42),
        zoom_start=1.0,
        zoom_end=1.03,
        highlight=(0.22, 0.30, 0.95, 0.93),
        highlight_label="view_maps_network",
        overlay="view_maps",
    ),
)


UAV_QUEUE_SCENES: tuple[Scene, ...] = (
    Scene(
        name="intro",
        image=PAGE_SHOTS / "core-pages-overview.png",
        stage="AGILAB",
        title="From scenario to queue evidence.",
        body="One workspace keeps UAV setup, execution, replay, and queue analysis aligned.",
        seconds=2.2,
        active_step=-1,
        focus=(0.56, 0.52),
        zoom_start=1.0,
        zoom_end=1.05,
        highlight=None,
        highlight_label=None,
    ),
    Scene(
        name="project",
        image=PAGE_SHOTS / "project-page.png",
        stage="PROJECT",
        title="Choose the hotspot benchmark.",
        body="Keep the same scenario, seed, and load fixed. Only the routing policy changes.",
        seconds=2.9,
        active_step=0,
        focus=(0.54, 0.46),
        zoom_start=1.0,
        zoom_end=1.04,
        highlight=(0.01, 0.43, 0.18, 0.67),
        highlight_label="Scenario + policy",
        overlay="uav_project_context",
    ),
    Scene(
        name="orchestrate",
        image=PAGE_SHOTS / "orchestrate-page.png",
        stage="ORCHESTRATE",
        title="Rerun the same load.",
        body="Package the benchmark cleanly, then compare shortest_path against queue_aware under the same conditions.",
        seconds=3.2,
        active_step=1,
        focus=(0.60, 0.44),
        zoom_start=1.0,
        zoom_end=1.03,
        highlight=(0.23, 0.20, 0.95, 0.77),
        highlight_label="Policy comparison setup",
        overlay="uav_orchestrate_compare",
    ),
    Scene(
        name="pipeline",
        image=PAGE_SHOTS / "pipeline-page.png",
        stage="PIPELINE",
        title="Keep the benchmark replayable.",
        body="Save the comparison logic as a step so routing regressions stay inspectable.",
        seconds=3.2,
        active_step=2,
        focus=(0.60, 0.48),
        zoom_start=1.0,
        zoom_end=1.03,
        highlight=(0.22, 0.39, 0.95, 0.80),
        highlight_label="Replayable step",
        overlay="uav_pipeline_snippet",
    ),
    Scene(
        name="finale",
        image=PAGE_SHOTS / "analysis-page.png",
        stage="ANALYSIS",
        title="Finish on queue evidence.",
        body="See exactly what the routing policy changed: drops, delay, bottleneck, and route usage.",
        seconds=3.1,
        active_step=3,
        focus=(0.54, 0.42),
        zoom_start=1.0,
        zoom_end=1.03,
        highlight=(0.22, 0.30, 0.95, 0.93),
        highlight_label="view_uav_relay_queue_analysis",
        overlay="uav_analysis",
    ),
)


VARIANTS: dict[str, Variant] = {
    "flight": Variant(key="flight", app_badge="FLIGHT PROJECT", scenes=FLIGHT_SCENES),
    "uav_queue": Variant(key="uav_queue", app_badge="UAV RELAY QUEUE", scenes=UAV_QUEUE_SCENES),
}


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


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


FONT_BADGE = load_font(25, bold=True)
FONT_KICKER = load_font(24, bold=True)
FONT_TITLE = load_font(72, bold=True)
FONT_BODY = load_font(30)
FONT_URL = load_font(22)
FONT_STEP = load_font(18, bold=True)
FONT_STEP_LABEL = load_font(22, bold=True)
FONT_HIGHLIGHT = load_font(21, bold=True)
FONT_FOOTER = load_font(26, bold=True)


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> str:
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join(current + [word]).strip()
        if not candidate:
            continue
        bbox = draw.textbbox((0, 0), candidate, font=font)
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
    for i in range(26):
        y0 = int(i * H / 26)
        y1 = int((i + 1) * H / 26)
        t = i / 25
        color = tuple(int(lerp(a, b, t)) for a, b in zip(BG, BG_2))
        draw.rectangle((0, y0, W, y1), fill=color + (255,))
    draw.ellipse((-220, -200, 760, 560), fill=BG_3 + (150,))
    draw.ellipse((1180, 380, 2140, 1340), fill=(12, 32, 58, 170))
    overlay = overlay.filter(ImageFilter.GaussianBlur(48))
    img.alpha_composite(overlay)
    grid = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(grid)
    for x in range(0, W, 80):
        gdraw.line((x, 0, x, H), fill=(255, 255, 255, 10), width=1)
    for y in range(0, H, 80):
        gdraw.line((0, y, W, y), fill=(255, 255, 255, 10), width=1)
    img.alpha_composite(grid)
    return img


def render_screenshot(
    img: Image.Image,
    *,
    width: int,
    height: int,
    focus: tuple[float, float],
    zoom: float,
) -> tuple[Image.Image, float, int, int]:
    src_w, src_h = img.size
    scale = max(width / src_w, height / src_h) * zoom
    rw, rh = int(src_w * scale), int(src_h * scale)
    resized = img.resize((rw, rh), Image.Resampling.LANCZOS)
    fx = focus[0] * rw
    fy = focus[1] * rh
    left = int(max(0, min(rw - width, fx - width / 2)))
    top = int(max(0, min(rh - height, fy - height / 2)))
    crop = resized.crop((left, top, left + width, top + height))
    return crop, scale, left, top


def draw_badge(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, fill: tuple[int, int, int], text_fill: tuple[int, int, int]) -> None:
    x, y = xy
    bbox = draw.textbbox((0, 0), text, font=FONT_BADGE)
    width = bbox[2] - bbox[0] + 38
    height = 44
    draw.rounded_rectangle((x, y, x + width, y + height), radius=20, fill=fill)
    draw.text((x + 19, y + 10), text, font=FONT_BADGE, fill=text_fill)


def draw_stepper(draw: ImageDraw.ImageDraw, active_step: int, reveal: float, *, top: int) -> None:
    labels = ["PROJECT", "ORCHESTRATE", "PIPELINE", "ANALYSIS"]
    x = 112
    gap = 96
    line_x = x + 18
    draw.line((line_x, top, line_x, top + gap * (len(labels) - 1)), fill=LINE + (180,), width=3)
    reveal_idx = len(labels) - 1 if active_step < 0 else active_step
    for idx, label in enumerate(labels):
        y = top + idx * gap
        is_active = idx == active_step
        is_done = idx < reveal_idx or active_step < 0
        if is_active:
            radius = 18
            fill = ACCENT
            outline = WHITE
        elif is_done:
            radius = 14
            fill = GREEN
            outline = WHITE
        else:
            radius = 12
            fill = SURFACE_2
            outline = LINE
        if idx > reveal_idx:
            alpha = int(70 + 185 * reveal)
        else:
            alpha = 255
        draw.ellipse((line_x - radius, y - radius, line_x + radius, y + radius), fill=fill + (alpha,), outline=outline + (alpha,), width=3)
        label_fill = INK if idx <= reveal_idx or is_active else MUTED
        draw.text((x + 56, y - 16), label, font=FONT_STEP_LABEL, fill=label_fill)
        draw.text((x - 10, y - 47), f"0{idx + 1}", font=FONT_STEP, fill=MUTED)


def draw_text_column(canvas: Image.Image, scene: Scene, t: float, variant: Variant) -> None:
    draw = ImageDraw.Draw(canvas)
    entry = ease_out(min(1.0, t / 0.22))
    x_offset = int(lerp(44, 0, entry))
    alpha = int(lerp(0, 255, entry))
    reveal = ease_in_out(min(1.0, t / 0.4))
    draw_badge(draw, (96 + x_offset, 84), "AGILAB", ACCENT + (220,), WHITE)
    draw_badge(draw, (219 + x_offset, 84), variant.app_badge, SURFACE_2 + (235,), INK)
    draw.text((96 + x_offset, 168), scene.stage, font=FONT_KICKER, fill=ACCENT_WARM + (alpha,))

    title_x = 96 + x_offset
    title_y = 222
    title = wrap_text(draw, scene.title, FONT_TITLE, 610)
    body = wrap_text(draw, scene.body, FONT_BODY, 560)
    draw.multiline_text((title_x, title_y), title, font=FONT_TITLE, fill=INK + (alpha,), spacing=2)
    title_bbox = draw.multiline_textbbox((title_x, title_y), title, font=FONT_TITLE, spacing=2)
    body_y = title_bbox[3] + 34
    draw.multiline_text((title_x, body_y), body, font=FONT_BODY, fill=MUTED + (alpha,), spacing=8)
    body_bbox = draw.multiline_textbbox((title_x, body_y), body, font=FONT_BODY, spacing=8)

    draw.text((96 + x_offset, 900), "github.com/ThalesGroup/agilab", font=FONT_URL, fill=MUTED + (alpha,))
    draw_stepper(draw, scene.active_step, reveal, top=max(456, body_bbox[3] + 92))


def draw_screenshot_card(canvas: Image.Image, scene: Scene, t: float, variant: Variant) -> None:
    zoom = lerp(scene.zoom_start, scene.zoom_end, ease_in_out(t))
    src = Image.open(scene.image).convert("RGB")
    screenshot, scale, left, top = render_screenshot(src, width=CARD_W, height=CARD_H, focus=scene.focus, zoom=zoom)
    screenshot_rgba = screenshot.convert("RGBA")

    overlay = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    for i in range(10):
        alpha = int(lerp(0, 90, i / 9))
        odraw.rectangle((0, 0, CARD_W, int(CARD_H * 0.35 * (i + 1) / 10)), fill=(7, 13, 20, alpha))
    screenshot_rgba.alpha_composite(overlay)

    card = Image.new("RGBA", (CARD_W + 60, CARD_H + 60), (0, 0, 0, 0))
    cdraw = ImageDraw.Draw(card)
    cdraw.rounded_rectangle((16, 18, CARD_W + 42, CARD_H + 46), radius=42, fill=(0, 0, 0, 90))
    card = card.filter(ImageFilter.GaussianBlur(14))
    entry = ease_out(min(1.0, t / 0.24))
    slide_x = int(lerp(86, 0, entry))
    slide_y = int(lerp(18, 0, entry))
    canvas.alpha_composite(card, (CARD_X - 24 + slide_x, CARD_Y - 8 + slide_y))

    frame = Image.new("RGBA", (CARD_W, CARD_H), SURFACE + (255,))
    fdraw = ImageDraw.Draw(frame)
    fdraw.rounded_rectangle((0, 0, CARD_W - 1, CARD_H - 1), radius=34, fill=SURFACE + (0,), outline=(255, 255, 255, 38), width=2)
    frame.alpha_composite(screenshot_rgba)

    border = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    bdraw = ImageDraw.Draw(border)
    bdraw.rounded_rectangle((0, 0, CARD_W - 1, CARD_H - 1), radius=34, outline=(255, 255, 255, 52), width=2)
    frame.alpha_composite(border)

    canvas.alpha_composite(frame, (CARD_X + slide_x, CARD_Y + slide_y))

    if scene.highlight:
        x0, y0, x1, y1 = scene.highlight
        src_w, src_h = src.size
        hx0 = x0 * src_w * scale - left
        hy0 = y0 * src_h * scale - top
        hx1 = x1 * src_w * scale - left
        hy1 = y1 * src_h * scale - top
        pulse = 0.5 + 0.5 * math.sin(2 * math.pi * t * 1.4)
        highlight = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
        hdraw = ImageDraw.Draw(highlight)
        fill_alpha = int(40 + 18 * pulse)
        outline_alpha = int(190 + 45 * pulse)
        hdraw.rounded_rectangle((hx0, hy0, hx1, hy1), radius=18, fill=ACCENT + (fill_alpha,), outline=ACCENT + (outline_alpha,), width=4)
        if scene.highlight_label:
            tag_bbox = hdraw.textbbox((0, 0), scene.highlight_label, font=FONT_HIGHLIGHT)
            tag_w = tag_bbox[2] - tag_bbox[0] + 32
            tag_h = 42
            tag_x = max(24, min(CARD_W - tag_w - 24, int(hx0)))
            tag_y = max(18, int(hy0) - 52)
            hdraw.rounded_rectangle((tag_x, tag_y, tag_x + tag_w, tag_y + tag_h), radius=18, fill=ACCENT_WARM + (232,))
            hdraw.text((tag_x + 16, tag_y + 10), scene.highlight_label, font=FONT_HIGHLIGHT, fill=WHITE)
        canvas.alpha_composite(highlight, (CARD_X + slide_x, CARD_Y + slide_y))

    if scene.overlay == "distribution_tree":
        draw_distribution_tree_overlay(canvas, scene, slide_x, slide_y)
    elif scene.overlay == "pipeline_snippet":
        draw_pipeline_snippet_overlay(canvas, scene, slide_x, slide_y)
    elif scene.overlay == "view_maps":
        draw_view_maps_overlay(canvas, scene, slide_x, slide_y)
    elif scene.overlay == "uav_project_context":
        draw_uav_project_context_overlay(canvas, scene, slide_x, slide_y)
    elif scene.overlay == "uav_distribution_tree":
        draw_uav_distribution_tree_overlay(canvas, scene, slide_x, slide_y)
    elif scene.overlay == "uav_orchestrate_compare":
        draw_uav_orchestrate_compare_overlay(canvas, scene, slide_x, slide_y)
    elif scene.overlay == "uav_pipeline_snippet":
        draw_uav_pipeline_snippet_overlay(canvas, scene, slide_x, slide_y)
    elif scene.overlay == "uav_analysis":
        draw_uav_analysis_overlay(canvas, scene, slide_x, slide_y)


def fit_contain(img: Image.Image, width: int, height: int) -> Image.Image:
    src_w, src_h = img.size
    scale = min(width / src_w, height / src_h)
    resized = img.resize((int(src_w * scale), int(src_h * scale)), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    x = (width - resized.size[0]) // 2
    y = (height - resized.size[1]) // 2
    canvas.alpha_composite(resized.convert("RGBA"), (x, y))
    return canvas


def draw_distribution_tree_overlay(canvas: Image.Image, scene: Scene, slide_x: int, slide_y: int) -> None:
    tree_path = DIAGRAMS / "agi_distributor_flow.png"
    if not tree_path.exists():
        return
    tree = Image.open(tree_path).convert("RGBA")
    box_w = 390
    box_h = 306
    x = CARD_X + 612 + slide_x
    y = CARD_Y + 274 + slide_y

    shadow = Image.new("RGBA", (box_w + 40, box_h + 40), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    sdraw.rounded_rectangle((18, 18, box_w + 18, box_h + 18), radius=28, fill=(0, 0, 0, 110))
    shadow = shadow.filter(ImageFilter.GaussianBlur(12))
    canvas.alpha_composite(shadow, (x - 20, y - 16))

    panel = Image.new("RGBA", (box_w, box_h), SURFACE + (248,))
    pdraw = ImageDraw.Draw(panel)
    pdraw.rounded_rectangle((0, 0, box_w - 1, box_h - 1), radius=26, fill=SURFACE_2 + (244,), outline=(255, 255, 255, 46), width=2)
    pdraw.rounded_rectangle((18, 16, 208, 54), radius=16, fill=ACCENT_WARM + (236,))
    pdraw.text((34, 26), "Distribution tree", font=FONT_HIGHLIGHT, fill=WHITE)
    pdraw.rounded_rectangle((238, 16, box_w - 18, 54), radius=16, fill=(17, 40, 62, 255))
    pdraw.text((274, 26), "data scale", font=FONT_HIGHLIGHT, fill=WHITE)
    pdraw.rounded_rectangle((16, 68, box_w - 16, 220), radius=20, fill=(255, 255, 255, 245))
    fitted = fit_contain(tree, box_w - 48, 136)
    panel.alpha_composite(fitted, (24, 76))

    stats_y = 236
    stat_specs = [
        ("Rows", "10M+"),
        ("Chunks", "24"),
        ("Artifacts", "batched"),
    ]
    stat_x = 18
    for label, value in stat_specs:
        card_w = 110 if label != "Artifacts" else 136
        pdraw.rounded_rectangle((stat_x, stats_y, stat_x + card_w, stats_y + 52), radius=16, fill=(11, 22, 34, 255), outline=(92, 160, 255), width=2)
        pdraw.text((stat_x + 12, stats_y + 10), label, font=FONT_STEP, fill=MUTED)
        pdraw.text((stat_x + 12, stats_y + 28), value, font=FONT_HIGHLIGHT, fill=INK)
        stat_x += card_w + 10

    pdraw.rounded_rectangle((box_w - 146, stats_y, box_w - 18, stats_y + 52), radius=16, fill=(16, 56, 44, 255))
    pdraw.text((box_w - 132, stats_y + 10), "Big-data", font=FONT_STEP, fill=(187, 229, 208))
    pdraw.text((box_w - 132, stats_y + 28), "ready", font=FONT_HIGHLIGHT, fill=WHITE)
    canvas.alpha_composite(panel, (x, y))


def draw_view_maps_overlay(canvas: Image.Image, scene: Scene, slide_x: int, slide_y: int) -> None:
    box_x = CARD_X + 128 + slide_x
    box_y = CARD_Y + 222 + slide_y
    box_w = 760
    box_h = 344

    map_panel = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(map_panel)
    draw.rounded_rectangle((0, 0, box_w - 1, box_h - 1), radius=28, fill=(9, 22, 35, 244), outline=(255, 255, 255, 34), width=2)
    draw.rounded_rectangle((18, 16, 264, 52), radius=14, fill=(255, 255, 255, 22))
    draw.text((36, 24), "view_maps_network", font=FONT_HIGHLIGHT, fill=INK)

    map_rect = (18, 68, box_w - 18, box_h - 18)
    x0, y0, x1, y1 = map_rect
    draw.rounded_rectangle(map_rect, radius=22, fill=(8, 28, 46, 255))
    ocean_highlight = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(ocean_highlight)
    odraw.ellipse((x0 - 80, y0 - 30, x1 - 10, y1 + 40), fill=(29, 80, 124, 34))
    odraw.ellipse((x0 + 120, y0 + 10, x1 + 80, y1 + 30), fill=(24, 63, 104, 24))
    map_panel.alpha_composite(ocean_highlight)

    def project(lon: float, lat: float) -> tuple[int, int]:
        lon_min, lon_max = -126.0, -66.0
        lat_min, lat_max = 24.0, 50.0
        px = x0 + 30 + (lon - lon_min) / (lon_max - lon_min) * (x1 - x0 - 60)
        py = y1 - 26 - (lat - lat_min) / (lat_max - lat_min) * (y1 - y0 - 52)
        return int(px), int(py)

    us_outline = [
        (-124.5, 48.8), (-124.0, 42.0), (-122.0, 38.0), (-119.0, 34.0), (-117.0, 32.4),
        (-111.0, 31.5), (-106.5, 31.0), (-104.0, 29.8), (-100.0, 28.8), (-97.0, 26.5),
        (-90.0, 29.0), (-85.0, 30.2), (-82.0, 27.5), (-80.2, 25.4), (-80.0, 30.5),
        (-81.5, 32.0), (-79.0, 34.8), (-76.0, 37.5), (-75.0, 39.5), (-74.0, 40.7),
        (-71.5, 41.8), (-70.0, 43.5), (-71.0, 45.0), (-74.0, 44.8), (-79.0, 43.5),
        (-83.0, 45.0), (-87.0, 47.0), (-94.0, 49.0), (-103.0, 49.0), (-111.0, 49.0),
        (-117.0, 49.0), (-124.5, 48.8),
    ]
    land_poly = [project(lon, lat) for lon, lat in us_outline]
    draw.polygon(land_poly, fill=(29, 57, 76), outline=(135, 176, 212))

    for lon in (-120, -110, -100, -90, -80, -70):
        gx0, gy0 = project(lon, 24.5)
        gx1, gy1 = project(lon, 49.5)
        draw.line((gx0, gy0, gx1, gy1), fill=(255, 255, 255, 16), width=1)
    for lat in (28, 34, 40, 46):
        gx0, gy0 = project(-125, lat)
        gx1, gy1 = project(-67, lat)
        draw.line((gx0, gy0, gx1, gy1), fill=(255, 255, 255, 16), width=1)

    spot_specs = [
        ("Spot A", -118.0, 35.0, 56),
        ("Spot B", -100.0, 39.0, 62),
        ("Spot C", -84.0, 35.5, 52),
    ]
    for label, lon, lat, radius in spot_specs:
        px, py = project(lon, lat)
        draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=(255, 190, 92, 26), outline=(255, 190, 92, 120), width=3)
        draw.ellipse((px - int(radius * 0.55), py - int(radius * 0.55), px + int(radius * 0.55), py + int(radius * 0.55)), outline=(255, 222, 158, 80), width=2)
        if label == "Spot B":
            tw = draw.textbbox((0, 0), label, font=FONT_STEP)[2]
            lx = px - tw // 2 - 8
            ly = py - radius - 26
            draw.rounded_rectangle((lx, ly, lx + tw + 16, ly + 22), radius=9, fill=(72, 48, 18, 220))
            draw.text((lx + 8, ly + 4), label, font=FONT_STEP, fill=(255, 236, 198))

    city_data = [
        ("Los Angeles", -118.2437, 34.0522),
        ("Denver", -104.9903, 39.7392),
        ("Chicago", -87.6298, 41.8781),
        ("Atlanta", -84.3880, 33.7490),
        ("New York", -74.0060, 40.7128),
    ]
    route = [project(lon, lat) for _, lon, lat in city_data]
    draw.line(route, fill=ACCENT + (255,), width=7, joint="curve")
    draw.line(route, fill=WHITE + (96,), width=2, joint="curve")
    for label, lon, lat in city_data:
        px, py = project(lon, lat)
        draw.ellipse((px - 8, py - 8, px + 8, py + 8), fill=ACCENT_WARM, outline=WHITE, width=2)
        tw = draw.textbbox((0, 0), label, font=FONT_STEP)[2]
        if label in {"Los Angeles", "Denver"}:
            lx = px + 12
            ly = py - 20
        elif label == "Atlanta":
            lx = px + 12
            ly = py - 6
        else:
            lx = px + 10
            ly = py - 28
        lx = min(x1 - tw - 24, max(x0 + 10, lx))
        ly = min(y1 - 32, max(y0 + 6, ly))
        draw.rounded_rectangle((lx, ly, lx + tw + 18, ly + 24), radius=10, fill=(7, 17, 28, 214))
        draw.text((lx + 9, ly + 5), label, font=FONT_STEP, fill=INK)

    draw.rounded_rectangle((x0 + 18, y1 - 44, x0 + 170, y1 - 18), radius=12, fill=(7, 17, 28, 220))
    draw.text((x0 + 30, y1 - 38), "USA map + sat spots", font=FONT_STEP, fill=MUTED)
    draw.rounded_rectangle((x1 - 144, y1 - 76, x1 - 28, y1 - 28), radius=16, fill=(7, 17, 28, 220))
    draw.text((x1 - 126, y1 - 66), "Routes", font=FONT_STEP, fill=MUTED)
    draw.text((x1 - 126, y1 - 42), "5 visible", font=FONT_HIGHLIGHT, fill=WHITE)
    canvas.alpha_composite(map_panel, (box_x, box_y))


def draw_pipeline_snippet_overlay(canvas: Image.Image, scene: Scene, slide_x: int, slide_y: int) -> None:
    box_x = CARD_X + 146 + slide_x
    box_y = CARD_Y + 188 + slide_y
    box_w = 690
    box_h = 268

    panel = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(panel)
    draw.rounded_rectangle((0, 0, box_w - 1, box_h - 1), radius=26, fill=(12, 22, 34, 248), outline=(255, 255, 255, 36), width=2)
    draw.rounded_rectangle((18, 16, 190, 52), radius=14, fill=ACCENT_WARM + (236,))
    draw.text((34, 24), "Replayable snippet", font=FONT_HIGHLIGHT, fill=WHITE)
    draw.rounded_rectangle((20, 70, box_w - 20, box_h - 20), radius=18, fill=(9, 15, 24, 255), outline=(92, 160, 255), width=2)

    code_lines = [
        "import asyncio",
        "from agi_cluster.agi_distributor import AGI",
        "from agi_env import AgiEnv",
        "",
        "APP = \"flight_project\"",
        "app_env = AgiEnv(apps_path=APPS_PATH, app=APP, verbose=1)",
        "res = await AGI.run(app_env, mode=15, data_in=\"flight/dataset\")",
        "print(res)",
    ]
    line_y = 92
    code_font = load_font(19)
    for line in code_lines:
        fill = INK if line and not line.startswith("APP") else (164, 194, 230)
        if "AGI.run" in line:
            fill = ACCENT_WARM
        draw.text((38, line_y), line, font=code_font, fill=fill)
        line_y += 24
    draw.rounded_rectangle((box_w - 154, box_h - 56, box_w - 26, box_h - 24), radius=14, fill=(18, 39, 60, 255))
    draw.text((box_w - 133, box_h - 47), "saved in lab_steps", font=FONT_STEP, fill=WHITE)
    canvas.alpha_composite(panel, (box_x, box_y))


def draw_uav_project_context_overlay(canvas: Image.Image, scene: Scene, slide_x: int, slide_y: int) -> None:
    box_x = CARD_X + 148 + slide_x
    box_y = CARD_Y + 214 + slide_y
    box_w = 648
    box_h = 248

    panel = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(panel)
    draw.rounded_rectangle((0, 0, box_w - 1, box_h - 1), radius=24, fill=(11, 22, 34, 246), outline=(255, 255, 255, 38), width=2)
    draw.rounded_rectangle((18, 16, 208, 52), radius=14, fill=ACCENT_WARM + (236,))
    draw.text((34, 24), "Scenario context", font=FONT_HIGHLIGHT, fill=WHITE)

    specs = [
        ("Scenario file", "uav_queue_hotspot.json"),
        ("Source load", "14 pps"),
        ("Seed", "2026"),
        ("Policies", "2 reruns"),
    ]
    row_y = 78
    for label, value in specs:
        draw.rounded_rectangle((24, row_y, box_w - 24, row_y + 34), radius=12, fill=(17, 34, 52, 255))
        draw.text((38, row_y + 8), label, font=FONT_STEP, fill=MUTED)
        value_bbox = draw.textbbox((0, 0), value, font=FONT_HIGHLIGHT)
        vw = value_bbox[2] - value_bbox[0]
        draw.text((box_w - vw - 42, row_y + 7), value, font=FONT_HIGHLIGHT, fill=INK)
        row_y += 40

    draw.rounded_rectangle((24, box_h - 52, 170, box_h - 18), radius=12, fill=(18, 56, 44, 255))
    draw.text((42, box_h - 43), "same scenario", font=FONT_STEP, fill=WHITE)
    draw.rounded_rectangle((box_w - 148, box_h - 52, box_w - 24, box_h - 18), radius=12, fill=(18, 39, 60, 255))
    draw.text((box_w - 128, box_h - 43), "queue + maps", font=FONT_STEP, fill=WHITE)
    canvas.alpha_composite(panel, (box_x, box_y))


def draw_uav_orchestrate_compare_overlay(canvas: Image.Image, scene: Scene, slide_x: int, slide_y: int) -> None:
    box_x = CARD_X + 556 + slide_x
    box_y = CARD_Y + 208 + slide_y
    box_w = 450
    box_h = 350

    panel = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(panel)
    draw.rounded_rectangle((0, 0, box_w - 1, box_h - 1), radius=26, fill=SURFACE_2 + (246,), outline=(255, 255, 255, 44), width=2)
    draw.rounded_rectangle((18, 16, 224, 54), radius=16, fill=ACCENT_WARM + (236,))
    draw.text((36, 26), "Policy comparison", font=FONT_HIGHLIGHT, fill=WHITE)
    draw.rounded_rectangle((244, 16, box_w - 18, 54), radius=16, fill=(17, 40, 62, 255))
    draw.text((266, 26), "same scenario / same load", font=FONT_HIGHLIGHT, fill=WHITE)

    specs = [("Scenario", "uav_queue_hotspot"), ("Packets", "409"), ("Seed", "2026")]
    sx = 18
    sy = 76
    for label, value in specs:
        draw.rounded_rectangle((sx, sy, sx + 130, sy + 52), radius=14, fill=(11, 22, 34, 255), outline=(92, 160, 255), width=2)
        draw.text((sx + 12, sy + 10), label, font=FONT_STEP, fill=MUTED)
        draw.text((sx + 12, sy + 28), value, font=FONT_HIGHLIGHT, fill=INK)
        sx += 142

    left = (26, 150, 210, 270)
    right = (240, 150, 424, 270)
    for box, title, subtitle, fill in [
        (left, "Run A", "shortest_path", (83, 111, 156)),
        (right, "Run B", "queue_aware", (71, 146, 107)),
    ]:
        x0, y0, x1, y1 = box
        draw.rounded_rectangle(box, radius=18, fill=(247, 251, 255), outline=fill, width=3)
        draw.text((x0 + 18, y0 + 18), title, font=FONT_STEP, fill=MUTED)
        draw.text((x0 + 18, y0 + 44), subtitle, font=FONT_HIGHLIGHT, fill=SURFACE)
        draw.text((x0 + 18, y0 + 76), "same source_rate_pps", font=FONT_STEP, fill=fill)

    draw.line((118, 270, 118, 318), fill=ACCENT + (255,), width=4)
    draw.line((332, 270, 332, 318), fill=GREEN + (255,), width=4)
    draw.line((118, 318, 332, 318), fill=(160, 180, 205), width=4)
    draw.rounded_rectangle((120, 296, 330, 340), radius=16, fill=(10, 18, 28, 255), outline=(255, 255, 255, 20), width=1)
    draw.text((140, 306), "Only the policy changes", font=FONT_HIGHLIGHT, fill=INK)
    canvas.alpha_composite(panel, (box_x, box_y))


def draw_uav_distribution_tree_overlay(canvas: Image.Image, scene: Scene, slide_x: int, slide_y: int) -> None:
    box_x = CARD_X + 564 + slide_x
    box_y = CARD_Y + 224 + slide_y
    box_w = 430
    box_h = 328

    panel = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(panel)
    draw.rounded_rectangle((0, 0, box_w - 1, box_h - 1), radius=26, fill=SURFACE_2 + (246,), outline=(255, 255, 255, 44), width=2)
    draw.rounded_rectangle((18, 16, 210, 54), radius=16, fill=ACCENT_WARM + (236,))
    draw.text((36, 26), "Scenario fan-out", font=FONT_HIGHLIGHT, fill=WHITE)
    draw.rounded_rectangle((238, 16, box_w - 18, 54), radius=16, fill=(17, 40, 62, 255))
    draw.text((256, 26), "1 file = 1 unit", font=FONT_HIGHLIGHT, fill=WHITE)

    # small custom tree
    node_fill = (248, 251, 255)
    node_outline = (113, 154, 202)
    scheduler = (170, 84, 260, 126)
    scen_a = (52, 170, 186, 214)
    scen_b = (244, 170, 378, 214)
    worker_a = (40, 258, 170, 302)
    worker_b = (150, 258, 280, 302)
    worker_c = (260, 258, 390, 302)
    for box, label in [
        (scheduler, "Scheduler"),
        (scen_a, "hotspot.json"),
        (scen_b, "hotspot_b.json"),
        (worker_a, "Worker 1"),
        (worker_b, "Worker 2"),
        (worker_c, "Worker 3"),
    ]:
        draw.rounded_rectangle(box, radius=14, fill=node_fill, outline=node_outline, width=2)
        bbox = draw.textbbox((0, 0), label, font=FONT_STEP)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        x0, y0, x1, y1 = box
        draw.text((x0 + (x1 - x0 - tw) / 2, y0 + (y1 - y0 - th) / 2 - 1), label, font=FONT_STEP, fill=SURFACE)

    def center(box: tuple[int, int, int, int]) -> tuple[int, int]:
        x0, y0, x1, y1 = box
        return int((x0 + x1) / 2), int((y0 + y1) / 2)

    sx, sy = center(scheduler)
    a1x, a1y = center(scen_a)
    b1x, b1y = center(scen_b)
    for tx, ty in ((a1x, a1y), (b1x, b1y)):
        draw.line((sx, sy + 22, tx, ty - 22), fill=ACCENT + (255,), width=4)
    for source, target in ((scen_a, worker_a), (scen_a, worker_b), (scen_b, worker_c)):
        x0, y0 = center(source)
        x1, y1 = center(target)
        draw.line((x0, y0 + 22, x1, y1 - 22), fill=(121, 192, 155), width=4)

    stat_specs = [
        ("Scenario files", "2"),
        ("Workers", "3"),
        ("Unit", "1 file"),
    ]
    sx = 18
    sy = 82
    for label, value in stat_specs:
        draw.rounded_rectangle((sx, sy, sx + 118, sy + 54), radius=14, fill=(11, 22, 34, 255), outline=(92, 160, 255), width=2)
        draw.text((sx + 12, sy + 10), label, font=FONT_STEP, fill=MUTED)
        draw.text((sx + 12, sy + 29), value, font=FONT_HIGHLIGHT, fill=INK)
        sx += 130

    draw.rounded_rectangle((box_w - 162, box_h - 52, box_w - 22, box_h - 18), radius=14, fill=(18, 56, 44, 255))
    draw.text((box_w - 144, box_h - 43), "parallel replay", font=FONT_STEP, fill=WHITE)
    canvas.alpha_composite(panel, (box_x, box_y))


def draw_uav_pipeline_snippet_overlay(canvas: Image.Image, scene: Scene, slide_x: int, slide_y: int) -> None:
    box_x = CARD_X + 124 + slide_x
    box_y = CARD_Y + 184 + slide_y
    box_w = 736
    box_h = 318

    panel = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(panel)
    draw.rounded_rectangle((0, 0, box_w - 1, box_h - 1), radius=26, fill=(12, 22, 34, 248), outline=(255, 255, 255, 36), width=2)
    draw.rounded_rectangle((18, 16, 196, 52), radius=14, fill=ACCENT_WARM + (236,))
    draw.text((34, 24), "Replayable snippet", font=FONT_HIGHLIGHT, fill=WHITE)
    draw.rounded_rectangle((20, 70, box_w - 20, box_h - 20), radius=18, fill=(9, 15, 24, 255), outline=(92, 160, 255), width=2)

    code_lines = [
        "import asyncio",
        "from agi_cluster.agi_distributor import AGI",
        "from agi_env import AgiEnv",
        "",
        "APP = \"uav_relay_queue_project\"",
        "env = AgiEnv(app=APP, verbose=1)",
        "for policy in [\"shortest_path\", \"queue_aware\"]:",
        "    await AGI.run(env, mode=15, data_in=\"uav_relay_queue/scenarios\")",
    ]
    line_y = 92
    code_font = load_font(17)
    for line in code_lines:
        fill = INK if line and not line.startswith("APP") else (164, 194, 230)
        if "AGI.run" in line or "policy" in line:
            fill = ACCENT_WARM
        draw.text((38, line_y), line, font=code_font, fill=fill)
        line_y += 21

    draw.rounded_rectangle((30, box_h - 58, 174, box_h - 24), radius=14, fill=(17, 40, 62, 255))
    draw.text((48, box_h - 49), "2-policy benchmark", font=FONT_STEP, fill=WHITE)
    draw.rounded_rectangle((194, box_h - 58, 376, box_h - 24), radius=14, fill=(18, 56, 44, 255))
    draw.text((212, box_h - 49), "writes queue telemetry", font=FONT_STEP, fill=WHITE)
    draw.rounded_rectangle((box_w - 124, box_h - 58, box_w - 26, box_h - 24), radius=14, fill=(18, 39, 60, 255))
    draw.text((box_w - 104, box_h - 49), "lab_steps", font=FONT_STEP, fill=WHITE)
    canvas.alpha_composite(panel, (box_x, box_y))


def draw_uav_analysis_overlay(canvas: Image.Image, scene: Scene, slide_x: int, slide_y: int) -> None:
    box_x = CARD_X + 84 + slide_x
    box_y = CARD_Y + 186 + slide_y
    box_w = 838
    box_h = 360

    panel = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(panel)
    draw.rounded_rectangle((0, 0, box_w - 1, box_h - 1), radius=28, fill=(9, 22, 35, 244), outline=(255, 255, 255, 34), width=2)
    draw.rounded_rectangle((18, 16, 250, 52), radius=14, fill=(255, 255, 255, 22))
    draw.text((36, 24), "view_uav_relay_queue_analysis", font=FONT_HIGHLIGHT, fill=INK)

    left_card = (24, 76, 222, 166)
    right_card = (238, 76, 436, 166)
    for box, title, lines, outline in [
        (left_card, "shortest_path", [("PDR", "0.511"), ("Drops", "200"), ("Delay", "1311 ms")], (93, 120, 159)),
        (right_card, "queue_aware", [("PDR", "1.000"), ("Drops", "0"), ("Delay", "206 ms")], (85, 162, 116)),
    ]:
        x0, y0, x1, y1 = box
        draw.rounded_rectangle(box, radius=18, fill=(12, 28, 44, 255), outline=outline, width=3)
        draw.text((x0 + 16, y0 + 14), title, font=FONT_HIGHLIGHT, fill=INK)
        ly = y0 + 42
        for label, value in lines:
            draw.text((x0 + 16, ly), label, font=FONT_STEP, fill=MUTED)
            draw.text((x1 - 16 - (draw.textbbox((0, 0), value, font=FONT_STEP)[2]), ly), value, font=FONT_STEP, fill=WHITE)
            ly += 20

    draw.rounded_rectangle((452, 76, box_w - 24, 166), radius=18, fill=(12, 28, 44, 255), outline=(75, 123, 171), width=2)
    draw.text((470, 90), "What changed", font=FONT_HIGHLIGHT, fill=INK)
    draw.text((470, 116), "relay_a hotspot removed", font=FONT_STEP, fill=WHITE)
    draw.text((470, 138), "route usage split across relays", font=FONT_STEP, fill=WHITE)

    # queue line chart
    chart = (28, 188, 520, 324)
    x0, y0, x1, y1 = chart
    draw.rounded_rectangle(chart, radius=18, fill=(10, 18, 28, 255))
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        yy = int(y0 + frac * (y1 - y0))
        draw.line((x0 + 16, yy, x1 - 16, yy), fill=(255, 255, 255, 16), width=1)
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        xx = int(x0 + frac * (x1 - x0))
        draw.line((xx, y0 + 12, xx, y1 - 12), fill=(255, 255, 255, 12), width=1)
    draw.text((x0 + 16, y0 + 12), "Queue occupancy: hotspot vs reroute", font=FONT_HIGHLIGHT, fill=INK)
    hotspot = [(x0 + 30, y1 - 28), (x0 + 96, y1 - 52), (x0 + 164, y1 - 88), (x0 + 232, y1 - 124), (x0 + 300, y1 - 116), (x0 + 372, y1 - 138), (x0 + 444, y1 - 146)]
    reroute = [(x0 + 30, y1 - 48), (x0 + 96, y1 - 50), (x0 + 164, y1 - 66), (x0 + 232, y1 - 78), (x0 + 300, y1 - 80), (x0 + 372, y1 - 88), (x0 + 444, y1 - 92)]
    draw.line(hotspot, fill=ACCENT_WARM + (255,), width=5, joint="curve")
    draw.line(reroute, fill=GREEN + (255,), width=5, joint="curve")
    draw.text((x0 + 24, y1 - 28), "hotspot", font=FONT_STEP, fill=ACCENT_WARM)
    draw.text((x0 + 108, y1 - 28), "queue_aware", font=FONT_STEP, fill=GREEN)

    # route usage + map reuse
    right = (548, 188, box_w - 24, 324)
    rx0, ry0, rx1, ry1 = right
    draw.rounded_rectangle(right, radius=18, fill=(10, 18, 28, 255))
    draw.text((rx0 + 18, ry0 + 14), "Route usage after reroute", font=FONT_HIGHLIGHT, fill=INK)
    bars = [
        ("relay_a 23%", 0.23, ACCENT),
        ("relay_b 77%", 0.77, GREEN),
    ]
    by = ry0 + 52
    for label, frac, color in bars:
        draw.text((rx0 + 18, by), label, font=FONT_STEP, fill=MUTED)
        draw.rounded_rectangle((rx0 + 18, by + 22, rx1 - 28, by + 40), radius=9, fill=(22, 32, 46, 255))
        fill_w = int((rx1 - rx0 - 46) * frac)
        draw.rounded_rectangle((rx0 + 18, by + 22, rx0 + 18 + fill_w, by + 40), radius=9, fill=color)
        by += 46

    mini = (rx0 + 18, ry1 - 72, rx1 - 28, ry1 - 18)
    mx0, my0, mx1, my1 = mini
    draw.rounded_rectangle(mini, radius=14, fill=(11, 26, 40, 255), outline=(255, 255, 255, 20), width=1)
    pts = [(mx0 + 24, my1 - 22), (mx0 + 108, my0 + 24), (mx0 + 206, my1 - 26), (mx0 + 292, my0 + 18)]
    draw.line(pts, fill=ACCENT + (255,), width=4)
    for px, py in pts:
        draw.ellipse((px - 5, py - 5, px + 5, py + 5), fill=ACCENT_WARM, outline=WHITE, width=1)
    draw.text((mx0 + 14, my0 + 8), "view_maps reusable", font=FONT_STEP, fill=INK)

    canvas.alpha_composite(panel, (box_x, box_y))


def draw_footer(canvas: Image.Image, scene: Scene, t: float) -> None:
    draw = ImageDraw.Draw(canvas)
    alpha = int(lerp(120, 255, ease_out(min(1.0, t / 0.22))))
    footer = "PROJECT -> ORCHESTRATE -> PIPELINE -> ANALYSIS"
    bbox = draw.textbbox((0, 0), footer, font=FONT_FOOTER)
    width = bbox[2] - bbox[0] + 42
    x = CARD_X + CARD_W - width
    y = 872
    draw.rounded_rectangle((x, y, x + width, y + 52), radius=24, fill=SURFACE_2 + (210,), outline=(255, 255, 255, 36), width=2)
    draw.text((x + 22, y + 13), footer, font=FONT_FOOTER, fill=INK + (alpha,))


def draw_scene(scene: Scene, t: float, variant: Variant) -> Image.Image:
    canvas = background()
    draw_text_column(canvas, scene, t, variant)
    draw_screenshot_card(canvas, scene, t, variant)
    draw_footer(canvas, scene, t)
    return canvas.convert("RGB")


def crossfade(a: Image.Image, b: Image.Image, frames: int) -> Iterable[Image.Image]:
    for i in range(frames):
        alpha = (i + 1) / (frames + 1)
        yield Image.blend(a, b, alpha)


def save_video_from_frames(frames_dir: Path, mp4_path: Path, gif_path: Path, fps: int) -> None:
    ffmpeg = "/opt/homebrew/bin/ffmpeg"
    mp4_path.parent.mkdir(parents=True, exist_ok=True)
    gif_path.parent.mkdir(parents=True, exist_ok=True)

    mp4_cmd = [
        ffmpeg,
        "-y",
        "-framerate",
        str(fps),
        "-i",
        str(frames_dir / "frame_%04d.png"),
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
        str(mp4_path),
    ]
    subprocess.run(mp4_cmd, check=True)

    gif_cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(mp4_path),
        "-vf",
        "fps=10,scale=1280:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse",
        str(gif_path),
    ]
    subprocess.run(gif_cmd, check=True)


def build(out_mp4: Path, out_gif: Path, out_poster: Path, *, variant_key: str = "flight") -> None:
    variant = VARIANTS[variant_key]
    scenes = variant.scenes
    transition_frames = 8
    with tempfile.TemporaryDirectory(prefix="agilab_product_reel_") as tmp:
        frames_dir = Path(tmp)
        frame_no = 0
        poster_written = False
        for idx, scene in enumerate(scenes):
            count = int(scene.seconds * FPS)
            scene_frames: list[Image.Image] = []
            for i in range(count):
                t = 0.0 if count <= 1 else i / (count - 1)
                frame = draw_scene(scene, t, variant)
                scene_frames.append(frame)
                frame.save(frames_dir / f"frame_{frame_no:04d}.png")
                if scene.name == "orchestrate" and not poster_written and i >= count // 2:
                    out_poster.parent.mkdir(parents=True, exist_ok=True)
                    frame.save(out_poster)
                    poster_written = True
                frame_no += 1
            if idx < len(scenes) - 1:
                current_end = scene_frames[-1]
                next_start = draw_scene(scenes[idx + 1], 0.10, variant)
                for frame in crossfade(current_end, next_start, transition_frames):
                    frame.save(frames_dir / f"frame_{frame_no:04d}.png")
                    frame_no += 1

        if not poster_written:
            Image.open(frames_dir / "frame_0000.png").save(out_poster)

        save_video_from_frames(frames_dir, out_mp4, out_gif, FPS)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a polished AGILAB product reel from real screenshots.")
    parser.add_argument("--variant", choices=sorted(VARIANTS.keys()), default="flight")
    parser.add_argument("--mp4", default="artifacts/demo_media/flight/agilab_flight.mp4")
    parser.add_argument("--gif", default="artifacts/demo_media/flight/agilab_flight.gif")
    parser.add_argument("--poster", default="artifacts/demo_media/flight/agilab_flight_poster.png")
    args = parser.parse_args()
    build(Path(args.mp4), Path(args.gif), Path(args.poster), variant_key=args.variant)
    print(Path(args.mp4).resolve())
    print(Path(args.gif).resolve())
    print(Path(args.poster).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
