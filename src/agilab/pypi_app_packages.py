"""PyPI app package discovery, preflight, and management helpers."""

from __future__ import annotations

import argparse
import configparser
import io
import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from dataclasses import asdict, dataclass, field
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

try:
    from packaging.requirements import Requirement
    from packaging.specifiers import InvalidSpecifier, SpecifierSet
    from packaging.version import InvalidVersion, Version
except ModuleNotFoundError:  # pragma: no cover - packaging is supplied by AGILAB's core stack.
    Requirement = None  # type: ignore[assignment]
    SpecifierSet = None  # type: ignore[assignment]
    Version = None  # type: ignore[assignment]
    InvalidSpecifier = Exception  # type: ignore[assignment]
    InvalidVersion = Exception  # type: ignore[assignment]


PYPI_APP_INSTALL_TIMEOUT_SECONDS = 15 * 60
PYPI_APP_METADATA_TIMEOUT_SECONDS = 15
MAX_WHEEL_METADATA_BYTES = 80 * 1024 * 1024
PYPI_APP_REQUIREMENT_RE = re.compile(
    r"^(?P<name>agi-app-[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)"
    r"(?P<specifier>(?:(?:==|~=|>=|<=|!=|>|<)[A-Za-z0-9][A-Za-z0-9.*+!_-]*)"
    r"(?:,(?:==|~=|>=|<=|!=|>|<)[A-Za-z0-9][A-Za-z0-9.*+!_-]*)*)?$",
    re.IGNORECASE,
)

PROMOTED_PYPI_APP_PACKAGES: tuple[str, ...] = (
    "agi-app-flight-telemetry",
    "agi-app-global-dag",
    "agi-app-mission-decision",
    "agi-app-pandas-execution",
    "agi-app-polars-execution",
    "agi-app-uav-relay-queue",
    "agi-app-weather-forecast",
)


@dataclass(frozen=True, slots=True)
class InstalledPypiApp:
    package: str
    version: str
    entry_point: str
    provider: str
    project_root: str
    summary: str = ""
    source: str = "installed"

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PypiAppMetadata:
    package: str
    version: str
    summary: str = ""
    requires_python: str = ""
    requires_dist: tuple[str, ...] = ()
    project_url: str = ""
    package_url: str = ""
    publisher: str = ""
    wheel_available: bool = False
    sdist_available: bool = False
    signed_files: bool = False
    provenance_available: bool = False
    entry_points: tuple[str, ...] = ()
    wheel_metadata_checked: bool = False
    hashes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PypiAppPreflight:
    status: str
    requirement: str
    package: str
    metadata: PypiAppMetadata | None = None
    checks: Mapping[str, str] = field(default_factory=dict)
    issues: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.metadata is not None:
            payload["metadata"] = self.metadata.as_dict()
        return payload


@dataclass(frozen=True, slots=True)
class PypiAppCommandResult:
    status: str
    requirement: str
    command: tuple[str, ...]
    returncode: int
    output_tail: str = ""

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["command"] = list(self.command)
        return payload


def normalize_pypi_app_requirement(raw_value: str) -> str:
    """Return a conservative PyPI requirement for one ``agi-app-*`` package."""

    value = str(raw_value or "").strip()
    if not value:
        raise ValueError("Enter an agi-app-* package name.")
    if any(char.isspace() for char in value):
        raise ValueError("Use one package requirement without spaces.")
    match = PYPI_APP_REQUIREMENT_RE.fullmatch(value)
    if match is None:
        raise ValueError("Only agi-app-* package names or simple version specifiers are accepted.")
    name = match.group("name").replace("_", "-").lower()
    specifier = match.group("specifier") or ""
    return f"{name}{specifier}"


def pypi_app_package_name(requirement: str) -> str:
    normalized = normalize_pypi_app_requirement(requirement)
    match = PYPI_APP_REQUIREMENT_RE.fullmatch(normalized)
    if match is None:
        raise ValueError("Invalid agi-app requirement.")
    return match.group("name").replace("_", "-").lower()


