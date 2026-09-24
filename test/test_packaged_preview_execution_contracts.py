"""Executable contracts for optional tracking and local migration previews."""

import importlib.machinery
import json
import sys
from types import ModuleType, SimpleNamespace

import pytest

from agilab.examples.mlflow_auto_tracking import (
    preview_mlflow_auto_tracking as tracking,
)
from agilab.examples.notebook_to_dask import preview_notebook_to_dask as notebook
from agilab.examples.parallel_stage import preview_parallel_stage as parallel


@pytest.fixture
def fake_mlflow(monkeypatch):
    module = ModuleType("mlflow")
    module.__spec__ = importlib.machinery.ModuleSpec("mlflow", loader=None)
    calls = []
    for operation in (
        "set_tracking_uri",
        "set_experiment",
        "log_param",
        "log_metric",
        "log_artifact",
        "end_run",
    ):
        setattr(
            module,
            operation,
            lambda *args, _operation=operation: calls.append((_operation, args)),
        )

    def start_run(*, run_name):
        calls.append(("start_run", (run_name,)))
        return SimpleNamespace(info=SimpleNamespace(run_id="test-local-run"))

    module.start_run = start_run
    monkeypatch.setitem(sys.modules, "mlflow", module)
    return module, calls


def test_tracking_cli_logs_complete_evidence_and_closes_run(
    tmp_path, fake_mlflow, capsys
):
    _, calls = fake_mlflow
    config = tmp_path / "run.json"
    config.write_text(
        json.dumps(
            {
                "experiment_name": "contract",
                "run_name": "local",
                "params": {"rows": 12},
                "metrics": {"score": "0.75"},
                "app": "demo",
                "pipeline": "fit",
            }
        )
    )
    output = tmp_path / "evidence"
    result = tracking.main(
        [
            "--config",
            str(config),
            "--output-dir",
            str(output),
            "--backend",
            "mlflow",
            "--require-mlflow",
            "--tracking-uri",
            "file:" + str(tmp_path / "mlruns"),
        ]
    )
    artifact = output / "artifacts" / "run_summary.json"
    assert calls == [
        ("set_tracking_uri", ("file:" + str(tmp_path / "mlruns"),)),
        ("set_experiment", ("contract",)),
        ("start_run", ("local",)),
        ("log_param", ("rows", 12)),
        ("log_metric", ("score", 0.75)),
        ("log_artifact", (str(artifact),)),
        ("end_run", ()),
    ]
    assert result["tracking"]["run_id"] == "test-local-run"
    assert result["tracking"]["status"] == "logged"
    assert result["registry_created_by_agilab"] is False
    assert json.loads(artifact.read_text())["metrics"] == {"score": 0.75}
    assert json.loads(capsys.readouterr().out) == result
    assert json.loads((output / "mlflow_tracking_preview.json").read_text()) == result


@pytest.mark.parametrize("backend,required", [("mlflow", False), ("auto", True)])
def test_requested_mlflow_requires_installed_backend(monkeypatch, backend, required):
    original = tracking.importlib.util.find_spec
    monkeypatch.setattr(
        tracking.importlib.util,
        "find_spec",
        lambda name: None if name == "mlflow" else original(name),
    )
    with pytest.raises(SystemExit, match="not installed"):
        tracking.create_tracker(
            backend=backend,
            experiment_name="test",
            run_name="test",
            tracking_uri=None,
            require_mlflow=required,
        )


@pytest.mark.parametrize("backend", ["none", "noop", "local", " NONE "])
def test_disabled_tracking_is_explicit_local_evidence(backend):
    tracker = tracking.create_tracker(
        backend=backend, experiment_name="test", run_name="test", tracking_uri=None
    )
    assert tracker.backend == "none"
    assert "disabled" in tracker.reason.lower()
    assert tracker.status == "skipped"


def test_tracking_rejects_unknown_backend_before_import():
    with pytest.raises(SystemExit, match="Unsupported tracking backend"):
        tracking.create_tracker(
            backend="remote-guess",
            experiment_name="test",
            run_name="test",
            tracking_uri=None,
        )


def test_mlflow_logging_failure_still_ends_run_and_keeps_local_evidence(
    tmp_path, fake_mlflow
):
    module, calls = fake_mlflow
    config = tmp_path / "run.json"
    config.write_text('{"metrics": {"loss": 0.25}}')

    def fail(*args):
        raise RuntimeError("tracking server unavailable")

    module.log_metric = fail
    with pytest.raises(RuntimeError, match="tracking server unavailable"):
        tracking.run_preview(
            config_path=config, output_dir=tmp_path / "evidence", backend="mlflow"
        )
    assert calls[-1] == ("end_run", ())
    assert (tmp_path / "evidence/artifacts/run_summary.json").is_file()
    assert not (tmp_path / "evidence/mlflow_tracking_preview.json").exists()


