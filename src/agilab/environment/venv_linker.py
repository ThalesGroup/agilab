"""Link compatible AGILAB virtual environments after install.

The linker is intentionally conservative about Python ABI and intentionally
permissive about packages: a larger environment may satisfy a smaller project's
runtime requirements and become the shared canonical venv.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import tomllib
from typing import Any

from packaging.markers import InvalidMarker, Marker, default_environment
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import InvalidName, canonicalize_name
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
    origin: str | None = None
    content_hash: str | None = None
    editable_path: str | None = None
    identity_error: str = ""


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
    name: str = ""
    authoritative_lock: Path | None = None
    dynamic_dependencies: bool = False
    invalid_dependencies: tuple[str, ...] = ()
    manifest_hashes: tuple[tuple[str, str | None], ...] = ()


@dataclass(frozen=True)
class VenvState:
    project: ProjectRequirements
    python: PythonInfo
    distributions: Mapping[str, DistributionInfo]
    directory_identity: tuple[int, int] = ()
    locked_dependencies: tuple[Requirement, ...] = ()
    lock_checked: bool = False
    lock_error: str = ""

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


def _metadata_payload(path: Path) -> tuple[bytes, dict[str, Any]]:
    try:
        content = path.read_bytes()
        return content, tomllib.loads(content.decode("utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        raise ValueError("Project metadata is unreadable or malformed") from None


def _lock_inputs(project_path: Path) -> tuple[Path | None, tuple[Path, ...]]:
    # uv, rather than a second workspace resolver, validates package membership.
    # Include ancestor workspace inputs even when the member has no local lock.
    root = project_path
    for parent in project_path.parents:
        manifest = parent / "pyproject.toml"
        if not manifest.is_file():
            continue
        _, payload = _metadata_payload(manifest)
        tool = payload.get("tool", {})
        uv = tool.get("uv", {}) if isinstance(tool, dict) else {}
        if isinstance(uv, dict) and "workspace" in uv:
            root = parent
            break
    lock = root / "uv.lock"
    inputs = tuple(
        dict.fromkeys(
            (
                project_path / "pyproject.toml",
                project_path / "uv.lock",
                project_path / "uv.toml",
                project_path / ".python-version",
                root / "pyproject.toml",
                root / "uv.lock",
                root / "uv.toml",
                root / ".python-version",
            )
        )
    )
    return (
        lock if root != project_path or lock.exists() or lock.is_symlink() else None
    ), inputs


def load_project_requirements(project_path: Path) -> ProjectRequirements:
    project_path = Path(project_path).expanduser()
    _, payload = _metadata_payload(project_path / "pyproject.toml")
    lock_path, inputs = _lock_inputs(project_path)
    hashes = []
    for path in inputs:
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except FileNotFoundError:
            digest = None
        hashes.append((str(path), digest))
    errors: list[str] = []
    project = payload.get("project")
    if not isinstance(project, dict):
        project = {}
        errors.append("project must be a metadata table")
    name = project.get("name", "")
    try:
        if not isinstance(name, str) or not name:
            raise InvalidName()
        name = canonicalize_name(name, validate=True)
    except InvalidName:
        name = ""
        errors.append("project.name must be a valid distribution name")
    if "version" in project:
        try:
            if not isinstance(project["version"], str):
                raise InvalidVersion("non-string")
            Version(project["version"])
        except InvalidVersion:
            errors.append("project.version must be a valid version string")
    tool = payload.get("tool", {})
    if not isinstance(tool, dict):
        errors.append("tool must be a metadata table")
        tool = {}
    uv = tool.get("uv", {})
    if not isinstance(uv, dict):
        errors.append("tool.uv must be a metadata table")
        uv = {}
    sources = uv.get("sources", {})
    if not isinstance(sources, dict):
        errors.append("tool.uv.sources must be a metadata table")
    elif sources and lock_path is None:
        errors.append("tool.uv.sources requires a qualified authoritative uv.lock")
    dynamic = project.get("dynamic", [])
    if not isinstance(dynamic, list) or any(
        not isinstance(item, str) for item in dynamic
    ):
        errors.append("project.dynamic must be an array of strings")
        dynamic = []
    requires_python = project.get("requires-python", "")
    try:
        if not isinstance(requires_python, str):
            raise InvalidSpecifier()
        SpecifierSet(requires_python)
    except InvalidSpecifier:
        requires_python = ""
        errors.append("project.requires-python must be a valid specifier string")

    def requirements(value: Any, field: str) -> tuple[Requirement, ...]:
        if not isinstance(value, list):
            errors.append(f"{field} must be an array of requirement strings")
            return ()
        result = []
        for index, item in enumerate(value):
            try:
                if not isinstance(item, str):
                    raise InvalidRequirement("non-string")
                result.append(Requirement(item))
            except InvalidRequirement:
                # Do not echo requirement values: URLs may contain credentials.
                errors.append(f"{field}[{index}] must be a valid requirement string")
        return tuple(result)

    dependencies = requirements(project.get("dependencies", []), "project.dependencies")
    optional = project.get("optional-dependencies", {})
    if not isinstance(optional, dict):
        errors.append("project.optional-dependencies must be a table")
    else:
        for extra, values in optional.items():
            try:
                canonicalize_name(extra, validate=True)
            except InvalidName:
                errors.append("project.optional-dependencies has an invalid extra name")
            requirements(values, "project.optional-dependencies entry")
    return ProjectRequirements(
        project_path=project_path,
        venv_path=project_path / ".venv",
        dependencies=dependencies,
        requires_python=requires_python,
        name=name,
        authoritative_lock=lock_path,
        dynamic_dependencies=bool(
            {"dependencies", "optional-dependencies", "requires-python"}.intersection(
                dynamic
            )
        ),
        invalid_dependencies=tuple(errors),
        manifest_hashes=tuple(hashes),
    )


def _validate_lock_shape(path: Path) -> None:
    """Constrain supported input shapes; uv still owns all resolution semantics."""
    _, payload = _metadata_payload(path)
    allowed = {
        "version",
        "revision",
        "requires-python",
        "resolution-markers",
        "supported-markers",
        "conflicts",
        "options",
        "manifest",
        "package",
    }
    if (
        set(payload) - allowed
        or type(payload.get("version")) is not int
        or payload["version"] != 1
        or type(payload.get("revision", 0)) is not int
        or not 0 <= payload.get("revision", 0) <= 3
        or not isinstance(payload.get("requires-python"), str)
        or not isinstance(payload.get("package"), list)
        or not payload["package"]
    ):
        raise ValueError("Unsupported or malformed authoritative uv.lock shape")
    try:
        SpecifierSet(payload["requires-python"])
        for field in ("resolution-markers", "supported-markers"):
            if field in payload:
                if not isinstance(payload[field], list):
                    raise ValueError()
                for marker in payload[field]:
                    if not isinstance(marker, str):
                        raise ValueError()
                    Marker(marker)
        for field in ("options", "manifest"):
            if field in payload and not isinstance(payload[field], dict):
                raise ValueError()
        if "conflicts" in payload and not isinstance(payload["conflicts"], list):
            raise ValueError()
        if set(payload.get("options", {})) - {
            "exclude-newer", "exclude-newer-package", "resolution", "prerelease",
            "fork-strategy", "index-strategy",
        }:
            raise ValueError()
        if set(payload.get("manifest", {})) - {
            "members", "requirements", "constraints", "overrides", "dependency-groups",
        }:
            raise ValueError()

        def dependency_rows(rows: Any) -> None:
            if not isinstance(rows, list):
                raise ValueError()
            for row in rows:
                if not isinstance(row, dict) or set(row) - {"name", "version", "source", "marker", "extras"}:
                    raise ValueError()
                canonicalize_name(row["name"], validate=True)
                if "marker" in row:
                    Marker(row["marker"])
                if "extras" in row and (
                    not isinstance(row["extras"], list)
                    or any(not isinstance(extra, str) for extra in row["extras"])
                ):
                    raise ValueError()

        for package in payload["package"]:
            if isinstance(package, dict) and set(package) - {
                "name", "version", "source", "dependencies", "optional-dependencies",
                "dev-dependencies", "resolution-markers", "sdist", "wheels", "metadata",
            }:
                raise ValueError()
            if isinstance(package, dict):
                dependency_rows(package.get("dependencies", []))
                for field in ("optional-dependencies", "dev-dependencies"):
                    groups = package.get(field, {})
                    if not isinstance(groups, dict):
                        raise ValueError()
                    for rows in groups.values():
                        dependency_rows(rows)
                metadata = package.get("metadata", {})
                if not isinstance(metadata, dict) or set(metadata) - {"requires-dist", "requires-dev", "provides-extras"}:
                    raise ValueError()
                for row in metadata.get("requires-dist", []):
                    if not isinstance(row, dict) or set(row) - {
                        "name", "specifier", "marker", "extras", "url", "directory",
                        "editable", "path", "git", "rev", "tag", "branch", "subdirectory", "index", "workspace",
                    }:
                        raise ValueError()
            if not isinstance(package, dict) or not isinstance(package.get("name"), str):
                raise ValueError()
            canonicalize_name(package["name"], validate=True)
            if not isinstance(package.get("version"), str):
                raise ValueError()
            Version(package["version"])
            origin = package.get("source")
            if (
                not isinstance(origin, dict) or len(origin) != 1
                or set(origin) - {"registry", "virtual", "editable", "directory", "git", "url"}
                or any(not isinstance(value, str) or not value for value in origin.values())
            ):
                raise ValueError()
    except (KeyError, ValueError, TypeError, InvalidName, InvalidVersion, InvalidMarker):
        raise ValueError("Unsupported or malformed authoritative uv.lock shape") from None


def _locked_requirements(
    project: ProjectRequirements, python: Path, *, uv: str = "uv",
) -> tuple[Requirement, ...]:
    lock = project.authoritative_lock
    if lock is None:
        return ()
    _validate_lock_shape(lock)
    completed = subprocess.run(
        [
            uv, "export", "--project", str(project.project_path),
            "--package", project.name, "--locked", "--offline", "--no-build",
            "--no-python-downloads", "--python", str(python),
            "--no-default-groups", "--no-dev", "--no-emit-project",
            "--no-emit-package", project.name, "--no-hashes", "--no-header",
            "--no-annotate", "--format", "requirements.txt",
        ],
        capture_output=True, text=True, check=False,
    )
    if completed.returncode:
        raise ValueError(
            "Authoritative uv.lock cannot be validated with uv export --locked --offline; "
            "refresh the lock with the selected Python and inspect again"
        )
    requirements = []
    for line in completed.stdout.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        try:
            requirement = Requirement(line)
        except InvalidRequirement:
            raise ValueError("Unsupported local or ambiguous authoritative lock export") from None
        pins = list(requirement.specifier)
        if requirement.url or len(pins) != 1 or pins[0].operator != "==" or "*" in pins[0].version:
            raise ValueError("Unsupported source identity in authoritative lock export")
        requirements.append(requirement)
    return tuple(requirements)


def _venv_directory_identity(venv_path: Path) -> tuple[int, int]:
    info = venv_path.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError(
            f"Expected an inspected venv directory, not a symlink or file: {venv_path}"
        )
    return info.st_dev, info.st_ino


def inspect_venv(venv_path: Path, *, uv: str = "uv") -> VenvState:
    venv_path = Path(venv_path).expanduser()
    directory_identity = _venv_directory_identity(venv_path)
    project = load_project_requirements(venv_path.parent)
    python = _venv_python(venv_path)
    if python is None:
        raise FileNotFoundError(f"No Python executable found under {venv_path}")

    probe = r"""
