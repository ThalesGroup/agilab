"""The forecast showcase only exposes complete, hash-verified public artifacts."""
import hashlib
import io
import json
import os
import sys
from types import ModuleType
import zipfile

import pytest
from streamlit.testing.v1 import AppTest

from agilab.agent_runtime import forecast_showcase as showcase


@pytest.fixture
def hub_boundary(monkeypatch):
    """Provide only the external API used by provisioning, without Hub installed."""
    hub = ModuleType("huggingface_hub")
    hub.__path__ = []
    errors = ModuleType("huggingface_hub.errors")

    class LocalEntryNotFoundError(FileNotFoundError):
        pass

    def unexpected_download(**_kwargs):
        raise AssertionError("Tests must explicitly mock model downloads")

    errors.LocalEntryNotFoundError = LocalEntryNotFoundError
    hub.errors = errors
    hub.snapshot_download = unexpected_download
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)
    monkeypatch.setitem(sys.modules, "huggingface_hub.errors", errors)
    return hub


@pytest.fixture
def local_model(tmp_path, monkeypatch):
    root = tmp_path / "model"
    root.mkdir()
    files = {"config.json": b'{"model_type": "fixture"}', "model.safetensors": b"fixture weights"}
    for name, data in files.items():
        (root / name).write_bytes(data)
    monkeypatch.setattr(showcase, "MODEL_HASHES", {
        name: hashlib.sha256(data).hexdigest() for name, data in files.items()
    })
    return root


@pytest.fixture
def demo_bundle(tmp_path, monkeypatch, local_model):
    monkeypatch.setattr(showcase, "_prepare_model", lambda _path: local_model)
    tmp_path = tmp_path / "public-demo"
    tmp_path.mkdir()
    contents = {
        "app.py": (
            "import streamlit as st\nfrom forecast_core import VALUE\n"
            "st.title('Forecast controls')\n"
            "horizon = st.slider('Forecast horizon', 1, 7, 3, key='forecast_horizon')\n"
            "st.metric('Forecast value', VALUE + horizon)\n"
        ),
        "forecast_core.py": "VALUE = 7\n",
        "solution.ipynb": '{"nbformat": 4, "cells": []}\n',
        "lab_stages.toml": "[forecast_project]\n",
        "LICENSE": "Apache-2.0 test fixture\n",
        "data/predictions.json": '{"forecast": [10, 11]}\n',
    }
    for name, content in contents.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    report = {
        "schema": "agilab.notebook_agent.public_demo.v1",
        "status": "passed",
        "demo": {
            "title": "Forecast lab",
            "description": "Explore recorded forecast results.",
            "request": "Compare forecasts and a baseline.",
        },
        "source": {
            "repository": "example/forecast",
            "commit": "a" * 40,
            "url": "https://github.com/example/forecast/blob/" + "a" * 40 + "/demo.ipynb",
            "license": "Apache-2.0",
        },
        "model": {"id": showcase.MODEL_ID, "revision": showcase.MODEL_REVISION, "license": "Apache-2.0"},
        "verification": {"status": "passed", "checks": ["notebook_execution", "forecast_controls"]},
        "verification_scope": "recorded_forecast_and_interface",
        "run_id": "fixture-run",
        "workflow_stages": 3,
        "seconds": 10.5,
        "files": {name: hashlib.sha256(content.encode()).hexdigest() for name, content in contents.items()},
    }
    (tmp_path / "result.json").write_text(json.dumps(report))
    monkeypatch.setattr(showcase, "DEMO_ROOT", tmp_path)
    return tmp_path, report


def _write_report(root, report):
    (root / "result.json").write_text(json.dumps(report))


def _forecast_page():
    from agilab.agent_runtime.forecast_showcase import render
    render()


def test_bundle_download_contains_exact_verified_assets(demo_bundle):
    root, report = demo_bundle
    assert showcase.load_report() == report
    with zipfile.ZipFile(io.BytesIO(showcase.download_bundle())) as archive:
        assert set(archive.namelist()) == set(report["files"]) | {"result.json"}
        for name in archive.namelist():
            assert archive.read(name) == (root / name).read_bytes()


