from __future__ import annotations

import importlib
import importlib.util
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
    expected_root = assert_agilab_checkout_alignment(current_file, package_name=package_name)
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
