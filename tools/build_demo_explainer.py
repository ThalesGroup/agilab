#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont


W, H = 1200, 672
BG_TOP = (251, 253, 255)
BG_BOTTOM = (238, 244, 251)
INK = (20, 40, 63)
MUTED = (84, 105, 129)
ACCENT = (191, 90, 36)
ACCENT_2 = (33, 84, 114)
LINE = (214, 224, 235)
WHITE = (255, 255, 255)
SHADOW = (130, 150, 180, 60)

VARIANTS = {
    "flight": {
        "name": "AGILAB FLIGHT-TELEMETRY PROJECT",
        "title": "One control path from idea to results",
        "subtitle": "Flight-telemetry project explainer for YouTube and public demo assets",
        "footer": "PROJECT -> ORCHESTRATE -> WORKFLOW -> ANALYSIS",
        "final_caption": "AGILAB keeps one app on one coherent path from setup to evidence.",
        "stage_captions": [
            "PROJECT keeps the flight-telemetry context and settings together.",
            "ORCHESTRATE removes shell glue and packages the run path.",
            "WORKFLOW makes the execution replayable and inspectable.",
            "ANALYSIS ends on a visible result, not on raw logs.",
        ],
        "boxes": [
            ("PROJECT", "select flight-\ntelemetry settings", (85, 212, 240, 482), (217, 239, 255)),
            ("ORCHESTRATE", "package,\nrun,\nvalidate", (327, 182, 510, 482), (230, 223, 255)),
            ("WORKFLOW", "replay steps\nand inspect flow", (540, 152, 770, 482), (255, 244, 212)),
            ("ANALYSIS", "open views\non results", (800, 122, 1115, 482), (255, 230, 236)),
        ],
    },
    "uav_queue": {
        "name": "AGILAB UAV QUEUE DEMO",
        "title": "Turn a queueing experiment into a reproducible workflow",
        "subtitle": "UAV routing and queue analysis explainer for technical demos",
        "footer": "PROJECT -> ORCHESTRATE -> WORKFLOW -> ANALYSIS",
        "final_caption": "AGILAB turns a queueing experiment into a controlled and analyzable workflow.",
        "stage_captions": [
            "PROJECT locks the scenario file and routing policy in one app context.",
            "ORCHESTRATE runs the queueing experiment without ad-hoc execution glue.",
            "WORKFLOW makes the simulation step explicit and replayable.",
            "ANALYSIS lands on queue buildup, drops, and routing evidence.",
        ],
        "boxes": [
            ("PROJECT", "pick scenario\nand routing policy", (85, 212, 255, 482), (221, 241, 255)),
            ("ORCHESTRATE", "run the\nqueueing\nexperiment", (342, 182, 545, 482), (233, 226, 255)),
            ("WORKFLOW", "capture the\nreplayable\nstep", (580, 152, 805, 482), (255, 243, 209)),
            ("ANALYSIS", "inspect queues,\ndrops,\nroutes", (835, 122, 1115, 482), (255, 231, 236)),
        ],
    },
}


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def ease_in_out(t: float) -> float:
    return 0.5 - 0.5 * math.cos(math.pi * max(0.0, min(1.0, t)))


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNS.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size, index=1 if bold else 0)
        except Exception:
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                continue
    return ImageFont.load_default()


TITLE_FONT = load_font(54, bold=True)
SUBTITLE_FONT = load_font(27)
LABEL_FONT = load_font(16, bold=True)
BOX_TITLE_FONT = load_font(24, bold=True)
BOX_BODY_FONT = load_font(19)
CALLOUT_FONT = load_font(21, bold=True)
FOOTER_FONT = load_font(19)


def gradient_background() -> Image.Image:
    arr = np.zeros((H, W, 3), dtype=np.uint8)
    for y in range(H):
        t = y / (H - 1)
        arr[y, :, 0] = int(lerp(BG_TOP[0], BG_BOTTOM[0], t))
        arr[y, :, 1] = int(lerp(BG_TOP[1], BG_BOTTOM[1], t))
        arr[y, :, 2] = int(lerp(BG_TOP[2], BG_BOTTOM[2], t))
    return Image.fromarray(arr, "RGB")


