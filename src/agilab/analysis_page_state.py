from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AnalysisViewSelectionState:
    view_names: tuple[str, ...]
    default_view_name: str | None
    default_view_path: Path | None
    widget_selection: tuple[str, ...]
    selected_views: tuple[str, ...]
    config_view_module: tuple[str, ...]
    default_route_path: Path | None


def normalize_view_name(value: object) -> str:
    """Normalize page bundle labels by removing leading icon glyphs/decoration."""
    if not isinstance(value, str) or not value:
        return ""
    normalized = re.sub(r"^\s*[^\w-]+", "", value).strip()
    return normalized or value.strip()


def _dedupe_preserve_order(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _excluded_view_options(pages_cfg: Mapping[str, Any]) -> set[str]:
    raw_excluded = pages_cfg.get("excluded_views")
    if not isinstance(raw_excluded, list):
        return set()
    return {
        normalized
        for value in raw_excluded
        if (normalized := normalize_view_name(value))
    }


def _configured_view_options(
    configured_views: Sequence[str],
    available_views: Sequence[str],
    resolved_pages: Mapping[str, Path],
) -> list[str]:
    available = set(available_views)
    options: list[str] = []
    for value in configured_views:
        if value in available:
            options.append(value)
            continue
        normalized = normalize_view_name(value)
        if normalized in resolved_pages and normalized in available:
            options.append(normalized)
    return _dedupe_preserve_order(options)


def _resolve_default_view(
    configured_default: object,
    available_views: Sequence[str],
    resolved_pages: Mapping[str, Path],
    custom_view_lookup: Mapping[str, Path],
) -> tuple[str | None, Path | None]:
    if not isinstance(configured_default, str):
        return None, None
    raw_value = configured_default.strip()
    if not raw_value:
        return None, None

    candidates = [raw_value]
    normalized = normalize_view_name(raw_value)
    if normalized and normalized not in candidates:
        candidates.append(normalized)

    available = set(available_views)
    for candidate in candidates:
        if candidate not in available:
            continue
        view_path = resolved_pages.get(candidate) or custom_view_lookup.get(candidate)
        if view_path is not None:
            return candidate, Path(view_path)
    return None, None


def _coerce_string_list(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [str(item) for item in value if isinstance(item, str) and item.strip()]


def _config_view_module(
    selected_views: Sequence[str],
    resolved_pages: Mapping[str, Path],
) -> tuple[str, ...]:
    payload: list[str] = []
    for page_id in selected_views:
        if page_id in resolved_pages:
            payload.append(page_id)
        else:
            payload.append(str(Path(page_id).resolve()))
    return tuple(payload)


def build_analysis_view_selection_state(
    *,
    pages_cfg: Mapping[str, Any],
    current_page: str | None,
    configured_views: Sequence[str],
    resolved_pages: Mapping[str, Path],
    custom_view_lookup: Mapping[str, Path],
    session_selection: Any = None,
    has_session_selection: bool = False,
) -> AnalysisViewSelectionState:
    """Build the pure view-selection state for the ANALYSIS page."""
    excluded_view_names = _excluded_view_options(pages_cfg)
    all_view_names = tuple(
        view_name
        for view_name in sorted(set(resolved_pages.keys()) | set(custom_view_lookup.keys()))
        if normalize_view_name(view_name) not in excluded_view_names
    )

    if bool(pages_cfg.get("restrict_to_view_module")):
        configured_options = _configured_view_options(
            configured_views,
            all_view_names,
            resolved_pages,
        )
        view_names = tuple(configured_options or all_view_names)
    else:
        view_names = all_view_names

    default_view_name, default_view_path = _resolve_default_view(
        pages_cfg.get("default_view"),
        view_names,
        resolved_pages,
        custom_view_lookup,
    )

    if has_session_selection:
        selection = [value for value in _coerce_string_list(session_selection) if value in view_names]
    else:
        selection = _configured_view_options(configured_views, view_names, resolved_pages)

    default_available = (
        not current_page
        and default_view_name
        and default_view_path is not None
    )
    should_prepend_default = (
        default_available
        and default_view_name not in selection
    )
    if should_prepend_default:
        selection = [default_view_name, *selection]

    selection = _dedupe_preserve_order(selection)
    default_route_path = Path(default_view_path) if default_available else None

    return AnalysisViewSelectionState(
        view_names=tuple(view_names),
        default_view_name=default_view_name,
        default_view_path=default_view_path,
        widget_selection=tuple(selection),
        selected_views=tuple(selection),
        config_view_module=_config_view_module(selection, resolved_pages),
        default_route_path=default_route_path,
    )
