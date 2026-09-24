"""Manager handoff registration validates metadata and reports partial failures."""
import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agi_cluster.agi_distributor.runtime import manager_mlflow_support as handoff


@pytest.fixture
def registration(tmp_path, monkeypatch):
    path = tmp_path / "worker" / "mlflow_handoff.json"
    path.parent.mkdir()
    payload = {"schema": handoff.HANDOFF_SCHEMA, "handoff_key": "workflow-worker"}
    path.write_text(json.dumps(payload))
    client = Mock()
    client.get_experiment_by_name.return_value = None
    client.create_experiment.return_value = "experiment"
    client.search_runs.return_value = []
    client.create_run.return_value = SimpleNamespace(info=SimpleNamespace(run_id="run"))
    mlflow = SimpleNamespace(MlflowClient=Mock(return_value=client))
    monkeypatch.setattr(handoff, "_tracking_paths", lambda _: (tmp_path / "tracking.db", tmp_path / "artifacts", "sqlite:///fixture"))
    return path, payload, client, mlflow


@pytest.mark.parametrize("payload,reason", [({"schema": "unsupported"}, "unsupported_schema"),
                                          ({"schema": handoff.HANDOFF_SCHEMA}, "missing_handoff_key")])
def test_unsupported_handoff_never_opens_tracking_client(registration, payload, reason):
    path, _, _, mlflow = registration
    path.write_text(json.dumps(payload))
    assert handoff._register_handoff(path, env=object(), mlflow=mlflow, log=Mock()) == {"status": "skipped", "reason": reason}
    mlflow.MlflowClient.assert_not_called()


def test_matching_marker_skips_duplicate_without_client(registration):
    path, payload, _, mlflow = registration
    marker = path.parent / "mlflow_manager_registration.json"
    marker.write_text(json.dumps({"status": "logged", "handoff_key": payload["handoff_key"], "run_id": "prior"}))
    assert handoff._register_handoff(path, env=object(), mlflow=mlflow, log=Mock()) == {
        "status": "skipped", "reason": "already_logged", "run_id": "prior"}
    mlflow.MlflowClient.assert_not_called()


@pytest.mark.parametrize("marker", ["{partial", '{"status":"logged","handoff_key":"different"}'])
def test_stale_or_interrupted_marker_does_not_suppress_registration(registration, marker):
    path, _, client, mlflow = registration
    (path.parent / "mlflow_manager_registration.json").write_text(marker)
    result = handoff._register_handoff(path, env=object(), mlflow=mlflow, log=Mock())
    assert result == {"status": "logged", "run_id": "run"}
    client.create_run.assert_called_once()
    client.set_terminated.assert_called_once_with("run", status="FINISHED")


def test_existing_tracking_run_is_reconciled_without_duplicate_creation(registration):
    path, _, client, mlflow = registration
    client.get_experiment_by_name.return_value = SimpleNamespace(experiment_id="existing-experiment")
    client.search_runs.return_value = [SimpleNamespace(info=SimpleNamespace(run_id="existing-run"))]
    assert handoff._register_handoff(path, env=object(), mlflow=mlflow, log=Mock()) == {
        "status": "skipped", "reason": "already_logged", "run_id": "existing-run"}
    client.create_run.assert_not_called()
    client.create_experiment.assert_not_called()
    assert json.loads((path.parent / "mlflow_manager_registration.json").read_text())["run_id"] == "existing-run"


def test_metrics_and_artifacts_are_validated_before_logging(registration):
    path, payload, client, mlflow = registration
    artifact = path.parent / "metrics.json"
    artifact.write_text("{}")
    outside = path.parent.parent / "outside-mlflow-fixture.json"
    outside.write_text("{}")
    (path.parent / "escape.json").symlink_to(outside)
    payload.update(
        params={"optimizer": "adam"},
        metrics={"finite": 1, "bool": True, "text": "1", "nan": float("nan"), "infinite": float("inf")},
        metric_history={"loss": [None, {"step": True, "value": 1}, {"step": "1", "value": 1},
                                {"step": 1, "value": True}, {"step": 1, "value": "1"},
                                {"step": 1, "value": float("nan")}, {"step": 2, "value": 0.25}],
                        "": [{"step": 1, "value": 1}], "invalid": "points"},
        artifacts=["metrics.json", "../outside-mlflow-fixture.json", "escape.json", "missing", "", None, str(outside)],
    )
    path.write_text(json.dumps(payload))
    assert handoff._register_handoff(path, env=object(), mlflow=mlflow, log=Mock())["status"] == "logged"
    assert client.log_metric.call_count == 2
    client.log_metric.assert_any_call("run", "finite", 1.0)
    client.log_metric.assert_any_call("run", "loss", 0.25, step=2)
    assert [call.args[1] for call in client.log_artifact.call_args_list] == [str(path), str(artifact)]
    client.log_param.assert_called_once_with("run", "optimizer", "adam")


@pytest.mark.parametrize("method", ["log_param", "log_metric", "log_artifact"])
def test_backend_failure_marks_run_failed_without_success_marker(registration, method):
    path, payload, client, mlflow = registration
    payload.update(params={"p": "v"}, metrics={"score": 1})
    path.write_text(json.dumps(payload))
    getattr(client, method).side_effect = RuntimeError("plugin failure")
    with pytest.raises(RuntimeError, match="plugin failure"):
        handoff._register_handoff(path, env=object(), mlflow=mlflow, log=Mock())
    client.set_terminated.assert_called_once_with("run", status="FAILED")
    assert not (path.parent / "mlflow_manager_registration.json").exists()


@pytest.mark.parametrize("value", [None, [], "invalid"])
def test_non_mapping_metrics_are_ignored(value):
    assert handoff._numeric_metrics(value) == {}
    assert handoff._metric_history(value) == {}


@pytest.mark.parametrize("enabled", [True, 1, "yes"])
def test_registration_reports_bad_handoff_without_failing_completed_worker(monkeypatch, tmp_path, enabled):
    (tmp_path / "mlflow_handoff.json").write_text("{invalid")
    monkeypatch.setitem(sys.modules, "mlflow", SimpleNamespace())
    agi = SimpleNamespace(_args={"nested": [{"mlflow_enabled": enabled}]}, _workers_data_path=str(tmp_path), env=object())
    result = handoff.register_shared_mlflow_handoffs(agi, log=Mock())
    assert len(result) == 1
    assert result[0]["status"] == "error"
    assert result[0]["path"] == str(tmp_path / "mlflow_handoff.json")


def test_missing_mlflow_dependency_leaves_handoff_unmodified(monkeypatch, tmp_path):
    path = tmp_path / "mlflow_handoff.json"
    path.write_text("{}")
    monkeypatch.setitem(sys.modules, "mlflow", None)
    agi = SimpleNamespace(_args={"mlflow_enabled": True}, _workers_data_path=str(tmp_path), env=object())
    assert handoff.register_shared_mlflow_handoffs(agi, log=Mock()) == []
    assert path.read_text() == "{}"
    assert not (tmp_path / "mlflow_manager_registration.json").exists()
