"""Public AGILAB analysis page bundle provider."""

from __future__ import annotations

import importlib.metadata
import importlib.util
from dataclasses import dataclass
from pathlib import Path

PAGE_BUNDLE_ENTRYPOINT_NAMES = ("{module}.py", "main.py", "app.py")
PAGE_BUNDLE_ENTRYPOINT_GROUP = "agilab.pages"
PUBLIC_PAGE_MODULES = (
    "view_barycentric",
    "view_data_io_decision",
    "view_forecast_analysis",
    "view_inference_analysis",
    "view_maps",
    "view_maps_3d",
    "view_maps_network",
    "view_queue_resilience",
    "view_relay_resilience",
    "view_release_decision",
    "view_shap_explanation",
    "view_training_analysis",
)


@dataclass(frozen=True, slots=True)
class PageBundle:
    """Resolved metadata for one AGILAB page bundle."""

    name: str
    root_path: Path
    script_path: Path
    inline_renderer: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "module": self.name,
            "root_path": self.root_path.as_posix(),
            "script_path": self.script_path.as_posix(),
            "inline_renderer": self.inline_renderer,
        }


def bundles_root() -> Path:
    """Return the installed root containing AGILAB page bundles."""

    package_root = Path(__file__).resolve().parent
    if _has_bundle_payload(package_root):
        return package_root
    for candidate in _source_checkout_bundle_roots(package_root):
        if _has_bundle_payload(candidate):
            return candidate
    return package_root


def iter_bundles(pages_root: str | Path | None = None) -> tuple[PageBundle, ...]:
    """Return all page bundles below ``pages_root`` in deterministic order."""

    include_installed = pages_root is None
    root = _coerce_root(pages_root)

    bundles: list[PageBundle] = []
    seen: set[str] = set()
    if root is not None and root.exists() and root.is_dir():
        for script in sorted(root.glob("*.py")):
            if script.name == "__init__.py" or script.name.startswith("."):
                continue
            bundle = PageBundle(
                name=script.stem,
                root_path=root.resolve(strict=False),
                script_path=script.resolve(strict=False),
                inline_renderer=_inline_renderer_target(script),
            )
            bundles.append(bundle)
            seen.add(_normalize_bundle_name(bundle.name))

        for bundle_dir in sorted(path for path in root.iterdir() if path.is_dir() and not path.name.startswith(".")):
            key = _normalize_bundle_name(bundle_dir.name)
            if not key or key in seen:
                continue
            bundle = resolve_bundle(bundle_dir.name, pages_root=root)
            if bundle is None:
                continue
            bundles.append(bundle)
            seen.add(key)

    if include_installed:
        for bundle in _iter_installed_bundles():
            key = _normalize_bundle_name(bundle.name)
            if not key or key in seen:
                continue
            bundles.append(bundle)
            seen.add(key)
    return tuple(sorted(bundles, key=lambda bundle: bundle.name.casefold()))


def resolve_bundle(module_name: str, pages_root: str | Path | None = None) -> PageBundle | None:
    """Resolve a page bundle by module name."""

    root = _coerce_root(pages_root)
    name = _normalize_bundle_name(module_name)
    if not name:
        return None

    if root is not None:
        direct_file = root / f"{name}.py"
        if direct_file.exists() and direct_file.is_file():
            script = direct_file.resolve(strict=False)
            return PageBundle(
                name=name,
                root_path=root.resolve(strict=False),
                script_path=script,
                inline_renderer=_inline_renderer_target(script),
            )

        bundle_dir = root / name
        if bundle_dir.exists() and bundle_dir.is_dir():
            script = _bundle_entrypoint(bundle_dir, name)
            if script is not None:
                return PageBundle(
                    name=name,
                    root_path=bundle_dir.resolve(strict=False),
                    script_path=script,
                    inline_renderer=_inline_renderer_target(script),
                )

    return _resolve_installed_bundle(name)


def _iter_installed_bundles() -> tuple[PageBundle, ...]:
    bundles: list[PageBundle] = []
    seen: set[str] = set()
    for entry_point in _page_entry_points():
        bundle = _bundle_from_entry_point(entry_point)
        if bundle is None:
            continue
        key = _normalize_bundle_name(bundle.name)
        if not key or key in seen:
            continue
        bundles.append(bundle)
        seen.add(key)
    for module_name in PUBLIC_PAGE_MODULES:
        key = _normalize_bundle_name(module_name)
        if not key or key in seen:
            continue
        bundle = _bundle_from_installed_module(module_name)
        if bundle is None:
            continue
        bundles.append(bundle)
        seen.add(key)
    return tuple(sorted(bundles, key=lambda bundle: bundle.name.casefold()))


def _resolve_installed_bundle(module_name: str) -> PageBundle | None:
    name = _normalize_bundle_name(module_name)
    for entry_point in _page_entry_points():
        if _normalize_bundle_name(entry_point.name) != name:
            continue
        bundle = _bundle_from_entry_point(entry_point)
        if bundle is not None:
            return bundle
    return _bundle_from_installed_module(name)


