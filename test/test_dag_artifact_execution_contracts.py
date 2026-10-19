from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from agilab.dag import dag_execution_adapters as adapters
from agilab.dag import dag_distributed_submitter as submitter
from agilab.dag.dag_run_engine import DagRunEngine


def _data_unit(*, kind="dataset", entrypoint="missing.executor"):
    output = {"artifact": "scientific_dataset", "path": "data/scientific_dataset.csv"}
    if kind is not None:
        output["kind"] = kind
    return {
        "id": "generate_data",
        "app": "uav_queue_project",
        "dispatch_status": "runnable",
        "execution_contract": {"entrypoint": entrypoint},
        "produces": [output],
    }


def _context(tmp_path, **kwargs):
    return adapters.DagExecutionContext(
        repo_root=Path.cwd(),
        lab_dir=tmp_path,
        execution_attempt_id="artifact-contract-check",
        persist_execution_claim_fn=lambda state: adapters._DURABLE_CLAIM_RECEIPT,
        **kwargs,
    )


def _producer_state(
    tmp_path,
    *,
    producer="source_b",
    source_status="completed",
    consumer_status="blocked",
):
    path = tmp_path / "shared.csv"
    path.write_text("actual dataset")
    return {
        "units": [
            {"id": "source_a", "dispatch_status": source_status},
            {"id": "source_b", "dispatch_status": "completed"},
            {
                "id": "consumer",
                "dispatch_status": consumer_status,
                "artifact_dependencies": [{"artifact": "shared", "from": "source_a"}],
            },
        ],
        "artifacts": [
            {
                "artifact": "shared",
                "producer": producer,
                "status": "available",
                "kind": "dataset",
                "path": str(path),
            }
        ],
    }


def test_readiness_requires_the_declared_producer(tmp_path):
    state = _producer_state(tmp_path)
    consumer = state["units"][2]
    assert not adapters._unblock_unit_when_artifacts_available(
        state, consumer, timestamp="now"
    )
    assert adapters.planned_stage_ids("controlled_contract_dag", state) == ()
    state["artifacts"].append({**state["artifacts"][0], "producer": "source_a"})
    assert adapters._unblock_unit_when_artifacts_available(
        state, consumer, timestamp="now"
    )
    assert adapters.planned_stage_ids("controlled_contract_dag", state) == ("consumer",)


@pytest.mark.parametrize("source_status", ["runnable", "running", "failed", "blocked"])
def test_available_artifact_cannot_bypass_producer_completion(tmp_path, source_status):
    state = _producer_state(tmp_path, producer="source_a", source_status=source_status)
    assert not adapters._artifact_dependency_available(
        state, {"artifact": "shared", "from": "source_a"}
    )
    assert not adapters._unblock_unit_when_artifacts_available(
        state, state["units"][2], timestamp="now"
    )


def test_stale_runnable_consumer_is_reblocked_for_wrong_producer(tmp_path):
    state = _producer_state(tmp_path, consumer_status="runnable")
    assert adapters.planned_stage_ids("controlled_contract_dag", state) == ()
    adapters._unblock_ready_units(state, timestamp="now")
    assert state["units"][2]["dispatch_status"] == "blocked"


def test_artifact_replacement_preserves_other_producers(tmp_path):
    state = _producer_state(tmp_path)
    source_b = deepcopy(state["artifacts"][0])
    new_path = tmp_path / "new.csv"
    retry_path = tmp_path / "retry.csv"
    new_path.write_text("new dataset")
    retry_path.write_text("retry dataset")
    adapters._replace_artifact(
        state,
        {
            "artifact": "shared",
            "producer": "source_a",
            "status": "available",
            "kind": "dataset",
            "path": str(new_path),
        },
    )
    assert source_b in state["artifacts"]
    assert len(state["artifacts"]) == 2
    adapters._replace_artifact(
        state,
        {
            "artifact": "shared",
            "producer": "source_a",
            "status": "available",
            "kind": "dataset",
            "path": str(retry_path),
        },
    )
    assert len(state["artifacts"]) == 2
    assert adapters._artifact_dependency_available(
        state, {"artifact": "shared", "from": "source_a"}
    )


def test_uav_relay_does_not_accept_another_producers_queue_metrics():
    state = {
        "units": [
            {"id": "queue_baseline", "dispatch_status": "completed"},
            {"id": "relay_followup", "dispatch_status": "blocked"},
        ],
        "artifacts": [
            {"artifact": "queue_metrics", "producer": "other", "status": "available"}
        ],
    }
    assert adapters.planned_stage_ids("uav_queue_to_relay_controlled", state) == ()
    assert adapters._queue_result_for_relay(state) == {}


@pytest.mark.parametrize("kind", ["dataset", "summary_metrics", "reduce_summary", None])
def test_unavailable_executor_never_creates_a_scientific_artifact(tmp_path, kind):
    unit = _data_unit(kind=kind)
    result = adapters._run_next_adapter_stage_uncommitted(
        "controlled_contract_dag",
        {"units": [unit], "artifacts": []},
        _context(tmp_path),
    )
    assert not result.ok
    assert "no registered executor" in result.message
    assert result.state["units"][0]["dispatch_status"] == "failed"
    assert not result.state["artifacts"]
    assert not list(tmp_path.rglob("scientific_dataset.csv"))


def test_params_only_contract_requires_an_executable_entrypoint(tmp_path):
    unit = _data_unit(kind="contract_artifact")
    unit["execution_contract"] = {"params": {"scenario": "demo"}}
    result = adapters._run_next_adapter_stage_uncommitted(
        "controlled_contract_dag", {"units": [unit]}, _context(tmp_path)
    )
    assert not result.ok
    assert "execution.entrypoint" in result.message


def test_explicit_receipt_contract_is_labelled_as_metadata(tmp_path):
    unit = _data_unit(kind="contract_artifact")
    unit["produces"][0]["path"] = "evidence/scientific-contract-receipt.json"
    result = adapters._run_next_adapter_stage_uncommitted(
        "controlled_contract_dag",
        {"units": [unit], "artifacts": []},
        _context(tmp_path),
    )
    assert result.ok
    assert "Recorded contract receipt" in result.message
    execution = result.state["units"][0]["contract_execution"]
    assert execution["receipt_only"] is True
    receipt = json.loads(Path(execution["contract_artifact_path"]).read_text())
    assert receipt["receipt_only"] is True
    assert result.state["artifacts"][0]["kind"] == "contract_artifact"


@pytest.mark.parametrize(
    "runner_output", [{}, {"summary_metrics_path": "missing/output.json"}]
)
def test_registered_callback_requires_its_persisted_output(tmp_path, runner_output):
    unit = _data_unit()
    artifact = adapters._primary_contract_artifact({}, unit)
    with pytest.raises(RuntimeError, match="did not produce.*scientific_dataset"):
        adapters._contract_stage_result_once(
            _context(
                tmp_path,
                stage_run_fns={"generate_data": lambda **kwargs: runner_output},
            ),
            unit=unit,
            artifact=artifact,
            timestamp="now",
            idempotency_token="callback-output",
            run_root=tmp_path / "run",
        )
    assert not (tmp_path / "run/data/scientific_dataset.csv").exists()


def _command_unit(tmp_path, *, second_output=False):
    unit = _data_unit()
    code = "from pathlib import Path; Path('data').mkdir(exist_ok=True); Path('data/scientific_dataset.csv').write_text('actual,data\\n')"
    if second_output:
        code += "; Path('data/secondary_dataset.csv').write_text('secondary,data\\n')"
    unit["execution_contract"] = {"command": [sys.executable, "-c", code]}
    unit["produces"].append(
        {
            "artifact": "secondary_dataset",
            "kind": "dataset",
            "path": "data/secondary_dataset.csv",
        }
    )
    return unit


