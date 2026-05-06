from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Pattern, Type

from agi_env import AgiEnv
from agi_env.snippet_contract import (
    is_supported_snippet_api,
    is_generated_agi_snippet,
    snippet_contract_block,
    stale_snippet_cleanup_message,
)
from agilab.runtime_diagnostics import coerce_diagnostics_verbose


def to_bool_flag(value: Any, default: bool = False) -> bool:
    """Convert settings values to bool with tolerant parsing."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return default


def snippet_apps_path(env: Any) -> str:
    apps_path = getattr(env, "apps_path", "")
    app = str(getattr(env, "app", "") or "")
    active_app = getattr(env, "active_app", None)

    if isinstance(active_app, Path) and active_app.parent.name == "builtin":
        return str(active_app.parent)

    if apps_path and app:
        try:
            candidate = Path(str(apps_path)) / "builtin" / app
            if candidate.exists():
                return str(candidate.parent)
        except (OSError, RuntimeError, TypeError, ValueError):
            pass

    return str(apps_path)


def safe_service_start_template(env: AgiEnv, marker: str) -> str:
    """Build an idempotent AGI.serve(start) snippet for PIPELINE import."""
    settings: Dict[str, Any] = {}
    try:
        app_settings_path = Path(env.app_settings_file)
        if app_settings_path.exists():
            with app_settings_path.open("rb") as stream:
                loaded = tomllib.load(stream)
            if isinstance(loaded, dict):
                settings = loaded
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError, tomllib.TOMLDecodeError):
        settings = {}

    cluster = settings.get("cluster", {}) if isinstance(settings.get("cluster"), dict) else {}
    run_args = settings.get("args", {}) if isinstance(settings.get("args"), dict) else {}

    cluster_enabled = to_bool_flag(cluster.get("cluster_enabled"), False)
    pool = to_bool_flag(cluster.get("pool"), False)
    cython = to_bool_flag(cluster.get("cython"), False)
    rapids = to_bool_flag(cluster.get("rapids"), False)
    mode = int(pool) + int(cython) * 2 + int(cluster_enabled) * 4 + int(rapids) * 8
    scheduler = cluster.get("scheduler") if cluster.get("scheduler") else None
    workers = cluster.get("workers") if isinstance(cluster.get("workers"), dict) else None
    verbose = coerce_diagnostics_verbose(cluster.get("verbose", 1))

    def _safe_literal(value: Any) -> str:
        if value is None:
            return "None"
        if isinstance(value, bool):
            return "True" if value else "False"
        if isinstance(value, int):
            return str(value)
        if isinstance(value, str):
            return json.dumps(value)
        return json.dumps(value)

    apps_path_lit = _safe_literal(snippet_apps_path(env))
    app_lit = _safe_literal(str(env.app))
    scheduler_lit = _safe_literal(scheduler)
    workers_lit = _safe_literal(workers) if workers is None else f"json.loads({json.dumps(json.dumps(workers))})"
    run_args_lit = _safe_literal(run_args) if run_args is None else f"json.loads({json.dumps(json.dumps(run_args))})"
    workers_preview = "" if workers is None else f"# WORKERS = {workers!r}\n"
    run_args_preview = "" if run_args is None else f"# RUN_ARGS = {run_args!r}\n"
    needs_json = workers is not None or run_args is not None
    json_import = "\nimport json" if needs_json else ""

    return f"""{marker}
import asyncio{json_import}
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv
{snippet_contract_block(app=str(env.app), generator="agilab.pipeline")}

APPS_PATH = {apps_path_lit}
APP = {app_lit}
VERBOSE = {int(verbose)}
MODE = {int(mode)}
SCHEDULER = {scheduler_lit}
{workers_preview}WORKERS = {workers_lit}
{run_args_preview}RUN_ARGS = {run_args_lit}

async def safe_service_start():
    app_env = AgiEnv(apps_path=APPS_PATH, app=APP, verbose=VERBOSE)
    if MODE & 4 == 0:
        raise RuntimeError(
            "Cluster (Dask) is disabled in app_settings.toml. "
            "Enable cluster before starting AGI.serve."
        )

    status = await AGI.serve(
        app_env,
        action="status",
        mode=MODE,
        scheduler=SCHEDULER,
        workers=WORKERS,
        **RUN_ARGS,
    )
    state = str((status or {{}}).get("status", "")).lower()

    if state in {{"running", "degraded"}}:
        print("Service already running; start skipped.")
        print(status)
        return status

    if state == "error":
        await AGI.serve(
            app_env,
            action="stop",
            mode=MODE,
            scheduler=SCHEDULER,
            workers=WORKERS,
            **RUN_ARGS,
        )

    result = await AGI.serve(
        app_env,
        action="start",
        mode=MODE,
        scheduler=SCHEDULER,
        workers=WORKERS,
        **RUN_ARGS,
    )
    print(result)
    return result

