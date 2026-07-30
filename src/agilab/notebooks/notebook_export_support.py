from __future__ import annotations

import ast
import hashlib
import json
import logging
import os
import shlex
import sys
import textwrap
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence

import tomllib

from agi_env.app_provider_registry import app_name_aliases
from agi_env.app_settings_support import read_app_settings

from agilab.notebooks.notebook_helper_cell import _helper_cell

from agilab.ui.page_bundle_registry import discover_page_bundle


logger = logging.getLogger(__name__)


DEFAULT_NOTEBOOK_EXPORT_MODE = "supervisor"
NOTEBOOK_EXPORT_SCHEMA = "agilab.notebook_export.v1"
NOTEBOOK_EXPORT_SCHEMA_VERSION = 1
NOTEBOOK_EXPORT_STAGE_CELL_SCHEMA = "agilab.notebook_export.stage_cell.v1"
NOTEBOOK_EXPORT_MANIFEST_SCHEMA = "agilab.notebook_export_manifest.v1"
NOTEBOOK_EXPORT_HANDOFF_SCHEMA = "agilab.notebook_export_handoff.v1"
NOTEBOOK_VIEW_SYNC_STATUS_SCHEMA = "agilab.notebook_view_sync_status.v1"
PYCHARM_NOTEBOOK_MIRROR_ROOT = "exported_notebooks"
PROJECT_NOTEBOOK_MIRROR_DIR = "notebooks"
ALLOW_WORKSPACE_SIBLING_APPS_ENV = "AGILAB_NOTEBOOK_EXPORT_ALLOW_WORKSPACE_SIBLINGS"
APPS_REPOSITORY_ENV_KEYS = ("APPS_REPOSITORY",)
STAGE_EXECUTION_CONTROL_KEYS = (
    "automation",
    "enabled",
    "skip",
    "skip_if_outputs_exist",
    "skip_if_outputs_current",
    "outputs",
    "output_paths",
    "inputs",
    "input_paths",
    "profiles",
    "pipeline_profiles",
    "automation_profiles",
)
NOTEBOOK_AUTOMATION_PROFILES = frozenset(
    {"balanced", "smoke", "fast", "evidence", "custom"}
)

PYCHARM_NOTEBOOK_SITECUSTOMIZE = """\
from __future__ import annotations

from pathlib import Path
import shlex
import sys

try:
    from debugpy._vendored import vendored as _debugpy_vendored
except Exception:
    _debugpy_vendored = None


def _preferred_jupyter_commands(notebook_path: Path) -> tuple[str, str]:
    try:
        current_file = Path(__file__).resolve()
    except Exception:
        current_file = Path(__file__)

    project_root = None
    try:
        if current_file.parent.name == "notebooks":
            candidate = current_file.parent.parent
            if (candidate / "pyproject.toml").exists() or (candidate / "src" / "app_settings.toml").exists():
                project_root = candidate
        elif current_file.parents[1].name == "exported_notebooks":
            project_root = current_file.parents[2]
    except Exception:
        project_root = None

    quoted_notebook = shlex.quote(str(notebook_path))
    if project_root is None:
        prefix = "uv run"
    else:
        prefix = f"uv --project {shlex.quote(str(project_root))} run"

    lab_cmd = f"{prefix} --with jupyterlab jupyter lab {quoted_notebook}"
    execute_cmd = (
        f"{prefix} --with nbconvert python -m jupyter nbconvert "
        f"--to notebook --execute --inplace {quoted_notebook}"
    )
    return lab_cmd, execute_cmd


def _guard_direct_python_notebook_execution() -> None:
    argv0 = str(getattr(sys, "argv", [""])[0] or "")
    if not argv0.lower().endswith(".ipynb"):
        return
    notebook_path = Path(argv0)
    lab_cmd, execute_cmd = _preferred_jupyter_commands(notebook_path)
    raise SystemExit(
        "AGILAB exported notebooks are Jupyter notebooks, not Python scripts. "
        f"Open `{notebook_path}` in PyCharm/Jupyter, or run "
        f"`{lab_cmd}` or "
        f"`{execute_cmd}`."
    )


def _ensure_pydevd_values_policy() -> None:
    if _debugpy_vendored is None:
        return
    try:
        with _debugpy_vendored("pydevd"):
            import _pydevd_bundle.pydevd_constants as _pydevd_constants
    except Exception:
        return

    if hasattr(_pydevd_constants, "ValuesPolicy"):
        return

    class _ValuesPolicy:
        SYNC = 0
        ASYNC = 1
        ON_DEMAND = 2

    _pydevd_constants.ValuesPolicy = _ValuesPolicy
    if not hasattr(_pydevd_constants, "LOAD_VALUES_POLICY"):
        _pydevd_constants.LOAD_VALUES_POLICY = _ValuesPolicy.SYNC
    if not hasattr(_pydevd_constants, "DEFAULT_VALUES_DICT"):
        _pydevd_constants.DEFAULT_VALUES_DICT = {
            _ValuesPolicy.ASYNC: "__pydevd_value_async",
            _ValuesPolicy.ON_DEMAND: "__pydevd_value_on_demand",
        }


try:
    _guard_direct_python_notebook_execution()
except SystemExit:
    raise
except Exception:
    pass

try:
    _ensure_pydevd_values_policy()
except Exception:
    pass
"""


@dataclass(frozen=True)
class RelatedPageExport:
    module: str
    label: str = ""
    description: str = ""
    artifacts: tuple[str, ...] = ()
    launch_note: str = ""
    script_path: str = ""
    inline_renderer: str = ""
    script_sha256: str = ""
    inline_renderer_sha256: str = ""


@dataclass(frozen=True)
class NotebookExportContext:
    project_name: str
    module_path: str
    artifact_dir: str
    active_app: str = ""
    app_settings_file: str = ""
    pages_root: str = ""
    repo_root: str = ""
    export_mode: str = DEFAULT_NOTEBOOK_EXPORT_MODE
    allow_workspace_sibling_apps: bool = False
    related_pages: tuple[RelatedPageExport, ...] = ()
    view_sync: Mapping[str, Any] | None = None


def _normalize_path(value: Any) -> str:
    if not value:
        return ""
    try:
        return str(Path(value).expanduser())
    except (OSError, RuntimeError, TypeError, ValueError):
        return str(value)