def test_command_must_produce_every_declared_output_even_with_stale_files(tmp_path):
    unit = _command_unit(tmp_path)
    stale = tmp_path / "run/data/secondary_dataset.csv"
    stale.parent.mkdir(parents=True)
    stale.write_text("old attempt")
    with pytest.raises(RuntimeError, match="secondary_dataset"):
        adapters._contract_stage_result_once(
            _context(tmp_path),
            unit=unit,
            artifact=adapters._primary_contract_artifact({}, unit),
            timestamp="now",
            idempotency_token="multiple-output-missing",
            run_root=tmp_path / "run",
        )
    assert not stale.exists()


def test_all_real_command_outputs_are_published_with_producer_identity(tmp_path):
    unit = _command_unit(tmp_path, second_output=True)
    result = adapters._run_next_adapter_stage_uncommitted(
        "controlled_contract_dag",
        {"units": [unit], "artifacts": []},
        _context(tmp_path),
    )
    assert result.ok
    assert {(a["artifact"], a["producer"]) for a in result.state["artifacts"]} == {
        ("scientific_dataset", "generate_data"),
        ("secondary_dataset", "generate_data"),
    }
    assert all(Path(a["path"]).is_file() for a in result.state["artifacts"])


def _distributed_run(
    tmp_path,
    *,
    runner,
    artifact=None,
    produces=None,
    data_out=None,
    token="distributed-output",
):
    repo = tmp_path / "repo"
    app = repo / "src/agilab/apps/builtin/uav_queue_project"
    app.mkdir(parents=True, exist_ok=True)
    (app / "pyproject.toml").write_text(
        '[project]\nname="uav_queue_project"\nversion="0.0.0"\n'
    )
    artifact = artifact or {
        "artifact": "dataset",
        "kind": "dataset",
        "path": "data/dataset.csv",
    }
    unit = {"id": "generate_data", "app": "uav_queue_project"}
    if produces is not None:
        unit["produces"] = produces
    return submitter.submit_distributed_stage(
        config=submitter.DagDistributedStageConfig(
            "local-test", {"local": 1}, str(tmp_path / "share"), 4
        ),
        runner_fn=runner,
        repo_root=repo,
        lab_dir=tmp_path,
        run_root=tmp_path / "run",
        unit=unit,
        artifact=artifact,
        execution_contract={"data_out": data_out},
        timestamp="now",
        idempotency_token=token,
    )


def _writing_runner(outputs, result=None):
    def runner(**kwargs):
        for path, data in outputs.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            replacement = path.with_name(path.name + ".current-attempt")
            replacement.write_bytes(data)
            replacement.replace(path)
        return dict(result or {})

    return runner


def test_distributed_missing_data_never_becomes_a_submission_receipt(tmp_path):
    with pytest.raises(RuntimeError, match="did not produce declared artifact"):
        _distributed_run(tmp_path, runner=lambda **kwargs: {})
    assert not (tmp_path / "run/data/dataset.csv").exists()
    evidence = list((tmp_path / "run/distributed_submission_evidence").glob("*.json"))
    assert len(evidence) == 1
    assert (
        json.loads(evidence[0].read_text())["schema"]
        == "agilab.distributed_dag_stage_submission.v1"
    )


@pytest.mark.parametrize("location", ["run", "share"])
def test_distributed_real_dataset_is_preserved_and_receipt_is_separate(
    tmp_path, location
):
    data = tmp_path / location / "data/dataset.csv"
    data.parent.mkdir(parents=True)
    data.write_bytes(b"actual,dataset\n")
    result = _distributed_run(
        tmp_path,
        runner=_writing_runner({data: b"actual,dataset\n"}),
        data_out="data/dataset.csv",
    )
    assert Path(result["contract_artifact_path"]) == data.resolve()
    assert data.read_bytes() == b"actual,dataset\n"
    assert Path(result["submission_evidence_path"]) != data
    assert Path(result["submission_evidence_path"]).suffix == ".json"
    assert result["receipt_only"] is False


def test_distributed_explicit_receipt_keeps_metadata_contract_valid(tmp_path):
    result = _distributed_run(
        tmp_path,
        runner=lambda **kwargs: {},
        artifact={
            "artifact": "run_receipt",
            "kind": "contract_artifact",
            "path": "receipt.json",
        },
    )
    assert result["receipt_only"] is True
    assert result["contract_artifact_path"] == result["submission_evidence_path"]
    assert Path(result["contract_artifact_path"]).is_file()


def test_distributed_missing_secondary_output_fails_closed(tmp_path):
    data = tmp_path / "run/data/dataset.csv"
    data.parent.mkdir(parents=True)
    data.write_text("actual dataset")
    outputs = [
        {"artifact": "dataset", "kind": "dataset", "path": "data/dataset.csv"},
        {"artifact": "second_dataset", "kind": "dataset", "path": "data/second.csv"},
    ]
    with pytest.raises(RuntimeError, match="second_dataset"):
        _distributed_run(
            tmp_path,
            runner=_writing_runner({data: b"actual dataset"}),
            produces=outputs,
        )
    assert data.read_text() == "actual dataset"


def test_public_engine_cannot_persist_success_for_an_unavailable_data_executor(
    tmp_path,
):
    repo = tmp_path / "repo"
    app = repo / "src/agilab/apps/builtin/uav_queue_project"
    app.mkdir(parents=True)
    (app / "pyproject.toml").write_text(
        '[project]\nname="uav_queue_project"\nversion="0.0.0"\n'
    )
    (app / "pipeline_view.dot").write_text("digraph { start -> end; }\n")
    consumer_app = repo / "src/agilab/apps/builtin/flight_telemetry_project"
    consumer_app.mkdir(parents=True)
    (consumer_app / "pyproject.toml").write_text(
        '[project]\nname="flight_telemetry_project"\nversion="0.0.0"\n'
    )
    (consumer_app / "pipeline_view.dot").write_text("digraph { start -> end; }\n")
    dag = app / "dag_templates/missing-data-executor.json"
    dag.parent.mkdir()
    dag.write_text(
        json.dumps(
            {
                "schema": "agilab.multi_app_dag.v1",
                "dag_id": "missing-data-executor",
                "label": "Missing data executor",
                "description": "A missing executor must not create data.",
                "execution": {
                    "mode": "sequential_dependency_order",
                    "runner_status": "controlled_contract_stage_execution",
                    "adapter": "controlled_contract_dag",
                    "stage_bindings": {
                        "generate_data": "uav_queue_project.missing_executor"
                    },
                },
                "nodes": [
                    {
                        "id": "generate_data",
                        "app": "uav_queue_project",
                        "execution": {
                            "entrypoint": "uav_queue_project.missing_executor"
                        },
                        "produces": [
                            {
                                "id": "scientific_dataset",
                                "kind": "dataset",
                                "path": "data/scientific_dataset.csv",
                            }
                        ],
                    },
                    {
                        "id": "z_consumer",
                        "app": "flight_telemetry_project",
                        "execution": {
                            "command": [
                                sys.executable,
                                "-c",
                                "from pathlib import Path; p=Path('consumer/metrics.json'); "
                                "p.parent.mkdir(parents=True, exist_ok=True); p.write_text('{}')",
                            ]
                        },
                        "produces": [
                            {
                                "id": "consumer_metrics",
                                "kind": "summary_metrics",
                                "path": "consumer/metrics.json",
                            }
                        ],
                        "consumes": [
                            {
                                "id": "scientific_dataset",
                                "kind": "dataset",
                                "path": "data/scientific_dataset.csv",
                            }
                        ],
                    },
                ],
                "edges": [
                    {
                        "from": "generate_data",
                        "to": "z_consumer",
                        "artifact": "scientific_dataset",
                    }
                ],
            }
        )
    )
    engine = DagRunEngine(repo_root=repo, lab_dir=tmp_path / "workspace", dag_path=dag)
    state, state_path, _ = engine.load_or_create_state()
    assert state["ok"] is True
    assert engine.real_run_support(state).supported is True
    result = engine.run_next_controlled_stage(state)
    assert not result.ok
    persisted = json.loads(state_path.read_text())
    assert all(a.get("status") != "available" for a in persisted.get("artifacts", []))
    assert persisted["units"][0]["dispatch_status"] == "failed"
    assert "has no registered executor" in result.message
    assert not list((tmp_path / "workspace").rglob("scientific_dataset.csv"))