import hashlib
import importlib.metadata as md
import json
from pathlib import Path
import platform
import sys
import sysconfig

distributions = []
for dist in md.distributions():
    name = dist.metadata.get("Name") or ""
    identity_error = ""
    content_hash = None
    origin = None
    editable_path = None
    try:
        direct = dist.read_text("direct_url.json")
        if direct is not None:
            from urllib.parse import unquote, urlsplit
            direct = json.loads(direct)
            if not isinstance(direct, dict) or not isinstance(direct.get("url"), str):
                raise ValueError()
            origin = json.dumps(direct, sort_keys=True, separators=(",", ":"))
            info = direct.get("dir_info", {})
            if not isinstance(info, dict) or type(info.get("editable", False)) is not bool:
                raise ValueError()
            if info.get("editable"):
                url = urlsplit(direct["url"])
                if url.scheme != "file" or url.netloc not in ("", "localhost") or url.query or url.fragment:
                    raise ValueError()
                editable_path = str(Path(unquote(url.path)).resolve(strict=True))
        if dist.files is None:
            raise ValueError()
        digest = hashlib.sha256()
        root = Path(dist.locate_file("")).resolve()
        for entry in sorted(dist.files, key=str):
            relative = str(entry)
            if relative.endswith((".pyc", ".pyo")) or Path(relative).name in ("RECORD", "INSTALLER", "REQUESTED", "direct_url.json"):
                continue
            path = Path(dist.locate_file(entry))
            if not path.resolve().is_relative_to(root):
                continue  # generated entry-point scripts contain environment-specific shebangs
            digest.update(relative.encode("utf-8") + b"\0")
            digest.update(path.read_bytes())
        content_hash = digest.hexdigest()
    except (OSError, UnicodeError, ValueError, TypeError):
        identity_error = "installed distribution identity is unreadable or malformed"
    distributions.append({
        "name": name, "version": dist.version, "requires": dist.requires,
        "origin": origin, "content_hash": content_hash,
        "editable_path": editable_path, "identity_error": identity_error,
    })