def _page_entry_points() -> tuple[importlib.metadata.EntryPoint, ...]:
    try:
        entry_points = importlib.metadata.entry_points()
        if hasattr(entry_points, "select"):
            selected = entry_points.select(group=PAGE_BUNDLE_ENTRYPOINT_GROUP)
        else:
            selected = entry_points.get(PAGE_BUNDLE_ENTRYPOINT_GROUP, ())
    except Exception:
        return ()
    return tuple(sorted(selected, key=lambda entry_point: entry_point.name.casefold()))


def _bundle_from_entry_point(entry_point: importlib.metadata.EntryPoint) -> PageBundle | None:
    name = _normalize_bundle_name(entry_point.name)
    if not name:
        return None
    try:
        root_factory = entry_point.load()
        root = Path(root_factory()).expanduser().resolve(strict=False)
    except Exception:
        return None
    return _bundle_from_root(name, root)


def _bundle_from_installed_module(module_name: str) -> PageBundle | None:
    name = _normalize_bundle_name(module_name)
    if not name:
        return None
    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, AttributeError, ValueError):
        return None
    if spec is None or spec.submodule_search_locations is None:
        return None
    for location in spec.submodule_search_locations:
        bundle = _bundle_from_root(name, Path(location).expanduser().resolve(strict=False))
        if bundle is not None:
            return bundle
    return None


def _bundle_from_root(name: str, root: Path) -> PageBundle | None:
    if not root.exists() or not root.is_dir():
        return None
    script = _bundle_entrypoint(root, name)
    if script is None:
        return None
    return PageBundle(
        name=name,
        root_path=root.resolve(strict=False),
        script_path=script,
        inline_renderer=_inline_renderer_target(script),
    )


def script_path(module_name: str, pages_root: str | Path | None = None) -> Path | None:
    """Return the Streamlit script path for a page bundle, if available."""

    bundle = resolve_bundle(module_name, pages_root=pages_root)
    return bundle.script_path if bundle is not None else None


def inline_renderer_target(module_name: str, pages_root: str | Path | None = None) -> str:
    """Return the notebook inline renderer target for a page bundle, if present."""

    bundle = resolve_bundle(module_name, pages_root=pages_root)
    return bundle.inline_renderer if bundle is not None else ""


def _bundle_entrypoint(bundle_dir: Path, module_name: str) -> Path | None:
    candidates: list[Path] = []
    for pattern_root in (bundle_dir, bundle_dir / "src" / module_name):
        candidates.extend(pattern_root / pattern.format(module=module_name) for pattern in PAGE_BUNDLE_ENTRYPOINT_NAMES)
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate.resolve(strict=False)
    fallback = sorted((bundle_dir / "src").glob("*/view_*.py"))
    return fallback[0].resolve(strict=False) if fallback else None


def _inline_renderer_target(script: Path) -> str:
    try:
        candidate = script.resolve(strict=False).with_name("notebook_inline.py")
    except (OSError, RuntimeError, TypeError, ValueError):
        return ""
    if not candidate.exists() or not candidate.is_file():
        return ""
    return f"{candidate}:render_inline"


def _coerce_root(value: str | Path | None = None) -> Path | None:
    if value is None or str(value).strip() == "":
        return bundles_root()
    try:
        return Path(value).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def _has_bundle_payload(root: Path) -> bool:
    try:
        if not root.exists() or not root.is_dir():
            return False
        if any(path.is_file() and path.name != "__init__.py" and not path.name.startswith(".") for path in root.glob("*.py")):
            return True
        for bundle_dir in sorted(path for path in root.iterdir() if path.is_dir() and not path.name.startswith(".")):
            if _bundle_entrypoint(bundle_dir, bundle_dir.name) is not None:
                return True
    except OSError:
        return False
    return False


def _source_checkout_bundle_roots(package_root: Path) -> tuple[Path, ...]:
    candidates: list[Path] = []
    seen: set[str] = set()
    for parent in package_root.parents:
        for candidate in (parent / "apps-pages", parent / "src" / "agilab" / "apps-pages"):
            candidate_text = candidate.as_posix()
            if candidate_text in seen:
                continue
            seen.add(candidate_text)
            candidates.append(candidate)
    return tuple(candidates)


def _normalize_bundle_name(value: str | None) -> str:
    return str(value or "").strip()


__all__ = [
    "PAGE_BUNDLE_ENTRYPOINT_NAMES",
    "PAGE_BUNDLE_ENTRYPOINT_GROUP",
    "PUBLIC_PAGE_MODULES",
    "PageBundle",
    "bundles_root",
    "inline_renderer_target",
    "iter_bundles",
    "resolve_bundle",
    "script_path",
]