def test_distributed_output_resolves_inside_the_authored_data_out_root(tmp_path):
    data = tmp_path / "share/workflow/output/dataset.csv"
    data.parent.mkdir(parents=True)
    data.write_bytes(b"actual,data\n")
    result = _distributed_run(
        tmp_path,
        runner=_writing_runner({data: b"actual,data\n"}),
        data_out="workflow/output",
        artifact={"artifact": "dataset", "kind": "dataset", "path": "dataset.csv"},
    )
    assert Path(result["contract_artifact_path"]) == data.resolve()


def test_distributed_summary_artifact_cannot_be_a_directory(tmp_path):
    path = tmp_path / "run/summary.json"
    path.mkdir(parents=True)
    with pytest.raises(RuntimeError, match="did not produce declared artifact"):
        _distributed_run(
            tmp_path,
            runner=lambda **kwargs: {
                "produced_artifacts": [{"artifact": "metrics", "path": str(path)}]
            },
            data_out="summaries",
            artifact={
                "artifact": "metrics",
                "kind": "summary_metrics",
                "path": "summary.json",
            },
        )


def test_failed_registered_callback_cannot_publish_an_existing_output(tmp_path):
    unit = _data_unit()
    data = tmp_path / "scientific.csv"
    data.write_text("existing scientific output")
    with pytest.raises(RuntimeError, match="executor reported a failed result"):
        adapters._contract_stage_result_once(
            _context(
                tmp_path,
                stage_run_fns={
                    "generate_data": lambda **kwargs: {
                        "status": "error",
                        "contract_artifact_path": str(data),
                    }
                },
            ),
            unit=unit,
            artifact=adapters._primary_contract_artifact({}, unit),
            timestamp="now",
            idempotency_token="failed-callback",
            run_root=tmp_path / "run",
        )


@pytest.mark.parametrize("large_logs", [False, True])
def test_legacy_receipt_cannot_unblock_a_scientific_dependency(tmp_path, large_logs):
    path = tmp_path / "legacy.csv"
    payload = {"schema": "agilab.dag_contract_stage_result.v1", "unit_id": "source_a"}
    if large_logs:
        payload["command_stdout"] = "old logs" * 200000
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    state = _producer_state(tmp_path, producer="source_a")
    state["artifacts"][0].update({"kind": "dataset", "path": str(path)})
    assert not adapters._artifact_dependency_available(
        state, {"artifact": "shared", "from": "source_a"}
    )


def test_callback_cannot_relabel_a_legacy_receipt_as_scientific_data(tmp_path):
    path = tmp_path / "legacy.csv"
    path.write_text(json.dumps({"schema": "agilab.dag_contract_stage_result.v1"}))
    unit = _data_unit()
    with pytest.raises(
        RuntimeError, match="receipt cannot satisfy scientific artifact"
    ):
        adapters._contract_stage_result_once(
            _context(
                tmp_path,
                stage_run_fns={
                    "generate_data": lambda **kwargs: {
                        "contract_artifact_path": str(path),
                    }
                },
            ),
            unit=unit,
            artifact=adapters._primary_contract_artifact({}, unit),
            timestamp="now",
            idempotency_token="legacy-receipt",
            run_root=tmp_path / "run",
        )


def test_distributed_output_cannot_relabel_an_existing_submission_receipt(tmp_path):
    path = tmp_path / "run/data/dataset.csv"
    path.parent.mkdir(parents=True)
    original = json.dumps({"schema": "agilab.distributed_dag_stage_submission.v1"})
    path.write_text(original)
    with pytest.raises(
        RuntimeError, match="receipt cannot satisfy scientific artifact"
    ):
        _distributed_run(tmp_path, runner=lambda **kwargs: {})
    assert path.read_text() == original


@pytest.mark.parametrize("dependency_field", ["depends_on", "dispatch_policy"])
def test_completion_policy_cannot_be_bypassed_by_name_only_inputs(
    tmp_path, dependency_field
):
    state = _producer_state(tmp_path, producer="source_a", source_status="running")
    consumer = state["units"][2]
    consumer["artifact_dependencies"][0].pop("from")
    if dependency_field == "depends_on":
        consumer["depends_on"] = ["source_a"]
    else:
        consumer["dispatch_policy"] = {"requires_completed_dependencies": ["source_a"]}
    assert not adapters._unit_dependencies_available(state, consumer)


@pytest.mark.parametrize("secondary_exists", [False, True])
def test_mixed_output_kinds_cannot_reuse_the_primary_legacy_alias(
    tmp_path, secondary_exists
):
    code = "from pathlib import Path; Path('metrics.json').write_text('{}')"
    if secondary_exists:
        code += "; Path('reduction.json').write_text('{}')"
    unit = {
        "id": "metrics_and_reduction",
        "dispatch_status": "runnable",
        "execution_contract": {"command": [sys.executable, "-c", code]},
        "produces": [
            {"artifact": "metrics", "kind": "summary_metrics", "path": "metrics.json"},
            {
                "artifact": "reduction",
                "kind": "reduce_summary",
                "path": "reduction.json",
            },
        ],
    }
    kwargs = dict(
        unit=unit,
        artifact=adapters._primary_contract_artifact({}, unit),
        timestamp="now",
        idempotency_token="mixed-output-aliases",
        run_root=tmp_path / "run",
    )
    if secondary_exists:
        result = adapters._contract_stage_result_once(_context(tmp_path), **kwargs)
        assert {
            Path(output["path"]).name for output in result["produced_artifacts"]
        } == {"metrics.json", "reduction.json"}
    else:
        with pytest.raises(RuntimeError, match="reduction"):
            adapters._contract_stage_result_once(_context(tmp_path), **kwargs)


@pytest.mark.parametrize(
    "path_state", ["deleted", "missing", "empty", "unset", "null", "malformed"]
)
def test_missing_persisted_output_reblocks_a_previously_runnable_consumer(
    tmp_path, path_state
):
    state = _producer_state(tmp_path, producer="source_a", consumer_status="runnable")
    artifact = state["artifacts"][0]
    if path_state == "deleted":
        Path(artifact["path"]).unlink()
    elif path_state == "missing":
        artifact["path"] = str(tmp_path / "missing.csv")
    elif path_state == "empty":
        artifact["path"] = ""
    elif path_state == "unset":
        artifact.pop("path")
    elif path_state == "null":
        artifact["path"] = None
    else:
        artifact["path"] = []
    assert not adapters._artifact_dependency_available(
        state, {"artifact": "shared", "from": "source_a"}
    )
    assert adapters.planned_stage_ids("controlled_contract_dag", state) == ()
    adapters._unblock_ready_units(state, timestamp="now")
    assert state["units"][2]["dispatch_status"] == "blocked"


