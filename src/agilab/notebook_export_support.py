from __future__ import annotations

import json
import textwrap
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Sequence

import tomllib


DEFAULT_NOTEBOOK_EXPORT_MODE = "supervisor"


@dataclass(frozen=True)
class RelatedPageExport:
    module: str
    label: str = ""
    description: str = ""
    artifacts: tuple[str, ...] = ()
    launch_note: str = ""
    script_path: str = ""


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
            script_path=_discover_page_script(pages_root, page),
        )
        for page in related_pages
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
    notebook_data = {"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}
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
        import shlex
        import subprocess
        import sys
        import tempfile
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


        def _resolve_step_python(step):
            try:
                from agilab.pipeline_runtime import python_for_step
            except Exception:
                return sys.executable
            return str(
                python_for_step(
                    step.get("env") or None,
                    engine=step.get("runtime") or None,
                    code=step.get("code") or "",
                )
            )


        def run_agilab_step(step_index, *, check=True, capture_output=True):
            steps = AGILAB_NOTEBOOK_EXPORT.get("steps", [])
            step = steps[step_index]
            workdir = Path(AGILAB_NOTEBOOK_EXPORT.get("artifact_dir") or ".").expanduser()
            workdir.mkdir(parents=True, exist_ok=True)
            python_exe = _resolve_step_python(step)
            with tempfile.TemporaryDirectory(prefix="agilab_notebook_step_") as tmpdir:
                script_path = Path(tmpdir) / f"step_{{step_index:03d}}.py"
                script_path.write_text(step.get("code") or "", encoding="utf-8")
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


        def launch_analysis_page(page, *, port=None, wait=False):
            cmd = analysis_launch_command(page, port=port)
            print(cmd)
            if cmd.startswith("#"):
                return cmd
            if wait:
                return subprocess.run(cmd, shell=True, check=False)
            return subprocess.Popen(cmd, shell=True)


        show_agilab_export_summary()
        """
    ).strip() + "\n"


def _analysis_cell(page: RelatedPageExport) -> str:
    return textwrap.dedent(
        f"""
        page = {page.module!r}
        print(f"Analysis page: {{page}}")
        print(analysis_launch_command(page))
        # Uncomment to launch immediately:
        # launch_analysis_page(page)
        """
    ).strip() + "\n"


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
                        f"To execute this step with its recorded runtime, run `run_agilab_step({step['index']})`.",
                    ]
                )
            )
        )
        cells.append(_code_cell(step.get("code", "")))

    if export_context.related_pages:
        cells.append(
            _markdown_cell(
                "\n".join(
                    [
                        "## Related analysis pages",
                        "",
                        "These helper cells generate launcher commands for the pages configured under `[pages].view_module` in the app settings.",
                        "The pages remain external Streamlit dashboards over the same exported artifacts.",
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
                            *(["- " + page.launch_note] if page.launch_note else []),
                            "- Run the next cell to print the launch command.",
                        ]
                    )
                )
            )
            cells.append(_code_cell(_analysis_cell(page)))

    return {
        "cells": cells,
        "metadata": {"agilab": payload},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