@pytest.mark.parametrize(
    "module,loader", [(tracking, "load_config"), (notebook, "load_json")]
)
def test_preview_json_loaders_reject_array_payloads(tmp_path, module, loader):
    path = tmp_path / "invalid.json"
    path.write_text("[]")
    with pytest.raises((ValueError, SystemExit), match="JSON object"):
        getattr(module, loader)(path)


@pytest.mark.parametrize("raw", [None, {}, "not-a-list"])
def test_notebook_artifact_references_require_a_list(raw):
    assert notebook._artifact_paths({"artifact_references": raw}) == []


def test_notebook_artifact_contract_deduplicates_mixed_references():
    payload = {
        "artifact_references": [
            None,
            123,
            {},
            {"path": ""},
            {"path": " data/source.csv "},
            {"path": "data/source.csv"},
            {"path": "result/model.json"},
        ]
    }
    contract = notebook.artifact_contract_from_import(
        payload, {"artifact_contract": None}
    )
    assert contract == {
        "inputs": ["data/source.csv"],
        "outputs": ["result/model.json"],
        "analysis_consumes": [],
    }


@pytest.mark.parametrize(
    "stages", [None, "invalid", [None, 1, {"id": "plain", "env_hints": []}]]
)
def test_dask_solution_does_not_infer_execution_from_invalid_stages(stages):
    result = notebook.dask_solution_from_import({"pipeline_stages": stages})
    assert result["stage_count"] == 0
    assert result["stage_ids"] == []
    assert result["real_execution"] is False


@pytest.mark.parametrize(
    "sample,generated",
    [
        (None, []),
        ([], None),
        ([{}], []),
        ([None], [{}]),
        ([{}], [None]),
        ([{"D": 1}], [{"D": 2}]),
    ],
)
def test_notebook_sample_match_rejects_structural_or_stage_drift(sample, generated):
    key = notebook.PROJECT_NAME
    assert not notebook._sample_matches_generated({key: sample}, {key: generated})


@pytest.mark.parametrize("write_output", [False, True])
def test_notebook_cli_writes_only_requested_preview(tmp_path, capsys, write_output):
    output = tmp_path / "notebook-preview.json"
    args = ["--output", str(output)]
    if not write_output:
        args.append("--no-output")
    result = notebook.main(args)
    assert result["real_notebook_execution"] is False
    assert result["dask_solution"]["real_execution"] is False
    assert result["lab_stages_preview"]["matches_generated"] is True
    assert output.exists() is write_output
    if write_output:
        assert json.loads(output.read_text()) == result
    assert json.loads(capsys.readouterr().out) == result


@pytest.mark.parametrize("workers", [None, 0, -2, 1.5, "four"])
def test_parallel_contract_rejects_invalid_worker_configuration(workers):
    with pytest.raises(ValueError, match="positive integer"):
        parallel._requested_workers({"workers": workers}, 8)


@pytest.mark.parametrize(
    "file_count,workers,splittable,expected",
    [
        (0, 8, True, 1),
        (0, 8, False, 1),
        (12, 8, False, 8),
        (2, 8, True, 8),
        (2, 8, False, 2),
    ],
)
def test_parallel_effective_workers_obeys_file_split_contract(
    file_count, workers, splittable, expected
):
    assert (
        parallel.effective_workers(
            file_count=file_count,
            requested_workers=workers,
            files_are_splittable=splittable,
        )
        == expected
    )


@pytest.mark.parametrize(
    "files,strategy,splittable,expected",
    [
        (0, "row-chunks", True, 1),
        (0, "row-chunks", False, 1),
        (2, "one-file-per-partition", True, 2),
        (2, "file-chunks", False, 2),
        (2, "row-chunks", True, 24),
    ],
)
def test_parallel_partition_plan_keeps_unsplittable_files_atomic(
    files, strategy, splittable, expected
):
    assert (
        parallel.planned_partitions(
            contract={
                "partition_strategy": strategy,
                "target_partitions": 24,
                "min_partitions_per_worker": 2,
            },
            file_count=files,
            requested_workers=8,
            files_are_splittable=splittable,
        )
        == expected
    )


def test_parallel_validation_reports_all_missing_contract_fields():
    issues = parallel.validate_contract({})
    assert (
        len([issue for issue in issues if issue.startswith("missing required key:")])
        == 12
    )
    assert "schema must be agilab.parallel_stage.v1" in issues
    assert "this preview expects split = files" in issues
    assert "low-file-count scaling needs a chunking partition_strategy" in issues
    assert any("target_partitions must" in issue for issue in issues)


@pytest.mark.parametrize("write_output", [False, True])
def test_parallel_cli_respects_output_mode_and_explicit_capacity(
    tmp_path, capsys, write_output
):
    output = tmp_path / "parallel-preview.json"
    args = ["--output", str(output), "--available-cores", "4", "--file-count", "0"]
    if not write_output:
        args.append("--no-output")
    result = parallel.main(args)
    assert result["contract_valid"] is True
    assert output.exists() is write_output
    if write_output:
        assert json.loads(output.read_text()) == result
    assert json.loads(capsys.readouterr().out) == result
