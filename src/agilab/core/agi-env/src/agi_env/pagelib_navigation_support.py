from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, MutableMapping, Sequence

from .app_provider_registry import app_name_aliases


SessionStateLike = MutableMapping[str, Any]


@dataclass(frozen=True)
class ProjectSelection:
    shortlist: list[str]
    total_matches: int
    default_index: int

    @property
    def needs_caption(self) -> bool:
        return bool(self.shortlist) and self.total_matches > len(self.shortlist)


@dataclass(frozen=True)
class SidebarDataframeSelection:
    module_path: Path
    df_files_rel: list[Path]
    index_page: Path | str
    key_df: str
    default_index: int


def ensure_csv_files_state(
    session_state: SessionStateLike,
    datadir: Path,
    discovered_files: Sequence[Path],
) -> None:
    if not session_state.get("csv_files"):
        session_state["csv_files"] = list(discovered_files)
    if "dataset_files" not in session_state:
        session_state["dataset_files"] = list(session_state["csv_files"])
    if not session_state.get("df_file"):
        csv_files_rel = [
            Path(file).relative_to(datadir).as_posix()
            for file in session_state["csv_files"]
        ]
        session_state["df_file"] = csv_files_rel[0] if csv_files_rel else None


def clear_dataframe_selection_state(session_state: SessionStateLike) -> None:
    for key in ("df_file", "csv_files", "dataset_files"):
        session_state.pop(key, None)


def copy_widget_value(session_state: SessionStateLike, var_key: str, widget_key: str) -> None:
    session_state[var_key] = session_state[widget_key]


def build_project_selection(
    projects: Sequence[str],
    current_project: str,
    search_term: str,
    limit: int = 50,
) -> ProjectSelection:
    normalized_search = search_term.strip().lower()
    if normalized_search:
        filtered_projects = [p for p in projects if normalized_search in p.lower()]
    else:
        filtered_projects = list(projects)

    total_matches = len(filtered_projects)
    shortlist = list(filtered_projects[:limit])

    if (
        current_project
        and current_project in filtered_projects
        and current_project not in shortlist
    ):
        shortlist = [current_project] + [p for p in shortlist if p != current_project]

    try:
        default_index = shortlist.index(current_project)
    except ValueError:
        default_index = 0

    return ProjectSelection(
        shortlist=shortlist,
        total_matches=total_matches,
        default_index=default_index,
    )


def normalize_query_param_value(raw_value: object) -> str | None:
    if isinstance(raw_value, list):
        return str(raw_value[-1]) if raw_value else None
    if raw_value is None:
        return None
    return str(raw_value)


def active_app_candidates(
    name: str,
    apps_path: Path,
    projects: Sequence[str],
    preferred_base: Path | None = None,
) -> list[Path]:
    base = preferred_base or apps_path
    builtin_base = apps_path / "builtin"
    candidates = [
        Path(name).expanduser(),
        base / name,
        base / f"{name}_project",
        apps_path / name,
        apps_path / f"{name}_project",
        builtin_base / name,
        builtin_base / f"{name}_project",
    ]

    requested_aliases = set(app_name_aliases(name))
    for project_name in projects:
        if requested_aliases & set(app_name_aliases(project_name)):
            candidates.extend(
                [
                    apps_path / project_name,
                    apps_path / f"{project_name}_project",
                    builtin_base / project_name,
                    builtin_base / f"{project_name}_project",
                ]
            )
            break

    deduped: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        deduped.append(candidate)
    return deduped


def resolve_default_selection(
    options: Sequence[str],
    preferred: str | None,
    fallback: str | None = None,
) -> tuple[str | None, int]:
    if not options:
        return None, 0
    if preferred in options:
        return preferred, list(options).index(preferred)
    if fallback in options:
        return fallback, list(options).index(fallback)
    return options[0], 0


def build_sidebar_dataframe_selection(
    export_root: Path,
    lab_dir_name: str,
    df_files: Sequence[Path],
    current_index_page: Path | str | None,
    default_index_page: Path | str,
) -> SidebarDataframeSelection:
    df_files_rel = sorted(
        (Path(file).relative_to(export_root) for file in df_files),
        key=str,
    )
    index_page = current_index_page if current_index_page is not None else (
        df_files_rel[0] if df_files_rel else default_index_page
    )
    key_df = f"{index_page}df"
    default_index = next(
        (i for i, rel_path in enumerate(df_files_rel) if rel_path.name == "default_df"),
        0,
    )
    return SidebarDataframeSelection(
        module_path=Path(lab_dir_name),
        df_files_rel=df_files_rel,
        index_page=index_page,
        key_df=key_df,
        default_index=default_index,
    )


def resolve_selected_df_path(
    selected_df: str | Path | None,
    *,
    fallback_df_file: str | Path | None = None,
    export_root: Path | None = None,
) -> Path | None:
    selected_path: Path | None = None
    if selected_df:
        selected_path = Path(selected_df)
        if not selected_path.is_absolute() and export_root is not None:
            selected_path = export_root / selected_path
    elif fallback_df_file:
        selected_path = Path(fallback_df_file)
    return selected_path
