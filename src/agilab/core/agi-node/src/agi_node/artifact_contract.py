from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar


WORKER_ARTIFACT_MANIFEST_SCHEMA = "agilab.worker_artifacts.v1"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _metadata_dict(metadata: dict[str, Any] | None) -> dict[str, Any]:
    return dict(metadata or {})


def _path_text(path: Path | str) -> str:
    return str(path).strip()


class ArtifactContract:
    """Mixin for workers that produce artifacts and scalar metrics.

    The contract is intentionally independent from pandas, polars, DAG execution,
    and Streamlit. It standardizes the evidence a worker can leave behind without
    changing how the worker schedules or executes work.
    """

    artifact_manifest_schema: ClassVar[str] = WORKER_ARTIFACT_MANIFEST_SCHEMA
    default_artifact_manifest_name: ClassVar[str] = "worker_artifacts.json"

    def _artifact_records(self) -> list[dict[str, Any]]:
        records = getattr(self, "_agi_artifacts", None)
        if not isinstance(records, list):
            records = []
            setattr(self, "_agi_artifacts", records)
        return records

    def _metric_records(self) -> list[dict[str, Any]]:
        records = getattr(self, "_agi_metrics", None)
        if not isinstance(records, list):
            records = []
            setattr(self, "_agi_metrics", records)
        return records

    def reset_artifact_contract(self) -> None:
        """Clear pending artifact and metric records for this worker instance."""

        setattr(self, "_agi_artifacts", [])
        setattr(self, "_agi_metrics", [])

    def record_artifact(
        self,
        path: Path | str,
        *,
        kind: str,
        label: str | None = None,
        artifact_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record an artifact path produced by the worker.

        ``path`` can be absolute or relative to the future manifest directory.
        Existence and file size are evaluated when the manifest is built, so the
        method is safe to call before the file is physically created.
        """

        path_value = _path_text(path)
        if not path_value:
            raise ValueError("artifact path must not be empty")
        kind_value = str(kind).strip()
        if not kind_value:
            raise ValueError("artifact kind must not be empty")

        record: dict[str, Any] = {
            "id": str(artifact_id or Path(path_value).stem or "artifact"),
            "kind": kind_value,
            "path": path_value,
        }
        if label:
            record["label"] = str(label)
        if metadata:
            record["metadata"] = _metadata_dict(metadata)

        self._artifact_records().append(record)
        return dict(record)

    def record_metric(
        self,
        name: str,
        value: int | float | str | bool | None,
        *,
        unit: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record a scalar metric produced by the worker."""

        metric_name = str(name).strip()
        if not metric_name:
            raise ValueError("metric name must not be empty")

        record: dict[str, Any] = {"name": metric_name, "value": value}
        if unit:
            record["unit"] = str(unit)
        if metadata:
            record["metadata"] = _metadata_dict(metadata)

        self._metric_records().append(record)
        return dict(record)

    def artifact_manifest(
        self,
        *,
        output_dir: Path | str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a manifest payload from recorded artifacts and metrics."""

        root = self._resolve_artifact_manifest_dir(output_dir)
        artifacts = [
            self._artifact_manifest_record(record, root=root)
            for record in self._artifact_records()
        ]
        worker_id = getattr(self, "worker_id", getattr(self, "_worker_id", None))

        manifest: dict[str, Any] = {
            "schema": self.artifact_manifest_schema,
            "created_at": _utc_now_iso(),
            "worker_class": type(self).__name__,
            "worker_id": worker_id,
            "artifact_count": len(artifacts),
            "metric_count": len(self._metric_records()),
            "artifacts": artifacts,
            "metrics": [dict(record) for record in self._metric_records()],
        }
        if metadata:
            manifest["metadata"] = _metadata_dict(metadata)
        return manifest

    def write_artifact_manifest(
        self,
        output_dir: Path | str | None = None,
        *,
        manifest_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Path:
        """Write the worker artifact manifest and return its path."""

        root = self._resolve_artifact_manifest_dir(output_dir)
        root.mkdir(parents=True, exist_ok=True)
        name = (
            self.default_artifact_manifest_name
            if manifest_name is None
            else str(manifest_name).strip()
        )
        if not name:
            raise ValueError("manifest name must not be empty")
        manifest_path = root / name
        manifest = self.artifact_manifest(output_dir=root, metadata=metadata)
        manifest["manifest_path"] = manifest_path.name
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return manifest_path

    def write_manifest(
        self,
        output_dir: Path | str | None = None,
        *,
        manifest_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Path:
        """Alias for ``write_artifact_manifest`` used by notebook-style flows."""

        return self.write_artifact_manifest(
            output_dir=output_dir,
            manifest_name=manifest_name,
            metadata=metadata,
        )

    def _resolve_artifact_manifest_dir(self, output_dir: Path | str | None) -> Path:
        if output_dir is not None:
            return Path(output_dir).expanduser()

        for attr_name in ("artifact_dir", "data_out", "output_dir"):
            value = getattr(self, attr_name, None)
            if value:
                return Path(value).expanduser()

        args = getattr(self, "args", None)
        for attr_name in ("artifact_dir", "data_out", "output_dir"):
            value = getattr(args, attr_name, None) if args is not None else None
            if value:
                return Path(value).expanduser()
            if hasattr(args, "get"):
                value = args.get(attr_name)
                if value:
                    return Path(value).expanduser()

        return Path.cwd()

    def _artifact_manifest_record(
        self,
        record: dict[str, Any],
        *,
        root: Path,
    ) -> dict[str, Any]:
        manifest_record = dict(record)
        path = Path(str(record["path"])).expanduser()
        resolved = path if path.is_absolute() else root / path
        manifest_record["exists"] = resolved.exists()
        if resolved.is_file():
            manifest_record["size_bytes"] = resolved.stat().st_size
        return manifest_record
