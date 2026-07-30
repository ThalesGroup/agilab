"""Read Python import layouts without executing environment-owned code."""

from __future__ import annotations

import ast
import json
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urlsplit


_EDITABLE_FINDER_PREFIX = "__editable___"
_EDITABLE_FINDER_SUFFIX = "_finder"
_MODULE_SUFFIXES = (".py", ".so", ".pyd", ".dylib")


@dataclass(frozen=True)
class PthImportLayout:
    """Filesystem roots and explicit module mappings declared by ``.pth`` files."""

    roots: tuple[Path, ...] = ()
    module_locations: tuple[tuple[str, Path], ...] = ()

    def exposes_module(self, module: str) -> bool:
        """Return whether an explicit editable mapping exposes ``module``."""

        top_level = module.partition(".")[0]
        return any(
            name.partition(".")[0] == top_level for name, _path in self.module_locations
        )


def inspect_pth_import_layout(site_packages: Path) -> PthImportLayout:
    """Inspect plain paths and canonical setuptools PEP 660 finders safely.

    Executable ``.pth`` files and their finder modules are parsed as syntax only.
    They are never imported or executed.
    """

    roots: list[Path] = []
    module_locations: list[tuple[str, Path]] = []
    parsed_finders: set[Path] = set()
    try:
        pth_files = sorted(site_packages.glob("*.pth"))
    except OSError:
        return PthImportLayout()

    for pth_file in pth_files:
        try:
            lines = pth_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("import "):
                finder_module = _canonical_setuptools_finder_module(line)
                if finder_module is None:
                    continue
                finder_path = _finder_path(site_packages, finder_module)
                if finder_path is None or finder_path in parsed_finders:
                    continue
                parsed_finders.add(finder_path)
                module_locations.extend(
                    _finder_module_locations(finder_path, site_packages)
                )
                continue

            candidate = Path(line).expanduser()
            if not candidate.is_absolute():
                candidate = site_packages / candidate
            candidate = _resolve_without_failure(candidate)
            try:
                if candidate.is_dir():
                    roots.append(candidate)
            except OSError:
                continue

    return PthImportLayout(
        roots=tuple(dict.fromkeys(roots)),
        module_locations=tuple(dict.fromkeys(module_locations)),
    )


def top_level_modules_from_distribution(
    site_packages: Iterable[Path],
    distribution_name: str,
) -> tuple[str, ...]:
    """Return installed top-level import names for a distribution."""

    normalized = _normalized_distribution_name(distribution_name)
    modules: list[str] = []
    for site_package in site_packages:
        try:
            metadata_files = sorted(site_package.glob("*.dist-info/METADATA"))
        except OSError:
            continue
        for metadata_file in metadata_files:
            if _metadata_distribution_name(metadata_file) != normalized:
                continue
            modules.extend(_top_level_modules_from_metadata_dir(metadata_file.parent))
    return tuple(dict.fromkeys(modules))


def is_typing_only_distribution(distribution_name: str) -> bool:
    """Return whether a distribution intentionally supplies typing data only."""

    normalized = _normalized_distribution_name(distribution_name)
    return normalized.endswith("-stubs") or normalized.startswith("types-")


def distribution_installation_matches(
    site_packages: Iterable[Path],
    distribution_name: str,
    *,
    expected_projects: Iterable[Path] = (),
) -> bool:
    """Return whether matching distribution metadata is installed.

    When local source projects are supplied, a matching ``direct_url.json``
    must point at one of them.  This prevents a stray importable directory or a
    stale editable finder from satisfying an installation postcondition.
    """

    expected = tuple(
        dict.fromkeys(
            _resolve_without_failure(path.expanduser()) for path in expected_projects
        )
    )
    for metadata_dir in _distribution_metadata_dirs(site_packages, distribution_name):
        if not expected:
            return True
        direct_project = _direct_url_project(metadata_dir / "direct_url.json")
        if direct_project is not None and any(
            _same_path(direct_project, project) for project in expected
        ):
            return True
    return False


