"""Public deployment must use fixed verified code and exclude local run details."""
import importlib.util
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from agilab.demos import notebook_showcase as showcase


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


def test_every_selectable_demo_shows_build_evidence_without_expanding(monkeypatch, tmp_path):
    """Read the real selector so a newly added demo cannot skip this contract."""
    from agilab.demos import forecast_showcase

    # Keep real receipt verification and presentation; avoid network/model inference.
    monkeypatch.setattr(forecast_showcase, "_prepare_model", lambda _path: tmp_path)
    monkeypatch.setattr(forecast_showcase, "_validate_model", lambda path: path)
    monkeypatch.setattr(forecast_showcase, "_run_verified_app", lambda _payload, _path, **_kwargs: None)
    initial = AppTest.from_file(showcase.__file__, default_timeout=30).run()
    assert not initial.exception and not initial.error
    assert initial.segmented_control(key="demo").options == list(showcase.DEMO_LABELS.values())
    for demo in showcase.DEMO_LABELS:
        at = AppTest.from_file(showcase.__file__, default_timeout=30)
        at.query_params["demo"] = demo
        at.run()
        assert not at.exception and not at.error, demo
        assert at.segmented_control(key="demo").value == demo
        title_label = "Built by OpenCode with local Qwen" if demo.endswith("_rtx") else "Built by an autonomous agent"
        timing_label = "Build duration" if demo.endswith("_rtx") else "Autonomous build"
        assert sum(title.value == title_label for title in at.main.title) == 1, demo
        timings = [item for item in at.main.metric if item.label == timing_label]
        assert len(timings) == 1, demo
        assert timings[0].value.endswith(" min") and float(timings[0].value[:-4]) > 0, demo
        assert any(item.label == "AGILAB workflow stages" for item in at.main.metric), demo
        # AppTest 1.58 represents an expander with an icon as a Status block.
        disclosures = [*at.main.expander, *at.main.get("status")]
        builders = [item for item in disclosures if item.label == "Build from your own notebook"]
        assert len(builders) == 1, demo
        assert any("agilab-notebook-demo --ui" in item.value for item in builders[0].code), demo
        assert any("uv tool install" in item.value for item in builders[0].code), demo
        assert any("This public Space runs the completed app" in item.value for item in at.main.caption), demo
        for hidden_container in (*at.expander, *at.get("status"), *at.get("tab"), at.sidebar):
            assert all(title.value != title_label for title in hidden_container.title), demo
            assert all(item.label != timing_label for item in hidden_container.metric), demo
            assert all(
                item is hidden_container or getattr(item, "label", None) != "Build from your own notebook"
                for item in hidden_container
            ), demo


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
    from agilab.demos import forecast_showcase
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

    monkeypatch.setitem(sys.modules, "agilab.demos.forecast_showcase", None)
    at = AppTest.from_file(showcase.__file__, default_timeout=30)
    at.query_params["demo"] = "forecast"
    at.run()
    assert not at.exception
    assert at.error[0].value == "Forecast demo unavailable in this distribution."
    at.segmented_control(key="demo").set_value("iris").run()
    assert not at.exception
    assert any(title.value == "Iris decision lab" for title in at.title)


