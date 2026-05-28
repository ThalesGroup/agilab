from __future__ import annotations

import json
import sys
from pathlib import Path

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
