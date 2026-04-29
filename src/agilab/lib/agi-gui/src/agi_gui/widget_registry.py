"""Typed registry for reusable AGILAB Streamlit widgets."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class WidgetSpec:
    """Metadata for a reusable ``agi-gui`` widget."""

    key: str
    label: str
    widget: Callable[..., Any]
    module: str
    category: str
    description: str = ""
    aliases: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _normalize_lookup_key(self.key):
            raise ValueError("Widget key must be a non-empty string")
        if not self.label.strip():
            raise ValueError("Widget label must be a non-empty string")
        if not callable(self.widget):
            raise TypeError(f"Widget {self.key!r} must be callable")
        if not self.module.strip():
            raise ValueError("Widget module must be a non-empty string")
        if not _normalize_lookup_key(self.category):
            raise ValueError("Widget category must be a non-empty string")

    @property
    def qualified_name(self) -> str:
        """Return the import-style name of the registered widget callable."""

        return f"{self.module}.{getattr(self.widget, '__name__', self.key)}"

    def as_row(self) -> dict[str, str]:
        """Return a compact row suitable for docs and diagnostics."""

        return {
            "key": self.key,
            "label": self.label,
            "category": self.category,
            "qualified_name": self.qualified_name,
            "description": self.description,
            "aliases": ", ".join(self.aliases),
            "tags": ", ".join(self.tags),
        }

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Delegate calls to the registered widget callable."""

        return self.widget(*args, **kwargs)


class WidgetRegistry:
    """Immutable registry for resolving AGILAB UI widgets by key or alias."""

    def __init__(self, widgets: Iterable[WidgetSpec] = ()) -> None:
        self._widgets = tuple(widgets)
        self._lookup = self._build_lookup(self._widgets)

    @staticmethod
    def _build_lookup(widgets: tuple[WidgetSpec, ...]) -> dict[str, WidgetSpec]:
        lookup: dict[str, WidgetSpec] = {}
        for spec in widgets:
            names = (spec.key, *spec.aliases)
            for name in names:
                lookup_key = _normalize_lookup_key(name)
                if not lookup_key:
                    raise ValueError(f"Widget {spec.key!r} has an empty alias")
                existing = lookup.get(lookup_key)
                if existing is not None and existing is not spec:
                    raise ValueError(
                        f"Widget lookup name {name!r} is already registered "
                        f"for {existing.key!r}"
                    )
                lookup[lookup_key] = spec
        return lookup

    def __contains__(self, key_or_alias: object) -> bool:
        if not isinstance(key_or_alias, str):
            return False
        return _normalize_lookup_key(key_or_alias) in self._lookup

    def __iter__(self) -> Iterator[WidgetSpec]:
        return iter(self._widgets)

    def __len__(self) -> int:
        return len(self._widgets)

    @property
    def widgets(self) -> tuple[WidgetSpec, ...]:
        """Return registered widgets in deterministic display order."""

        return self._widgets

    def keys(self) -> tuple[str, ...]:
        """Return primary widget keys in deterministic display order."""

        return tuple(spec.key for spec in self._widgets)

    def categories(self) -> tuple[str, ...]:
        """Return known widget categories in deterministic display order."""

        seen: set[str] = set()
        categories: list[str] = []
        for spec in self._widgets:
            if spec.category not in seen:
                seen.add(spec.category)
                categories.append(spec.category)
        return tuple(categories)

    def get(self, key_or_alias: str, default: Any = None) -> WidgetSpec | Any:
        """Return a widget spec by key or alias, or ``default`` when absent."""

        return self._lookup.get(_normalize_lookup_key(key_or_alias), default)

    def require(self, key_or_alias: str) -> WidgetSpec:
        """Return a widget spec by key or alias, raising a useful error when absent."""

        lookup_key = _normalize_lookup_key(key_or_alias)
        spec = self._lookup.get(lookup_key)
        if spec is not None:
            return spec
        available = ", ".join(self.keys()) or "<empty>"
        raise KeyError(f"Unknown agi-gui widget {key_or_alias!r}. Available widgets: {available}")

    def by_category(self, category: str) -> tuple[WidgetSpec, ...]:
        """Return widgets matching ``category`` in deterministic display order."""

        lookup_category = _normalize_lookup_key(category)
        return tuple(
            spec
            for spec in self._widgets
            if _normalize_lookup_key(spec.category) == lookup_category
        )

    def register(self, spec: WidgetSpec) -> "WidgetRegistry":
        """Return a new registry with ``spec`` added."""

        return type(self)((*self._widgets, spec))

    def as_rows(self) -> list[dict[str, str]]:
        """Return registry rows suitable for rendering as a table."""

        return [spec.as_row() for spec in self._widgets]


