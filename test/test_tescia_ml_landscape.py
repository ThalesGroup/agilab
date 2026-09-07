from __future__ import annotations

import importlib
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest


APP_SRC = (
    Path(__file__).resolve().parents[1]
    / "src/agilab/apps/builtin/tescia_diagnostic_project/src"
)


@pytest.fixture
def surface(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(APP_SRC))
    module = importlib.import_module("tescia_diagnostic.ui.app_surface")
    monkeypatch.setattr(module, "_runtime_context", lambda _: (None, None))
    monkeypatch.setattr(module, "classroom_artifact_dirs", lambda *a, **k: [tmp_path])
    return module


def test_landscape_modules_have_scored_exercises_and_accessible_figures(surface):
    from tescia_diagnostic.domain.learning import (
        load_ml_landscape,
        ml_landscape_svg,
        probability_density_svg,
    )

    guide = load_ml_landscape()
    cases = {case["case_id"]: case for case in surface.load_cases()}
    assert guide["coverage_entry_count"] == 55
    assert {module["id"] for module in guide["modules"]} == {
        "taxonomy",
        "supervised",
        "ensembles",
        "clustering",
        "projection",
        "density",
        "probability",
        "representation",
        "architectures",
        "optimization",
        "evaluation",
        "adaptation",
    }
    assert len({module["case_id"] for module in guide["modules"]}) == 12
    for module in guide["modules"]:
        case = cases[module["case_id"]]
        assert case["learning_track"] == "data_science_2026"
        report = surface.score_student_submission(case, case["student_answer"])
        assert report["student_score"] >= 85
        wrong = {
            **case["student_answer"],
            "root_cause": case["proposed_diagnosis"],
            "selected_fix_id": case["candidate_fixes"][1]["id"],
            "evidence_ids": [],
            "regression_test_ids": [],
        }
        assert (
            surface.score_student_submission(case, wrong)["student_score"]
            < report["student_score"]
        )

    for svg in (ml_landscape_svg(), probability_density_svg()):
        root = ET.fromstring(svg)
        assert root.get("role") == "img"
        assert root.find("{http://www.w3.org/2000/svg}title").text
        assert root.find("{http://www.w3.org/2000/svg}desc").text
        assert not root.findall(".//{http://www.w3.org/2000/svg}image")


def test_ml_exercise_selection_and_scoring_survive_learning_path_switches(surface):
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string(
        "from tescia_diagnostic.ui.app_surface import render\nrender(mode='analysis')",
        default_timeout=30,
    ).run()
    assert not app.exception
    app.segmented_control(key="tescia_learning_track").set_value(
        "data_science_2026"
    ).run()
    assert not app.exception
    app.selectbox(key="tescia_ml_family").select("density").run()
    app.button(key="tescia_ml_select_exercise").click().run()
    assert not app.exception
    assert app.selectbox(key="tescia_answer_case").value == "ml_landscape_2026_density"
    assert any("Worked example" in info.value for info in app.info)

    app.button(key="tescia_answer_evaluate").click().run()
    assert not app.exception
    worked_score = next(
        float(m.value) for m in app.metric if m.label == "Student score"
    )
    app.text_input(key="tescia_answer_fix_ml_landscape_2026_density").set_value(
        "clip_density_to_one"
    )
    app.text_input(key="tescia_answer_evidence_ml_landscape_2026_density").set_value("")
    app.button(key="tescia_answer_evaluate").click().run()
    assert not app.exception
    wrong_score = next(float(m.value) for m in app.metric if m.label == "Student score")
    assert wrong_score < worked_score

    app.segmented_control(key="tescia_learning_track").set_value(
        "mathematics_2026"
    ).run()
    assert not app.exception
    assert app.selectbox(key="tescia_answer_case").value.startswith("math_2026_")
    app.segmented_control(key="tescia_learning_track").set_value(
        "data_science_2026"
    ).run()
    app.selectbox(key="tescia_ml_family").select("ensembles").run()
    app.button(key="tescia_ml_select_exercise").click().run()
    assert not app.exception
    assert (
        app.selectbox(key="tescia_answer_case").value == "ml_landscape_2026_ensembles"
    )
