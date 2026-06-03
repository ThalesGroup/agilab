from __future__ import annotations

import importlib.util
import importlib
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace


REPORT_PATH = Path("tools/global_pipeline_dag_report.py").resolve()
CORE_PATH = Path("src/agilab/global_pipeline_dag.py").resolve()
SRC_ROOT = Path("src").resolve()


def _load_report_module():
    spec = importlib.util.spec_from_file_location("global_pipeline_dag_report_test_module", REPORT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_core_module():
    package_root = str(SRC_ROOT / "agilab")
    src_root_str = str(SRC_ROOT)
    if src_root_str not in sys.path:
        sys.path.insert(0, src_root_str)
    pkg = sys.modules.get("agilab")
    if pkg is None or not hasattr(pkg, "__path__"):
        pkg = types.ModuleType("agilab")
        pkg.__path__ = [package_root]
        sys.modules["agilab"] = pkg
    else:
        package_path = list(pkg.__path__)
        if package_root not in package_path:
            pkg.__path__ = [package_root, *package_path]
    importlib.invalidate_caches()
    return importlib.import_module("agilab.global_pipeline_dag")


def test_global_pipeline_dag_report_builds_checked_in_graph() -> None:
    module = _load_report_module()

    report = module.build_report(repo_root=Path.cwd())

    assert report["report"] == "Global pipeline DAG report"
    assert report["status"] == "pass"
    assert report["dag_path"] == "docs/source/data/multi_app_dag_sample.json"
    assert report["summary"]["runner_status"] == "not_executed"
    assert report["summary"]["app_node_count"] == 2
    assert report["summary"]["app_step_node_count"] == 8
    assert report["summary"]["local_pipeline_edge_count"] == 6
    assert report["summary"]["cross_app_edge_count"] == 1
    assert report["summary"]["global_node_count"] == 10
    assert report["summary"]["global_edge_count"] == 7
    assert report["summary"]["execution_order"] == ["queue_baseline", "relay_followup"]
    assert {check["id"] for check in report["checks"]} == {
        "global_pipeline_dag_source_contract",
        "global_pipeline_dag_app_views",
        "global_pipeline_dag_graph_shape",
        "global_pipeline_dag_artifact_edge",
        "global_pipeline_dag_docs_reference",
    }

    edge = next(edge for edge in report["graph"]["edges"] if edge["kind"] == "artifact_handoff")
    assert edge == {
        "artifact": "queue_metrics",
        "from": "queue_baseline",
        "from_app": "uav_queue_project",
        "handoff": "Use base queue summary metrics as the relay scenario context.",
        "kind": "artifact_handoff",
        "source": "docs/source/data/multi_app_dag_sample.json",
        "to": "relay_followup",
        "to_app": "uav_relay_queue_project",
    }


def test_parse_pipeline_view_dot_expands_chained_edges() -> None:
    module = _load_core_module()

    parsed = module.parse_pipeline_view_dot(
        """
        digraph demo {
          start [label="Start"];
          middle [label="Middle\\nstep"];
          finish [label="Finish"];
          start -> middle -> finish;
        }
        """
    )

    assert parsed["nodes"] == (
        {"id": "finish", "label": "Finish"},
        {"id": "middle", "label": "Middle | step"},
        {"id": "start", "label": "Start"},
    )
    assert parsed["edges"] == (
        {"from": "start", "to": "middle"},
        {"from": "middle", "to": "finish"},
    )


def test_global_pipeline_dag_reports_missing_pipeline_view(tmp_path: Path) -> None:
    module = _load_core_module()
    dag_path = tmp_path / "dag.json"
    dag_path.write_text(
        json.dumps(
            {
                "schema": "agilab.multi_app_dag.v1",
                "dag_id": "missing-view",
                "nodes": [
                    {
                        "id": "a",
                        "app": "uav_queue_project",
                        "produces": [{"id": "a_out", "path": "a.json"}],
                    },
                    {
                        "id": "b",
                        "app": "uav_relay_queue_project",
                        "consumes": [{"id": "a_out", "path": "a.json"}],
                    },
                ],
                "edges": [{"from": "a", "to": "b", "artifact": "a_out"}],
            }
        ),
        encoding="utf-8",
    )
    for app in ("uav_queue_project", "uav_relay_queue_project"):
        app_root = tmp_path / "src" / "agilab" / "apps" / "builtin" / app
        app_root.mkdir(parents=True)
        (app_root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "src" / "agilab" / "apps" / "builtin" / "uav_queue_project" / "pipeline_view.dot").write_text(
        'digraph demo { start [label="Start"]; finish [label="Finish"]; start -> finish; }\n',
        encoding="utf-8",
    )

    graph = module.build_global_pipeline_dag(repo_root=tmp_path, dag_path=dag_path)

    assert graph.ok is False
    assert {
        issue.message
        for issue in graph.issues
    } >= {"app 'uav_relay_queue_project' does not expose pipeline_view.dot"}


def test_global_pipeline_dag_core_handles_empty_local_views_and_bad_rows(tmp_path: Path) -> None:
    module = _load_core_module()
    issue = module._issue("where", "what")
    assert issue.as_dict() == {"level": "error", "location": "where", "message": "what"}
    assert module._node_rows({"nodes": "bad"}) == {}
    assert module._edge_rows({"edges": "bad"}) == ()

    app_root = tmp_path / "src" / "agilab" / "apps" / "builtin" / "demo_project"
    app_root.mkdir(parents=True)
    (app_root / "pipeline_view.dot").write_text("digraph empty { }\n", encoding="utf-8")

    view, issues = module._load_app_pipeline_view(
        repo_root=tmp_path,
        app="demo_project",
        dag_node="demo_node",
    )

    assert view is not None
    assert [item.location for item in issues] == ["pipeline_views.demo_node", "pipeline_views.demo_node"]
    assert {item.message for item in issues} == {
        "app 'demo_project' pipeline_view.dot has no labeled nodes",
        "app 'demo_project' pipeline_view.dot has no edges",
    }


def test_global_pipeline_dag_build_handles_relative_path_validation_issues_and_missing_order_rows(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_core_module()
    app_root = tmp_path / "src" / "agilab" / "apps" / "builtin" / "demo_project"
    app_root.mkdir(parents=True)
    (app_root / "pipeline_view.dot").write_text(
        'digraph demo { extract [label="Extract"]; train [label="Train"]; extract -> train; }\n',
        encoding="utf-8",
    )
    payload = {
        "nodes": [{"id": "present", "app": "demo_project", "purpose": "Demo"}],
        "edges": [],
    }

    monkeypatch.setattr(module, "load_multi_app_dag", lambda path: payload)
    monkeypatch.setattr(
        module,
        "validate_multi_app_dag",
        lambda _payload, *, repo_root: SimpleNamespace(
            issues=(SimpleNamespace(location="nodes[0]", message="synthetic validation issue"),),
            execution_order=("missing", "present"),
            artifact_handoffs=(),
        ),
    )

    graph = module.build_global_pipeline_dag(repo_root=tmp_path, dag_path=Path("dag.json"))

    assert graph.dag_path == "dag.json"
    assert any(issue.location == "multi_app_dag.nodes[0]" for issue in graph.issues)
    assert [node["id"] for node in graph.nodes if node["kind"] == "app"] == ["present"]