@pytest.mark.parametrize("name", ["app.py", "data/predictions.json", "LICENSE"])
def test_modified_asset_blocks_render_and_download(demo_bundle, name):
    root, _ = demo_bundle
    (root / name).write_text("tampered")
    with pytest.raises(ValueError, match="changed since verification"):
        showcase.download_bundle()
    at = AppTest.from_function(_forecast_page).run()
    assert not at.exception
    assert "changed since verification" in at.error[0].value
    assert not at.title
    assert not at.slider


@pytest.mark.parametrize("name", ["../outside.py", "/outside.py", "./extra.py", "data//extra.py", "data\\extra.py"])
def test_manifest_path_escape_is_rejected(demo_bundle, name):
    root, report = demo_bundle
    report["files"][name] = "0" * 64
    _write_report(root, report)
    with pytest.raises(ValueError, match="Invalid forecast demo artifact path"):
        showcase.load_report()


@pytest.mark.parametrize("name", ["result.json", "forecast_core.py"])
def test_symlink_receipt_or_executable_is_rejected(demo_bundle, tmp_path, name):
    root, _ = demo_bundle
    original = (root / name).read_bytes()
    target = root.parent / (root.name + "-outside-" + name)
    target.write_bytes(original)
    (root / name).unlink()
    (root / name).symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        showcase.load_report()


def test_symlink_in_nested_asset_path_is_rejected(demo_bundle):
    root, _ = demo_bundle
    original = root / "data"
    target = root.parent / (root.name + "-outside-data")
    original.rename(target)
    original.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        showcase.load_report()


def test_unlisted_code_cannot_enter_verified_bundle(demo_bundle):
    root, _ = demo_bundle
    (root / "unexpected.py").write_text("raise RuntimeError('unverified')\n")
    with pytest.raises(ValueError, match="Unverified forecast demo artifact"):
        showcase.load_report()


@pytest.mark.parametrize("section", ["status", "verification"])
def test_failed_receipt_is_rejected(demo_bundle, section):
    root, report = demo_bundle
    if section == "status":
        report["status"] = "failed"
    else:
        report["verification"]["status"] = "failed"
    _write_report(root, report)
    with pytest.raises(ValueError, match="pass"):
        showcase.load_report()


def test_missing_executable_is_not_a_verified_bundle(demo_bundle):
    root, report = demo_bundle
    del report["files"]["forecast_core.py"]
    _write_report(root, report)
    with pytest.raises(ValueError, match="manifest is incomplete"):
        showcase.load_report()


def test_forecast_controls_render_and_update_without_provider(demo_bundle):
    at = AppTest.from_function(_forecast_page).run()
    assert not at.exception
    assert any(heading.value == "Forecast lab" for heading in at.subheader)
    assert at.metric[-1].value == "10"
    at.slider(key="forecast_horizon").set_value(5).run()
    assert not at.exception
    assert at.metric[-1].value == "12"
    assert any("recorded forecast and interface" in item.value for item in at.markdown)
    assert all("autonomous" not in title.value.lower() for title in at.title)


def test_import_state_is_restored_after_app_failure(demo_bundle, monkeypatch):
    _, payload = showcase._read_verified_bundle()
    previous = ModuleType("forecast_core")
    previous.VALUE = -99
    monkeypatch.setitem(sys.modules, "forecast_core", previous)
    payload["app.py"] = b"import forecast_core\nassert forecast_core.VALUE == 7\nraise RuntimeError('app failed')\n"
    with pytest.raises(RuntimeError, match="app failed"):
        showcase._run_verified_app(payload)
    assert sys.modules["forecast_core"] is previous


def test_missing_resource_shows_clear_unavailability(tmp_path, monkeypatch):
    monkeypatch.setattr(showcase, "DEMO_ROOT", tmp_path / "absent")
    at = AppTest.from_function(_forecast_page).run()
    assert not at.exception
    assert "Forecast demo unavailable" in at.error[0].value
    assert not at.slider


@pytest.mark.parametrize("name", ["config.json", "model.safetensors"])
def test_local_model_rejects_changed_pinned_artifacts(local_model, name):
    assert showcase._validate_model(local_model) == local_model.resolve()
    (local_model / name).write_bytes(b"changed after download")
    with pytest.raises(ValueError, match="Pinned model artifact changed"):
        showcase._validate_model(local_model)


