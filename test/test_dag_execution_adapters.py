from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
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


@pytest.mark.parametrize("stage", ["queue", "relay"])
@pytest.mark.parametrize("missing_output", ["summary", "reduce"])
def test_specialized_uav_callback_cannot_complete_without_both_output_files(
    tmp_path, stage, missing_output
):
    queue_path = tmp_path / "queue-input.json"
    queue_path.write_text("{}")
    state = {
        "units": [
            {
                "id": "queue_baseline",
                "dispatch_status": "runnable" if stage == "queue" else "completed",
            },
            {
                "id": "relay_followup",
                "dispatch_status": "blocked" if stage == "queue" else "runnable",
            },
        ],
        "artifacts": []
        if stage == "queue"
        else [
            {
                "artifact": "queue_metrics",
                "kind": "summary_metrics",
                "producer": "queue_baseline",
                "status": "available",
                "path": str(queue_path),
            }
        ],
    }

    def callback(*, run_root, **kwargs):
        run_root.mkdir(parents=True, exist_ok=True)
        for name in ("summary", "reduce"):
            if name != missing_output:
                (run_root / f"{name}.json").write_text("{}")
        return {
            "summary_metrics_path": "summary.json",
            "reduce_artifact_path": "reduce.json",
        }

    result = dag_execution_adapters._run_next_adapter_stage_uncommitted(
        "uav_queue_to_relay_controlled",
        state,
        dag_execution_adapters.DagExecutionContext(
            repo_root=Path.cwd(),
            lab_dir=tmp_path,
            run_queue_fn=callback,
            run_relay_fn=callback,
            execution_attempt_id="specialized-output-check",
            persist_execution_claim_fn=lambda state: dag_execution_adapters._DURABLE_CLAIM_RECEIPT,
        ),
    )
    assert not result.ok
    assert result.state["run_status"] == "failed"
    failed_id = "queue_baseline" if stage == "queue" else "relay_followup"
    assert (
        next(unit for unit in result.state["units"] if unit["id"] == failed_id)[
            "dispatch_status"
        ]
        == "failed"
    )
    assert not any(
        artifact["producer"] == failed_id
        for artifact in result.state.get("artifacts", [])
    )


@pytest.mark.parametrize("stage", ["queue", "relay"])
def test_specialized_uav_callback_publishes_only_materialized_output_paths(
    tmp_path, stage
):
    queue_path = tmp_path / "queue-input.json"
    queue_path.write_text("{}")
    state = {
        "units": [
            {
                "id": "queue_baseline",
                "dispatch_status": "runnable" if stage == "queue" else "completed",
            },
            {
                "id": "relay_followup",
                "dispatch_status": "blocked" if stage == "queue" else "runnable",
            },
        ],
        "artifacts": []
        if stage == "queue"
        else [
            {
                "artifact": "queue_metrics",
                "kind": "summary_metrics",
                "producer": "queue_baseline",
                "status": "available",
                "path": str(queue_path),
            }
        ],
    }

    def callback(*, run_root, **kwargs):
        run_root.mkdir(parents=True, exist_ok=True)
        for name in ("summary", "reduce"):
            (run_root / f"{name}.json").write_text("{}")
        return {
            "summary_metrics_path": "summary.json",
            "reduce_artifact_path": "reduce.json",
        }

    result = dag_execution_adapters._run_next_adapter_stage_uncommitted(
        "uav_queue_to_relay_controlled",
        state,
        dag_execution_adapters.DagExecutionContext(
            repo_root=Path.cwd(),
            lab_dir=tmp_path,
            run_queue_fn=callback,
            run_relay_fn=callback,
            execution_attempt_id="specialized-real-output-check",
            persist_execution_claim_fn=lambda state: dag_execution_adapters._DURABLE_CLAIM_RECEIPT,
        ),
    )
    assert result.ok
    expected_producer = "queue_baseline" if stage == "queue" else "relay_followup"
    outputs = [
        artifact
        for artifact in result.state["artifacts"]
        if artifact["producer"] == expected_producer
    ]
    assert len(outputs) == 2
    assert all(
        Path(output["path"]).is_absolute() and Path(output["path"]).is_file()
        for output in outputs
    )
    if stage == "relay":
        assert result.state["run_status"] == "completed"


@pytest.mark.parametrize("stage", ["queue", "relay"])
def test_specialized_uav_noop_cannot_complete_using_previous_attempt_outputs(
    tmp_path, stage
):
    queue_path = tmp_path / "queue-input.json"
    queue_path.write_text("{}")
    unit_id = "queue_baseline" if stage == "queue" else "relay_followup"
    run_root = tmp_path / ".agilab/multi_app_dag_real_runs" / unit_id
    run_root.mkdir(parents=True)
    for name in ("summary", "reduce"):
        (run_root / f"{name}.json").write_text("{}")
    state = {
        "units": [
            {
                "id": "queue_baseline",
                "dispatch_status": "runnable" if stage == "queue" else "completed",
            },
            {
                "id": "relay_followup",
                "dispatch_status": "blocked" if stage == "queue" else "runnable",
            },
        ],
        "artifacts": []
        if stage == "queue"
        else [
            {
                "artifact": "queue_metrics",
                "kind": "summary_metrics",
                "producer": "queue_baseline",
                "status": "available",
                "path": str(queue_path),
            }
        ],
    }
    calls = []

    def callback(**kwargs):
        calls.append(kwargs["idempotency_token"])
        return {
            "summary_metrics_path": "summary.json",
            "reduce_artifact_path": "reduce.json",
        }

    context = dag_execution_adapters.DagExecutionContext(
        repo_root=Path.cwd(),
        lab_dir=tmp_path,
        run_queue_fn=callback,
        run_relay_fn=callback,
        execution_attempt_id="new-specialized-attempt",
        persist_execution_claim_fn=lambda state: dag_execution_adapters._DURABLE_CLAIM_RECEIPT,
    )
    for _ in range(2):
        result = dag_execution_adapters._run_next_adapter_stage_uncommitted(
            "uav_queue_to_relay_controlled", state, context
        )
        assert not result.ok and "freshly produce" in result.message
        assert result.state["run_status"] == "failed"
    assert len(calls) == 1