def search_promoted_pypi_app_catalog(query: str = "") -> tuple[str, ...]:
    cleaned = str(query or "").strip().lower().replace("_", "-")
    if not cleaned:
        return PROMOTED_PYPI_APP_PACKAGES
    return tuple(package for package in PROMOTED_PYPI_APP_PACKAGES if cleaned in package)


def pypi_app_install_command(
    requirement: str,
    *,
    python_executable: str | None = None,
    uv_executable: str | None = None,
) -> tuple[str, ...]:
    uv = uv_executable or shutil.which("uv") or "uv"
    return (
        uv,
        "--preview-features",
        "extra-build-dependencies",
        "pip",
        "install",
        "--python",
        python_executable or sys.executable,
        "--upgrade",
        normalize_pypi_app_requirement(requirement),
    )


def pypi_app_uninstall_command(
    requirement: str,
    *,
    python_executable: str | None = None,
    uv_executable: str | None = None,
) -> tuple[str, ...]:
    uv = uv_executable or shutil.which("uv") or "uv"
    return (
        uv,
        "--preview-features",
        "extra-build-dependencies",
        "pip",
        "uninstall",
        "--python",
        python_executable or sys.executable,
        "-y",
        pypi_app_package_name(requirement),
    )


def _subprocess_tail(stdout: str, stderr: str, *, max_lines: int = 24) -> str:
    lines = [line for line in (stdout + "\n" + stderr).splitlines() if line.strip()]
    return "\n".join(lines[-max_lines:])


def run_pypi_app_install(
    requirement: str,
    *,
    runner: Callable[..., Any] = subprocess.run,
    python_executable: str | None = None,
    uv_executable: str | None = None,
) -> PypiAppCommandResult:
    normalized = normalize_pypi_app_requirement(requirement)
    command = pypi_app_install_command(
        normalized,
        python_executable=python_executable,
        uv_executable=uv_executable,
    )
    completed = runner(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=PYPI_APP_INSTALL_TIMEOUT_SECONDS,
        check=False,
    )
    output_tail = _subprocess_tail(
        str(getattr(completed, "stdout", "") or ""),
        str(getattr(completed, "stderr", "") or ""),
    )
    returncode = int(getattr(completed, "returncode", 1))
    return PypiAppCommandResult(
        "success" if returncode == 0 else "error",
        normalized,
        command,
        returncode,
        output_tail,
    )


def run_pypi_app_uninstall(
    requirement: str,
    *,
    runner: Callable[..., Any] = subprocess.run,
    python_executable: str | None = None,
    uv_executable: str | None = None,
) -> PypiAppCommandResult:
    normalized = pypi_app_package_name(requirement)
    command = pypi_app_uninstall_command(
        normalized,
        python_executable=python_executable,
        uv_executable=uv_executable,
    )
    completed = runner(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=PYPI_APP_INSTALL_TIMEOUT_SECONDS,
        check=False,
    )
    output_tail = _subprocess_tail(
        str(getattr(completed, "stdout", "") or ""),
        str(getattr(completed, "stderr", "") or ""),
    )
    returncode = int(getattr(completed, "returncode", 1))
    return PypiAppCommandResult(
        "success" if returncode == 0 else "error",
        normalized,
        command,
        returncode,
        output_tail,
    )


def _entry_points_for_distribution(distribution: Any) -> tuple[Any, ...]:
    entry_points = getattr(distribution, "entry_points", ())
    try:
        selected = entry_points.select(group="agilab.apps")
        return tuple(selected)
    except AttributeError:
        return tuple(entry_point for entry_point in entry_points if getattr(entry_point, "group", "") == "agilab.apps")
    except Exception:
        return ()


def _coerce_project_root(value: Any) -> Path | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        value = value.get("project_root") or value.get("path") or value.get("root")
    if callable(value):
        try:
            value = value()
        except Exception:
            return None
    try:
        path = Path(value).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    return path


