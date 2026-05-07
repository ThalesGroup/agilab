from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


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
