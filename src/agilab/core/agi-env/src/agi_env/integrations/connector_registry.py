# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Shared connector path registry for AGILAB apps and pages."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


def _clean_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Path):
        return str(value)
    text = str(value).strip()
    return text or None


def _mapping_get(mapping: Any, key: str) -> Any:
    if isinstance(mapping, Mapping):
        return mapping.get(key)
    getter = getattr(mapping, "get", None)
    if callable(getter):
        return getter(key)
    return None


def _instance_attr(env: Any, attr_name: str) -> Any:
    try:
        return vars(env).get(attr_name)
    except TypeError:
        return getattr(env, attr_name, None)


def _env_home(env: Any, home_path: Path | None = None) -> Path:
    if home_path is not None:
        return home_path.expanduser()
    raw_home = _clean_value(_instance_attr(env, "home_abs"))
    return Path(raw_home).expanduser() if raw_home else Path.home()


def _resolve_path(value: Any, *, home_path: Path) -> Path:
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        return (home_path / path).resolve()
    return path


def _path_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


@dataclass(frozen=True)
class ConnectorPath:
    """A named AGILAB path root or derived artifact path."""

    id: str
    label: str
    path: Path
    kind: str
    source: str
    env_key: str | None = None
    description: str = ""

    @property
    def exists(self) -> bool:
        return _path_exists(self.path)

    def as_row(self) -> dict[str, Any]:
        return {
            "connector_id": self.id,
            "label": self.label,
            "kind": self.kind,
            "path": str(self.path),
            "exists": self.exists,
            "source": self.source,
            "env_key": self.env_key or "",
            "description": self.description,
        }


@dataclass(frozen=True)
class ConnectorPathRegistry:
    """Resolved connector paths for one app/page launch context."""

    paths: tuple[ConnectorPath, ...]

    def get(self, connector_id: str) -> ConnectorPath | None:
        return next((path for path in self.paths if path.id == connector_id), None)

    def require(self, connector_id: str) -> ConnectorPath:
        connector = self.get(connector_id)
        if connector is None:
            raise KeyError(f"Unknown connector path id: {connector_id}")
        return connector

    def path(self, connector_id: str) -> Path:
        return self.require(connector_id).path

    def portable_label(self, path: Path | str) -> str:
        target = Path(path).expanduser()
        matches: list[ConnectorPath] = []
        for connector in self.paths:
            try:
                if target == connector.path or target.is_relative_to(connector.path):
                    matches.append(connector)
            except (OSError, RuntimeError, ValueError):
                continue
        if not matches:
            return str(target)

        best = max(matches, key=lambda connector: len(connector.path.parts))
        relative = target.relative_to(best.path)
        suffix = "." if str(relative) == "." else relative.as_posix()
        return f"{best.id}://{suffix}"

    def as_rows(self) -> list[dict[str, Any]]:
        return [
            {
                **connector.as_row(),
                "portable_path": self.portable_label(connector.path),
            }
            for connector in self.paths
        ]

    def summary(self) -> dict[str, Any]:
        return {
            "connector_count": len(self.paths),
            "paths": {connector.id: str(connector.path) for connector in self.paths},
            "missing_connector_ids": [
                connector.id for connector in self.paths if not connector.exists
            ],
        }


def resolve_connector_root(
    env: Any,
    *,
    connector_id: str,
    label: str,
    attr_name: str,
    env_key: str,
    default_child: str,
    home_path: Path | None = None,
    ensure: bool = False,
    prefer_attr: bool = True,
    description: str = "",
) -> ConnectorPath:
    """Resolve one canonical root from env attr, env config, process env, or home default."""

    home = _env_home(env, home_path)
    envars = _instance_attr(env, "envars") or {}
    candidates = [
        (f"envars:{env_key}", _mapping_get(envars, env_key)),
        (f"os.environ:{env_key}", os.environ.get(env_key)),
        (f"default:~/{default_child}", home / default_child),
    ]
    if prefer_attr:
        candidates.insert(0, (f"attr:{attr_name}", _instance_attr(env, attr_name)))
    for source, raw_value in candidates:
        value = _clean_value(raw_value)
        if value:
            path = _resolve_path(value, home_path=home)
            if ensure:
                path.mkdir(parents=True, exist_ok=True)
            return ConnectorPath(
                id=connector_id,
                label=label,
                path=path,
                kind="root",
                source=source,
                env_key=env_key,
                description=description,
            )
    raise RuntimeError(f"Unable to resolve connector root {connector_id!r}")