def test_target_preview_rechecks_available_inputs_without_mutating_state(tmp_path):
    input_path = tmp_path / "input.csv"
    input_path.write_text("actual input")
    state = {
        "units": [
            {
                "id": "newly_ready",
                "dispatch_status": "blocked",
                "artifact_dependencies": [{"artifact": "input"}],
            },
            {"id": "already_ready", "dispatch_status": "runnable"},
            {
                "id": "waiting",
                "dispatch_status": "blocked",
                "artifact_dependencies": [{"artifact": "absent"}],
            },
            {"id": "failed", "dispatch_status": "failed", "artifact_dependencies": []},
        ],
        "artifacts": [
            {
                "artifact": "input",
                "status": "available",
                "kind": "dataset",
                "path": str(input_path),
            }
        ],
        "events": [],
        "summary": {"runnable_unit_ids": ["already_ready"]},
    }
    original = json.dumps(state, sort_keys=True)
    assert dag_execution_adapters.planned_stage_ids("controlled_contract_dag", state) == ("newly_ready",)
    assert dag_execution_adapters.planned_stage_ids("controlled_contract_dag", state, batch=True) == ("newly_ready", "already_ready")
    assert json.dumps(state, sort_keys=True) == original
    with pytest.raises(ValueError, match="No execution target preview"):
        dag_execution_adapters.planned_stage_ids("unknown", state)


def test_uav_target_preview_preserves_adapter_order_and_single_stage_batch(tmp_path):
    metrics_path = tmp_path / "queue-metrics.json"
    metrics_path.write_text("{}")
    state = {
        "units": [
            {"id": "relay_followup", "dispatch_status": "runnable"},
            {"id": "queue_baseline", "dispatch_status": "runnable"},
        ],
        "artifacts": [
            {
                "artifact": "queue_metrics",
                "producer": "queue_baseline",
                "status": "available",
                "kind": "summary_metrics",
                "path": str(metrics_path),
            }
        ],
    }
    assert dag_execution_adapters.planned_stage_ids("uav_queue_to_relay_controlled", state) == ("queue_baseline",)
    assert dag_execution_adapters.planned_stage_ids("uav_queue_to_relay_controlled", state, batch=True) == ("queue_baseline",)
    state["units"][1]["dispatch_status"] = "completed"
    assert dag_execution_adapters.planned_stage_ids("uav_queue_to_relay_controlled", state) == ("relay_followup",)
    state["artifacts"] = []
    assert dag_execution_adapters.planned_stage_ids("uav_queue_to_relay_controlled", state) == ()


def test_adapter_dispatch_reports_unknown_adapter(tmp_path):
    result = dag_execution_adapters._run_next_adapter_stage_uncommitted(
        "missing-adapter",
        {"units": []},
        dag_execution_adapters.DagExecutionContext(repo_root=Path.cwd(), lab_dir=tmp_path),
    )

    assert not result.ok
    assert result.state == {"units": []}
    assert "No DAG execution adapter is registered" in result.message


def test_ready_adapter_dispatch_reports_unknown_adapter(tmp_path):
    result = dag_execution_adapters._run_ready_adapter_stages_uncommitted(
        "missing-adapter",
        {"units": []},
        dag_execution_adapters.DagExecutionContext(repo_root=Path.cwd(), lab_dir=tmp_path),
    )

    assert not result.ok
    assert "No DAG execution adapter is registered" in result.message


def test_public_adapter_entrypoints_cannot_accept_a_forged_claim_receipt(tmp_path):
    callback_count = 0

    def _unexpected_callback(**_kwargs):
        nonlocal callback_count
        callback_count += 1
        return {}

    context = dag_execution_adapters.DagExecutionContext(
        repo_root=Path.cwd(),
        lab_dir=tmp_path,
        run_queue_fn=_unexpected_callback,
        execution_attempt_id="forged-receipt",
        persist_execution_claim_fn=lambda _state: (
            dag_execution_adapters._DURABLE_CLAIM_RECEIPT
        ),
    )
    with pytest.raises(RuntimeError, match="Direct DAG adapter execution is disabled"):
        dag_execution_adapters.run_next_adapter_stage(
            "uav_queue_to_relay_controlled",
            {"units": []},
            context,
        )
    with pytest.raises(RuntimeError, match="Direct DAG adapter batch execution is disabled"):
        dag_execution_adapters.run_ready_adapter_stages(
            "controlled_contract_dag",
            {"units": []},
            context,
        )
    assert not hasattr(dag_execution_adapters, "UavQueueToRelayExecutionAdapter")
    assert not hasattr(dag_execution_adapters, "ControlledContractDagExecutionAdapter")
    assert not hasattr(dag_execution_adapters, "DAG_EXECUTION_ADAPTERS_BY_ID")
    for adapter in dag_execution_adapters._DAG_EXECUTION_ADAPTERS_BY_ID.values():
        assert not hasattr(adapter, "run_next")

    assert callback_count == 0