def list_installed_pypi_apps(
    *,
    distributions_fn: Callable[[], Iterable[Any]] = importlib_metadata.distributions,
) -> tuple[InstalledPypiApp, ...]:
    """List installed distributions that expose AGILAB app entry points."""

    apps: list[InstalledPypiApp] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for distribution in distributions_fn():
        metadata = getattr(distribution, "metadata", {})
        package = str(metadata.get("Name") or "").strip()
        if not package.lower().replace("_", "-").startswith("agi-app-"):
            continue
        version = str(getattr(distribution, "version", "") or metadata.get("Version") or "").strip()
        summary = str(metadata.get("Summary") or "").strip()
        for entry_point in _entry_points_for_distribution(distribution):
            try:
                loaded = entry_point.load()
            except Exception:
                loaded = None
            project_root = _coerce_project_root(loaded)
            provider = str(getattr(entry_point, "name", "") or "")
            entry_point_value = str(getattr(entry_point, "value", "") or "")
            project_root_value = project_root.as_posix() if project_root is not None else ""
            key = (package.lower(), version, provider, entry_point_value, project_root_value)
            if key in seen:
                continue
            seen.add(key)
            apps.append(
                InstalledPypiApp(
                    package=package,
                    version=version,
                    entry_point=entry_point_value,
                    provider=provider,
                    project_root=project_root_value,
                    summary=summary,
                )
            )
    return tuple(sorted(apps, key=lambda item: (item.package.lower(), item.provider.lower())))


def _read_json_response(response: Any) -> Mapping[str, Any]:
    with response:
        payload = response.read()
    if isinstance(payload, str):
        return json.loads(payload)
    return json.loads(payload.decode("utf-8"))


def _open_url(
    url: str,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
    timeout: float = PYPI_APP_METADATA_TIMEOUT_SECONDS,
) -> Any:
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "agilab-pypi-app-preflight"})
    return opener(request, timeout=timeout)


def _pypi_json_url(package: str) -> str:
    return f"https://pypi.org/pypi/{package}/json"


def _distribution_project_url(info: Mapping[str, Any]) -> str:
    project_urls = info.get("project_urls")
    if isinstance(project_urls, Mapping):
        for key in ("Homepage", "Source", "Repository", "Documentation"):
            value = str(project_urls.get(key) or "").strip()
            if value:
                return value
    return str(info.get("home_page") or info.get("package_url") or "").strip()


def _release_files(payload: Mapping[str, Any], version: str) -> tuple[Mapping[str, Any], ...]:
    releases = payload.get("releases")
    if isinstance(releases, Mapping):
        files = releases.get(version)
        if isinstance(files, list):
            return tuple(item for item in files if isinstance(item, Mapping))
    urls = payload.get("urls")
    if isinstance(urls, list):
        return tuple(item for item in urls if isinstance(item, Mapping))
    return ()


def _best_wheel_url(files: Sequence[Mapping[str, Any]]) -> str:
    for file_info in files:
        if str(file_info.get("packagetype") or "") == "bdist_wheel":
            return str(file_info.get("url") or "")
    return ""


def _wheel_entry_points_from_bytes(data: bytes) -> tuple[str, ...]:
    with zipfile.ZipFile(io.BytesIO(data)) as wheel:
        entry_points_name = next(
            (name for name in wheel.namelist() if name.endswith(".dist-info/entry_points.txt")),
            "",
        )
        if not entry_points_name:
            return ()
        parser = configparser.ConfigParser()
        parser.read_string(wheel.read(entry_points_name).decode("utf-8"))
    if not parser.has_section("agilab.apps"):
        return ()
    return tuple(f"{name}={value}" for name, value in sorted(parser.items("agilab.apps")))


def _download_wheel_entry_points(
    wheel_url: str,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
    timeout: float = PYPI_APP_METADATA_TIMEOUT_SECONDS,
    max_bytes: int = MAX_WHEEL_METADATA_BYTES,
) -> tuple[str, ...] | None:
    if not wheel_url:
        return None
    request = urllib.request.Request(wheel_url, headers={"User-Agent": "agilab-pypi-app-preflight"})
    with opener(request, timeout=timeout) as response:
        length = response.headers.get("Content-Length") if hasattr(response, "headers") else None
        if length and int(length) > max_bytes:
            return None
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        return None
    return _wheel_entry_points_from_bytes(data)


