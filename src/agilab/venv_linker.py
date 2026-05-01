"""Link compatible AGILAB virtual environments after install.

The linker is intentionally conservative about Python ABI and intentionally
permissive about packages: a larger environment may satisfy a smaller project's
runtime requirements and become the shared canonical venv.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import tomllib
from typing import Any

from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version


EXCLUDED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "htmlcov",
    "node_modules",
}


@dataclass(frozen=True)
class DistributionInfo:
    name: str
    version: str
    requires: tuple[str, ...] = ()


@dataclass(frozen=True)
class PythonInfo:
    executable: Path
    version: str
    major: int
    minor: int
    abiflags: str
    platform: str
    marker_environment: dict[str, str]

    @property
    def abi_key(self) -> tuple[int, int, str, str]:
        return (self.major, self.minor, self.abiflags, self.platform)


@dataclass(frozen=True)
class ProjectRequirements:
    project_path: Path
    venv_path: Path
    dependencies: tuple[Requirement, ...]
    requires_python: str
    dynamic_dependencies: bool = False
    invalid_dependencies: tuple[str, ...] = ()


@dataclass(frozen=True)
class VenvState:
    project: ProjectRequirements
    python: PythonInfo
    distributions: Mapping[str, DistributionInfo]

    @property
    def package_count(self) -> int:
        return len(self.distributions)


@dataclass(frozen=True)
class RequirementCheck:
    ok: bool
    missing: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()


@dataclass(frozen=True)
class LinkAction:
    target_project: Path
    target_venv: Path
    canonical_project: Path
    canonical_venv: Path
    reason: str
    target_package_count: int
    canonical_package_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "target_project": str(self.target_project),
            "target_venv": str(self.target_venv),
            "canonical_project": str(self.canonical_project),
            "canonical_venv": str(self.canonical_venv),
            "reason": self.reason,
            "target_package_count": self.target_package_count,
            "canonical_package_count": self.canonical_package_count,
        }


@dataclass(frozen=True)
class LinkReport:
    actions: tuple[LinkAction, ...]
    skipped: tuple[dict[str, Any], ...]
    applied: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "agilab.venv_link_report.v1",
            "applied": self.applied,
            "linked_count": len(self.actions),
            "actions": [action.as_dict() for action in self.actions],
            "skipped": list(self.skipped),
        }


def _venv_python(venv_path: Path) -> Path | None:
    candidates = (
        venv_path / "bin" / "python",
        venv_path / "Scripts" / "python.exe",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _is_excluded(path: Path) -> bool:
    return any(part in EXCLUDED_PARTS for part in path.parts)


def discover_projects(roots: Sequence[Path]) -> list[ProjectRequirements]:
    projects: list[ProjectRequirements] = []
    seen: set[Path] = set()
    for root in sorted(
        (Path(item).expanduser().resolve(strict=False) for item in roots),
        key=lambda p: p.as_posix(),
    ):
        if not root.exists():
            continue
        pyprojects = sorted(root.rglob("pyproject.toml"), key=lambda p: p.as_posix())
        for pyproject_path in pyprojects:
            if _is_excluded(pyproject_path.relative_to(root)):
                continue
            project_path = pyproject_path.parent
            venv_path = project_path / ".venv"
            if not venv_path.exists() or venv_path.is_symlink():
                continue
            resolved_project = project_path.resolve(strict=False)
            if resolved_project in seen:
                continue
            seen.add(resolved_project)
            projects.append(load_project_requirements(project_path))
    return projects


def load_project_requirements(project_path: Path) -> ProjectRequirements:
    project_path = Path(project_path).expanduser()
    pyproject_path = project_path / "pyproject.toml"
    with open(pyproject_path, "rb") as handle:
        payload = tomllib.load(handle)
    project = payload.get("project", {})
    if not isinstance(project, dict):
        project = {}
    dynamic = project.get("dynamic", [])
    dynamic_dependencies = isinstance(dynamic, list) and "dependencies" in dynamic
    raw_dependencies = project.get("dependencies", [])
    dependencies: list[Requirement] = []
    invalid_dependencies: list[str] = []
    if isinstance(raw_dependencies, list):
        for raw_dependency in raw_dependencies:
            try:
                dependencies.append(Requirement(str(raw_dependency)))
            except InvalidRequirement:
                invalid_dependencies.append(str(raw_dependency))
    return ProjectRequirements(
        project_path=project_path,
        venv_path=project_path / ".venv",
        dependencies=tuple(dependencies),
        requires_python=str(project.get("requires-python", "") or ""),
        dynamic_dependencies=dynamic_dependencies,
        invalid_dependencies=tuple(invalid_dependencies),
    )


def inspect_venv(venv_path: Path) -> VenvState:
    venv_path = Path(venv_path).expanduser()
    python = _venv_python(venv_path)
    if python is None:
        raise FileNotFoundError(f"No Python executable found under {venv_path}")
    probe = """