def test_controlled_contract_adapter_records_declared_receipt_contracts(tmp_path):
    state = {
        "created_at": "2026-05-07T00:00:00Z",
        "units": [
            {
                "id": "extract_context",
                "dispatch_status": "runnable",
                "execution_contract": {
                    "entrypoint": "alpha.extract_context",
                    "params": {"scenario": "demo"},
                    "stages": [{"name": "prepare", "args": {"n": 2}}],
                    "data_in": "alpha/input",
                    "data_out": "alpha/output",
                    "reset_target": False,
                },
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
                "artifact_dependencies": [
                    {"artifact": "context_artifact", "from": "extract_context"}
                ],
                "produces": [
                    {
                        "artifact": "forecast_metrics",
                        "kind": "contract_artifact",
                        "path": "forecast/metrics.json",
                    }
                ],
            },
            {
                "id": "publish_report",
                "dispatch_status": "blocked",
                "execution_contract": {"entrypoint": "gamma.publish_report"},
                "artifact_dependencies": [
                    {"artifact": "forecast_metrics", "from": "review_forecast"}
                ],
                "produces": [
                    {
                        "artifact": "report_summary",
                        "kind": "contract_artifact",
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
        execution_attempt_id="contract-sequence",
        persist_execution_claim_fn=lambda _state: dag_execution_adapters._DURABLE_CLAIM_RECEIPT,
    )

    first_targets = dag_execution_adapters.planned_stage_ids("controlled_contract_dag", state)
    first = dag_execution_adapters._run_next_adapter_stage_uncommitted(
        "controlled_contract_dag", state, context
    )
    assert first_targets == (first.executed_unit_id,)
    second_targets = dag_execution_adapters.planned_stage_ids("controlled_contract_dag", first.state)
    second = dag_execution_adapters._run_next_adapter_stage_uncommitted(
        "controlled_contract_dag", first.state, context
    )
    assert second_targets == (second.executed_unit_id,)
    third = dag_execution_adapters._run_next_adapter_stage_uncommitted(
        "controlled_contract_dag", second.state, context
    )

    assert first.ok
    assert first.executed_unit_id == "extract_context"
    assert first.state["summary"]["available_artifact_ids"] == ["context_artifact"]
    assert first.state["summary"]["controlled_executed_unit_ids"] == ["extract_context"]
    assert first.state["provenance"]["real_app_execution"] is False
    assert first.state["provenance"]["controlled_execution"] is True
    assert first.state["units"][0]["execution_mode"] == "contract_adapter"
    assert first.state["units"][1]["dispatch_status"] == "runnable"
    context_artifact = tmp_path / ".agilab" / "multi_app_dag_real_runs" / "extract_context" / "context" / "context.json"
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

    def _runner(
        *,
        repo_root: Path,
        run_root: Path,
        idempotency_token: str,
    ) -> dict[str, object]:
        assert idempotency_token == "custom-runner:extract_context"
        calls.append(run_root)
        output_path = run_root / "alpha/summary.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text('{"stage_completed": 1}\n', encoding="utf-8")
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
                "execution_contract": {
                    "entrypoint": "alpha.extract_context",
                    "params": {"scenario": "demo"},
                    "stages": [{"name": "prepare", "args": {"n": 2}}],
                    "data_in": "alpha/input",
                    "data_out": "alpha/output",
                    "reset_target": False,
                },
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
        execution_attempt_id="custom-runner",
        persist_execution_claim_fn=lambda _state: dag_execution_adapters._DURABLE_CLAIM_RECEIPT,
    )

    result = dag_execution_adapters._run_next_adapter_stage_uncommitted(
        "controlled_contract_dag", state, context
    )

    assert result.ok
    assert calls == [tmp_path / ".agilab" / "multi_app_dag_real_runs" / "extract_context"]
    unit = result.state["units"][0]
    assert unit["contract_execution"]["summary_metrics"]["custom_runner"] == 1
    assert unit["contract_execution"]["execution_contract"]["params"] == {"scenario": "demo"}
    assert unit["contract_execution"]["execution_contract"]["stages"] == [
        {"name": "prepare", "args": {"n": 2}}
    ]
    assert unit["contract_execution"]["execution_contract"]["data_in"] == "alpha/input"


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
        execution_attempt_id="command-runner",
        persist_execution_claim_fn=lambda _state: dag_execution_adapters._DURABLE_CLAIM_RECEIPT,
    )

    result = dag_execution_adapters._run_next_adapter_stage_uncommitted(
        "controlled_contract_dag", state, context
    )

    assert result.ok
    artifact_path = tmp_path / ".agilab" / "multi_app_dag_real_runs" / "extract_context" / "context" / "context.json"
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

    result = dag_execution_adapters._run_next_adapter_stage_uncommitted(
        "controlled_contract_dag",
        state,
        dag_execution_adapters.DagExecutionContext(repo_root=Path.cwd(), lab_dir=tmp_path),
    )

    assert not result.ok
    assert "must declare `execution.entrypoint` or `execution.command`" in result.message


def test_uav_queue_adapter_reports_missing_required_stages(tmp_path):
    result = dag_execution_adapters._run_next_adapter_stage_uncommitted(
        "uav_queue_to_relay_controlled",
        {"units": [{"id": "queue_baseline", "dispatch_status": "runnable"}]},
        dag_execution_adapters.DagExecutionContext(repo_root=Path.cwd(), lab_dir=tmp_path),
    )

    assert not result.ok
    assert "missing the expected queue or relay stage" in result.message


def test_uav_queue_adapter_runs_blocked_relay_from_available_artifact(tmp_path):
    relay_calls: list[dict[str, object]] = []
    metrics_path = tmp_path / "queue/from-artifact.json"
    metrics_path.parent.mkdir()
    metrics_path.write_text("{}")
    state = {
        "created_at": "2026-05-07T00:00:00Z",
        "units": [
            {"id": "queue_baseline", "dispatch_status": "completed"},
            {"id": "relay_followup", "dispatch_status": "blocked"},
        ],
        "artifacts": [
            {
                "artifact": "queue_metrics",
                "path": str(metrics_path),
                "kind": "summary_metrics",
                "producer": "queue_baseline",
                "status": "available",
            }
        ],
        "events": [],
        "summary": {},
        "provenance": {},
    }

    def _relay_run(
        *,
        repo_root: Path,
        run_root: Path,
        queue_result: dict[str, object],
        idempotency_token: str,
    ) -> dict[str, object]:
        assert idempotency_token == "relay-run:relay_followup"
        relay_calls.append({"run_root": run_root, "queue_result": queue_result})
        for name in ("summary", "reduce"):
            path = run_root / f"relay/{name}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}")
        return {
            "summary_metrics_path": "relay/summary.json",
            "reduce_artifact_path": "relay/reduce.json",
            "summary_metrics": {"packets_generated": 2, "packets_delivered": 2},
        }

    result = dag_execution_adapters._run_next_adapter_stage_uncommitted(
        "uav_queue_to_relay_controlled",
        state,
        dag_execution_adapters.DagExecutionContext(
            repo_root=Path.cwd(),
            lab_dir=tmp_path,
            run_relay_fn=_relay_run,
            now_fn=lambda: "2026-05-07T00:00:00Z",
            execution_attempt_id="relay-run",
            persist_execution_claim_fn=lambda _state: dag_execution_adapters._DURABLE_CLAIM_RECEIPT,
        ),
    )

    assert result.ok
    assert result.executed_unit_id == "relay_followup"
    assert relay_calls == [
        {
            "run_root": tmp_path
            / ".agilab"
            / "multi_app_dag_real_runs"
            / "relay_followup",
            "queue_result": {"summary_metrics_path": str(metrics_path)},
        }
    ]
    assert result.state["run_status"] == "completed"
    assert result.state["summary"]["real_executed_unit_ids"] == ["relay_followup"]


def test_uav_queue_adapter_reports_no_ready_stage(tmp_path):
    state = {
        "units": [
            {"id": "queue_baseline", "dispatch_status": "completed"},
            {"id": "relay_followup", "dispatch_status": "blocked"},
        ],
        "artifacts": [],
        "events": [],
        "summary": {},
    }

    result = dag_execution_adapters._run_next_adapter_stage_uncommitted(
        "uav_queue_to_relay_controlled",
        state,
        dag_execution_adapters.DagExecutionContext(repo_root=Path.cwd(), lab_dir=tmp_path),
    )

    assert not result.ok
    assert result.message == "No controlled real DAG stage is ready to run."
    assert result.state["summary"]["blocked_unit_ids"] == ["relay_followup"]


def test_controlled_contract_adapter_reports_no_ready_stage(tmp_path):
    state = {
        "units": [
            {
                "id": "extract_context",
                "dispatch_status": "completed",
                "execution_contract": {"entrypoint": "alpha.extract_context"},
                "produces": [{"artifact": "context_artifact", "path": "context/context.json"}],
            }
        ],
        "artifacts": [],
        "events": [],
        "summary": {},
    }

    result = dag_execution_adapters._run_next_adapter_stage_uncommitted(
        "controlled_contract_dag",
        state,
        dag_execution_adapters.DagExecutionContext(repo_root=Path.cwd(), lab_dir=tmp_path),
    )

    assert not result.ok
    assert result.message == "No controlled contract DAG stage is ready to run."
    assert result.state["run_status"] == "completed"


def test_controlled_contract_command_failure_requires_exact_token_recovery(tmp_path):
    state = {
        "created_at": "2026-05-07T00:00:00Z",
        "units": [
            {
                "id": "extract_context",
                "dispatch_status": "runnable",
                "execution_contract": {
                    "command": f"{sys.executable} -c \"import sys; print('bad command'); sys.exit(3)\""
                },
                "produces": [{"artifact": "context_artifact", "path": "context/context.json"}],
            }
        ],
        "artifacts": [],
        "events": [],
        "summary": {},
    }

    with pytest.raises(
        dag_execution_adapters.DagExternalExecutionUncertainError,
        match=r"Controlled contract command failed \(3\): bad command",
    ):
        dag_execution_adapters._run_next_adapter_stage_uncommitted(
            "controlled_contract_dag",
            state,
            dag_execution_adapters.DagExecutionContext(
                repo_root=Path.cwd(),
                lab_dir=tmp_path,
                now_fn=lambda: "2026-05-07T00:00:00Z",
                execution_attempt_id="command-failure",
                persist_execution_claim_fn=lambda _state: (
                    dag_execution_adapters._DURABLE_CLAIM_RECEIPT
                ),
            ),
        )


def test_controlled_contract_adapter_uses_unit_id_runner_before_entrypoint_runner(tmp_path):
    calls: list[str] = []

    def _unit_runner(
        *,
        repo_root: Path,
        run_root: Path,
        idempotency_token: str,
    ) -> dict[str, object]:
        del repo_root, idempotency_token
        calls.append("unit")
        output_path = run_root / "unit/summary.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text('{"runner": "unit"}\n', encoding="utf-8")
        return {
            "summary_metrics_path": "unit/summary.json",
            "summary_metrics": {"stage_completed": 1, "runner": "unit"},
        }

    def _entrypoint_runner(
        *,
        repo_root: Path,
        run_root: Path,
        idempotency_token: str,
    ) -> dict[str, object]:
        del repo_root, run_root, idempotency_token
        calls.append("entrypoint")
        return {
            "summary_metrics_path": "entrypoint/summary.json",
            "summary_metrics": {"stage_completed": 1, "runner": "entrypoint"},
        }

    state = {
        "created_at": "2026-05-07T00:00:00Z",
        "units": [
            {
                "id": "extract_context",
                "dispatch_status": "runnable",
                "execution_contract": {"entrypoint": "alpha.extract_context"},
                "produces": [{"artifact": "context_artifact", "kind": "summary_metrics", "path": "context.json"}],
            }
        ],
        "artifacts": [],
        "events": [],
        "summary": {},
    }

    result = dag_execution_adapters._run_next_adapter_stage_uncommitted(
        "controlled_contract_dag",
        state,
        dag_execution_adapters.DagExecutionContext(
            repo_root=Path.cwd(),
            lab_dir=tmp_path,
            stage_run_fns={
                "extract_context": _unit_runner,
                "alpha.extract_context": _entrypoint_runner,
            },
            now_fn=lambda: "2026-05-07T00:00:00Z",
            execution_attempt_id="runner-priority",
            persist_execution_claim_fn=lambda _state: dag_execution_adapters._DURABLE_CLAIM_RECEIPT,
        ),
    )

    assert result.ok
    assert calls == ["unit"]
    assert result.state["units"][0]["contract_execution"]["summary_metrics"]["runner"] == "unit"


def test_controlled_contract_adapter_sanitizes_unsafe_artifact_path(tmp_path):
    state = {
        "created_at": "2026-05-07T00:00:00Z",
        "units": [
            {
                "id": "extract/context",
                "dispatch_status": "runnable",
                "execution_contract": {"entrypoint": "alpha.extract_context"},
                "produces": [{"artifact": "context_artifact", "kind": "contract_artifact", "path": "../escape.json"}],
            }
        ],
        "artifacts": [],
        "events": [],
        "summary": {},
    }

    result = dag_execution_adapters._run_next_adapter_stage_uncommitted(
        "controlled_contract_dag",
        state,
        dag_execution_adapters.DagExecutionContext(
            repo_root=Path.cwd(),
            lab_dir=tmp_path,
            now_fn=lambda: "2026-05-07T00:00:00Z",
            execution_attempt_id="unsafe-path",
            persist_execution_claim_fn=lambda _state: dag_execution_adapters._DURABLE_CLAIM_RECEIPT,
        ),
    )

    expected_path = tmp_path / ".agilab" / "multi_app_dag_real_runs" / "extract-context" / "context_artifact.json"
    assert result.ok
    assert expected_path.is_file()
    assert result.state["units"][0]["produces"][0]["path"] == str(expected_path)
    assert not (tmp_path / ".agilab" / "multi_app_dag_real_runs" / "escape.json").exists()


def test_adapter_helpers_tolerate_nonstandard_state_shapes():
    assert dag_execution_adapters.dag_units({"units": "not-a-list"}) == []
    assert dag_execution_adapters.available_artifact_ids({"artifacts": "not-a-list"}) == set()
    assert dag_execution_adapters._failed_stage_text([], {}) == "no stage"


def test_contract_artifact_inference_and_contract_normalization_edges():
    state = {
        "units": [
            {
                "id": "source",
                "produces": ["bad", {"artifact": "", "path": ""}],
            },
            {
                "id": "downstream",
                "artifact_dependencies": [
                    "bad",
                    {"from": "other", "artifact": "ignored"},
                    {"from": "source", "artifact": ""},
                    {"from": "source", "artifact": "source_metrics", "source_path": "source/metrics.json"},
                ],
            },
        ]
    }

    assert dag_execution_adapters._primary_contract_artifact(state, state["units"][0]) == {
        "artifact": "source_metrics",
        "kind": "summary_metrics",
        "path": "source/metrics.json",
    }
    assert dag_execution_adapters._primary_contract_artifact({"units": []}, {"id": "fallback"}) == {
        "artifact": "fallback_contract_artifact",
        "kind": "contract_artifact",
        "path": "",
    }
    assert dag_execution_adapters._contract_artifact_kind("queue_reduce_summary", "") == "reduce_summary"
    assert dag_execution_adapters._contract_artifact_kind("queue_metrics", "") == "summary_metrics"
    assert dag_execution_adapters._contract_artifact_path(Path("/tmp/run"), artifact_id="artifact", declared_path="/abs/x") == (
        Path("/tmp/run") / "artifact.json"
    )
    assert dag_execution_adapters._contract_command({"command": "python -m demo --flag"}) == [
        "python",
        "-m",
        "demo",
        "--flag",
    ]
    assert dag_execution_adapters._unit_execution_contract(
        {
            "execution_contract": {
                "entrypoint": "demo.run",
                "run_params": {"x": 1},
                "rapids_enabled": 1,
                "benchmark_best_single_node": "",
            }
        }
    ) == {
        "entrypoint": "demo.run",
        "params": {"x": 1},
        "rapids_enabled": True,
        "benchmark_best_single_node": False,
    }
    with pytest.raises(ValueError, match="legacy 'steps'"):
        dag_execution_adapters._unit_execution_contract({"execution_contract": {"entrypoint": "x", "steps": []}})
    assert dag_execution_adapters._has_declared_contract_artifact("bad") is False
    assert dag_execution_adapters._controlled_contract_unit_issue({"id": "", "produces": []}).startswith(
        "Controlled contract stage `stage`"
    )


def test_run_ready_contract_batch_marks_invalid_runnable_stage_failure(tmp_path):
    state = {
        "units": [
            {
                "id": "bad_stage",
                "dispatch_status": "runnable",
                "execution_contract": {"entrypoint": "demo.run"},
                "produces": [],
            }
        ],
        "events": [],
        "artifacts": [],
    }

    result = dag_execution_adapters._run_ready_adapter_stages_uncommitted(
        "controlled_contract_dag",
        state,
        dag_execution_adapters.DagExecutionContext(
            repo_root=Path.cwd(),
            lab_dir=tmp_path,
            now_fn=lambda: "2026-05-17T00:00:00Z",
        ),
    )

    assert not result.ok
    assert result.failed_unit_ids == ("bad_stage",)
    assert result.state["units"][0]["dispatch_status"] == "failed"
    assert "must declare at least one produced artifact" in result.message


def test_run_contract_command_timeout_and_state_mutation_edges(monkeypatch, tmp_path):
    def _raise_timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=["demo"], timeout=300)

    monkeypatch.setattr(dag_execution_adapters.subprocess, "run", _raise_timeout)
    with pytest.raises(RuntimeError, match="timed out"):
        dag_execution_adapters._run_contract_command(
            ["demo"],
            run_root=tmp_path,
            idempotency_token="timeout:demo",
        )

    state = {"events": "bad", "artifacts": "bad", "created_at": "created"}
    events = dag_execution_adapters._events(state)
    assert events == []
    dag_execution_adapters._replace_artifact(state, {"artifact": ""})
    assert state["artifacts"] == "bad"
    dag_execution_adapters._replace_artifact(state, {"artifact": "alpha", "status": "available"})
    assert state["artifacts"] == [{"artifact": "alpha", "status": "available"}]

    unit = {
        "id": "alpha",
        "dispatch_status": "running",
        "timestamps": [],
        "produces": [
            "bad",
            {"artifact": "other", "path": "old.json"},
        ],
    }
    dag_execution_adapters._mark_controlled_stage_execution(
        state,
        unit,
        result={"summary_metrics": "bad", "summary_metrics_path": "alpha/summary.json"},
        timestamp="2026-05-17T00:00:00Z",
        artifact_id="alpha_metrics",
        reduce_artifact_id=None,
    )
    assert unit["produces"][-1]["artifact"] == "alpha_metrics"
    assert unit["produces"][0]["artifact"] == "other"