def test_summary_dependency_requires_a_persisted_file(tmp_path):
    state = _producer_state(tmp_path, producer="source_a")
    state["artifacts"][0].update({"kind": "summary_metrics", "path": str(tmp_path)})
    assert not adapters._artifact_dependency_available(
        state, {"artifact": "shared", "from": "source_a"}
    )


def test_preview_dispatch_remains_independent_of_materialized_output(tmp_path):
    from agilab.global_pipeline.global_pipeline_runner_state import (
        dispatch_next_runnable,
    )

    state = _producer_state(tmp_path, producer="source_a", consumer_status="runnable")
    Path(state["artifacts"][0]["path"]).unlink()
    state["provenance"] = {
        "dispatch_mode": "simulated_persistent_state",
        "real_app_execution": False,
    }
    result = dispatch_next_runnable(state, now="now")
    assert result.ok and result.dispatched_unit_id == "consumer"
    assert "active_execution" not in result.state
    assert state["units"][2]["dispatch_status"] == "runnable"
    # The same preview state is not sufficient for real execution readiness.
    assert adapters.planned_stage_ids("controlled_contract_dag", state) == ()


def test_distributed_preserves_explicit_paths_for_each_same_kind_output(tmp_path):
    outputs = [
        {"artifact": "x", "kind": "dataset"},
        {"artifact": "y", "kind": "dataset"},
    ]

    def runner(**kwargs):
        run_root = kwargs["run_root"]
        run_root.mkdir(parents=True, exist_ok=True)
        paths = []
        for name in ("x", "y"):
            path = run_root / f"actual-{name}.csv"
            path.write_text(f"{name},data\n")
            paths.append({"artifact": name, "path": str(path)})
        return {"produced_artifacts": paths}

    result = _distributed_run(
        tmp_path, runner=runner, artifact=outputs[0], produces=outputs
    )
    assert {
        output["artifact"]: Path(output["path"]).name
        for output in result["produced_artifacts"]
    } == {"x": "actual-x.csv", "y": "actual-y.csv"}


@pytest.mark.parametrize("report_primary", [True, False])
@pytest.mark.parametrize("secondary_exists", [True, False])
def test_distributed_mixed_kind_alias_cannot_certify_the_missing_secondary(
    tmp_path, report_primary, secondary_exists
):
    primary = tmp_path / "run/metrics.json"
    primary.parent.mkdir()
    primary.write_text("{}")
    secondary = primary.parent / "reduction.json"
    if secondary_exists:
        secondary.write_text("{}")
    outputs = [
        {"artifact": "metrics", "kind": "summary_metrics", "path": "metrics.json"},
        {"artifact": "reduction", "kind": "reduce_summary", "path": "reduction.json"},
    ]
    aliases = {"reduce_artifact_path": str(primary)}
    if report_primary:
        aliases["summary_metrics_path"] = str(primary)
    current_outputs = {primary: b"{}"}
    if secondary_exists:
        current_outputs[secondary] = b"{}"
    runner = _writing_runner(current_outputs, aliases)
    if secondary_exists:
        result = _distributed_run(
            tmp_path,
            runner=runner,
            artifact=outputs[0],
            produces=outputs,
        )
        assert {
            Path(output["path"]).name for output in result["produced_artifacts"]
        } == {"metrics.json", "reduction.json"}
    else:
        with pytest.raises(RuntimeError, match="reduction"):
            _distributed_run(
                tmp_path,
                runner=runner,
                artifact=outputs[0],
                produces=outputs,
            )


@pytest.mark.parametrize(
    "reported",
    [
        None,
        {},
        [None],
        [{"artifact": "x", "path": ""}],
        [{"artifact": "x", "path": None}],
        [{"artifact": "x", "path": 42}],
        [{"artifact": 42, "path": "x.csv"}],
        [{"artifact": "x", "path": "x.csv"}, {"artifact": "x", "path": "other.csv"}],
    ],
)
def test_malformed_per_artifact_paths_fail_closed_for_both_backends(tmp_path, reported):
    output = {"artifact": "x", "kind": "dataset", "path": "data/dataset.csv"}
    path = tmp_path / "run/data/dataset.csv"
    path.parent.mkdir(parents=True)
    path.write_text("real data")
    result = {"produced_artifacts": reported, "contract_artifact_path": str(path)}
    with pytest.raises(RuntimeError, match="DAG executor"):
        adapters._validated_contract_stage_result(
            {"id": "u", "produces": [output]},
            output,
            run_root=tmp_path / "run",
            result=dict(result),
        )
    with pytest.raises(RuntimeError, match="DAG executor"):
        _distributed_run(
            tmp_path, runner=lambda **kwargs: result, artifact=output, produces=[output]
        )


@pytest.mark.parametrize("location", ["run", "share"])
@pytest.mark.parametrize("explicit_report", [True, False])
def test_distributed_noop_cannot_publish_an_older_output_for_a_new_token(
    tmp_path, location, explicit_report
):
    path = tmp_path / location / "data/dataset.csv"
    path.parent.mkdir(parents=True)
    path.write_text("previous attempt data")
    os.utime(path, (100, 100))
    result = (
        {"produced_artifacts": [{"artifact": "dataset", "path": str(path)}]}
        if explicit_report
        else {}
    )
    with pytest.raises(RuntimeError, match="did not produce declared artifact `dataset`"):
        _distributed_run(
            tmp_path,
            runner=lambda **kwargs: result,
            data_out="data/dataset.csv",
            token="new-attempt",
        )
    assert path.read_text() == "previous attempt data"


def test_distributed_deterministic_regeneration_and_same_token_replay(tmp_path):
    path = tmp_path / "share/data/dataset.csv"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"deterministic,data\n")
    os.utime(path, (100, 100))
    calls = []
    writer = _writing_runner({path: b"deterministic,data\n"})

    def runner(**kwargs):
        calls.append(kwargs["idempotency_token"])
        return writer(**kwargs)

    first = _distributed_run(
        tmp_path, runner=runner, data_out="data/dataset.csv", token="first-generation"
    )
    replay = _distributed_run(
        tmp_path, runner=runner, data_out="data/dataset.csv", token="first-generation"
    )
    assert replay == first and calls == ["first-generation"]
    next_result = _distributed_run(
        tmp_path, runner=runner, data_out="data/dataset.csv", token="second-generation"
    )
    assert calls == ["first-generation", "second-generation"]
    assert Path(next_result["contract_artifact_path"]) == path.resolve()
    assert path.read_bytes() == b"deterministic,data\n"


@pytest.mark.parametrize("explicit_report", [True, False])
def test_registered_callback_noop_cannot_publish_a_preexisting_output(
    tmp_path, explicit_report
):
    unit = _data_unit()
    path = tmp_path / "run/data/scientific_dataset.csv"
    path.parent.mkdir(parents=True)
    path.write_text("previous attempt data")
    os.utime(path, (100, 100))
    result = (
        {"produced_artifacts": [{"artifact": "scientific_dataset", "path": str(path)}]}
        if explicit_report
        else {}
    )
    with pytest.raises(RuntimeError, match="freshly produce.*scientific_dataset"):
        adapters._contract_stage_result_once(
            _context(
                tmp_path, stage_run_fns={"generate_data": lambda **kwargs: result}
            ),
            unit=unit,
            artifact=adapters._primary_contract_artifact({}, unit),
            timestamp="now",
            idempotency_token="new-callback-attempt",
            run_root=tmp_path / "run",
        )