def test_local_model_rejects_adapter_configuration(local_model):
    (local_model / "adapter_config.json").write_text("{}")
    with pytest.raises(ValueError, match="not an adapter"):
        showcase._validate_model(local_model)


def test_model_download_uses_only_pinned_public_artifacts(local_model, monkeypatch, hub_boundary):
    LocalEntryNotFoundError = hub_boundary.errors.LocalEntryNotFoundError

    calls = []

    def snapshot_download(**kwargs):
        calls.append(kwargs)
        if kwargs.get("local_files_only"):
            raise LocalEntryNotFoundError("No local snapshot")
        return str(local_model)

    prepare = showcase._prepare_model
    prepare.clear()
    monkeypatch.setattr(hub_boundary, "snapshot_download", snapshot_download)
    try:
        assert prepare("") == local_model.resolve()
        assert prepare("") == local_model.resolve()
    finally:
        prepare.clear()
    expected = {
        "repo_id": showcase.MODEL_ID, "revision": showcase.MODEL_REVISION,
        "allow_patterns": list(showcase.MODEL_HASHES), "token": False,
    }
    assert calls == [{**expected, "local_files_only": True}, expected]


def test_partial_cached_snapshot_fetches_missing_weights(local_model, monkeypatch, hub_boundary):

    weights = local_model / "model.safetensors"
    original = weights.read_bytes()
    weights.unlink()
    calls = []

    def snapshot_download(**kwargs):
        calls.append(kwargs)
        if not kwargs.get("local_files_only"):
            weights.write_bytes(original)
        return str(local_model)

    prepare = showcase._prepare_model
    prepare.clear()
    monkeypatch.setattr(hub_boundary, "snapshot_download", snapshot_download)
    try:
        assert prepare("") == local_model.resolve()
    finally:
        prepare.clear()
    assert len(calls) == 2
    assert calls[0]["local_files_only"] is True
    assert "local_files_only" not in calls[1]


def test_explicit_local_model_never_requests_a_download(local_model, monkeypatch, hub_boundary):

    def unexpected_download(**_kwargs):
        raise AssertionError("Local model validation must not use the network")

    prepare = showcase._prepare_model
    prepare.clear()
    monkeypatch.setattr(hub_boundary, "snapshot_download", unexpected_download)
    try:
        assert prepare(str(local_model)) == local_model.resolve()
    finally:
        prepare.clear()


@pytest.mark.parametrize("previous_path", [None, "/prior/model"])
def test_model_environment_is_restored_after_generated_app_failure(demo_bundle, local_model, monkeypatch, previous_path):
    if previous_path is None:
        monkeypatch.delenv("CHRONOS_MODEL_PATH", raising=False)
    else:
        monkeypatch.setenv("CHRONOS_MODEL_PATH", previous_path)
    _, payload = showcase._read_verified_bundle()
    payload["app.py"] = (
        "import os\n"
        f"assert os.environ['CHRONOS_MODEL_PATH'] == {str(local_model)!r}\n"
        "raise RuntimeError('app failed')\n"
    ).encode()
    with pytest.raises(RuntimeError, match="app failed"):
        showcase._run_verified_app(payload, local_model)
    assert os.environ.get("CHRONOS_MODEL_PATH") == previous_path


def test_cached_model_mutation_blocks_the_next_render(demo_bundle, local_model):
    at = AppTest.from_function(_forecast_page).run()
    assert not at.exception
    assert at.slider
    (local_model / "model.safetensors").write_bytes(b"changed checkpoint")
    at.run()
    assert not at.exception
    assert "could not be prepared" in at.error[0].value
    assert not at.slider


@pytest.mark.parametrize("failure_type", ["httpx", "dependency"])
def test_preparation_failure_is_actionable_without_private_paths(demo_bundle, monkeypatch, failure_type):
    import httpx

    def unavailable(_path):
        if failure_type == "httpx":
            raise httpx.ConnectError("Connection failed at /Users/private/model")
        raise ModuleNotFoundError("Dependency missing at /Users/private/library")

    monkeypatch.setattr(showcase, "_prepare_model", unavailable)
    at = AppTest.from_function(_forecast_page).run()
    assert not at.exception
    assert "could not be prepared" in at.error[0].value
    assert "dependencies" in at.error[0].value
    assert "/Users/" not in at.error[0].value
    assert not at.slider


