from __future__ import annotations

import json
import sys
import textwrap
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Sequence

import tomllib


DEFAULT_NOTEBOOK_EXPORT_MODE = "supervisor"
PYCHARM_NOTEBOOK_MIRROR_ROOT = "exported_notebooks"

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


def _resolve_pycharm_repo_root(
    export_context: NotebookExportContext | None,
    *,
    current_file: str | Path = __file__,
) -> Path | None:
    for candidate in _repo_root_candidates(export_context, current_file=current_file):
        if _looks_like_source_checkout(candidate):
            return candidate
    return None


def pycharm_notebook_mirror_path(
    toml_path: str | Path,
    *,
    export_context: NotebookExportContext | None = None,
    current_file: str | Path = __file__,
) -> str:
    try:
        steps_path = Path(toml_path).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, TypeError, ValueError):
        return ""
    notebook_path = steps_path.with_suffix(".ipynb")
    repo_root = _resolve_pycharm_repo_root(export_context, current_file=current_file)
    if repo_root is None:
        return ""
    if notebook_path.is_relative_to(repo_root):
        return str(notebook_path)

    artifact_dir = ""
    if export_context and export_context.artifact_dir:
        artifact_dir = Path(_normalize_path(export_context.artifact_dir)).name
    folder_name = artifact_dir or steps_path.parent.name or steps_path.stem
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


def _discover_page_script(pages_root: str | Path | None, module_name: str) -> str:
    if not pages_root:
        return ""
    try:
        root = Path(pages_root).expanduser()
    except (OSError, RuntimeError, TypeError, ValueError):
        return ""

    candidates = (
        root / f"{module_name}.py",
        root / module_name / f"{module_name}.py",
        root / module_name / "main.py",
        root / module_name / "app.py",
        root / module_name / "src" / module_name / f"{module_name}.py",
        root / module_name / "src" / module_name / "main.py",
        root / module_name / "src" / module_name / "app.py",
    )
    for candidate in candidates:
        if candidate.exists():
            return str(candidate.resolve())
    return ""


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
        return ""
    return f"{candidate}:render_inline"