def test_registered_callback_deterministic_regeneration_and_same_token_replay(tmp_path):
    unit = _data_unit()
    path = (
        adapters._real_run_root(tmp_path, "generate_data")
        / "data/scientific_dataset.csv"
    )
    path.parent.mkdir(parents=True)
    path.write_text("deterministic data")
    calls = []
    writer = _writing_runner({path: b"deterministic data"})

    def runner(**kwargs):
        calls.append(kwargs["idempotency_token"])
        return writer(**kwargs)

    context = _context(tmp_path, stage_run_fns={"generate_data": runner})
    artifact = adapters._primary_contract_artifact({}, unit)
    unit["execution_attempt"] = {"idempotency_token": "first-callback-generation"}
    first = adapters._contract_stage_result(
        context, unit=unit, artifact=artifact, timestamp="now"
    )
    replay = adapters._contract_stage_result(
        context, unit=unit, artifact=artifact, timestamp="now"
    )
    assert replay == first and calls == ["first-callback-generation"]
    unit["execution_attempt"]["idempotency_token"] = "second-callback-generation"
    next_result = adapters._contract_stage_result(
        context, unit=unit, artifact=artifact, timestamp="now"
    )
    assert calls == ["first-callback-generation", "second-callback-generation"]
    assert Path(next_result["contract_artifact_path"]) == path


def test_registered_callback_replay_cannot_republish_a_deleted_cached_output(tmp_path):
    unit = _data_unit()
    unit["execution_attempt"] = {"idempotency_token": "cached-callback-output"}
    path = (
        adapters._real_run_root(tmp_path, "generate_data")
        / "data/scientific_dataset.csv"
    )
    calls = []
    writer = _writing_runner({path: b"current data"})

    def runner(**kwargs):
        calls.append(kwargs["idempotency_token"])
        return writer(**kwargs)

    context = _context(tmp_path, stage_run_fns={"generate_data": runner})
    artifact = adapters._primary_contract_artifact({}, unit)
    adapters._contract_stage_result(
        context, unit=unit, artifact=artifact, timestamp="now"
    )
    path.unlink()
    with pytest.raises(RuntimeError, match="did not produce.*scientific_dataset"):
        adapters._contract_stage_result(
            context, unit=unit, artifact=artifact, timestamp="now"
        )
    assert calls == ["cached-callback-output"]


@pytest.mark.parametrize("phase", ["callback", "completed_cache"])
def test_distributed_adapter_preserves_exact_packet_intent_across_callback_and_cache(tmp_path, phase):
    producer = tmp_path / "original-queue.json"
    producer.write_text('{"packets_generated": 3, "packets_delivered": 2}')
    original = {
        "artifact": "queue_metrics", "producer": "queue_baseline", "kind": "summary_metrics",
        "path": str(producer), "resolved_path": str(producer.resolve()),
        "producer_run_root": str(tmp_path), **submitter.artifact_file_identity(producer),
    }
    unit = {
        "id": "relay_followup", "app": "uav_relay_queue_project",
        "execution_contract": {"params": {}},
        "execution_attempt": {"idempotency_token": "authored-packet-intent"},
        "artifact_dependencies": [{"from": "queue_baseline", "artifact": "queue_metrics"}],
        "produces": [{"artifact": "relay_metrics", "kind": "summary_metrics", "path": "relay.json"}],
    }
    artifact = unit["produces"][0]
    calls = []

    def legacy_endpoint(**arguments):
        calls.append(arguments)
        output = arguments["run_root"] / "relay.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text('{"packets_generated": 3, "packets_delivered": 2}')
        return {
            "summary_metrics_path": str(output),
            "input_artifact_fingerprint": submitter._input_artifact_fingerprint([original]),
            "consumed_artifacts": [{**original, "role": "upstream_context",
                "read_scope": "child_orchestrator", "numerically_conditioned": False,
                "summary_metrics": {"packets_generated": 3, "packets_delivered": 2}}],
        }

    context = _context(tmp_path, stage_submit_fn=legacy_endpoint)
    if phase == "completed_cache":
        adapters._distributed_stage_result(
            context, unit=unit, artifact=artifact, timestamp="now", input_artifacts=[original],
        )
    unit["execution_contract"]["params"]["use_upstream_delivery_trace"] = True
    expected_error = RuntimeError if phase == "callback" else ValueError
    with pytest.raises(expected_error, match="actual worker packet consumption receipt"):
        adapters._distributed_stage_result(
            context, unit=unit, artifact=artifact, timestamp="now", input_artifacts=[original],
        )
    assert len(calls) == 1


def test_submission_receipt_write_cannot_make_an_old_dataset_directory_fresh(tmp_path):
    run_root = tmp_path / "run"
    run_root.mkdir()
    (run_root / "old-data.csv").write_text("previous data")
    with pytest.raises(RuntimeError, match="did not produce declared artifact `dataset`"):
        _distributed_run(
            tmp_path,
            runner=lambda **kwargs: {},
            artifact={"artifact": "dataset", "kind": "dataset", "path": "."},
        )


def test_snapshot_skips_virtual_environments_and_symlink_loops(tmp_path):
    from agilab.dag.dag_artifact_contracts import ArtifactOutputSnapshot

    cache = tmp_path / ".venv/scientific.csv"
    cache.parent.mkdir()
    cache.write_text("old cached data")
    (tmp_path / "loop").symlink_to(tmp_path, target_is_directory=True)
    snapshot = ArtifactOutputSnapshot(workspaces=[tmp_path])
    with pytest.raises(RuntimeError, match="Declare its output path"):
        snapshot.require_fresh(cache, artifact_id="cached_data")
    output = tmp_path / "output.csv"
    output.write_text("current output")
    snapshot.require_fresh(output, artifact_id="actual_data")


def test_cache_creation_cannot_make_an_existing_dataset_directory_fresh(tmp_path):
    from agilab.dag.dag_artifact_contracts import ArtifactOutputSnapshot

    (tmp_path / "old-data.csv").write_text("old data")
    snapshot = ArtifactOutputSnapshot(workspaces=[tmp_path])
    cache = tmp_path / ".venv/cache.txt"
    cache.parent.mkdir()
    cache.write_text("only cache changed")
    with pytest.raises(RuntimeError, match="freshly produce.*dataset"):
        snapshot.require_fresh(tmp_path, artifact_id="dataset")


@pytest.mark.parametrize("explicit_report", [True, False])
def test_custom_distributed_callback_noop_cannot_publish_old_workspace_output(
    tmp_path, explicit_report
):
    unit = _data_unit()
    unit["execution_attempt"] = {"idempotency_token": "new-custom-distributed-attempt"}
    path = (
        adapters._real_run_root(tmp_path, "generate_data")
        / "data/scientific_dataset.csv"
    )
    path.parent.mkdir(parents=True)
    path.write_text("previous attempt data")
    os.utime(path, (100, 100))
    result = (
        {"produced_artifacts": [{"artifact": "scientific_dataset", "path": str(path)}]}
        if explicit_report
        else {}
    )
    with pytest.raises(RuntimeError, match="freshly produce.*scientific_dataset"):
        adapters._distributed_stage_result(
            _context(tmp_path, stage_submit_fn=lambda **kwargs: result),
            unit=unit,
            artifact=adapters._primary_contract_artifact({}, unit),
            timestamp="now",
        )


