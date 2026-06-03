from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import importlib.util
import json
from pathlib import Path
from typing import Any, Protocol, Sequence


CONFIG_PATH = (
    Path(__file__).resolve().parents[2]
    / "apps"
    / "builtin"
    / "weather_forecast_project"
    / "tracking_templates"
    / "mlflow_auto_tracking_run_config.json"
)
DEFAULT_OUTPUT_DIR = Path.home() / "log" / "execute" / "mlflow_auto_tracking"


class Tracker(Protocol):
    status: str
    reason: str
    backend: str
    run_id: str | None

    def log_param(self, key: str, value: Any) -> None: ...

    def log_metric(self, key: str, value: float) -> None: ...

    def log_artifact(self, path: Path) -> None: ...

    def finish(self) -> None: ...

    def as_dict(self) -> dict[str, Any]: ...


@dataclass
class TrackingEvent:
    action: str
    key: str
    value: Any


@dataclass
class NullTracker:
    status: str = "skipped"
    reason: str = "MLflow is not installed; local evidence was written only."
    backend: str = "none"
    run_id: str | None = None
    events: list[TrackingEvent] = field(default_factory=list)

    def log_param(self, key: str, value: Any) -> None:
        self.events.append(TrackingEvent("log_param", key, value))

    def log_metric(self, key: str, value: float) -> None:
        self.events.append(TrackingEvent("log_metric", key, value))

    def log_artifact(self, path: Path) -> None:
        self.events.append(TrackingEvent("log_artifact", "path", str(path)))

    def finish(self) -> None:
        return None

    def as_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "status": self.status,
            "reason": self.reason,
            "run_id": self.run_id,
            "events": [event.__dict__ for event in self.events],
        }


class MlflowTracker:
    def __init__(
        self,
        *,
        mlflow_module: Any,
        experiment_name: str,
        run_name: str,
        tracking_uri: str | None,
    ) -> None:
        self._mlflow = mlflow_module
        self.backend = "mlflow"
        self.status = "logged"
        self.reason = "ok"
        self.events: list[TrackingEvent] = []
        if tracking_uri:
            self._mlflow.set_tracking_uri(_expand_file_uri(tracking_uri))
        self._mlflow.set_experiment(experiment_name)
        self._run = self._mlflow.start_run(run_name=run_name)
        self.run_id = getattr(getattr(self._run, "info", None), "run_id", None)

    def log_param(self, key: str, value: Any) -> None:
        self._mlflow.log_param(key, value)
        self.events.append(TrackingEvent("log_param", key, value))

    def log_metric(self, key: str, value: float) -> None:
        self._mlflow.log_metric(key, float(value))
        self.events.append(TrackingEvent("log_metric", key, float(value)))

    def log_artifact(self, path: Path) -> None:
        self._mlflow.log_artifact(str(path))
        self.events.append(TrackingEvent("log_artifact", "path", str(path)))

    def finish(self) -> None:
        self._mlflow.end_run()

    def as_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "status": self.status,
            "reason": self.reason,
            "run_id": self.run_id,
            "events": [event.__dict__ for event in self.events],
        }


def _expand_file_uri(uri: str) -> str:
    if not uri.startswith("file:"):
        return uri
    path = Path(uri.removeprefix("file:")).expanduser()
    return f"file:{path}"


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    with path.expanduser().open("r", encoding="utf-8") as stream:
        config = json.load(stream)
    if not isinstance(config, dict):
        raise SystemExit(f"Run config must be a JSON object: {path}")
    return config


