from __future__ import annotations

import importlib
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


_ensure_agilab_package_path()
dag_run_engine = importlib.import_module("agilab.dag_run_engine")
evidence_graph = importlib.import_module("agilab.evidence_graph")
workflow_run_manifest = importlib.import_module("agilab.workflow_run_manifest")
runtime_contract = importlib.import_module("agilab.workflow_runtime_contract")

LATEST_WORKFLOW_EVIDENCE_FILENAME = workflow_run_manifest.LATEST_WORKFLOW_EVIDENCE_FILENAME
WORKFLOW_EVIDENCE_DIRNAME = workflow_run_manifest.WORKFLOW_EVIDENCE_DIRNAME
load_evidence_ledger = workflow_run_manifest.load_evidence_ledger
load_workflow_run_manifest = workflow_run_manifest.load_workflow_run_manifest
sha256_payload = workflow_run_manifest.sha256_payload
workflow_manifest_summary = workflow_run_manifest.workflow_manifest_summary
write_workflow_run_evidence = workflow_run_manifest.write_workflow_run_evidence


def _sample_state(*, run_status: str = "completed") -> dict[str, object]:
    return {
        "schema": "agilab.global_pipeline_runner_state.v1",
        "run_id": "demo-run",
        "run_status": run_status,
        "created_at": "2026-05-12T08:00:00Z",
        "updated_at": "2026-05-12T08:01:00Z",
        "source": {
            "source_type": "multi_app_dag",
            "dag_path": "src/agilab/apps/builtin/uav_queue_project/dag_templates/uav_queue_to_relay.json",
            "plan_schema": "agilab.multi_app_dag.v1",
            "plan_runner_status": "controlled_contract_stage_execution",
            "execution_order": ["queue_context", "relay_review"],
        },
        "summary": {
            "unit_count": 2,
            "completed_count": 2,
            "failed_count": 0,
            "available_artifact_ids": ["queue_metrics", "relay_metrics"],
        },
        "units": [
            {
                "id": "queue_context",
                "order_index": 0,
                "app": "uav_queue_project",
                "dispatch_status": "completed",
                "depends_on": [],
                "produces": [
                    {"artifact": "queue_metrics", "kind": "summary_metrics", "path": "queue/metrics.json"}
                ],
                "artifact_dependencies": [],
                "execution_contract": {"entrypoint": "uav_queue_project.queue_context"},
            },
            {
                "id": "relay_review",
                "order_index": 1,
                "app": "uav_relay_queue_project",
                "dispatch_status": "completed" if run_status == "completed" else "failed",
                "depends_on": ["queue_context"],
                "produces": [
                    {"artifact": "relay_metrics", "kind": "summary_metrics", "path": "relay/metrics.json"}
                ],
                "artifact_dependencies": [
                    {
                        "artifact": "queue_metrics",
                        "from": "queue_context",
                        "from_app": "uav_queue_project",
                        "source_path": "queue/metrics.json",
                    }
                ],
                "execution_contract": {"entrypoint": "uav_relay_queue_project.relay_review"},
            },
        ],
        "artifacts": [],
        "events": [
            {
                "timestamp": "2026-05-12T08:01:00Z",
                "kind": "unit_completed",
                "unit_id": "relay_review",
                "from_status": "running",
                "to_status": run_status,
                "detail": "sample state",
            }
        ],
    }


