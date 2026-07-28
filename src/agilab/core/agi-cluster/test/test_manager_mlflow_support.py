from __future__ import annotations

import builtins
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from agi_cluster.agi_distributor.runtime.manager_mlflow_support import (
    register_shared_mlflow_handoffs,
)


class _Runs:
    empty = True


class _Run:
    info = SimpleNamespace(run_id="manager-run-1")


class _Mlflow:
    def __init__(self):
        self.uri = "file:///previous"
        self.logged_artifacts: list[str] = []

    def get_tracking_uri(self):
        return self.uri

    def set_tracking_uri(self, uri):
        self.uri = uri

    def get_experiment_by_name(self, name):
        return None

    def create_experiment(self, name, artifact_location):
        return "7"

    def set_experiment(self, name):
        return None

    def search_runs(self, experiment_ids, filter_string):
        return _Runs()

    def start_run(self, run_name):
        class _Context:
            def __enter__(self):
                return _Run()

            def __exit__(self, *_args):
                return False

        return _Context()

    def set_tags(self, tags):
        return None

    def log_param(self, key, value):
        return None

    def log_metric(self, key, value):
        return None

    def log_artifact(self, path):
        self.logged_artifacts.append(path)


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
    assert str(artifact) in fake_mlflow.logged_artifacts
    marker = json.loads((output / "mlflow_manager_registration.json").read_text(encoding="utf-8"))
    assert marker["status"] == "logged"
