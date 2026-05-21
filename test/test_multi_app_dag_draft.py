from __future__ import annotations

import builtins
import importlib.util
from pathlib import Path
import sys

import pytest


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


def _load_module(module_name: str, relative_path: str):
    _ensure_agilab_package_path()
    module_path = Path(relative_path)
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


multi_app_dag = _load_module("agilab.multi_app_dag", "src/agilab/multi_app_dag.py")
multi_app_dag_draft = _load_module("agilab.multi_app_dag_draft", "src/agilab/multi_app_dag_draft.py")


def test_dag_draft_spec_builds_payload_from_structured_rows():
    payload = multi_app_dag_draft.build_dag_payload_from_editor(
        {"execution": {"mode": "sequential_dependency_order", "runner_status": "contract_only"}},
        dag_id="uav-queue-relay",
        label="UAV queue to relay",
        description="Pass queue metrics to the relay app.",
        stage_rows=[
            {"id": "queue", "app": "uav_queue_project", "purpose": "Generate queue metrics."},
            {"id": "relay", "app": "uav_relay_queue_project", "purpose": "Consume queue metrics."},
        ],
        produced_artifact_rows=[
            {"node": "queue", "id": "queue_metrics", "kind": "summary_metrics", "path": "queue/summary.json"}
        ],
        consumed_artifact_rows=[
            {"node": "relay", "id": "queue_metrics", "kind": "summary_metrics", "path": "queue/summary.json"}
        ],
        handoff_rows=[
            {"from": "queue", "to": "relay", "artifact": "queue_metrics", "handoff": "Use queue metrics."}
        ],
    )

    assert payload["schema"] == multi_app_dag.SCHEMA
    assert payload["dag_id"] == "uav-queue-relay"
    assert payload["nodes"] == [
        {
            "id": "queue",
            "app": "uav_queue_project",
            "purpose": "Generate queue metrics.",
            "produces": [{"id": "queue_metrics", "kind": "summary_metrics", "path": "queue/summary.json"}],
        },
        {
            "id": "relay",
            "app": "uav_relay_queue_project",
            "purpose": "Consume queue metrics.",
            "consumes": [{"id": "queue_metrics", "kind": "summary_metrics", "path": "queue/summary.json"}],
        },
    ]
    assert payload["edges"] == [
        {"from": "queue", "to": "relay", "artifact": "queue_metrics", "handoff": "Use queue metrics."}
    ]
    assert multi_app_dag.validate_multi_app_dag(payload, repo_root=Path.cwd()).ok


def test_dag_draft_can_emit_controlled_contract_execution_marker():
    payload = multi_app_dag_draft.build_dag_payload_from_editor(
        {"execution": {"mode": "sequential_dependency_order", "runner_status": "contract_only"}},
        dag_id="uav-queue-relay",
        label="UAV queue to relay",
        description="Pass queue metrics to the relay app.",
        stage_rows=[
            {"id": "queue", "app": "uav_queue_project", "purpose": "Generate queue metrics."},
            {"id": "relay", "app": "uav_relay_queue_project", "purpose": "Consume queue metrics."},
        ],
        produced_artifact_rows=[
            {"node": "queue", "id": "queue_metrics", "kind": "summary_metrics", "path": "queue/summary.json"}
        ],
        consumed_artifact_rows=[
            {"node": "relay", "id": "queue_metrics", "kind": "summary_metrics", "path": "queue/summary.json"}
        ],
        handoff_rows=[
            {"from": "queue", "to": "relay", "artifact": "queue_metrics", "handoff": "Use queue metrics."}
        ],
        controlled_contract_execution=True,
    )

    assert payload["execution"] == multi_app_dag_draft.CONTROLLED_CONTRACT_EXECUTION
    assert payload["nodes"][0]["execution"] == {"entrypoint": "uav_queue_project.queue"}
    assert payload["nodes"][1]["execution"] == {"entrypoint": "uav_relay_queue_project.relay"}
    assert multi_app_dag.validate_multi_app_dag(payload, repo_root=Path.cwd()).ok


def test_dag_draft_preserves_existing_node_execution_contract():
    payload = multi_app_dag_draft.build_dag_payload_from_editor(
        {
            "execution": multi_app_dag_draft.CONTROLLED_CONTRACT_EXECUTION,
            "nodes": [
                {
                    "id": "queue",
                    "app": "uav_queue_project",
                    "execution": {
                        "entrypoint": "custom.queue",
                        "params": {"scenario": "demo"},
                        "stages": [{"name": "prepare", "args": {"n": 2}}],
                        "data_in": "queue/input",
                        "data_out": "queue/output",
                        "reset_target": False,
                    },
                }
            ],
        },
        dag_id="uav-queue-relay",
        label="UAV queue to relay",
        description="Pass queue metrics to the relay app.",
        stage_rows=[
            {"id": "queue", "app": "uav_queue_project", "purpose": "Generate queue metrics."},
            {"id": "relay", "app": "uav_relay_queue_project", "purpose": "Consume queue metrics."},
        ],
        produced_artifact_rows=[
            {"node": "queue", "id": "queue_metrics", "kind": "summary_metrics", "path": "queue/summary.json"}
        ],
        consumed_artifact_rows=[
            {"node": "relay", "id": "queue_metrics", "kind": "summary_metrics", "path": "queue/summary.json"}
        ],
        handoff_rows=[
            {"from": "queue", "to": "relay", "artifact": "queue_metrics", "handoff": "Use queue metrics."}
        ],
        controlled_contract_execution=True,
    )

    assert payload["nodes"][0]["execution"] == {
        "entrypoint": "custom.queue",
        "params": {"scenario": "demo"},
        "stages": [{"name": "prepare", "args": {"n": 2}}],
        "data_in": "queue/input",
        "data_out": "queue/output",
        "reset_target": False,
    }
    assert payload["nodes"][1]["execution"] == {"entrypoint": "uav_relay_queue_project.relay"}


