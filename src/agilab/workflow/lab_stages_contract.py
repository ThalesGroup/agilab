"""Pure renderability contract shared by WORKFLOW and static validators."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


LAB_STAGES_META_KEY = "__meta__"
LAB_STAGES_SCHEMA = "agilab.lab_stages.v1"
LAB_STAGES_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class LabStagesMetadataIssue:
    """One shared metadata issue used by runtime and static validation."""

    severity: str
    check_id: str
    message: str


def module_key_from_project(value: str | Path) -> str:
    """Return the module key used by WORKFLOW for an app/project directory."""

    raw = str(value).strip().replace("\\", "/").rstrip("/")
    name = raw.rsplit("/", 1)[-1] if raw else ""
    return name.removesuffix("_project")


def lab_stages_metadata_issues(
    payload: Mapping[str, Any],
    *,
    require_metadata: bool = False,
) -> tuple[LabStagesMetadataIssue, ...]:
    """Return metadata issues under the single persisted-stage contract."""

    meta = payload.get(LAB_STAGES_META_KEY, {})
    if meta in ({}, None):
        return (
            LabStagesMetadataIssue(
                "error" if require_metadata else "info",
                "metadata-missing",
                "lab_stages.toml has no __meta__ schema block; treating it as a legacy-compatible contract.",
            ),
        )
    if not isinstance(meta, Mapping):
        return (
            LabStagesMetadataIssue(
                "error",
                "metadata-shape",
                "lab_stages.toml __meta__ must be a TOML table.",
            ),
        )

    issues: list[LabStagesMetadataIssue] = []
    schema = str(meta.get("schema", "") or "")
    if require_metadata and not schema:
        issues.append(
            LabStagesMetadataIssue(
                "error",
                "metadata-schema",
                "lab_stages.toml metadata must declare its schema.",
            )
        )
    elif schema and schema != LAB_STAGES_SCHEMA:
        issues.append(
            LabStagesMetadataIssue(
                "error",
                "metadata-schema",
                f"Unsupported lab_stages.toml schema {schema!r}.",
            )
        )

    raw_version = meta.get("version")
    if require_metadata and raw_version in (None, ""):
        issues.append(
            LabStagesMetadataIssue(
                "error",
                "metadata-version",
                "lab_stages.toml metadata must declare its schema version.",
            )
        )
    elif raw_version not in (None, ""):
        if isinstance(raw_version, bool) or not isinstance(raw_version, int):
            issues.append(
                LabStagesMetadataIssue(
                    "error",
                    "metadata-version",
                    f"Unsupported lab_stages.toml schema version {raw_version!r}.",
                )
            )
        else:
            version = raw_version
            if version < 1 or version > LAB_STAGES_SCHEMA_VERSION:
                issues.append(
                    LabStagesMetadataIssue(
                        "error",
                        "metadata-version",
                        (
                            f"Unsupported lab_stages.toml schema version {version}; "
                            "upgrade AGILAB before editing this pipeline."
                        ),
                    )
                )
    return tuple(issues)


def ensure_lab_stages_metadata(data: dict[str, Any]) -> dict[str, Any]:
    """Stamp legacy-compatible data with the current persisted-stage contract."""

    meta = data.get(LAB_STAGES_META_KEY)
    if not isinstance(meta, dict):
        meta = {}
        data[LAB_STAGES_META_KEY] = meta
    if not str(meta.get("schema", "") or "").strip():
        meta["schema"] = LAB_STAGES_SCHEMA
    if meta.get("version") in (None, ""):
        meta["version"] = LAB_STAGES_SCHEMA_VERSION
    return data


def is_displayable_stage(entry: Any) -> bool:
    """Return whether WORKFLOW keeps and renders a persisted stage entry."""

    if not isinstance(entry, Mapping) or not entry:
        return False
    return any(
        isinstance(entry.get(field), str) and bool(str(entry[field]).strip())
        for field in ("Q", "C")
    )


def displayable_stage_rows(
    payload: Mapping[str, Any],
    module_key: str,
) -> list[tuple[str, int, Mapping[str, Any]]]:
    """Return exactly the stage rows WORKFLOW renders for ``module_key``."""

    entries = payload.get(module_key)
    if not isinstance(entries, list):
        return []
    return [
        (module_key, index, entry)
        for index, entry in enumerate(entries)
        if is_displayable_stage(entry)
    ]
