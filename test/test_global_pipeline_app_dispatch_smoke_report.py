from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


REPORT_PATH = Path("tools/global_pipeline_app_dispatch_smoke_report.py").resolve()
CORE_PATH = Path("src/agilab/global_pipeline_app_dispatch_smoke.py").resolve()


def _load_report_module():
    spec = importlib.util.spec_from_file_location("global_pipeline_app_dispatch_smoke_report_test_module", REPORT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_core_module():
    spec = importlib.util.spec_from_file_location("global_pipeline_app_dispatch_smoke_test_module", CORE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_app_dispatch_smoke_report_executes_queue_and_relay(tmp_path: Path) -> None:
    module = _load_report_module()
    output_path = tmp_path / "app_dispatch_smoke.json"

    report = module.build_report(
        repo_root=Path.cwd(),
        output_path=output_path,
        workspace_path=tmp_path / "workspace",
    )

    assert report["report"] == "Global pipeline app dispatch smoke report"
    assert report["status"] == "pass"
    assert output_path.is_file()
    assert report["summary"]["schema"] == "agilab.global_pipeline_dispatch_state.v1"
    assert report["summary"]["smoke_schema"] == "agilab.global_pipeline_app_dispatch_smoke.v1"
    assert report["summary"]["run_id"] == "global-dag-real-dispatch-smoke"
    assert report["summary"]["run_status"] == "completed"
    assert report["summary"]["persistence_format"] == "json"
    assert report["summary"]["round_trip_ok"] is True
    assert report["summary"]["unit_count"] == 2
    assert report["summary"]["completed_unit_ids"] == ["queue_baseline", "relay_followup"]
    assert report["summary"]["runnable_unit_ids"] == []
    assert report["summary"]["real_executed_unit_ids"] == ["queue_baseline", "relay_followup"]
    assert report["summary"]["readiness_only_unit_ids"] == []
    assert report["summary"]["real_execution_scope"] == "full_dag_smoke"
    assert report["summary"]["queue_packets_generated"] > 0
    assert report["summary"]["relay_packets_generated"] > 0
    assert report["summary"]["packets_generated"] > 0
    assert report["summary"]["available_artifact_ids"] == [
        "queue_metrics",
        "queue_reduce_summary",
        "relay_metrics",
        "relay_reduce_summary",
    ]
    assert {check["id"] for check in report["checks"]} == {
        "global_pipeline_app_dispatch_smoke_schema",
        "global_pipeline_app_dispatch_smoke_real_queue",
        "global_pipeline_app_dispatch_smoke_real_relay",
        "global_pipeline_app_dispatch_smoke_artifacts",
        "global_pipeline_app_dispatch_smoke_full_dag",
        "global_pipeline_app_dispatch_smoke_persistence",
        "global_pipeline_app_dispatch_smoke_provenance",
        "global_pipeline_app_dispatch_smoke_docs_reference",
    }


def test_app_dispatch_smoke_state_contains_real_artifacts(tmp_path: Path) -> None:
    module = _load_core_module()

    proof = module.persist_app_dispatch_smoke(
        repo_root=Path.cwd(),
        output_path=tmp_path / "app_dispatch_smoke.json",
        run_root=tmp_path / "workspace",
    )

    assert proof.ok is True
    assert proof.round_trip_ok is True
    state = proof.dispatch_state
    queue, relay = state["units"]
    queue_metrics = queue["real_execution"]["summary_metrics"]
    relay_metrics = relay["real_execution"]["summary_metrics"]
    workspace = Path(queue["real_execution"]["workspace"])
    assert state["provenance"]["real_app_execution"] is True
    assert state["provenance"]["real_execution_scope"] == "full_dag_smoke"
    assert state["summary"]["real_executed_unit_ids"] == ["queue_baseline", "relay_followup"]
    assert state["summary"]["readiness_only_unit_ids"] == []
    assert queue["dispatch_status"] == "completed"
    assert queue["execution_mode"] == "real_app_entry"
    assert queue_metrics["routing_policy"] == "queue_aware"
    assert queue_metrics["packets_generated"] > 0
    assert relay["dispatch_status"] == "completed"
    assert relay["execution_mode"] == "real_app_entry"
    assert relay["unblocked_by"] == ["queue_metrics"]
    assert relay["real_execution"]["consumed_artifacts"] == [
        {
            "artifact": "queue_metrics",
            "path": queue["real_execution"]["summary_metrics_path"],
            "producer": "queue_baseline",
        }
    ]
    assert relay_metrics["routing_policy"] == "queue_aware"
    assert relay_metrics["packets_generated"] > 0
    assert (workspace / queue["real_execution"]["summary_metrics_path"]).is_file()
    assert (workspace / queue["real_execution"]["reduce_artifact_path"]).is_file()
    assert (workspace / relay["real_execution"]["summary_metrics_path"]).is_file()
    assert (workspace / relay["real_execution"]["reduce_artifact_path"]).is_file()


def test_app_dispatch_smoke_report_handles_load_failure(tmp_path: Path) -> None:
    module = _load_report_module()
    missing = tmp_path / "missing.json"

    report = module.build_report(
        repo_root=Path.cwd(),
        dag_path=missing,
        output_path=tmp_path / "app_dispatch_smoke.json",
        workspace_path=tmp_path / "workspace",
    )

    assert report["status"] == "fail"
    assert report["checks"] == [
        {
            "details": {
                "error": f"[Errno 2] No such file or directory: '{missing}'",
            },
            "evidence": [str(missing)],
            "id": "global_pipeline_app_dispatch_smoke_load",
            "label": "Global pipeline app dispatch smoke load",
            "status": "fail",
            "summary": "global pipeline app dispatch smoke could not be persisted",
        }
    ]


def test_app_dispatch_smoke_helper_properties_handle_malformed_state(tmp_path: Path) -> None:
    module = _load_core_module()
    issue = module._issue("state", "bad")
    proof = module.AppDispatchSmokeProof(
        ok=False,
        issues=(issue,),
        path=str(tmp_path / "state.json"),
        dispatch_state={
            "summary": {
                "real_executed_unit_ids": ["queue", "", None],
                "readiness_only_unit_ids": ["relay", ""],
            },
            "units": "bad",
            "artifacts": "bad",
            "events": "bad",
        },
        reloaded_state={},
    )

    assert issue.as_dict() == {"level": "error", "location": "state", "message": "bad"}
    assert proof.round_trip_ok is False
    assert proof.completed_unit_ids == ()
    assert proof.runnable_unit_ids == ()
    assert proof.available_artifact_ids == ()
    assert proof.summary_metric_paths == ()
    assert proof.event_count == 0
    assert proof.packet_count == 0
    assert proof.as_dict()["issues"] == [issue.as_dict()]
    assert module._unit_rows({"units": "bad"}) == ()
    assert module._queue_metrics({"units": [{"id": module.QUEUE_UNIT_ID, "real_execution": {"summary_metrics": "bad"}}]}) == {}
    assert module._queue_metrics({"units": []}) == {}
    assert module._relative(tmp_path / "outside.txt", tmp_path / "root") == str(tmp_path / "outside.txt")


def test_app_dispatch_smoke_persist_reports_round_trip_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_core_module()
    state = {
        "schema": "agilab.global_pipeline_dispatch_state.v1",
        "summary": {},
        "units": [],
        "artifacts": [],
        "events": [],
    }
    monkeypatch.setattr(module, "build_app_dispatch_smoke_state", lambda **_kwargs: state)
    monkeypatch.setattr(module, "load_dispatch_state", lambda _path: {"changed": True})

    proof = module.persist_app_dispatch_smoke(
        repo_root=Path.cwd(),
        output_path=tmp_path / "smoke.json",
    )

    assert proof.ok is False
    assert proof.issues[0].location == "persistence.round_trip"


def test_app_dispatch_smoke_queue_runner_requires_expected_outputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_core_module()
    env = module._make_env(tmp_path / "run", target="target")
    source = Path(env.AGI_LOCAL_SHARE) / "scenario.json"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("{}", encoding="utf-8")

    class FakeManager:
        def __init__(self, _env, *, args):
            args.data_in = source.parent
            args.model_dump = lambda mode="json": {}
            self.args = args

        def reset_data(self):
            return None

        def init(self):
            return None

    class FakeWorker:
        def start(self):
            self.data_out = tmp_path / "worker-out"
            return None

        def work_pool(self, _source):
            return {"summary_metrics": {"artifact_stem": "missing"}}

        def work_done(self, _result):
            return None

    monkeypatch.setattr(module.importlib, "import_module", lambda _name: module.SimpleNamespace(
        UavQueue=FakeManager,
        UavQueueArgs=lambda **_kwargs: module.SimpleNamespace(),
        UavQueueWorker=FakeWorker,
    ))

    with pytest.raises(FileNotFoundError, match="summary metrics"):
        module._run_queue_family_app(
            repo_root=tmp_path,
            run_root=tmp_path / "run",
            project_name="uav_queue_project",
            manager_package="uav_queue",
            worker_package="uav_queue",
            manager_class_name="UavQueue",
            args_class_name="UavQueueArgs",
            worker_class_name="UavQueueWorker",
            target="target",
            app_entry="fake",
        )


def test_app_dispatch_smoke_queue_runner_requires_reduce_artifact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_core_module()
    run_root = tmp_path / "run"
    source = run_root / "share" / "scenario.json"
    source.parent.mkdir(parents=True)
    source.write_text("{}", encoding="utf-8")

    class FakeManager:
        def __init__(self, _env, *, args):
            args.data_in = source.parent
            args.model_dump = lambda mode="json": {}
            self.args = args

    class FakeWorker:
        def start(self):
            self.data_out = tmp_path / "worker-out"

        def work_pool(self, _source):
            return {"summary_metrics": {"artifact_stem": "missing-reduce"}}

        def work_done(self, result):
            export_root = run_root / "export" / "target" / "queue_analysis" / "missing-reduce"
            export_root.mkdir(parents=True)
            (export_root / "missing-reduce_summary_metrics.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(module.importlib, "import_module", lambda _name: module.SimpleNamespace(
        UavQueue=FakeManager,
        UavQueueArgs=lambda **_kwargs: module.SimpleNamespace(),
        UavQueueWorker=FakeWorker,
    ))

    with pytest.raises(FileNotFoundError, match="reduce artifact"):
        module._run_queue_family_app(
            repo_root=tmp_path,
            run_root=run_root,
            project_name="uav_queue_project",
            manager_package="uav_queue",
            worker_package="uav_queue",
            manager_class_name="UavQueue",
            args_class_name="UavQueueArgs",
            worker_class_name="UavQueueWorker",
            target="target",
            app_entry="fake",
        )
