from __future__ import annotations

import importlib
import importlib.util
import shlex
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable, Mapping, MutableMapping


class MixedCheckoutImportError(ImportError):
    """Raised when AGILAB code is imported from a different checkout."""


def _resolve_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve(strict=False)


def resolve_package_root(current_file: str | Path, package_name: str = "agilab") -> Path:
    current_path = _resolve_path(current_file)
    search_root = current_path if current_path.is_dir() else current_path.parent
    for candidate in (search_root, *search_root.parents):
        if candidate.name == package_name and (candidate / "__init__.py").exists():
            return candidate
    raise RuntimeError(f"Unable to resolve {package_name} package root from {current_path}")


def _module_origin_paths(module: Any) -> list[Path]:
    candidates: list[Path] = []
    module_file = getattr(module, "__file__", None)
    if module_file:
        candidates.append(_resolve_path(module_file))
    module_path = getattr(module, "__path__", None)
    if module_path:
        for entry in module_path:
            candidates.append(_resolve_path(entry))
    seen: set[Path] = set()
    result: list[Path] = []
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        result.append(path)
    return result


def _allowed_roots(expected_root: Path) -> set[Path]:
    roots = {expected_root}
    if len(expected_root.parents) >= 2:
        roots.add(expected_root.parents[1])
    return roots


def _origin_root(origin: Path) -> Path:
    if origin.is_file():
        return origin.parent
    return origin


def _paths_outside_expected(origins: Iterable[Path], expected_root: Path) -> list[Path]:
    allowed_roots = _allowed_roots(expected_root)
    outside: list[Path] = []
    for origin in origins:
        origin_root = _origin_root(origin)
        if any(origin_root == root or root in origin_root.parents for root in allowed_roots):
            continue
        outside.append(origin)
    return outside


def _mixed_checkout_message(
    *,
    current_file: str | Path,
    expected_root: Path,
    actual_paths: Iterable[Path],
    module_name: str,
) -> str:
    actual_display = ", ".join(str(path) for path in actual_paths) or "<unknown>"
    return (
        f"Mixed AGILAB checkout detected while importing {module_name!r}. "
        f"Current file {Path(current_file).resolve()} expects package root {expected_root}, "
        f"but Python resolved AGILAB from {actual_display}. "
        "Remove stale AGILAB checkout paths from PYTHONPATH/sys.path and relaunch."
    )


def assert_agilab_checkout_alignment(current_file: str | Path, package_name: str = "agilab") -> Path:
    expected_root = resolve_package_root(current_file, package_name=package_name)
    package_module = sys.modules.get(package_name)
    if package_module is None:
        return expected_root
    package_origins = _module_origin_paths(package_module)
    outside = _paths_outside_expected(package_origins, expected_root)
    if outside:
        raise MixedCheckoutImportError(
            _mixed_checkout_message(
                current_file=current_file,
                expected_root=expected_root,
                actual_paths=outside,
                module_name=package_name,
            )
        )
    return expected_root


def _source_root_for_package_root(package_root: Path, package_name: str = "agilab") -> Path | None:
    if len(package_root.parents) < 2:
        return None
    source_root = package_root.parents[1]
    if (source_root / "src" / package_name / "About_agilab.py").exists():
        return source_root.resolve(strict=False)
    return None


def _source_root_from_candidate(candidate: Path, package_name: str = "agilab") -> Path | None:
    candidate_root = candidate.resolve(strict=False)
    if (candidate_root / "src" / package_name / "About_agilab.py").exists():
        return candidate_root
    return None


def _source_root_for_path_entry(entry: str, package_name: str = "agilab") -> Path | None:
    entry_path = _resolve_path(entry or ".")
    candidates = [entry_path, entry_path.parent, *entry_path.parents]
    seen: set[Path] = set()
    for candidate in candidates:
        candidate_root = candidate.resolve(strict=False)
        if candidate_root in seen:
            continue
        seen.add(candidate_root)
        source_root = _source_root_from_candidate(candidate_root, package_name=package_name)
        if source_root is not None:
            return source_root
    return None


def _source_root_for_python_executable(executable: str | Path, package_name: str = "agilab") -> Path | None:
    # uv-managed venv Python binaries are often symlinks to a shared interpreter.
    # Inspect the lexical venv path before resolving, otherwise the checkout root
    # is lost and a wrong PyCharm SDK is misreported as a generic sys.path issue.
    executable_path = Path(executable).expanduser()
    parts = executable_path.parts
    if ".venv" not in parts:
        return None
    idx = parts.index(".venv")
    if idx == 0:
        return None
    source_root = Path(*parts[:idx]).resolve(strict=False)
    return _source_root_from_candidate(source_root, package_name=package_name)