def test_local_iris_defaults_winners_and_selected_model_predictions():
    """Published controls must use all four measurements and the selected estimator."""
    import numpy as np
    from sklearn.datasets import load_iris
    from sklearn.metrics import accuracy_score
    from sklearn.model_selection import train_test_split

    spec = importlib.util.spec_from_file_location(
        "iris_prediction_reference", showcase.LOCAL_DEMO_ROOT / "models.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    iris = load_iris()
    X_train, X_test, y_train, y_test = train_test_split(
        iris.data, iris.target, test_size=0.3, stratify=iris.target, random_state=42
    )
    at = AppTest.from_file(showcase.__file__, default_timeout=60)
    at.query_params["demo"] = "iris_local"
    at.run()
    assert not at.exception and not at.error
    assert [field.value for field in at.number_input] == [5.1, 3.5, 1.4, 0.2]

    for depth in (1, 4):
        at.slider[0].set_value(depth).run()
        assert not at.exception
        models = module.build_models(max_depth=depth, seed=42)
        scores = {}
        for name, estimator in models.items():
            estimator.fit(X_train, y_train)
            scores[name] = accuracy_score(y_test, estimator.predict(X_test))
        table = next(
            item.value
            for item in at.dataframe
            if set(item.value.columns) == {"Model", "Train Acc", "Test Acc"}
        ).set_index("Model")["Test Acc"]
        assert set(table.index) == set(scores)
        for name, score in scores.items():
            assert table[name] == pytest.approx(score)
        captions = " ".join(
            item.value
            for collection in (at.caption, at.info, at.warning)
            for item in collection
        )
        best = max(scores.values())
        assert "N/A" not in captions
        assert "exploratory" in captions.lower() and "untouched" in captions.lower()
        assert all(name in captions for name, score in scores.items() if score == best)

        for name, estimator in models.items():
            at.selectbox[0].select(name)
            for measurements in ([5.1, 3.5, 1.4, 0.2], [6.5, 3.0, 5.2, 2.0]):
                for field, value in zip(at.number_input, measurements, strict=True):
                    field.set_value(value)
                next(
                    button for button in at.button if button.label == "Predict"
                ).click().run()
                assert not at.exception and not at.error
                expected = iris.target_names[
                    estimator.predict(np.array([measurements]))[0]
                ]
                assert any(
                    f"**{name}** predicts: *Iris {expected}*" in item.value
                    for item in at.success
                )
                assert any("uncalibrated" in item.value for item in at.caption)


def test_public_iris_confusion_matrix_annotations_match_cells(monkeypatch):
    """The displayed count must belong to its true-row/predicted-column cell."""
    from matplotlib.axes import Axes

    annotations = []
    original_text = Axes.text

    def record_text(axes, x, y, text, *args, **kwargs):
        if axes.images:
            matrix = axes.images[0].get_array()
            if matrix.shape == (3, 3) and x in (0, 1, 2) and y in (0, 1, 2):
                try:
                    count = float(text)
                except (TypeError, ValueError):
                    pass
                else:
                    annotations.append((x, y, count, float(matrix[int(y), int(x)])))
        return original_text(axes, x, y, text, *args, **kwargs)

    monkeypatch.setattr(Axes, "text", record_text)
    at = AppTest.from_file(showcase.__file__, default_timeout=60)
    at.query_params["demo"] = "iris_local"
    at.run()
    assert not at.exception and not at.error
    assert len(annotations) == 9
    assert all(displayed == expected for _, _, displayed, expected in annotations)
    assert any(x != y and expected > 0 for x, y, _, expected in annotations)


def test_both_iris_flavours_keep_distinct_verified_bundles_and_switch_cleanly():
    import io
    import zipfile

    original = showcase.load_report()
    local = showcase.load_report(showcase.LOCAL_DEMO_ROOT)
    assert original["run_id"] == '20260918T105634Z-d0baf9b5'
    assert local["run_id"] != original["run_id"]
    assert local["build_model"]["id"] == "ddalcu/Qwen3.8-27B-MLX-Serve-4bit"
    assert local["build_model"]["execution"] == "local"
    for root in (showcase.DEMO_ROOT, showcase.LOCAL_DEMO_ROOT):
        with zipfile.ZipFile(io.BytesIO(showcase.download_bundle(root))) as bundle:
            assert bundle.read("app.py") == (root / "app.py").read_bytes()
            assert json.loads(bundle.read("result.json")) == showcase.load_report(root)

    at = AppTest.from_file(showcase.__file__, default_timeout=60).run()
    for key, report, label in (
        ("iris", original, "GPT-6 Astra"),
        ("iris_local", local, "Qwen 3.8 27B"),
        ("iris", original, "GPT-6 Astra"),
    ):
        at.segmented_control(key="demo").set_value(key).run()
        assert not at.exception and not at.error
        assert any(label in item.value for item in at.caption)
        assert any(report["run_id"] in item.value for item in at.caption)
        assert len(at.number_input) == 4


def test_local_iris_tamper_fails_closed_without_affecting_original(tmp_path):
    import shutil

    shutil.copytree(showcase.LOCAL_DEMO_ROOT, tmp_path / "local")
    (tmp_path / "local/app.py").write_text("raise AssertionError('unverified')")
    with pytest.raises(ValueError, match="Demo artifact changed since verification"):
        showcase.load_report(tmp_path / "local")
    assert showcase.load_report()["status"] == "passed"