def test_adapter_accepts_current_token_shared_output_validation_and_rechecks_replay_files(
    tmp_path,
):
    unit = _data_unit()
    unit["execution_attempt"] = {"idempotency_token": "verified-shared-submission"}
    path = tmp_path / "share/data/scientific_dataset.csv"
    path.parent.mkdir(parents=True)
    path.write_text("old generation")
    calls = []
    writer = _writing_runner({path: b"current shared data"})

    def stage_submit(**kwargs):
        calls.append(kwargs["idempotency_token"])
        return submitter.submit_distributed_stage(
            config=submitter.DagDistributedStageConfig(
                "local-test", {"local": 1}, str(tmp_path / "share"), 4
            ),
            runner_fn=writer,
            **kwargs,
        )

    context = _context(tmp_path, stage_submit_fn=stage_submit)
    artifact = adapters._primary_contract_artifact({}, unit)
    first = adapters._distributed_stage_result(
        context, unit=unit, artifact=artifact, timestamp="now"
    )
    receipt = json.loads(Path(first["submission_evidence_path"]).read_text())
    assert receipt["artifact_validation"]["status"] == "passed"
    assert Path(first["contract_artifact_path"]) == path.resolve()
    replay = adapters._distributed_stage_result(
        context, unit=unit, artifact=artifact, timestamp="now"
    )
    assert replay == first and calls == ["verified-shared-submission"]
    path.unlink()
    with pytest.raises(RuntimeError, match="did not produce.*scientific_dataset"):
        adapters._distributed_stage_result(
            context, unit=unit, artifact=artifact, timestamp="now"
        )
    assert calls == ["verified-shared-submission"]


@pytest.mark.parametrize("receipt_status", ["failed", "passed"])
def test_old_or_failed_submission_receipt_cannot_attest_a_new_custom_attempt(
    tmp_path, receipt_status
):
    unit = _data_unit()
    unit["execution_attempt"] = {"idempotency_token": "new-attempt"}
    path = tmp_path / "share/old-data.csv"
    path.parent.mkdir()
    path.write_text("old data")
    run_root = adapters._real_run_root(tmp_path, "generate_data")
    run_root.mkdir(parents=True)
    receipt_path = run_root / "old-submission-evidence.json"
    receipt_path.write_text(
        json.dumps(
            {
                "schema": "agilab.distributed_dag_stage_submission.v1",
                "unit_id": "generate_data",
                "idempotency_token": "old-attempt"
                if receipt_status == "passed"
                else "new-attempt",
                "artifact_validation": {
                    "status": receipt_status,
                    "produced_artifacts": [
                        {
                            "artifact": "scientific_dataset",
                            "kind": "dataset",
                            "path": str(path),
                        }
                    ],
                },
            }
        )
    )
    result = {
        "submission_evidence_path": str(receipt_path),
        "contract_artifact_path": str(path),
    }
    with pytest.raises(RuntimeError, match="Declare its output path"):
        adapters._distributed_stage_result(
            _context(tmp_path, stage_submit_fn=lambda **kwargs: result),
            unit=unit,
            artifact=adapters._primary_contract_artifact({}, unit),
            timestamp="now",
        )


@pytest.mark.parametrize(
    "backend,shape",
    [
        (backend, shape)
        for backend in (
            "local_callback",
            "distributed_callback",
            "distributed_submitter",
        )
        for shape in ("file", "directory", "workspace")
    ]
    + [("local_command", "file")],
)
@pytest.mark.parametrize("change", ["modified", "unbound"])
def test_executor_token_cache_rejects_changed_artifact_bytes(
    tmp_path, backend, shape, change
):
    token = "bound-scientific-output"
    unit = _data_unit()
    if shape != "file":
        unit["produces"][0]["path"] = "data" if shape == "directory" else "."
    output = unit["produces"][0]
    run_root = (
        tmp_path / "run"
        if backend == "distributed_submitter"
        else adapters._real_run_root(tmp_path, unit["id"])
    )
    data = run_root / "data/scientific_dataset.csv"
    unit["execution_attempt"] = {"idempotency_token": token}
    calls = []

    def writer(**kwargs):
        calls.append(kwargs["idempotency_token"])
        data.parent.mkdir(parents=True, exist_ok=True)
        data.write_bytes(b"value,1\n")
        return {}

    if backend == "local_command":
        unit["execution_contract"]["command"] = [
            sys.executable,
            "-c",
            "from pathlib import Path; Path('data').mkdir(exist_ok=True); "
            "Path('data/scientific_dataset.csv').write_bytes(b'value,1\\n'); "
            "Path('command-calls').write_text('once')",
        ]
    context = _context(
        tmp_path,
        stage_run_fns={unit["id"]: writer},
        stage_submit_fn=writer,
    )
    artifact = adapters._primary_contract_artifact({}, unit)

    def execute():
        if backend == "distributed_submitter":
            return _distributed_run(
                tmp_path, runner=writer, artifact=output, token=token
            )
        executor = (
            adapters._distributed_stage_result
            if backend == "distributed_callback"
            else adapters._contract_stage_result
        )
        effective_context = (
            _context(tmp_path) if backend == "local_command" else context
        )
        return executor(
            effective_context, unit=unit, artifact=artifact, timestamp="now"
        )

    first = execute()
    assert execute() == first
    if change == "modified":
        data.write_bytes(b"value,2\n")
    else:
        scope = (
            "distributed-submitter" if backend == "distributed_submitter" else "adapter"
        )
        for ledger_path in (run_root / ".agilab-idempotency").glob("*.json"):
            ledger = json.loads(ledger_path.read_text())
            if ledger["scope"] == scope:
                for record in ledger["result"]["produced_artifacts"]:
                    for key in ("sha256", "size_bytes", "identity_kind", "entry_count"):
                        record.pop(key, None)
                ledger_path.write_text(json.dumps(ledger))
    with pytest.raises(ValueError, match="produced artifact"):
        execute()
    if backend == "local_command":
        assert (run_root / "command-calls").read_text() == "once"
    else:
        assert calls == [token]


@pytest.mark.parametrize(
    "change",
    ["rename", "empty_directory", "symlink_file", "symlink_directory", "symlink_root"],
)
def test_cached_dataset_directory_tracks_members_and_rejects_symlinks(
    tmp_path, monkeypatch, change
):
    unit = _data_unit()
    unit["produces"][0]["path"] = "dataset"
    unit["execution_attempt"] = {"idempotency_token": "directory-members"}
    run_root = adapters._real_run_root(tmp_path, unit["id"])
    dataset = run_root / "dataset"
    calls = []

    def writer(**kwargs):
        calls.append(kwargs["idempotency_token"])
        dataset.mkdir(parents=True)
        (dataset / "rows.csv").write_bytes(b"value,1\n")
        return {}

    context = _context(tmp_path, stage_run_fns={unit["id"]: writer})
    artifact = adapters._primary_contract_artifact({}, unit)

    def execute():
        return adapters._contract_stage_result(
            context, unit=unit, artifact=artifact, timestamp="now"
        )

    execute()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.csv").write_bytes(b"never read this")
    original_open = Path.open

    def guarded_open(path, *args, **kwargs):
        assert not path.resolve().is_relative_to(outside), (
            "Must not read a symlink target"
        )
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    if change == "rename":
        (dataset / "rows.csv").rename(dataset / "renamed.csv")
    elif change == "empty_directory":
        (dataset / "empty").mkdir()
    elif change == "symlink_root":
        dataset.rename(run_root / "original-dataset")
        dataset.symlink_to(outside, target_is_directory=True)
    else:
        target = outside / "private.csv" if change == "symlink_file" else outside
        (dataset / "linked").symlink_to(
            target, target_is_directory=change == "symlink_directory"
        )

    with pytest.raises(ValueError, match="produced artifact"):
        execute()
    assert calls == ["directory-members"]


