#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_AUTO_SHAPE_TYPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/demo_media/agilab_youtube_demo_pack.pptx"

BG = RGBColor(247, 243, 235)
PANEL = RGBColor(255, 251, 245)
INK = RGBColor(33, 36, 39)
MUTED = RGBColor(91, 98, 104)
ACCENT = RGBColor(184, 87, 36)
ACCENT_2 = RGBColor(45, 92, 122)
LINE = RGBColor(220, 206, 191)

SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)


def add_full_bg(slide) -> None:
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = BG


def add_title(slide, title: str, subtitle: str | None = None) -> None:
    tb = slide.shapes.add_textbox(Inches(0.7), Inches(0.55), Inches(12), Inches(1.1))
    p = tb.text_frame.paragraphs[0]
    r = p.add_run()
    r.text = title
    r.font.size = Pt(28)
    r.font.bold = True
    r.font.color.rgb = ACCENT_2
    if subtitle:
        p2 = tb.text_frame.add_paragraph()
        r2 = p2.add_run()
        r2.text = subtitle
        r2.font.size = Pt(14)
        r2.font.color.rgb = MUTED
        p2.space_before = Pt(4)


def add_panel(slide, left, top, width, height):
    shape = slide.shapes.add_shape(
        MSO_AUTO_SHAPE_TYPE.ROUNDED_RECTANGLE,
        left,
        top,
        width,
        height,
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = PANEL
    shape.line.color.rgb = LINE
    shape.line.width = Pt(1.5)
    return shape


def add_bullets(slide, left, top, width, height, items: list[str], font_size: int = 20) -> None:
    tb = slide.shapes.add_textbox(left, top, width, height)
    tf = tb.text_frame
    tf.word_wrap = True
    for idx, item in enumerate(items):
        p = tf.paragraphs[0] if idx == 0 else tf.add_paragraph()
        p.text = item
        p.level = 0
        p.font.size = Pt(font_size)
        p.font.color.rgb = INK
        p.space_after = Pt(8)


def add_poster(slide, poster: Path, left, top, width, height) -> None:
    if poster.exists():
        slide.shapes.add_picture(str(poster), left, top, width=width, height=height)
    else:
        add_panel(slide, left, top, width, height)
        add_bullets(slide, left + Inches(0.2), top + Inches(0.6), width - Inches(0.4), Inches(0.8), [f"Missing poster: {poster.name}"], 16)


def build() -> Path:
    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H

    flight_poster = ROOT / "artifacts/demo_media/flight/agilab_flight_poster.png"
    uav_poster = ROOT / "artifacts/demo_media/uav_queue/agilab_uav_queue_poster.png"

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_full_bg(slide)
    add_title(slide, "AGILAB YouTube Demo Pack", "Two ready-to-record narratives: onboarding and technical wow")
    add_panel(slide, Inches(0.7), Inches(1.6), Inches(12), Inches(4.9))
    add_bullets(
        slide,
        Inches(1.0),
        Inches(2.0),
        Inches(11.4),
        Inches(3.8),
        [
            "Flight demo: the safe main intro path for newcomers.",
            "UAV queue demo: the more technical path ending on visible queueing evidence.",
            "Both keep the same AGILAB message: one app, one control path, one visible result.",
        ],
        22,
    )

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_full_bg(slide)
    add_title(slide, "Flight Project Demo", "Default product intro")
    add_poster(slide, flight_poster, Inches(0.7), Inches(1.5), Inches(6.2), Inches(3.5))
    add_panel(slide, Inches(7.2), Inches(1.5), Inches(5.4), Inches(3.5))
    add_bullets(
        slide,
        Inches(7.5),
        Inches(1.9),
        Inches(4.8),
        Inches(2.7),
        [
            "Path: PROJECT -> ORCHESTRATE -> PIPELINE -> ANALYSIS",
            "Message: one app, one controlled path from setup to result.",
            "Use this for the first AGILAB video.",
        ],
        18,
    )
    add_panel(slide, Inches(0.7), Inches(5.2), Inches(11.9), Inches(1.1))
    add_bullets(
        slide,
        Inches(1.0),
        Inches(5.45),
        Inches(11.3),
        Inches(0.6),
        ["Narration: AGILAB packages, runs, replays, and ends on visible evidence instead of shell glue and raw logs."],
        18,
    )

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_full_bg(slide)
    add_title(slide, "UAV Queue Demo", "Technical and memorable analysis-driven story")
    add_poster(slide, uav_poster, Inches(0.7), Inches(1.5), Inches(6.2), Inches(3.5))
    add_panel(slide, Inches(7.2), Inches(1.5), Inches(5.4), Inches(3.5))
    add_bullets(
        slide,
        Inches(7.5),
        Inches(1.9),
        Inches(4.8),
        Inches(2.7),
        [
            "Path: PROJECT -> ORCHESTRATE -> PIPELINE -> ANALYSIS",
            "Show scenario, routing policy, queue buildup, drops, and route usage.",
            "Use this for the more technical YouTube demo.",
        ],
        18,
    )
    add_panel(slide, Inches(0.7), Inches(5.2), Inches(11.9), Inches(1.1))
    add_bullets(
        slide,
        Inches(1.0),
        Inches(5.45),
        Inches(11.3),
        Inches(0.6),
        ["Narration: AGILAB turns a lightweight queueing experiment into a controlled, replayable, and analyzable workflow."],
        18,
    )

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_full_bg(slide)
    add_title(slide, "Capture Notes", "What still requires manual screen capture")
    add_panel(slide, Inches(0.7), Inches(1.5), Inches(12), Inches(4.8))
    add_bullets(
        slide,
        Inches(1.0),
        Inches(1.9),
        Inches(11.3),
        Inches(3.8),
        [
            "Generated assets can be used as teaser video/poster/slides immediately.",
            "Live UI capture still needs a manual recording pass on PROJECT, ORCHESTRATE, PIPELINE, and ANALYSIS.",
            "Use the matching track only: do not mix flight and UAV queue in one short demo.",
        ],
        22,
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUT)
    return OUT


def main() -> int:
    out = build()
    print(out.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