def test_relay_queue_result_and_provenance_edge_paths():
    state = {"units": [{"id": "relay_followup", "dispatch_status": "runnable"}], "artifacts": []}
    dag_execution_adapters._unblock_relay_after_queue(state, timestamp="now")
    assert state["units"][0]["dispatch_status"] == "runnable"
    assert dag_execution_adapters._queue_result_for_relay({"units": [], "artifacts": []}) == {}

    provenance_state = {
        "provenance": {
            "real_executed_unit_ids": "bad",
            "controlled_executed_unit_ids": "bad",
        }
    }
    dag_execution_adapters._update_real_execution_provenance(
        provenance_state,
        executed_unit_id="alpha",
        timestamp="2026-05-17T00:00:00Z",
    )
    assert provenance_state["provenance"]["real_executed_unit_ids"] == ["alpha"]
    assert provenance_state["provenance"]["controlled_executed_unit_ids"] == ["alpha"]


def test_idempotency_ledger_reuses_completed_result_without_repeating_callback(tmp_path):
    callback_count = 0

    def _callback() -> dict[str, object]:
        nonlocal callback_count
        callback_count += 1
        return {"summary_metrics": {"stage_completed": 1}}

    first = dag_execution_adapters._execute_idempotently(
        run_root=tmp_path / "run",
        unit_id="queue_context",
        idempotency_token="duplicate-attempt:queue_context",
        callback=_callback,
    )
    second = dag_execution_adapters._execute_idempotently(
        run_root=tmp_path / "run",
        unit_id="queue_context",
        idempotency_token="duplicate-attempt:queue_context",
        callback=_callback,
    )

    assert callback_count == 1
    assert first == second
    assert second["idempotency_token"] == "duplicate-attempt:queue_context"


