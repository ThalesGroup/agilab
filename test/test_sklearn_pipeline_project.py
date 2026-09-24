from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROJECT_SRC = ROOT / "src/agilab/apps/builtin/sklearn_pipeline_project/src"
sys.path.insert(0, str(PROJECT_SRC))

from sklearn_pipeline import (  # noqa: E402
    SklearnPipelineArgs,
    SklearnPipeline,
    build_sklearn_pipeline_artifacts,
    filter_arg_overrides,
    safe_reset_path,
)
from sklearn_pipeline.reduction import partial_from_sklearn_summary  # noqa: E402
from sklearn_pipeline_worker.sklearn_pipeline_worker import (  # noqa: E402
    SklearnPipelineWorker,
)


@pytest.mark.parametrize(
    "value",
    [
        "",
        ".",
        "..",
        "../outside",
        "sklearn_pipeline/../outside",
        "/tmp/sklearn_pipeline",
        "~/sklearn_pipeline",
        r"C:\tmp\sklearn_pipeline",
        "C:tmp/sklearn_pipeline",
    ],
)
def test_sklearn_pipeline_rejects_unsafe_data_out(value: str) -> None:
    with pytest.raises(ValueError):
        SklearnPipelineArgs(data_out=value)


def test_sklearn_pipeline_filters_generic_runtime_kwargs() -> None:
    filtered = filter_arg_overrides(
        {
            "data_out": "sklearn_pipeline/evidence",
            "sample_count": 80,
            "verbose": 2,
            "scheduler": "127.0.0.1",
            "workers": {"127.0.0.1": 1},
        }
    )

    assert filtered == {
        "data_out": "sklearn_pipeline/evidence",
        "sample_count": 80,
    }
    assert SklearnPipelineArgs(**filtered).sample_count == 80