def test_workflow_run_manifest_writes_immutable_manifest_and_ledger(tmp_path: Path) -> None:
    lab_dir = tmp_path / "lab"
    state_path = lab_dir / ".agilab" / "runner_state.json"
    state_path.parent.mkdir(parents=True)
    state = _sample_state()
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    first = write_workflow_run_evidence(
        state=state,
        state_path=state_path,
        repo_root=tmp_path,
        lab_dir=lab_dir,
        trigger={"surface": "test", "action": "write"},
    )
    second = write_workflow_run_evidence(
        state=state,
        state_path=state_path,
        repo_root=tmp_path,
        lab_dir=lab_dir,
        trigger={"surface": "test", "action": "write"},
    )

    assert first.manifest_path == second.manifest_path
    assert first.ledger_path == second.ledger_path
    assert first.graph_path == second.graph_path
    assert first.latest_path == lab_dir / ".agilab" / WORKFLOW_EVIDENCE_DIRNAME / LATEST_WORKFLOW_EVIDENCE_FILENAME

    manifest = load_workflow_run_manifest(first.manifest_path)
    ledger = load_evidence_ledger(first.ledger_path)
    graph = json.loads(first.graph_path.read_text(encoding="utf-8"))
    summary = workflow_manifest_summary(manifest)

    assert manifest["schema_version"] == workflow_run_manifest.WORKFLOW_RUN_MANIFEST_SCHEMA_VERSION
    assert "-v3-" in manifest["manifest_id"]
    assert manifest["status"] == "pass"
    assert first.graph == graph
    assert first.graph_path == first.manifest_path.parent / workflow_run_manifest.EVIDENCE_GRAPH_FILENAME
    assert evidence_graph.validate_evidence_graph(graph) == ()
    assert graph["summary"]["node_kinds"]["stage"] == 2
    assert summary["unit_count"] == 2
    assert summary["produced_count"] == 2
    assert summary["consumed_count"] == 1
    assert summary["phase"] == "completed"
    assert summary["event_count"] == 1
    assert manifest["runtime_contract"]["schema"] == runtime_contract.WORKFLOW_RUNTIME_CONTRACT_SCHEMA
    assert manifest["runtime_contract"]["phase"] == "completed"
    assert runtime_contract.enabled_workflow_control_labels(manifest["runtime_contract"]) == ()
    assert manifest["runner_state"]["sha256"]
    assert manifest["runner_state"]["snapshot_sha256"]
    assert ledger["manifest_id"] == manifest["manifest_id"]
    assert ledger["claims"]
    assert {
        artifact["name"]
        for artifact in ledger["artifacts"]
    } >= {workflow_run_manifest.EVIDENCE_GRAPH_FILENAME, workflow_run_manifest.WORKFLOW_RUN_MANIFEST_FILENAME}
    assert {
        evidence["sha256"]
        for claim in ledger["claims"]
        for evidence in claim["evidence"]
        if evidence["kind"] == "agilab.workflow_run_manifest"
    } == {sha256_payload(manifest)}


def test_workflow_run_manifest_loads_legacy_schema_v2_without_graph(tmp_path: Path) -> None:
    legacy_path = tmp_path / "legacy_workflow_run_manifest.json"
    legacy_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "kind": workflow_run_manifest.WORKFLOW_RUN_MANIFEST_KIND,
                "manifest_id": "legacy-demo",
                "run_id": "legacy-run",
                "status": "unknown",
                "workflow": {"unit_count": 0},
                "artifact_contracts": {"produced_count": 0, "consumed_count": 0},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    manifest = load_workflow_run_manifest(legacy_path)
    summary = workflow_manifest_summary(manifest)

    assert manifest["schema_version"] == 2
    assert summary["manifest_id"] == "legacy-demo"
    assert summary["phase"] == "unknown"
    assert "evidence_graph" not in manifest


def test_dag_run_engine_emits_workflow_evidence_on_state_writes(tmp_path: Path) -> None:
    repo_root = Path.cwd()

    def _fake_queue_run(*, repo_root: Path, run_root: Path) -> dict[str, object]:
        return {
            "summary_metrics_path": str(run_root / "queue_metrics.json"),
            "reduce_artifact_path": str(run_root / "queue_reduce.json"),
            "summary_metrics": {"packets_generated": 3, "packets_delivered": 3},
        }

    engine = dag_run_engine.DagRunEngine(
        repo_root=repo_root,
        lab_dir=tmp_path,
        dag_path=repo_root / dag_run_engine.GLOBAL_DAG_SAMPLE_RELATIVE_PATH,
        run_queue_fn=_fake_queue_run,
        now_fn=lambda: "2026-05-12T08:00:00Z",
    )

    state, state_path, _dag_path = engine.load_or_create_state()
    latest_path = tmp_path / ".agilab" / WORKFLOW_EVIDENCE_DIRNAME / LATEST_WORKFLOW_EVIDENCE_FILENAME
    planned_latest = json.loads(latest_path.read_text(encoding="utf-8"))
    planned_manifest = load_workflow_run_manifest(Path(planned_latest["manifest_path"]))
    assert planned_manifest["status"] == "unknown"

    result = engine.run_next_controlled_stage(state)
    assert result.ok is True
    engine.write_state(result.state)

    executed_latest = json.loads(latest_path.read_text(encoding="utf-8"))
    executed_manifest = load_workflow_run_manifest(Path(executed_latest["manifest_path"]))
    executed_ledger = load_evidence_ledger(Path(executed_latest["ledger_path"]))

    assert state_path == tmp_path / ".agilab" / "runner_state.json"
    assert executed_latest["manifest_id"] != planned_latest["manifest_id"]
    assert executed_manifest["runner_state"]["path"] == str(state_path)
    assert executed_manifest["artifact_contracts"]["produced_count"] >= 1
    assert executed_ledger["manifest_id"] == executed_manifest["manifest_id"]
