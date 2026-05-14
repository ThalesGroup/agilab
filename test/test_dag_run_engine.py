from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import threading


def _ensure_agilab_package_path() -> None:
    package_root = Path("src/agilab").resolve()
    package_spec = importlib.util.spec_from_file_location(
        "agilab",
        package_root / "__init__.py",
        submodule_search_locations=[str(package_root)],
    )
    package = sys.modules.get("agilab")
    if package is None:
        assert package_spec is not None and package_spec.loader is not None
        package = importlib.util.module_from_spec(package_spec)
        sys.modules["agilab"] = package
        package_spec.loader.exec_module(package)
        return

    package_paths = list(getattr(package, "__path__", []) or [])
    package_root_text = str(package_root)
    if package_root_text not in package_paths:
        package.__path__ = [package_root_text, *package_paths]
    package.__spec__ = package_spec
    package.__file__ = str(package_root / "__init__.py")
    package.__package__ = "agilab"


def _load_dag_run_engine():
    _ensure_agilab_package_path()
    module_path = Path("src/agilab/dag_run_engine.py")
    spec = importlib.util.spec_from_file_location("agilab.dag_run_engine", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["agilab.dag_run_engine"] = module
    spec.loader.exec_module(module)
    return module


def _load_multi_app_dag_draft():
    _ensure_agilab_package_path()
    module_path = Path("src/agilab/multi_app_dag_draft.py")
    spec = importlib.util.spec_from_file_location("agilab.multi_app_dag_draft", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["agilab.multi_app_dag_draft"] = module
    spec.loader.exec_module(module)
    return module


dag_run_engine = _load_dag_run_engine()
multi_app_dag_draft = _load_multi_app_dag_draft()


def _sample_dag_path(repo_root: Path) -> Path:
    return repo_root / dag_run_engine.GLOBAL_DAG_SAMPLE_RELATIVE_PATH


def _app_template_dag_path(repo_root: Path) -> Path:
    return repo_root / dag_run_engine.GLOBAL_DAG_UAV_QUEUE_TEMPLATE_RELATIVE_PATH


def _flight_template_dag_path(repo_root: Path) -> Path:
    return repo_root / dag_run_engine.GLOBAL_DAG_FLIGHT_TO_WEATHER_TEMPLATE_RELATIVE_PATH


def _write_parallel_contract_repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    apps_root = repo_root / "src" / "agilab" / "apps" / "builtin"
    for app_name in ("uav_queue_project", "flight_telemetry_project", "weather_forecast_project"):
        app_root = apps_root / app_name
        app_root.mkdir(parents=True, exist_ok=True)
        (app_root / "pyproject.toml").write_text(
            f"[project]\nname = \"{app_name}\"\nversion = \"0.0.0\"\n",
            encoding="utf-8",
        )
        (app_root / "pipeline_view.dot").write_text(
            'digraph { start [label="Start"]; end [label="End"]; start -> end; }\n',
            encoding="utf-8",
        )
    dag_path = apps_root / "uav_queue_project" / "dag_templates" / "parallel_roots.json"
    dag_path.parent.mkdir(parents=True, exist_ok=True)
    dag_path.write_text(
        json.dumps(
            {
                "schema": "agilab.multi_app_dag.v1",
                "dag_id": "parallel-roots",
                "label": "Parallel roots",
                "description": "Two independent roots unlock a downstream review stage.",
                "execution": {
                    "mode": "sequential_dependency_order",
                    "runner_status": "controlled_contract_stage_execution",
                    "adapter": "controlled_contract_dag",
                    "stage_bindings": {
                        "queue_context": "uav_queue_project.queue_context",
                        "flight_context": "flight_telemetry_project.flight_context",
                        "joined_review": "weather_forecast_project.joined_review",
                    },
                },
                "nodes": [
                    {
                        "id": "queue_context",
                        "app": "uav_queue_project",
                        "execution": {"entrypoint": "uav_queue_project.queue_context"},
                        "purpose": "Produce queue context.",
                        "produces": [
                            {"id": "queue_metrics", "kind": "summary_metrics", "path": "queue/metrics.json"}
                        ],
                    },
                    {
                        "id": "flight_context",
                        "app": "flight_telemetry_project",
                        "execution": {"entrypoint": "flight_telemetry_project.flight_context"},
                        "purpose": "Produce flight context.",
                        "produces": [
                            {"id": "flight_metrics", "kind": "summary_metrics", "path": "flight/metrics.json"}
                        ],
                    },
                    {
                        "id": "joined_review",
                        "app": "weather_forecast_project",
                        "execution": {"entrypoint": "weather_forecast_project.joined_review"},
                        "purpose": "Review both contexts.",
                        "consumes": [
                            {"id": "queue_metrics", "kind": "summary_metrics", "path": "queue/metrics.json"},
                            {"id": "flight_metrics", "kind": "summary_metrics", "path": "flight/metrics.json"},
                        ],
                        "produces": [
                            {"id": "review_metrics", "kind": "summary_metrics", "path": "review/metrics.json"}
                        ],
                    },
                ],
                "edges": [
                    {
                        "from": "queue_context",
                        "to": "joined_review",
                        "artifact": "queue_metrics",
                        "handoff": "Pass queue context.",
                    },
                    {
                        "from": "flight_context",
                        "to": "joined_review",
                        "artifact": "flight_metrics",
                        "handoff": "Pass flight context.",
                    },
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return dag_path


def _unit_by_id(state: dict[str, object], unit_id: str) -> dict[str, object]:
    return next(unit for unit in state["units"] if isinstance(unit, dict) and unit.get("id") == unit_id)


def test_dag_run_engine_reuses_matching_persisted_state(tmp_path):
    repo_root = Path.cwd()
    engine = dag_run_engine.DagRunEngine(
        repo_root=repo_root,
        lab_dir=tmp_path,
        dag_path=_sample_dag_path(repo_root),
    )

    state, state_path, dag_path = engine.load_or_create_state()
    state["events"].append(
        {
            "timestamp": "2026-05-07T00:01:00Z",
            "kind": "operator_note",
            "unit_id": "",
            "from_status": "",
            "to_status": "planned",
            "detail": "keep me",
        }
    )
    engine.write_state(state)

    reloaded, reloaded_path, reloaded_dag_path = engine.load_or_create_state()

    assert state_path == reloaded_path == tmp_path / ".agilab" / "runner_state.json"
    assert dag_path == reloaded_dag_path == _sample_dag_path(repo_root)
    assert reloaded["events"][-1]["detail"] == "keep me"


def test_dag_run_engine_recreates_mismatched_persisted_state(tmp_path):
    repo_root = Path.cwd()
    engine = dag_run_engine.DagRunEngine(
        repo_root=repo_root,
        lab_dir=tmp_path,
        dag_path=_sample_dag_path(repo_root),
    )
    state, _state_path, _dag_path = engine.load_or_create_state()
    state["source"]["dag_path"] = "different/dag.json"
    state["events"].append(
        {
            "timestamp": "2026-05-07T00:01:00Z",
            "kind": "operator_note",
            "detail": "discard me",
        }
    )
    engine.write_state(state)

    recreated, recreated_path, recreated_dag_path = engine.load_or_create_state()

    assert recreated_path == tmp_path / ".agilab" / "runner_state.json"
    assert recreated_dag_path == _sample_dag_path(repo_root)
    assert all(event.get("detail") != "discard me" for event in recreated["events"])
    assert dag_run_engine.runner_state_dag_matches(recreated, _sample_dag_path(repo_root), repo_root)


def test_dag_run_engine_executes_controlled_queue_stage(tmp_path):
    repo_root = Path.cwd()
    calls: list[Path] = []

    def _fake_queue_run(*, repo_root: Path, run_root: Path) -> dict[str, object]:
        calls.append(run_root)
        return {
            "summary_metrics_path": "queue/summary.json",
            "reduce_artifact_path": "queue/reduce.json",
            "summary_metrics": {"packets_generated": 13, "packets_delivered": 11},
        }

    engine = dag_run_engine.DagRunEngine(
        repo_root=repo_root,
        lab_dir=tmp_path,
        dag_path=_sample_dag_path(repo_root),
        run_queue_fn=_fake_queue_run,
        now_fn=lambda: "2026-05-07T00:00:00Z",
    )
    state, _state_path, _dag_path = engine.load_or_create_state()

    result = engine.run_next_controlled_stage(state)

    assert result.ok
    assert result.executed_unit_id == dag_run_engine.GLOBAL_DAG_QUEUE_UNIT_ID
    assert calls == [tmp_path / ".agilab" / "global_dag_real_runs" / "queue_baseline"]
    assert result.state["summary"]["completed_unit_ids"] == ["queue_baseline"]
    assert result.state["summary"]["runnable_unit_ids"] == ["relay_followup"]
    assert result.state["summary"]["available_artifact_ids"] == ["queue_metrics", "queue_reduce_summary"]
    queue = next(unit for unit in result.state["units"] if unit["id"] == "queue_baseline")
    assert queue["execution_mode"] == "real_app_entry"
    assert queue["real_execution"]["summary_metrics"]["packets_delivered"] == 11


def test_dag_run_engine_executes_app_owned_uav_template_queue_stage(tmp_path):
    repo_root = Path.cwd()
    calls: list[Path] = []

    def _fake_queue_run(*, repo_root: Path, run_root: Path) -> dict[str, object]:
        calls.append(run_root)
        return {
            "summary_metrics_path": "queue/summary.json",
            "reduce_artifact_path": "queue/reduce.json",
            "summary_metrics": {"packets_generated": 13, "packets_delivered": 11},
        }

    engine = dag_run_engine.DagRunEngine(
        repo_root=repo_root,
        lab_dir=tmp_path,
        dag_path=_app_template_dag_path(repo_root),
        run_queue_fn=_fake_queue_run,
        now_fn=lambda: "2026-05-07T00:00:00Z",
    )
    state, _state_path, _dag_path = engine.load_or_create_state()
    support = engine.real_run_support(state)

    result = engine.run_next_controlled_stage(state)

    assert support.supported
    assert support.status == "Executable"
    assert support.adapter == dag_run_engine.GLOBAL_DAG_CONTROLLED_ADAPTER
    assert result.ok
    assert result.executed_unit_id == dag_run_engine.GLOBAL_DAG_QUEUE_UNIT_ID
    assert calls == [tmp_path / ".agilab" / "global_dag_real_runs" / "queue_baseline"]


def test_dag_run_engine_executes_app_owned_flight_template_contract_stage(tmp_path):
    repo_root = Path.cwd()
    calls: list[Path] = []

    def _fake_flight_contract(*, repo_root: Path, run_root: Path) -> dict[str, object]:
        calls.append(run_root)
        return {
            "summary_metrics_path": "flight/summary.json",
            "reduce_artifact_path": "flight/reduce.json",
            "summary_metrics": {"stage_completed": 1},
        }

    engine = dag_run_engine.DagRunEngine(
        repo_root=repo_root,
        lab_dir=tmp_path,
        dag_path=_flight_template_dag_path(repo_root),
        stage_run_fns={"flight_telemetry_project.flight_context": _fake_flight_contract},
        now_fn=lambda: "2026-05-07T00:00:00Z",
    )
    state, _state_path, _dag_path = engine.load_or_create_state()
    support = engine.real_run_support(state)

    result = engine.run_next_controlled_stage(state)

    assert support.supported
    assert support.status == "Executable"
    assert support.adapter == dag_run_engine.GLOBAL_DAG_CONTROLLED_CONTRACT_ADAPTER
    assert result.ok
    assert result.executed_unit_id == dag_run_engine.GLOBAL_DAG_FLIGHT_CONTEXT_UNIT_ID
    assert calls == [tmp_path / ".agilab" / "global_dag_real_runs" / "flight_context"]
    assert result.state["summary"]["completed_unit_ids"] == ["flight_context"]
    assert result.state["summary"]["runnable_unit_ids"] == ["weather_forecast_review"]
    assert result.state["summary"]["available_artifact_ids"] == ["flight_reduce_summary"]
    assert result.state["summary"]["controlled_executed_unit_ids"] == ["flight_context"]
    assert result.state["provenance"]["real_app_execution"] is False
    assert result.state["provenance"]["controlled_execution"] is True
    assert result.state["provenance"]["controlled_execution_scope"] == "controlled_contract_dag_stage"
    flight = next(unit for unit in result.state["units"] if unit["id"] == "flight_context")
    assert flight["execution_contract"]["entrypoint"] == "flight_telemetry_project.flight_context"
    assert flight["execution_contract"]["data_in"] == "flight/dataset"
    assert flight["execution_contract"]["data_out"] == "flight/dataframe"
    assert flight["execution_mode"] == "contract_adapter"
    assert flight["contract_execution"]["summary_metrics"]["stage_completed"] == 1
    assert flight["produces"] == [
        {"artifact": "flight_reduce_summary", "kind": "reduce_summary", "path": "flight/reduce.json"}
    ]


def test_dag_run_engine_runs_ready_contract_stages_as_parallel_batch(tmp_path):
    dag_path = _write_parallel_contract_repo(tmp_path)
    repo_root = tmp_path / "repo"
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    started: list[str] = []

    def _stage(unit_id: str):
        def _run(*, repo_root: Path, run_root: Path) -> dict[str, object]:
            with lock:
                started.append(unit_id)
            barrier.wait(timeout=1.0)
            return {
                "summary_metrics_path": f"{unit_id}/summary.json",
                "reduce_artifact_path": f"{unit_id}/reduce.json",
                "summary_metrics": {"stage_completed": 1},
            }

        return _run

    engine = dag_run_engine.DagRunEngine(
        repo_root=repo_root,
        lab_dir=tmp_path / "lab",
        dag_path=dag_path,
        stage_run_fns={
            "uav_queue_project.queue_context": _stage("queue_context"),
            "flight_telemetry_project.flight_context": _stage("flight_context"),
        },
        now_fn=lambda: "2026-05-07T00:00:00Z",
    )
    state, _state_path, _dag_path = engine.load_or_create_state()

    result = engine.run_ready_controlled_stages(state)

    assert result.ok
    assert result.executed_unit_ids == ("flight_context", "queue_context")
    assert sorted(started) == ["flight_context", "queue_context"]
    assert result.state["summary"]["completed_unit_ids"] == ["flight_context", "queue_context"]
    assert result.state["summary"]["runnable_unit_ids"] == ["joined_review"]
    assert result.state["summary"]["available_artifact_ids"] == ["flight_metrics", "queue_metrics"]
    assert result.state["summary"]["controlled_executed_unit_ids"] == ["flight_context", "queue_context"]
    assert result.state["provenance"]["controlled_execution"] is True
    assert result.state["provenance"]["real_app_execution"] is False
    queue = next(unit for unit in result.state["units"] if unit["id"] == "queue_context")
    flight = next(unit for unit in result.state["units"] if unit["id"] == "flight_context")
    assert queue["execution_mode"] == "contract_adapter"
    assert flight["execution_mode"] == "contract_adapter"


def test_dag_run_engine_run_ready_wraps_single_stage_adapter(tmp_path):
    repo_root = Path.cwd()
    calls: list[Path] = []

    def _fake_queue_run(*, repo_root: Path, run_root: Path) -> dict[str, object]:
        calls.append(run_root)
        return {
            "summary_metrics_path": "queue/summary.json",
            "reduce_artifact_path": "queue/reduce.json",
            "summary_metrics": {"packets_generated": 3, "packets_delivered": 3},
        }

    engine = dag_run_engine.DagRunEngine(
        repo_root=repo_root,
        lab_dir=tmp_path,
        dag_path=_sample_dag_path(repo_root),
        run_queue_fn=_fake_queue_run,
        now_fn=lambda: "2026-05-07T00:00:00Z",
    )
    state, _state_path, _dag_path = engine.load_or_create_state()

    result = engine.run_ready_controlled_stages(state)

    assert result.ok
    assert result.executed_unit_ids == (dag_run_engine.GLOBAL_DAG_QUEUE_UNIT_ID,)
    assert calls == [tmp_path / ".agilab" / "global_dag_real_runs" / "queue_baseline"]
    assert result.state["summary"]["completed_unit_ids"] == ["queue_baseline"]
    assert result.state["summary"]["runnable_unit_ids"] == ["relay_followup"]


def test_dag_run_engine_run_ready_contract_batch_reports_no_ready_stage(tmp_path):
    dag_path = _write_parallel_contract_repo(tmp_path)
    repo_root = tmp_path / "repo"
    engine = dag_run_engine.DagRunEngine(
        repo_root=repo_root,
        lab_dir=tmp_path / "lab",
        dag_path=dag_path,
    )
    state, _state_path, _dag_path = engine.load_or_create_state()
    for unit in state["units"]:
        unit["dispatch_status"] = "completed"

    result = engine.run_ready_controlled_stages(state)

    assert not result.ok
    assert result.message == "No controlled contract DAG stages are ready to run."
    assert result.executed_unit_ids == ()
    assert result.failed_unit_ids == ()
    assert set(result.state["summary"]["completed_unit_ids"]) == {
        "flight_context",
        "joined_review",
        "queue_context",
    }


def test_dag_run_engine_run_ready_contract_batch_reports_partial_failure(tmp_path):
    dag_path = _write_parallel_contract_repo(tmp_path)
    repo_root = tmp_path / "repo"

    def _pass_stage(*, repo_root: Path, run_root: Path) -> dict[str, object]:
        return {
            "summary_metrics_path": "queue/summary.json",
            "summary_metrics": {"stage_completed": 1},
        }

    def _fail_stage(*, repo_root: Path, run_root: Path) -> dict[str, object]:
        raise RuntimeError("synthetic flight failure")

    engine = dag_run_engine.DagRunEngine(
        repo_root=repo_root,
        lab_dir=tmp_path / "lab",
        dag_path=dag_path,
        stage_run_fns={
            "uav_queue_project.queue_context": _pass_stage,
            "flight_telemetry_project.flight_context": _fail_stage,
        },
        now_fn=lambda: "2026-05-07T00:00:00Z",
    )
    state, _state_path, _dag_path = engine.load_or_create_state()

    result = engine.run_ready_controlled_stages(state, max_workers=2)

    assert not result.ok
    assert set(result.executed_unit_ids) == {"queue_context"}
    assert set(result.failed_unit_ids) == {"flight_context"}
    assert "synthetic flight failure" in result.message
    queue = _unit_by_id(result.state, "queue_context")
    flight = _unit_by_id(result.state, "flight_context")
    assert queue["dispatch_status"] == "completed"
    assert flight["dispatch_status"] == "failed"
    assert flight["operator_ui"]["message"] == "synthetic flight failure"
    assert result.state["summary"]["failed_unit_ids"] == ["flight_context"]


def test_dag_run_engine_runs_ready_contract_stages_through_distributed_submitter(tmp_path):
    dag_path = _write_parallel_contract_repo(tmp_path)
    repo_root = tmp_path / "repo"
    submissions: list[dict[str, object]] = []

    def _submit_stage(
        *,
        repo_root: Path,
        lab_dir: Path,
        run_root: Path,
        unit: dict[str, object],
        artifact: dict[str, object],
        execution_contract: dict[str, object],
        timestamp: str,
    ) -> dict[str, object]:
        unit_id = str(unit["id"])
        submissions.append(
            {
                "unit_id": unit_id,
                "repo_root": repo_root,
                "lab_dir": lab_dir,
                "run_root": run_root,
                "entrypoint": execution_contract["entrypoint"],
                "timestamp": timestamp,
            }
        )
        return {
            "summary_metrics_path": f"{unit_id}/distributed-summary.json",
            "reduce_artifact_path": f"{unit_id}/distributed-reduce.json",
            "summary_metrics": {"stage_completed": 1, "distributed_submissions": 1},
        }

    engine = dag_run_engine.DagRunEngine(
        repo_root=repo_root,
        lab_dir=tmp_path / "lab",
        dag_path=dag_path,
        stage_submit_fn=_submit_stage,
        now_fn=lambda: "2026-05-07T00:00:00Z",
    )
    state, _state_path, _dag_path = engine.load_or_create_state()

    result = engine.run_ready_controlled_stages(
        state,
        execution_backend=dag_run_engine.GLOBAL_DAG_STAGE_BACKEND_DISTRIBUTED,
    )

    assert engine.distributed_stage_supported()
    assert result.ok
    assert result.executed_unit_ids == ("flight_context", "queue_context")
    submitted_unit_ids = [
        submission["unit_id"]
        for submission in sorted(submissions, key=lambda row: str(row["unit_id"]))
    ]
    assert submitted_unit_ids == [
        "flight_context",
        "queue_context",
    ]
    assert all(submission["lab_dir"] == tmp_path / "lab" for submission in submissions)
    assert result.state["summary"]["completed_unit_ids"] == ["flight_context", "queue_context"]
    assert result.state["summary"]["runnable_unit_ids"] == ["joined_review"]
    assert result.state["provenance"]["controlled_execution"] is True
    assert result.state["provenance"]["controlled_execution_scope"] == (
        dag_run_engine.GLOBAL_DAG_DISTRIBUTED_CONTRACT_EXECUTION_SCOPE
    )
    flight = next(unit for unit in result.state["units"] if unit["id"] == "flight_context")
    assert flight["execution_mode"] == "distributed_stage"
    assert flight["distributed_execution"]["stage_backend"] == "distributed"
    assert "contract_execution" not in flight


def test_dag_run_engine_distributed_batch_fails_when_submitter_is_missing(tmp_path):
    dag_path = _write_parallel_contract_repo(tmp_path)
    repo_root = tmp_path / "repo"
    engine = dag_run_engine.DagRunEngine(
        repo_root=repo_root,
        lab_dir=tmp_path / "lab",
        dag_path=dag_path,
        now_fn=lambda: "2026-05-07T00:00:00Z",
    )
    state, _state_path, _dag_path = engine.load_or_create_state()

    result = engine.run_ready_controlled_stages(
        state,
        execution_backend=dag_run_engine.GLOBAL_DAG_STAGE_BACKEND_DISTRIBUTED,
    )

    assert not engine.distributed_stage_supported()
    assert not result.ok
    assert result.executed_unit_ids == ()
    assert result.failed_unit_ids == ("flight_context", "queue_context")
    assert "Distributed DAG stage backend is not configured" in result.message
    flight = next(unit for unit in result.state["units"] if unit["id"] == "flight_context")
    assert flight["execution_mode"] == "distributed_stage"
    assert "Distributed DAG stage backend is not configured" in flight["operator_ui"]["message"]


def test_dag_run_engine_keeps_workspace_copy_preview_only(tmp_path):
    repo_root = Path.cwd()
    dag_path = tmp_path / "copied-uav-template.json"
    dag_path.write_text(_app_template_dag_path(repo_root).read_text(encoding="utf-8"), encoding="utf-8")
    engine = dag_run_engine.DagRunEngine(repo_root=repo_root, lab_dir=tmp_path / "lab", dag_path=dag_path)
    state, _state_path, _dag_path = engine.load_or_create_state()

    support = engine.real_run_support(state)
    result = engine.run_next_controlled_stage(state)

    assert not support.supported
    assert support.status == "Preview-only"
    assert "Workspace and custom DAGs remain preview-only" in support.message
    assert not result.ok
    assert "Workspace and custom DAGs remain preview-only" in result.message
    ready_result = engine.run_ready_controlled_stages(state)
    assert not ready_result.ok
    assert "Workspace and custom DAGs remain preview-only" in ready_result.message


def test_dag_run_engine_executes_controlled_relay_stage_after_queue(tmp_path):
    repo_root = Path.cwd()
    relay_calls: list[dict[str, object]] = []

    def _fake_queue_run(*, repo_root: Path, run_root: Path) -> dict[str, object]:
        return {
            "summary_metrics_path": "queue/summary.json",
            "reduce_artifact_path": "queue/reduce.json",
            "summary_metrics": {"packets_generated": 8, "packets_delivered": 7},
        }

    def _fake_relay_run(
        *,
        repo_root: Path,
        run_root: Path,
        queue_result: dict[str, object],
    ) -> dict[str, object]:
        relay_calls.append({"run_root": run_root, "queue_result": queue_result})
        return {
            "summary_metrics_path": "relay/summary.json",
            "reduce_artifact_path": "relay/reduce.json",
            "summary_metrics": {"packets_generated": 5, "packets_delivered": 5},
            "consumed_artifacts": [
                {
                    "artifact": "queue_metrics",
                    "path": str(queue_result.get("summary_metrics_path", "")),
                    "producer": "queue_baseline",
                }
            ],
        }

    engine = dag_run_engine.DagRunEngine(
        repo_root=repo_root,
        lab_dir=tmp_path,
        dag_path=_sample_dag_path(repo_root),
        run_queue_fn=_fake_queue_run,
        run_relay_fn=_fake_relay_run,
        now_fn=lambda: "2026-05-07T00:00:00Z",
    )
    state, _state_path, _dag_path = engine.load_or_create_state()
    queue_result = engine.run_next_controlled_stage(state)

    relay_result = engine.run_next_controlled_stage(queue_result.state)

    assert relay_result.ok
    assert relay_result.executed_unit_id == dag_run_engine.GLOBAL_DAG_RELAY_UNIT_ID
    assert relay_calls == [
        {
            "run_root": tmp_path / ".agilab" / "global_dag_real_runs" / "relay_followup",
            "queue_result": relay_result.state["units"][0]["real_execution"],
        }
    ]
    assert relay_result.state["run_status"] == "completed"
    assert relay_result.state["summary"]["completed_unit_ids"] == ["queue_baseline", "relay_followup"]
    assert relay_result.state["summary"]["real_executed_unit_ids"] == ["queue_baseline", "relay_followup"]
    relay = next(unit for unit in relay_result.state["units"] if unit["id"] == "relay_followup")
    assert relay["real_execution"]["consumed_artifacts"][0]["path"] == "queue/summary.json"


def test_execution_history_rows_skip_planning_and_sort_latest_first():
    rows = dag_run_engine.execution_history_rows(
        {
            "events": [
                {
                    "timestamp": "2026-05-07T00:00:00Z",
                    "kind": "run_planned",
                    "unit_id": "",
                    "from_status": "",
                    "to_status": "planned",
                    "detail": "created",
                },
                {
                    "timestamp": "2026-05-07T00:01:00Z",
                    "kind": "unit_dispatched",
                    "unit_id": "queue_baseline",
                    "from_status": "runnable",
                    "to_status": "running",
                    "detail": "preview",
                },
                {
                    "timestamp": "2026-05-07T00:02:00Z",
                    "kind": "unit_completed",
                    "unit_id": "queue_baseline",
                    "from_status": "running",
                    "to_status": "completed",
                    "detail": "real run",
                },
            ]
        }
    )

    assert [row["Event"] for row in rows] == ["unit completed", "unit dispatched"]
    assert rows[0]["Status"] == "running -> completed"


def test_dag_run_engine_helper_edge_branches(tmp_path):
    repo_root = Path.cwd()
    external = tmp_path / "external-dag.json"

    assert dag_run_engine.repo_relative_text(external, repo_root) == str(external)
    assert dag_run_engine.runner_state_dag_matches({}, None, repo_root)
    assert not dag_run_engine.runner_state_dag_matches({"source": "bad"}, _sample_dag_path(repo_root), repo_root)
    assert dag_run_engine.execution_history_rows({"events": "bad"}) == []
    assert dag_run_engine.execution_history_rows(
        {
            "events": [
                "bad",
                {
                    "timestamp": "2026-05-07T00:03:00Z",
                    "kind": "unit_completed",
                    "unit_id": "",
                    "from_status": "",
                    "to_status": "",
                    "detail": "no status",
                },
            ]
        }
    ) == [
        {
            "Time": "2026-05-07T00:03:00Z",
            "Stage": "-",
            "Event": "unit completed",
            "Status": "-",
            "Detail": "no status",
        }
    ]

    engine = dag_run_engine.DagRunEngine(
        repo_root=repo_root,
        lab_dir=tmp_path,
        dag_path=_app_template_dag_path(repo_root),
    )
    state, _state_path, _dag_path = engine.load_or_create_state()
    assert engine.real_run_supported(state)
    assert dag_run_engine.controlled_real_run_supported(state, _app_template_dag_path(repo_root), repo_root)


def test_dag_engine_loads_saved_draft_and_dispatches_first_runnable_stage(tmp_path):
    repo_root = Path.cwd()
    dag_path = tmp_path / "workspace-dag.json"
    payload = multi_app_dag_draft.build_dag_payload_from_editor(
        {"execution": {"mode": "sequential_dependency_order", "runner_status": "contract_only"}},
        dag_id="workspace-uav-dag",
        label="Workspace UAV DAG",
        description="Preview dispatch from a saved workspace DAG.",
        stage_rows=[
            {"id": "queue", "app": "uav_queue_project", "purpose": "Generate metrics."},
            {"id": "relay", "app": "uav_relay_queue_project", "purpose": "Consume metrics."},
        ],
        produced_artifact_rows=[
            {"node": "queue", "id": "queue_metrics", "kind": "summary_metrics", "path": "queue/summary.json"}
        ],
        consumed_artifact_rows=[
            {"node": "relay", "id": "queue_metrics", "kind": "summary_metrics", "path": "queue/summary.json"}
        ],
        handoff_rows=[
            {"from": "queue", "to": "relay", "artifact": "queue_metrics", "handoff": "Pass queue metrics."}
        ],
    )
    dag_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    engine = dag_run_engine.DagRunEngine(
        repo_root=repo_root,
        lab_dir=tmp_path / "lab",
        dag_path=dag_path,
    )

    state, state_path, loaded_dag_path = engine.load_or_create_state()
    dispatched = engine.dispatch_next_runnable(state)
    engine.write_state(dispatched.state)
    reloaded, _state_path, _dag_path = engine.load_or_create_state()

    assert state_path == tmp_path / "lab" / ".agilab" / "runner_state.json"
    assert loaded_dag_path == dag_path
    assert dispatched.ok
    assert dispatched.dispatched_unit_id == "queue"
    assert reloaded["summary"]["running_unit_ids"] == ["queue"]
    assert reloaded["summary"]["blocked_unit_ids"] == ["relay"]