def test_sklearn_pipeline_manager_keeps_dispatched_args_relative(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class FakeEnv:
        verbose = 0
        target = "sklearn_pipeline_project"
        app = "sklearn_pipeline_project"
        active_app = "sklearn_pipeline_project"
        AGILAB_EXPORT_ABS = tmp_path / "export"

        def resolve_share_path(self, path: str | Path) -> Path:
            return tmp_path / "share" / Path(path)

    monkeypatch.setattr(SklearnPipeline, "_ensure_managed_pc_share_dir", lambda self, env: None)
    monkeypatch.setattr(SklearnPipeline, "_apply_managed_pc_paths", lambda self, args: args)

    app = SklearnPipeline(
        FakeEnv(),
        data_out="sklearn_pipeline/evidence",
        scheduler="127.0.0.1",
        workers={"127.0.0.1": 1},
    )

    assert app.args.data_out == Path("sklearn_pipeline/evidence")
    assert app.data_out == (tmp_path / "share" / "sklearn_pipeline" / "evidence")


def test_sklearn_pipeline_safe_reset_path_stays_under_share_root(tmp_path: Path) -> None:
    share_root = tmp_path / "share"
    target = share_root / "sklearn_pipeline" / "evidence"
    target.mkdir(parents=True)

    assert safe_reset_path(target, share_root=share_root, label="data_out") == target.resolve(strict=False)

    with pytest.raises(ValueError, match="share root"):
        safe_reset_path(share_root, share_root=share_root, label="data_out")
    with pytest.raises(ValueError, match="under"):
        safe_reset_path(tmp_path / "outside", share_root=share_root, label="data_out")


def test_sklearn_pipeline_worker_rejects_absolute_output_outside_share(
    tmp_path: Path,
) -> None:
    share_root = tmp_path / "share"
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "important.txt"
    marker.write_text("keep", encoding="utf-8")

    def _resolve_share_path(value: str | Path) -> Path:
        candidate = Path(value)
        return candidate if candidate.is_absolute() else share_root / candidate

    worker = SklearnPipelineWorker()
    worker.env = SimpleNamespace(
        resolve_share_path=_resolve_share_path,
        AGILAB_EXPORT_ABS=tmp_path / "export",
        target="sklearn_pipeline_project",
    )
    worker.args = SklearnPipelineArgs.model_construct(
        data_out=outside,
        reset_target=True,
    )

    with pytest.raises(ValueError, match="active share root"):
        worker.start()

    assert marker.read_text(encoding="utf-8") == "keep"


def test_sklearn_pipeline_artifact_summary_matches_persisted_file(tmp_path: Path) -> None:
    output_dir = tmp_path / "evidence"

    summary = build_sklearn_pipeline_artifacts(
        output_dir=output_dir,
        seed=2026,
        sample_count=80,
        test_size=0.25,
        regularization_c=1.0,
    )

    persisted_summary = json.loads((output_dir / "sklearn_pipeline_summary.json").read_text(encoding="utf-8"))
    persisted_manifest = json.loads((output_dir / "run_manifest.json").read_text(encoding="utf-8"))

    assert persisted_summary == summary
    assert set(summary["artifacts"]) == {
        "manifest",
        "metrics",
        "model",
        "predictions",
        "report",
    }
    assert "manifest" not in persisted_manifest["artifacts"]
    assert summary["artifacts"]["manifest"]["path"] == "run_manifest.json"
    assert (output_dir / "metrics.json").is_file()
    assert (output_dir / "predictions.csv").is_file()
    assert (output_dir / "model.joblib").is_file()

    partial = partial_from_sklearn_summary(summary, partial_id="worker-0")
    assert partial.payload["run_count"] == 1
    assert partial.payload["test_rows"] == summary["metrics"]["test_rows"]
    assert "run_manifest.json" in partial.payload["artifact_paths"]


@pytest.mark.parametrize("reset", [False, True])
def test_worker_exports_real_training_evidence_and_preserves_unrelated_files(tmp_path, monkeypatch, reset):
    import importlib
    module = importlib.import_module("sklearn_pipeline_worker.sklearn_pipeline_worker")
    monkeypatch.setattr(module, "_runtime", {})
    share = tmp_path / "share"
    export = tmp_path / "export"
    output = share / "sklearn_pipeline" / "evidence"
    artifact = export / "sklearn_pipeline_project" / "sklearn_pipeline"
    for directory in (output, artifact):
        directory.mkdir(parents=True)
        (directory / "stale.txt").write_text("old")
    sibling = share / "unrelated.txt"
    sibling.write_text("keep")
    worker = SklearnPipelineWorker()
    worker.env = SimpleNamespace(
        resolve_share_path=lambda value: share / Path(value),
        AGILAB_EXPORT_ABS=export,
        target="sklearn_pipeline_project",
    )
    worker.args = dict(data_out="sklearn_pipeline/evidence", sample_count=80, reset_target=reset)
    worker._worker_id = 2
    worker.start()
    assert worker.data_out == output
    assert worker.artifact_dir == artifact
    for directory in (output, artifact):
        assert (directory / "stale.txt").exists() is (not reset)
    worker.pool_init(worker.pool_vars)
    frame = worker.work_pool("single-run")
    assert len(frame) == 1
    assert frame.iloc[0]["worker_id"] == 2
    assert frame.iloc[0]["data_out"] == str(output)
    assert frame.iloc[0]["artifact_dir"] == str(artifact)
    for path in output.rglob("*"):
        if path.is_file():
            assert (artifact / path.relative_to(output)).read_bytes() == path.read_bytes()
    assert (output / "model.joblib").is_file()
    assert (output / "run_manifest.json").is_file()
    assert sibling.read_text() == "keep"


@pytest.mark.parametrize("representation", ["model", "dict", "namespace", "object"])
def test_worker_args_accept_runtime_representations_without_private_transport_fields(representation):
    import importlib
    module = importlib.import_module("sklearn_pipeline_worker.sklearn_pipeline_worker")
    values = dict(sample_count=80, seed=34)
    if representation == "model":
        value = SklearnPipelineArgs(**values)
    elif representation == "dict":
        value = dict(**values, _transport="ignored")
    elif representation == "namespace":
        value = SimpleNamespace(**values, _transport="ignored")
    else:
        class Payload:
            pass
        value = Payload()
        value.__dict__.update(values, _transport="ignored")
    result = module._args_with_defaults(value)
    assert result.sample_count == 80
    assert result.seed == 34
    assert not hasattr(result, "_transport")
    if representation == "model":
        assert result is value


@pytest.mark.parametrize("plan,worker_id,expected", [
    ([[["a", "b"], ("c",), "d"]], 0, ["a", "b", "c", "d"]),
    ([[["other"]], [["mine"]]], 1, ["mine"]),
    ([], 0, []),
    (None, 0, []),
    (["invalid-batches"], 0, []),
    ([[["other"]]], 1, []),
])
@pytest.mark.parametrize("started", [None, 10.0])
def test_worker_schedule_only_processes_assigned_batches(monkeypatch, plan, worker_id, expected, started):
    import importlib
    from unittest.mock import Mock
    module = importlib.import_module("sklearn_pipeline_worker.sklearn_pipeline_worker")
    monkeypatch.setattr(module.BaseWorker, "_t0", started)
    monkeypatch.setattr(module, "time", SimpleNamespace(time=lambda: 20.0))
    worker = SklearnPipelineWorker()
    worker._worker_id = worker_id
    processed = []
    completed = []
    worker.work_pool = lambda item: processed.append(item) or {"item": item}
    worker.work_done = lambda summary: completed.append(summary["item"])
    worker.stop = Mock()
    elapsed = worker.works(plan, None)
    assert processed == completed == expected
    worker.stop.assert_called_once_with()
    assert elapsed == (0.0 if started is None else 10.0)


def test_artifact_copy_to_same_directory_preserves_existing_payload(tmp_path):
    import importlib
    module = importlib.import_module("sklearn_pipeline_worker.sklearn_pipeline_worker")
    payload = tmp_path / "metrics.json"
    payload.write_text('{"accuracy": 1}')
    module._copy_artifacts(tmp_path, tmp_path / ".")
    assert payload.read_text() == '{"accuracy": 1}'
