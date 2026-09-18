"""Public deployment must use fixed verified code and exclude local run details."""
import importlib.util
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from agilab.agent_runtime import notebook_showcase as showcase


def test_public_bundle_has_verified_hashes_and_no_private_run_paths():
    report = showcase.load_report()
    assert report["status"] == "passed"
    assert "project" not in report
    assert "/Users/" not in json.dumps(report)
    assert not (showcase.DEMO_ROOT / "agent").exists()
    assert not (showcase.DEMO_ROOT / "request.txt").exists()


def test_public_app_renders_and_depth_changes_without_provider():
    at = AppTest.from_file(showcase.__file__, default_timeout=30).run()
    assert not at.exception
    assert any(title.value == "Iris decision lab" for title in at.title)
    assert len(at.number_input) == 4
    assert all(button.label != "Build my app" for button in at.button)
    at.slider[0].set_value(4).run()
    assert not at.exception


def test_export_rejects_tampered_verified_code(tmp_path):
    script = Path(__file__).parents[1] / "tools" / "demos" / "export_notebook_agent_demo.py"
    spec = importlib.util.spec_from_file_location("export_demo_test", script)
    exporter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exporter)
    report = showcase.load_report()
    (tmp_path / "result.json").write_text(json.dumps(report))
    project = tmp_path / "decision_lab_project"
    project.mkdir()
    (project / "app.py").write_text("tampered")
    with pytest.raises(ValueError, match="Verified artifact changed"):
        exporter.export_demo(tmp_path, tmp_path / "public")


def test_forecast_query_selects_second_demo_and_can_return_to_iris(monkeypatch):
    from agilab.agent_runtime import forecast_showcase
    import streamlit as st

    monkeypatch.setattr(forecast_showcase, "render", lambda: st.title("Forecast fixture"))
    at = AppTest.from_file(showcase.__file__, default_timeout=30)
    at.query_params["demo"] = "forecast"
    at.run()
    assert not at.exception
    assert [title.value for title in at.title] == ["Forecast fixture"]
    assert at.segmented_control(key="demo").value == "forecast"
    at.segmented_control(key="demo").set_value("iris").run()
    assert not at.exception
    assert any(title.value == "Iris decision lab" for title in at.title)
    at.slider[0].set_value(4).run()
    assert not at.exception


def test_unknown_demo_query_falls_back_to_iris():
    at = AppTest.from_file(showcase.__file__, default_timeout=30)
    at.query_params["demo"] = "unknown"
    at.run()
    assert not at.exception
    assert any(title.value == "Iris decision lab" for title in at.title)



def test_iris_only_distribution_reports_forecast_unavailability(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "agilab.agent_runtime.forecast_showcase", None)
    at = AppTest.from_file(showcase.__file__, default_timeout=30)
    at.query_params["demo"] = "forecast"
    at.run()
    assert not at.exception
    assert at.error[0].value == "Forecast demo unavailable in this distribution."
    at.segmented_control(key="demo").set_value("iris").run()
    assert not at.exception
    assert any(title.value == "Iris decision lab" for title in at.title)
