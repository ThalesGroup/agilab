from __future__ import annotations

import builtins
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from agi_cluster.agi_distributor.runtime.manager_mlflow_support import (
    register_shared_mlflow_handoffs,
)


class _Run:
    info = SimpleNamespace(run_id="manager-run-1")


class _MlflowClient:
    def __init__(self):
        self.logged_artifacts: list[tuple[str, str]] = []
        self.logged_metrics: list[tuple[str, str, float, int | None]] = []
        self.terminated: list[tuple[str, str]] = []

    def get_experiment_by_name(self, name):
        return None

    def create_experiment(self, name, artifact_location):
        return "7"

    def search_runs(self, experiment_ids, filter_string):
        return []

    def create_run(self, experiment_id, *, run_name, tags):
        return _Run()

    def log_param(self, run_id, key, value):
        return None

    def log_metric(self, run_id, key, value, step=None):
        self.logged_metrics.append((run_id, key, value, step))

    def log_artifact(self, run_id, path):
        self.logged_artifacts.append((run_id, path))

    def set_terminated(self, run_id, status):
        self.terminated.append((run_id, status))


class _Mlflow:
    def __init__(self):
        self.active_run = SimpleNamespace(info=SimpleNamespace(run_id="pipeline-run"))
        self.client = _MlflowClient()
        self.client_tracking_uris: list[str] = []

    def MlflowClient(self, *, tracking_uri):
        self.client_tracking_uris.append(tracking_uri)
        return self.client

    def start_run(self, **_kwargs):
        raise AssertionError("Manager handoff registration must not use fluent active-run state")


def test_manager_does_not_scan_or_import_mlflow_when_request_is_disabled(
    tmp_path,
    monkeypatch,
):
    share = tmp_path / "workflow"
    share.mkdir()
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "mlflow":
            raise AssertionError("MLflow must not be imported without a handoff")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    def forbidden_rglob(_self, _pattern):
        raise AssertionError("Disabled MLflow must not scan the workflow tree")

    monkeypatch.setattr(Path, "rglob", forbidden_rglob)
    agi = SimpleNamespace(
        _workers_data_path=str(share),
        _args={
            "_agilab_run_stages": [
                {
                    "name": "fcas_routing_path_ac",
                    "args": {
                        "mlflow_enabled": False,
                        "tracking_backend": "mlflow",
                        "mlflow_tracking_uri": "http://192.0.2.10:5000",
                    },
                }
            ]
        },
        env=SimpleNamespace(home_abs=str(tmp_path)),
    )

    assert register_shared_mlflow_handoffs(agi) == []


def test_manager_registers_shared_handoff_and_is_idempotent(tmp_path, monkeypatch):
    share = tmp_path / "workflow"
    output = share / "sb3_trainer" / "pipeline" / "trainer_fcas_routing_path_ac"
    output.mkdir(parents=True)
    artifact = output / "summary_metrics.json"
    artifact.write_text("{}", encoding="utf-8")
    handoff = {
        "schema": "agilab.mlflow.handoff.v1",
        "handoff_key": "stable-key",
        "trainer_name": "fcas_routing_path_ac",
        "experiment": "FCAS Routing Models",
        "run_name": "fcas_routing_path_ac",
        "params": {"seed": 42},
        "metrics": {"served_bandwidth_ratio": 0.75},
        "metric_history": {
            "evaluation/decision_time_ms": [
                {"step": 0, "value": 12.0},
                {"step": 1, "value": 18.0},
            ]
        },
        "artifacts": ["summary_metrics.json", "../outside.txt"],
    }
    (output / "mlflow_handoff.json").write_text(json.dumps(handoff), encoding="utf-8")

    fake_mlflow = _Mlflow()
    monkeypatch.setitem(sys.modules, "mlflow", fake_mlflow)
    agi = SimpleNamespace(
        _workers_data_path=str(share),
        _args={
            "_agilab_run_stages": [
                {
                    "name": "fcas_routing_path_ac",
                    "args": {"mlflow_enabled": True},
                }
            ]
        },
        env=SimpleNamespace(
            home_abs=str(tmp_path),
            MLFLOW_TRACKING_DIR=str(tmp_path / "manager-mlflow"),
        ),
    )

    first = register_shared_mlflow_handoffs(agi)
    second = register_shared_mlflow_handoffs(agi)

    assert first == [{"status": "logged", "run_id": "manager-run-1"}]
    assert second == [{"status": "skipped", "reason": "already_logged", "run_id": "manager-run-1"}]
    assert ("manager-run-1", str(artifact)) in fake_mlflow.client.logged_artifacts
    assert (
        "manager-run-1",
        "evaluation/decision_time_ms",
        12.0,
        0,
    ) in fake_mlflow.client.logged_metrics
    assert (
        "manager-run-1",
        "evaluation/decision_time_ms",
        18.0,
        1,
    ) in fake_mlflow.client.logged_metrics
    assert fake_mlflow.active_run.info.run_id == "pipeline-run"
    assert fake_mlflow.client.terminated == [("manager-run-1", "FINISHED")]
    marker = json.loads((output / "mlflow_manager_registration.json").read_text(encoding="utf-8"))
    assert marker["status"] == "logged"


def test_manager_handoff_failure_does_not_escape(tmp_path, monkeypatch):
    share = tmp_path / "workflow"
    output = share / "sb3_trainer" / "pipeline" / "trainer"
    output.mkdir(parents=True)
    (output / "mlflow_handoff.json").write_text(
        json.dumps(
            {
                "schema": "agilab.mlflow.handoff.v1",
                "handoff_key": "stable-key",
                "metrics": {"score": 1.0},
            }
        ),
        encoding="utf-8",
    )
    fake_mlflow = _Mlflow()

    def fail_log_metric(*_args, **_kwargs):
        raise Exception("tracking store unavailable")

    fake_mlflow.client.log_metric = fail_log_metric
    monkeypatch.setitem(sys.modules, "mlflow", fake_mlflow)
    agi = SimpleNamespace(
        _workers_data_path=str(share),
        _args={"mlflow_enabled": True},
        env=SimpleNamespace(
            home_abs=str(tmp_path),
            MLFLOW_TRACKING_DIR=str(tmp_path / "manager-mlflow"),
        ),
    )

    result = register_shared_mlflow_handoffs(agi)

    assert result[0]["status"] == "error"
    assert result[0]["message"] == "tracking store unavailable"
    assert fake_mlflow.client.terminated == [("manager-run-1", "FAILED")]