def test_idempotency_ledger_hierarchy_failure_aborts_before_callback(monkeypatch, tmp_path):
    callback_count = 0

    def _callback() -> dict[str, object]:
        nonlocal callback_count
        callback_count += 1
        return {}

    idempotency_module = sys.modules[
        dag_execution_adapters._execute_idempotently.__module__
    ]
    monkeypatch.setattr(
        idempotency_module,
        "_ensure_directory_hierarchy_durable",
        lambda _path: False,
    )

    with pytest.raises(OSError, match="ledger directory"):
        dag_execution_adapters._execute_idempotently(
            run_root=tmp_path / "new" / "run",
            unit_id="queue_context",
            idempotency_token="non-durable:queue_context",
            callback=_callback,
        )

    assert callback_count == 0


@pytest.mark.parametrize("with_command", [False, True])
def test_fallback_contract_artifact_is_replaced_with_retry_token(tmp_path, with_command):
    context = dag_execution_adapters.DagExecutionContext(
        repo_root=Path.cwd(),
        lab_dir=tmp_path,
    )
    artifact = {
        "artifact": "context_artifact",
        "kind": "contract_artifact",
        "path": "context/context.json",
    }

    def _unit(token: str) -> dict[str, object]:
        contract: dict[str, object] = {"entrypoint": "alpha.extract_context"}
        if with_command:
            contract["command"] = [sys.executable, "-c", "pass"]
        return {
            "id": "extract_context",
            "execution_contract": contract,
            "execution_attempt": {"idempotency_token": token},
        }

    first = dag_execution_adapters._contract_stage_result(
        context,
        unit=_unit("attempt-one:extract_context"),
        artifact=artifact,
        timestamp="2026-05-07T00:00:00Z",
    )
    output_path = Path(first["contract_artifact_path"])
    assert json.loads(output_path.read_text(encoding="utf-8"))["idempotency_token"] == (
        "attempt-one:extract_context"
    )

    second = dag_execution_adapters._contract_stage_result(
        context,
        unit=_unit("attempt-two:extract_context"),
        artifact=artifact,
        timestamp="2026-05-07T00:00:01Z",
    )

    assert Path(second["contract_artifact_path"]) == output_path
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["idempotency_token"] == "attempt-two:extract_context"
    assert payload["created_at"] == "2026-05-07T00:00:01Z"