def top_level_modules_from_project(project_root: Path) -> tuple[str, ...]:
    """Return explicit setuptools top-level imports declared by a source project."""

    try:
        data = tomllib.loads(
            (project_root / "pyproject.toml").read_text(encoding="utf-8")
        )
    except (OSError, tomllib.TOMLDecodeError):
        return ()
    setuptools = data.get("tool", {}).get("setuptools", {})
    if not isinstance(setuptools, dict):
        return ()
    modules: list[str] = []
    for key in ("packages", "py-modules"):
        values = setuptools.get(key)
        if not isinstance(values, list):
            continue
        for value in values:
            if not isinstance(value, str):
                continue
            module = value.strip().partition(".")[0]
            if module.isidentifier():
                modules.append(module)
    return tuple(dict.fromkeys(modules))


def _canonical_setuptools_finder_module(line: str) -> str | None:
    try:
        tree = ast.parse(line, mode="exec")
    except SyntaxError:
        return None
    if len(tree.body) != 2:
        return None
    import_node, install_node = tree.body
    if not isinstance(import_node, ast.Import) or len(import_node.names) != 1:
        return None
    imported = import_node.names[0]
    module = imported.name
    if imported.asname is not None or not module.isidentifier():
        return None
    if not module.startswith(_EDITABLE_FINDER_PREFIX) or not module.endswith(
        _EDITABLE_FINDER_SUFFIX
    ):
        return None
    if not isinstance(install_node, ast.Expr) or not isinstance(
        install_node.value, ast.Call
    ):
        return None
    call = install_node.value
    if call.args or call.keywords or not isinstance(call.func, ast.Attribute):
        return None
    if call.func.attr != "install" or not isinstance(call.func.value, ast.Name):
        return None
    return module if call.func.value.id == module else None


def _finder_path(site_packages: Path, finder_module: str) -> Path | None:
    candidate = site_packages / f"{finder_module}.py"
    try:
        site_root = site_packages.resolve(strict=True)
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(site_root)
        if not resolved.is_file():
            return None
    except (FileNotFoundError, OSError, RuntimeError, ValueError):
        return None
    return resolved


def _finder_module_locations(
    finder_path: Path,
    site_packages: Path,
) -> tuple[tuple[str, Path], ...]:
    try:
        tree = ast.parse(
            finder_path.read_text(encoding="utf-8", errors="replace"),
            filename=str(finder_path),
        )
    except (OSError, SyntaxError, ValueError):
        return ()
    if any(
        not isinstance(
            node,
            (
                ast.Import,
                ast.ImportFrom,
                ast.Assign,
                ast.AnnAssign,
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.ClassDef,
            ),
        )
        for node in tree.body
    ):
        return ()

    mapping = _literal_assignment(tree, "MAPPING", expected_type=dict)
    namespaces = _literal_assignment(tree, "NAMESPACES", expected_type=dict)
    locations: list[tuple[str, Path]] = []

    if isinstance(mapping, dict):
        for module, raw_path in mapping.items():
            if not _valid_dotted_module(module) or not isinstance(raw_path, str):
                continue
            location = _import_location(raw_path, site_packages)
            if location is not None:
                locations.append((module, location))

    if isinstance(namespaces, dict):
        for module, raw_paths in namespaces.items():
            if not _valid_dotted_module(module) or not isinstance(
                raw_paths, list | tuple
            ):
                continue
            for raw_path in raw_paths:
                if not isinstance(raw_path, str):
                    continue
                location = _import_location(raw_path, site_packages, namespace=True)
                if location is not None:
                    locations.append((module, location))

    return tuple(dict.fromkeys(locations))


