"""Manager-side MLflow registration for shared worker handoffs."""
from __future__ import annotations

import json
import logging
import math
import os
from pathlib import Path
from typing import Any

from agi_env import mlflow_store

logger = logging.getLogger(__name__)
HANDOFF_SCHEMA = "agilab.mlflow.handoff.v1"


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _request_enables_mlflow(value: Any) -> bool:
    if isinstance(value, dict):
        if "mlflow_enabled" in value and _truthy(value.get("mlflow_enabled")):
            return True
        return any(_request_enables_mlflow(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_request_enables_mlflow(item) for item in value)
    return False


def _workflow_root(agi_cls: Any) -> Path | None:
    raw = str(getattr(agi_cls, "_workers_data_path", "") or "").strip()
    if not raw:
        return None
    root = Path(raw).expanduser()
    if not root.is_absolute():
        root = Path(getattr(agi_cls.env, "home_abs", Path.home())) / root
    return root.resolve()


def _safe_relative(root: Path, value: Any) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    resolved = (root / candidate).resolve()
    if not resolved.is_relative_to(root):
        return None
    return resolved


def _numeric_metrics(payload: Any) -> dict[str, float]:
    if not isinstance(payload, dict):
        return {}
    metrics: dict[str, float] = {}
    for key, value in payload.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        numeric = float(value)
        if math.isfinite(numeric):
            metrics[str(key)] = numeric
    return metrics


def _tracking_paths(env: Any) -> tuple[Path, Path, str]:
    tracking_dir = mlflow_store.resolve_mlflow_tracking_dir(env)
    tracking_dir.mkdir(parents=True, exist_ok=True)
    db_path = mlflow_store.resolve_mlflow_backend_db(tracking_dir, default_db_name="mlflow.db")
    artifact_dir = mlflow_store.resolve_mlflow_artifact_dir(
        tracking_dir,
        default_artifact_dir="artifacts",
    )
    tracking_uri = mlflow_store.sqlite_uri_for_path(
        db_path,
        os_name=os.name,
    )
    return db_path, artifact_dir, tracking_uri


def _register_handoff(path: Path, *, env: Any, mlflow: Any, log: Any) -> dict[str, Any]:
    root = path.parent.resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != HANDOFF_SCHEMA:
        return {"status": "skipped", "reason": "unsupported_schema"}
    handoff_key = str(payload.get("handoff_key") or "").strip()
    if not handoff_key:
        return {"status": "skipped", "reason": "missing_handoff_key"}

    marker = root / "mlflow_manager_registration.json"
    if marker.exists():
        try:
            previous = json.loads(marker.read_text(encoding="utf-8"))
            if previous.get("status") == "logged" and previous.get("handoff_key") == handoff_key:
                return {"status": "skipped", "reason": "already_logged", "run_id": previous.get("run_id")}
        except (OSError, TypeError, ValueError):
            pass

    _db_path, artifact_dir, tracking_uri = _tracking_paths(env)
    previous_uri = mlflow.get_tracking_uri()
    try:
        mlflow.set_tracking_uri(tracking_uri)
        experiment_name = str(payload.get("experiment") or "AGILAB SB3 Trainer")
        experiment = mlflow.get_experiment_by_name(experiment_name)
        if experiment is None:
            experiment_id = mlflow.create_experiment(
                experiment_name,
                artifact_location=artifact_dir.as_uri(),
            )
        else:
            experiment_id = experiment.experiment_id
        mlflow.set_experiment(experiment_name)

        existing = mlflow.search_runs(
            experiment_ids=[str(experiment_id)],
            filter_string=f"tags.`agilab.handoff_key` = '{handoff_key}'",
        )
        if not existing.empty:
            run_id = str(existing.iloc[0]["run_id"])
            status = {"status": "skipped", "reason": "already_logged", "run_id": run_id}
        else:
            params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
            metrics = _numeric_metrics(payload.get("metrics"))
            with mlflow.start_run(run_name=str(payload.get("run_name") or payload.get("trainer_name") or "worker")) as run:
                mlflow.set_tags(
                    {
                        "agilab.handoff_key": handoff_key,
                        "agilab.trainer_name": str(payload.get("trainer_name") or ""),
                        "agilab.registration": "manager",
                    }
                )
                for key, value in params.items():
                    mlflow.log_param(str(key), value)
                for key, value in metrics.items():
                    mlflow.log_metric(key, value)
                mlflow.log_artifact(str(path))
                for value in payload.get("artifacts", []):
                    artifact = _safe_relative(root, value)
                    if artifact is None or not artifact.is_file():
                        log.warning("Skipping invalid MLflow handoff artifact %r from %s", value, path)
                        continue
                    mlflow.log_artifact(str(artifact))
                run_id = run.info.run_id
            status = {"status": "logged", "run_id": run_id}
    finally:
        mlflow.set_tracking_uri(previous_uri)

    marker_payload = {
        "schema": HANDOFF_SCHEMA,
        "handoff_key": handoff_key,
        "tracking_uri": tracking_uri,
        **status,
    }
    marker.write_text(json.dumps(marker_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return status


def register_shared_mlflow_handoffs(agi_cls: Any, *, log: Any = logger) -> list[dict[str, Any]]:
    """Register completed worker handoffs in the manager's local MLflow store."""

    if not _request_enables_mlflow(getattr(agi_cls, "_args", None)):
        return []
    root = _workflow_root(agi_cls)
    if root is None or not root.is_dir():
        return []
    handoff_paths: list[Path] = []
    for path in sorted(root.rglob("mlflow_handoff.json")):
        try:
            resolved = path.resolve()
        except OSError as exc:
            log.warning("Failed to resolve MLflow handoff %s: %s", path, exc)
            continue
        if resolved.is_relative_to(root):
            handoff_paths.append(resolved)
    if not handoff_paths:
        return []
    try:
        import mlflow  # type: ignore
    except (ImportError, TypeError):
        log.info("MLflow handoffs present but MLflow is not installed on the manager")
        return []

    results: list[dict[str, Any]] = []
    for path in handoff_paths:
        try:
            results.append(_register_handoff(path, env=agi_cls.env, mlflow=mlflow, log=log))
        except (OSError, TypeError, ValueError, RuntimeError) as exc:
            log.warning("MLflow handoff registration failed for %s: %s", path, exc)
            results.append({"status": "error", "path": str(path), "message": str(exc)})
    return results


__all__ = ["HANDOFF_SCHEMA", "register_shared_mlflow_handoffs"]
