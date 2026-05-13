from __future__ import annotations

import json
import os
import sys
import textwrap
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Sequence

import tomllib

from .page_bundle_registry import discover_page_bundle


DEFAULT_NOTEBOOK_EXPORT_MODE = "supervisor"
NOTEBOOK_EXPORT_SCHEMA = "agilab.notebook_export.v1"
NOTEBOOK_EXPORT_SCHEMA_VERSION = 1
PYCHARM_NOTEBOOK_MIRROR_ROOT = "exported_notebooks"
ALLOW_WORKSPACE_SIBLING_APPS_ENV = "AGILAB_NOTEBOOK_EXPORT_ALLOW_WORKSPACE_SIBLINGS"
APPS_REPOSITORY_ENV_KEYS = ("APPS_REPOSITORY",)

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

    repo_root = None
    try:
        if current_file.parents[1].name == "exported_notebooks":
            repo_root = current_file.parents[2]
    except Exception:
        repo_root = None

    quoted_notebook = shlex.quote(str(notebook_path))
    if repo_root is None:
        prefix = "uv run"
    else:
        prefix = f"uv --project {shlex.quote(str(repo_root))} run"

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
        local_root = Path(current_file).resolve().parents[2]
    except (OSError, RuntimeError, TypeError, ValueError, IndexError):
        local_root = None
    if local_root is not None and local_root not in candidates:
        candidates.append(local_root)
    return tuple(candidates)


def _looks_like_source_checkout(root: Path) -> bool:
    return (root / "src" / "agilab").exists() and ((root / ".git").exists() or (root / ".idea").exists())


