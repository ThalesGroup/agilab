from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path("tools/docs_diagram_wording_check.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("docs_diagram_wording_check_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_current_docs_diagrams_do_not_use_deprecated_public_wording() -> None:
    module = _load_module()

    assert module.collect_violations(Path("docs/source")) == []


def test_generic_tour_diagrams_reject_app_specific_demo_names(tmp_path: Path) -> None:
    module = _load_module()
    diagram = tmp_path / "diagrams" / "agilab_readme_tour.svg"
    diagram.parent.mkdir(parents=True)
    diagram.write_text("<svg><text>Use the built-in UAV Relay Queue demo</text></svg>", encoding="utf-8")

    violations = module.collect_violations(tmp_path)

    assert len(violations) == 1
    assert violations[0].rule == "generic-tour-diagrams-must-stay-app-agnostic"
    assert violations[0].phrase == "UAV Relay Queue"


def test_diagram_wording_check_rejects_deprecated_decision_labels(tmp_path: Path) -> None:
    module = _load_module()
    diagram = tmp_path / "diagrams" / "card.svg"
    diagram.parent.mkdir(parents=True)
    diagram.write_text("<svg><title>Mission Decision AGILAB demo card</title></svg>", encoding="utf-8")

    violations = module.collect_violations(tmp_path)

    assert len(violations) == 1
    assert violations[0].rule == "global-deprecated-diagram-wording"
    assert violations[0].suggestion == "Decision Evidence AGILAB demo card"