def test_dag_draft_rejects_legacy_node_execution_steps_contract():
    with pytest.raises(ValueError, match="Legacy execution keys 'steps'/'run_steps'"):
        multi_app_dag_draft.build_dag_payload_from_editor(
            {
                "execution": multi_app_dag_draft.CONTROLLED_CONTRACT_EXECUTION,
                "nodes": [
                    {
                        "id": "queue",
                        "app": "uav_queue_project",
                        "execution": {
                            "entrypoint": "custom.queue",
                            "steps": [{"name": "prepare", "args": {"n": 2}}],
                        },
                    }
                ],
            },
            dag_id="uav-queue-relay",
            label="UAV queue to relay",
            description="Pass queue metrics to the relay app.",
            stage_rows=[
                {"id": "queue", "app": "uav_queue_project", "purpose": "Generate queue metrics."},
                {"id": "relay", "app": "uav_relay_queue_project", "purpose": "Consume queue metrics."},
            ],
            produced_artifact_rows=[],
            consumed_artifact_rows=[],
            handoff_rows=[],
            controlled_contract_execution=True,
        )


def test_dag_draft_validation_guidance_is_actionable_for_users():
    payload = {
        "schema": multi_app_dag.SCHEMA,
        "dag_id": "",
        "nodes": [],
        "edges": [],
    }

    message = multi_app_dag_draft.format_validation_error_for_user(payload, repo_root=Path.cwd())

    assert "How to fix the DAG draft:" in message
    assert "Name the DAG with a portable DAG id." in message
    assert "Choose at least two stages." in message
    assert "Detail: dag_id: dag_id is required" in message
    assert "Detail: nodes: nodes must be a non-empty list" in message


def test_dag_draft_validation_guidance_explains_bad_handoff():
    payload = {
        "schema": multi_app_dag.SCHEMA,
        "dag_id": "bad-handoff",
        "nodes": [
            {"id": "queue", "app": "uav_queue_project", "produces": [{"id": "queue_metrics", "path": "q.json"}]},
            {"id": "relay", "app": "uav_relay_queue_project"},
        ],
        "edges": [{"from": "queue", "to": "relay", "artifact": "missing_metrics"}],
    }

    message = multi_app_dag_draft.format_validation_error_for_user(payload, repo_root=Path.cwd())

    assert "Select the artifact as a produced artifact for the source stage" in message
    assert "source node does not produce artifact 'missing_metrics'" in message


def test_dag_draft_clean_cell_and_editor_rows_handle_empty_inputs(monkeypatch):
    assert multi_app_dag_draft.clean_dag_cell(float("nan")) == ""
    assert multi_app_dag_draft.dag_editor_rows(None, ["id"]) == []
    assert multi_app_dag_draft.dag_editor_rows(["skip", {"id": "  node  "}, {"id": "  "}], ["id"]) == [
        {"id": "node"}
    ]

    real_import = builtins.__import__

    def _raise_pandas_import(name, *args, **kwargs):
        if name == "pandas":
            raise ImportError("pandas unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _raise_pandas_import)
    assert multi_app_dag_draft.clean_dag_cell(" nan ") == ""
    assert multi_app_dag_draft.dag_editor_rows([{"id": "node"}], ["id"]) == [{"id": "node"}]


def test_dag_draft_base_node_and_execution_edge_cases():
    assert multi_app_dag_draft._base_nodes_by_id(None) == {}
    assert multi_app_dag_draft._base_nodes_by_id({"nodes": "not-list"}) == {}
    assert multi_app_dag_draft._base_nodes_by_id({"nodes": ["skip", {"id": "node"}]}) == {
        "node": {"id": "node"}
    }

    execution = multi_app_dag_draft._node_execution_payload(
        {
            "execution": {
                "entrypoint": "  demo.run  ",
                "command": [" python ", "", " task.py "],
                "run_params": {"n": 2},
                "rapids_enabled": 1,
                "benchmark_best_single_node": "",
            }
        }
    )
    assert execution == {
        "entrypoint": "demo.run",
        "command": ["python", "task.py"],
        "params": {"n": 2},
        "rapids_enabled": True,
        "benchmark_best_single_node": False,
    }

    assert multi_app_dag_draft._node_execution_payload({"execution": {"command": " python task.py "}}) == {
        "command": "python task.py"
    }
    assert multi_app_dag_draft._artifacts_by_node(
        [
            multi_app_dag_draft.DagArtifact(node="", id="a", path="a.json"),
            multi_app_dag_draft.DagArtifact(node="stage", id="", path="a.json"),
            multi_app_dag_draft.DagArtifact(node="stage", id="a", path=""),
            multi_app_dag_draft.DagArtifact(node="stage", id="a", path="a.json"),
        ]
    ) == {
        "stage": [multi_app_dag_draft.DagArtifact(node="stage", id="a", path="a.json")]
    }


def test_dag_draft_guidance_covers_common_validation_messages():
    guidance = multi_app_dag_draft._user_guidance_for_issue

    assert guidance("edges", "DAG must include at least one cross-app edge").startswith("Connect stages")
    assert guidance("edges[0]", "target node does not consume artifact 'x'").startswith("Let the editor")
    assert guidance("edges", "dependency graph contains a cycle").startswith("Remove the circular")
    assert guidance("nodes[0].produces[0]", "artifact path must be portable and relative").startswith(
        "Use relative"
    )
    assert guidance("nodes[0]", "node app 'missing' is not a checked-in built-in app").startswith(
        "Choose an app"
    )
    assert guidance("schema", "unsupported schema").startswith("unsupported schema")
