#!/usr/bin/env python3
from __future__ import annotations

from io import BytesIO
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_AUTO_SHAPE_TYPE
from pptx.util import Inches, Pt


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DECK_NAME = "AGILAB_Demo_Slideshow.pptx"
ARTIFACT_OUT = ROOT / "artifacts" / "demo_media" / "agilab_youtube_demo_pack.pptx"
PUBLIC_OUT = ROOT / "docs" / "source" / PUBLIC_DECK_NAME

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


def add_image(slide, image_path: Path, left, top, width, height) -> None:
    if image_path.exists():
        slide.shapes.add_picture(str(image_path), left, top, width=width, height=height)
    else:
        add_panel(slide, left, top, width, height)
        add_bullets(
            slide,
            left + Inches(0.2),
            top + Inches(0.6),
            width - Inches(0.4),
            Inches(0.8),
            [f"Missing image: {image_path.name}"],
            16,
        )


def _default_output_targets() -> list[Path]:
    targets = [ARTIFACT_OUT, PUBLIC_OUT]
    canonical = ROOT.parent / "thales_agilab" / "docs" / "source" / PUBLIC_DECK_NAME
    if canonical.parent.exists():
        targets.append(canonical)
    return targets


def build(*, output_targets: list[Path] | None = None) -> list[Path]:
    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H

    page_shots = ROOT / "docs" / "source" / "_static" / "page-shots"
    core_overview = page_shots / "core-pages-overview.png"
    project_page = page_shots / "project-page.png"
    orchestrate_page = page_shots / "orchestrate-page.png"
    pipeline_page = page_shots / "pipeline-page.png"
    analysis_page = page_shots / "analysis-page.png"

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_full_bg(slide)
    add_title(slide, "AGILAB Demo Slideshow", "Public screenshots deck for README, docs, and narrated walkthroughs")
    add_panel(slide, Inches(0.7), Inches(1.6), Inches(12), Inches(4.9))
    add_bullets(
        slide,
        Inches(1.0),
        Inches(2.0),
        Inches(11.4),
        Inches(3.8),
        [
            "Built from tracked AGILAB screenshots, not local-only demo captures.",
            "Best used as a skimmable companion to the short video demos.",
            "Keep the message stable: one app, one control path, one visible result.",
        ],
        22,
    )

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_full_bg(slide)
    add_title(slide, "AGILAB Core Flow", "The stable four-page story used in the public intro")
    add_image(slide, core_overview, Inches(0.7), Inches(1.5), Inches(6.2), Inches(3.73))
    add_panel(slide, Inches(7.2), Inches(1.5), Inches(5.4), Inches(3.5))
    add_bullets(
        slide,
        Inches(7.5),
        Inches(1.9),
        Inches(4.8),
        Inches(2.7),
        [
            "Pages: PROJECT -> ORCHESTRATE -> PIPELINE -> ANALYSIS",
            "Message: AGILAB keeps the app, runtime path, and visible result aligned.",
            "Use this slide as the orientation frame before drilling into screenshots.",
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
    add_title(slide, "First Proof Path", "PROJECT and ORCHESTRATE in the newcomer-safe local flow")
    add_image(slide, project_page, Inches(0.7), Inches(1.55), Inches(5.75), Inches(3.27))
    add_image(slide, orchestrate_page, Inches(6.85), Inches(1.55), Inches(5.75), Inches(3.27))
    add_panel(slide, Inches(0.7), Inches(5.15), Inches(11.9), Inches(1.2))
    add_bullets(
        slide,
        Inches(1.0),
        Inches(5.4),
        Inches(11.3),
        Inches(0.7),
        [
            "Use `flight_project` for the safe first proof: select the app in PROJECT, then INSTALL and EXECUTE in ORCHESTRATE.",
            "End the spoken story on fresh output and a visible analysis result, not on raw infrastructure logs.",
        ],
        18,
    )

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_full_bg(slide)
    add_title(slide, "Full Tour Path", "PIPELINE and ANALYSIS for the replayable workflow story")
    add_image(slide, pipeline_page, Inches(0.7), Inches(1.55), Inches(5.75), Inches(3.27))
    add_image(slide, analysis_page, Inches(6.85), Inches(1.55), Inches(5.75), Inches(3.27))
    add_panel(slide, Inches(0.7), Inches(1.5), Inches(12), Inches(4.8))
    add_bullets(
        slide,
        Inches(1.0),
        Inches(5.35),
        Inches(11.3),
        Inches(0.8),
        [
            "Use `uav_relay_queue_project` when you want the stronger technical story: explicit replayable steps in PIPELINE and visible evidence in ANALYSIS.",
            "The slideshow should complement the video, not replace the message with new claims.",
        ],
        18,
    )

    outputs = output_targets or _default_output_targets()
    buffer = BytesIO()
    prs.save(buffer)
    payload = buffer.getvalue()
    written: list[Path] = []
    for output in outputs:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(payload)
        written.append(output)
    return written


def main() -> int:
    outputs = build()
    for output in outputs:
        print(output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