def _repo_root_candidates(
    export_context: NotebookExportContext | None,
    *,
    current_file: str | Path = __file__,
) -> tuple[Path, ...]:
    candidates: list[Path] = []
    if export_context and export_context.repo_root:
        try:
            candidates.append(Path(export_context.repo_root).expanduser().resolve(strict=False))
        except (OSError, RuntimeError, TypeError, ValueError):
            pass
    try:
        current_path = Path(current_file).resolve()
        local_root = next(
            (
                candidate
                for candidate in current_path.parents
                if (candidate / "src" / "agilab").exists()
            ),
            None,
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        local_root = None
    if local_root is not None and local_root not in candidates:
        candidates.append(local_root)
    return tuple(candidates)


def _looks_like_source_checkout(root: Path) -> bool:
    return (root / "src" / "agilab").exists() and ((root / ".git").exists() or (root / ".idea").exists())


def _truthy_env(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _runtime_role_from_engine(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace("_", "-")
    if normalized in {"agi.run", "agi"}:
        return "worker"
    if normalized in {"runpy", "python", "local"}:
        return "manager"
    return ""


def _normalize_notebook_runtime_role(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace("_", "-")
    if normalized in {"manager", "worker"}:
        return normalized
    return ""


def _allow_workspace_sibling_apps() -> bool:
    return _truthy_env(os.environ.get(ALLOW_WORKSPACE_SIBLING_APPS_ENV))


def _project_name_candidates(project_name: str | None) -> tuple[str, ...]:
    text = str(project_name or "").strip()
    if not text:
        return ()
    candidates: list[str] = []

    def _add(candidate: str) -> None:
        candidate = str(candidate or "").strip()
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    for alias in app_name_aliases(text):
        _add(alias)
    return tuple(candidates)


def _resolve_pycharm_repo_root(
    export_context: NotebookExportContext | None,
    *,
    current_file: str | Path = __file__,
) -> Path | None:
    for candidate in _repo_root_candidates(export_context, current_file=current_file):
        if _looks_like_source_checkout(candidate):
            return candidate
    return None


def _normalize_repo_root_hint(value: str | Path | None) -> str:
    if not value:
        return ""
    try:
        path = Path(value).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, TypeError, ValueError):
        return _normalize_path(value)

    for candidate in (path, *path.parents):
        if _looks_like_source_checkout(candidate):
            return str(candidate)
    return str(path)


def _iter_checkout_workspace_apps_dirs(
    repo_root_hint: str | Path | None,
    *,
    allow_siblings: bool = False,
) -> Iterable[Path]:
    repo_root = _normalize_repo_root_hint(repo_root_hint)
    if not repo_root:
        return
    try:
        checkout_root = Path(repo_root)
    except (OSError, RuntimeError, TypeError, ValueError):
        return
    if not _looks_like_source_checkout(checkout_root):
        return

    seen: set[str] = set()

    def _emit(candidate: Path) -> Iterable[Path]:
        candidate_text = _normalize_path(candidate)
        if not candidate_text or candidate_text in seen:
            return ()
        seen.add(candidate_text)
        return (candidate,)

    yield from _emit(checkout_root / "src" / "agilab" / "apps")
    yield from _emit(checkout_root / "apps")

    if not allow_siblings:
        return

    workspace_root = checkout_root.parent
    try:
        siblings = sorted(
            candidate
            for candidate in workspace_root.iterdir()
            if candidate.is_dir() and candidate != checkout_root
        )
    except OSError:
        siblings = []
    for sibling in siblings:
        yield from _emit(sibling / "apps")
        yield from _emit(sibling / "src" / "agilab" / "apps")


def _project_notebook_mirror_path(
    export_context: NotebookExportContext | None,
    notebook_name: str,
) -> Path | None:
    if export_context is None or not export_context.active_app:
        return None
    try:
        app_root = Path(export_context.active_app).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    if not app_root.is_dir():
        return None
    project_name = str(export_context.project_name or "").strip()
    if project_name and app_root.name not in _project_name_candidates(project_name):
        return None
    if not (app_root / "pyproject.toml").is_file() and not (app_root / "src" / "app_settings.toml").is_file():
        return None
    return app_root / PROJECT_NOTEBOOK_MIRROR_DIR / notebook_name


def pycharm_notebook_mirror_path(
    toml_path: str | Path,
    *,
    export_context: NotebookExportContext | None = None,
    current_file: str | Path = __file__,
) -> str:
    try:
        stages_path = Path(toml_path).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, TypeError, ValueError):
        return ""
    notebook_path = stages_path.with_suffix(".ipynb")
    repo_root = _resolve_pycharm_repo_root(export_context, current_file=current_file)
    if repo_root is None:
        return ""
    project_mirror = _project_notebook_mirror_path(export_context, notebook_path.name)
    if project_mirror is not None:
        return str(project_mirror)
    if notebook_path.is_relative_to(repo_root):
        return str(notebook_path)

    artifact_dir = ""
    if export_context and export_context.artifact_dir:
        artifact_dir = Path(_normalize_path(export_context.artifact_dir)).name
    folder_name = artifact_dir or stages_path.parent.name or stages_path.stem
    mirror_path = repo_root / PYCHARM_NOTEBOOK_MIRROR_ROOT / folder_name / notebook_path.name
    return str(mirror_path)


def pycharm_notebook_sitecustomize_text() -> str:
    return PYCHARM_NOTEBOOK_SITECUSTOMIZE


def _settings_to_app_root(settings_path: Path | None) -> str:
    if settings_path is None:
        return ""
    parent = settings_path.parent
    if parent.name == "src":
        return str(parent.parent)
    return str(parent)


def _is_valid_app_root(app_root: str | Path | None) -> bool:
    if not app_root:
        return False
    try:
        root = Path(app_root).expanduser()
    except (OSError, RuntimeError, TypeError, ValueError):
        return False
    try:
        return root.is_dir() and ((root / "pyproject.toml").is_file() or (root / "src" / "app_settings.toml").is_file())
    except OSError:
        return False


def _app_root_matches_project(app_root: str | Path | None, project_name: str) -> bool:
    if not project_name:
        return True
    if not app_root:
        return False
    try:
        return Path(app_root).expanduser().name in _project_name_candidates(project_name)
    except (OSError, RuntimeError, TypeError, ValueError):
        return False


def _iter_valid_app_roots(
    project_name: str,
    *,
    direct_roots: Sequence[str | Path | None],
    apps_dirs: Sequence[str | Path | None],
) -> Iterable[str]:
    seen: set[str] = set()
    project_name = str(project_name or "").strip()
    project_candidates = _project_name_candidates(project_name)

    def _emit(
        candidate: str | Path | None,
        *,
        require_project_match: bool = False,
    ) -> Iterable[str]:
        if not candidate:
            return ()
        path_text = _normalize_path(candidate)
        if not path_text or path_text in seen or not _is_valid_app_root(path_text):
            return ()
        if require_project_match and not _app_root_matches_project(path_text, project_name):
            return ()
        seen.add(path_text)
        return (path_text,)

    for candidate in direct_roots:
        yield from _emit(candidate, require_project_match=bool(project_name))

    if not project_name:
        return

    for apps_dir in apps_dirs:
        if not apps_dir:
            continue
        apps_root = _normalize_path(apps_dir)
        if not apps_root:
            continue
        for candidate_name in project_candidates:
            yield from _emit(Path(apps_root) / candidate_name)
            yield from _emit(Path(apps_root) / "builtin" / candidate_name)


def _load_related_pages_from_settings(settings_path: Path | None) -> tuple[str, ...]:
    if settings_path is None or not settings_path.exists():
        return ()
    try:
        payload = read_app_settings(settings_path)
    except (OSError, TypeError, ValueError, tomllib.TOMLDecodeError):
        return ()
    raw_pages = payload.get("pages", {}).get("view_module", [])
    if not isinstance(raw_pages, list):
        return ()
    normalized: list[str] = []
    for raw_page in raw_pages:
        page = str(raw_page or "").strip()
        if page and page not in normalized:
            normalized.append(page)
    return tuple(normalized)


def _candidate_notebook_manifest_paths(app_root: str | Path | None) -> tuple[Path, ...]:
    if not app_root:
        return ()
    try:
        root = Path(app_root).expanduser()
    except (OSError, RuntimeError, TypeError, ValueError):
        return ()
    return (root / "notebook_export.toml", root / "src" / "notebook_export.toml")


def _load_related_page_manifest(
    app_root: str | Path | None,
) -> tuple[dict[str, dict[str, Any]], tuple[str, ...]]:
    for manifest_path in _candidate_notebook_manifest_paths(app_root):
        if not manifest_path.exists():
            continue
        try:
            with open(manifest_path, "rb") as stream:
                payload = tomllib.load(stream)
        except (OSError, TypeError, ValueError, tomllib.TOMLDecodeError):
            return {}, ()
        export_cfg = payload.get("notebook_export", {})
        raw_pages = export_cfg.get("related_pages", [])
        if not isinstance(raw_pages, list):
            return {}, ()
        records: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for raw_page in raw_pages:
            if not isinstance(raw_page, dict):
                continue
            module = str(raw_page.get("module", "") or "").strip()
            if not module:
                continue
            record = {
                "label": str(raw_page.get("label", "") or ""),
                "description": str(raw_page.get("description", "") or ""),
                "artifacts": tuple(str(item) for item in raw_page.get("artifacts", []) if str(item or "").strip()),
                "launch_note": str(raw_page.get("launch_note", "") or ""),
                "inline_renderer": str(raw_page.get("inline_renderer", "") or ""),
            }
            records[module] = record
            if module not in order:
                order.append(module)
        return records, tuple(order)
    return {}, ()


def _file_sha256(path: str | Path | None) -> str:
    if not path:
        return ""
    try:
        candidate = Path(path).expanduser()
        if not candidate.is_file():
            return ""
        return hashlib.sha256(candidate.read_bytes()).hexdigest()
    except (OSError, RuntimeError, TypeError, ValueError):
        return ""


def _inline_renderer_module_path(target: str | None) -> str:
    target_text = str(target or "").strip()
    if not target_text:
        return ""
    module_target, _, _attr = target_text.partition(":")
    module_target = module_target.strip()
    if not module_target:
        return ""
    try:
        candidate = Path(module_target).expanduser()
    except (OSError, RuntimeError, TypeError, ValueError):
        return ""
    if candidate.suffix == ".py" or "/" in module_target or "\\" in module_target:
        return str(candidate)
    return ""


def _sync_source_record(kind: str, path: str | Path | None, *, module: str = "") -> dict[str, Any]:
    path_text = _normalize_path(path)
    return {
        "kind": kind,
        "module": str(module or ""),
        "path": path_text,
        "sha256": _file_sha256(path_text),
    }


def _dedupe_sync_sources(sources: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for source in sources:
        path = str(source.get("path", "") or "").strip()
        sha256 = str(source.get("sha256", "") or "").strip()
        if not path or not sha256:
            continue
        record = {
            "kind": str(source.get("kind", "") or ""),
            "module": str(source.get("module", "") or ""),
            "path": path,
            "sha256": sha256,
        }
        key = (record["kind"], record["module"], record["path"])
        if key in seen:
            continue
        seen.add(key)
        normalized.append(record)
    normalized.sort(key=lambda item: (item["kind"], item["module"], item["path"]))
    return normalized


def _build_view_sync_snapshot(
    *,
    settings_file: Path | None,
    source_settings: Path | None,
    active_app: str,
    related_pages: Sequence[RelatedPageExport],
) -> dict[str, Any]:
    sources: list[dict[str, Any]] = []
    for path, kind in (
        (settings_file, "workspace_app_settings"),
        (source_settings, "source_app_settings"),
    ):
        if path is not None:
            sources.append(_sync_source_record(kind, path))
    for path in _candidate_notebook_manifest_paths(active_app):
        sources.append(_sync_source_record("notebook_export_manifest", path))
    for page in related_pages:
        sources.append(_sync_source_record("analysis_page_script", page.script_path, module=page.module))
        inline_path = _inline_renderer_module_path(page.inline_renderer)
        if inline_path:
            sources.append(_sync_source_record("analysis_page_inline_renderer", inline_path, module=page.module))

    normalized_sources = _dedupe_sync_sources(sources)
    modules = [page.module for page in related_pages if page.module]
    payload = {
        "schema": "agilab.notebook_view_sync.v1",
        "source": "notebook_export_manifest_and_app_settings",
        "related_page_modules": modules,
        "sources": normalized_sources,
    }
    payload["sha256"] = notebook_export_sha256(payload)
    return payload


def _bundle_record_from_provider(bundle: Any) -> dict[str, str]:
    if bundle is None:
        return {}
    if hasattr(bundle, "as_dict"):
        try:
            raw_record = bundle.as_dict()
        except Exception:
            raw_record = {}
    elif isinstance(bundle, dict):
        raw_record = bundle
    else:
        raw_record = {
            "name": getattr(bundle, "name", ""),
            "module": getattr(bundle, "module", "") or getattr(bundle, "name", ""),
            "root_path": getattr(bundle, "root_path", ""),
            "script_path": getattr(bundle, "script_path", ""),
            "inline_renderer": getattr(bundle, "inline_renderer", ""),
        }
    record = {
        "name": str(raw_record.get("name", "") or raw_record.get("module", "") or ""),
        "module": str(raw_record.get("module", "") or raw_record.get("name", "") or ""),
        "root_path": _normalize_path(raw_record.get("root_path", "")),
        "script_path": _normalize_path(raw_record.get("script_path", "")),
        "inline_renderer": str(raw_record.get("inline_renderer", "") or ""),
    }
    return record if record["script_path"] else {}


def _discover_agi_pages_bundle(module_name: str, pages_root: str | Path | None = None) -> dict[str, str]:
    try:
        import agi_pages
    except Exception:
        return {}

    resolver = getattr(agi_pages, "resolve_bundle", None)
    if callable(resolver):
        try:
            bundle = resolver(module_name, pages_root=pages_root or None)
        except TypeError:
            try:
                bundle = resolver(module_name)
            except Exception:
                bundle = None
        except Exception:
            bundle = None
        record = _bundle_record_from_provider(bundle)
        if record:
            return record

    script_resolver = getattr(agi_pages, "script_path", None)
    if not callable(script_resolver):
        return {}
    try:
        script = script_resolver(module_name, pages_root=pages_root or None)
    except TypeError:
        try:
            script = script_resolver(module_name)
        except Exception:
            script = ""
    except Exception:
        script = ""
    if not script:
        return {}

    inline_renderer = ""
    inline_resolver = getattr(agi_pages, "inline_renderer_target", None)
    if callable(inline_resolver):
        try:
            inline_renderer = str(inline_resolver(module_name, pages_root=pages_root or None) or "")
        except TypeError:
            try:
                inline_renderer = str(inline_resolver(module_name) or "")
            except Exception:
                inline_renderer = ""
        except Exception:
            inline_renderer = ""
    return {
        "name": module_name,
        "module": module_name,
        "root_path": "",
        "script_path": _normalize_path(script),
        "inline_renderer": inline_renderer,
    }


def _discover_page_script(pages_root: str | Path | None, module_name: str) -> str:
    if pages_root:
        bundle = discover_page_bundle(pages_root, module_name)
        if bundle is not None:
            return str(bundle.script_path)
    provider_record = _discover_agi_pages_bundle(module_name, pages_root=pages_root)
    return provider_record.get("script_path", "")


def _discover_page_inline_renderer(
    page_manifest: dict[str, dict[str, Any]],
    page: str,
    *,
    script_path: str,
) -> str:
    configured = str(page_manifest.get(page, {}).get("inline_renderer", "") or "").strip()
    if configured:
        return configured
    if not script_path:
        return ""
    try:
        candidate = Path(script_path).resolve(strict=False).with_name("notebook_inline.py")
    except (OSError, RuntimeError, TypeError, ValueError):
        return ""
    if not candidate.exists():
        provider_record = _discover_agi_pages_bundle(page)
        return provider_record.get("inline_renderer", "")
    return f"{candidate}:render_inline"


def build_notebook_export_context(
    env: Any,
    module_path: str | Path,
    stages_file: str | Path,
    *,
    project_name: str | None = None,
) -> NotebookExportContext:
    module_name = str(project_name or Path(module_path).parts[0] or Path(module_path).name)
    settings_file: Path | None = None
    if hasattr(env, "resolve_user_app_settings_file"):
        try:
            settings_file = Path(env.resolve_user_app_settings_file(module_name, ensure_exists=False))
        except (OSError, RuntimeError, TypeError, ValueError):
            settings_file = None
    if settings_file is None:
        raw_settings = getattr(env, "app_settings_file", None)
        if raw_settings:
            try:
                settings_file = Path(raw_settings)
            except (OSError, RuntimeError, TypeError, ValueError):
                settings_file = None

    source_settings: Path | None = None
    if hasattr(env, "find_source_app_settings_file"):
        try:
            resolved = env.find_source_app_settings_file(module_name)
            source_settings = Path(resolved) if resolved else None
        except (OSError, RuntimeError, TypeError, ValueError):
            source_settings = None

    repo_root = ""
    read_agilab_path = getattr(env, "read_agilab_path", None)
    if callable(read_agilab_path):
        try:
            repo_root = _normalize_repo_root_hint(read_agilab_path())
        except (OSError, RuntimeError, TypeError, ValueError):
            repo_root = ""
    repo_apps_dir = Path(repo_root) / "src" / "agilab" / "apps" if repo_root else None
    allow_workspace_sibling_apps = _allow_workspace_sibling_apps()
    active_app = next(
        iter(
            _iter_valid_app_roots(
                module_name,
                direct_roots=(
                    _settings_to_app_root(source_settings),
                    _normalize_path(getattr(env, "active_app", "")),
                ),
                apps_dirs=(
                    getattr(env, "apps_path", None),
                    getattr(env, "builtin_apps_path", None),
                    getattr(env, "apps_repository_root", None),
                    repo_apps_dir,
                    *_iter_checkout_workspace_apps_dirs(
                        repo_root,
                        allow_siblings=allow_workspace_sibling_apps,
                    ),
                ),
            )
        ),
        "",
    )
    page_manifest, manifest_order = _load_related_page_manifest(active_app)
    settings_pages = _load_related_pages_from_settings(
        settings_file
    ) or _load_related_pages_from_settings(source_settings)
    # The app-owned notebook_export.toml is the curated export contract
    # (labels, artifact globs, launch notes); it leads the related-page list.
    # Settings-only pages are appended so live view selections stay visible.
    related_pages = tuple(
        dict.fromkeys((*manifest_order, *settings_pages))
    )
    pages_root = _normalize_path(getattr(env, "AGILAB_PAGES_ABS", ""))
    related_page_records_list: list[RelatedPageExport] = []
    for page in related_pages:
        script_path = _discover_page_script(pages_root, page)
        inline_renderer = _discover_page_inline_renderer(page_manifest, page, script_path=script_path)
        related_page_records_list.append(
            RelatedPageExport(
                module=page,
                label=str(page_manifest.get(page, {}).get("label", "") or ""),
                description=str(page_manifest.get(page, {}).get("description", "") or ""),
                artifacts=tuple(str(item) for item in page_manifest.get(page, {}).get("artifacts", ())),
                launch_note=str(page_manifest.get(page, {}).get("launch_note", "") or ""),
                script_path=script_path,
                inline_renderer=inline_renderer,
                script_sha256=_file_sha256(script_path),
                inline_renderer_sha256=_file_sha256(_inline_renderer_module_path(inline_renderer)),
            )
        )
    related_page_records = tuple(related_page_records_list)
    view_sync = _build_view_sync_snapshot(
        settings_file=settings_file,
        source_settings=source_settings,
        active_app=active_app,
        related_pages=related_page_records,
    )

    return NotebookExportContext(
        project_name=module_name,
        module_path=Path(module_path).as_posix(),
        artifact_dir=str(Path(stages_file).resolve().parent),
        active_app=active_app,
        app_settings_file=str(settings_file) if settings_file is not None else "",
        pages_root=pages_root,
        repo_root=repo_root,
        allow_workspace_sibling_apps=allow_workspace_sibling_apps,
        related_pages=related_page_records,
        view_sync=view_sync,
    )


def _build_plain_notebook(toml_data: Dict[str, Any]) -> Dict[str, Any]:
    notebook_data = {
        "cells": [],
        "metadata": _notebook_metadata(),
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    for module, stages in toml_data.items():
        if module == "__meta__" or not isinstance(stages, list):
            continue
        for stage in stages:
            code_text = ""
            if isinstance(stage, dict):
                code_text = str(stage.get("C", "") or "")
            elif isinstance(stage, str):
                code_text = stage
            if not code_text:
                continue
            notebook_data["cells"].append(
                {
                    "cell_type": "code",
                    "execution_count": None,
                    "metadata": {},
                    "outputs": [],
                    "source": code_text.splitlines(keepends=True),
                }
            )
    return notebook_data


def _metadata_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _stage_dependency_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return _metadata_string_list(value)


def _metadata_value(value: Any) -> Any:
    """Return a JSON/TOML-safe copy of structured stage metadata."""
    if isinstance(value, Mapping):
        return {str(key): _metadata_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_metadata_value(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _stage_execution_controls(stage: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: _metadata_value(stage[key])
        for key in STAGE_EXECUTION_CONTROL_KEYS
        if key in stage
    }


def _normalized_automation_profile(value: Any) -> str:
    raw_value = str(value or "").strip()
    if not raw_value:
        return "balanced"
    normalized = raw_value.lower()
    if normalized in NOTEBOOK_AUTOMATION_PROFILES:
        return normalized
    logger.warning(
        "Unknown automation profile %r; defaulting to 'balanced'",
        value,
    )
    return "balanced"


def _deep_merge_metadata(
    base: Mapping[str, Any],
    override: Mapping[str, Any],
) -> dict[str, Any]:
    merged = {str(key): _metadata_value(value) for key, value in base.items()}
    for key, value in override.items():
        normalized_key = str(key)
        current = merged.get(normalized_key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            merged[normalized_key] = _deep_merge_metadata(current, value)
        else:
            merged[normalized_key] = _metadata_value(value)
    return merged


def _stage_with_profile(
    stage: Mapping[str, Any],
    profile: str,
) -> dict[str, Any]:
    for key in ("profiles", "pipeline_profiles", "automation_profiles"):
        profile_map = stage.get(key)
        if not isinstance(profile_map, Mapping):
            continue
        override = profile_map.get(profile)
        if isinstance(override, Mapping):
            return _deep_merge_metadata(stage, override)
    return _deep_merge_metadata(stage, {})


def _stage_semantic_payload(stage: Any) -> dict[str, Any]:
    if isinstance(stage, str):
        return {"C": stage}
    if not isinstance(stage, Mapping):
        return {"value": _metadata_value(stage)}
    payload = {
        key: _metadata_value(stage.get(key))
        for key in ("id", "stage_id", "label", "kind", "D", "Q", "M", "C", "R", "E")
        if key in stage
    }
    payload["depends_on"] = _stage_dependency_list(
        stage.get(
            "deps",
            stage.get("depends_on", stage.get("dependencies", [])),
        )
    )
    payload["produces"] = _metadata_string_list(stage.get("produces", []))
    payload.update(_stage_execution_controls(stage))
    return payload


def notebook_stage_fingerprint(
    module: str,
    module_index: int,
    stage: Any,
) -> str:
    """Fingerprint export-time semantics used to guard ID-less stage upserts.

    The source module and index locate the legacy stage candidate. This digest,
    which includes source, dependencies, and execution controls, proves that the
    persisted candidate has not changed since export. Edits inside the exported
    notebook are intentionally not part of this comparison: they are the update
    payload that may replace an otherwise unchanged target stage.
    """
    payload = {
        "module": str(module),
        "module_index": int(module_index),
        "stage": _stage_semantic_payload(stage),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _notebook_import_metadata_from_stage(raw_stage: Mapping[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    cell_id = str(raw_stage.get("NB_CELL_ID", "") or "")
    if cell_id:
        metadata["cell_id"] = cell_id

    raw_cell_index = raw_stage.get("NB_CELL_INDEX")
    if raw_cell_index not in (None, ""):
        try:
            metadata["source_cell_index"] = int(raw_cell_index)
        except (TypeError, ValueError):
            metadata["source_cell_index"] = str(raw_cell_index)

    context_ids = _metadata_string_list(raw_stage.get("NB_CONTEXT_IDS", []))
    if context_ids:
        metadata["context_ids"] = context_ids

    env_hints = _metadata_string_list(raw_stage.get("NB_ENV_HINTS", []))
    if env_hints:
        metadata["env_hints"] = env_hints

    artifact_references = _metadata_string_list(raw_stage.get("NB_ARTIFACT_REFERENCES", []))
    if artifact_references:
        metadata["artifact_references"] = artifact_references

    execution_mode = str(raw_stage.get("NB_EXECUTION_MODE", "") or "")
    if execution_mode:
        metadata["execution_mode"] = execution_mode

    source_notebook = str(raw_stage.get("NB_SOURCE_NOTEBOOK", "") or "")
    if source_notebook:
        metadata["source_notebook"] = source_notebook

    runtime_role = _normalize_notebook_runtime_role(raw_stage.get("NB_RUNTIME_ROLE", ""))
    if runtime_role:
        metadata["runtime_role"] = runtime_role

    raw_execution_count = raw_stage.get("NB_EXECUTION_COUNT")
    if raw_execution_count not in (None, ""):
        try:
            metadata["execution_count"] = int(raw_execution_count)
        except (TypeError, ValueError):
            metadata["execution_count"] = str(raw_execution_count)

    return metadata


def _stage_runtime_role(stage: Mapping[str, Any]) -> str:
    notebook_import = stage.get("notebook_import", {})
    if isinstance(notebook_import, Mapping):
        explicit_role = _normalize_notebook_runtime_role(notebook_import.get("runtime_role", ""))
        if explicit_role:
            return explicit_role
    explicit_role = _normalize_notebook_runtime_role(stage.get("runtime_role", ""))
    if explicit_role:
        return explicit_role
    return _runtime_role_from_engine(stage.get("runtime", ""))


def _module_stage_indices(
    toml_data: Mapping[str, Any],
    module: str,
    stages: Sequence[Any],
) -> list[int]:
    """Return the effective saved execution order for one module."""
    meta = toml_data.get("__meta__", {})
    raw_sequence = meta.get(f"{module}__sequence", []) if isinstance(meta, Mapping) else []
    ordered: list[int] = []
    if isinstance(raw_sequence, list):
        for raw_index in raw_sequence:
            if not isinstance(raw_index, int) or isinstance(raw_index, bool):
                continue
            if 0 <= raw_index < len(stages) and raw_index not in ordered:
                ordered.append(raw_index)
    ordered.extend(index for index in range(len(stages)) if index not in ordered)
    return ordered


def _topologically_order_stage_records(
    records: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep saved order as the tie-break while enforcing a valid stage graph."""
    ordered_records = list(records)
    records_by_id: dict[str, dict[str, Any]] = {}
    for record in ordered_records:
        stage_id = str(
            record.get("effective_stage_id", record.get("stage_id", "")) or ""
        )
        if stage_id in records_by_id:
            raise ValueError(f"Duplicate workflow stage ID {stage_id!r} in notebook export.")
        records_by_id[stage_id] = record
    known_ids = set(records_by_id)
    for record in ordered_records:
        stage_id = str(
            record.get("effective_stage_id", record.get("stage_id", "")) or ""
        )
        missing = [
            dependency
            for dependency in _metadata_string_list(
                record.get("effective_depends_on", record.get("depends_on", []))
            )
            if dependency not in known_ids
        ]
        if missing:
            raise ValueError(
                f"Workflow stage {stage_id!r} depends on missing stage ID(s): "
                f"{', '.join(missing)}."
            )
    emitted: set[str] = set()
    remaining = list(ordered_records)
    result: list[dict[str, Any]] = []
    while remaining:
        ready_offset = next(
            (
                offset
                for offset, record in enumerate(remaining)
                if all(
                    dependency in emitted
                    for dependency in _metadata_string_list(
                        record.get(
                            "effective_depends_on",
                            record.get("depends_on", []),
                        )
                    )
                )
            ),
            None,
        )
        if ready_offset is None:
            blocked = ", ".join(
                str(
                    record.get(
                        "effective_stage_id",
                        record.get("stage_id", ""),
                    )
                    or "(unnamed stage)"
                )
                for record in remaining
            )
            raise ValueError(
                "Workflow stage dependencies contain a cycle or self-dependency: "
                f"{blocked}."
            )
        record = remaining.pop(ready_offset)
        result.append(record)
        stage_id = str(
            record.get("effective_stage_id", record.get("stage_id", "")) or ""
        )
        emitted.add(stage_id)
    for index, record in enumerate(result):
        record["index"] = index
    return result


def _stage_records(
    toml_data: Dict[str, Any],
    *,
    module_key: str | None = None,
    profile: str = "balanced",
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    global_index = 0
    for module, stages in toml_data.items():
        if module == "__meta__" or not isinstance(stages, list):
            continue
        if module_key is not None and str(module) != module_key:
            continue
        for module_index in _module_stage_indices(toml_data, str(module), stages):
            raw_stage = stages[module_index]
            if isinstance(raw_stage, dict):
                effective_stage = _stage_with_profile(raw_stage, profile)
                code_text = str(raw_stage.get("C", "") or "")
                description = str(raw_stage.get("D", "") or "")
                question = str(raw_stage.get("Q", "") or "")
                model = str(raw_stage.get("M", "") or "")
                runtime = str(raw_stage.get("R", "") or "")
                env_root = _normalize_path(raw_stage.get("E", ""))
                notebook_import = _notebook_import_metadata_from_stage(raw_stage)
                explicit_stage_id = str(
                    raw_stage.get("id", "") or raw_stage.get("stage_id", "") or ""
                ).strip()
                label = str(raw_stage.get("label", "") or "")
                kind = str(raw_stage.get("kind", "") or "")
                depends_on = _stage_dependency_list(
                    raw_stage.get(
                        "deps",
                        raw_stage.get(
                            "depends_on", raw_stage.get("dependencies", [])
                        ),
                    )
                )
                produces = _metadata_string_list(raw_stage.get("produces", []))
                execution_controls = _stage_execution_controls(raw_stage)
                effective_stage_id = str(
                    effective_stage.get("id", "")
                    or effective_stage.get("stage_id", "")
                    or f"stage_{module_index + 1}"
                ).strip()
                effective_depends_on = _stage_dependency_list(
                    effective_stage.get(
                        "deps",
                        effective_stage.get(
                            "depends_on",
                            effective_stage.get("dependencies", []),
                        ),
                    )
                )
            elif isinstance(raw_stage, str):
                code_text = raw_stage
                description = ""
                question = ""
                model = ""
                runtime = ""
                env_root = ""
                notebook_import = {}
                explicit_stage_id = ""
                label = ""
                kind = ""
                depends_on = []
                produces = []
                execution_controls = {}
                effective_stage_id = f"stage_{module_index + 1}"
                effective_depends_on = []
            else:
                continue
            if not code_text:
                continue
            runtime_role = _normalize_notebook_runtime_role(
                notebook_import.get("runtime_role", "")
            ) or _runtime_role_from_engine(runtime)
            stage_id = explicit_stage_id or f"supervisor-stage-{global_index + 1}"
            record = {
                "index": global_index,
                "module": str(module),
                "module_index": module_index,
                "stage_id": stage_id,
                "stage_id_explicit": bool(explicit_stage_id),
                "effective_stage_id": effective_stage_id,
                "label": label,
                "kind": kind,
                "depends_on": depends_on,
                "effective_depends_on": effective_depends_on,
                "produces": produces,
                "description": description,
                "question": question,
                "model": model,
                "runtime": runtime,
                "runtime_role": runtime_role,
                "env": env_root,
                "code": code_text,
                "source_stage_fingerprint": notebook_stage_fingerprint(
                    str(module), module_index, raw_stage
                ),
            }
            record.update(execution_controls)
            if notebook_import:
                record["notebook_import"] = notebook_import
            records.append(record)
            global_index += 1
    return _topologically_order_stage_records(records)


def _export_module_key(
    toml_data: Mapping[str, Any],
    export_context: NotebookExportContext,
) -> str:
    modules = [
        str(key)
        for key, value in toml_data.items()
        if key != "__meta__" and isinstance(value, list)
    ]
    requested_module = str(export_context.module_path or "").strip()
    candidates = [requested_module]
    if requested_module:
        candidates.append(Path(requested_module).as_posix())
    else:
        candidates.append(str(export_context.project_name or "").strip())
    if not modules:
        empty_module = next((candidate for candidate in candidates if candidate), "")
        if empty_module:
            return empty_module
    for candidate in candidates:
        if candidate and candidate in modules:
            return candidate
    if len(modules) == 1:
        return modules[0]
    raise ValueError(
        "Unable to identify the active workflow module for notebook export. "
        f"Requested {export_context.module_path!r}; available modules: {', '.join(modules) or '(none)'}."
    )


def _module_automation_preferences(
    toml_data: Mapping[str, Any],
    module_key: str,
) -> dict[str, Any]:
    metadata = toml_data.get("__meta__", {})
    if not isinstance(metadata, Mapping):
        return {}
    raw = metadata.get(f"{module_key}__automation", {})
    return _metadata_value(raw) if isinstance(raw, Mapping) else {}


def _cell_id(*parts: Any) -> str:
    raw = "-".join(str(part or "").strip().lower() for part in parts if str(part or "").strip())
    normalized = "".join(char if char.isalnum() else "-" for char in raw)
    normalized = "-".join(part for part in normalized.split("-") if part)
    return (normalized or "agilab-cell")[:64]


def _with_cell_id(cell: dict[str, Any], cell_id: str | None) -> dict[str, Any]:
    if cell_id:
        cell["id"] = cell_id
    return cell


def _markdown_cell(text: str, *, cell_id: str | None = None) -> dict[str, Any]:
    return _with_cell_id({
        "cell_type": "markdown",
        "metadata": {},
        "source": [line if line.endswith("\n") else line + "\n" for line in text.splitlines()],
    }, cell_id)


def _code_cell(
    code: str,
    *,
    metadata: Mapping[str, Any] | None = None,
    cell_id: str | None = None,
) -> dict[str, Any]:
    return _with_cell_id({
        "cell_type": "code",
        "execution_count": None,
        "metadata": dict(metadata or {}),
        "outputs": [],
        "source": code.splitlines(keepends=True),
    }, cell_id)


def notebook_export_manifest_path(notebook_path: str | Path) -> Path:
    path = Path(notebook_path)
    return path.with_suffix(".notebook_export.json")


def notebook_export_handoff_path(notebook_path: str | Path) -> Path:
    path = Path(notebook_path)
    return path.with_suffix(".notebook_export.md")


def notebook_export_json_text(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def notebook_export_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(notebook_export_json_text(payload).encode("utf-8")).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _notebook_agilab_metadata(notebook_data: Mapping[str, Any]) -> Mapping[str, Any]:
    metadata = notebook_data.get("metadata", {})
    if not isinstance(metadata, Mapping):
        return {}
    agilab_metadata = metadata.get("agilab", {})
    return agilab_metadata if isinstance(agilab_metadata, Mapping) else {}


def _notebook_cells(notebook_data: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    cells = notebook_data.get("cells", [])
    if not isinstance(cells, list):
        return []
    return [cell for cell in cells if isinstance(cell, Mapping)]


def _stage_cell_manifest_records(notebook_data: Mapping[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, cell in enumerate(_notebook_cells(notebook_data)):
        metadata = cell.get("metadata", {})
        if not isinstance(metadata, Mapping):
            continue
        agilab_metadata = metadata.get("agilab", {})
        if not isinstance(agilab_metadata, Mapping):
            continue
        stage_cell = agilab_metadata.get("stage_cell", {})
        if not isinstance(stage_cell, Mapping) or not stage_cell:
            continue
        record = {
            "cell_index": index,
            "cell_id": str(cell.get("id", "") or ""),
            "kind": str(stage_cell.get("kind", "") or ""),
            "stage_index": stage_cell.get("stage_index"),
            "stage_id": str(stage_cell.get("stage_id", "") or ""),
            "module": str(stage_cell.get("module", "") or ""),
            "module_index": stage_cell.get("module_index"),
            "runtime": str(stage_cell.get("runtime", "") or ""),
            "runtime_role": str(
                stage_cell.get("runtime_role", "") or agilab_metadata.get("runtime_role", "") or ""
            ),
            "env": str(stage_cell.get("env", "") or ""),
        }
        if bool(stage_cell.get("stage_id_explicit", False)):
            record["stage_id_explicit"] = True
        source_stage_fingerprint = str(
            stage_cell.get("source_stage_fingerprint", "") or ""
        )
        if source_stage_fingerprint:
            record["source_stage_fingerprint"] = source_stage_fingerprint
        for key in ("label", "stage_kind"):
            value = str(stage_cell.get(key, "") or "")
            if value:
                record[key] = value
        for key in ("depends_on", "produces"):
            values = _metadata_string_list(stage_cell.get(key, []))
            if values:
                record[key] = values
        notebook_import = stage_cell.get("notebook_import", {})
        if isinstance(notebook_import, Mapping) and notebook_import:
            record["notebook_import"] = dict(notebook_import)
        records.append(record)
    return records


def _cell_source_text(cell: Mapping[str, Any]) -> str:
    source = cell.get("source", [])
    if isinstance(source, str):
        return source
    if isinstance(source, Iterable):
        return "".join(str(line) for line in source)
    return str(source or "")


def _extract_stage_source_from_exported_cell(cell: Mapping[str, Any], stage_index: int) -> str:
    source_text = _cell_source_text(cell)
    variable_name = f"STAGE_{stage_index:03d}_CODE"
    try:
        tree = ast.parse(source_text or "")
    except SyntaxError:
        return source_text
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id != variable_name:
            continue
        try:
            value = ast.literal_eval(node.value)
        except (TypeError, ValueError):
            continue
        if isinstance(value, str):
            return value
    return source_text


def _stage_source_hashes(metadata: Mapping[str, Any]) -> list[dict[str, Any]]:
    stages = metadata.get("stages", [])
    if not isinstance(stages, list):
        return []
    records: list[dict[str, Any]] = []
    for offset, stage in enumerate(stage for stage in stages if isinstance(stage, Mapping)):
        stage_index = int(stage.get("index", offset) or 0)
        source = str(stage.get("code", "") or "")
        record = {
            "stage_index": stage_index,
            "stage_id": str(stage.get("stage_id", "") or f"supervisor-stage-{stage_index + 1}"),
            "module": str(stage.get("module", "") or ""),
            "module_index": stage.get("module_index"),
            "source_sha256": _sha256_text(source),
            "source_hash": _sha256_text(source)[:16],
            "runtime": str(stage.get("runtime", "") or ""),
            "runtime_role": _stage_runtime_role(stage),
        }
        notebook_import = stage.get("notebook_import", {})
        if isinstance(notebook_import, Mapping) and notebook_import:
            record["notebook_import"] = dict(notebook_import)
        records.append(record)
    return records


def _stage_manifest_records(metadata: Mapping[str, Any]) -> list[dict[str, Any]]:
    stages = metadata.get("stages", [])
    if not isinstance(stages, list):
        return []
    records: list[dict[str, Any]] = []
    for offset, stage in enumerate(stage for stage in stages if isinstance(stage, Mapping)):
        stage_index = int(stage.get("index", offset) or 0)
        runtime = str(stage.get("runtime", "") or "")
        record = {
            "stage_index": stage_index,
            "stage_id": str(stage.get("stage_id", "") or f"supervisor-stage-{stage_index + 1}"),
            "stage_id_explicit": bool(stage.get("stage_id_explicit", False)),
            "effective_stage_id": str(stage.get("effective_stage_id", "") or ""),
            "module": str(stage.get("module", "") or ""),
            "module_index": stage.get("module_index"),
            "label": str(stage.get("label", "") or ""),
            "kind": str(stage.get("kind", "") or ""),
            "depends_on": _metadata_string_list(stage.get("depends_on", [])),
            "effective_depends_on": _metadata_string_list(
                stage.get("effective_depends_on", [])
            ),
            "produces": _metadata_string_list(stage.get("produces", [])),
            "description": str(stage.get("description", "") or ""),
            "question": str(stage.get("question", "") or ""),
            "model": str(stage.get("model", "") or ""),
            "runtime": runtime,
            "runtime_role": _stage_runtime_role(stage),
            "env": str(stage.get("env", "") or ""),
            "source_hash": _sha256_text(str(stage.get("code", "") or ""))[:16],
            "source_stage_fingerprint": str(
                stage.get("source_stage_fingerprint", "") or ""
            ),
        }
        notebook_import = stage.get("notebook_import", {})
        if isinstance(notebook_import, Mapping) and notebook_import:
            record["notebook_import"] = dict(notebook_import)
        record.update(_stage_execution_controls(stage))
        records.append(record)
    return records


def _related_page_manifest_records(metadata: Mapping[str, Any]) -> list[dict[str, Any]]:
    pages = metadata.get("related_pages", [])
    if not isinstance(pages, list):
        return []
    records: list[dict[str, Any]] = []
    for page in (page for page in pages if isinstance(page, Mapping)):
        records.append(
            {
                "module": str(page.get("module", "") or ""),
                "label": str(page.get("label", "") or ""),
                "description": str(page.get("description", "") or ""),
                "artifacts": [str(item) for item in page.get("artifacts", []) if str(item or "").strip()]
                if isinstance(page.get("artifacts", []), (list, tuple))
                else [],
                "launch_note": str(page.get("launch_note", "") or ""),
                "script_path": str(page.get("script_path", "") or ""),
                "inline_renderer": str(page.get("inline_renderer", "") or ""),
                "script_sha256": str(page.get("script_sha256", "") or ""),
                "inline_renderer_sha256": str(page.get("inline_renderer_sha256", "") or ""),
            }
        )
    return records


def _path_kind(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "missing"
    if Path(text).is_absolute() or (len(text) >= 3 and text[1] == ":" and text[2] in {"\\", "/"}):
        return "absolute"
    return "relative"


def build_notebook_export_portability_review(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Return an honest portability review for a notebook export handoff."""
    path_fields = [
        ("notebook", manifest.get("notebook_path")),
        ("manifest", manifest.get("manifest_path")),
        ("handoff", manifest.get("handoff_path")),
        ("artifact_dir", manifest.get("artifact_dir")),
        ("active_app", manifest.get("active_app")),
        ("stages_file", manifest.get("stages_file")),
        ("mirror", manifest.get("mirror_path")),
        ("sitecustomize", manifest.get("sitecustomize_path")),
    ]
    paths = [
        {"label": label, "path": str(path or ""), "kind": _path_kind(path)}
        for label, path in path_fields
        if str(path or "").strip()
    ]
    stages = manifest.get("stages", [])
    stage_records = [stage for stage in stages if isinstance(stage, Mapping)] if isinstance(stages, list) else []
    worker_stage_count = sum(
        1
        for stage in stage_records
        if str(stage.get("runtime_role", "") or "") == "worker"
        or str(stage.get("runtime", "") or "") in {"agi", "agi.run"}
    )
    env_path_count = sum(1 for stage in stage_records if str(stage.get("env", "") or "").strip())
    absolute_path_count = sum(1 for path in paths if path["kind"] == "absolute")
    related_page_count = int(manifest.get("related_page_count", 0) or 0)

    actions = ["Run `validate_agilab_export()` after moving or editing the notebook."]
    if str(manifest.get("active_app", "") or "").strip():
        actions.append("Keep or reinstall the active app root before replaying AGILAB runner cells.")
    if worker_stage_count:
        actions.append("Worker stages still need AGILAB runtime access, or must be rewritten as local notebook code.")
    if env_path_count:
        actions.append("Check recorded stage environment paths before executing on another machine.")
    if absolute_path_count:
        actions.append("Update absolute paths if the export is shared outside this workstation.")
    if related_page_count:
        actions.append("Recreate expected artifacts before opening related analysis pages.")

    project_bound = bool(worker_stage_count or env_path_count or str(manifest.get("active_app", "") or "").strip())
    level = "project-bound" if project_bound else "notebook-local"
    summary = (
        "Project-bound export: the notebook is runnable, but AGILAB app/runtime paths remain part of the contract."
        if project_bound
        else "Notebook-local export: no AGILAB worker/runtime path was recorded, but validation is still required."
    )
    return {
        "schema": "agilab.notebook_export_portability.v1",
        "level": level,
        "summary": summary,
        "absolute_path_count": absolute_path_count,
        "worker_stage_count": worker_stage_count,
        "env_path_count": env_path_count,
        "related_page_count": related_page_count,
        "paths": paths,
        "actions": actions,
    }


def build_notebook_export_manifest(
    notebook_data: Mapping[str, Any],
    notebook_path: str | Path,
    *,
    mirror_path: str | Path | None = None,
    sitecustomize_path: str | Path | None = None,
    handoff_path: str | Path | None = None,
    handoff_sha256: str = "",
) -> dict[str, Any]:
    metadata = _notebook_agilab_metadata(notebook_data)
    cells = _notebook_cells(notebook_data)
    stages = metadata.get("stages", [])
    related_pages = metadata.get("related_pages", [])
    manifest = {
        "schema": NOTEBOOK_EXPORT_MANIFEST_SCHEMA,
        "version": NOTEBOOK_EXPORT_SCHEMA_VERSION,
        "notebook_path": str(Path(notebook_path)),
        "manifest_path": str(notebook_export_manifest_path(notebook_path)),
        "handoff_path": str(Path(handoff_path)) if handoff_path else str(notebook_export_handoff_path(notebook_path)),
        "handoff_sha256": str(handoff_sha256 or ""),
        "mirror_path": str(Path(mirror_path)) if mirror_path else "",
        "sitecustomize_path": str(Path(sitecustomize_path)) if sitecustomize_path else "",
        "project_name": str(metadata.get("project_name", "") or ""),
        "module_path": str(metadata.get("module_path", "") or ""),
        "artifact_dir": str(metadata.get("artifact_dir", "") or ""),
        "active_app": str(metadata.get("active_app", "") or ""),
        "stages_file": str(metadata.get("stages_file", "") or ""),
        "export_mode": str(metadata.get("export_mode", "") or ""),
        "stage_count": len(stages) if isinstance(stages, list) else 0,
        "related_page_count": len(related_pages) if isinstance(related_pages, list) else 0,
        "cell_count": len(cells),
        "cell_ids": [str(cell.get("id", "") or "") for cell in cells],
        "notebook_sha256": notebook_export_sha256(notebook_data),
        "stages": _stage_manifest_records(metadata),
        "related_pages": _related_page_manifest_records(metadata),
        "view_sync": dict(metadata.get("view_sync", {})) if isinstance(metadata.get("view_sync", {}), Mapping) else {},
        "stage_source_hashes": _stage_source_hashes(metadata),
        "stage_cells": _stage_cell_manifest_records(notebook_data),
    }
    manifest["portability_review"] = build_notebook_export_portability_review(manifest)
    return manifest


def _markdown_code(value: Any) -> str:
    text = str(value or "").strip()
    return f"`{text}`" if text else "`(not set)`"


def build_notebook_export_handoff_markdown(manifest: Mapping[str, Any]) -> str:
    project = str(manifest.get("project_name", "") or "AGILAB project")
    notebook_path = str(manifest.get("notebook_path", "") or "")
    active_app = str(manifest.get("active_app", "") or "")
    stage_records = manifest.get("stages", [])
    stages = [stage for stage in stage_records if isinstance(stage, Mapping)] if isinstance(stage_records, list) else []
    pages = manifest.get("related_pages", [])
    related_pages = [page for page in pages if isinstance(page, Mapping)] if isinstance(pages, list) else []
    portability_review = manifest.get("portability_review", {})
    if not isinstance(portability_review, Mapping) or not portability_review:
        portability_review = build_notebook_export_portability_review(manifest)

    quoted_notebook_path = shlex.quote(notebook_path)
    open_prefix = "uv run"
    if active_app:
        open_prefix = f"uv --project {shlex.quote(active_app)} run"
    jupyter_command = f"{open_prefix} --with jupyterlab jupyter lab {quoted_notebook_path}".strip()
    execute_command = (
        f"{open_prefix} --with nbconvert python -m jupyter nbconvert "
        f"--to notebook --execute --inplace {quoted_notebook_path}"
    ).strip()

    lines = [
        f"# AGILAB notebook handoff: {project}",
        "",
        f"Schema: `{NOTEBOOK_EXPORT_HANDOFF_SCHEMA}`",
        "",
        "This folder is a durable exit path from AGILAB: the notebook contains editable stage source cells, runner cells, validation helpers, and enough metadata to verify that the export has not drifted.",
        "",
        "## Files",
        "",
        f"- Notebook: {_markdown_code(notebook_path)}",
        f"- Manifest: {_markdown_code(manifest.get('manifest_path'))}",
        f"- Handoff: {_markdown_code(manifest.get('handoff_path'))}",
        f"- PyCharm/Jupyter mirror: {_markdown_code(manifest.get('mirror_path'))}",
        f"- Artifact directory: {_markdown_code(manifest.get('artifact_dir'))}",
        f"- Active app root: {_markdown_code(active_app)}",
        "",
        "## First actions",
        "",
        "1. Open the notebook.",
        "2. Run `validate_agilab_export()` before executing workflow code.",
        "3. Run `run_agilab_stage(i)` for one stage, or `run_agilab_pipeline()` for the full workflow.",
        "4. Edit `STAGE_###_CODE` cells when you want the notebook to become the new source of truth.",
        "",
        "## Commands",
        "",
        "```bash",
        jupyter_command,
        execute_command,
        "```",
        "",
        "## Integrity",
        "",
        f"- Notebook SHA-256: `{manifest.get('notebook_sha256', '')}`",
        "- Handoff SHA-256: recorded in the manifest field `handoff_sha256`.",
        "",
        "## Portability Review",
        "",
        f"- Status: **{portability_review.get('level', 'unknown')}**",
        f"- Critic note: {portability_review.get('summary', 'Run validation before trusting this export.')}",
        f"- Absolute paths: {int(portability_review.get('absolute_path_count', 0) or 0)}",
        f"- Worker/runtime stages: {int(portability_review.get('worker_stage_count', 0) or 0)}",
        f"- Recorded stage environments: {int(portability_review.get('env_path_count', 0) or 0)}",
        "",
        "Recommended checks:",
    ]
    actions = portability_review.get("actions", [])
    if isinstance(actions, list) and actions:
        lines.extend(f"- {action}" for action in actions if str(action or "").strip())
    else:
        lines.append("- Run `validate_agilab_export()` before executing workflow code.")
    lines.extend([
        "",
        "## Stages",
        "",
        "| Stage | Role | Runtime | Source hash | Description |",
        "|---:|---|---|---|---|",
    ])
    if stages:
        for stage in stages:
            description = str(stage.get("description", "") or "").replace("|", "\\|")
            lines.append(
                "| "
                f"{stage.get('stage_index', '')} | "
                f"{stage.get('runtime_role', '') or 'manager'} | "
                f"{stage.get('runtime', '') or 'runpy'} | "
                f"`{stage.get('source_hash', '')}` | "
                f"{description or '(no description)'} |"
            )
    else:
        lines.append("| - | - | - | - | No executable stages exported. |")

    if related_pages:
        lines.extend(["", "## Related Analysis Pages", ""])
        for page in related_pages:
            label = str(page.get("label", "") or page.get("module", "") or "analysis page")
            lines.append(f"- **{label}** ({page.get('module', '')})")
            description = str(page.get("description", "") or "")
            if description:
                lines.append(f"  - {description}")
            artifacts = page.get("artifacts", [])
            if isinstance(artifacts, list) and artifacts:
                lines.append("  - Expected artifacts: " + ", ".join(f"`{artifact}`" for artifact in artifacts))
            if page.get("inline_renderer"):
                lines.append(f"  - Inline renderer: `{page.get('inline_renderer')}`")
            if page.get("script_path"):
                lines.append(f"  - Streamlit script: `{page.get('script_path')}`")

    lines.extend(["", "## Re-import Contract", "", "Supervisor metadata and per-cell AGILAB stage metadata are preserved so AGILAB can import edited stage source cells back into `lab_stages.toml` without guessing manager versus worker ownership.", ""])
    return "\n".join(lines)


def _read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _verification_check(checks: list[dict[str, Any]], check_id: str, ok: bool, summary: str, **details: Any) -> bool:
    checks.append(
        {
            "id": check_id,
            "status": "pass" if ok else "fail",
            "summary": summary,
            "details": details,
        }
    )
    return ok


def _view_sync_source_drift(manifest: Mapping[str, Any]) -> tuple[int, list[dict[str, Any]], list[dict[str, Any]], int]:
    view_sync = manifest.get("view_sync", {})
    if not isinstance(view_sync, Mapping):
        return 0, [], [], 0
    raw_sources = view_sync.get("sources", [])
    if not isinstance(raw_sources, list):
        return 0, [], [], 0

    checked = 0
    changed: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []
    for raw_source in raw_sources:
        if not isinstance(raw_source, Mapping):
            continue
        path = str(raw_source.get("path", "") or "").strip()
        expected_sha256 = str(raw_source.get("sha256", "") or "").strip()
        if not path or not expected_sha256:
            continue
        actual_sha256 = _file_sha256(path)
        record = {
            "kind": str(raw_source.get("kind", "") or ""),
            "module": str(raw_source.get("module", "") or ""),
            "path": path,
            "expected_sha256": expected_sha256,
            "actual_sha256": actual_sha256,
        }
        if not actual_sha256:
            unavailable.append(record)
            continue
        checked += 1
        if actual_sha256 != expected_sha256:
            changed.append(record)
    return checked, changed, unavailable, len(raw_sources)


def verify_notebook_export_manifest(
    notebook_path: str | Path,
    manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    """Verify an exported notebook against its sidecar manifest without executing it."""
    notebook_file = Path(notebook_path)
    manifest_file = Path(manifest_path) if manifest_path is not None else notebook_export_manifest_path(notebook_file)
    checks: list[dict[str, Any]] = []

    if not notebook_file.is_file():
        _verification_check(checks, "notebook_exists", False, "Notebook file exists.", notebook_path=str(notebook_file))
        return {"ok": False, "notebook_path": str(notebook_file), "manifest_path": str(manifest_file), "checks": checks}
    _verification_check(checks, "notebook_exists", True, "Notebook file exists.", notebook_path=str(notebook_file))

    if not manifest_file.is_file():
        _verification_check(checks, "manifest_exists", False, "Notebook export manifest exists.", manifest_path=str(manifest_file))
        return {"ok": False, "notebook_path": str(notebook_file), "manifest_path": str(manifest_file), "checks": checks}
    _verification_check(checks, "manifest_exists", True, "Notebook export manifest exists.", manifest_path=str(manifest_file))

    notebook = _read_json_object(notebook_file)
    manifest = _read_json_object(manifest_file)
    expected_schema = str(manifest.get("schema", "") or "")
    _verification_check(
        checks,
        "manifest_schema",
        expected_schema == NOTEBOOK_EXPORT_MANIFEST_SCHEMA,
        "Notebook export manifest schema is supported.",
        schema=expected_schema,
        expected_schema=NOTEBOOK_EXPORT_MANIFEST_SCHEMA,
    )

    expected_hash = str(manifest.get("notebook_sha256", "") or "")
    actual_hash = _sha256_text(notebook_file.read_text(encoding="utf-8"))
    _verification_check(
        checks,
        "notebook_sha256",
        bool(expected_hash) and expected_hash == actual_hash,
        "Notebook file hash matches the export manifest.",
        expected_sha256=expected_hash,
        actual_sha256=actual_hash,
    )

    manifest_cell_ids = [str(value or "") for value in manifest.get("cell_ids", []) if isinstance(value, str)]
    actual_cell_ids = [str(cell.get("id", "") or "") for cell in _notebook_cells(notebook)]
    _verification_check(
        checks,
        "cell_ids",
        manifest_cell_ids == actual_cell_ids,
        "Notebook cell IDs match the export manifest.",
        expected_cell_ids=manifest_cell_ids,
        actual_cell_ids=actual_cell_ids,
    )

    handoff_path = str(manifest.get("handoff_path", "") or "")
    expected_handoff_hash = str(manifest.get("handoff_sha256", "") or "")
    if handoff_path:
        handoff_file = Path(handoff_path)
        handoff_exists = handoff_file.is_file()
        _verification_check(
            checks,
            "handoff_exists",
            handoff_exists,
            "Notebook export handoff file exists.",
            handoff_path=handoff_path,
        )
        actual_handoff_hash = _sha256_text(handoff_file.read_text(encoding="utf-8")) if handoff_exists else ""
        _verification_check(
            checks,
            "handoff_sha256",
            handoff_exists and bool(expected_handoff_hash) and expected_handoff_hash == actual_handoff_hash,
            "Notebook export handoff hash matches the manifest.",
            expected_sha256=expected_handoff_hash,
            actual_sha256=actual_handoff_hash,
        )

    source_cells_by_stage: dict[int, Mapping[str, Any]] = {}
    for cell in _notebook_cells(notebook):
        metadata = cell.get("metadata", {})
        if not isinstance(metadata, Mapping):
            continue
        agilab_metadata = metadata.get("agilab", {})
        if not isinstance(agilab_metadata, Mapping):
            continue
        stage_cell = agilab_metadata.get("stage_cell", {})
        if not isinstance(stage_cell, Mapping):
            continue
        if str(stage_cell.get("kind", "") or "") != "source":
            continue
        try:
            stage_index = int(stage_cell.get("stage_index", 0) or 0)
        except (TypeError, ValueError):
            continue
        source_cells_by_stage.setdefault(stage_index, cell)

    for record in manifest.get("stage_source_hashes", []):
        if not isinstance(record, Mapping):
            continue
        try:
            stage_index = int(record.get("stage_index", 0) or 0)
        except (TypeError, ValueError):
            stage_index = -1
        expected_source_hash = str(record.get("source_sha256", "") or "")
        cell = source_cells_by_stage.get(stage_index)
        source = _extract_stage_source_from_exported_cell(cell, stage_index) if cell is not None else ""
        actual_source_hash = _sha256_text(source) if source or cell is not None else ""
        _verification_check(
            checks,
            f"stage_source_{stage_index}",
            cell is not None and bool(expected_source_hash) and expected_source_hash == actual_source_hash,
            f"Stage {stage_index} source hash matches the export manifest.",
            stage_index=stage_index,
            expected_sha256=expected_source_hash,
            actual_sha256=actual_source_hash,
        )

    checked_sources, changed_sources, unavailable_sources, total_sources = _view_sync_source_drift(manifest)
    if total_sources:
        _verification_check(
            checks,
            "view_sync_sources",
            not changed_sources,
            "Reachable app settings, page manifests, and analysis page sources match the notebook export snapshot.",
            source_count=total_sources,
            checked_count=checked_sources,
            changed_sources=changed_sources,
            unavailable_sources=unavailable_sources,
        )

    return {
        "ok": all(check["status"] == "pass" for check in checks),
        "notebook_path": str(notebook_file),
        "manifest_path": str(manifest_file),
        "checks": checks,
    }


def notebook_view_sync_status(
    notebook_path: str | Path,
    manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    """Summarize both drift directions between an exported notebook and AGILAB views."""
    verification = verify_notebook_export_manifest(notebook_path, manifest_path=manifest_path)
    checks = verification.get("checks", [])
    check_records = [check for check in checks if isinstance(check, Mapping)]
    failed_checks = [check for check in check_records if check.get("status") != "pass"]
    failed_ids = {str(check.get("id", "") or "") for check in failed_checks}

    source_check = next((check for check in check_records if check.get("id") == "view_sync_sources"), {})
    source_details = source_check.get("details", {}) if isinstance(source_check, Mapping) else {}
    if not isinstance(source_details, Mapping):
        source_details = {}
    changed_sources = source_details.get("changed_sources", [])
    unavailable_sources = source_details.get("unavailable_sources", [])
    changed_source_count = len(changed_sources) if isinstance(changed_sources, list) else 0
    unavailable_source_count = len(unavailable_sources) if isinstance(unavailable_sources, list) else 0
    source_changed = str(source_check.get("status", "") or "") == "fail" and changed_source_count > 0

    notebook_content_check_ids = {"notebook_sha256", "cell_ids"}
    notebook_changed = any(check_id in failed_ids for check_id in notebook_content_check_ids) or any(
        check_id.startswith("stage_source_") for check_id in failed_ids
    )
    manifest_problem = any(check_id in failed_ids for check_id in {"notebook_exists", "manifest_exists", "manifest_schema"})
    handoff_changed = any(check_id in failed_ids for check_id in {"handoff_exists", "handoff_sha256"})

    if manifest_problem:
        state = "unverified"
        summary = "Notebook sync could not be verified because the export notebook or manifest is missing or unsupported."
    elif source_changed and notebook_changed:
        state = "both_changed"
        summary = "Both the notebook and linked AGILAB view/app sources changed since export."
    elif source_changed:
        state = "source_changed"
        summary = "Linked AGILAB view/app sources changed since this notebook was exported."
    elif notebook_changed:
        state = "notebook_changed"
        summary = "The notebook changed since export; re-import edited stage cells before treating AGILAB sources as current."
    elif failed_checks:
        state = "support_changed"
        summary = "Notebook export support files changed or are unavailable."
    else:
        state = "synced"
        summary = "Notebook, export manifest, and linked AGILAB view/app sources are synchronized."

    fallback_manifest_path = (
        str(Path(manifest_path))
        if manifest_path is not None
        else str(notebook_export_manifest_path(notebook_path))
    )
    return {
        "schema": NOTEBOOK_VIEW_SYNC_STATUS_SCHEMA,
        "ok": bool(verification.get("ok")),
        "state": state,
        "summary": summary,
        "notebook_changed": notebook_changed,
        "source_changed": source_changed,
        "handoff_changed": handoff_changed,
        "changed_source_count": changed_source_count,
        "unavailable_source_count": unavailable_source_count,
        "failed_check_ids": sorted(failed_ids),
        "notebook_path": verification.get("notebook_path", str(Path(notebook_path))),
        "manifest_path": verification.get("manifest_path", fallback_manifest_path),
        "verification": verification,
    }




def _analysis_cell(page: RelatedPageExport) -> str:
    return textwrap.dedent(
        f"""
        page = {page.module!r}
        render_analysis_page(page)
        """
    ).strip() + "\n"


def _validation_cell() -> str:
    return "validate_agilab_export()\n"


def _handoff_cell() -> str:
    return "show_agilab_export_handoff()\n"


def _stage_code_variable_name(stage: dict[str, Any]) -> str:
    return f"STAGE_{int(stage['index']):03d}_CODE"


def _stage_source_cell(stage: dict[str, Any]) -> str:
    variable_name = _stage_code_variable_name(stage)
    code_text = str(stage.get("code", "") or "")
    return f"{variable_name} = {code_text!r}\nprint({variable_name})\n"


def _stage_runner_cell(stage: dict[str, Any]) -> str:
    variable_name = _stage_code_variable_name(stage)
    return textwrap.dedent(
        f"""
        run_agilab_stage({int(stage['index'])}, code_override={variable_name})
        """
    ).strip() + "\n"


def _stage_cell_metadata(stage: dict[str, Any], *, kind: str) -> dict[str, Any]:
    stage_index = int(stage.get("index", 0) or 0)
    runtime = str(stage.get("runtime", "") or "")
    runtime_role = _stage_runtime_role(stage)
    stage_cell = {
        "schema": NOTEBOOK_EXPORT_STAGE_CELL_SCHEMA,
        "kind": kind,
        "stage_index": stage_index,
        "stage_id": str(stage.get("stage_id", "") or f"supervisor-stage-{stage_index + 1}"),
        "stage_id_explicit": bool(stage.get("stage_id_explicit", False)),
        "effective_stage_id": str(stage.get("effective_stage_id", "") or ""),
        "module": str(stage.get("module", "") or ""),
        "module_index": int(stage.get("module_index", 0) or 0),
        "label": str(stage.get("label", "") or ""),
        "stage_kind": str(stage.get("kind", "") or ""),
        "depends_on": _metadata_string_list(stage.get("depends_on", [])),
        "effective_depends_on": _metadata_string_list(
            stage.get("effective_depends_on", [])
        ),
        "produces": _metadata_string_list(stage.get("produces", [])),
        "description": str(stage.get("description", "") or ""),
        "question": str(stage.get("question", "") or ""),
        "model": str(stage.get("model", "") or ""),
        "runtime": runtime,
        "env": str(stage.get("env", "") or ""),
        "source_stage_fingerprint": str(
            stage.get("source_stage_fingerprint", "") or ""
        ),
    }
    if runtime_role:
        stage_cell["runtime_role"] = runtime_role
    notebook_import = stage.get("notebook_import", {})
    if isinstance(notebook_import, Mapping) and notebook_import:
        stage_cell["notebook_import"] = dict(notebook_import)
    stage_cell.update(_stage_execution_controls(stage))

    agilab_payload: dict[str, Any] = {
        "schema": NOTEBOOK_EXPORT_SCHEMA,
        "stage_cell": stage_cell,
    }
    if runtime_role:
        agilab_payload["runtime_role"] = runtime_role
    if isinstance(notebook_import, Mapping) and notebook_import:
        agilab_payload["notebook_import"] = dict(notebook_import)

    metadata: dict[str, Any] = {"agilab": agilab_payload}
    if runtime_role:
        metadata["tags"] = [f"agilab.runtime.{runtime_role}"]
    return metadata


def _stage_notebook_import_context_lines(stage: Mapping[str, Any]) -> list[str]:
    notebook_import = stage.get("notebook_import", {})
    if not isinstance(notebook_import, Mapping) or not notebook_import:
        return []

    lines = ["", "Notebook import metadata:"]
    source_notebook = str(notebook_import.get("source_notebook", "") or "")
    cell_id = str(notebook_import.get("cell_id", "") or "")
    source_cell_index = notebook_import.get("source_cell_index")
    if source_notebook:
        lines.append(f"- Source notebook: `{source_notebook}`")
    if cell_id or source_cell_index not in (None, ""):
        cell_bits = []
        if cell_id:
            cell_bits.append(f"id `{cell_id}`")
        if source_cell_index not in (None, ""):
            cell_bits.append(f"index `{source_cell_index}`")
        lines.append("- Source cell: " + ", ".join(cell_bits))
    env_hints = _metadata_string_list(notebook_import.get("env_hints", []))
    if env_hints:
        lines.append("- Environment hints: " + ", ".join(f"`{hint}`" for hint in env_hints))
    artifacts = _metadata_string_list(notebook_import.get("artifact_references", []))
    if artifacts:
        lines.append("- Artifact references: " + ", ".join(f"`{artifact}`" for artifact in artifacts))
    return lines


def _agilab_notebook_payload(
    agilab_payload: dict[str, Any] | None = None,
    *,
    export_mode: str = "plain",
) -> dict[str, Any]:
    payload = dict(agilab_payload or {})
    payload.setdefault("schema", NOTEBOOK_EXPORT_SCHEMA)
    payload.setdefault("version", NOTEBOOK_EXPORT_SCHEMA_VERSION)
    payload.setdefault("export_mode", export_mode)
    return payload


def _notebook_metadata(
    agilab_payload: dict[str, Any] | None = None,
    *,
    export_mode: str = "plain",
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3",
        },
        "language_info": {
            "name": "python",
            "version": sys.version.split()[0],
        },
        "pycharm": {
            "stem_cell": {
                "cell_type": "raw",
                "metadata": {"collapsed": False},
                "source": [],
            }
        },
    }
    metadata["agilab"] = _agilab_notebook_payload(agilab_payload, export_mode=export_mode)
    return metadata


def build_notebook_document(
    toml_data: Dict[str, Any],
    toml_path: str | Path,
    *,
    export_context: NotebookExportContext | None = None,
) -> Dict[str, Any]:
    if export_context is None:
        return _build_plain_notebook(toml_data)

    module_key = _export_module_key(toml_data, export_context)
    module_automation = _module_automation_preferences(toml_data, module_key)
    selected_profile = _normalized_automation_profile(
        module_automation.get("profile", "balanced")
    )
    stage_records = _stage_records(
        toml_data,
        module_key=module_key,
        profile=selected_profile,
    )
    payload = {
        "schema": NOTEBOOK_EXPORT_SCHEMA,
        "version": NOTEBOOK_EXPORT_SCHEMA_VERSION,
        "project_name": export_context.project_name,
        "module_path": export_context.module_path,
        "artifact_dir": export_context.artifact_dir,
        "controller_python": sys.executable,
        "pycharm_mirror_path": pycharm_notebook_mirror_path(toml_path, export_context=export_context),
        "active_app": export_context.active_app,
        "app_settings_file": export_context.app_settings_file,
        "pages_root": export_context.pages_root,
        "repo_root": export_context.repo_root,
        "export_mode": export_context.export_mode,
        "allow_workspace_sibling_apps": export_context.allow_workspace_sibling_apps,
        "related_pages": [asdict(page) for page in export_context.related_pages],
        "view_sync": dict(export_context.view_sync or {}),
        "module_key": module_key,
        "module_automation": module_automation,
        "stages": stage_records,
        "stages_file": str(Path(toml_path)),
    }

    cells: list[dict[str, Any]] = [
        _markdown_cell(
            "\n".join(
                [
                    f"# AGILAB Workflow Export: {export_context.project_name}",
                    "",
                    "This notebook preserves the AGILAB workflow as a **supervisor notebook**.",
                    "",
                    f"- Module: `{export_context.module_path}`",
                    f"- Artifact directory: `{export_context.artifact_dir}`",
                    f"- Export mode: `{export_context.export_mode}`",
                    "- First run `validate_agilab_export()` to check local paths before executing workflow code.",
                    "- Use `run_agilab_stage(i)` or `run_agilab_pipeline()` to execute workflow stages in their recorded runtime.",
                    "- Disabled/skipped stages and output-skip rules remain enforced by the exported runner helpers.",
                    "- The selected automation profile is applied; module max_workers is preserved for re-import, while notebook pipeline execution stays sequential.",
                    "- ID-less stages can be re-imported only while the stage at the recorded module/index still matches its export fingerprint. Notebook source edits are accepted; if the AGILAB target changed, refresh the export or add an explicit stage ID.",
                    "- The code cells below stay readable/editable, but they do not replace the recorded per-stage environment.",
                ]
            ),
            cell_id="agilab-export-intro",
        ),
        _code_cell(_helper_cell(payload), cell_id="agilab-export-helper"),
        _code_cell(_validation_cell(), cell_id="agilab-export-validate"),
        _code_cell(_handoff_cell(), cell_id="agilab-export-handoff"),
    ]

    for stage in stage_records:
        cells.append(
            _markdown_cell(
                "\n".join(
                    [
                        f"## Stage {stage['index']}: {stage.get('description') or '(no description)'}",
                        "",
                        f"- Module key: `{stage.get('module')}`",
                        f"- Stage ID: `{stage.get('stage_id')}`",
                        f"- Effective profile stage ID: `{stage.get('effective_stage_id')}`",
                        f"- Question: `{stage.get('question') or ''}`",
                        f"- Runtime: `{stage.get('runtime') or 'runpy'}`",
                        f"- Environment root: `{stage.get('env') or '(current kernel / controller default)'}`",
                        (
                            "- Dependencies: "
                            + ", ".join(
                                f"`{dependency}`"
                                for dependency in stage.get("effective_depends_on", [])
                            )
                            if stage.get("effective_depends_on")
                            else "- Dependencies: `(none)`"
                        ),
                        *_stage_notebook_import_context_lines(stage),
                        "",
                        "- Edit the next cell if you want to override the saved stage source.",
                        "- The runner cell below it replays the stage with its recorded runtime. Running the whole notebook executes those runner cells too.",
                    ]
                ),
                cell_id=_cell_id("stage", f"{int(stage['index']):03d}", "context"),
            )
        )
        cells.append(
            _code_cell(
                _stage_source_cell(stage),
                metadata=_stage_cell_metadata(stage, kind="source"),
                cell_id=_cell_id("stage", f"{int(stage['index']):03d}", "source"),
            )
        )
        cells.append(
            _code_cell(
                _stage_runner_cell(stage),
                metadata=_stage_cell_metadata(stage, kind="runner"),
                cell_id=_cell_id("stage", f"{int(stage['index']):03d}", "runner"),
            )
        )

    if export_context.related_pages:
        cells.append(
            _markdown_cell(
                "\n".join(
                    [
                        "## Related analysis pages",
                        "",
                        "These helper cells try notebook-native renderers for the pages configured under `[pages].view_module` in the app settings.",
                        "If a page does not provide an inline notebook renderer yet, the helper falls back to launching the external Streamlit dashboard over the same exported artifacts.",
                    ]
                ),
                cell_id="agilab-analysis-pages",
            )
        )
        for page in export_context.related_pages:
            cells.append(
                _markdown_cell(
                    "\n".join(
                        [
                            f"### {page.label or page.module}",
                            "",
                            *(["- " + page.description] if page.description else []),
                            *(["- Expected artifacts:"] + [f"  - `{artifact}`" for artifact in page.artifacts] if page.artifacts else []),
                            f"- Script path: `{page.script_path or '(not resolved during export)'}`",
                            *(["- Inline renderer: `" + page.inline_renderer + "`"] if page.inline_renderer else []),
                            *(["- " + page.launch_note] if page.launch_note else []),
                            "- Run the next cell to render notebook-native output when available, otherwise it launches the page and prints the exact command.",
                        ]
                    ),
                    cell_id=_cell_id("analysis", page.module, "context"),
                )
            )
            cells.append(_code_cell(_analysis_cell(page), cell_id=_cell_id("analysis", page.module, "render")))

    return {
        "cells": cells,
        "metadata": _notebook_metadata(payload, export_mode=export_context.export_mode),
        "nbformat": 4,
        "nbformat_minor": 5,
    }