_DEFAULT_WIDGET_REGISTRY: WidgetRegistry | None = None


def default_widget_registry() -> WidgetRegistry:
    """Return the default ``agi-gui`` widget registry."""

    global _DEFAULT_WIDGET_REGISTRY
    if _DEFAULT_WIDGET_REGISTRY is None:
        _DEFAULT_WIDGET_REGISTRY = WidgetRegistry(_default_widget_specs())
    return _DEFAULT_WIDGET_REGISTRY


def get_widget(key_or_alias: str) -> Callable[..., Any]:
    """Return a registered widget callable by key or alias."""

    return default_widget_registry().require(key_or_alias).widget


def widget_registry_rows() -> list[dict[str, str]]:
    """Return default registry rows for diagnostics or documentation."""

    return default_widget_registry().as_rows()


def _default_widget_specs() -> tuple[WidgetSpec, ...]:
    from .file_picker import agi_file_picker
    from .ux_widgets import (
        action_button,
        action_row,
        compact_choice,
        confirm_button,
        empty_state,
        notice,
        status_container,
        toast,
    )

    return (
        WidgetSpec(
            key="file_picker",
            label="File picker",
            widget=agi_file_picker,
            module="agi_gui.file_picker",
            category="file",
            description="Server-side Streamlit path picker with root validation.",
            aliases=("agi_file_picker", "picker", "path_picker"),
            tags=("filesystem", "upload", "selection"),
        ),
        WidgetSpec(
            key="compact_choice",
            label="Compact choice",
            widget=compact_choice,
            module="agi_gui.ux_widgets",
            category="choice",
            description="Single-choice control using modern Streamlit primitives with fallbacks.",
            aliases=("choice", "segmented_choice", "pills_choice"),
            tags=("selection", "navigation"),
        ),
        WidgetSpec(
            key="action_button",
            label="Action button",
            widget=action_button,
            module="agi_gui.ux_widgets",
            category="action",
            description="Button with normalized AGILAB action styling.",
            aliases=("button", "command_button"),
            tags=("action", "command"),
        ),
        WidgetSpec(
            key="action_row",
            label="Action row",
            widget=action_row,
            module="agi_gui.ux_widgets",
            category="action",
            description="Deterministic row of normalized action buttons.",
            aliases=("button_row", "command_row"),
            tags=("action", "layout"),
        ),
        WidgetSpec(
            key="confirm_button",
            label="Confirm button",
            widget=confirm_button,
            module="agi_gui.ux_widgets",
            category="action",
            description="Two-step confirmation button for destructive or costly actions.",
            aliases=("confirm", "destructive_confirm"),
            tags=("action", "safety"),
        ),
        WidgetSpec(
            key="empty_state",
            label="Empty state",
            widget=empty_state,
            module="agi_gui.ux_widgets",
            category="feedback",
            description="Normalized empty-state notice with optional action.",
            aliases=("empty", "placeholder_state"),
            tags=("feedback", "state"),
        ),
        WidgetSpec(
            key="notice",
            label="Notice",
            widget=notice,
            module="agi_gui.ux_widgets",
            category="feedback",
            description="Inline message wrapper with compatibility fallbacks.",
            aliases=("message", "inline_notice"),
            tags=("feedback", "message"),
        ),
        WidgetSpec(
            key="status_container",
            label="Status container",
            widget=status_container,
            module="agi_gui.ux_widgets",
            category="feedback",
            description="Status context using Streamlit status or compatible fallbacks.",
            aliases=("status", "progress_status"),
            tags=("feedback", "progress"),
        ),
        WidgetSpec(
            key="toast",
            label="Toast",
            widget=toast,
            module="agi_gui.ux_widgets",
            category="feedback",
            description="Toast notification with regular-message fallback.",
            aliases=("notification", "notify"),
            tags=("feedback", "notification"),
        ),
    )


def _normalize_lookup_key(value: str) -> str:
    return str(value).strip().casefold().replace("-", "_").replace(" ", "_")
