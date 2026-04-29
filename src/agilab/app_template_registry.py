"""Typed registry for AGILAB app templates."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


APP_TEMPLATE_SCHEMA = "agilab.app_template_registry.v1"
APP_TEMPLATE_SUFFIX = "_app_template"


@dataclass(frozen=True, slots=True)
class AppTemplateSpec:
    """Resolved metadata for one app template."""

    name: str
    root_path: Path
    pyproject_path: Path
    settings_path: Path | None = None
    schema: str = APP_TEMPLATE_SCHEMA
    source: str = "discovered"

    def __post_init__(self) -> None:
        normalized = _normalize_template_name(self.name)
        if not _is_template_name(normalized):
            raise ValueError(f"App template name must end with {APP_TEMPLATE_SUFFIX!r}")
        object.__setattr__(self, "name", normalized)
        if not isinstance(self.root_path, Path):
            object.__setattr__(self, "root_path", Path(self.root_path))
        if not isinstance(self.pyproject_path, Path):
            object.__setattr__(self, "pyproject_path", Path(self.pyproject_path))
        if self.settings_path is not None and not isinstance(self.settings_path, Path):
            object.__setattr__(self, "settings_path", Path(self.settings_path))

    def as_row(self) -> dict[str, str]:
        """Return a stable row for diagnostics and documentation."""

        return {
            "schema": self.schema,
            "name": self.name,
            "root_path": self.root_path.as_posix(),
            "pyproject_path": self.pyproject_path.as_posix(),
            "settings_path": self.settings_path.as_posix() if self.settings_path is not None else "",
            "source": self.source,
        }


class AppTemplateRegistry:
    """Immutable registry for resolving app templates by name."""

    def __init__(self, templates: Iterable[AppTemplateSpec] = ()) -> None:
        self._templates = tuple(sorted(templates, key=lambda template: template.name.casefold()))
        self._by_name = self._build_lookup(self._templates)

    @staticmethod
    def _build_lookup(templates: tuple[AppTemplateSpec, ...]) -> dict[str, AppTemplateSpec]:
        lookup: dict[str, AppTemplateSpec] = {}
        for template in templates:
            key = _template_key(template.name)
            existing = lookup.get(key)
            if existing is not None:
                raise ValueError(
                    f"Duplicate app template {template.name!r}: "
                    f"{existing.root_path} and {template.root_path}"
                )
            lookup[key] = template
        return lookup

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and _template_key(name) in self._by_name

    def __iter__(self) -> Iterator[AppTemplateSpec]:
        return iter(self._templates)

    def __len__(self) -> int:
        return len(self._templates)

    @property
    def templates(self) -> tuple[AppTemplateSpec, ...]:
        """Return templates in deterministic display order."""

        return self._templates

    def names(self) -> tuple[str, ...]:
        """Return template names in deterministic display order."""

        return tuple(template.name for template in self._templates)

    def get(self, name: str, default: Any = None) -> AppTemplateSpec | Any:
        """Return a template by name, or ``default`` when absent."""

        return self._by_name.get(_template_key(name), default)

    def require(self, name: str) -> AppTemplateSpec:
        """Return a template by name, raising a useful error when absent."""

        template = self.get(name)
        if template is not None:
            return template
        available = ", ".join(self.names()) or "<empty>"
        raise KeyError(f"Unknown app template {name!r}. Available templates: {available}")

    def select(self, names: Sequence[str]) -> tuple[AppTemplateSpec, ...]:
        """Return configured templates by name, preserving input order and removing duplicates."""

        selected: list[AppTemplateSpec] = []
        seen: set[str] = set()
        for name in names:
            key = _template_key(name)
            if not key or key in seen:
                continue
            template = self.get(name)
            if template is None:
                continue
            seen.add(key)
            selected.append(template)
        return tuple(selected)

    def as_rows(self) -> list[dict[str, str]]:
        """Return registry rows suitable for rendering as a table."""

        return [template.as_row() for template in self._templates]


def discover_app_templates(
    templates_root: str | Path,
    *,
    require_pyproject: bool = True,
    require_settings: bool = False,
) -> AppTemplateRegistry:
    """Discover app templates below ``templates_root``."""

    root = _coerce_root(templates_root)
    if root is None or not root.exists() or not root.is_dir():
        return AppTemplateRegistry()

    templates: list[AppTemplateSpec] = []
    for template_dir in sorted(
        (path for path in root.iterdir() if path.is_dir() and not path.name.startswith(".")),
        key=lambda path: path.name.casefold(),
    ):
        if not _is_template_name(template_dir.name):
            continue
        template = discover_app_template(
            root,
            template_dir.name,
            require_pyproject=require_pyproject,
            require_settings=require_settings,
        )
        if template is not None:
            templates.append(template)
    return AppTemplateRegistry(templates)


def discover_app_template(
    templates_root: str | Path,
    template_name: str,
    *,
    require_pyproject: bool = True,
    require_settings: bool = False,
) -> AppTemplateSpec | None:
    """Resolve one app template under ``templates_root``."""

    root = _coerce_root(templates_root)
    name = _normalize_template_name(template_name)
    if root is None or not _is_template_name(name):
        return None

    template_dir = root / name
    if not template_dir.exists() or not template_dir.is_dir():
        return None

    pyproject_path = template_dir / "pyproject.toml"
    if require_pyproject and not pyproject_path.is_file():
        return None

    settings_path = template_dir / "src" / "app_settings.toml"
    resolved_settings_path = settings_path.resolve(strict=False) if settings_path.is_file() else None
    if require_settings and resolved_settings_path is None:
        return None

    return AppTemplateSpec(
        name=name,
        root_path=template_dir.resolve(strict=False),
        pyproject_path=pyproject_path.resolve(strict=False),
        settings_path=resolved_settings_path,
    )


def _coerce_root(value: str | Path) -> Path | None:
    try:
        return Path(value).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def _normalize_template_name(value: str) -> str:
    return str(value).strip()


def _is_template_name(value: str) -> bool:
    return bool(value) and value.endswith(APP_TEMPLATE_SUFFIX)


def _template_key(value: str) -> str:
    return _normalize_template_name(value).casefold()