def _connector_child(
    parent: ConnectorPath,
    *,
    connector_id: str,
    label: str,
    relative_path: str | Path,
    kind: str,
    ensure: bool = False,
    description: str = "",
) -> ConnectorPath:
    path = parent.path / relative_path
    if ensure:
        path.mkdir(parents=True, exist_ok=True)
    return ConnectorPath(
        id=connector_id,
        label=label,
        path=path,
        kind=kind,
        source=f"derived:{parent.id}",
        description=description,
    )


def build_connector_path_registry(
    env: Any,
    *,
    target: str | None = None,
    first_proof_target: str = "flight",
    run_manifest_filename: str = "run_manifest.json",
    ensure_roots: bool = False,
) -> ConnectorPathRegistry:
    """Build the portable path registry shared by AGILAB pages and apps."""

    app_target = str(target or _instance_attr(env, "target") or "").strip()
    home = _env_home(env)
    export_root = resolve_connector_root(
        env,
        connector_id="export_root",
        label="Export root",
        attr_name="AGILAB_EXPORT_ABS",
        env_key="AGI_EXPORT_DIR",
        default_child="export",
        home_path=home,
        ensure=ensure_roots,
        description="Root for app and page output artifacts.",
    )
    log_root = resolve_connector_root(
        env,
        connector_id="log_root",
        label="Log root",
        attr_name="AGILAB_LOG_ABS",
        env_key="AGI_LOG_DIR",
        default_child="log",
        home_path=home,
        ensure=ensure_roots,
        description="Root for execution logs and run manifests.",
    )

    paths: list[ConnectorPath] = [export_root, log_root]
    if app_target:
        paths.append(
            _connector_child(
                export_root,
                connector_id="artifact_root",
                label="App artifact root",
                relative_path=app_target,
                kind="artifact_root",
                ensure=False,
                description="Default artifact directory for the active app target.",
            )
        )
        paths.append(
            _connector_child(
                log_root,
                connector_id="execute_log_root",
                label="App execute log root",
                relative_path=Path("execute") / app_target,
                kind="log_root",
                ensure=ensure_roots,
                description="Default execution log directory for the active app target.",
            )
        )

    first_proof_root = _connector_child(
        log_root,
        connector_id="first_proof_log_root",
        label="First-proof log root",
        relative_path=Path("execute") / first_proof_target,
        kind="log_root",
        ensure=ensure_roots,
        description="Stable source-checkout first-proof manifest directory.",
    )
    paths.append(first_proof_root)
    paths.append(
        ConnectorPath(
            id="first_proof_manifest",
            label="First-proof run manifest",
            path=first_proof_root.path / run_manifest_filename,
            kind="manifest",
            source="derived:first_proof_log_root",
            description="Stable first-proof run_manifest.json evidence file.",
        )
    )

    pages_root_value = _clean_value(_instance_attr(env, "AGILAB_PAGES_ABS"))
    if pages_root_value:
        paths.append(
            ConnectorPath(
                id="pages_root",
                label="Apps-pages root",
                path=_resolve_path(pages_root_value, home_path=home),
                kind="root",
                source="attr:AGILAB_PAGES_ABS",
                env_key="AGI_PAGES_DIR",
                description="Root used by the Analysis launcher for page bundles.",
            )
        )

    return ConnectorPathRegistry(tuple(paths))


__all__ = [
    "ConnectorPath",
    "ConnectorPathRegistry",
    "build_connector_path_registry",
    "resolve_connector_root",
]
