"""PyTorch Lightning evidence bridge for AGILAB.

The module is intentionally dependency-light: importing it must not install or
import PyTorch Lightning. When Lightning is available, the callback subclasses
``lightning.pytorch.callbacks.Callback``; otherwise it remains a plain Python
object with the same hook methods, which keeps tests and packaging lightweight.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import platform
from importlib import metadata as importlib_metadata
from pathlib import Path
import sys
import uuid
from typing import Any, Iterable, Mapping, Sequence


LIGHTNING_EVIDENCE_SCHEMA = "agilab.lightning_evidence.v1"
LIGHTNING_CHECKPOINT_SCHEMA = "agilab.lightning_checkpoint_manifest.v1"
LIGHTNING_VERIFY_SCHEMA = "agilab.lightning_evidence_verification.v1"

MANIFEST_FILENAME = "lightning_evidence.json"
METRICS_FILENAME = "metrics.jsonl"
CHECKPOINT_MANIFEST_FILENAME = "checkpoint_manifest.json"


@dataclass(frozen=True)
class LightningEvidenceWriteResult:
    output_dir: Path
    manifest_path: Path
    metrics_path: Path
    checkpoint_manifest_path: Path
    manifest: dict[str, Any]


def _callback_base() -> type:
    try:
        from lightning.pytorch.callbacks import Callback
    except Exception:
        return object
    return Callback


class AgilabLightningEvidenceCallback(_callback_base()):
    """Capture Trainer metrics, configuration, and checkpoints as AGILAB evidence.

    The callback writes three files under ``output_dir``:

    - ``metrics.jsonl``: one normalized metric event per line
    - ``checkpoint_manifest.json``: checkpoint paths and optional SHA-256 hashes
    - ``lightning_evidence.json``: run-level manifest linking the two artifacts
    """

    def __init__(
        self,
        output_dir: str | Path,
        *,
        run_id: str | None = None,
        run_name: str | None = None,
        extra_metadata: Mapping[str, Any] | None = None,
        checkpoint_paths: Sequence[str | Path] | None = None,
        include_checkpoint_hashes: bool = True,
    ) -> None:
        try:
            super().__init__()
        except TypeError:
            pass
        self.output_dir = Path(output_dir)
        self.run_id = run_id or f"lightning-{uuid.uuid4().hex[:12]}"
        self.run_name = run_name or "lightning-training"
        self.extra_metadata = dict(extra_metadata or {})
        self.checkpoint_paths = tuple(Path(path) for path in checkpoint_paths or ())
        self.include_checkpoint_hashes = include_checkpoint_hashes
        self._started_at = utc_now()
        self._finished_at: str | None = None
        self._status = "unknown"
        self._exception: str | None = None
        self._metrics: list[dict[str, Any]] = []
        self._trainer_config: dict[str, Any] = {}

    @property
    def metrics(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._metrics)

    def on_fit_start(self, trainer: Any, pl_module: Any) -> None:
        self._started_at = utc_now()
        self._status = "running"
        self._exception = None
        self._trainer_config = collect_trainer_config(trainer)
        self._record_metrics(trainer, pl_module, event="fit_start")

    def on_train_epoch_end(self, trainer: Any, pl_module: Any) -> None:
        self._record_metrics(trainer, pl_module, event="train_epoch_end")

    def on_validation_epoch_end(self, trainer: Any, pl_module: Any) -> None:
        self._record_metrics(trainer, pl_module, event="validation_epoch_end")

    def on_test_epoch_end(self, trainer: Any, pl_module: Any) -> None:
        self._record_metrics(trainer, pl_module, event="test_epoch_end")

    def on_fit_end(self, trainer: Any, pl_module: Any) -> None:
        self._status = "pass"
        self._finished_at = utc_now()
        self.write_evidence(trainer, pl_module)

    def on_exception(self, trainer: Any, pl_module: Any, exception: BaseException) -> None:
        self._status = "fail"
        self._exception = f"{type(exception).__name__}: {exception}"
        self._finished_at = utc_now()
        self.write_evidence(trainer, pl_module)

    def write_evidence(self, trainer: Any = None, pl_module: Any = None) -> LightningEvidenceWriteResult:
        return write_lightning_evidence(
            self.output_dir,
            trainer=trainer,
            pl_module=pl_module,
            run_id=self.run_id,
            run_name=self.run_name,
            status=self._status,
            started_at=self._started_at,
            finished_at=self._finished_at or utc_now(),
            metrics=self._metrics,
            trainer_config=self._trainer_config or collect_trainer_config(trainer),
            exception=self._exception,
            extra_metadata=self.extra_metadata,
            checkpoint_paths=self.checkpoint_paths,
            include_checkpoint_hashes=self.include_checkpoint_hashes,
        )

    def _record_metrics(self, trainer: Any, pl_module: Any, *, event: str) -> None:
        metrics = collect_callback_metrics(trainer)
        if not metrics and event != "fit_start":
            return
        self._metrics.append(
            {
                "event": event,
                "epoch": _json_safe(getattr(trainer, "current_epoch", None)),
                "global_step": _json_safe(getattr(trainer, "global_step", None)),
                "metrics": metrics,
                "model": object_identity(pl_module),
            }
        )


LightningEvidenceCallback = AgilabLightningEvidenceCallback


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def collect_callback_metrics(trainer: Any) -> dict[str, Any]:
    metrics = getattr(trainer, "callback_metrics", {}) if trainer is not None else {}
    if not isinstance(metrics, Mapping):
        return {}
    return {str(key): _json_safe(value) for key, value in sorted(metrics.items(), key=lambda item: str(item[0]))}


def collect_trainer_config(trainer: Any) -> dict[str, Any]:
    if trainer is None:
        return {}
    fields = (
        "accelerator",
        "strategy",
        "devices",
        "num_nodes",
        "precision",
        "max_epochs",
        "min_epochs",
        "max_steps",
        "deterministic",
        "fast_dev_run",
        "enable_checkpointing",
        "limit_train_batches",
        "limit_val_batches",
        "limit_test_batches",
        "log_every_n_steps",
    )
    config = {field: _json_safe(getattr(trainer, field, None)) for field in fields}
    logger = getattr(trainer, "logger", None)
    config["logger"] = object_identity(logger) if logger is not None else None
    callbacks = getattr(trainer, "callbacks", None)
    if isinstance(callbacks, Sequence):
        config["callbacks"] = [object_identity(callback) for callback in callbacks]
    return config


def build_checkpoint_manifest(
    checkpoint_paths: Iterable[str | Path],
    *,
    include_hashes: bool = True,
) -> dict[str, Any]:
    entries = []
    for raw_path in sorted({str(Path(path).expanduser()) for path in checkpoint_paths if str(path)}):
        path = Path(raw_path)
        exists = path.is_file()
        entry: dict[str, Any] = {
            "path": str(path),
            "exists": exists,
            "size_bytes": path.stat().st_size if exists else None,
        }
        if include_hashes:
            entry["sha256"] = sha256_file(path) if exists else None
        entries.append(entry)
    return {
        "schema": LIGHTNING_CHECKPOINT_SCHEMA,
        "checkpoints": entries,
    }


def write_lightning_evidence(
    output_dir: str | Path,
    *,
    trainer: Any = None,
    pl_module: Any = None,
    run_id: str | None = None,
    run_name: str = "lightning-training",
    status: str = "unknown",
    started_at: str | None = None,
    finished_at: str | None = None,
    metrics: Sequence[Mapping[str, Any]] = (),
    trainer_config: Mapping[str, Any] | None = None,
    exception: str | None = None,
    extra_metadata: Mapping[str, Any] | None = None,
    checkpoint_paths: Sequence[str | Path] = (),
    include_checkpoint_hashes: bool = True,
) -> LightningEvidenceWriteResult:
    output_path = Path(output_dir).expanduser()
    output_path.mkdir(parents=True, exist_ok=True)
    metrics_path = output_path / METRICS_FILENAME
    checkpoint_manifest_path = output_path / CHECKPOINT_MANIFEST_FILENAME
    manifest_path = output_path / MANIFEST_FILENAME

    normalized_metrics = [_json_safe(record) for record in metrics]
    metrics_path.write_text(
        "".join(f"{canonical_json(record)}\n" for record in normalized_metrics),
        encoding="utf-8",
    )

    discovered_checkpoints = tuple(discover_checkpoint_paths(trainer)) + tuple(checkpoint_paths)
    checkpoint_manifest = build_checkpoint_manifest(
        discovered_checkpoints,
        include_hashes=include_checkpoint_hashes,
    )
    checkpoint_manifest_path.write_text(
        f"{canonical_json(checkpoint_manifest)}\n",
        encoding="utf-8",
    )

    manifest = build_lightning_evidence_manifest(
        output_path,
        run_id=run_id or f"lightning-{uuid.uuid4().hex[:12]}",
        run_name=run_name,
        status=status,
        started_at=started_at or utc_now(),
        finished_at=finished_at or utc_now(),
        metrics=normalized_metrics,
        trainer=trainer,
        pl_module=pl_module,
        trainer_config=trainer_config,
        checkpoint_manifest=checkpoint_manifest,
        exception=exception,
        extra_metadata=extra_metadata,
    )
    manifest_path.write_text(f"{canonical_json(manifest)}\n", encoding="utf-8")
    return LightningEvidenceWriteResult(
        output_dir=output_path,
        manifest_path=manifest_path,
        metrics_path=metrics_path,
        checkpoint_manifest_path=checkpoint_manifest_path,
        manifest=manifest,
    )


def build_lightning_evidence_manifest(
    output_dir: str | Path,
    *,
    run_id: str,
    run_name: str,
    status: str,
    started_at: str,
    finished_at: str,
    metrics: Sequence[Mapping[str, Any]],
    trainer: Any = None,
    pl_module: Any = None,
    trainer_config: Mapping[str, Any] | None = None,
    checkpoint_manifest: Mapping[str, Any] | None = None,
    exception: str | None = None,
    extra_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    output_path = Path(output_dir).expanduser()
    artifacts = [
        _artifact_entry(output_path / METRICS_FILENAME),
        _artifact_entry(output_path / CHECKPOINT_MANIFEST_FILENAME),
    ]
    return {
        "schema": LIGHTNING_EVIDENCE_SCHEMA,
        "run_id": run_id,
        "run_name": run_name,
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": _duration_seconds(started_at, finished_at),
        "model": object_identity(pl_module),
        "model_hparams": _json_safe(_hparams(pl_module)),
        "datamodule": object_identity(getattr(trainer, "datamodule", None)) if trainer is not None else None,
        "datamodule_hparams": _json_safe(_hparams(getattr(trainer, "datamodule", None)) if trainer is not None else {}),
        "trainer": _json_safe(trainer_config if trainer_config is not None else collect_trainer_config(trainer)),
        "metrics": {
            "event_count": len(metrics),
            "latest": dict(metrics[-1]) if metrics else {},
        },
        "checkpoints": dict(checkpoint_manifest or {"schema": LIGHTNING_CHECKPOINT_SCHEMA, "checkpoints": []}),
        "runtime": runtime_metadata(),
        "artifacts": artifacts,
        "exception": exception,
        "metadata": _json_safe(dict(extra_metadata or {})),
    }


def discover_checkpoint_paths(trainer: Any) -> tuple[Path, ...]:
    if trainer is None:
        return ()
    paths: list[Path] = []
    checkpoint_callbacks = []
    primary = getattr(trainer, "checkpoint_callback", None)
    if primary is not None:
        checkpoint_callbacks.append(primary)
    callbacks = getattr(trainer, "callbacks", None)
    if isinstance(callbacks, Sequence):
        checkpoint_callbacks.extend(callbacks)
    for callback in checkpoint_callbacks:
        for attr in ("best_model_path", "last_model_path"):
            value = getattr(callback, attr, None)
            if value:
                paths.append(Path(str(value)).expanduser())
        best_k_models = getattr(callback, "best_k_models", None)
        if isinstance(best_k_models, Mapping):
            paths.extend(Path(str(path)).expanduser() for path in best_k_models.keys() if str(path))
    return tuple(dict.fromkeys(paths))


def verify_lightning_evidence(output_dir: str | Path) -> dict[str, Any]:
    output_path = Path(output_dir).expanduser()
    manifest_path = output_path / MANIFEST_FILENAME
    checks: list[dict[str, Any]] = []
    manifest: dict[str, Any] = {}
    checks.append(_check("manifest_exists", manifest_path.is_file(), f"{manifest_path} exists"))
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            checks.append(
                _check(
                    "manifest_schema_supported",
                    manifest.get("schema") == LIGHTNING_EVIDENCE_SCHEMA,
                    "Lightning evidence schema is supported.",
                    expected=LIGHTNING_EVIDENCE_SCHEMA,
                    actual=manifest.get("schema"),
                )
            )
        except Exception as exc:
            checks.append(_check("manifest_schema_supported", False, f"Manifest is invalid JSON: {exc}"))
    artifact_checks = [_verify_artifact(artifact) for artifact in manifest.get("artifacts", [])]
    checks.extend(artifact_checks)
    checkpoint_checks = _verify_checkpoint_hashes(manifest)
    checks.extend(checkpoint_checks)
    status = "pass" if checks and all(check["status"] == "pass" for check in checks) else "fail"
    return {
        "schema": LIGHTNING_VERIFY_SCHEMA,
        "status": status,
        "manifest_path": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path) if manifest_path.is_file() else "",
        "checks": checks,
    }


def runtime_metadata() -> dict[str, Any]:
    packages = {}
    for package in ("lightning", "pytorch-lightning", "torch"):
        try:
            packages[package] = importlib_metadata.version(package)
        except importlib_metadata.PackageNotFoundError:
            packages[package] = None
    return {
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "packages": packages,
    }


def object_identity(value: Any) -> str | None:
    if value is None:
        return None
    cls = value if isinstance(value, type) else type(value)
    module = getattr(cls, "__module__", "")
    name = getattr(cls, "__qualname__", getattr(cls, "__name__", ""))
    return ".".join(part for part in (module, name) if part)


def canonical_json(payload: Mapping[str, Any] | Sequence[Any]) -> str:
    return json.dumps(_json_safe(payload), ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _artifact_entry(path: Path) -> dict[str, Any]:
    exists = path.is_file()
    return {
        "path": str(path),
        "exists": exists,
        "size_bytes": path.stat().st_size if exists else None,
        "sha256": sha256_file(path) if exists else None,
    }


def _verify_artifact(artifact: Mapping[str, Any]) -> dict[str, Any]:
    path = Path(str(artifact.get("path", ""))).expanduser()
    expected_hash = artifact.get("sha256")
    exists = path.is_file()
    actual_hash = sha256_file(path) if exists else None
    return _check(
        f"artifact:{path.name or 'missing'}",
        exists and (not expected_hash or actual_hash == expected_hash),
        f"{path} exists and matches its recorded hash."
        if exists and (not expected_hash or actual_hash == expected_hash)
        else f"{path} is missing or changed.",
        path=str(path),
        expected_sha256=expected_hash,
        actual_sha256=actual_hash,
    )


def _verify_checkpoint_hashes(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    checkpoints = dict(manifest.get("checkpoints", {})).get("checkpoints", [])
    if not isinstance(checkpoints, list):
        return [_check("checkpoints_shape", False, "Checkpoint manifest is not a list.")]
    checks = []
    for index, checkpoint in enumerate(checkpoints):
        if not isinstance(checkpoint, Mapping):
            checks.append(_check(f"checkpoint:{index}", False, "Checkpoint entry is invalid."))
            continue
        path = Path(str(checkpoint.get("path", ""))).expanduser()
        expected_hash = checkpoint.get("sha256")
        exists = path.is_file()
        actual_hash = sha256_file(path) if exists and expected_hash else None
        ok = exists if expected_hash is None else exists and actual_hash == expected_hash
        checks.append(
            _check(
                f"checkpoint:{path.name or index}",
                ok,
                f"{path} exists and matches its recorded hash." if ok else f"{path} is missing or changed.",
                path=str(path),
                expected_sha256=expected_hash,
                actual_sha256=actual_hash,
            )
        )
    return checks


def _check(check_id: str, ok: bool, summary: str, **details: Any) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": "pass" if ok else "fail",
        "summary": summary,
        "details": _json_safe(details),
    }


def _hparams(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    for attr in ("hparams_initial", "hparams"):
        payload = getattr(value, attr, None)
        if isinstance(payload, Mapping):
            return dict(payload)
        if payload is not None and hasattr(payload, "__dict__"):
            return dict(vars(payload))
    return {}


def _duration_seconds(started_at: str, finished_at: str) -> float | None:
    try:
        started = _parse_utc(started_at)
        finished = _parse_utc(finished_at)
    except ValueError:
        return None
    return max(0.0, (finished - started).total_seconds())


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            return None
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, set):
        return [_json_safe(item) for item in sorted(value, key=str)]
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _json_safe(item())
        except Exception:
            pass
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        try:
            return _json_safe(tolist())
        except Exception:
            pass
    detach = getattr(value, "detach", None)
    if callable(detach):
        try:
            detached = detach()
            cpu = getattr(detached, "cpu", None)
            if callable(cpu):
                detached = cpu()
            return _json_safe(detached)
        except Exception:
            pass
    if hasattr(value, "__dict__") and not isinstance(value, type):
        return object_identity(value)
    return str(value)