print(json.dumps({
    "python": {
        "executable": sys.executable, "prefix": sys.prefix, "base_prefix": sys.base_prefix,
        "version": ".".join(str(part) for part in sys.version_info[:3]),
        "major": sys.version_info.major, "minor": sys.version_info.minor,
        "abiflags": getattr(sys, "abiflags", ""), "platform": sysconfig.get_platform(),
        "implementation_name": sys.implementation.name,
        "implementation_version": platform.python_version(), "sys_platform": sys.platform,
        "platform_machine": platform.machine(),
        "platform_python_implementation": platform.python_implementation(),
        "platform_release": platform.release(), "platform_system": platform.system(),
        "platform_version": platform.version(),
    },
    "distributions": distributions,
}, sort_keys=True))
"""
    completed = subprocess.run(
        [str(python), "-I", "-B", "-c", probe],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    python_payload = payload["python"]
    prefix = Path(python_payload["prefix"]).resolve()
    if (
        prefix != venv_path.resolve()
        or prefix == Path(python_payload["base_prefix"]).resolve()
    ):
        raise ValueError(
            f"Python is not running in the selected virtual environment: {venv_path}"
        )
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

    distributions = {}
    for info in payload["distributions"]:
        try:
            name = canonicalize_name(info["name"], validate=True)
            if name in distributions:
                raise ValueError("Ambiguous duplicate installed distribution")
            requires = info["requires"]
            if requires is None:
                requires = []
            if not isinstance(requires, list) or any(not isinstance(item, str) for item in requires):
                raise ValueError("Malformed installed dependency declarations")
            distributions[name] = DistributionInfo(
                name=info["name"], version=info["version"], requires=tuple(requires),
                origin=info["origin"], content_hash=info["content_hash"],
                editable_path=info["editable_path"], identity_error=info["identity_error"],
            )
        except (InvalidName, KeyError, TypeError):
            raise ValueError("Malformed installed distribution metadata") from None
    locked_dependencies = ()
    lock_error = ""
    try:
        if not project.invalid_dependencies and not project.dynamic_dependencies:
            locked_dependencies = _locked_requirements(project, python, uv=uv)
    except ValueError as exc:
        lock_error = str(exc)
    except OSError:
        lock_error = "Authoritative uv.lock validation requires an available uv executable"
    if (
        _venv_directory_identity(venv_path) != directory_identity
        or load_project_requirements(venv_path.parent) != project
    ):
        raise ValueError(
            f"Environment or manifest changed during inspection: {venv_path}"
        )
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
        directory_identity=directory_identity,
        locked_dependencies=locked_dependencies,
        lock_checked=not lock_error and not project.invalid_dependencies and not project.dynamic_dependencies,
        lock_error=lock_error,
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
        raise ValueError("Dependency marker cannot be evaluated for the selected Python") from None


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
    stack: frozenset[tuple[str, tuple[str, ...], str]] = frozenset(),
) -> RequirementCheck:
    try:
        applies = _marker_applies(requirement, marker_environment, extra=extra)
    except ValueError as exc:
        return RequirementCheck(False, conflicts=(str(exc),))
    if not applies:
        return RequirementCheck(True, skipped=(str(requirement),))
    if requirement.url:
        return RequirementCheck(
            False, conflicts=(f"direct URL identity is not verified for {requirement.name}",)
        )
    canonical_name = canonicalize_name(requirement.name)
    distribution = distributions.get(canonical_name)
    if distribution is None:
        return RequirementCheck(False, missing=(str(requirement),))
    if not _version_ok(requirement, distribution):
        return RequirementCheck(
            False,
            conflicts=(f"{requirement} installed={distribution.version}",),
        )
    context = (canonical_name, tuple(sorted(requirement.extras)), extra)
    if context in stack:
        return RequirementCheck(True)
    checks: list[RequirementCheck] = [RequirementCheck(True)]
    for requested_extra in ("", *sorted(requirement.extras)):
        for raw_extra_dependency in distribution.requires:
            try:
                extra_requirement = Requirement(raw_extra_dependency)
            except InvalidRequirement:
                checks.append(RequirementCheck(False, conflicts=(f"invalid installed dependency for {distribution.name}",)))
                continue
            checks.append(
                requirement_satisfied(
                    extra_requirement,
                    distributions,
                    marker_environment,
                    extra=requested_extra,
                    stack=stack | {context},
                )
            )
    return _merge_checks(checks)


def _application_check(target: VenvState, candidate: VenvState) -> RequirementCheck:
    name = target.project.name
    expected = target.distributions.get(name)
    actual = candidate.distributions.get(name)
    if expected is None:
        if actual is not None:
            return RequirementCheck(False, conflicts=("candidate contains an unverified target application collision",))
        return RequirementCheck(True)
    if actual is None:
        return RequirementCheck(False, missing=(f"installed target application {name}",))
    if (
        expected.identity_error or actual.identity_error
        or not expected.content_hash or not actual.content_hash
        or expected.version != actual.version
        or expected.origin != actual.origin
        or expected.content_hash != actual.content_hash
        or expected.editable_path != actual.editable_path
        or (expected.editable_path is not None and Path(expected.editable_path) != target.project.project_path.resolve())
    ):
        return RequirementCheck(False, conflicts=("installed target application source or resource identity differs or is unverified",))
    return RequirementCheck(True)


def candidate_satisfies_project(
    target: VenvState,
    candidate: VenvState,
) -> RequirementCheck:
    for role, state in (("target", target), ("candidate", candidate)):
        if state.project.dynamic_dependencies:
            return RequirementCheck(
                False,
                conflicts=(
                    "project declares dynamic dependencies or Python requirements",
                ),
            )
        if state.project.invalid_dependencies:
            return RequirementCheck(False, conflicts=tuple(
                f"invalid metadata in {role} project: {problem}"
                for problem in state.project.invalid_dependencies
            ))
        if state.lock_error or (state.project.authoritative_lock is not None and not state.lock_checked):
            return RequirementCheck(False, conflicts=(state.lock_error or "authoritative lock has not been qualified",))
    if target.python.abi_key != candidate.python.abi_key:
        return RequirementCheck(False, conflicts=(
            "python ABI mismatch: "
            f"target={target.python.abi_key} candidate={candidate.python.abi_key}",
        ))
    if not _requires_python_ok(target.project.requires_python, candidate.python):
        return RequirementCheck(False, conflicts=(
            f"candidate Python {candidate.python.version} does not satisfy {target.project.requires_python}",
        ))
    return _merge_checks([
        _application_check(target, candidate),
        *(requirement_satisfied(
            requirement, candidate.distributions, candidate.python.marker_environment,
        ) for requirement in (*target.project.dependencies, *target.locked_dependencies)),
    ])


def _state_sort_key(state: VenvState) -> tuple[int, str]:
    return (-state.package_count, state.project.project_path.as_posix())


def _link_path_conflict(
    target: VenvState, candidate: VenvState, states: Sequence[VenvState] = ()
) -> str:
    """Keep both environment trees and all inspected project inputs disjoint."""
    environments = (
        target.project.venv_path.resolve(),
        candidate.project.venv_path.resolve(),
    )
    left, right = environments
    if left.is_relative_to(right) or right.is_relative_to(left):
        return "target and canonical environment trees overlap"
    for state in (target, candidate, *states):
        protected = (
            state.project.project_path,
            *(Path(path) for path, _ in state.project.manifest_hashes),
        )
        for path in protected:
            resolved = path.resolve()
            if any(
                resolved.is_relative_to(environment) for environment in environments
            ):
                return (
                    "environment tree contains an inspected project or manifest input"
                )
    return ""


def build_link_plan(
    states: Sequence[VenvState],
) -> tuple[tuple[LinkAction, ...], tuple[dict[str, Any], ...]]:
    actions: list[LinkAction] = []
    skipped: list[dict[str, Any]] = []
    replaced: set[Path] = set()
    canonical_venvs: set[Path] = set()
    candidates = sorted(states, key=_state_sort_key)
    targets = sorted(
        states,
        key=lambda state: (state.package_count, state.project.project_path.as_posix()),
    )

    for target in targets:
        if target.project.venv_path.resolve() in replaced:
            continue
        if target.project.venv_path.resolve() in canonical_venvs:
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
            if candidate is target:
                continue
            if candidate.project.venv_path.resolve() in replaced:
                continue
            conflict = _link_path_conflict(target, candidate, states)
            if conflict:
                failed_checks.append(conflict)
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
        replaced.add(target.project.venv_path.resolve())
        canonical_venvs.add(selected.project.venv_path.resolve())
    return tuple(actions), tuple(skipped)


def _verify_link_state(
    state: VenvState,
    inspect_venv_fn: Callable[[Path], VenvState],
) -> None:
    venv = state.project.venv_path
    if (
        not state.directory_identity
        or _venv_directory_identity(venv) != state.directory_identity
        or load_project_requirements(state.project.project_path) != state.project
        or inspect_venv_fn(venv) != state
    ):
        raise ValueError(
            f"Environment or manifest changed; inspect and plan again: {venv}"
        )


def apply_link_actions(
    actions: Sequence[LinkAction],
    states_by_venv: Mapping[Path, VenvState],
    *,
    uv: str = "uv",
    dry_run: bool = True,
    install_projects: bool = False,
    inspect_venv_fn: Callable[[Path], VenvState] = inspect_venv,
) -> None:
    """Link inspected environments without installing or modifying donor packages.

    Legacy install_projects=True is refused before mutation. Prepare projects
    separately, inspect both environments again, then plan and retry the link.
    """
    if install_projects:
        raise ValueError(
            "Project registration is a separate operation and is not supported by linking; "
            "prepare the environments separately, inspect again, and retry with install_projects=False"
        )
    # Preflight every action before any action can stage or rename a target.
    for action in actions:
        target_state = states_by_venv.get(action.target_venv)
        canonical_state = states_by_venv.get(action.canonical_venv)
        if target_state is None or canonical_state is None:
            raise ValueError("Target or canonical environment has not been inspected")
        if (
            target_state.project.venv_path != action.target_venv
            or canonical_state.project.venv_path != action.canonical_venv
            or target_state.project.project_path != action.target_project
            or canonical_state.project.project_path != action.canonical_project
        ):
            raise ValueError("Link action does not match the inspected environments")
        conflict = _link_path_conflict(
            target_state, canonical_state, tuple(states_by_venv.values())
        )
        if conflict:
            raise ValueError(conflict)
    for action in actions:
        if dry_run:
            continue
        target_state = states_by_venv[action.target_venv]
        canonical_state = states_by_venv[action.canonical_venv]
        _verify_link_state(target_state, inspect_venv_fn)
        _verify_link_state(canonical_state, inspect_venv_fn)
        check = candidate_satisfies_project(target_state, canonical_state)
        if not check.ok:
            raise ValueError(f"Candidate no longer satisfies target: {check}")
        # Validate symlink creation in an exclusively owned staging directory first.
        staging = Path(
            tempfile.mkdtemp(
                prefix=f"{action.target_venv.name}.agilab-linking.",
                dir=action.target_venv.parent,
            )
        )
        backup = staging / "original"
        moved = False
        try:
            (staging / "link").symlink_to(
                action.canonical_venv.resolve(), target_is_directory=True
            )
            _verify_link_state(target_state, inspect_venv_fn)
            _verify_link_state(canonical_state, inspect_venv_fn)
            action.target_venv.rename(backup)
            moved = True
            # symlink_to refuses an occupied destination instead of replacing it.
            action.target_venv.symlink_to(
                action.canonical_venv.resolve(), target_is_directory=True
            )
        except BaseException as exc:
            if moved:
                if action.target_venv.exists() or action.target_venv.is_symlink():
                    raise OSError(
                        f"Target occupied; preserved original environment at {backup}. "
                        "Resolve the occupant before restoring the original and replanning."
                    ) from exc
                backup.rename(action.target_venv)
            shutil.rmtree(staging)
            raise
        shutil.rmtree(staging)


def link_compatible_venvs(
    roots: Sequence[Path],
    *,
    apply: bool = False,
    uv: str = "uv",
    install_projects: bool = False,
    inspect_venv_fn: Callable[[Path], VenvState] = inspect_venv,
) -> LinkReport:
    if inspect_venv_fn is inspect_venv:

        def inspect_selected(venv_path: Path) -> VenvState:
            return inspect_venv(venv_path, uv=uv)

        inspect_venv_fn = inspect_selected
    projects = discover_projects(roots)
    states: list[VenvState] = []
    skipped: list[dict[str, Any]] = []
    for project in projects:
        try:
            states.append(inspect_venv_fn(project.venv_path))
        except (ValueError, subprocess.CalledProcessError, OSError) as exc:
            skipped.append({"project": str(project.project_path), "reason": str(exc)})
    actions, plan_skipped = build_link_plan(states)
    states_by_venv = {state.project.venv_path: state for state in states}
    apply_link_actions(
        actions,
        states_by_venv,
        uv=uv,
        dry_run=not apply,
        install_projects=install_projects,
        inspect_venv_fn=inspect_venv_fn,
    )
    return LinkReport(
        actions=actions, skipped=tuple([*skipped, *plan_skipped]), applied=apply
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Link compatible AGILAB virtual environments."
    )
    parser.add_argument(
        "--root",
        action="append",
        type=Path,
        default=[],
        help="Root to scan for projects with pyproject.toml and .venv. Repeatable.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Replace compatible target .venv directories with symlinks.",
    )
    parser.add_argument(
        "--report", type=Path, default=None, help="Optional JSON report path."
    )
    parser.add_argument(
        "--uv",
        default="uv",
        help="uv executable used to inspect authoritative lock requirements.",
    )
    parser.add_argument(
        "--no-install-project",
        action="store_true",
        help="Compatibility option: links always preserve donor packages. Prepare projects separately before planning.",
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
        install_projects=False,
    )
    payload = report.as_dict()
    if args.report:
        args.report.expanduser().parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if args.compact:
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