def _literal_assignment(
    tree: ast.Module,
    name: str,
    *,
    expected_type: type[dict],
) -> object | None:
    value_node: ast.expr | None = None
    for node in tree.body:
        candidate: ast.expr | None = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == name:
                candidate = node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id == name:
                candidate = node.value
        if candidate is None:
            continue
        if value_node is not None:
            return None
        value_node = candidate
    if value_node is None:
        return None
    try:
        value = ast.literal_eval(value_node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return None
    return value if isinstance(value, expected_type) else None


def _import_location(
    raw_path: str,
    site_packages: Path,
    *,
    namespace: bool = False,
) -> Path | None:
    if not raw_path.strip():
        return None
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = site_packages / candidate
    candidate = _resolve_without_failure(candidate)
    try:
        if namespace:
            return candidate if candidate.is_dir() else None
        if (candidate / "__init__.py").is_file():
            return candidate
        if any(candidate.with_suffix(suffix).is_file() for suffix in _MODULE_SUFFIXES):
            return candidate
        if any(candidate.parent.glob(f"{candidate.name}.*.so")) or any(
            candidate.parent.glob(f"{candidate.name}.*.pyd")
        ):
            return candidate
    except OSError:
        return None
    return None


def _resolve_without_failure(path: Path) -> Path:
    try:
        return path.resolve(strict=False)
    except OSError:
        return path


def _valid_dotted_module(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and all(part.isidentifier() for part in value.split("."))
    )


def _normalized_distribution_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value.strip()).strip("-").lower()


def _metadata_distribution_name(metadata_file: Path) -> str | None:
    try:
        for line in metadata_file.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines():
            if line.startswith("Name:"):
                return _normalized_distribution_name(line.partition(":")[2])
    except OSError:
        return None
    return None


def _distribution_metadata_dirs(
    site_packages: Iterable[Path],
    distribution_name: str,
) -> tuple[Path, ...]:
    normalized = _normalized_distribution_name(distribution_name)
    metadata_dirs: list[Path] = []
    for site_package in site_packages:
        try:
            metadata_files = sorted(site_package.glob("*.dist-info/METADATA"))
        except OSError:
            continue
        for metadata_file in metadata_files:
            if _metadata_distribution_name(metadata_file) == normalized:
                metadata_dirs.append(metadata_file.parent)
    return tuple(dict.fromkeys(metadata_dirs))


def _direct_url_project(direct_url_file: Path) -> Path | None:
    try:
        payload = json.loads(direct_url_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    url = payload.get("url") if isinstance(payload, dict) else None
    if not isinstance(url, str):
        return None
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "file":
        return None
    raw_path = unquote(parsed.path)
    if os.name == "nt" and re.match(r"^/[A-Za-z]:", raw_path):
        raw_path = raw_path[1:]
    elif parsed.netloc and parsed.netloc.lower() != "localhost":
        raw_path = f"//{parsed.netloc}{raw_path}"
    return _resolve_without_failure(Path(raw_path).expanduser()) if raw_path else None


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.samefile(right)
    except (FileNotFoundError, OSError):
        return _resolve_without_failure(left) == _resolve_without_failure(right)


def _top_level_modules_from_metadata_dir(metadata_dir: Path) -> tuple[str, ...]:
    modules: list[str] = []
    try:
        lines = (
            (metadata_dir / "top_level.txt")
            .read_text(
                encoding="utf-8",
                errors="replace",
            )
            .splitlines()
        )
    except OSError:
        lines = []
    for line in lines:
        module = line.strip()
        if (
            module
            and not module.startswith("#")
            and module.isidentifier()
            and not (module.startswith("__") and module.endswith("__"))
        ):
            modules.append(module)
    if modules:
        return tuple(dict.fromkeys(modules))

    try:
        record_lines = (
            (metadata_dir / "RECORD")
            .read_text(
                encoding="utf-8",
                errors="replace",
            )
            .splitlines()
        )
    except OSError:
        return ()
    for line in record_lines:
        module = _module_name_from_record_path(line)
        if module:
            modules.append(module)
    return tuple(dict.fromkeys(modules))


def _module_name_from_record_path(path_text: str) -> str | None:
    root = path_text.strip().split(",", 1)[0].replace("\\", "/").split("/", 1)[0]
    if not root or root.endswith((".dist-info", ".egg-info", ".data")):
        return None
    if root.endswith(".py"):
        module = root[:-3]
    elif root.endswith((".so", ".pyd", ".dylib")):
        module = root.split(".", 1)[0]
    elif "." in root:
        return None
    else:
        module = root
    if module.startswith("__editable__"):
        return None
    return module if module.isidentifier() else None