def test_external_execution_claim_fails_closed_without_persistence_callback(tmp_path):
    context = dag_execution_adapters.DagExecutionContext(
        repo_root=Path.cwd(),
        lab_dir=tmp_path,
        execution_attempt_id="unsafe-direct-call",
    )

    with pytest.raises(RuntimeError, match="runner-state transaction API"):
        dag_execution_adapters._persist_execution_claim(
            context,
            {"units": [], "events": [], "artifacts": []},
        )

    no_op_context = dag_execution_adapters.DagExecutionContext(
        repo_root=Path.cwd(),
        lab_dir=tmp_path,
        execution_attempt_id="unsafe-no-op-callback",
        persist_execution_claim_fn=lambda _state: None,
    )
    with pytest.raises(RuntimeError, match="durable claim receipt"):
        dag_execution_adapters._persist_execution_claim(
            no_op_context,
            {"units": [], "events": [], "artifacts": []},
        )


@pytest.mark.parametrize("case", ["missing_active", "wrong_active_token", "missing_unit", "completed_unit", "wrong_unit_token"])
def test_recovery_rejects_stale_or_foreign_claim_without_mutating_state(case):
    import copy
    module = importlib.import_module("agilab.dag.dag_execution_adapters")
    state = {"active_execution":{"unit_tokens":{"stage":"token"}},
             "units":[{"id":"stage", "dispatch_status":"running",
                       "execution_attempt":{"idempotency_token":"token"}}]}
    if case == "missing_active":
        state.pop("active_execution")
    elif case == "wrong_active_token":
        state["active_execution"]["unit_tokens"]["stage"] = "other"
    elif case == "missing_unit":
        state["units"] = []
    elif case == "completed_unit":
        state["units"][0]["dispatch_status"] = "completed"
    else:
        state["units"][0]["execution_attempt"]["idempotency_token"] = "other"
    before = copy.deepcopy(state)
    with pytest.raises(ValueError, match="token|missing from runner state"):
        module.recover_execution_attempt(state, unit_id="stage",
            idempotency_token="token", timestamp="2026-09-24T10:00:00Z")
    assert state == before


def test_recovery_preserves_other_ambiguous_parallel_claims():
    import copy
    module = importlib.import_module("agilab.dag.dag_execution_adapters")
    state = {"active_execution":{"unit_tokens":{"stage":"token", "other":"other-token"}},
             "units":[{"id":"stage", "dispatch_status":"running",
                       "execution_attempt":{"idempotency_token":"token"}},
                      {"id":"other", "dispatch_status":"running",
                       "execution_attempt":{"idempotency_token":"other-token"}}],
             "artifacts":[], "events":[], "summary":{}}
    before = copy.deepcopy(state)
    recovered = module.recover_execution_attempt(state, unit_id="stage",
        idempotency_token="token", timestamp="2026-09-24T10:00:00Z")
    assert state == before
    assert recovered["active_execution"]["unit_tokens"] == {"other":"other-token"}
    assert recovered["active_execution"]["status"] == "recovery_required"
    assert recovered["units"][0]["execution_attempt"]["status"] == "recovered_failed"
    assert recovered["units"][1] == state["units"][1]


