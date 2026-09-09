from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("free_threading_probe", ROOT / "tools/free_threading_probe.py")
assert SPEC and SPEC.loader
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def test_probe_removes_polluted_runtime_settings(monkeypatch, tmp_path):
    for key in ("PYTHONPATH", "PYTHONHOME", "PYTHON_GIL", "AGI_PYTHON_VERSION",
                "AGILAB_POOL_EXECUTOR", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "APPS_REPOSITORY"):
        monkeypatch.setenv(key, "polluted")
    env = probe.isolated_env(tmp_path)
    assert env["HOME"] == str(tmp_path / "home")
    assert env["USERPROFILE"] == env["HOME"]
    assert env["AGILAB_POOL_MAX_WORKERS"] == "2"
    for key in ("PYTHONPATH", "PYTHONHOME", "PYTHON_GIL", "AGI_PYTHON_VERSION",
                "AGILAB_POOL_EXECUTOR", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "APPS_REPOSITORY"):
        assert key not in env


def test_regular_python_cannot_claim_free_threading(monkeypatch):
    monkeypatch.setattr(probe.sysconfig, "get_config_var", lambda key: 0)
    report = probe.runtime_probe()
    assert report["status"] == "failed"
    assert report["imports"] == []
    assert report["worker"]["status"] == "skipped"


@pytest.mark.parametrize("failure", ["gil", "source", "import"])
def test_import_failures_are_recorded_before_skipping_worker(monkeypatch, failure):
    enabled = False
    monkeypatch.setattr(probe.sysconfig, "get_config_var", lambda key: 1)
    monkeypatch.setattr(probe.sys, "_is_gil_enabled", lambda: enabled, raising=False)
    monkeypatch.setattr(probe, "MODULES", ("dependency",))

    def import_module(name):
        nonlocal enabled
        if failure == "import":
            raise ImportError("missing binary")
        enabled = failure == "gil"
        origin = ROOT if failure == "source" else Path(sys.prefix)
        return SimpleNamespace(__file__=str(origin / "dependency.py"))

    monkeypatch.setattr(probe.importlib, "import_module", import_module)
    report = probe.runtime_probe()
    assert report["status"] == "failed"
    assert report["imports"][0]["status"] == "failed"
    assert report["worker"]["status"] == "skipped"
    if failure == "gil":
        assert report["imports"][0]["gil_enabled_before"] is False
        assert report["imports"][0]["gil_enabled_after"] is True


def test_actual_polars_worker_preserves_results_and_labels():
    report = probe.worker_check()
    assert report["status"] == "passed"
    assert report["items"] == 7
    assert len(report["output_sha256"]) == 64


def test_worker_check_detects_lost_results(monkeypatch):
    from agi_node.polars_worker import PolarsWorker
    monkeypatch.setattr(PolarsWorker, "works", lambda *args: 0)
    assert probe.worker_check()["status"] == "failed"


def test_timeout_is_a_failed_step(monkeypatch, tmp_path):
    def expired(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])
    monkeypatch.setattr(probe.subprocess, "run", expired)
    report = probe.run_step(["uv", "build"], cwd=tmp_path, env={}, timeout=1)
    assert report["status"] == "failed"
    assert report["returncode"] is None


def test_elapsed_measurement_does_not_depend_on_wall_clock(monkeypatch, tmp_path):
    ticks = iter((12.0, 12.125))
    monkeypatch.setattr(probe.time, "perf_counter", lambda: next(ticks))
    monkeypatch.setattr(probe.time, "time", lambda: pytest.fail("wall clock used for duration"))
    monkeypatch.setattr(probe.subprocess, "run", lambda *args, **kwargs:
                        SimpleNamespace(returncode=0, stdout="", stderr=""))
    report = probe.run_step(["probe"], cwd=tmp_path, env={}, timeout=1)
    assert report["elapsed_seconds"] == 0.125


def test_diagnostic_redacts_credentials(monkeypatch):
    monkeypatch.setenv("EXAMPLE_API_KEY", "private-example-key")
    text = probe.diagnostic("https://user:password@example.test/simple private-example-key")
    assert "password" not in text
    assert "private-example-key" not in text
    assert "example.test" in text


@pytest.mark.parametrize("failed_step", ["build", "dependencies", "runtime", None])
def test_report_separates_build_dependency_and_runtime_failures(monkeypatch, failed_step):
    monkeypatch.setattr(probe.shutil, "which", lambda name: "/bin/uv")
    calls = []

    def run_step(command, **kwargs):
        calls.append(command)
        stage = "build" if "build" in command else "dependencies" if "install" in command else "runtime" if "--runtime" in command else "environment"
        if stage == "build":
            wheel_dir = Path(command[command.index("--out-dir") + 1])
            (wheel_dir / (Path(command[-1]).name + ".whl")).write_bytes(b"built wheel")
        if stage == "runtime":
            Path(command[-1]).write_text(json.dumps({"status": "failed" if failed_step == "runtime" else "passed", "detail": "recorded"}))
        return {"status": "failed" if stage == failed_step else "passed", "returncode": 1 if stage == failed_step else 0}

    monkeypatch.setattr(probe, "run_step", run_step)
    report = probe.probe(python="3.14t", timeout=1)
    assert report["schema"] == "agilab.free_threading_probe.v1"
    assert report["local_only"] is True
    assert datetime.fromisoformat(report["created_at"]).utcoffset() == timedelta(0)
    assert report["status"] == ("passed" if failed_step is None else "failed")
    if failed_step in {"build", "dependencies"}:
        assert report["runtime"]["status"] == "skipped"
        assert not any("--runtime" in cmd for cmd in calls)
    else:
        assert report["runtime"]["detail"] == "recorded"
        assert "-I" in calls[-1]
    if failed_step != "build":
        assert len(report["wheels"]) == 5
        assert all(len(wheel["sha256"]) == 64 and not wheel["retained"] for wheel in report["wheels"])


def test_runtime_json_is_not_truncated(monkeypatch, tmp_path):
    report = {"status": "passed", "versions": {f"package-{i}": "1.0" for i in range(500)}}
    monkeypatch.setattr(probe, "runtime_probe", lambda: report)
    output = tmp_path / "runtime.json"
    assert probe.main(["--runtime", str(output)]) == 0
    assert json.loads(output.read_text()) == report


@pytest.mark.parametrize("payload", [None, "truncated {", "[]", '{"status": "unknown"}'])
def test_missing_or_invalid_runtime_report_is_a_failure(tmp_path, payload):
    path = tmp_path / "runtime.json"
    if payload is not None:
        path.write_text(payload)
    result = probe.read_runtime_result(path)
    assert result["status"] == "failed"
    assert result["reason"] == "runtime_result_missing_or_invalid"