import importlib.metadata as md
import json
import platform
import sys
import sysconfig

distributions = {}
for dist in md.distributions():
    name = dist.metadata.get("Name") or ""
    if not name:
        continue
    distributions[name] = {
        "version": dist.version,
        "requires": list(dist.requires or []),
    }
print(json.dumps({
    "python": {
        "executable": sys.executable,
        "version": ".".join(str(part) for part in sys.version_info[:3]),
        "major": sys.version_info.major,
        "minor": sys.version_info.minor,
        "abiflags": getattr(sys, "abiflags", ""),
        "platform": sysconfig.get_platform(),
        "implementation_name": sys.implementation.name,
        "implementation_version": platform.python_version(),
        "sys_platform": sys.platform,
        "platform_machine": platform.machine(),
        "platform_python_implementation": platform.python_implementation(),
        "platform_release": platform.release(),
        "platform_system": platform.system(),
        "platform_version": platform.version(),
    },
    "distributions": distributions,
}, sort_keys=True))
"""
    completed = subprocess.run(
        [str(python), "-c", probe],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    python_payload = payload["python"]
    marker_environment = default_environment()
    marker_environment.update(
        {
            "implementation_name": str(python_payload.get("implementation_name", "")),
            "implementation_version": str(python_payload.get("implementation_version", "")),
            "platform_machine": str(python_payload.get("platform_machine", "")),
            "platform_python_implementation": str(
                python_payload.get("platform_python_implementation", "")
            ),
            "platform_release": str(python_payload.get("platform_release", "")),
            "platform_system": str(python_payload.get("platform_system", "")),
            "platform_version": str(python_payload.get("platform_version", "")),
            "python_full_version": str(python_payload.get("version", "")),
            "python_version": ".".join(
                str(python_payload.get(key, ""))
                for key in ("major", "minor")
            ),
            "sys_platform": str(python_payload.get("sys_platform", "")),
        }
    )
    distributions = {
        canonicalize_name(name): DistributionInfo(
            name=name,
            version=str(info.get("version", "")),
            requires=tuple(str(item) for item in info.get("requires", []) or []),
        )
        for name, info in payload.get("distributions", {}).items()
        if isinstance(info, dict)
    }
    project = load_project_requirements(venv_path.parent)
    return VenvState(
        project=project,
        python=PythonInfo(
            executable=Path(python_payload.get("executable", python)),
            version=str(python_payload.get("version", "")),
            major=int(python_payload.get("major", 0) or 0),
            minor=int(python_payload.get("minor", 0) or 0),
            abiflags=str(python_payload.get("abiflags", "") or ""),
            platform=str(python_payload.get("platform", "") or ""),
            marker_environment=marker_environment,
        ),
        distributions=distributions,
    )


def _requires_python_ok(requirement: str, python: PythonInfo) -> bool:
    if not requirement:
        return True
    try:
        return SpecifierSet(requirement).contains(python.version, prereleases=True)
    except InvalidSpecifier:
        return False


def _marker_applies(requirement: Requirement, marker_environment: Mapping[str, str], *, extra: str = "") -> bool:
    if requirement.marker is None:
        return True
    environment = dict(marker_environment)
    environment["extra"] = extra
    try:
        return bool(requirement.marker.evaluate(environment))
    except (AssertionError, KeyError, TypeError, ValueError):
        return False


def _version_ok(requirement: Requirement, distribution: DistributionInfo) -> bool:
    if not requirement.specifier:
        return True
    try:
        version = Version(distribution.version)
    except InvalidVersion:
        return False
    return requirement.specifier.contains(version, prereleases=True)


def _merge_checks(checks: Iterable[RequirementCheck]) -> RequirementCheck:
    missing: list[str] = []
    conflicts: list[str] = []
    skipped: list[str] = []
    ok = True
    for check in checks:
        ok = ok and check.ok
        missing.extend(check.missing)
        conflicts.extend(check.conflicts)
        skipped.extend(check.skipped)
    return RequirementCheck(
        ok=ok,
        missing=tuple(dict.fromkeys(missing)),
        conflicts=tuple(dict.fromkeys(conflicts)),
        skipped=tuple(dict.fromkeys(skipped)),
    )


def requirement_satisfied(
    requirement: Requirement,
    distributions: Mapping[str, DistributionInfo],
    marker_environment: Mapping[str, str],
    *,
    extra: str = "",
    stack: frozenset[str] = frozenset(),
) -> RequirementCheck:
    if not _marker_applies(requirement, marker_environment, extra=extra):
        return RequirementCheck(True, skipped=(str(requirement),))
    canonical_name = canonicalize_name(requirement.name)
    distribution = distributions.get(canonical_name)
    if distribution is None:
        return RequirementCheck(False, missing=(str(requirement),))
    if not _version_ok(requirement, distribution):
        return RequirementCheck(
            False,
            conflicts=(f"{requirement} installed={distribution.version}",),
        )
    if canonical_name in stack:
        return RequirementCheck(True)
    checks: list[RequirementCheck] = [RequirementCheck(True)]
    for requested_extra in sorted(requirement.extras):
        for raw_extra_dependency in distribution.requires:
            try:
                extra_requirement = Requirement(raw_extra_dependency)
            except InvalidRequirement:
                checks.append(RequirementCheck(False, conflicts=(raw_extra_dependency,)))
                continue
            if not _marker_applies(
                extra_requirement,
                marker_environment,
                extra=requested_extra,
            ):
                continue
            checks.append(
                requirement_satisfied(
                    extra_requirement,
                    distributions,
                    marker_environment,
                    extra=requested_extra,
                    stack=stack | {canonical_name},
                )
            )
    return _merge_checks(checks)


def candidate_satisfies_project(
    target: VenvState,
    candidate: VenvState,
) -> RequirementCheck:
    if target.project.dynamic_dependencies:
        return RequirementCheck(
            False,
            conflicts=("project declares dynamic dependencies",),
        )
    if target.project.invalid_dependencies:
        return RequirementCheck(
            False,
            conflicts=tuple(
                f"invalid dependency in target project: {dependency}"
                for dependency in target.project.invalid_dependencies
            ),
        )
    if target.python.abi_key != candidate.python.abi_key:
        return RequirementCheck(
            False,
            conflicts=(
                "python ABI mismatch: "
                f"target={target.python.abi_key} candidate={candidate.python.abi_key}",
            ),
        )
    if not _requires_python_ok(target.project.requires_python, candidate.python):
        return RequirementCheck(
            False,
            conflicts=(
                f"candidate Python {candidate.python.version} does not satisfy "
                f"{target.project.requires_python}",
            ),
        )
    return _merge_checks(
        requirement_satisfied(
            requirement,
            candidate.distributions,
            candidate.python.marker_environment,
        )
        for requirement in target.project.dependencies
    )


def _state_sort_key(state: VenvState) -> tuple[int, str]:
    return (-state.package_count, state.project.project_path.as_posix())


def build_link_plan(states: Sequence[VenvState]) -> tuple[tuple[LinkAction, ...], tuple[dict[str, Any], ...]]:
    actions: list[LinkAction] = []
    skipped: list[dict[str, Any]] = []
    replaced: set[Path] = set()
    canonical_venvs: set[Path] = set()
    candidates = sorted(states, key=_state_sort_key)
    targets = sorted(states, key=lambda state: (state.package_count, state.project.project_path.as_posix()))

    for target in targets:
        if target.project.venv_path in replaced:
            continue
        if target.project.venv_path in canonical_venvs:
            skipped.append(
                {
                    "project": str(target.project.project_path),
                    "reason": "environment selected as canonical for another project",
                }
            )
            continue
        if target.project.venv_path.is_symlink():
            skipped.append(
                {
                    "project": str(target.project.project_path),
                    "reason": "target venv is already a symlink",
                }
            )
            continue
        selected: VenvState | None = None
        selected_check: RequirementCheck | None = None
        failed_checks: list[str] = []
        for candidate in candidates:
            if candidate.project.venv_path == target.project.venv_path:
                continue
            if candidate.project.venv_path in replaced:
                continue
            check = candidate_satisfies_project(target, candidate)
            if check.ok:
                selected = candidate
                selected_check = check
                break
            failed_checks.extend(check.missing)
            failed_checks.extend(check.conflicts)
        if selected is None or selected_check is None:
            skipped.append(
                {
                    "project": str(target.project.project_path),
                    "reason": "no compatible larger environment found",
                    "details": sorted(dict.fromkeys(failed_checks))[:10],
                }
            )
            continue
        actions.append(
            LinkAction(
                target_project=target.project.project_path,
                target_venv=target.project.venv_path,
                canonical_project=selected.project.project_path,
                canonical_venv=selected.project.venv_path,
                reason="candidate satisfies target project requirements",
                target_package_count=target.package_count,
                canonical_package_count=selected.package_count,
            )
        )
        replaced.add(target.project.venv_path)
        canonical_venvs.add(selected.project.venv_path)
    return tuple(actions), tuple(skipped)


def _install_project_no_deps(
    *,
    uv: str,
    project_path: Path,
    canonical_python: Path,
    dry_run: bool,
) -> None:
    if dry_run:
        return
    subprocess.run(
        [
            uv,
            "pip",
            "install",
            "--python",
            str(canonical_python),
            "--no-deps",
            "-e",
            str(project_path),
        ],
        check=True,
    )


def apply_link_actions(
    actions: Sequence[LinkAction],
    states_by_venv: Mapping[Path, VenvState],
    *,
    uv: str = "uv",
    dry_run: bool = True,
    install_projects: bool = True,
) -> None:
    for action in actions:
        canonical_state = states_by_venv[action.canonical_venv]
        if install_projects:
            _install_project_no_deps(
                uv=uv,
                project_path=action.target_project,
                canonical_python=canonical_state.python.executable,
                dry_run=dry_run,
            )
        if dry_run:
            continue
        backup_path: Path | None = None
        if action.target_venv.exists() or action.target_venv.is_symlink():
            backup_path = action.target_venv.with_name(f"{action.target_venv.name}.agilab-linking")
            suffix = 0
            while backup_path.exists() or backup_path.is_symlink():
                suffix += 1
                backup_path = action.target_venv.with_name(
                    f"{action.target_venv.name}.agilab-linking.{suffix}"
                )
            action.target_venv.rename(backup_path)
        try:
            action.target_venv.symlink_to(action.canonical_venv, target_is_directory=True)
        except OSError:
            if backup_path is not None and (backup_path.exists() or backup_path.is_symlink()):
                if action.target_venv.is_symlink():
                    action.target_venv.unlink()
                elif action.target_venv.exists():
                    shutil.rmtree(action.target_venv)
                backup_path.rename(action.target_venv)
            raise
        if backup_path is not None:
            if backup_path.is_symlink():
                backup_path.unlink()
            elif backup_path.exists():
                shutil.rmtree(backup_path)


def link_compatible_venvs(
    roots: Sequence[Path],
    *,
    apply: bool = False,
    uv: str = "uv",
    install_projects: bool = True,
    inspect_venv_fn: Callable[[Path], VenvState] = inspect_venv,
) -> LinkReport:
    projects = discover_projects(roots)
    states: list[VenvState] = []
    skipped: list[dict[str, Any]] = []
    for project in projects:
        try:
            states.append(inspect_venv_fn(project.venv_path))
        except (FileNotFoundError, json.JSONDecodeError, subprocess.CalledProcessError, OSError) as exc:
            skipped.append({"project": str(project.project_path), "reason": str(exc)})
    actions, plan_skipped = build_link_plan(states)
    states_by_venv = {state.project.venv_path: state for state in states}
    apply_link_actions(
        actions,
        states_by_venv,
        uv=uv,
        dry_run=not apply,
        install_projects=install_projects,
    )
    return LinkReport(actions=actions, skipped=tuple([*skipped, *plan_skipped]), applied=apply)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Link compatible AGILAB virtual environments.")
    parser.add_argument(
        "--root",
        action="append",
        type=Path,
        default=[],
        help="Root to scan for projects with pyproject.toml and .venv. Repeatable.",
    )
    parser.add_argument("--apply", action="store_true", help="Replace compatible target .venv directories with symlinks.")
    parser.add_argument("--report", type=Path, default=None, help="Optional JSON report path.")
    parser.add_argument("--uv", default="uv", help="uv executable used to register linked projects.")
    parser.add_argument(
        "--no-install-project",
        action="store_true",
        help="Do not install linked target projects into the canonical environment.",
    )
    parser.add_argument("--compact", action="store_true", help="Print compact JSON.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    roots = args.root or [Path.cwd()]
    report = link_compatible_venvs(
        roots,
        apply=bool(args.apply),
        uv=args.uv,
        install_projects=not args.no_install_project,
    )
    payload = report.as_dict()
    if args.report:
        args.report.expanduser().parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.compact:
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