def _truthy_env(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


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

    _add(text)
    if text.endswith("_project"):
        _add(text.removesuffix("_project"))
    else:
        _add(f"{text}_project")
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
        with open(settings_path, "rb") as stream:
            payload = tomllib.load(stream)
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
    related_pages = _load_related_pages_from_settings(settings_file) or _load_related_pages_from_settings(source_settings) or manifest_order
    pages_root = _normalize_path(getattr(env, "AGILAB_PAGES_ABS", ""))
    related_page_records = tuple(
        RelatedPageExport(
            module=page,
            label=str(page_manifest.get(page, {}).get("label", "") or ""),
            description=str(page_manifest.get(page, {}).get("description", "") or ""),
            artifacts=tuple(str(item) for item in page_manifest.get(page, {}).get("artifacts", ())),
            launch_note=str(page_manifest.get(page, {}).get("launch_note", "") or ""),
            script_path=script_path,
            inline_renderer=_discover_page_inline_renderer(page_manifest, page, script_path=script_path),
        )
        for page in related_pages
        for script_path in (_discover_page_script(pages_root, page),)
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


def _stage_records(toml_data: Dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    global_index = 0
    for module, stages in toml_data.items():
        if module == "__meta__" or not isinstance(stages, list):
            continue
        for module_index, raw_stage in enumerate(stages):
            if isinstance(raw_stage, dict):
                code_text = str(raw_stage.get("C", "") or "")
                description = str(raw_stage.get("D", "") or "")
                question = str(raw_stage.get("Q", "") or "")
                model = str(raw_stage.get("M", "") or "")
                runtime = str(raw_stage.get("R", "") or "")
                env_root = _normalize_path(raw_stage.get("E", ""))
            elif isinstance(raw_stage, str):
                code_text = raw_stage
                description = ""
                question = ""
                model = ""
                runtime = ""
                env_root = ""
            else:
                continue
            if not code_text:
                continue
            records.append(
                {
                    "index": global_index,
                    "module": str(module),
                    "module_index": module_index,
                    "description": description,
                    "question": question,
                    "model": model,
                    "runtime": runtime,
                    "env": env_root,
                    "code": code_text,
                }
            )
            global_index += 1
    return records


def _markdown_cell(text: str) -> dict[str, Any]:
    return {
        "cell_type": "markdown",
        "metadata": {},
        "source": [line if line.endswith("\n") else line + "\n" for line in text.splitlines()],
    }


def _code_cell(code: str) -> dict[str, Any]:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": code.splitlines(keepends=True),
    }


def _helper_cell(payload: dict[str, Any]) -> str:
    payload_literal = repr(json.dumps(payload, ensure_ascii=False))
    return textwrap.dedent(
        f"""
        import json
        import ast
        import importlib
        import importlib.util
        import os
        import shlex
        import socket
        import subprocess
        import sys
        import tempfile
        import tomllib
        import traceback
        from pathlib import Path

        AGILAB_NOTEBOOK_EXPORT = json.loads({payload_literal})


        def _normalized_path(value):
            if not value:
                return ""
            try:
                return str(Path(value).expanduser())
            except Exception:
                return str(value)


        def _is_valid_active_app_root(path_value):
            if not path_value:
                return False
            try:
                root = Path(path_value).expanduser()
            except Exception:
                return False
            try:
                return root.is_dir() and (
                    (root / "pyproject.toml").is_file() or
                    (root / "src" / "app_settings.toml").is_file()
                )
            except OSError:
                return False


        def _active_app_matches_project(path_value, project_name):
            if not project_name:
                return True
            if not path_value:
                return False
            try:
                return Path(path_value).expanduser().name in _project_name_candidates(project_name)
            except Exception:
                return False


        def _project_name_candidates(project_name):
            text = str(project_name or "").strip()
            if not text:
                return []
            candidates = []

            def add(candidate):
                candidate = str(candidate or "").strip()
                if candidate and candidate not in candidates:
                    candidates.append(candidate)

            add(text)
            if text.endswith("_project"):
                add(text.removesuffix("_project"))
            else:
                add(f"{{text}}_project")
            return candidates


        def _truthy_env(name):
            return str(os.environ.get(name) or "").strip().lower() in {{"1", "true", "yes", "y", "on"}}


        def _allow_workspace_sibling_apps():
            return bool(AGILAB_NOTEBOOK_EXPORT.get("allow_workspace_sibling_apps")) or _truthy_env(
                "AGILAB_NOTEBOOK_EXPORT_ALLOW_WORKSPACE_SIBLINGS"
            )


        def _looks_like_source_checkout(path_value):
            try:
                root = Path(path_value).expanduser()
            except Exception:
                return False
            try:
                return (root / "src" / "agilab").exists() and ((root / ".git").exists() or (root / ".idea").exists())
            except OSError:
                return False


        def _candidate_checkout_roots():
            seen = set()

            def emit(seed):
                if not seed:
                    return
                try:
                    path = Path(_normalized_path(seed)).expanduser()
                except Exception:
                    return
                for candidate in (path, *path.parents):
                    candidate_text = _normalized_path(candidate)
                    if not candidate_text or candidate_text in seen:
                        continue
                    if _looks_like_source_checkout(candidate):
                        seen.add(candidate_text)
                        yield candidate

            yield from emit(AGILAB_NOTEBOOK_EXPORT.get("repo_root"))
            yield from emit(AGILAB_NOTEBOOK_EXPORT.get("pycharm_mirror_path"))
            yield from emit(AGILAB_NOTEBOOK_EXPORT.get("pages_root"))


        def _candidate_apps_directories():
            seen = set()

            def emit(candidate):
                if not candidate:
                    return
                candidate_text = _normalized_path(candidate)
                if not candidate_text or candidate_text in seen:
                    return
                try:
                    path = Path(candidate_text)
                except Exception:
                    return
                if not path.exists():
                    return
                seen.add(candidate_text)
                yield path

            for repo_root in _candidate_checkout_roots():
                yield from emit(repo_root / "src" / "agilab" / "apps")
                yield from emit(repo_root / "apps")

                if _allow_workspace_sibling_apps():
                    workspace_root = repo_root.parent
                    try:
                        siblings = sorted(
                            candidate
                            for candidate in workspace_root.iterdir()
                            if candidate.is_dir() and candidate != repo_root
                        )
                    except OSError:
                        siblings = []
                    for sibling in siblings:
                        yield from emit(sibling / "apps")
                        yield from emit(sibling / "src" / "agilab" / "apps")

            for env_key in ("APPS_REPOSITORY",):
                apps_repository = str(os.environ.get(env_key) or "").strip()
                if apps_repository:
                    repo_path = Path(apps_repository).expanduser()
                    yield from emit(repo_path)
                    yield from emit(repo_path / "apps")
                    yield from emit(repo_path / "src" / "agilab" / "apps")


        def resolve_active_app_root(app_name=None):
            active_app = _normalized_path(AGILAB_NOTEBOOK_EXPORT.get("active_app"))
            project_name = str(app_name or AGILAB_NOTEBOOK_EXPORT.get("project_name") or "").strip()
            if _is_valid_active_app_root(active_app) and _active_app_matches_project(active_app, project_name):
                AGILAB_NOTEBOOK_EXPORT["active_app"] = active_app
                return active_app

            if project_name:
                for apps_dir in _candidate_apps_directories():
                    for project_candidate in _project_name_candidates(project_name):
                        for candidate in (apps_dir / project_candidate, apps_dir / "builtin" / project_candidate):
                            candidate_text = _normalized_path(candidate)
                            if _is_valid_active_app_root(candidate_text):
                                AGILAB_NOTEBOOK_EXPORT["active_app"] = candidate_text
                                return candidate_text

            raise ValueError(
                "Unable to resolve a valid AGILAB app root for exported notebook "
                f"project={{project_name or app_name or '<unknown>'}}. "
                f"Current active_app={{active_app or '<missing>'}}. "
                "Re-export the notebook from AGILAB with the correct project selected, "
                "or set APPS_REPOSITORY so the project root can be discovered."
            )


        def _load_app_settings_args(active_app):
            settings_candidates = []

            configured = _normalized_path(AGILAB_NOTEBOOK_EXPORT.get("app_settings_file"))
            if configured:
                settings_candidates.append(Path(configured))

            try:
                active_root = Path(active_app).expanduser()
            except Exception:
                active_root = None
            if active_root is not None:
                settings_candidates.append(active_root / "src" / "app_settings.toml")
                settings_candidates.append(active_root / "app_settings.toml")

            for candidate in settings_candidates:
                try:
                    if not candidate.exists():
                        continue
                    with candidate.open("rb") as stream:
                        payload = tomllib.load(stream)
                except (OSError, TypeError, ValueError, tomllib.TOMLDecodeError):
                    continue
                args_payload = payload.get("args")
                if isinstance(args_payload, dict):
                    return json.loads(json.dumps(args_payload, ensure_ascii=False))
            return {{}}


        def _merge_shorthand_run_args(assignments, active_app):
            flat_assignments = dict(assignments)
            run_args = _load_app_settings_args(active_app)
            trainer_name = str(flat_assignments.pop("trainer", "") or "").strip()

            if not run_args:
                return dict(assignments)

            if "args" in run_args:
                raise ValueError("Legacy run settings key 'args' is no longer supported; use 'stages'.")
            nested_trainers = run_args.get("stages")
            if trainer_name and isinstance(nested_trainers, list):
                selected = None
                for item in nested_trainers:
                    if isinstance(item, dict) and str(item.get("name", "") or "").strip() == trainer_name:
                        selected = json.loads(json.dumps(item, ensure_ascii=False))
                        break
                if selected is None:
                    selected = {{"name": trainer_name, "args": {{}}}}
                selected_args = selected.get("args")
                if not isinstance(selected_args, dict):
                    selected_args = {{}}

                for key, value in flat_assignments.items():
                    if key in run_args and key != "stages":
                        run_args[key] = value
                    else:
                        selected_args[key] = value

                selected["args"] = selected_args
                run_args["stages"] = [selected]
                return run_args

            for key, value in flat_assignments.items():
                run_args[key] = value
            return run_args


        def show_agilab_export_summary():
            related = [page.get("module", "") for page in AGILAB_NOTEBOOK_EXPORT.get("related_pages", [])]
            summary = {{
                "project_name": AGILAB_NOTEBOOK_EXPORT.get("project_name"),
                "module_path": AGILAB_NOTEBOOK_EXPORT.get("module_path"),
                "artifact_dir": AGILAB_NOTEBOOK_EXPORT.get("artifact_dir"),
                "active_app": AGILAB_NOTEBOOK_EXPORT.get("active_app"),
                "export_mode": AGILAB_NOTEBOOK_EXPORT.get("export_mode"),
                "stages": len(AGILAB_NOTEBOOK_EXPORT.get("stages", [])),
                "related_pages": related,
            }}
            print(json.dumps(summary, indent=2))
            return summary


        def _path_exists(path_value):
            if not path_value:
                return False
            try:
                return Path(path_value).expanduser().exists()
            except Exception:
                return False


        def _inline_renderer_target_exists(target):
            target_text = str(target or "").strip()
            if not target_text:
                return False
            module_target, _, _ = target_text.partition(":")
            module_target = module_target.strip()
            if not module_target:
                return False
            try:
                path_target = Path(module_target).expanduser()
            except Exception:
                return True
            if path_target.suffix == ".py" or "/" in module_target or "\\\\" in module_target:
                return path_target.exists()
            return True


        def _resolve_pages_root():
            configured = _normalized_path(AGILAB_NOTEBOOK_EXPORT.get("pages_root"))
            if configured and _path_exists(configured):
                return configured

            try:
                from agi_env import AgiEnv

                env = AgiEnv()
                pages_root = _normalized_path(getattr(env, "AGILAB_PAGES_ABS", ""))
                if pages_root and _path_exists(pages_root):
                    AGILAB_NOTEBOOK_EXPORT["pages_root"] = pages_root
                    return pages_root
            except Exception:
                pass

            try:
                import agi_pages

                pages_root = _normalized_path(agi_pages.bundles_root())
                if pages_root and _path_exists(pages_root):
                    AGILAB_NOTEBOOK_EXPORT["pages_root"] = pages_root
                    return pages_root
            except Exception:
                pass

            return configured


        def _bundle_to_record(bundle):
            if bundle is None:
                return {{}}
            if hasattr(bundle, "as_dict"):
                try:
                    raw_record = bundle.as_dict()
                except Exception:
                    raw_record = {{}}
            elif isinstance(bundle, dict):
                raw_record = bundle
            else:
                raw_record = {{
                    "name": getattr(bundle, "name", ""),
                    "module": getattr(bundle, "module", "") or getattr(bundle, "name", ""),
                    "root_path": getattr(bundle, "root_path", ""),
                    "script_path": getattr(bundle, "script_path", ""),
                    "inline_renderer": getattr(bundle, "inline_renderer", ""),
                }}

            record = {{
                "name": str(raw_record.get("name", "") or raw_record.get("module", "") or ""),
                "module": str(raw_record.get("module", "") or raw_record.get("name", "") or ""),
                "root_path": _normalized_path(raw_record.get("root_path", "")),
                "script_path": _normalized_path(raw_record.get("script_path", "")),
                "inline_renderer": str(raw_record.get("inline_renderer", "") or ""),
            }}
            return record if record.get("script_path") else {{}}


        def _resolve_agi_pages_bundle(page, pages_root=None):
            try:
                import agi_pages
            except Exception:
                return {{}}

            resolver = getattr(agi_pages, "resolve_bundle", None)
            if callable(resolver):
                try:
                    bundle = resolver(page, pages_root=pages_root or None)
                except TypeError:
                    try:
                        bundle = resolver(page)
                    except Exception:
                        bundle = None
                except Exception:
                    bundle = None
                record = _bundle_to_record(bundle)
                if record:
                    return record

            script_resolver = getattr(agi_pages, "script_path", None)
            if not callable(script_resolver):
                return {{}}
            try:
                script = script_resolver(page, pages_root=pages_root or None)
            except TypeError:
                try:
                    script = script_resolver(page)
                except Exception:
                    script = ""
            except Exception:
                script = ""
            if not script:
                return {{}}
            inline_renderer = ""
            inline_resolver = getattr(agi_pages, "inline_renderer_target", None)
            if callable(inline_resolver):
                try:
                    inline_renderer = str(inline_resolver(page, pages_root=pages_root or None) or "")
                except TypeError:
                    try:
                        inline_renderer = str(inline_resolver(page) or "")
                    except Exception:
                        inline_renderer = ""
                except Exception:
                    inline_renderer = ""
            return {{
                "name": str(page),
                "module": str(page),
                "root_path": "",
                "script_path": _normalized_path(script),
                "inline_renderer": inline_renderer,
            }}


        def _inline_renderer_target_for_script(script):
            if not script:
                return ""
            try:
                candidate = Path(script).expanduser().resolve().with_name("notebook_inline.py")
            except Exception:
                return ""
            if not candidate.exists():
                return ""
            return f"{{candidate}}:render_inline"


        def _resolve_page_bundle_from_root(page, pages_root):
            root_text = _normalized_path(pages_root)
            page_name = str(page or "").strip()
            if not root_text or not page_name:
                return {{}}
            try:
                root = Path(root_text).expanduser()
            except Exception:
                return {{}}
            direct_file = root / f"{{page_name}}.py"
            if direct_file.exists() and direct_file.is_file():
                script = direct_file.resolve()
                return {{
                    "name": page_name,
                    "module": page_name,
                    "root_path": str(root.resolve()),
                    "script_path": str(script),
                    "inline_renderer": _inline_renderer_target_for_script(script),
                }}
            bundle_dir = root / page_name
            if not bundle_dir.exists() or not bundle_dir.is_dir():
                return {{}}
            candidates = []
            for pattern_root in (bundle_dir, bundle_dir / "src" / page_name):
                candidates.extend(
                    [
                        pattern_root / f"{{page_name}}.py",
                        pattern_root / "main.py",
                        pattern_root / "app.py",
                    ]
                )
            script = None
            for candidate in candidates:
                if candidate.exists() and candidate.is_file():
                    script = candidate.resolve()
                    break
            if script is None:
                fallback = sorted((bundle_dir / "src").glob("*/view_*.py"))
                if fallback:
                    script = fallback[0].resolve()
            if script is None:
                return {{}}
            return {{
                "name": page_name,
                "module": page_name,
                "root_path": str(bundle_dir.resolve()),
                "script_path": str(script),
                "inline_renderer": _inline_renderer_target_for_script(script),
            }}


        def _resolve_page_bundle_record(page):
            pages_root = _resolve_pages_root()
            record = _resolve_agi_pages_bundle(page, pages_root=pages_root)
            if record:
                return record
            if pages_root:
                record = _resolve_page_bundle_from_root(page, pages_root)
                if record:
                    return record
            return _resolve_agi_pages_bundle(page)


        def _enrich_page_record(record):
            resolved = dict(record)
            page = str(resolved.get("module") or resolved.get("name") or "").strip()
            if not page:
                return resolved
            script_path = _normalized_path(resolved.get("script_path"))
            inline_renderer = str(resolved.get("inline_renderer") or "").strip()
            script_missing = not script_path or not _path_exists(script_path)
            inline_missing = bool(inline_renderer) and not _inline_renderer_target_exists(inline_renderer)
            if script_missing or not inline_renderer or inline_missing:
                provider_record = _resolve_page_bundle_record(page)
                if provider_record:
                    if script_missing and provider_record.get("script_path"):
                        resolved["script_path"] = provider_record["script_path"]
                    if (not inline_renderer or inline_missing) and provider_record.get("inline_renderer"):
                        resolved["inline_renderer"] = provider_record["inline_renderer"]
            return resolved


        def _page_record(page):
            for record in AGILAB_NOTEBOOK_EXPORT.get("related_pages", []):
                if record.get("module") == page:
                    return _enrich_page_record(record)
            raise KeyError(f"Unknown analysis page: {{page}}")


        def _display_inline_result(result):
            if result is None:
                return None
            try:
                from IPython.display import Markdown, display
            except Exception:
                return result
            if isinstance(result, str):
                display(Markdown(result))
                return result
            if isinstance(result, (list, tuple)):
                for item in result:
                    _display_inline_result(item)
                return result
            display(result)
            return result


        def _load_inline_renderer(target):
            target_text = str(target or "").strip()
            if not target_text:
                raise ValueError("Inline renderer target is empty.")
            module_target, _, attr_name = target_text.partition(":")
            module_target = module_target.strip()
            attr_name = attr_name or "render_inline"
            path_target = Path(module_target).expanduser()
            if path_target.suffix == ".py" or path_target.exists():
                module_path = path_target.resolve()
                synthetic_name = f"agilab_notebook_inline_{{module_path.stem}}_{{abs(hash(str(module_path)))}}"
                spec = importlib.util.spec_from_file_location(synthetic_name, module_path)
                if spec is None or spec.loader is None:
                    raise ModuleNotFoundError(f"Unable to load inline renderer module from {{module_path}}")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            else:
                module = importlib.import_module(module_target)
            renderer = getattr(module, attr_name)
            if not callable(renderer):
                raise TypeError(f"Inline renderer {{target_text!r}} is not callable.")
            return renderer


        def _resolve_stage_python(stage):
            controller_python = AGILAB_NOTEBOOK_EXPORT.get("controller_python") or sys.executable
            try:
                from agilab.pipeline_runtime import python_for_stage
            except Exception:
                return controller_python
            try:
                resolved = python_for_stage(
                    stage.get("env") or None,
                    engine=stage.get("runtime") or None,
                    code=stage.get("code") or "",
                    sys_executable=controller_python,
                )
            except TypeError:
                resolved = python_for_stage(
                    stage.get("env") or None,
                    engine=stage.get("runtime") or None,
                    code=stage.get("code") or "",
                )
            return str(resolved)


        def _stage_assignments(code_text):
            try:
                tree = ast.parse(code_text or "")
            except SyntaxError:
                return {{}}
            assignments = {{}}
            for node in tree.body:
                if not isinstance(node, ast.Assign) or len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                    return {{}}
                try:
                    value = ast.literal_eval(node.value)
                except Exception:
                    return {{}}
                assignments[node.targets[0].id] = value
            return assignments


        def _stage_shorthand_method(stage, code_text):
            runtime = str(stage.get("runtime") or "").strip().lower()
            if runtime.startswith("agi."):
                return runtime.split(".", 1)[1]
            lowered = str(code_text or "").lower()
            if "agi.install(" in lowered:
                return "install"
            if "agi.run(" in lowered:
                return "run"
            if "APP" in _stage_assignments(code_text):
                return "run"
            return ""


        def _build_shorthand_agi_script(stage, code_text):
            assignments = _stage_assignments(code_text)
            app_name = str(assignments.pop("APP", "") or "").strip()
            if not app_name:
                return None
            method = _stage_shorthand_method(stage, code_text)
            if method not in {{"run", "install"}}:
                return None
            active_app = resolve_active_app_root(app_name)
            explicit_mode = assignments.pop("mode", None) if method == "run" else None
            run_args = _merge_shorthand_run_args(assignments, active_app)
            run_mode = 0
            if method == "run":
                if explicit_mode not in (None, ""):
                    run_mode = explicit_mode
                else:
                    inherited_mode = run_args.pop("mode", None)
                    if inherited_mode not in (None, ""):
                        run_mode = inherited_mode
            run_params = dict(run_args)
            run_stages_payload = run_params.pop("stages", []) or []
            if "args" in run_params:
                raise ValueError("Legacy run settings key 'args' is no longer supported; use 'stages'.")
            run_data_in = run_params.pop("data_in", None)
            run_data_out = run_params.pop("data_out", None)
            run_reset_target = run_params.pop("reset_target", None)
            run_args_literal = json.dumps(
                run_args,
                ensure_ascii=False,
                sort_keys=True,
            )
            run_params_literal = json.dumps(
                run_params,
                ensure_ascii=False,
                sort_keys=True,
            )
            run_stages_literal = json.dumps(
                run_stages_payload,
                ensure_ascii=False,
                sort_keys=True,
            )
            prelude = (
                "import asyncio\\n"
                "import json\\n"
                "from agi_cluster.agi_distributor import AGI, RunRequest, StageRequest\\n"
                "from agi_env import AgiEnv\\n\\n"
                f"ACTIVE_APP = {{active_app!r}}\\n"
                f"RUN_ARGS = json.loads({{run_args_literal!r}})\\n"
                f"RUN_PARAMS = json.loads({{run_params_literal!r}})\\n"
                f"RUN_STAGES_PAYLOAD = json.loads({{run_stages_literal!r}})\\n"
                f"RUN_DATA_IN = json.loads({{json.dumps(run_data_in, ensure_ascii=False)!r}})\\n"
                f"RUN_DATA_OUT = json.loads({{json.dumps(run_data_out, ensure_ascii=False)!r}})\\n"
                f"RUN_RESET_TARGET = json.loads({{json.dumps(run_reset_target, ensure_ascii=False)!r}})\\n"
            )
            if method == "run":
                mode_literal = json.dumps(run_mode, ensure_ascii=False)
                prelude += f"RUN_MODE = json.loads({{mode_literal!r}})\\n"
            prelude += "\\n"
            if method == "run":
                invoke = (
                    "    run_stages = [\\n"
                    "        StageRequest(name=stage['name'], args=stage.get('args') or {{}})\\n"
                    "        for stage in RUN_STAGES_PAYLOAD\\n"
                    "    ]\\n"
                    "    request = RunRequest(\\n"
                    "        params=RUN_PARAMS,\\n"
                    "        stages=run_stages,\\n"
                    "        data_in=RUN_DATA_IN,\\n"
                    "        data_out=RUN_DATA_OUT,\\n"
                    "        reset_target=RUN_RESET_TARGET,\\n"
                    "        mode=RUN_MODE,\\n"
                    "    )\\n"
                    "    res = await AGI.run(app_env, request=request)\\n"
                )
            else:
                invoke = "    res = await AGI.install(app_env, **RUN_ARGS)\\n"
            return (
                prelude
                + "async def main():\\n"
                + "    app_env = AgiEnv(active_app=ACTIVE_APP, verbose=1)\\n"
                + invoke
                + "    print(res)\\n"
                + "    return res\\n\\n"
                + 'if __name__ == "__main__":\\n'
                + "    asyncio.run(main())\\n"
            )


        def _stage_script_text(stage, code_text):
            shorthand = _build_shorthand_agi_script(stage, code_text)
            if shorthand:
                return shorthand
            return code_text or ""


        def run_agilab_stage(stage_index, *, check=True, capture_output=True, code_override=None):
            stages = AGILAB_NOTEBOOK_EXPORT.get("stages", [])
            stage = stages[stage_index]
            workdir = Path(AGILAB_NOTEBOOK_EXPORT.get("artifact_dir") or ".").expanduser()
            workdir.mkdir(parents=True, exist_ok=True)
            code_text = code_override if code_override is not None else (stage.get("code") or "")
            script_text = _stage_script_text(stage, code_text)
            stage_for_python = dict(stage)
            stage_for_python["code"] = code_text
            python_exe = _resolve_stage_python(stage_for_python)
            with tempfile.TemporaryDirectory(prefix="agilab_notebook_stage_") as tmpdir:
                script_path = Path(tmpdir) / f"stage_{{stage_index:03d}}.py"
                script_path.write_text(script_text, encoding="utf-8")
                result = subprocess.run(
                    [python_exe, str(script_path)],
                    cwd=str(workdir),
                    text=True,
                    capture_output=capture_output,
                    check=False,
                )
            if capture_output and result.stdout:
                print(result.stdout, end="")
            if capture_output and result.stderr:
                print(result.stderr, file=sys.stderr, end="")
            if check:
                result.check_returncode()
            return result

        def run_agilab_pipeline(stage_indices=None, *, check=True):
            indices = list(stage_indices) if stage_indices is not None else list(range(len(AGILAB_NOTEBOOK_EXPORT.get("stages", []))))
            results = []
            for stage_index in indices:
                print(f"== Running AGILAB stage {{stage_index}} ==")
                results.append(run_agilab_stage(stage_index, check=check))
            return results


        def analysis_launch_command(page, *, port=None):
            argv = analysis_launch_argv(page, port=port)
            if isinstance(argv, str):
                return argv
            return shlex.join(argv)


        def analysis_launch_argv(page, *, port=None):
            record = _page_record(page)
            active_app = resolve_active_app_root()
            script_path = record.get("script_path") or ""
            if not script_path or not _path_exists(script_path):
                return f"# Missing page script for analysis page {{page}}"
            cmd = [
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "streamlit",
                "run",
            ]
            if port is not None:
                cmd.extend(["--server.port", str(port)])
            cmd.extend([script_path, "--", "--active-app", active_app])
            return cmd


        def _find_free_streamlit_port():
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(("127.0.0.1", 0))
                return sock.getsockname()[1]


        def launch_analysis_page(page, *, port=None, wait=False):
            resolved_port = port if port is not None else _find_free_streamlit_port()
            argv = analysis_launch_argv(page, port=resolved_port)
            print(analysis_launch_command(page, port=resolved_port))
            if isinstance(argv, str) and argv.startswith("#"):
                return argv
            if wait:
                return subprocess.run(argv, check=False)
            return subprocess.Popen(argv)


        def render_analysis_page(page, *, fallback_launch=True, port=None):
            record = _page_record(page)
            target = str(record.get("inline_renderer") or "").strip()
            if target:
                try:
                    renderer = _load_inline_renderer(target)
                    result = renderer(
                        page=page,
                        record=record,
                        export_payload=AGILAB_NOTEBOOK_EXPORT,
                    )
                    return _display_inline_result(result)
                except Exception as exc:
                    print(f"Inline analysis failed for {{page}}: {{exc}}", file=sys.stderr)
                    traceback.print_exc()
                    if not fallback_launch:
                        raise
            if fallback_launch:
                return launch_analysis_page(page, port=port)
            return None


        show_agilab_export_summary()
        """
    ).strip() + "\n"


def _analysis_cell(page: RelatedPageExport) -> str:
    return textwrap.dedent(
        f"""
        page = {page.module!r}
        render_analysis_page(page)
        """
    ).strip() + "\n"


def _stage_code_variable_name(stage: dict[str, Any]) -> str:
    return f"STAGE_{int(stage['index']):03d}_CODE"


def _stage_source_cell(stage: dict[str, Any]) -> str:
    variable_name = _stage_code_variable_name(stage)
    code_text = str(stage.get("code", "") or "").replace('"""', '\\"""')
    return f'{variable_name} = """{code_text}"""\nprint({variable_name})\n'


def _stage_runner_cell(stage: dict[str, Any]) -> str:
    variable_name = _stage_code_variable_name(stage)
    return textwrap.dedent(
        f"""
        run_agilab_stage({int(stage['index'])}, code_override={variable_name})
        """
    ).strip() + "\n"


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

    stage_records = _stage_records(toml_data)
    payload = {
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
                    "- Use `run_agilab_stage(i)` or `run_agilab_pipeline()` to execute workflow stages in their recorded runtime.",
                    "- The code cells below stay readable/editable, but they do not replace the recorded per-stage environment.",
                ]
            )
        ),
        _code_cell(_helper_cell(payload)),
    ]

    for stage in stage_records:
        cells.append(
            _markdown_cell(
                "\n".join(
                    [
                        f"## Stage {stage['index']}: {stage.get('description') or '(no description)'}",
                        "",
                        f"- Module key: `{stage.get('module')}`",
                        f"- Question: `{stage.get('question') or ''}`",
                        f"- Runtime: `{stage.get('runtime') or 'runpy'}`",
                        f"- Environment root: `{stage.get('env') or '(current kernel / controller default)'}`",
                        "",
                        f"- Edit the next cell if you want to override the saved stage source.",
                        f"- The runner cell below it replays the stage with its recorded runtime. Running the whole notebook executes those runner cells too.",
                    ]
                )
            )
        )
        cells.append(_code_cell(_stage_source_cell(stage)))
        cells.append(_code_cell(_stage_runner_cell(stage)))

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
                )
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
                    )
                )
            )
            cells.append(_code_cell(_analysis_cell(page)))

    return {
        "cells": cells,
        "metadata": _notebook_metadata(payload, export_mode=export_context.export_mode),
        "nbformat": 4,
        "nbformat_minor": 5,
    }