if __name__ == "__main__":
    asyncio.run(safe_service_start())
"""


def ensure_safe_service_template(
    env: AgiEnv,
    steps_file: Path,
    *,
    template_filename: str,
    marker: str,
    debug_log: Callable[[str, Any], None],
) -> Optional[Path]:
    """Create or update an autogenerated safe service snippet file near lab steps."""
    template_path = steps_file.parent / template_filename
    content = safe_service_start_template(env, marker)
    try:
        existing = template_path.read_text(encoding="utf-8") if template_path.exists() else None
        if existing == content:
            return template_path
        if existing:
            first_line = existing.splitlines()[0].strip()
            if first_line and first_line != marker:
                return template_path
        template_path.parent.mkdir(parents=True, exist_ok=True)
        template_path.write_text(content, encoding="utf-8")
        return template_path
    except OSError as exc:
        debug_log("Unable to ensure safe service template at %s: %s", template_path, exc)
        return None


def python_for_venv(venv_root: str | Path | None, *, sys_executable: str | None = None) -> Path:
    """Return a python executable for a runtime selection."""
    if not venv_root:
        return Path(sys_executable or sys.executable)

    root = Path(venv_root).expanduser()
    venv_candidates = [root]
    project_venv = root / ".venv"
    if project_venv.exists():
        venv_candidates.insert(0, project_venv)

    for venv in venv_candidates:
        for candidate in (
            venv / "bin" / "python",
            venv / "bin" / "python3",
            venv / "Scripts" / "python.exe",
            venv / "Scripts" / "python",
        ):
            if candidate.exists():
                return candidate

    return Path(sys_executable or sys.executable)


def uses_controller_python(engine: str | None, code: str | None) -> bool:
    """Return True when a step should execute in the current AGILab/controller env."""
    if not str(engine or "").startswith("agi."):
        return False
    text = str(code or "")
    return (
        "from agi_cluster.agi_distributor import AGI" in text
        or "import agi_cluster" in text
        or "AGI.install(" in text
        or "AGI.run(" in text
        or "AGI.serve(" in text
        or "AGI.get_distrib(" in text
    )


def python_for_step(
    venv_root: str | Path | None,
    *,
    engine: str | None,
    code: str | None,
    sys_executable: str | None = None,
) -> Path:
    """Choose the python executable for one step."""
    if uses_controller_python(engine, code):
        return Path(sys_executable or sys.executable)
    return python_for_venv(venv_root, sys_executable=sys_executable)


def label_for_step_runtime(
    venv_root: str | Path | None,
    *,
    engine: str | None,
    code: str | None,
    sys_executable: str | None = None,
) -> str:
    """Return a readable runtime label for the step log."""
    if uses_controller_python(engine, code):
        executable = Path(sys_executable or sys_executable)
        target = Path(venv_root).name if venv_root else str(getattr(executable, "name", "python"))
        return f"controller env -> {target}"
    return Path(venv_root).name if venv_root else "default env"


def is_valid_runtime_root(venv_root: str | Path | None) -> bool:
    """Return True when the runtime root points at an existing project/venv."""
    if not venv_root:
        return False
    try:
        root = Path(venv_root).expanduser()
    except (OSError, RuntimeError, TypeError, ValueError):
        return False
    if not root.exists():
        return False
    if (root / ".venv").exists():
        return True
    for candidate in (
        root / "bin" / "python",
        root / "bin" / "python3",
        root / "Scripts" / "python.exe",
        root / "Scripts" / "python",
    ):
        if candidate.exists():
            return True
    return False


def stream_run_command(
    env: AgiEnv,
    index_page: str,
    cmd: str,
    cwd: Path,
    *,
    push_run_log: Callable[[str, str, Optional[Any]], None],
    ansi_escape_re: Pattern[str],
    jump_exception_cls: Type[BaseException],
    placeholder: Optional[Any] = None,
    extra_env: Optional[Dict[str, str]] = None,
    timeout: Optional[int] = None,
    env_vars: Optional[Dict[str, str]] = None,
    popen_factory: Callable[..., Any] = subprocess.Popen,
    path_separator: str = os.pathsep,
) -> str:
    """Run a shell command and stream its output into the run log."""
    process_env = dict(env_vars or os.environ.copy())
    process_env["uv_IGNORE_ACTIVE_VENV"] = "1"
    apps_root = getattr(env, "apps_path", None)
    extra_python_paths: List[str] = []
    if apps_root:
        try:
            apps_root = Path(apps_root).expanduser()
            src_root = apps_root.parent.parent
            if (src_root / "agilab").is_dir():
                extra_python_paths.append(str(src_root))
        except (OSError, RuntimeError, TypeError, ValueError):
            pass
    if extra_python_paths:
        existing = process_env.get("PYTHONPATH")
        joined = path_separator.join(extra_python_paths + ([existing] if existing else []))
        process_env["PYTHONPATH"] = joined
    if extra_env:
        process_env.update({str(key): str(value) for key, value in extra_env.items() if value is not None})

    lines: List[str] = []
    with popen_factory(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        shell=True,
        cwd=Path(cwd).resolve(),
        env=process_env,
        text=True,
        bufsize=1,
    ) as proc:
        try:
            assert proc.stdout is not None
            for raw_line in proc.stdout:
                cleaned = ansi_escape_re.sub("", raw_line.rstrip())
                if cleaned:
                    lines.append(cleaned)
                    push_run_log(index_page, cleaned, placeholder)
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            push_run_log(index_page, f"Command timed out after {timeout} seconds.", placeholder)
        except subprocess.CalledProcessError as err:
            proc.kill()
            push_run_log(index_page, f"Command failed: {err}", placeholder)
        combined = "\n".join(lines).strip()
        lowered = combined.lower()
        if "module not found" in lowered:
            apps_root = env.apps_path
            if apps_root and not (Path(apps_root) / ".venv").exists():
                raise jump_exception_cls(combined)
        return combined


def run_locked_step(
    env: AgiEnv,
    index_page_str: str,
    steps_file: Path,
    step: int,
    entry: Dict[str, Any],
    selected_map: Dict[int, str],
    engine_map: Dict[int, str],
    *,
    normalize_runtime_path: Callable[[Any], str],
    prepare_run_log_file: Callable[[str, AgiEnv, str], tuple[Optional[Path], Optional[str]]],
    push_run_log: Callable[[str, str, Optional[Any]], None],
    refresh_pipeline_run_lock: Callable[[Optional[Dict[str, Any]]], None],
    acquire_pipeline_run_lock: Callable[[AgiEnv, str, Optional[Any]], Optional[Dict[str, Any]]],
    release_pipeline_run_lock: Callable[[Optional[Dict[str, Any]], str, Optional[Any]], None],
    get_run_placeholder: Callable[[str], Optional[Any]],
    is_valid_runtime_root: Callable[[str | Path | None], bool],
    python_for_venv: Callable[[str | Path | None], Path],
    stream_run_command: Callable[..., str],
    step_summary: Callable[[Optional[Dict[str, Any]], int], str],
    label_for_step_runtime_fn: Callable[[str | Path | None], str] | Callable[..., str],
    start_mlflow_run_fn: Callable[..., Any],
    build_mlflow_process_env_fn: Callable[..., Dict[str, str]],
    log_mlflow_artifacts_fn: Callable[..., None],
    run_lab_fn: Callable[..., str],
    python_for_step_fn: Callable[..., Path],
    wrap_code_with_mlflow_resume_fn: Callable[[str], str],
) -> None:
    """Execute one immutable ORCHESTRATE-derived step."""
    stored_placeholder = get_run_placeholder(index_page_str)
    import streamlit as st

    st.session_state[f"{index_page_str}__run_logs"] = []
    if stored_placeholder is not None:
        stored_placeholder.caption("Starting step execution…")
    snippet_file = st.session_state.get("snippet_file")
    if not snippet_file:
        st.error("Snippet file is not configured. Reload the page and try again.")
        return
    lock_handle = acquire_pipeline_run_lock(env, index_page_str, stored_placeholder)
    if lock_handle is None:
        return

    try:
        selected_map_entry = normalize_runtime_path(selected_map.get(step, ""))
        entry_runtime_raw = normalize_runtime_path(entry.get("E", ""))
        venv_root = selected_map_entry or (entry_runtime_raw if is_valid_runtime_root(entry_runtime_raw) else "")
        if not venv_root:
            fallback = normalize_runtime_path(st.session_state.get("lab_selected_venv", ""))
            if fallback and is_valid_runtime_root(fallback):
                venv_root = fallback
        if not venv_root:
            fallback = normalize_runtime_path(getattr(env, "active_app", ""))
            if is_valid_runtime_root(fallback):
                venv_root = fallback

        entry_engine = str(entry.get("R", "") or "")
        engine = entry_engine or ("agi.run" if venv_root else "runpy")
        if engine.startswith("agi.") and not venv_root:
            fallback = normalize_runtime_path(getattr(env, "active_app", "") or "")
            if is_valid_runtime_root(fallback):
                venv_root = fallback
        if venv_root:
            selected_map[step] = venv_root
            st.session_state["lab_selected_venv"] = venv_root
            if engine == "runpy":
                engine = "agi.run"

        code_to_run = str(entry.get("C", ""))
        if is_generated_agi_snippet(code_to_run) and not is_supported_snippet_api(code_to_run):
            source = entry.get("_orchestrate_snippet_source") or entry.get("Q") or ""
            paths = [source] if source else None
            message = stale_snippet_cleanup_message(paths)
            st.error(message)
            push_run_log(index_page_str, message, stored_placeholder)
            return
        engine_map[step] = engine
        st.session_state["lab_selected_engine"] = engine

        log_file_path, log_error = prepare_run_log_file(index_page_str, env, f"step_{step + 1}")
        if log_file_path:
            push_run_log(
                index_page_str,
                f"Run step {step + 1} started… logs will be saved to {log_file_path}",
                stored_placeholder,
            )
        else:
            push_run_log(
                index_page_str,
                f"Run step {step + 1} started… (unable to prepare log file: {log_error})",
                stored_placeholder,
            )

        try:
            refresh_pipeline_run_lock(lock_handle)
            target_base = Path(steps_file).parent.resolve()
            target_base.mkdir(parents=True, exist_ok=True)
            env_label = label_for_step_runtime_fn(venv_root, engine=engine, code=code_to_run)
            summary = step_summary({"Q": entry.get("Q", ""), "C": code_to_run}, 60)
            step_tags = {
                "agilab.component": "pipeline-step",
                "agilab.app": str(getattr(env, "app", "") or ""),
                "agilab.lab": Path(steps_file).parent.name,
                "agilab.step_index": step + 1,
                "agilab.engine": engine,
                "agilab.runtime": venv_root or "",
                "agilab.summary": summary,
            }
            step_params = {
                "description": entry.get("D", ""),
                "question": entry.get("Q", ""),
                "model": entry.get("M", ""),
                "runtime": venv_root or "",
                "engine": engine,
            }
            with start_mlflow_run_fn(
                env,
                run_name=f"{getattr(env, 'app', 'agilab')}:{Path(steps_file).parent.name}:step_{step + 1}",
                tags=step_tags,
                params=step_params,
            ) as step_tracking:
                step_env = build_mlflow_process_env_fn(
                    env,
                    run_id=step_tracking["run"].info.run_id if step_tracking else None,
                )
                step_files: List[Any] = []
                if engine == "runpy":
                    run_output = run_lab_fn(
                        [entry.get("D", ""), entry.get("Q", ""), code_to_run],
                        snippet_file,
                        env.copilot_file,
                        env_overrides=step_env,
                    )
                    step_files.append(Path(snippet_file))
                else:
                    script_path = (target_base / "AGI_run.py").resolve()
                    script_path.write_text(wrap_code_with_mlflow_resume_fn(code_to_run))
                    step_files.append(script_path)
                    python_cmd = python_for_step_fn(venv_root, engine=engine, code=code_to_run)
                    run_output = stream_run_command(
                        env,
                        index_page_str,
                        f"{python_cmd} {script_path}",
                        cwd=target_base,
                        placeholder=stored_placeholder,
                        extra_env=step_env,
                    )
                refresh_pipeline_run_lock(lock_handle)
                push_run_log(
                    index_page_str,
                    f"Step {step + 1}: engine={engine}, env={env_label}, summary=\"{summary}\"",
                    stored_placeholder,
                )
                preview = run_output.strip() if run_output else ""
                if preview:
                    push_run_log(
                        index_page_str,
                        f"Output (step {step + 1}):\n{preview}",
                        stored_placeholder,
                    )
                elif engine == "runpy":
                    push_run_log(
                        index_page_str,
                        f"Output (step {step + 1}): runpy executed (no captured stdout)",
                        stored_placeholder,
                    )
                export_target = st.session_state.get("df_file_out", "")
                if export_target:
                    step_files.append(export_target)
                if step_tracking:
                    log_mlflow_artifacts_fn(
                        step_tracking,
                        text_artifacts={f"step_{step + 1}/stdout.txt": preview or ""},
                        file_artifacts=step_files,
                        tags={"agilab.status": "completed"},
                    )
        finally:
            st.session_state.pop(f"{index_page_str}__run_log_file", None)
    finally:
        release_pipeline_run_lock(lock_handle, index_page_str, stored_placeholder)