def test_forecast_evidence_counts_and_labels_both_check_groups(demo_bundle):
    root, report = demo_bundle
    report["verification"]["forecast"] = {
        "status": "passed",
        "checks": ["held_out_actual_invariance", "future_promotion_changes_forecast"],
        "measurements": {"cases": [{"seed": 42, "mae": 12.0, "baseline_mae": 14.0, "coverage": 0.5}]},
    }
    _write_report(root, report)
    at = AppTest.from_function(_forecast_page).run()
    assert not at.exception
    assert next(metric.value for metric in at.metric if metric.label == "Recorded checks") == "4"
    assert any("Notebook and interface checks" in value.value for value in at.markdown)
    assert any("Forecast checks" in value.value for value in at.markdown)
    assert at.dataframe[0].value["coverage"].tolist() == [0.5]
    assert any("observed coverage can be lower" in value.value for value in at.caption)


@pytest.fixture
def packaged_forecast_core(monkeypatch):
    """Load real fixture/result code while leaving expensive inference uncalled."""
    from importlib import util

    spec = util.spec_from_file_location("forecast_core", showcase.DEMO_ROOT / "forecast_core.py")
    core = util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "forecast_core", core)
    spec.loader.exec_module(core)
    return core


def test_packaged_run_analysis_submits_scenario_and_refreshes_results(packaged_forecast_core, monkeypatch):
    core = packaged_forecast_core
    calls = []

    def controlled_inference(**parameters):
        # Real inference is checked by the separate acceptance script. This
        # boundary stub verifies the actual app's form and result lifecycle.
        calls.append(parameters)
        data = core.make_fixture(**parameters)
        baseline = core.seasonal_baseline(data["context"], parameters["horizon"])
        forecast = baseline + parameters["promotion_days"]
        prediction = {"forecast": forecast, "lower": forecast - 5, "upper": forecast + 5}
        return core.assemble_results(data, prediction, baseline, parameters)

    monkeypatch.setattr(core, "run_analysis", controlled_inference)
    at = AppTest.from_file(str(showcase.DEMO_ROOT / "app.py"), default_timeout=20).run()
    assert not at.exception
    assert calls == []
    assert not at.metric

    at.selectbox[0].set_value(14)
    next(widget for widget in at.number_input if widget.label == "Promotion duration (days)").set_value(0)
    next(button for button in at.button if button.label == "Run analysis").click().run()
    assert not at.exception
    assert calls == [{"seed": 42, "horizon": 14, "promotion_start": 7, "promotion_days": 0}]
    assert {metric.label for metric in at.metric} == {
        "Chronos MAE", "Seasonal-7 MAE", "Observed p10–p90 coverage",
    }
    assert len(at.dataframe[0].value) == 14
    assert set(at.dataframe[0].value["Promotion"]) == {"Off"}

    at.selectbox[0].set_value(56).run()
    assert not at.exception
    assert len(calls) == 1
    assert len(at.dataframe[0].value) == 14
    next(widget for widget in at.number_input if widget.label == "Promotion duration (days)").set_value(7)
    next(button for button in at.button if button.label == "Run analysis").click().run()
    assert not at.exception
    assert len(calls) == 2
    assert calls[-1]["horizon"] == 56
    assert calls[-1]["promotion_days"] == 7
    assert len(at.dataframe[0].value) == 56
    assert (at.dataframe[0].value["Promotion"] == "On").sum() == 7


def test_packaged_run_analysis_reports_missing_model(packaged_forecast_core, monkeypatch):
    def missing_model(**_parameters):
        raise packaged_forecast_core.PrerequisiteError("The prepared model snapshot is unavailable.")

    monkeypatch.setattr(packaged_forecast_core, "run_analysis", missing_model)
    at = AppTest.from_file(str(showcase.DEMO_ROOT / "app.py"), default_timeout=20).run()
    next(button for button in at.button if button.label == "Run analysis").click().run()
    assert not at.exception
    assert at.error[0].value == "The prepared model snapshot is unavailable."
    assert not at.metric
    assert not at.dataframe