def _powershell_single_quote(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _format_rebind_commands(source_root: Path) -> tuple[str, str]:
    unix_command = (
        f"cd {shlex.quote(str(source_root))} && "
        "AGILAB_PYCHARM_ALLOW_SDK_REBIND=1 "
        "uv --preview-features extra-build-dependencies run python pycharm/setup_pycharm.py"
    )
    powershell_command = (
        f"Set-Location -LiteralPath {_powershell_single_quote(source_root)}\n"
        "$env:AGILAB_PYCHARM_ALLOW_SDK_REBIND = '1'\n"
        "uv --preview-features extra-build-dependencies run python pycharm/setup_pycharm.py"
    )
    return unix_command, powershell_command


def _format_expected_sdk_paths(source_root: Path) -> tuple[Path, Path]:
    return (
        source_root / ".venv" / "bin" / "python",
        source_root / ".venv" / "Scripts" / "python.exe",
    )


def _format_python_environment_mismatch_message(
    *,
    current_file: str | Path,
    expected_source_root: Path,
    actual_source_root: Path,
    executable: str | Path,
) -> str:
    expected_unix_python, expected_windows_python = _format_expected_sdk_paths(expected_source_root)
    unix_setup_command, powershell_setup_command = _format_rebind_commands(expected_source_root)
    return (
        "Mixed AGILAB Python environment detected.\n\n"
        "AGILAB is being launched from one source checkout, but Python belongs to another checkout.\n"
        f"- Launched file: {Path(current_file).resolve()}\n"
        f"- Expected checkout: {expected_source_root}\n"
        f"- Detected Python checkout: {actual_source_root}\n"
        f"- sys.executable: {Path(executable).expanduser()}\n"
        f"- Expected PyCharm uv SDK path (macOS/Linux): {expected_unix_python}\n"
        f"- Expected PyCharm uv SDK path (Windows): {expected_windows_python}\n\n"
        "Why this usually happens:\n"
        "- PyCharm is still using the uv SDK created from an older AGILAB clone.\n"
        "- A previous Streamlit/PyCharm run is still alive after switching source trees.\n"
        "- PYTHONPATH or the run configuration still contains paths from the old checkout.\n\n"
        "How to fix this checkout:\n"
        "1. Stop the current Streamlit/PyCharm run.\n"
        "2. Rebind PyCharm to the checkout you are launching.\n\n"
        "macOS/Linux:\n"
        f"   {unix_setup_command}\n\n"
        "Windows PowerShell:\n"
        f"   {powershell_setup_command.replace(chr(10), chr(10) + '   ')}\n\n"
        "3. In PyCharm, select SDK 'uv (agilab)' and verify it points to:\n"
        f"   {expected_unix_python}\n"
        "   or on Windows:\n"
        f"   {expected_windows_python}\n"
        "4. Relaunch AGILAB from the same checkout.\n\n"
        "If you intended to run the other checkout instead, open and launch that checkout directly:\n"
        f"   {actual_source_root}"
    )


def _foreign_source_roots_on_sys_path(
    expected_source_root: Path,
    package_name: str = "agilab",
) -> list[tuple[Path, str]]:
    foreign_roots: list[tuple[Path, str]] = []
    seen: set[Path] = set()
    for raw_entry in sys.path:
        source_root = _source_root_for_path_entry(raw_entry, package_name=package_name)
        if source_root is None or source_root == expected_source_root or source_root in seen:
            continue
        seen.add(source_root)
        foreign_roots.append((source_root, raw_entry or "."))
    return foreign_roots


def _sys_path_foreign_root_guidance(foreign_roots: Iterable[tuple[Path, str]]) -> str:
    has_site_packages = any(
        ".venv" in Path(entry).parts and "site-packages" in Path(entry).parts
        for _root, entry in foreign_roots
    )
    if has_site_packages:
        return (
            " The stale entry is a virtualenv site-packages path; stop the old Streamlit/PyCharm "
            "run process and select the matching uv SDK, or rerun pycharm/setup_pycharm.py from "
            "the intended source root."
        )
    return ""


def assert_sys_path_checkout_alignment(current_file: str | Path, package_name: str = "agilab") -> Path:
    """Reject source runs that keep another AGILAB checkout on ``sys.path``."""
    expected_package_root = resolve_package_root(current_file, package_name=package_name)
    expected_source_root = _source_root_for_package_root(expected_package_root, package_name=package_name)
    if expected_source_root is None:
        return expected_package_root

    foreign_roots = _foreign_source_roots_on_sys_path(expected_source_root, package_name=package_name)
    if foreign_roots:
        details = ", ".join(f"{root} via sys.path entry {entry!r}" for root, entry in foreign_roots)
        guidance = _sys_path_foreign_root_guidance(foreign_roots)
        raise MixedCheckoutImportError(
            "Mixed AGILAB sys.path detected. "
            f"Current file {Path(current_file).resolve()} belongs to {expected_source_root}, "
            f"but Python can also resolve AGILAB from {details}. "
            "Remove stale PYTHONPATH/PyCharm content roots and relaunch. If you intentionally "
            "switched checkout, rerun pycharm/setup_pycharm.py from the intended source root."
            f"{guidance}"
        )
    return expected_package_root


def assert_python_environment_alignment(current_file: str | Path, package_name: str = "agilab") -> Path:
    """Reject source runs that use a Python venv from another AGILAB checkout."""
    expected_package_root = resolve_package_root(current_file, package_name=package_name)
    expected_source_root = _source_root_for_package_root(expected_package_root, package_name=package_name)
    actual_source_root = _source_root_for_python_executable(sys.executable, package_name=package_name)
    if (
        expected_source_root is not None
        and actual_source_root is not None
        and actual_source_root != expected_source_root
    ):
        raise MixedCheckoutImportError(
            _format_python_environment_mismatch_message(
                current_file=current_file,
                expected_source_root=expected_source_root,
                actual_source_root=actual_source_root,
                executable=sys.executable,
            )
        )
    return expected_package_root


def _load_module_from_path(module_name: str, fallback_path: str | Path, fallback_name: str | None = None) -> ModuleType:
    module_path = _resolve_path(fallback_path)
    synthetic_name = fallback_name or f"{module_name.replace('.', '_')}_fallback"
    spec = importlib.util.spec_from_file_location(synthetic_name, module_path)
    if spec is None or spec.loader is None:
        raise ModuleNotFoundError(f"Unable to load local fallback module at {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[synthetic_name] = module
    spec.loader.exec_module(module)
    return module


def _should_fallback_module_not_found(exc: ModuleNotFoundError, module_name: str, package_name: str) -> bool:
    missing_name = str(getattr(exc, "name", "") or "")
    if missing_name in {package_name, module_name}:
        return True
    return missing_name.startswith(f"{package_name}.")


def load_local_module(
    module_name: str,
    *,
    current_file: str | Path,
    fallback_path: str | Path,
    fallback_name: str | None = None,
    package_name: str = "agilab",
) -> ModuleType:
    expected_root = assert_python_environment_alignment(current_file, package_name=package_name)
    assert_sys_path_checkout_alignment(current_file, package_name=package_name)
    assert_agilab_checkout_alignment(current_file, package_name=package_name)
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if not _should_fallback_module_not_found(exc, module_name, package_name):
            raise
        module = _load_module_from_path(module_name, fallback_path, fallback_name=fallback_name)
    except ImportError as exc:
        try:
            assert_agilab_checkout_alignment(current_file, package_name=package_name)
        except MixedCheckoutImportError as mixed_exc:
            raise mixed_exc from exc
        raise

    outside = _paths_outside_expected(_module_origin_paths(module), expected_root)
    if outside:
        raise MixedCheckoutImportError(
            _mixed_checkout_message(
                current_file=current_file,
                expected_root=expected_root,
                actual_paths=outside,
                module_name=module_name,
            )
        )
    return module


def import_agilab_module(
    module_name: str,
    *,
    current_file: str | Path,
    fallback_path: str | Path,
    fallback_name: str | None = None,
    package_name: str = "agilab",
) -> ModuleType:
    """Load an AGILAB module while preserving mixed-checkout protections.

    Prefer this helper in new code so module dependencies stay explicit at the
    call site instead of being injected into ``globals()``.
    """
    return load_local_module(
        module_name,
        current_file=current_file,
        fallback_path=fallback_path,
        fallback_name=fallback_name,
        package_name=package_name,
    )


def import_agilab_symbols(
    target_globals: MutableMapping[str, Any],
    module_name: str,
    bindings: Mapping[str, str] | Iterable[str],
    *,
    current_file: str | Path,
    fallback_path: str | Path,
    fallback_name: str | None = None,
) -> ModuleType:
    """Compatibility helper for legacy call sites that mutate globals()."""
    module = import_agilab_module(
        module_name,
        current_file=current_file,
        fallback_path=fallback_path,
        fallback_name=fallback_name,
    )
    if isinstance(bindings, Mapping):
        binding_items = list(bindings.items())
    else:
        binding_items = [(name, name) for name in bindings]
    for attribute_name, target_name in binding_items:
        try:
            target_globals[target_name] = getattr(module, attribute_name)
        except AttributeError as exc:
            raise ImportError(f"cannot import name {attribute_name!r} from {module_name!r}") from exc
    return module