def build_demo_evidence(config: dict[str, Any], *, output_dir: Path) -> dict[str, Any]:
    params = dict(config.get("params") or {})
    metrics = {key: float(value) for key, value in dict(config.get("metrics") or {}).items()}
    artifact_name = str((config.get("artifacts") or {}).get("summary_name") or "run_summary.json")
    artifact_dir = output_dir.expanduser() / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    summary_path = artifact_dir / artifact_name
    summary = {
        "schema": "agilab.example.mlflow_auto_tracking.evidence.v1",
        "app": str(config.get("app") or "unknown"),
        "pipeline": str(config.get("pipeline") or "unknown"),
        "params": params,
        "metrics": metrics,
        "artifact_role": "local evidence bundle before optional MLflow logging",
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return {
        "params": params,
        "metrics": metrics,
        "artifact_path": summary_path,
        "summary": summary,
    }


def create_tracker(
    *,
    backend: str,
    experiment_name: str,
    run_name: str,
    tracking_uri: str | None,
    require_mlflow: bool = False,
) -> Tracker:
    normalized = backend.strip().lower()
    if normalized in {"none", "noop", "local"}:
        return NullTracker(reason="Tracking backend disabled; local evidence was written only.")
    if normalized not in {"auto", "mlflow"}:
        raise SystemExit(f"Unsupported tracking backend: {backend!r}. Use auto, mlflow, or none.")

    if importlib.util.find_spec("mlflow") is None:
        if require_mlflow or normalized == "mlflow":
            raise SystemExit(
                "MLflow backend requested but the `mlflow` package is not installed. "
                "Run with `uv --preview-features extra-build-dependencies run --with mlflow ...`."
            )
        return NullTracker()

    try:
        import mlflow  # type: ignore[import-not-found]

        return MlflowTracker(
            mlflow_module=mlflow,
            experiment_name=experiment_name,
            run_name=run_name,
            tracking_uri=tracking_uri,
        )
    except Exception as exc:  # pragma: no cover - depends on local MLflow installation
        if require_mlflow:
            raise SystemExit(f"MLflow tracking failed: {exc}") from exc
        return NullTracker(status="failed", reason=f"MLflow tracking failed: {exc}")


def run_preview(
    *,
    config_path: Path = CONFIG_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    backend: str = "auto",
    tracking_uri: str | None = None,
    require_mlflow: bool = False,
) -> dict[str, Any]:
    config = load_config(config_path)
    output_dir = output_dir.expanduser()
    evidence = build_demo_evidence(config, output_dir=output_dir)
    tracker = create_tracker(
        backend=backend,
        experiment_name=str(config.get("experiment_name") or "AGILAB Preview"),
        run_name=str(config.get("run_name") or "agilab_preview"),
        tracking_uri=tracking_uri if tracking_uri is not None else config.get("tracking_uri"),
        require_mlflow=require_mlflow,
    )

    try:
        for key, value in evidence["params"].items():
            tracker.log_param(key, value)
        for key, value in evidence["metrics"].items():
            tracker.log_metric(key, value)
        tracker.log_artifact(evidence["artifact_path"])
    finally:
        tracker.finish()

    preview = {
        "example": "mlflow_auto_tracking",
        "goal": "Show AGILAB execution evidence logged through an optional MLflow-backed tracker.",
        "tracker_backend": tracker.backend,
        "tracking": tracker.as_dict(),
        "logged_params": sorted(evidence["params"]),
        "logged_metrics": sorted(evidence["metrics"]),
        "local_evidence": {
            "run_summary": str(evidence["artifact_path"]),
        },
        "registry_created_by_agilab": False,
    }
    preview_path = output_dir / "mlflow_tracking_preview.json"
    preview_path.write_text(json.dumps(preview, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(preview, indent=2, sort_keys=True))
    return preview


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview optional MLflow auto-tracking through an AGILAB tracker abstraction."
    )
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--backend",
        choices=("auto", "mlflow", "none"),
        default="auto",
        help="Tracking backend. auto logs to MLflow when installed, otherwise records skipped.",
    )
    parser.add_argument("--tracking-uri", default=None)
    parser.add_argument(
        "--require-mlflow",
        action="store_true",
        help="Fail instead of recording skipped/failed when MLflow is unavailable.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> dict[str, Any]:
    args = _parse_args(argv)
    return run_preview(
        config_path=args.config,
        output_dir=args.output_dir,
        backend=args.backend,
        tracking_uri=args.tracking_uri,
        require_mlflow=bool(args.require_mlflow),
    )


if __name__ == "__main__":
    main()