def test_directory_artifact_identity_is_ordered_and_ignores_only_runtime_metadata(
    tmp_path,
):
    from agilab.dag.dag_artifact_contracts import artifact_identity

    first = tmp_path / "first"
    second = tmp_path / "second"
    for root, names in ((first, ("z", "a")), (second, ("a", "z"))):
        root.mkdir()
        for name in names:
            (root / name).write_bytes(name.encode())
        (root / "empty").mkdir()
    assert artifact_identity(first, run_root=first) == artifact_identity(
        second, run_root=second
    )
    original = artifact_identity(first, run_root=first)
    for name in (".agilab-idempotency", "distributed_submission_evidence"):
        metadata = first / name
        metadata.mkdir()
        (metadata / "receipt.json").write_text("{}")
    assert artifact_identity(first, run_root=first) == original
    # A same-named directory below the dataset is user output and stays in the digest.
    nested = first / "data/distributed_submission_evidence"
    nested.mkdir(parents=True)
    (nested / "scientific.csv").write_text("real data")
    assert artifact_identity(first, run_root=first) != original


def test_nested_completed_submitter_cannot_rebind_changed_outputs_as_fresh(tmp_path):
    unit = _data_unit()
    token = "nested-submitter"
    unit["execution_attempt"] = {"idempotency_token": token}
    run_root = adapters._real_run_root(tmp_path, unit["id"])
    path = run_root / unit["produces"][0]["path"]
    calls = []
    config = submitter.DagDistributedStageConfig(
        "local-test", {"local": 1}, str(tmp_path / "share"), 4
    )

    def writer(**kwargs):
        calls.append(kwargs["idempotency_token"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"value,1\n")
        return {}

    artifact = adapters._primary_contract_artifact({}, unit)

    def submit(**kwargs):
        return submitter.submit_distributed_stage(
            config=config,
            runner_fn=writer,
            repo_root=Path.cwd(),
            lab_dir=tmp_path,
            run_root=run_root,
            unit=unit,
            artifact=artifact,
            execution_contract=unit["execution_contract"],
            timestamp="now",
            idempotency_token=token,
        )

    submit()
    path.write_bytes(b"value,2\n")
    with pytest.raises(RuntimeError, match="produced artifact"):
        adapters._distributed_stage_result(
            _context(tmp_path, stage_submit_fn=submit),
            unit=unit,
            artifact=artifact,
            timestamp="now",
        )
    assert calls == [token]


def test_nested_cached_transport_cannot_validate_modified_scientific_output(
    tmp_path, monkeypatch
):
    import subprocess

    token = "nested-transport"
    path = tmp_path / "run/data/dataset.csv"
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"value,1\n")
        kwargs["stdout"].write(
            json.dumps(
                {
                    "result": {
                        "produced_artifacts": [
                            {
                                "artifact": "dataset",
                                "kind": "dataset",
                                "path": str(path),
                            }
                        ]
                    }
                }
            )
            + "\n"
        )
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(submitter.subprocess, "run", fake_run)
    config = submitter.DagDistributedStageConfig(
        "local-test", {"local": 1}, str(tmp_path / "share"), 4
    )
    submitter.run_agilab_stage_subprocess(
        config=config,
        repo_root=tmp_path,
        run_root=tmp_path / "run",
        apps_path=tmp_path / "apps",
        app_name="uav_queue_project",
        request_payload={"data_out": None},
        timestamp="now",
        idempotency_token=token,
    )
    path.write_bytes(b"value,2\n")
    # Transport-cache completion is not a fresh scientific execution.
    with pytest.raises(RuntimeError, match="did not produce declared artifact `dataset`"):
        _distributed_run(
            tmp_path, runner=submitter.run_agilab_stage_subprocess, token=token
        )
    assert len(calls) == 1


@pytest.mark.parametrize(
    "corruption", ["empty", "missing_record", "wrong_kind", "wrong_primary_alias"]
)
def test_submitter_cache_requires_every_original_output_record(tmp_path, corruption):
    paths = [
        tmp_path / "run/data/dataset.csv",
        tmp_path / "run/data/second.csv",
    ]
    outputs = [
        {"artifact": "dataset", "kind": "dataset", "path": "data/dataset.csv"},
        {"artifact": "second", "kind": "dataset", "path": "data/second.csv"},
    ]
    calls = []
    writer = _writing_runner({path: b"value,1\n" for path in paths})

    def runner(**kwargs):
        calls.append(kwargs["idempotency_token"])
        return writer(**kwargs)

    def execute():
        return _distributed_run(
            tmp_path,
            runner=runner,
            artifact=outputs[0],
            produces=outputs,
            token="complete-records",
        )

    execute()
    (ledger_path,) = (tmp_path / "run/.agilab-idempotency").glob("*.json")
    ledger = json.loads(ledger_path.read_text())
    result = ledger["result"]
    if corruption == "empty":
        result["produced_artifacts"] = []
    elif corruption == "missing_record":
        result["produced_artifacts"].pop()
    elif corruption == "wrong_kind":
        result["produced_artifacts"][0]["kind"] = "summary_metrics"
    else:
        result["contract_artifact_path"] = str(paths[1])
    ledger_path.write_text(json.dumps(ledger))
    with pytest.raises(ValueError, match="Cached produced artifact"):
        execute()
    assert calls == ["complete-records"]


@pytest.mark.parametrize("changed", [False, True])
def test_normalized_output_id_preserves_original_byte_identity(tmp_path, changed):
    from agilab.dag.dag_artifact_contracts import artifact_identity

    unit = _data_unit()
    path = tmp_path / "data/scientific_dataset.csv"
    path.parent.mkdir()
    path.write_bytes(b"value,1\n")
    original = artifact_identity(path, run_root=tmp_path)
    result = {
        "produced_artifacts": [
            {
                "artifact": " scientific_dataset ",
                "kind": "dataset",
                "path": str(path),
                **original,
            }
        ]
    }
    if changed:
        path.write_bytes(b"value,2\n")

    def validate():
        return adapters._validated_contract_stage_result(
            unit,
            adapters._primary_contract_artifact({}, unit),
            run_root=tmp_path,
            result=result,
            bind_output_identity=True,
        )

    if changed:
        with pytest.raises(ValueError, match="completed producer bytes"):
            validate()
    else:
        (record,) = validate()["produced_artifacts"]
        assert record["artifact"] == "scientific_dataset"
        assert {key: record[key] for key in original} == original