def fetch_pypi_app_metadata(
    requirement: str,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
    inspect_wheel: bool = True,
) -> PypiAppMetadata:
    """Fetch PyPI JSON metadata and, when feasible, app entry points from the latest wheel."""

    package = pypi_app_package_name(requirement)
    try:
        payload = _read_json_response(_open_url(_pypi_json_url(package), opener=opener))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise ValueError(f"{package} is not available on PyPI.") from exc
        raise ValueError(f"PyPI metadata lookup failed for {package}: HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"PyPI metadata lookup failed for {package}: {exc.reason}.") from exc
    except Exception as exc:
        raise ValueError(f"PyPI metadata lookup failed for {package}: {exc}.") from exc

    info = payload.get("info") if isinstance(payload, Mapping) else {}
    if not isinstance(info, Mapping):
        info = {}
    version = str(info.get("version") or "").strip()
    files = _release_files(payload, version)
    wheel_available = any(str(file_info.get("packagetype") or "") == "bdist_wheel" for file_info in files)
    sdist_available = any(str(file_info.get("packagetype") or "") == "sdist" for file_info in files)
    signed_files = any(bool(file_info.get("has_sig")) for file_info in files)
    provenance_available = any(
        bool(file_info.get("provenance") or file_info.get("attestation") or file_info.get("attestations"))
        for file_info in files
    )
    hashes = tuple(
        str((file_info.get("digests") or {}).get("sha256") or "")
        for file_info in files
        if isinstance(file_info.get("digests"), Mapping) and (file_info.get("digests") or {}).get("sha256")
    )
    entry_points: tuple[str, ...] = ()
    wheel_metadata_checked = False
    if inspect_wheel and wheel_available:
        entry_points_or_none = _download_wheel_entry_points(_best_wheel_url(files), opener=opener)
        if entry_points_or_none is not None:
            wheel_metadata_checked = True
            entry_points = entry_points_or_none
    return PypiAppMetadata(
        package=package,
        version=version,
        summary=str(info.get("summary") or "").strip(),
        requires_python=str(info.get("requires_python") or "").strip(),
        requires_dist=tuple(str(item) for item in (info.get("requires_dist") or ()) if item),
        project_url=_distribution_project_url(info),
        package_url=str(info.get("package_url") or f"https://pypi.org/project/{package}/").strip(),
        publisher=str(info.get("maintainer") or info.get("author") or "").strip(),
        wheel_available=wheel_available,
        sdist_available=sdist_available,
        signed_files=signed_files,
        provenance_available=provenance_available,
        entry_points=entry_points,
        wheel_metadata_checked=wheel_metadata_checked,
        hashes=hashes,
    )


def _version_satisfies_spec(version: str, specifier: str) -> bool | None:
    if not specifier:
        return True
    if Version is None or SpecifierSet is None:
        return None
    try:
        return Version(version) in SpecifierSet(specifier)
    except (InvalidSpecifier, InvalidVersion):
        return None


def _python_version_string(version_info: tuple[int, int, int] | None = None) -> str:
    version = version_info or (sys.version_info.major, sys.version_info.minor, sys.version_info.micro)
    return ".".join(str(part) for part in version)


def _installed_version(distribution_name: str) -> str:
    try:
        return importlib_metadata.version(distribution_name)
    except importlib_metadata.PackageNotFoundError:
        return ""


def _dependency_compatibility(requires_dist: Iterable[str]) -> dict[str, str]:
    checks: dict[str, str] = {}
    if Requirement is None:
        return checks
    for raw_requirement in requires_dist:
        try:
            requirement = Requirement(str(raw_requirement))
        except Exception:
            continue
        normalized_name = requirement.name.lower().replace("_", "-")
        if normalized_name not in {"agilab", "agi-core"}:
            continue
        installed = _installed_version(normalized_name)
        if not installed:
            checks[f"{normalized_name}_compatibility"] = "unknown: distribution is not installed"
            continue
        satisfied = _version_satisfies_spec(installed, str(requirement.specifier))
        if satisfied is True:
            checks[f"{normalized_name}_compatibility"] = f"pass: installed {installed} satisfies {requirement.specifier}"
        elif satisfied is False:
            checks[f"{normalized_name}_compatibility"] = f"fail: installed {installed} does not satisfy {requirement.specifier}"
        else:
            checks[f"{normalized_name}_compatibility"] = f"unknown: could not evaluate {requirement.specifier}"
    return checks


def preflight_pypi_app_install(
    requirement: str,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
    python_version: str | None = None,
) -> PypiAppPreflight:
    """Check package existence, Python compatibility, app entry points, and supply-chain evidence."""

    normalized = normalize_pypi_app_requirement(requirement)
    package = pypi_app_package_name(normalized)
    issues: list[str] = []
    checks: dict[str, str] = {}
    try:
        metadata = fetch_pypi_app_metadata(normalized, opener=opener, inspect_wheel=True)
    except ValueError as exc:
        return PypiAppPreflight(
            "fail",
            normalized,
            package,
            metadata=None,
            checks={"pypi": "fail"},
            issues=(str(exc),),
        )

    checks["pypi"] = "pass"
    checks["wheel"] = "pass" if metadata.wheel_available else "warning: no wheel published"
    checks["sdist"] = "pass" if metadata.sdist_available else "warning: no source distribution published"
    checks["provenance"] = "pass" if metadata.provenance_available else "unknown: PyPI JSON exposes no attestation for the latest files"
    checks["signature"] = "pass" if metadata.signed_files else "unknown: no detached signature advertised"

    current_python = python_version or _python_version_string()
    python_satisfied = _version_satisfies_spec(current_python, metadata.requires_python)
    if python_satisfied is True:
        checks["python"] = f"pass: Python {current_python} satisfies {metadata.requires_python or '<none>'}"
    elif python_satisfied is False:
        checks["python"] = f"fail: Python {current_python} does not satisfy {metadata.requires_python}"
        issues.append(checks["python"])
    else:
        checks["python"] = f"unknown: could not evaluate Requires-Python {metadata.requires_python or '<none>'}"

    if metadata.wheel_metadata_checked and metadata.entry_points:
        checks["entry_point"] = f"pass: {', '.join(metadata.entry_points)}"
    elif metadata.wheel_metadata_checked:
        checks["entry_point"] = "fail: latest wheel has no agilab.apps entry point"
        issues.append(checks["entry_point"])
    else:
        checks["entry_point"] = "unknown: wheel metadata was not inspected"

    checks.update(_dependency_compatibility(metadata.requires_dist))
    for key, detail in checks.items():
        if key.endswith("_compatibility") and detail.startswith("fail:"):
            issues.append(detail)

    return PypiAppPreflight(
        "fail" if issues else "pass",
        normalized,
        package,
        metadata=metadata,
        checks=checks,
        issues=tuple(issues),
    )


def installed_app_package_names(apps: Iterable[InstalledPypiApp] | None = None) -> tuple[str, ...]:
    listed = tuple(apps) if apps is not None else list_installed_pypi_apps()
    return tuple(sorted({app.package for app in listed}, key=str.lower))


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _print_table(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> None:
    if not rows:
        print("No entries.")
        return
    widths = {
        column: max(len(column), *(len(str(row.get(column, ""))) for row in rows))
        for column in columns
    }
    print("  ".join(column.ljust(widths[column]) for column in columns))
    print("  ".join("-" * widths[column] for column in columns))
    for row in rows:
        print("  ".join(str(row.get(column, "")).ljust(widths[column]) for column in columns))


def _app_list(args: argparse.Namespace) -> int:
    apps = [app.as_dict() for app in list_installed_pypi_apps()]
    if args.json:
        _print_json({"apps": apps})
    else:
        _print_table(apps, ("package", "version", "provider", "project_root"))
    return 0


def _app_search(args: argparse.Namespace) -> int:
    packages = search_promoted_pypi_app_catalog(args.query or "")
    rows = [{"package": package, "source": "promoted-catalog"} for package in packages]
    if args.json:
        _print_json({"packages": rows})
    else:
        _print_table(rows, ("package", "source"))
    return 0


def _app_check(args: argparse.Namespace) -> int:
    try:
        result = preflight_pypi_app_install(args.requirement)
    except ValueError as exc:
        if args.json:
            _print_json({"status": "fail", "issues": [str(exc)]})
        else:
            print(str(exc), file=sys.stderr)
        return 2
    if args.json:
        _print_json(result.as_dict())
    else:
        print(f"{result.status}: {result.requirement}")
        for key, value in result.checks.items():
            print(f"- {key}: {value}")
        if result.metadata:
            print(f"- version: {result.metadata.version}")
            print(f"- url: {result.metadata.package_url}")
        for issue in result.issues:
            print(f"! {issue}")
    return 0 if result.status == "pass" else 1


def _run_management_command(
    result: PypiAppCommandResult,
    *,
    json_output: bool,
) -> int:
    if json_output:
        _print_json(result.as_dict())
    else:
        print(f"{result.status}: {' '.join(result.command)}")
        if result.output_tail:
            print(result.output_tail)
    return 0 if result.status == "success" else result.returncode or 1


def _app_install(args: argparse.Namespace) -> int:
    requirement = normalize_pypi_app_requirement(args.requirement)
    if args.dry_run:
        command = pypi_app_install_command(requirement)
        payload = {"requirement": requirement, "command": list(command)}
        if args.json:
            _print_json(payload)
        else:
            print(" ".join(command))
        return 0
    if not args.skip_preflight:
        preflight = preflight_pypi_app_install(requirement)
        if preflight.status != "pass":
            if args.json:
                _print_json(preflight.as_dict())
            else:
                print(f"preflight failed for {requirement}", file=sys.stderr)
                for issue in preflight.issues:
                    print(f"- {issue}", file=sys.stderr)
            return 1
    return _run_management_command(run_pypi_app_install(requirement), json_output=args.json)


def _app_update(args: argparse.Namespace) -> int:
    if args.all:
        packages = installed_app_package_names()
        if not packages:
            if args.json:
                _print_json({"updated": []})
            else:
                print("No installed PyPI app packages found.")
            return 0
        results = [run_pypi_app_install(package).as_dict() for package in packages]
        if args.json:
            _print_json({"updated": results})
        else:
            for result in results:
                print(f"{result['status']}: {result['requirement']}")
        return 0 if all(result["status"] == "success" for result in results) else 1
    if not args.requirement:
        raise SystemExit("agilab app update requires a package or --all")
    return _run_management_command(
        run_pypi_app_install(args.requirement),
        json_output=args.json,
    )


def _app_remove(args: argparse.Namespace) -> int:
    if args.dry_run:
        command = pypi_app_uninstall_command(args.requirement)
        payload = {"requirement": pypi_app_package_name(args.requirement), "command": list(command)}
        if args.json:
            _print_json(payload)
        else:
            print(" ".join(command))
        return 0
    return _run_management_command(
        run_pypi_app_uninstall(args.requirement),
        json_output=args.json,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage AGILAB PyPI app packages.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List installed agi-app-* packages.")
    list_parser.add_argument("--json", action="store_true")
    list_parser.set_defaults(func=_app_list)

    search_parser = subparsers.add_parser("search", help="Search the promoted agi-app-* package catalog.")
    search_parser.add_argument("query", nargs="?")
    search_parser.add_argument("--json", action="store_true")
    search_parser.set_defaults(func=_app_search)

    check_parser = subparsers.add_parser("check", help="Run PyPI metadata and compatibility preflight.")
    check_parser.add_argument("requirement")
    check_parser.add_argument("--json", action="store_true")
    check_parser.set_defaults(func=_app_check)

    install_parser = subparsers.add_parser("install", help="Install one trusted agi-app-* package.")
    install_parser.add_argument("requirement")
    install_parser.add_argument("--skip-preflight", action="store_true")
    install_parser.add_argument("--dry-run", action="store_true")
    install_parser.add_argument("--json", action="store_true")
    install_parser.set_defaults(func=_app_install)

    update_parser = subparsers.add_parser("update", help="Update one installed agi-app-* package or all installed app packages.")
    update_parser.add_argument("requirement", nargs="?")
    update_parser.add_argument("--all", action="store_true")
    update_parser.add_argument("--json", action="store_true")
    update_parser.set_defaults(func=_app_update)

    remove_parser = subparsers.add_parser("remove", help="Remove one installed agi-app-* package.")
    remove_parser.add_argument("requirement")
    remove_parser.add_argument("--dry-run", action="store_true")
    remove_parser.add_argument("--json", action="store_true")
    remove_parser.set_defaults(func=_app_remove)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    return args.func(args)