def test_authored_uav_dag_executes_its_declared_scientific_settings(
    tmp_path: Path,
) -> None:
    from agilab.dag.dag_run_engine import DagRunEngine

    repo_root = Path.cwd()
    template = (
        repo_root
        / "src/agilab/apps/builtin/uav_queue_project/dag_templates/uav_queue_to_relay.json"
    )
    payload = json.loads(template.read_text(encoding="utf-8"))
    engine = DagRunEngine(repo_root=repo_root, lab_dir=tmp_path, dag_path=template)
    state, *_ = engine.load_or_create_state()
    for expected in payload["nodes"]:
        execution = engine.run_next_controlled_stage_transaction(state)
        assert execution.ok
        state = execution.state
        actual = next(unit for unit in state["units"] if unit["id"] == expected["id"])
        metrics = actual["real_execution"]["summary_metrics"]
        for key in (
            "routing_policy",
            "sim_time_s",
            "sampling_interval_s",
            "source_rate_pps",
            "queue_weight",
            "random_seed",
        ):
            assert metrics[key] == expected["execution"]["params"][key]
    assert state["run_status"] == "completed"


@pytest.mark.parametrize(
    "error", [TypeError("body type failure"), ValueError("body value failure")]
)
def test_uav_callback_contract_compatibility_never_reinvokes_body(
    error: Exception,
) -> None:
    calls = []

    def legacy(*, repo_root, run_root, idempotency_token):
        calls.append(idempotency_token)
        raise error

    with pytest.raises(type(error), match="body"):
        dag_execution_adapters._invoke_uav_stage_runner(
            legacy,
            {"execution_contract": {"params": {"sim_time_s": 30}}},
            repo_root=Path.cwd(),
            run_root=Path.cwd(),
            idempotency_token="once",
        )
    assert calls == ["once"]


def test_uav_adapter_passes_per_unit_contract_to_aware_callback(tmp_path: Path) -> None:
    from agilab.dag.dag_run_engine import DagRunEngine

    template = (
        Path.cwd()
        / "src/agilab/apps/builtin/uav_queue_project/dag_templates/uav_queue_to_relay.json"
    )
    observed = []

    def queue_run(*, repo_root, run_root, idempotency_token, execution_contract):
        observed.append(execution_contract)
        run_root.mkdir(parents=True, exist_ok=True)
        summary = run_root / "queue_summary.json"
        reduce = run_root / "queue_reduce.json"
        summary.write_text(
            '{"packets_generated": 2, "packets_delivered": 2}', encoding="utf-8"
        )
        reduce.write_text("{}", encoding="utf-8")
        return {
            "summary_metrics_path": str(summary),
            "reduce_artifact_path": str(reduce),
            "summary_metrics": {"packets_generated": 2, "packets_delivered": 2},
        }

    engine = DagRunEngine(
        repo_root=Path.cwd(),
        lab_dir=tmp_path,
        dag_path=template,
        run_queue_fn=queue_run,
    )
    state, *_ = engine.load_or_create_state()
    result = engine.run_next_controlled_stage_transaction(state)
    assert result.ok
    assert observed == [state["units"][0]["execution_contract"]]
    assert observed[0]["params"]["sim_time_s"] == 30.0


def test_uav_outer_token_cache_rejects_changed_contract_without_callback(
    tmp_path: Path,
) -> None:
    calls = []
    contract = {"params": {"sim_time_s": 2.0}}
    state = {
        "units": [
            {
                "id": "queue_baseline",
                "app": "uav_queue_project",
                "dispatch_status": "runnable",
                "produces": [],
                "execution_contract": contract,
            },
            {
                "id": "relay_followup",
                "app": "uav_relay_queue_project",
                "dispatch_status": "blocked",
                "produces": [],
                "depends_on": ["queue_baseline"],
                "artifact_dependencies": [],
            },
        ],
        "artifacts": [],
    }

    def queue_run(*, run_root, execution_contract, **kwargs):
        calls.append(execution_contract)
        run_root.mkdir(parents=True, exist_ok=True)
        summary = run_root / "summary.json"
        reduce = run_root / "reduce.json"
        summary.write_text(
            '{"packets_generated": 2, "packets_delivered": 2}', encoding="utf-8"
        )
        reduce.write_text("{}", encoding="utf-8")
        return {
            "summary_metrics_path": str(summary),
            "reduce_artifact_path": str(reduce),
            "summary_metrics": {"packets_generated": 2, "packets_delivered": 2},
            "execution_contract": dict(execution_contract),
            "execution_inputs_sha256": "bound",
        }

    context = dag_execution_adapters.DagExecutionContext(
        repo_root=Path.cwd(),
        lab_dir=tmp_path,
        run_queue_fn=queue_run,
        execution_attempt_id="same-attempt",
        persist_execution_claim_fn=lambda _: dag_execution_adapters._DURABLE_CLAIM_RECEIPT,
    )
    first = dag_execution_adapters._run_next_adapter_stage_uncommitted(
        "uav_queue_to_relay_controlled",
        state,
        context,
    )
    assert first.ok
    state["units"][0]["execution_contract"] = {"params": {"sim_time_s": 3.0}}
    second = dag_execution_adapters._run_next_adapter_stage_uncommitted(
        "uav_queue_to_relay_controlled",
        state,
        context,
    )
    assert not second.ok
    assert "different execution contract" in second.message
    assert len(calls) == 1


