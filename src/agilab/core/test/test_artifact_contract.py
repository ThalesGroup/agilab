from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agi_node import ArtifactContract, WORKER_ARTIFACT_MANIFEST_SCHEMA
from agi_node.agi_dispatcher import BaseWorker
from agi_node.dag_worker import DagWorker


class DummyWorker(BaseWorker):
    def works(self, *_args, **_kwargs):
        return 0.0


def test_baseworker_records_artifacts_metrics_and_manifest(tmp_path):
    worker = DummyWorker()
    output = tmp_path / "artifacts"
    output.mkdir()
    artifact = output / "summary.json"
    artifact.write_text('{"ok": true}\n', encoding="utf-8")
    worker.worker_id = 7
    worker.data_out = output

    artifact_record = worker.record_artifact(
        "summary.json",
        kind="summary",
        label="Run summary",
        metadata={"stage": "reduce"},
    )
    metric_record = worker.record_metric("rows", 42, unit="count")
    manifest = worker.artifact_manifest(metadata={"run": "demo"})

    assert artifact_record["path"] == "summary.json"
    assert metric_record == {"name": "rows", "value": 42, "unit": "count"}
    assert manifest["schema"] == WORKER_ARTIFACT_MANIFEST_SCHEMA
    assert manifest["worker_class"] == "DummyWorker"
    assert manifest["worker_id"] == 7
    assert manifest["artifact_count"] == 1
    assert manifest["metric_count"] == 1
    assert manifest["metadata"] == {"run": "demo"}
    assert manifest["artifacts"][0]["exists"] is True
    assert manifest["artifacts"][0]["size_bytes"] == artifact.stat().st_size


def test_baseworker_writes_manifest_to_args_artifact_dir(tmp_path):
    worker = DummyWorker()
    worker.args = SimpleNamespace(artifact_dir=tmp_path / "manifest-root")
    worker.record_artifact("plot.png", kind="figure", artifact_id="plot")
    worker.record_metric("accuracy", 0.91)

    manifest_path = worker.write_manifest(manifest_name="manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest_path == tmp_path / "manifest-root" / "manifest.json"
    assert manifest["manifest_path"] == "manifest.json"
    assert manifest["artifacts"] == [
        {
            "exists": False,
            "id": "plot",
            "kind": "figure",
            "path": "plot.png",
        }
    ]
    assert manifest["metrics"] == [{"name": "accuracy", "value": 0.91}]


def test_artifact_contract_resets_records_and_preserves_metric_metadata(tmp_path):
    worker = DummyWorker()
    worker.data_out = tmp_path

    worker.record_artifact("summary.json", kind="summary")
    metric = worker.record_metric("loss", 0.12, metadata={"split": "validation"})

    assert metric == {
        "name": "loss",
        "value": 0.12,
        "metadata": {"split": "validation"},
    }

    worker.reset_artifact_contract()
    manifest = worker.artifact_manifest()

    assert manifest["artifact_count"] == 0
    assert manifest["metric_count"] == 0
    assert manifest["artifacts"] == []
    assert manifest["metrics"] == []


def test_artifact_manifest_resolves_mapping_args_and_cwd_fallback(tmp_path, monkeypatch):
    mapping_root = tmp_path / "mapping-root"
    mapping_root.mkdir()
    (mapping_root / "mapped.json").write_text("{}\n", encoding="utf-8")
    worker = DummyWorker()
    worker.args = {"data_out": mapping_root}
    worker.record_artifact("mapped.json", kind="json")

    mapping_manifest = worker.artifact_manifest()

    assert mapping_manifest["artifacts"][0]["exists"] is True

    cwd_root = tmp_path / "cwd-root"
    cwd_root.mkdir()
    (cwd_root / "cwd.txt").write_text("ok\n", encoding="utf-8")
    cwd_worker = DummyWorker()
    cwd_worker.record_artifact("cwd.txt", kind="text")

    monkeypatch.chdir(cwd_root)
    cwd_manifest = cwd_worker.artifact_manifest()

    assert cwd_manifest["artifacts"][0]["exists"] is True


def test_artifact_contract_is_available_on_dag_worker(tmp_path):
    worker = DagWorker()
    artifact = tmp_path / "dag-output.txt"
    artifact.write_text("done\n", encoding="utf-8")

    worker.record_artifact(artifact, kind="text")
    worker.record_metric("stage_count", 3)
    manifest = worker.artifact_manifest(output_dir=tmp_path)

    assert isinstance(worker, ArtifactContract)
    assert manifest["worker_class"] == "DagWorker"
    assert manifest["artifacts"][0]["exists"] is True
    assert manifest["metrics"] == [{"name": "stage_count", "value": 3}]


@pytest.mark.parametrize(
    ("call", "match"),
    [
        (lambda worker: worker.record_artifact("", kind="json"), "artifact path"),
        (lambda worker: worker.record_artifact("out.json", kind=""), "artifact kind"),
        (lambda worker: worker.record_metric("", 1), "metric name"),
        (lambda worker: worker.write_manifest(manifest_name=""), "manifest name"),
    ],
)
def test_artifact_contract_rejects_empty_identifiers(tmp_path, call, match):
    worker = DummyWorker()
    worker.data_out = tmp_path

    with pytest.raises(ValueError, match=match):
        call(worker)
