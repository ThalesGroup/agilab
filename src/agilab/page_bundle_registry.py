"""Typed registry for AGILAB apps-page bundles."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PAGE_BUNDLE_SCHEMA = "agilab.page_bundle_registry.v1"
PAGE_BUNDLE_ENTRYPOINT_NAMES = ("{module}.py", "main.py", "app.py")


@dataclass(frozen=True, slots=True)
class PageBundleSpec:
    """Resolved metadata for one apps-page bundle."""

    name: str
    root_path: Path
    script_path: Path
    schema: str = PAGE_BUNDLE_SCHEMA
    source: str = "discovered"

    def __post_init__(self) -> None:
        if not _normalize_bundle_name(self.name):
            raise ValueError("Page bundle name must be a non-empty string")
        if not isinstance(self.root_path, Path):
            object.__setattr__(self, "root_path", Path(self.root_path))
        if not isinstance(self.script_path, Path):
            object.__setattr__(self, "script_path", Path(self.script_path))

    def as_row(self) -> dict[str, str]:
        """Return a stable row for diagnostics and documentation."""

        return {
            "schema": self.schema,
            "name": self.name,
            "root_path": self.root_path.as_posix(),
            "script_path": self.script_path.as_posix(),
            "source": self.source,
        }


class PageBundleRegistry:
    """Immutable registry for resolving apps-page bundles by name."""

    def __init__(self, bundles: Iterable[PageBundleSpec] = ()) -> None:
        self._bundles = tuple(sorted(bundles, key=lambda bundle: bundle.name.casefold()))
        self._by_name = self._build_lookup(self._bundles)

    @staticmethod
    def _build_lookup(bundles: tuple[PageBundleSpec, ...]) -> dict[str, PageBundleSpec]:
        lookup: dict[str, PageBundleSpec] = {}
        for bundle in bundles:
            key = _normalize_bundle_name(bundle.name)
            existing = lookup.get(key)
            if existing is not None:
                raise ValueError(
                    f"Duplicate apps-page bundle {bundle.name!r}: "
                    f"{existing.script_path} and {bundle.script_path}"
                )
            lookup[key] = bundle
        return lookup

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and _normalize_bundle_name(name) in self._by_name

    def __iter__(self) -> Iterator[PageBundleSpec]:
        return iter(self._bundles)

    def __len__(self) -> int:
        return len(self._bundles)

    @property
    def bundles(self) -> tuple[PageBundleSpec, ...]:
        """Return bundles in deterministic display order."""

        return self._bundles

    def names(self) -> tuple[str, ...]:
        """Return bundle names in deterministic display order."""

        return tuple(bundle.name for bundle in self._bundles)

    def get(self, name: str, default: Any = None) -> PageBundleSpec | Any:
        """Return a bundle by name, or ``default`` when absent."""

        return self._by_name.get(_normalize_bundle_name(name), default)

    def require(self, name: str) -> PageBundleSpec:
        """Return a bundle by name, raising a useful error when absent."""

        bundle = self.get(name)
        if bundle is not None:
            return bundle
        available = ", ".join(self.names()) or "<empty>"
        raise KeyError(f"Unknown apps-page bundle {name!r}. Available bundles: {available}")

    def select(self, names: Sequence[str]) -> tuple[PageBundleSpec, ...]:
        """Return configured bundles by name, preserving input order and removing duplicates."""

        selected: list[PageBundleSpec] = []
        seen: set[str] = set()
        for name in names:
            key = _normalize_bundle_name(name)
            if not key or key in seen:
                continue
            bundle = self.get(name)
            if bundle is None:
                continue
            seen.add(key)
            selected.append(bundle)
        return tuple(selected)

    def as_rows(self) -> list[dict[str, str]]:
        """Return registry rows suitable for rendering as a table."""

        return [bundle.as_row() for bundle in self._bundles]


def discover_page_bundles(
    pages_root: str | Path,
    *,
    require_pyproject: bool = False,
) -> PageBundleRegistry:
    """Discover apps-page bundles below ``pages_root``."""

    root = _coerce_root(pages_root)
    if root is None or not root.exists() or not root.is_dir():
        return PageBundleRegistry()

    bundles: list[PageBundleSpec] = []
    for script_path in sorted(root.glob("*.py")):
        if script_path.name == "__init__.py" or script_path.name.startswith("."):
            continue
        bundles.append(
            PageBundleSpec(
                name=script_path.stem,
                root_path=root,
                script_path=script_path.resolve(strict=False),
            )
        )

    for bundle_dir in sorted(path for path in root.iterdir() if path.is_dir() and not path.name.startswith(".")):
        bundle = discover_page_bundle(root, bundle_dir.name, require_pyproject=require_pyproject)
        if bundle is not None:
            bundles.append(bundle)
    return PageBundleRegistry(bundles)


def discover_page_bundle(
    pages_root: str | Path,
    module_name: str,
    *,
    require_pyproject: bool = False,
) -> PageBundleSpec | None:
    """Resolve one apps-page bundle under ``pages_root``."""

    root = _coerce_root(pages_root)
    name = _normalize_bundle_name(module_name)
    if root is None or not name:
        return None

    direct_file = root / f"{name}.py"
    if direct_file.exists() and direct_file.is_file():
        return PageBundleSpec(
            name=name,
            root_path=root,
            script_path=direct_file.resolve(strict=False),
        )

    bundle_dir = root / name
    if not bundle_dir.exists() or not bundle_dir.is_dir():
        return None
    if require_pyproject and not (bundle_dir / "pyproject.toml").exists():
        return None

    script_path = _bundle_entrypoint(bundle_dir, name)
    if script_path is None:
        return None
    return PageBundleSpec(
        name=name,
        root_path=bundle_dir.resolve(strict=False),
        script_path=script_path,
    )


def resolve_page_bundles(
    names_or_paths: Sequence[str],
    *,
    pages_root: str | Path,
    require_pyproject: bool = False,
) -> tuple[PageBundleSpec, ...]:
    """Resolve explicit apps-page names or paths."""

    registry = discover_page_bundles(pages_root, require_pyproject=require_pyproject)
    resolved: list[PageBundleSpec] = []
    for item in names_or_paths:
        text = str(item).strip()
        if not text:
            continue
        path = Path(text).expanduser()
        if path.exists():
            resolved.append(_bundle_from_existing_path(path))
            continue
        bundle = registry.get(text)
        if bundle is not None:
            resolved.append(bundle)
            continue
        direct_bundle = discover_page_bundle(pages_root, text, require_pyproject=require_pyproject)
        if direct_bundle is None:
            raise ValueError(f"Unknown apps-page bundle: {text}")
        resolved.append(direct_bundle)
    return tuple(resolved)


def configured_page_bundle_names(settings: Mapping[str, Any]) -> tuple[str, ...]:
    """Extract ordered apps-page bundle names from an app settings payload."""

    pages_config = settings.get("pages")
    if not isinstance(pages_config, Mapping):
        return ()

    names: list[str] = []
    default_view = pages_config.get("default_view")
    if isinstance(default_view, str) and default_view.strip():
        names.append(default_view.strip())
    view_module = pages_config.get("view_module")
    if isinstance(view_module, list):
        names.extend(str(item).strip() for item in view_module if isinstance(item, str) and item.strip())

    seen: set[str] = set()
    ordered: list[str] = []
    for name in names:
        key = _normalize_bundle_name(name)
        if key and key not in seen:
            seen.add(key)
            ordered.append(key)
    return tuple(ordered)


def _bundle_from_existing_path(path: Path) -> PageBundleSpec:
    resolved = path.resolve(strict=False)
    if resolved.is_file():
        return PageBundleSpec(
            name=resolved.stem,
            root_path=resolved.parent,
            script_path=resolved,
            source="explicit_path",
        )
    script_path = _bundle_entrypoint(resolved, resolved.name)
    if script_path is None:
        raise ValueError(f"Apps-page path has no supported entrypoint: {path}")
    return PageBundleSpec(
        name=resolved.name,
        root_path=resolved,
        script_path=script_path,
        source="explicit_path",
    )


def _bundle_entrypoint(bundle_dir: Path, module_name: str) -> Path | None:
    candidates: list[Path] = []
    for pattern_root in (bundle_dir, bundle_dir / "src" / module_name):
        candidates.extend(pattern_root / pattern.format(module=module_name) for pattern in PAGE_BUNDLE_ENTRYPOINT_NAMES)
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate.resolve(strict=False)
    fallback = sorted((bundle_dir / "src").glob("*/view_*.py"))
    return fallback[0].resolve(strict=False) if fallback else None


def _coerce_root(value: str | Path) -> Path | None:
    try:
        return Path(value).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def _normalize_bundle_name(value: str) -> str:
    return str(value).strip()
