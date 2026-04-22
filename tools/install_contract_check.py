#!/usr/bin/env python3
"""Check AGILAB installer manifest contracts for a given app and copied worker."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from packaging.requirements import InvalidRequirement, Requirement


REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_PACKAGE_NAMES = {"agi-env", "agi-node", "agi-cluster", "agi-core", "agilab"}
SAFE_STATUS = "safe"
APP_LOCAL_STATUS = "app-local-issue"
SHARED_CORE_STATUS = "shared-core-installer-issue"


@dataclass
class DependencySpec:
    name: str
    raw: str
    exact_pin: bool
    specifier: str


@dataclass
class ManifestSnapshot:
    path: str
    name: str | None
    dependencies: dict[str, DependencySpec]
    uv_sources: dict[str, str]


@dataclass
class Finding:
    key: str
    severity: str
    category: str
    summary: str
    details: list[str] = field(default_factory=list)


@dataclass
class ContractReport:
    status: str
    app_path: str
    manager_manifest: str | None
    worker_source_manifest: str | None
    worker_copy_manifest: str | None
    findings: list[Finding]
    recommended_commands: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "app_path": self.app_path,
            "manager_manifest": self.manager_manifest,
            "worker_source_manifest": self.worker_source_manifest,
            "worker_copy_manifest": self.worker_copy_manifest,
            "findings": [asdict(finding) for finding in self.findings],
            "recommended_commands": self.recommended_commands,
        }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare source app/worker manifests with a copied worker project and "
            "flag installer contract drift that often causes AGILAB install failures."
        )
    )
    parser.add_argument(
        "--app-path",
        required=True,
        help="Path to the AGILAB app project root or its pyproject.toml.",
    )
    parser.add_argument(
        "--worker-copy",
        help=(
            "Path to the copied worker project root or pyproject.toml. "
            "If omitted, the tool tries to infer a likely ~/wenv/... location."
        ),
    )
    parser.add_argument(
        "--worker-source",
        help=(
            "Path to the source worker project root or pyproject.toml. "
            "If omitted, the tool looks for a unique src/*_worker/pyproject.toml under the app."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of the human summary.",
    )
    return parser


def _normalize_project_path(raw_path: str | Path) -> Path:
    path = Path(raw_path).expanduser()
    if path.name == "pyproject.toml":
        return path.resolve(strict=False)
    return (path / "pyproject.toml").resolve(strict=False)


def _find_worker_source_manifest(app_root: Path) -> tuple[Path | None, str | None]:
    candidates = sorted(app_root.glob("src/*_worker/pyproject.toml"))
    if not candidates:
        return None, "No source worker pyproject was found under src/*_worker/pyproject.toml."
    if len(candidates) > 1:
        joined = ", ".join(str(path) for path in candidates)
        return None, f"Multiple source worker pyprojects were found; pass --worker-source explicitly: {joined}"
    return candidates[0].resolve(strict=False), None


def _infer_worker_copy_manifest(app_root: Path) -> Path | None:
    candidates: list[Path] = []
    home_wenv = Path.home() / "wenv"
    app_name = app_root.name
    if app_name.endswith("_project"):
        worker_name = app_name[:-8] + "_worker"
    else:
        worker_name = app_name + "_worker"
    candidates.append(home_wenv / worker_name / "pyproject.toml")

    parts = app_root.resolve(strict=False).parts
    try:
        apps_index = parts.index("apps")
    except ValueError:
        apps_index = -1
    if apps_index >= 0 and apps_index + 1 < len(parts):
        relative_parts = list(parts[apps_index + 1 :])
        if relative_parts:
            relative_parts[-1] = worker_name
            candidates.append((home_wenv / Path(*relative_parts) / "pyproject.toml").resolve(strict=False))

    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve(strict=False)
    return candidates[0].resolve(strict=False) if candidates else None


def _load_manifest(path: Path) -> ManifestSnapshot:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    project = data.get("project") or {}
    dependencies = _parse_dependencies(project.get("dependencies") or [])
    uv_sources = _parse_uv_sources(data)
    return ManifestSnapshot(
        path=str(path),
        name=project.get("name"),
        dependencies=dependencies,
        uv_sources=uv_sources,
    )


def _parse_dependencies(raw_dependencies: Any) -> dict[str, DependencySpec]:
    parsed: dict[str, DependencySpec] = {}
    if not isinstance(raw_dependencies, list):
        return parsed
    for entry in raw_dependencies:
        if not isinstance(entry, str):
            continue
        requirement = Requirement(entry)
        parsed[requirement.name] = DependencySpec(
            name=requirement.name,
            raw=entry,
            exact_pin=_is_exact_pin(requirement),
            specifier=str(requirement.specifier),
        )
    return parsed


def _is_exact_pin(requirement: Requirement) -> bool:
    return any(spec.operator == "==" for spec in requirement.specifier)


def _parse_uv_sources(data: dict[str, Any]) -> dict[str, str]:
    sources = ((data.get("tool") or {}).get("uv") or {}).get("sources") or {}
    if not isinstance(sources, dict):
        return {}
    parsed: dict[str, str] = {}
    for name, meta in sources.items():
        if isinstance(meta, dict):
            path_value = meta.get("path")
            if isinstance(path_value, str) and path_value.strip():
                parsed[str(name)] = path_value
    return parsed


def _resolve_uv_source_path(pyproject_path: Path, raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path.resolve(strict=False)
    return (pyproject_path.parent / path).resolve(strict=False)


def _is_repo_app(app_root: Path) -> bool:
    try:
        app_root.resolve(strict=False).relative_to(REPO_ROOT)
        return True
    except ValueError:
        return False


def _checkout_core_project_paths() -> dict[str, Path]:
    src_root = REPO_ROOT / "src" / "agilab"
    return {
        "agi-env": src_root / "core" / "agi-env",
        "agi-node": src_root / "core" / "agi-node",
        "agi-core": src_root / "core" / "agi-core",
        "agi-cluster": src_root / "core" / "agi-cluster",
        "agilab": REPO_ROOT,
    }


def analyze_contract(
    *,
    app_path: str | Path,
    worker_copy: str | Path | None = None,
    worker_source: str | Path | None = None,
) -> ContractReport:
    app_root = Path(app_path).expanduser()
    if app_root.name == "pyproject.toml":
        app_root = app_root.parent
    app_root = app_root.resolve(strict=False)
    manager_manifest = _normalize_project_path(app_root)

    findings: list[Finding] = []
    manager_snapshot: ManifestSnapshot | None = None
    worker_source_snapshot: ManifestSnapshot | None = None
    worker_copy_snapshot: ManifestSnapshot | None = None

    if not manager_manifest.exists():
        findings.append(
            Finding(
                key="missing-manager-manifest",
                severity="error",
                category=APP_LOCAL_STATUS,
                summary="Manager pyproject.toml is missing for the selected app.",
                details=[str(manager_manifest)],
            )
        )
    else:
        try:
            manager_snapshot = _load_manifest(manager_manifest)
        except (tomllib.TOMLDecodeError, InvalidRequirement, OSError, UnicodeDecodeError) as exc:
            findings.append(
                Finding(
                    key="invalid-manager-manifest",
                    severity="error",
                    category=APP_LOCAL_STATUS,
                    summary=f"Manager pyproject.toml could not be parsed: {exc}",
                    details=[str(manager_manifest)],
                )
            )

    if worker_source is None:
        worker_source_manifest, worker_source_error = _find_worker_source_manifest(app_root)
        if worker_source_error:
            findings.append(
                Finding(
                    key="worker-source-discovery",
                    severity="error",
                    category=APP_LOCAL_STATUS,
                    summary=worker_source_error,
                )
            )
            worker_source_manifest = None
    else:
        worker_source_manifest = _normalize_project_path(worker_source)

    if worker_source_manifest is not None:
        if not worker_source_manifest.exists():
            findings.append(
                Finding(
                    key="missing-worker-source-manifest",
                    severity="error",
                    category=APP_LOCAL_STATUS,
                    summary="Source worker pyproject.toml is missing.",
                    details=[str(worker_source_manifest)],
                )
            )
        else:
            try:
                worker_source_snapshot = _load_manifest(worker_source_manifest)
            except (tomllib.TOMLDecodeError, InvalidRequirement, OSError, UnicodeDecodeError) as exc:
                findings.append(
                    Finding(
                        key="invalid-worker-source-manifest",
                        severity="error",
                        category=APP_LOCAL_STATUS,
                        summary=f"Source worker pyproject.toml could not be parsed: {exc}",
                        details=[str(worker_source_manifest)],
                    )
                )

    worker_copy_manifest = (
        _normalize_project_path(worker_copy) if worker_copy is not None else _infer_worker_copy_manifest(app_root)
    )
    if worker_copy_manifest is None:
        findings.append(
            Finding(
                key="missing-worker-copy-manifest",
                severity="error",
                category=APP_LOCAL_STATUS,
                summary="Could not infer the copied worker pyproject.toml location; pass --worker-copy explicitly.",
            )
        )
    elif not worker_copy_manifest.exists():
        findings.append(
            Finding(
                key="missing-worker-copy-manifest",
                severity="error",
                category=APP_LOCAL_STATUS,
                summary="Copied worker pyproject.toml is missing.",
                details=[str(worker_copy_manifest)],
            )
        )
    else:
        try:
            worker_copy_snapshot = _load_manifest(worker_copy_manifest)
        except (tomllib.TOMLDecodeError, InvalidRequirement, OSError, UnicodeDecodeError) as exc:
            findings.append(
                Finding(
                    key="invalid-worker-copy-manifest",
                    severity="error",
                    category=APP_LOCAL_STATUS,
                    summary=f"Copied worker pyproject.toml could not be parsed: {exc}",
                    details=[str(worker_copy_manifest)],
                )
            )

    findings.extend(_compare_source_manifests(manager_snapshot, worker_source_snapshot))
    findings.extend(_compare_manager_manifest(manager_snapshot))
    findings.extend(_compare_worker_copy(manager_snapshot, worker_source_snapshot, worker_copy_snapshot, _is_repo_app(app_root)))

    recursion_depth = os.environ.get("UV_RUN_RECURSION_DEPTH", "").strip()
    if recursion_depth:
        severity = "warning" if recursion_depth not in {"0", "1"} else "info"
        findings.append(
            Finding(
                key="uv-run-recursion-depth",
                severity=severity,
                category=SHARED_CORE_STATUS,
                summary="UV_RUN_RECURSION_DEPTH is set in the current environment; nested uv commands may leak source-install context.",
                details=[f"UV_RUN_RECURSION_DEPTH={recursion_depth}"],
            )
        )

    status = _status_from_findings(findings)
    commands = _recommended_commands(app_root, worker_copy_manifest)
    return ContractReport(
        status=status,
        app_path=str(app_root),
        manager_manifest=str(manager_manifest) if manager_manifest else None,
        worker_source_manifest=str(worker_source_manifest) if worker_source_manifest else None,
        worker_copy_manifest=str(worker_copy_manifest) if worker_copy_manifest else None,
        findings=findings,
        recommended_commands=commands,
    )


def _compare_source_manifests(
    manager_snapshot: ManifestSnapshot | None,
    worker_source_snapshot: ManifestSnapshot | None,
) -> list[Finding]:
    if manager_snapshot is None or worker_source_snapshot is None:
        return []
    manager_only = sorted(set(manager_snapshot.dependencies) - set(worker_source_snapshot.dependencies))
    worker_only = sorted(set(worker_source_snapshot.dependencies) - set(manager_snapshot.dependencies))
    findings: list[Finding] = []
    if manager_only:
        findings.append(
            Finding(
                key="manager-only-deps",
                severity="info",
                category="inspection",
                summary="Manager-only dependencies differ from the source worker manifest.",
                details=manager_only,
            )
        )
    if worker_only:
        findings.append(
            Finding(
                key="worker-only-deps",
                severity="info",
                category="inspection",
                summary="Worker-only dependencies differ from the manager manifest.",
                details=worker_only,
            )
        )
    return findings


def _compare_manager_manifest(manager_snapshot: ManifestSnapshot | None) -> list[Finding]:
    if manager_snapshot is None:
        return []

    findings: list[Finding] = []
    checkout_core_paths = _checkout_core_project_paths()
    missing_resolution: list[str] = []

    for core_name in ("agi-env", "agi-node"):
        if core_name not in manager_snapshot.dependencies:
            continue
        raw_path = manager_snapshot.uv_sources.get(core_name)
        if raw_path:
            resolved = _resolve_uv_source_path(Path(manager_snapshot.path), raw_path)
            if not resolved.exists():
                missing_resolution.append(f"{core_name}: {raw_path}")
            continue

        checkout_path = checkout_core_paths.get(core_name)
        if checkout_path is None or not checkout_path.exists():
            missing_resolution.append(
                f"{core_name}: missing manager uv source and missing checkout path {checkout_path}"
            )

    if missing_resolution:
        findings.append(
            Finding(
                key="missing-manager-core-resolution-paths",
                severity="error",
                category=SHARED_CORE_STATUS,
                summary=(
                    "Manager manifest depends on local AGILAB core packages, but no manager-side "
                    "local resolution path is available for the offline installer overlay."
                ),
                details=missing_resolution,
            )
        )

    return findings


def _compare_worker_copy(
    manager_snapshot: ManifestSnapshot | None,
    worker_source_snapshot: ManifestSnapshot | None,
    worker_copy_snapshot: ManifestSnapshot | None,
    repo_app: bool,
) -> list[Finding]:
    if worker_copy_snapshot is None:
        return []
    findings: list[Finding] = []
    source_worker_dependencies = worker_source_snapshot.dependencies if worker_source_snapshot else {}
    source_manager_dependencies = manager_snapshot.dependencies if manager_snapshot else {}

    missing_from_copy = sorted(set(source_worker_dependencies) - set(worker_copy_snapshot.dependencies))
    if missing_from_copy:
        findings.append(
            Finding(
                key="copied-worker-missing-source-deps",
                severity="error",
                category=SHARED_CORE_STATUS,
                summary="Copied worker manifest is missing dependencies declared by the source worker manifest.",
                details=missing_from_copy,
            )
        )

    injected_exact_pins: list[str] = []
    for name, copied_dep in sorted(worker_copy_snapshot.dependencies.items()):
        if name in CORE_PACKAGE_NAMES or not copied_dep.exact_pin:
            continue
        source_worker_dep = source_worker_dependencies.get(name)
        source_manager_dep = source_manager_dependencies.get(name)
        if source_worker_dep and source_worker_dep.exact_pin and source_worker_dep.raw == copied_dep.raw:
            continue
        if source_manager_dep and source_manager_dep.exact_pin and source_manager_dep.raw == copied_dep.raw:
            continue
        injected_exact_pins.append(f"{name}: copied={copied_dep.raw}")
    if injected_exact_pins:
        findings.append(
            Finding(
                key="injected-exact-pins",
                severity="error",
                category=SHARED_CORE_STATUS,
                summary="Copied worker manifest gained exact-pinned dependencies that are not exact pins in source manifests.",
                details=injected_exact_pins,
            )
        )

    stale_uv_sources: list[str] = []
    for name, raw_path in sorted(worker_copy_snapshot.uv_sources.items()):
        resolved = _resolve_uv_source_path(Path(worker_copy_snapshot.path), raw_path)
        if not resolved.exists():
            stale_uv_sources.append(f"{name}: {raw_path}")
    if stale_uv_sources:
        findings.append(
            Finding(
                key="stale-uv-sources",
                severity="error",
                category=SHARED_CORE_STATUS,
                summary="Copied worker manifest references missing local uv source paths.",
                details=stale_uv_sources,
            )
        )

    if repo_app:
        missing_core_paths: list[str] = []
        for core_name in ("agi-env", "agi-node"):
            if core_name not in worker_copy_snapshot.dependencies:
                continue
            raw_path = worker_copy_snapshot.uv_sources.get(core_name)
            if not raw_path:
                missing_core_paths.append(f"{core_name}: missing [tool.uv.sources].{core_name}.path")
                continue
            resolved = _resolve_uv_source_path(Path(worker_copy_snapshot.path), raw_path)
            if not resolved.exists():
                missing_core_paths.append(f"{core_name}: {raw_path}")
        if missing_core_paths:
            findings.append(
                Finding(
                    key="missing-local-core-paths",
                    severity="error",
                    category=SHARED_CORE_STATUS,
                    summary="Copied worker manifest does not preserve local agi-env/agi-node source paths for a repo checkout app.",
                    details=missing_core_paths,
                )
            )

    return findings


def _status_from_findings(findings: Iterable[Finding]) -> str:
    categories = {finding.category for finding in findings if finding.severity in {"error", "warning"}}
    if SHARED_CORE_STATUS in categories:
        return SHARED_CORE_STATUS
    if APP_LOCAL_STATUS in categories:
        return APP_LOCAL_STATUS
    return SAFE_STATUS


def _recommended_commands(app_root: Path, worker_copy_manifest: Path | None) -> list[str]:
    commands = [
        f"uv sync --project '{app_root}'",
        f"uv --preview-features extra-build-dependencies run python src/agilab/apps/install.py '{app_root}' --verbose 1",
    ]
    if worker_copy_manifest is not None:
        commands.append(f"sed -n '1,220p' '{worker_copy_manifest}'")
    return commands


def _render_human(report: ContractReport) -> str:
    lines = [
        f"Status: {report.status}",
        f"App path: {report.app_path}",
        f"Manager manifest: {report.manager_manifest or '<missing>'}",
        f"Worker source manifest: {report.worker_source_manifest or '<missing>'}",
        f"Worker copy manifest: {report.worker_copy_manifest or '<missing>'}",
    ]
    if report.findings:
        lines.append("")
        lines.append("Findings:")
        for finding in report.findings:
            lines.append(f"- [{finding.severity}] {finding.summary}")
            for detail in finding.details:
                lines.append(f"  - {detail}")
    else:
        lines.append("")
        lines.append("Findings:")
        lines.append("- No contract drift detected.")
    if report.recommended_commands:
        lines.append("")
        lines.append("Recommended commands:")
        for command in report.recommended_commands:
            lines.append(f"- {command}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        report = analyze_contract(
            app_path=args.app_path,
            worker_copy=args.worker_copy,
            worker_source=args.worker_source,
        )
    except Exception as exc:  # pragma: no cover - CLI safety boundary
        print(f"[install-contract-check] {exc}", file=sys.stderr)
        return 3

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        print(_render_human(report))

    if report.status == SAFE_STATUS:
        return 0
    if report.status == APP_LOCAL_STATUS:
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
