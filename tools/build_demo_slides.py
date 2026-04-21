#!/usr/bin/env python3
from __future__ import annotations

from io import BytesIO
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_AUTO_SHAPE_TYPE
from pptx.util import Inches, Pt


ROOT = Path(__file__).resolve().parents[1]
FLIGHT_DECK_NAME = "AGILAB_Flight_First_Proof_Slides.pptx"
UAV_DECK_NAME = "AGILAB_UAV_Full_Tour_Slides.pptx"
ARTIFACT_DIR = ROOT / "artifacts" / "demo_media"
DOCS_DIR = ROOT / "docs" / "source"

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


def _canonical_docs_dir() -> Path | None:
    canonical = ROOT.parent / "thales_agilab" / "docs" / "source"
    return canonical if canonical.parent.exists() else None


def _default_output_targets(filename: str, artifact_name: str) -> list[Path]:
    targets = [ARTIFACT_DIR / artifact_name, DOCS_DIR / filename]
    canonical = _canonical_docs_dir()
    if canonical is not None:
        targets.append(canonical / filename)
    return targets


def _write_presentation(prs: Presentation, output_targets: list[Path]) -> list[Path]:
    buffer = BytesIO()
    prs.save(buffer)
    payload = buffer.getvalue()
    written: list[Path] = []
    for output in output_targets:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(payload)
        written.append(output)
    return written


def build_flight_deck(*, output_targets: list[Path] | None = None) -> list[Path]:
    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H

    page_shots = ROOT / "docs" / "source" / "_static" / "page-shots"
    core_overview = page_shots / "core-pages-overview.png"
    project_page = page_shots / "project-page.png"
    orchestrate_page = page_shots / "orchestrate-page.png"
    analysis_page = page_shots / "analysis-page.png"

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_full_bg(slide)
    add_title(slide, "AGILAB First Proof", "Slideshow companion for the newcomer-safe `flight_project` story")
    add_panel(slide, Inches(0.7), Inches(1.6), Inches(12), Inches(4.9))
    add_bullets(
        slide,
        Inches(1.0),
        Inches(2.0),
        Inches(11.4),
        Inches(3.8),
        [
            "Goal: prove the safest AGILAB path once before branching into notebooks, clusters, or packaged installs.",
            "Scope: PROJECT -> ORCHESTRATE -> ANALYSIS on `flight_project`.",
            "Keep the message narrow: one app, one local path, one visible result.",
        ],
        22,
    )

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_full_bg(slide)
    add_title(slide, "Why This Path", "The first proof is deliberately smaller than the full tour")
    add_image(slide, core_overview, Inches(0.7), Inches(1.5), Inches(6.2), Inches(3.73))
    add_panel(slide, Inches(7.2), Inches(1.5), Inches(5.4), Inches(3.5))
    add_bullets(
        slide,
        Inches(7.5),
        Inches(1.9),
        Inches(4.8),
        Inches(2.7),
        [
            "Select the built-in app once and keep its context visible.",
            "Run the local path through ORCHESTRATE without ad-hoc shell glue.",
            "End on visible analysis evidence instead of raw logs.",
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
        ["Narration: this is the newcomer-safe proof that AGILAB can take one app from selection to visible evidence."],
        18,
    )

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_full_bg(slide)
    add_title(slide, "Select And Run", "PROJECT sets the app context; ORCHESTRATE executes the local proof")
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
            "Use `flight_project`: choose it in PROJECT, then INSTALL and EXECUTE in ORCHESTRATE.",
            "Keep the visual story simple and operator-visible.",
        ],
        18,
    )

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_full_bg(slide)
    add_title(slide, "End On Evidence", "ANALYSIS is where the first proof becomes concrete")
    add_image(slide, analysis_page, Inches(0.9), Inches(1.45), Inches(11.5), Inches(4.25))
    add_panel(slide, Inches(0.7), Inches(5.95), Inches(12), Inches(0.85))
    add_bullets(
        slide,
        Inches(1.0),
        Inches(6.12),
        Inches(11.3),
        Inches(0.45),
        [
            "Close the deck on visible output: the point is not just that AGILAB ran, but that it landed on a readable result.",
        ],
        18,
    )

    outputs = output_targets or _default_output_targets(
        FLIGHT_DECK_NAME,
        "agilab_flight_first_proof_slides.pptx",
    )
    return _write_presentation(prs, outputs)


