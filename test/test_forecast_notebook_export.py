"""Publication must preserve both autonomous-run and model-evaluation evidence."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location(
    "forecast_export", Path(__file__).parents[1] / "tools/demos/export_forecast_notebook_demo.py",
)
exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exporter)


@pytest.fixture
def completed_run(tmp_path):
    run = tmp_path / "verified-run"
    project = run / "notebook_app_project"
    project.mkdir(parents=True)
    files = {}
    for name in exporter.CORE_FILES | {"LICENSE", "data/series.csv"}:
        path = project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"fixture {name}\n")
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    source = {
        "repository": "example/forecast", "commit": "a" * 40,
        "url": "https://github.com/example/forecast/blob/" + "a" * 40 + "/demo.ipynb",
        "sha256": "b" * 64, "license": "Apache-2.0", "author": "Example",
        "retrieved_at": "2026-09-18T00:00:00Z",
    }
    report = {
        "status": "passed", "seconds": 20, "workflow_stages": 3,
        "source": source, "files": {name: files[name] for name in exporter.CORE_FILES},
        "verification": {"status": "passed", "scientific_correctness_verified": False},
    }
    (run / "result.json").write_text(json.dumps(report))
    validation = tmp_path / "validation.json"
    checked = {
        "status": "passed", "run_id": run.name, "checks": ["finite_forecast"],
        "files": files, "source": source,
        "model": {"id": "example/model", "revision": "c" * 40, "license": "Apache-2.0"},
        "demo": {"title": "Forecast", "description": "A checked forecast", "request": "Build it"},
        "verification_scope": "fixture evaluation and interface", "measurements": {"mae": 0.1},
    }
    validation.write_text(json.dumps(checked))
    return run, tmp_path / "export", validation


def test_export_keeps_scopes_and_hashes(completed_run):
    run, target, validation = completed_run
    report = exporter.export_demo(run, target, validation)
    assert report["verification"]["scientific_correctness_verified"] is False
    assert report["verification"]["forecast"]["checks"] == ["finite_forecast"]
    assert report["files"]["data/series.csv"] == hashlib.sha256((target / "data/series.csv").read_bytes()).hexdigest()
    assert json.loads((target / "result.json").read_text()) == report


@pytest.mark.parametrize("change", ["data", "code", "source", "run", "failed", "failed-check", "symlink", "extra", "stale", "parent-symlink"])
def test_export_rejects_drift_before_writing(completed_run, change):
    run, target, validation = completed_run
    checked = json.loads(validation.read_text())
    project = run / "notebook_app_project"
    if change == "data":
        (project / "data/series.csv").write_text("changed")
    elif change == "code":
        (project / "app.py").write_text("changed")
        checked["files"]["app.py"] = hashlib.sha256(b"changed").hexdigest()
    elif change == "source":
        checked["source"]["commit"] = "d" * 40
    elif change == "run":
        checked["run_id"] = "another-run"
    elif change == "failed":
        checked["status"] = "failed"
    elif change == "failed-check":
        checked["checks"] = {"finite_forecast": False}
    elif change == "symlink":
        (project / "data").rename(project / "real-data")
        (project / "data").symlink_to(project / "real-data", target_is_directory=True)
    elif change == "extra":
        checked["files"]["../secret.py"] = "e" * 64
    elif change == "stale":
        target.mkdir()
        (target / "stale.py").write_text("old code")
    elif change == "parent-symlink":
        outside = target.parent / "outside"
        outside.mkdir()
        redirect = target.parent / "redirect"
        redirect.symlink_to(outside, target_is_directory=True)
        target = redirect / "export"
    validation.write_text(json.dumps(checked))
    with pytest.raises(ValueError):
        exporter.export_demo(run, target, validation)
    assert not (target / "result.json").exists()
