from __future__ import annotations

import importlib.util
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


def _load_dag_execution_adapters():
    _ensure_agilab_package_path()
    module_path = Path("src/agilab/dag_execution_adapters.py")
    spec = importlib.util.spec_from_file_location("agilab.dag_execution_adapters", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["agilab.dag_execution_adapters"] = module
    spec.loader.exec_module(module)
    return module


dag_execution_adapters = _load_dag_execution_adapters()


def test_adapter_registry_exposes_uav_queue_to_relay_adapter():
    assert dag_execution_adapters.registered_execution_adapter_ids() == (
        "controlled_contract_dag",
        "uav_queue_to_relay_controlled",
    )


def test_adapter_dispatch_reports_unknown_adapter(tmp_path):
    result = dag_execution_adapters.run_next_adapter_stage(
        "missing-adapter",
        {"units": []},
        dag_execution_adapters.DagExecutionContext(repo_root=Path.cwd(), lab_dir=tmp_path),
    )

    assert not result.ok
    assert result.state == {"units": []}
    assert "No DAG execution adapter is registered" in result.message


def test_controlled_contract_adapter_executes_declared_contract_stages(tmp_path):
    state = {
        "created_at": "2026-05-07T00:00:00Z",
        "units": [
            {
                "id": "extract_context",
                "dispatch_status": "runnable",
                "execution_contract": {"entrypoint": "alpha.extract_context"},
                "produces": [
                    {
                        "artifact": "context_artifact",
                        "kind": "contract_artifact",
                        "path": "context/context.json",
                    }
                ],
            },
            {
                "id": "review_forecast",
                "dispatch_status": "blocked",
                "execution_contract": {"entrypoint": "beta.review_forecast"},
                "artifact_dependencies": [{"artifact": "context_artifact", "from": "extract_context"}],
                "produces": [
                    {
                        "artifact": "forecast_metrics",
                        "kind": "summary_metrics",
                        "path": "forecast/metrics.json",
                    }
                ],
            },
            {
                "id": "publish_report",
                "dispatch_status": "blocked",
                "execution_contract": {"entrypoint": "gamma.publish_report"},
                "artifact_dependencies": [{"artifact": "forecast_metrics", "from": "review_forecast"}],
                "produces": [
                    {
                        "artifact": "report_summary",
                        "kind": "summary_metrics",
                        "path": "report/summary.json",
                    }
                ],
            },
        ],
        "artifacts": [],
        "events": [],
        "summary": {},
        "provenance": {"real_app_execution": False},
    }
    context = dag_execution_adapters.DagExecutionContext(
        repo_root=Path.cwd(),
        lab_dir=tmp_path,
        now_fn=lambda: "2026-05-07T00:00:00Z",
    )

    first = dag_execution_adapters.run_next_adapter_stage("controlled_contract_dag", state, context)
    second = dag_execution_adapters.run_next_adapter_stage("controlled_contract_dag", first.state, context)
    third = dag_execution_adapters.run_next_adapter_stage("controlled_contract_dag", second.state, context)

    assert first.ok
    assert first.executed_unit_id == "extract_context"
    assert first.state["summary"]["available_artifact_ids"] == ["context_artifact"]
    assert first.state["summary"]["controlled_executed_unit_ids"] == ["extract_context"]
    assert first.state["provenance"]["real_app_execution"] is False
    assert first.state["provenance"]["controlled_execution"] is True
    assert first.state["units"][0]["execution_mode"] == "contract_adapter"
    assert first.state["units"][1]["dispatch_status"] == "runnable"
    context_artifact = tmp_path / ".agilab" / "global_dag_real_runs" / "extract_context" / "context" / "context.json"
    assert context_artifact.is_file()
    assert second.ok
    assert second.executed_unit_id == "review_forecast"
    assert second.state["summary"]["available_artifact_ids"] == [
        "context_artifact",
        "forecast_metrics",
    ]
    assert second.state["units"][2]["dispatch_status"] == "runnable"
    assert third.ok
    assert third.executed_unit_id == "publish_report"
    assert third.state["run_status"] == "completed"
    assert third.state["summary"]["available_artifact_ids"] == [
        "context_artifact",
        "forecast_metrics",
        "report_summary",
    ]


def test_controlled_contract_adapter_uses_entrypoint_runner(tmp_path):
    calls: list[Path] = []

    def _runner(*, repo_root: Path, run_root: Path) -> dict[str, object]:
        calls.append(run_root)
        return {
            "summary_metrics_path": "alpha/summary.json",
            "summary_metrics": {"stage_completed": 1, "custom_runner": 1},
        }

    state = {
        "created_at": "2026-05-07T00:00:00Z",
        "units": [
            {
                "id": "extract_context",
                "dispatch_status": "runnable",
                "execution_contract": {"entrypoint": "alpha.extract_context"},
                "produces": [
                    {
                        "artifact": "context_artifact",
                        "kind": "summary_metrics",
                        "path": "context/context.json",
                    }
                ],
            }
        ],
        "artifacts": [],
        "events": [],
        "summary": {},
        "provenance": {"real_app_execution": False},
    }
    context = dag_execution_adapters.DagExecutionContext(
        repo_root=Path.cwd(),
        lab_dir=tmp_path,
        stage_run_fns={"alpha.extract_context": _runner},
        now_fn=lambda: "2026-05-07T00:00:00Z",
    )

    result = dag_execution_adapters.run_next_adapter_stage("controlled_contract_dag", state, context)

    assert result.ok
    assert calls == [tmp_path / ".agilab" / "global_dag_real_runs" / "extract_context"]
    unit = result.state["units"][0]
    assert unit["contract_execution"]["summary_metrics"]["custom_runner"] == 1


def test_controlled_contract_adapter_runs_declared_command(tmp_path):
    state = {
        "created_at": "2026-05-07T00:00:00Z",
        "units": [
            {
                "id": "extract_context",
                "dispatch_status": "runnable",
                "execution_contract": {
                    "command": [
                        sys.executable,
                        "-c",
                        "from pathlib import Path; "
                        "Path('context').mkdir(); "
                        "Path('context/context.json').write_text('{\"ok\": true}\\n')",
                    ]
                },
                "produces": [
                    {
                        "artifact": "context_artifact",
                        "kind": "contract_artifact",
                        "path": "context/context.json",
                    }
                ],
            }
        ],
        "artifacts": [],
        "events": [],
        "summary": {},
        "provenance": {"real_app_execution": False},
    }
    context = dag_execution_adapters.DagExecutionContext(
        repo_root=Path.cwd(),
        lab_dir=tmp_path,
        now_fn=lambda: "2026-05-07T00:00:00Z",
    )

    result = dag_execution_adapters.run_next_adapter_stage("controlled_contract_dag", state, context)

    assert result.ok
    artifact_path = tmp_path / ".agilab" / "global_dag_real_runs" / "extract_context" / "context" / "context.json"
    assert artifact_path.read_text(encoding="utf-8") == '{"ok": true}\n'
    assert result.state["units"][0]["contract_execution"]["command_returncode"] == 0


def test_controlled_contract_adapter_rejects_stage_without_execution_contract(tmp_path):
    state = {
        "units": [
            {
                "id": "extract_context",
                "dispatch_status": "runnable",
                "produces": [{"artifact": "context_artifact", "path": "context/context.json"}],
            }
        ],
        "artifacts": [],
        "events": [],
        "summary": {},
    }

    result = dag_execution_adapters.run_next_adapter_stage(
        "controlled_contract_dag",
        state,
        dag_execution_adapters.DagExecutionContext(repo_root=Path.cwd(), lab_dir=tmp_path),
    )

    assert not result.ok
    assert "must declare `execution.entrypoint` or `execution.command`" in result.message