def build_uav_deck(*, output_targets: list[Path] | None = None) -> list[Path]:
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
    add_title(slide, "AGILAB Full Tour", "Slideshow companion for the `uav_relay_queue_project` public workflow story")
    add_panel(slide, Inches(0.7), Inches(1.6), Inches(12), Inches(4.9))
    add_bullets(
        slide,
        Inches(1.0),
        Inches(2.0),
        Inches(11.4),
        Inches(3.8),
        [
            "Goal: show the main AGILAB four-page story without asking the viewer to watch a hosted runtime or replay a video.",
            "Scope: PROJECT -> ORCHESTRATE -> PIPELINE -> ANALYSIS on `uav_relay_queue_project`.",
            "Keep the message stable: replayable workflow plus visible queue or route evidence.",
        ],
        22,
    )

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_full_bg(slide)
    add_title(slide, "The Full Workflow Story", "This is the stronger README and public-tour narrative")
    add_image(slide, core_overview, Inches(0.7), Inches(1.5), Inches(6.15), Inches(3.7))
    add_panel(slide, Inches(7.1), Inches(1.5), Inches(5.5), Inches(3.55))
    add_bullets(
        slide,
        Inches(7.4),
        Inches(1.9),
        Inches(4.9),
        Inches(2.8),
        [
            "Use the four core pages in order, not as isolated screens.",
            "Make the run replayable through PIPELINE, not only executable once.",
            "End on ANALYSIS evidence that a technical audience can interpret quickly.",
        ],
        18,
    )
    add_panel(slide, Inches(0.7), Inches(5.25), Inches(11.9), Inches(1.0))
    add_bullets(
        slide,
        Inches(1.0),
        Inches(5.48),
        Inches(11.3),
        Inches(0.55),
        ["Narration: AGILAB turns a lightweight experiment into a controlled, replayable workflow instead of a one-off script path."],
        18,
    )

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_full_bg(slide)
    add_title(slide, "Project To Pipeline", "PROJECT and ORCHESTRATE establish the run; PIPELINE makes it explicit")
    add_image(slide, project_page, Inches(0.65), Inches(1.55), Inches(4.0), Inches(2.3))
    add_image(slide, orchestrate_page, Inches(4.68), Inches(1.55), Inches(4.0), Inches(2.3))
    add_image(slide, pipeline_page, Inches(8.71), Inches(1.55), Inches(4.0), Inches(2.3))
    add_panel(slide, Inches(0.7), Inches(4.2), Inches(12), Inches(2.15))
    add_bullets(
        slide,
        Inches(1.0),
        Inches(4.5),
        Inches(11.3),
        Inches(1.4),
        [
            "Select `uav_relay_queue_project` in PROJECT and keep the routing scenario visible.",
            "Trigger the run in ORCHESTRATE, then move to PIPELINE to show that the execution path is tracked and replayable.",
        ],
        18,
    )

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_full_bg(slide)
    add_title(slide, "End On Queue Evidence", "ANALYSIS carries the technical payoff of the full tour")
    add_image(slide, core_overview, Inches(0.7), Inches(1.45), Inches(6.0), Inches(3.6))
    add_image(slide, analysis_page, Inches(6.95), Inches(1.45), Inches(5.55), Inches(3.15))
    add_panel(slide, Inches(0.7), Inches(5.45), Inches(12), Inches(1.1))
    add_bullets(
        slide,
        Inches(1.0),
        Inches(5.7),
        Inches(11.3),
        Inches(0.6),
        [
            "The point of the full tour is not breadth for its own sake. It is that AGILAB keeps the workflow explicit all the way to queue or route evidence.",
        ],
        18,
    )

    outputs = output_targets or _default_output_targets(
        UAV_DECK_NAME,
        "agilab_uav_full_tour_slides.pptx",
    )
    return _write_presentation(prs, outputs)


def build() -> dict[str, list[Path]]:
    return {
        "flight": build_flight_deck(),
        "uav": build_uav_deck(),
    }


def main() -> int:
    outputs = build()
    for deck_outputs in outputs.values():
        for output in deck_outputs:
            print(output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
