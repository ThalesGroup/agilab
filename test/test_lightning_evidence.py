from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "agilab" / "lightning_evidence.py"
MODULE_SPEC = importlib.util.spec_from_file_location("agilab.lightning_evidence", MODULE_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
lightning_evidence = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = lightning_evidence
MODULE_SPEC.loader.exec_module(lightning_evidence)


class FakeScalar:
    def __init__(self, value: float) -> None:
        self.value = value

    def item(self) -> float:
        return self.value


class FakeModel:
    hparams = {"layers": [8, 4], "learning_rate": 0.01}


class FakeDataModule:
    hparams_initial = {"dataset": "tiny"}


def _fake_trainer(checkpoint: Path) -> SimpleNamespace:
    checkpoint_callback = SimpleNamespace(
        best_model_path=str(checkpoint),
        last_model_path="",
        best_k_models={str(checkpoint): FakeScalar(0.92)},
    )
    return SimpleNamespace(
        accelerator="cpu",
        strategy="auto",
        devices=1,
        num_nodes=1,
        precision="32-true",
        max_epochs=3,
        min_epochs=1,
        max_steps=-1,
        deterministic=True,
        fast_dev_run=False,
        enable_checkpointing=True,
        limit_train_batches=1.0,
        limit_val_batches=1.0,
        limit_test_batches=1.0,
        log_every_n_steps=1,
        current_epoch=2,
        global_step=12,
        callback_metrics={
            "val_acc": FakeScalar(0.875),
            "train_loss": FakeScalar(0.123),
        },
        logger=SimpleNamespace(name="csv"),
        callbacks=[checkpoint_callback],
        checkpoint_callback=checkpoint_callback,
        datamodule=FakeDataModule(),
    )


def test_lightning_evidence_callback_writes_manifest_metrics_and_checkpoint_hash(tmp_path: Path) -> None:
    checkpoint = tmp_path / "model.ckpt"
    checkpoint.write_bytes(b"checkpoint-bytes")
    trainer = _fake_trainer(checkpoint)
    model = FakeModel()

    callback = lightning_evidence.AgilabLightningEvidenceCallback(
        tmp_path / "evidence",
        run_id="run-lightning-demo",
        run_name="demo",
        extra_metadata={"source": "unit-test"},
    )
    callback.on_fit_start(trainer, model)
    callback.on_train_epoch_end(trainer, model)
    result = callback.write_evidence(trainer, model)

    assert result.manifest_path.is_file()
    assert result.metrics_path.is_file()
    assert result.checkpoint_manifest_path.is_file()
    assert result.manifest["schema"] == lightning_evidence.LIGHTNING_EVIDENCE_SCHEMA
    assert result.manifest["run_id"] == "run-lightning-demo"
    assert result.manifest["run_name"] == "demo"
    assert result.manifest["model"].endswith("FakeModel")
    assert result.manifest["model_hparams"] == {"layers": [8, 4], "learning_rate": 0.01}
    assert result.manifest["datamodule_hparams"] == {"dataset": "tiny"}
    assert result.manifest["trainer"]["accelerator"] == "cpu"
    assert result.manifest["trainer"]["max_epochs"] == 3
    assert result.manifest["metadata"] == {"source": "unit-test"}

    metric_events = [
        json.loads(line)
        for line in result.metrics_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [event["event"] for event in metric_events] == ["fit_start", "train_epoch_end"]
    assert metric_events[-1]["metrics"] == {"train_loss": 0.123, "val_acc": 0.875}
    checkpoint_entry = result.manifest["checkpoints"]["checkpoints"][0]
    assert checkpoint_entry["path"] == str(checkpoint)
    assert checkpoint_entry["exists"] is True
    assert checkpoint_entry["sha256"] == hashlib.sha256(b"checkpoint-bytes").hexdigest()

    verify = lightning_evidence.verify_lightning_evidence(result.output_dir)
    assert verify["status"] == "pass"


def test_lightning_evidence_verifier_detects_changed_checkpoint(tmp_path: Path) -> None:
    checkpoint = tmp_path / "model.ckpt"
    checkpoint.write_bytes(b"first")
    result = lightning_evidence.write_lightning_evidence(
        tmp_path / "evidence",
        trainer=_fake_trainer(checkpoint),
        pl_module=FakeModel(),
        run_id="run-lightning-demo",
        status="pass",
        checkpoint_paths=[checkpoint],
    )

    checkpoint.write_bytes(b"changed")

    verify = lightning_evidence.verify_lightning_evidence(result.output_dir)
    checkpoint_checks = [check for check in verify["checks"] if check["id"].startswith("checkpoint:")]

    assert verify["status"] == "fail"
    assert checkpoint_checks
    assert checkpoint_checks[0]["status"] == "fail"
    assert checkpoint_checks[0]["details"]["expected_sha256"] == hashlib.sha256(b"first").hexdigest()
    assert checkpoint_checks[0]["details"]["actual_sha256"] == hashlib.sha256(b"changed").hexdigest()


def test_lightning_evidence_helpers_are_dependency_light_and_json_safe(tmp_path: Path) -> None:
    payload = {
        "set": {"b", "a"},
        "path": tmp_path,
        "nan": float("nan"),
        "scalar": FakeScalar(4.5),
    }

    encoded = lightning_evidence.canonical_json(payload)
    decoded = json.loads(encoded)

    assert decoded["set"] == ["a", "b"]
    assert decoded["path"] == str(tmp_path)
    assert decoded["nan"] is None
    assert decoded["scalar"] == 4.5
    assert lightning_evidence.LightningEvidenceCallback is lightning_evidence.AgilabLightningEvidenceCallback


def test_lightning_evidence_lifecycle_and_verifier_edges(tmp_path: Path) -> None:
    trainer = SimpleNamespace(
        current_epoch=1,
        global_step=2,
        callback_metrics={},
        callbacks=[],
        checkpoint_callback=None,
    )
    callback = lightning_evidence.AgilabLightningEvidenceCallback(
        tmp_path / "lifecycle",
        run_id="run-lifecycle",
        checkpoint_paths=[""],
        include_checkpoint_hashes=False,
    )

    callback.on_fit_start(trainer, None)
    callback.on_validation_epoch_end(trainer, None)
    callback.on_test_epoch_end(trainer, None)
    assert [event["event"] for event in callback.metrics] == ["fit_start"]

    callback.on_fit_end(trainer, None)
    manifest = json.loads((tmp_path / "lifecycle" / "lightning_evidence.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "pass"

    failing = lightning_evidence.AgilabLightningEvidenceCallback(tmp_path / "failing", run_id="run-failing")
    failing.on_exception(trainer, None, RuntimeError("boom"))
    fail_manifest = json.loads((tmp_path / "failing" / "lightning_evidence.json").read_text(encoding="utf-8"))
    assert fail_manifest["status"] == "fail"
    assert fail_manifest["exception"] == "RuntimeError: boom"

    invalid_manifest_dir = tmp_path / "invalid"
    invalid_manifest_dir.mkdir()
    (invalid_manifest_dir / "lightning_evidence.json").write_text("{bad json", encoding="utf-8")
    verify = lightning_evidence.verify_lightning_evidence(invalid_manifest_dir)
    assert verify["status"] == "fail"
    assert any(check["id"] == "manifest_schema_supported" for check in verify["checks"])

    assert lightning_evidence.discover_checkpoint_paths(None) == ()
    bad_checks = lightning_evidence._verify_checkpoint_hashes({"checkpoints": {"checkpoints": "bad"}})
    assert bad_checks[0]["id"] == "checkpoints_shape"
    invalid_entry_checks = lightning_evidence._verify_checkpoint_hashes({"checkpoints": {"checkpoints": ["bad"]}})
    assert invalid_entry_checks[0]["id"] == "checkpoint:0"
    missing_artifact = lightning_evidence._verify_artifact({"path": tmp_path / "missing.txt", "sha256": "expected"})
    assert missing_artifact["status"] == "fail"
    assert lightning_evidence.object_identity(None) is None
    assert lightning_evidence._hparams(SimpleNamespace(hparams=SimpleNamespace(alpha=1))) == {"alpha": 1}
    assert lightning_evidence._duration_seconds("not-a-date", "also-bad") is None


def test_lightning_json_safe_handles_array_like_fallbacks() -> None:
    class BrokenItem:
        def item(self):
            raise RuntimeError("bad scalar")

        def tolist(self):
            return [1, 2]

    class BrokenListAndDetach:
        def item(self):
            raise RuntimeError("bad scalar")

        def tolist(self):
            raise RuntimeError("bad list")

        def detach(self):
            return self

        def cpu(self):
            return {"tensor": 3}

    assert lightning_evidence._json_safe(BrokenItem()) == [1, 2]
    assert lightning_evidence._json_safe(BrokenListAndDetach()) == {"tensor": 3}


def test_lightning_evidence_remaining_helper_edges() -> None:
    class BrokenEverything:
        marker = "keeps-dict"

        def item(self):
            raise RuntimeError("bad scalar")

        def tolist(self):
            raise RuntimeError("bad list")

        def detach(self):
            raise RuntimeError("bad detach")

    class BrokenNoDict:
        __slots__ = ()

        def item(self):
            raise RuntimeError("bad scalar")

        def tolist(self):
            raise RuntimeError("bad list")

        def detach(self):
            raise RuntimeError("bad detach")

        def __str__(self) -> str:
            return "opaque"

    assert lightning_evidence.collect_callback_metrics(SimpleNamespace(callback_metrics="bad")) == {}
    assert lightning_evidence.collect_trainer_config(None) == {}
    assert lightning_evidence._json_safe(BrokenEverything()).endswith("BrokenEverything")
    assert lightning_evidence._json_safe(BrokenNoDict()) == "opaque"
    assert lightning_evidence._duration_seconds("2026-06-01T00:00:02Z", "2026-06-01T00:00:01Z") == 0.0