def test_authored_uav_dag_keeps_independent_node_overrides(tmp_path: Path) -> None:
    from agilab.dag.dag_run_engine import DagRunEngine

    source_root = Path.cwd()
    repo_root = tmp_path / "public-repo"
    relative = Path(
        "src/agilab/apps/builtin/uav_queue_project/dag_templates/uav_queue_to_relay.json"
    )
    template = repo_root / relative
    template.parent.mkdir(parents=True)
    payload = json.loads((source_root / relative).read_text(encoding="utf-8"))
    queue_params = payload["nodes"][0]["execution"]["params"]
    relay_params = payload["nodes"][1]["execution"]["params"]
    queue_params.update(sim_time_s=3.0, source_rate_pps=5.0, random_seed=21)
    relay_params.update(
        sim_time_s=4.0,
        source_rate_pps=9.0,
        routing_policy="queue_aware",
        random_seed=23,
    )
    template.write_text(json.dumps(payload), encoding="utf-8")
    for project in ("uav_queue_project", "uav_relay_queue_project"):
        target = repo_root / "src/agilab/apps/builtin" / project / "src"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(
            source_root / "src/agilab/apps/builtin" / project / "src",
            target_is_directory=True,
        )
        for name in ("pyproject.toml", "pipeline_view.dot"):
            (target.parent / name).write_bytes(
                (source_root / "src/agilab/apps/builtin" / project / name).read_bytes()
            )
    engine = DagRunEngine(
        repo_root=repo_root, lab_dir=tmp_path / "lab", dag_path=template
    )
    state, *_ = engine.load_or_create_state()
    for expected in payload["nodes"]:
        result = engine.run_next_controlled_stage_transaction(state)
        assert result.ok
        state = result.state
        unit = next(unit for unit in state["units"] if unit["id"] == expected["id"])
        metrics = unit["real_execution"]["summary_metrics"]
        assert {
            key: metrics[key]
            for key in expected["execution"]["params"]
            if key not in {"files", "nfile"}
        } == {
            key: value
            for key, value in expected["execution"]["params"].items()
            if key not in {"files", "nfile"}
        }
    assert (
        state["units"][1]["real_execution"]["consumed_artifacts"][0]["summary_metrics"]
        == state["units"][0]["real_execution"]["summary_metrics"]
    )


def test_uav_outer_token_cache_rechecks_exact_relay_context(tmp_path: Path) -> None:
    import hashlib
    from agilab.global_pipeline.global_pipeline_app_dispatch_smoke import (
        _read_queue_context,
    )

    calls = []
    queue_path = tmp_path / "queue_summary.json"
    queue_metrics = {"packets_generated": 8, "packets_delivered": 7}
    queue_path.write_text(json.dumps(queue_metrics), encoding="utf-8")
    queue_result = {
        "summary_metrics_path": str(queue_path),
        "summary_metrics": queue_metrics,
        "summary_metrics_sha256": hashlib.sha256(queue_path.read_bytes()).hexdigest(),
    }
    state = {
        "units": [
            {
                "id": "queue_baseline",
                "app": "uav_queue_project",
                "dispatch_status": "completed",
                "produces": [],
                "real_execution": queue_result,
            },
            {
                "id": "relay_followup",
                "app": "uav_relay_queue_project",
                "dispatch_status": "runnable",
                "produces": [],
                "depends_on": ["queue_baseline"],
                "artifact_dependencies": [],
            },
        ],
        "artifacts": [
            {
                "artifact": "queue_metrics",
                "kind": "summary_metrics",
                "status": "available",
                "producer": "queue_baseline",
                "path": str(queue_path),
            }
        ],
    }

    def relay_run(*, run_root, queue_result, **kwargs):
        calls.append(queue_result)
        run_root.mkdir(parents=True, exist_ok=True)
        summary = run_root / "summary.json"
        reduce = run_root / "reduce.json"
        summary.write_text(
            '{"packets_generated": 2, "packets_delivered": 2}', encoding="utf-8"
        )
        reduce.write_text("{}", encoding="utf-8")
        return {
            "summary_metrics_path": str(summary),
            "reduce_artifact_path": str(reduce),
            "summary_metrics": {"packets_generated": 2, "packets_delivered": 2},
            "execution_inputs_sha256": "bound",
            "consumed_artifacts": [_read_queue_context(queue_result)],
        }

    context = dag_execution_adapters.DagExecutionContext(
        repo_root=Path.cwd(),
        lab_dir=tmp_path / "lab",
        run_relay_fn=relay_run,
        execution_attempt_id="same-relay-attempt",
        persist_execution_claim_fn=lambda _: dag_execution_adapters._DURABLE_CLAIM_RECEIPT,
    )
    first = dag_execution_adapters._run_next_adapter_stage_uncommitted(
        "uav_queue_to_relay_controlled",
        state,
        context,
    )
    assert first.ok
    queue_path.write_bytes(queue_path.read_bytes() + b" ")
    second = dag_execution_adapters._run_next_adapter_stage_uncommitted(
        "uav_queue_to_relay_controlled",
        state,
        context,
    )
    assert not second.ok
    assert "completed producer hash" in second.message
    assert len(calls) == 1


@pytest.mark.parametrize("pollution", ["data_out", "export"])
def test_uav_outer_token_cache_rejects_output_pollution_without_worker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    pollution: str,
) -> None:
    from agi_node.agi_dispatcher import base_worker_runtime_support as runtime_support

    loader = runtime_support.load_worker
    calls = []

    def select_worker(*args, **kwargs):
        calls.append(args[0].target_worker)
        return loader(*args, **kwargs)

    monkeypatch.setattr(runtime_support, "load_worker", select_worker)
    state = {
        "units": [
            {
                "id": "queue_baseline",
                "app": "uav_queue_project",
                "dispatch_status": "runnable",
                "produces": [],
                "execution_contract": {
                    "params": {"sim_time_s": 2.0},
                    "reset_target": False,
                },
            },
            {
                "id": "relay_followup",
                "app": "uav_relay_queue_project",
                "dispatch_status": "blocked",
                "produces": [],
                "depends_on": ["queue_baseline"],
                "artifact_dependencies": [],
            },
        ],
        "artifacts": [],
    }
    context = dag_execution_adapters.DagExecutionContext(
        repo_root=Path.cwd(),
        lab_dir=tmp_path / "lab",
        execution_attempt_id="cached-owned-run",
        persist_execution_claim_fn=lambda _: dag_execution_adapters._DURABLE_CLAIM_RECEIPT,
    )
    first = dag_execution_adapters._run_next_adapter_stage_uncommitted(
        "uav_queue_to_relay_controlled",
        state,
        context,
    )
    assert first.ok
    receipt = first.state["units"][0]["real_execution"]
    root = (
        Path(receipt["effective_args"]["data_out"])
        if pollution == "data_out"
        else Path(receipt["workspace"]) / "export"
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_text("preserve", encoding="utf-8")
    (root / "polluted-child").symlink_to(outside, target_is_directory=True)
    second = dag_execution_adapters._run_next_adapter_stage_uncommitted(
        "uav_queue_to_relay_controlled",
        state,
        context,
    )
    assert not second.ok
    assert "output contains a symlink" in second.message
    assert calls == ["uav_queue_worker"]
    assert list(outside.iterdir()) == [sentinel]
    assert sentinel.read_text(encoding="utf-8") == "preserve"
