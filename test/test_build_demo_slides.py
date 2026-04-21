from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from pptx import Presentation


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "build_demo_slides.py"
MODULE_SPEC = importlib.util.spec_from_file_location("tools.build_demo_slides", MODULE_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
demo_slides = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = demo_slides
MODULE_SPEC.loader.exec_module(demo_slides)


def test_build_demo_slides_writes_a_public_deck(tmp_path: Path) -> None:
    out = tmp_path / "AGILAB_Demo_Slideshow.pptx"

    written = demo_slides.build(output_targets=[out])

    assert written == [out]
    assert out.exists()
    prs = Presentation(out)
    assert len(prs.slides) == 4
    titles = []
    for slide in prs.slides:
        slide_text = "\n".join(shape.text for shape in slide.shapes if hasattr(shape, "text"))
        titles.append(slide_text)
    assert any("AGILAB Demo Slideshow" in text for text in titles)
    assert any("First Proof Path" in text for text in titles)
    assert any("Full Tour Path" in text for text in titles)