@pytest.mark.parametrize("linked", ["file", "parent"])
def test_cached_regular_artifact_rejects_symlink_before_receipt_read(
    tmp_path, monkeypatch, linked
):
    unit = _data_unit()
    unit["execution_attempt"] = {"idempotency_token": "regular-file-symlink"}
    run_root = adapters._real_run_root(tmp_path, unit["id"])
    path = run_root / "data/scientific_dataset.csv"
    calls = []
    writer = _writing_runner({path: b"value,1\n"})

    def runner(**kwargs):
        calls.append(kwargs["idempotency_token"])
        return writer(**kwargs)

    context = _context(tmp_path, stage_run_fns={unit["id"]: runner})
    artifact = adapters._primary_contract_artifact({}, unit)

    def execute():
        return adapters._contract_stage_result(
            context, unit=unit, artifact=artifact, timestamp="now"
        )

    execute()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / path.name).write_bytes(path.read_bytes())
    if linked == "file":
        path.unlink()
        path.symlink_to(outside / path.name)
    else:
        path.parent.rename(run_root / "original-data")
        path.parent.symlink_to(outside, target_is_directory=True)
    original_open = Path.open

    def guarded_open(candidate, *args, **kwargs):
        assert not candidate.resolve().is_relative_to(outside), (
            "Must not read an external symlink target"
        )
        return original_open(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    with pytest.raises(ValueError, match="produced artifact.*symlink"):
        execute()
    assert calls == ["regular-file-symlink"]


def test_directory_identity_runtime_exclusions_use_canonical_run_root(tmp_path):
    from agilab.dag.dag_artifact_contracts import artifact_identity

    canonical = tmp_path / "canonical"
    canonical.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(canonical, target_is_directory=True)
    actual_root = canonical / "run"
    actual_root.mkdir()
    (actual_root / "scientific.csv").write_bytes(b"value,1\n")
    before = artifact_identity(actual_root, run_root=alias / "run")
    for name in (".agilab-idempotency", "distributed_submission_evidence"):
        metadata = actual_root / name
        metadata.mkdir()
        (metadata / "receipt.json").write_text("{}")
    assert artifact_identity(actual_root, run_root=alias / "run") == before


def test_workspace_directory_cache_preserves_runtime_parent_alias(tmp_path):
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(canonical, target_is_directory=True)
    path = alias / "run/scientific.csv"
    calls = []
    writer = _writing_runner({path: b"value,1\n"})

    def runner(**kwargs):
        calls.append(kwargs["idempotency_token"])
        return writer(**kwargs)

    def execute():
        return _distributed_run(
            alias,
            runner=runner,
            artifact={"artifact": "dataset", "kind": "dataset", "path": "."},
            token="aliased-runtime",
        )

    first = execute()
    assert execute() == first
    assert calls == ["aliased-runtime"]


@pytest.mark.parametrize("linked", ["root", "child"])
@pytest.mark.parametrize(
    "native",
    [
        pytest.param(False, id="simulated"),
        pytest.param(
            True,
            id="native-windows",
            marks=pytest.mark.skipif(
                sys.platform != "win32", reason="native Windows directory junction required"
            ),
        ),
    ],
)
def test_cached_dataset_rejects_junction_before_target_reads(
    tmp_path, monkeypatch, linked, native
):
    unit = _data_unit()
    unit["produces"][0]["path"] = "dataset"
    unit["execution_attempt"] = {"idempotency_token": "directory-junction"}
    run_root = adapters._real_run_root(tmp_path, unit["id"])
    dataset = run_root / "dataset"
    calls = []

    def writer(**kwargs):
        calls.append(kwargs["idempotency_token"])
        (dataset / "child").mkdir(parents=True)
        (dataset / "child/rows.csv").write_bytes(b"value,1\n")
        return {}

    context = _context(tmp_path, stage_run_fns={unit["id"]: writer})
    artifact = adapters._primary_contract_artifact({}, unit)

    def execute():
        return adapters._contract_stage_result(
            context, unit=unit, artifact=artifact, timestamp="now"
        )

    first = execute()
    assert execute() == first
    junction = dataset if linked == "root" else dataset / "child"
    outside = tmp_path / "outside"
    destination = outside / "child" if linked == "root" else outside
    destination.mkdir(parents=True)
    (destination / "rows.csv").write_bytes(b"value,1\n")
    if native:
        junction.rename(run_root / "original-output")
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
            capture_output=True,
            text=True,
            check=True,
        )
        assert junction.is_junction()
        assert not junction.is_symlink()
    else:
        # Model Windows' separate junction flag on a normal directory: os.walk
        # still descends unless the artifact contract explicitly rejects it.
        original_is_junction = Path.is_junction
        monkeypatch.setattr(
            Path,
            "is_junction",
            lambda path: path.absolute() == junction.absolute()
            or original_is_junction(path),
        )
        assert not junction.is_symlink()

    original_open = Path.open
    original_receipt_probe = adapters.is_contract_receipt_artifact
    reads = []

    def guarded_open(path, *args, **kwargs):
        target = path.resolve() if native else path.absolute()
        forbidden = outside if native else junction.absolute()
        if target.is_relative_to(forbidden):
            reads.append(path)
            raise AssertionError("Must not read a junction target")
        return original_open(path, *args, **kwargs)

    def guarded_receipt_probe(path):
        assert not path.is_junction(), "Must reject a junction before receipt probing"
        return original_receipt_probe(path)

    monkeypatch.setattr(Path, "open", guarded_open)
    monkeypatch.setattr(adapters, "is_contract_receipt_artifact", guarded_receipt_probe)
    try:
        with pytest.raises(ValueError, match="produced artifact.*junction"):
            execute()
        assert reads == []
        assert calls == ["directory-junction"]
    finally:
        if native:
            junction.rmdir()


@pytest.mark.parametrize("linked", ["declared", "child"])
def test_snapshot_does_not_traverse_junctions(tmp_path, monkeypatch, linked):
    from agilab.dag.dag_artifact_contracts import ArtifactOutputSnapshot

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    junction = workspace / "junction" if linked == "child" else tmp_path / "junction"
    junction.mkdir()
    (junction / "rows.csv").write_bytes(b"value,1\n")
    original_is_junction = Path.is_junction
    monkeypatch.setattr(
        Path,
        "is_junction",
        lambda path: path.absolute() == junction.absolute()
        or original_is_junction(path),
    )
    original_stat = Path.stat

    def guarded_stat(path, *args, **kwargs):
        if kwargs.get("follow_symlinks", True):
            assert not path.absolute().is_relative_to(junction.absolute()), (
                "Must not inspect junction target metadata"
            )
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", guarded_stat)
    if linked == "child":
        snapshot = ArtifactOutputSnapshot(workspaces=[workspace])
        with pytest.raises(RuntimeError, match="Declare its output path"):
            snapshot.require_fresh(junction / "rows.csv", artifact_id="linked-data")
        current = workspace / "current.csv"
        current.write_bytes(b"fresh")
        snapshot.require_fresh(current, artifact_id="current-data")
    else:
        with pytest.raises(ValueError, match="junction"):
            ArtifactOutputSnapshot(
                workspaces=[workspace],
                declared_paths=[junction],
            )


@pytest.mark.parametrize("linked", ["symlink", "junction"])
def test_snapshot_preserves_explicit_workspace_anchor_alias(
    tmp_path, monkeypatch, linked
):
    from agilab.dag.dag_artifact_contracts import artifact_identity

    canonical = tmp_path / "canonical"
    canonical.mkdir()
    (canonical / "old.csv").write_bytes(b"value,1\n")
    anchor = tmp_path / "anchor"
    anchor.symlink_to(canonical, target_is_directory=True)
    if linked == "junction":
        original_is_junction = Path.is_junction
        original_is_symlink = Path.is_symlink
        monkeypatch.setattr(
            Path,
            "is_junction",
            lambda path: path.absolute() == anchor.absolute()
            or original_is_junction(path),
        )
        monkeypatch.setattr(
            Path,
            "is_symlink",
            lambda path: path.absolute() != anchor.absolute()
            and original_is_symlink(path),
        )
    # Real callback construction declares "." through the chosen raw anchor.
    unit = _data_unit()
    unit["produces"][0]["path"] = "."
    snapshot = adapters._callback_output_snapshot(unit, run_root=anchor)
    original = artifact_identity(canonical, run_root=anchor)
    with pytest.raises(RuntimeError, match="freshly produce"):
        snapshot.require_fresh(anchor, artifact_id="workspace")
    (canonical / "current.csv").write_bytes(b"value,2\n")
    snapshot.require_fresh(anchor, artifact_id="workspace")
    assert artifact_identity(canonical, run_root=anchor) != original
    replacement = canonical / "replacement"
    replacement.mkdir()
    (replacement / "rows.csv").write_bytes(b"value,3\n")
    anchor.unlink()
    anchor.symlink_to(replacement, target_is_directory=True)
    with pytest.raises(ValueError, match="workspace anchor changed location"):
        snapshot.require_fresh(anchor, artifact_id="workspace")