def rounded(draw: ImageDraw.ImageDraw, xy, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def multiline_center(draw: ImageDraw.ImageDraw, box, text: str, font, fill, spacing=6):
    x0, y0, x1, y1 = box
    bbox = draw.multiline_textbbox((0, 0), text, font=font, align="center", spacing=spacing)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = x0 + (x1 - x0 - tw) / 2
    y = y0 + (y1 - y0 - th) / 2
    draw.multiline_text((x, y), text, font=font, fill=fill, align="center", spacing=spacing)


def box_center(box):
    x0, y0, x1, y1 = box
    return ((x0 + x1) / 2, (y0 + y1) / 2)


def stage_caption(variant: dict, stage: int) -> str:
    return variant["stage_captions"][stage]


def final_caption(variant: dict) -> str:
    return variant["final_caption"]


def draw_arrow(draw: ImageDraw.ImageDraw, a, b, color, width=5):
    draw.line([a, b], fill=color, width=width)
    ang = math.atan2(b[1] - a[1], b[0] - a[0])
    head = 12
    for delta in (2.5, -2.5):
        p = (
            b[0] - head * math.cos(ang + delta),
            b[1] - head * math.sin(ang + delta),
        )
        draw.line([b, p], fill=color, width=width)


def render_frame(t: float, variant_key: str) -> Image.Image:
    variant = VARIANTS[variant_key]
    img = gradient_background()
    draw = ImageDraw.Draw(img)

    draw.rounded_rectangle((0, 0, W - 1, H - 1), radius=32, outline=(225, 232, 240), width=1)
    rounded(draw, (70, 54, 318, 96), 18, fill=INK)
    draw.text((194, 67), variant["name"], font=LABEL_FONT, fill=WHITE, anchor="mm")

    title_alpha = 0.35 + 0.65 * ease_in_out(min(1.0, t / 0.18))
    title_fill = tuple(int(lerp(240, c, title_alpha)) for c in INK)
    sub_fill = tuple(int(lerp(244, c, title_alpha)) for c in MUTED)
    draw.text((70, 126), variant["title"], font=TITLE_FONT, fill=title_fill)
    draw.text((70, 182), variant["subtitle"], font=SUBTITLE_FONT, fill=sub_fill)

    # Progress stages across main cards.
    active = min(3, int(max(0.0, t - 0.18) / 0.18))
    pulse = 0.5 + 0.5 * math.sin(2 * math.pi * t * 1.4)

    centers = []
    for idx, (label, body, box, fill) in enumerate(variant["boxes"]):
        x0, y0, x1, y1 = box
        centers.append(box_center(box))
        shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        sdraw = ImageDraw.Draw(shadow)
        rounded(sdraw, (x0, y0 + 8, x1, y1 + 8), 28, fill=SHADOW)
        shadow = shadow.filter(ImageFilter.GaussianBlur(8))
        img.alpha_composite(shadow) if img.mode == "RGBA" else img.paste(shadow, (0, 0), shadow)

        fill_now = fill
        outline = LINE
        width = 3
        if idx == active:
            boost = 10 + int(16 * pulse)
            fill_now = tuple(min(255, c + boost) for c in fill)
            outline = ACCENT if idx in (1, 2) else ACCENT_2
            width = 5
        elif idx < active:
            outline = (154, 179, 201)
        rounded(draw, box, 28, fill=fill_now, outline=outline, width=width)
        draw.text((x0 + 26, y0 + 34), label, font=BOX_TITLE_FONT, fill=INK)
        multiline_center(draw, (x0 + 18, y0 + 106, x1 - 18, y1 - 28), body, BOX_BODY_FONT, MUTED)

    for i in range(len(centers) - 1):
        draw_arrow(draw, (centers[i][0] + 78, centers[i][1]), (centers[i + 1][0] - 88, centers[i + 1][1]), (124, 147, 170), 4)

    # Moving dot
    path_points = centers
    seg_progress = max(0.0, min(0.999, (t - 0.18) / 0.72)) * (len(path_points) - 1)
    seg = min(len(path_points) - 2, max(0, int(seg_progress)))
    local_t = seg_progress - seg
    a = path_points[seg]
    b = path_points[seg + 1]
    x = lerp(a[0] + 78, b[0] - 88, local_t)
    y = lerp(a[1], b[1], local_t)
    r = 14
    draw.ellipse((x - r, y - r, x + r, y + r), fill=ACCENT, outline=WHITE, width=3)

    # Bottom callout
    rounded(draw, (70, 538, 1130, 618), 24, fill=(255, 250, 244), outline=(223, 214, 204), width=2)
    caption = stage_caption(variant, active) if t < 0.90 else final_caption(variant)
    draw.text((600, 570), caption, font=CALLOUT_FONT, fill=ACCENT_2, anchor="mm")
    draw.text((600, 604), variant["footer"], font=FOOTER_FONT, fill=ACCENT, anchor="mm")

    return img.convert("RGB")


def build_animation(
    out_gif: Path,
    out_mp4: Path,
    out_poster: Path,
    *,
    variant_key: str = "flight",
    fps: int = 12,
    seconds: float = 6.0,
) -> None:
    import imageio.v3 as iio

    frame_count = int(fps * seconds)
    frames = [np.array(render_frame(i / (frame_count - 1), variant_key)) for i in range(frame_count)]
    out_gif.parent.mkdir(parents=True, exist_ok=True)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    out_poster.parent.mkdir(parents=True, exist_ok=True)
    iio.imwrite(out_gif, frames, duration=1000 / fps, loop=0)
    iio.imwrite(out_mp4, frames, fps=fps, codec="libx264", pixelformat="yuv420p")
    Image.fromarray(frames[min(len(frames) - 1, int(frame_count * 0.55))]).save(out_poster)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a self-generated AGILAB explainer GIF/MP4.")
    parser.add_argument("--variant", choices=sorted(VARIANTS.keys()), default="flight")
    parser.add_argument("--gif", default="artifacts/demo_media/agilab_explainer.gif")
    parser.add_argument("--mp4", default="artifacts/demo_media/agilab_explainer.mp4")
    parser.add_argument("--poster", default="artifacts/demo_media/agilab_explainer_poster.png")
    parser.add_argument("--fps", type=int, default=12)
    parser.add_argument("--seconds", type=float, default=6.0)
    args = parser.parse_args()

    build_animation(
        Path(args.gif),
        Path(args.mp4),
        Path(args.poster),
        variant_key=args.variant,
        fps=args.fps,
        seconds=args.seconds,
    )
    print(Path(args.gif).resolve())
    print(Path(args.mp4).resolve())
    print(Path(args.poster).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