def build_notebook_export_context(
    env: Any,
    module_path: str | Path,
    steps_file: str | Path,
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

    active_app = _settings_to_app_root(source_settings) or _normalize_path(getattr(env, "active_app", ""))
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
    repo_root = ""
    read_agilab_path = getattr(env, "read_agilab_path", None)
    if callable(read_agilab_path):
        try:
            repo_root = _normalize_path(read_agilab_path())
        except (OSError, RuntimeError, TypeError, ValueError):
            repo_root = ""

    return NotebookExportContext(
        project_name=module_name,
        module_path=Path(module_path).as_posix(),
        artifact_dir=str(Path(steps_file).resolve().parent),
        active_app=active_app,
        app_settings_file=str(settings_file) if settings_file is not None else "",
        pages_root=pages_root,
        repo_root=repo_root,
        related_pages=related_page_records,
    )


def _build_plain_notebook(toml_data: Dict[str, Any]) -> Dict[str, Any]:
    notebook_data = {
        "cells": [],
        "metadata": _notebook_metadata(),
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    for module, steps in toml_data.items():
        if module == "__meta__" or not isinstance(steps, list):
            continue
        for step in steps:
            code_text = ""
            if isinstance(step, dict):
                code_text = str(step.get("C", "") or "")
            elif isinstance(step, str):
                code_text = step
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


def _step_records(toml_data: Dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    global_index = 0
    for module, steps in toml_data.items():
        if module == "__meta__" or not isinstance(steps, list):
            continue
        for module_index, raw_step in enumerate(steps):
            if isinstance(raw_step, dict):
                code_text = str(raw_step.get("C", "") or "")
                description = str(raw_step.get("D", "") or "")
                question = str(raw_step.get("Q", "") or "")
                model = str(raw_step.get("M", "") or "")
                runtime = str(raw_step.get("R", "") or "")
                env_root = _normalize_path(raw_step.get("E", ""))
            elif isinstance(raw_step, str):
                code_text = raw_step
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
        import shlex
        import socket
        import subprocess
        import sys
        import tempfile
        import traceback
        from pathlib import Path

        AGILAB_NOTEBOOK_EXPORT = json.loads({payload_literal})


        def show_agilab_export_summary():
            related = [page.get("module", "") for page in AGILAB_NOTEBOOK_EXPORT.get("related_pages", [])]
            summary = {{
                "project_name": AGILAB_NOTEBOOK_EXPORT.get("project_name"),
                "module_path": AGILAB_NOTEBOOK_EXPORT.get("module_path"),
                "artifact_dir": AGILAB_NOTEBOOK_EXPORT.get("artifact_dir"),
                "export_mode": AGILAB_NOTEBOOK_EXPORT.get("export_mode"),
                "steps": len(AGILAB_NOTEBOOK_EXPORT.get("steps", [])),
                "related_pages": related,
            }}
            print(json.dumps(summary, indent=2))
            return summary


        def _page_record(page):
            for record in AGILAB_NOTEBOOK_EXPORT.get("related_pages", []):
                if record.get("module") == page:
                    return record
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


        def _resolve_step_python(step):
            controller_python = AGILAB_NOTEBOOK_EXPORT.get("controller_python") or sys.executable
            try:
                from agilab.pipeline_runtime import python_for_step
            except Exception:
                return controller_python
            try:
                resolved = python_for_step(
                    step.get("env") or None,
                    engine=step.get("runtime") or None,
                    code=step.get("code") or "",
                    sys_executable=controller_python,
                )
            except TypeError:
                resolved = python_for_step(
                    step.get("env") or None,
                    engine=step.get("runtime") or None,
                    code=step.get("code") or "",
                )
            return str(resolved)


        def _step_assignments(code_text):
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


        def _step_shorthand_method(step, code_text):
            runtime = str(step.get("runtime") or "").strip().lower()
            if runtime.startswith("agi."):
                return runtime.split(".", 1)[1]
            lowered = str(code_text or "").lower()
            if "agi.install(" in lowered:
                return "install"
            if "agi.run(" in lowered:
                return "run"
            if "APP" in _step_assignments(code_text):
                return "run"
            return ""


        def _build_shorthand_agi_script(step, code_text):
            assignments = _step_assignments(code_text)
            app_name = str(assignments.pop("APP", "") or "").strip()
            if not app_name:
                return None
            method = _step_shorthand_method(step, code_text)
            if method not in {{"run", "install"}}:
                return None
            active_app = str(AGILAB_NOTEBOOK_EXPORT.get("active_app") or "").strip()
            apps_root = str(Path(active_app).expanduser().parent) if active_app else ""
            if not apps_root:
                return None
            run_args_literal = json.dumps(assignments, ensure_ascii=False, sort_keys=True)
            return (
                "import asyncio\\n"
                "import json\\n"
                "from agi_cluster.agi_distributor import AGI\\n"
                "from agi_env import AgiEnv\\n\\n"
                f"APPS_PATH = {{apps_root!r}}\\n"
                f"APP = {{app_name!r}}\\n"
                f"RUN_ARGS = json.loads({{run_args_literal!r}})\\n\\n"
                "async def main():\\n"
                "    app_env = AgiEnv(apps_path=APPS_PATH, app=APP, verbose=1)\\n"
                f"    res = await AGI.{{method}}(app_env, **RUN_ARGS)\\n"
                "    print(res)\\n"
                "    return res\\n\\n"
                'if __name__ == "__main__":\\n'
                "    asyncio.run(main())\\n"
            )


        def _step_script_text(step, code_text):
            shorthand = _build_shorthand_agi_script(step, code_text)
            if shorthand:
                return shorthand
            return code_text or ""


        def run_agilab_step(step_index, *, check=True, capture_output=True, code_override=None):
            steps = AGILAB_NOTEBOOK_EXPORT.get("steps", [])
            step = steps[step_index]
            workdir = Path(AGILAB_NOTEBOOK_EXPORT.get("artifact_dir") or ".").expanduser()
            workdir.mkdir(parents=True, exist_ok=True)
            code_text = code_override if code_override is not None else (step.get("code") or "")
            script_text = _step_script_text(step, code_text)
            step_for_python = dict(step)
            step_for_python["code"] = code_text
            python_exe = _resolve_step_python(step_for_python)
            with tempfile.TemporaryDirectory(prefix="agilab_notebook_step_") as tmpdir:
                script_path = Path(tmpdir) / f"step_{{step_index:03d}}.py"
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


        def run_agilab_pipeline(step_indices=None, *, check=True):
            indices = list(step_indices) if step_indices is not None else list(range(len(AGILAB_NOTEBOOK_EXPORT.get("steps", []))))
            results = []
            for step_index in indices:
                print(f"== Running AGILAB step {{step_index}} ==")
                results.append(run_agilab_step(step_index, check=check))
            return results


        def analysis_launch_command(page, *, port=None):
            record = _page_record(page)
            active_app = AGILAB_NOTEBOOK_EXPORT.get("active_app") or ""
            script_path = record.get("script_path") or ""
            if not active_app:
                return f"# Missing active_app for analysis page {{page}}"
            if not script_path:
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
            return shlex.join(cmd)


        def _find_free_streamlit_port():
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(("127.0.0.1", 0))
                return sock.getsockname()[1]


        def launch_analysis_page(page, *, port=None, wait=False):
            resolved_port = port if port is not None else _find_free_streamlit_port()
            cmd = analysis_launch_command(page, port=resolved_port)
            print(cmd)
            if cmd.startswith("#"):
                return cmd
            if wait:
                return subprocess.run(cmd, shell=True, check=False)
            return subprocess.Popen(cmd, shell=True)


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


def _step_code_variable_name(step: dict[str, Any]) -> str:
    return f"STEP_{int(step['index']):03d}_CODE"


def _step_source_cell(step: dict[str, Any]) -> str:
    variable_name = _step_code_variable_name(step)
    code_text = str(step.get("code", "") or "").replace('"""', '\\"""')
    return f'{variable_name} = """{code_text}"""\nprint({variable_name})\n'


def _step_runner_cell(step: dict[str, Any]) -> str:
    variable_name = _step_code_variable_name(step)
    return textwrap.dedent(
        f"""
        run_agilab_step({int(step['index'])}, code_override={variable_name})
        """
    ).strip() + "\n"


def _notebook_metadata(agilab_payload: dict[str, Any] | None = None) -> dict[str, Any]:
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
    if agilab_payload is not None:
        metadata["agilab"] = agilab_payload
    return metadata


def build_notebook_document(
    toml_data: Dict[str, Any],
    toml_path: str | Path,
    *,
    export_context: NotebookExportContext | None = None,
) -> Dict[str, Any]:
    if export_context is None:
        return _build_plain_notebook(toml_data)

    step_records = _step_records(toml_data)
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
        "related_pages": [asdict(page) for page in export_context.related_pages],
        "steps": step_records,
        "steps_file": str(Path(toml_path)),
    }

    cells: list[dict[str, Any]] = [
        _markdown_cell(
            "\n".join(
                [
                    f"# AGILAB Pipeline Export: {export_context.project_name}",
                    "",
                    "This notebook preserves the AGILAB pipeline as a **supervisor notebook**.",
                    "",
                    f"- Module: `{export_context.module_path}`",
                    f"- Artifact directory: `{export_context.artifact_dir}`",
                    f"- Export mode: `{export_context.export_mode}`",
                    "- Use `run_agilab_step(i)` or `run_agilab_pipeline()` to execute steps in their recorded runtime.",
                    "- The code cells below stay readable/editable, but they do not replace the recorded per-step environment.",
                ]
            )
        ),
        _code_cell(_helper_cell(payload)),
    ]

    for step in step_records:
        cells.append(
            _markdown_cell(
                "\n".join(
                    [
                        f"## Step {step['index']}: {step.get('description') or '(no description)'}",
                        "",
                        f"- Module key: `{step.get('module')}`",
                        f"- Question: `{step.get('question') or ''}`",
                        f"- Runtime: `{step.get('runtime') or 'runpy'}`",
                        f"- Environment root: `{step.get('env') or '(current kernel / controller default)'}`",
                        "",
                        f"- Edit the next cell if you want to override the saved step source.",
                        f"- The runner cell below it replays the step with its recorded runtime. Running the whole notebook executes those runner cells too.",
                    ]
                )
            )
        )
        cells.append(_code_cell(_step_source_cell(step)))
        cells.append(_code_cell(_step_runner_cell(step)))

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
        "metadata": _notebook_metadata(payload),
        "nbformat": 4,
        "nbformat_minor": 5,
    }
