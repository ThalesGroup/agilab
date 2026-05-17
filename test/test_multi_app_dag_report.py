from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


REPORT_PATH = Path("tools/multi_app_dag_report.py").resolve()
CORE_PATH = Path("src/agilab/multi_app_dag.py").resolve()


def _load_report_module():
    spec = importlib.util.spec_from_file_location("multi_app_dag_report_test_module", REPORT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_core_module():
    spec = importlib.util.spec_from_file_location("multi_app_dag_test_module", CORE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _repo_with_apps(tmp_path: Path, *apps: str) -> Path:
    builtin_root = tmp_path / "src" / "agilab" / "apps" / "builtin"
    for app in apps:
        app_root = builtin_root / app
        app_root.mkdir(parents=True)
        (app_root / "pyproject.toml").write_text("[project]\nname = 'test-app'\n", encoding="utf-8")
    return tmp_path


def test_multi_app_dag_report_validates_checked_in_sample() -> None:
    module = _load_report_module()

    report = module.build_report(repo_root=Path.cwd())

    assert report["report"] == "Multi-app DAG report"
    assert report["status"] == "pass"
    assert report["dag_path"] == "docs/source/data/multi_app_dag_sample.json"
    assert report["summary"]["node_count"] == 2
    assert report["summary"]["edge_count"] == 1
    assert report["summary"]["app_count"] == 2
    assert report["summary"]["cross_app_edge_count"] == 1
    assert report["summary"]["execution_order"] == ["queue_baseline", "relay_followup"]
    assert report["summary"]["sample_count"] == 2
    assert report["summary"]["supplemental_sample_count"] == 1
    assert report["summary"]["suite_node_count"] == 6
    assert report["summary"]["suite_edge_count"] == 4
    assert report["summary"]["suite_app_count"] == 6
    assert report["summary"]["suite_cross_app_edge_count"] == 4
    assert report["summary"]["supplemental_dag_paths"] == [
        "docs/source/data/multi_app_dag_portfolio_sample.json"
    ]
    assert report["summary"]["artifact_handoffs"] == [
        {
            "artifact": "queue_metrics",
            "from": "queue_baseline",
            "from_app": "uav_queue_project",
            "handoff": "Use base queue summary metrics as the relay scenario context.",
            "source_path": "queue_analysis/uav_queue_summary_metrics.json",
            "to": "relay_followup",
            "to_app": "uav_relay_queue_project",
        }
    ]
    assert {check["id"] for check in report["checks"]} == {
        "multi_app_dag_schema",
        "multi_app_dag_app_nodes",
        "multi_app_dag_dependencies",
        "multi_app_dag_artifact_handoffs",
        "multi_app_dag_sample_suite",
        "multi_app_dag_docs_reference",
    }


def test_multi_app_dag_report_validates_portfolio_sample() -> None:
    module = _load_report_module()

    report = module.build_report(
        repo_root=Path.cwd(),
        dag_path=Path("docs/source/data/multi_app_dag_portfolio_sample.json"),
    )

    assert report["status"] == "pass"
    assert report["dag_path"] == "docs/source/data/multi_app_dag_portfolio_sample.json"
    assert report["summary"]["node_count"] == 4
    assert report["summary"]["edge_count"] == 3
    assert report["summary"]["app_count"] == 4
    assert report["summary"]["cross_app_edge_count"] == 3
    assert report["summary"]["execution_order"] == [
        "flight_context",
        "weather_forecast_review",
        "pandas_benchmark_review",
        "polars_benchmark_review",
    ]
    assert "sample_count" not in report["summary"]
    assert {handoff["artifact"] for handoff in report["summary"]["artifact_handoffs"]} == {
        "flight_reduce_summary",
        "forecast_metrics",
    }
    assert {check["id"] for check in report["checks"]} == {
        "multi_app_dag_schema",
        "multi_app_dag_app_nodes",
        "multi_app_dag_dependencies",
        "multi_app_dag_artifact_handoffs",
        "multi_app_dag_docs_reference",
    }


def test_multi_app_dag_validation_reports_cycles_and_missing_handoffs(tmp_path: Path) -> None:
    module = _load_report_module()
    bad_dag = tmp_path / "bad_dag.json"
    bad_dag.write_text(
        json.dumps(
            {
                "schema": "agilab.multi_app_dag.v1",
                "dag_id": "bad-cycle",
                "nodes": [
                    {
                        "id": "a",
                        "app": "uav_queue_project",
                        "produces": [{"id": "a_out", "path": "a.json"}],
                    },
                    {
                        "id": "b",
                        "app": "uav_relay_queue_project",
                        "produces": [{"id": "b_out", "path": "b.json"}],
                    },
                ],
                "edges": [
                    {"from": "a", "to": "b", "artifact": "a_out"},
                    {"from": "b", "to": "a", "artifact": "missing"},
                ],
            }
        ),
        encoding="utf-8",
    )

    report = module.build_report(repo_root=Path.cwd(), dag_path=bad_dag)

    assert report["status"] == "fail"
    issue_messages = {
        issue["message"]
        for issue in report["summary"]["issues"]
    }
    assert "dependency graph contains a cycle" in issue_messages
    assert "source node does not produce artifact 'missing'" in issue_messages


def test_multi_app_dag_validation_rejects_nonportable_artifact_paths() -> None:
    module = _load_core_module()
    payload = {
        "schema": "agilab.multi_app_dag.v1",
        "dag_id": "absolute-path",
        "nodes": [
            {
                "id": "a",
                "app": "uav_queue_project",
                "produces": [{"id": "artifact", "path": "/tmp/output.json"}],
            },
            {
                "id": "b",
                "app": "uav_relay_queue_project",
                "consumes": [{"id": "artifact", "path": "../input.json"}],
            },
        ],
        "edges": [{"from": "a", "to": "b", "artifact": "artifact"}],
    }

    result = module.validate_multi_app_dag(payload, repo_root=Path.cwd())

    assert result.ok is False
    assert {
        issue.message
        for issue in result.issues
    } >= {
        "artifact path must be portable and relative",
    }


def test_multi_app_dag_load_rejects_non_object_payload(tmp_path: Path) -> None:
    module = _load_core_module()
    dag_path = tmp_path / "dag.json"
    dag_path.write_text("[]", encoding="utf-8")

    try:
        module.load_multi_app_dag(dag_path)
    except ValueError as exc:
        assert "must be a JSON object" in str(exc)
    else:
        raise AssertionError("load_multi_app_dag should reject non-object JSON")


def test_multi_app_dag_validation_reports_contract_shape_errors(tmp_path: Path) -> None:
    module = _load_core_module()
    repo_root = _repo_with_apps(tmp_path, "app_a_project", "app_b_project")
    payload = {
        "schema": "wrong",
        "dag_id": "",
        "nodes": [
            "not-object",
            {
                "id": "",
                "app": "",
                "produces": "not-list",
                "consumes": [
                    "not-object",
                    {"id": "", "path": ""},
                    {"id": "dup", "path": "in.json"},
                    {"id": "dup", "path": "in2.json"},
                ],
            },
            {"id": "bad id", "app": "missing_project"},
        ],
        "edges": "not-list",
    }

    result = module.validate_multi_app_dag(payload, repo_root=repo_root)
    messages = {issue.message for issue in result.issues}

    assert result.ok is False
    assert "unsupported schema 'wrong'; expected 'agilab.multi_app_dag.v1'" in messages
    assert "dag_id is required" in messages
    assert "edges must be a list" in messages
    assert "node must be an object" in messages
    assert "node id is required" in messages
    assert "node app is required" in messages
    assert "artifact entries must be a list" in messages
    assert "artifact entry must be an object" in messages
    assert "artifact id is required" in messages
    assert "artifact path is required" in messages
    assert "duplicate artifact id 'dup'" in messages
    assert "node id 'bad id' is not portable" in messages
    assert "node app 'missing_project' is not a checked-in built-in app" in messages


def test_multi_app_dag_validation_reports_edge_shape_errors(tmp_path: Path) -> None:
    module = _load_core_module()
    repo_root = _repo_with_apps(tmp_path, "app_a_project", "app_b_project")
    payload = {
        "schema": "agilab.multi_app_dag.v1",
        "dag_id": "bad-edges",
        "nodes": [
            {
                "id": "a",
                "app": "app_a_project",
                "produces": [{"id": "a_out", "path": "a.json"}],
            },
            {
                "id": "b",
                "app": "app_b_project",
                "consumes": [{"id": "wanted", "path": "wanted.json"}],
            },
            {
                "id": "b",
                "app": "app_b_project",
                "produces": [{"id": "b_out", "path": "b.json"}],
            },
        ],
        "edges": [
            "not-object",
            {"from": "missing", "to": "b", "artifact": "a_out"},
            {"from": "a", "to": "missing", "artifact": "a_out"},
            {"from": "a", "to": "a", "artifact": "a_out"},
            {"from": "a", "to": "b", "artifact": ""},
            {"from": "a", "to": "b", "artifact": "a_out"},
        ],
    }

    result = module.validate_multi_app_dag(payload, repo_root=repo_root)
    messages = {issue.message for issue in result.issues}

    assert result.ok is False
    assert "duplicate node id 'b'" in messages
    assert "edge must be an object" in messages
    assert "edge source 'missing' does not match a node" in messages
    assert "edge target 'missing' does not match a node" in messages
    assert "edge cannot depend on itself" in messages
    assert "edge artifact is required" in messages
    assert "target node does not consume artifact 'a_out'" in messages


def test_multi_app_dag_validation_requires_cross_app_edge_when_edges_exist(tmp_path: Path) -> None:
    module = _load_core_module()
    repo_root = _repo_with_apps(tmp_path, "app_a_project", "app_b_project")
    payload = {
        "schema": "agilab.multi_app_dag.v1",
        "dag_id": "same-app",
        "nodes": [
            {
                "id": "a",
                "app": "app_a_project",
                "produces": [{"id": "a_out", "path": "a.json"}],
            },
            {
                "id": "b",
                "app": "app_a_project",
                "consumes": [{"id": "a_out", "path": "a.json"}],
            },
        ],
        "edges": [{"from": "a", "to": "b", "artifact": "a_out"}],
    }

    result = module.validate_multi_app_dag(payload, repo_root=repo_root)

    assert result.ok is False
    assert "DAG must include at least one cross-app edge" in {issue.message for issue in result.issues}
