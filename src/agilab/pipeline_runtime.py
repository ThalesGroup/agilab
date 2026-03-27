from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Callable, Dict, List, Optional, Pattern, Type

from agi_env import AgiEnv
from agi_env.pagelib import run_lab

MLFLOW_STEP_RUN_ID_ENV = "AGILAB_PIPELINE_MLFLOW_RUN_ID"
MLFLOW_TEXT_LIMIT = 500
DEFAULT_MLFLOW_EXPERIMENT_NAME = "Default"


def to_bool_flag(value: Any, default: bool = False) -> bool:
    """Convert settings values to bool with tolerant parsing."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return default


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
    except Exception:
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
    verbose_raw = cluster.get("verbose", 1)
    try:
        verbose = int(verbose_raw)
    except Exception:
        verbose = 1

    return f"""{marker}
import asyncio
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv

APPS_PATH = {str(env.apps_path)!r}
APP = {str(env.app)!r}
VERBOSE = {verbose}
MODE = {mode}
SCHEDULER = {scheduler!r}
WORKERS = {workers!r}
RUN_ARGS = {run_args!r}

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


def get_mlflow_module():
    """Import MLflow lazily so callers can degrade gracefully when unavailable."""
    try:
        import mlflow  # type: ignore
    except Exception:
        return None
    return mlflow


def truncate_mlflow_text(value: Any, limit: int = MLFLOW_TEXT_LIMIT) -> str:
    """Convert arbitrary values into bounded MLflow-safe strings."""
    text = "" if value is None else str(value)
    if limit <= 0 or len(text) <= limit:
        return text
    if limit == 1:
        return text[:1]
    return text[: limit - 1] + "…"


def resolve_mlflow_tracking_dir(env: AgiEnv) -> Path:
    """Resolve the shared MLflow store, falling back to HOME when unset."""
    home_abs = Path(getattr(env, "home_abs", Path.home())).expanduser()
    tracking_value = getattr(env, "MLFLOW_TRACKING_DIR", None)
    if tracking_value:
        tracking_dir = Path(tracking_value).expanduser()
        if not tracking_dir.is_absolute():
            tracking_dir = home_abs / tracking_dir
    else:
        tracking_dir = home_abs / ".mlflow"
    tracking_dir.mkdir(parents=True, exist_ok=True)
    return tracking_dir.resolve()


def mlflow_tracking_uri(env: AgiEnv) -> str:
    """Return the shared MLflow tracking URI used by the AGILab sidebar service."""
    return resolve_mlflow_tracking_dir(env).as_uri()


def ensure_default_mlflow_experiment(env: AgiEnv, mlflow: Any | None = None) -> str | None:
    """Create the default experiment when the backend store is still empty."""
    mlflow = mlflow or get_mlflow_module()
    if mlflow is None:
        return None
    tracking_uri = mlflow_tracking_uri(env)
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(DEFAULT_MLFLOW_EXPERIMENT_NAME)
    return tracking_uri


def build_mlflow_process_env(
    env: AgiEnv,
    *,
    run_id: str | None = None,
    base_env: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Inject the shared tracking URI into a child process environment."""
    process_env = dict(base_env or os.environ.copy())
    process_env["MLFLOW_TRACKING_URI"] = mlflow_tracking_uri(env)
    if run_id:
        process_env[MLFLOW_STEP_RUN_ID_ENV] = str(run_id)
        # Standard env name so explicit mlflow clients in child code can reuse the step run.
        process_env["MLFLOW_RUN_ID"] = str(run_id)
    else:
        process_env.pop(MLFLOW_STEP_RUN_ID_ENV, None)
        process_env.pop("MLFLOW_RUN_ID", None)
    return process_env


@contextmanager
def temporary_env_overrides(overrides: Optional[Dict[str, Any]]):
    """Temporarily apply environment overrides for in-process step execution."""
    if not overrides:
        yield
        return

    sentinel = object()
    previous = {key: os.environ.get(key, sentinel) for key in overrides}
    try:
        for key, value in overrides.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = str(value)
        yield
    finally:
        for key, value in previous.items():
            if value is sentinel:
                os.environ.pop(key, None)
            else:
                os.environ[key] = str(value)


@contextmanager
def start_mlflow_run(
    env: AgiEnv,
    *,
    run_name: str,
    tags: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    nested: bool = False,
):
    """Open an MLflow run against the sidebar tracking store when MLflow is available."""
    mlflow = get_mlflow_module()
    if mlflow is None:
        yield None
        return

    tracking_uri = ensure_default_mlflow_experiment(env, mlflow)
    clean_tags = {
        str(key): truncate_mlflow_text(value, 5000)
        for key, value in (tags or {}).items()
        if value is not None
    }
    clean_params = {
        str(key): truncate_mlflow_text(value, MLFLOW_TEXT_LIMIT)
        for key, value in (params or {}).items()
        if value is not None
    }
    run_kwargs: Dict[str, Any] = {"run_name": run_name}
    if nested:
        run_kwargs["nested"] = True

    with mlflow.start_run(**run_kwargs) as run:
        if clean_tags:
            mlflow.set_tags(clean_tags)
        if clean_params:
            mlflow.log_params(clean_params)
        yield {"mlflow": mlflow, "run": run, "tracking_uri": tracking_uri}


def log_mlflow_artifacts(
    tracking: Optional[Dict[str, Any]],
    *,
    text_artifacts: Optional[Dict[str, Any]] = None,
    file_artifacts: Optional[List[str | Path]] = None,
    tags: Optional[Dict[str, Any]] = None,
    metrics: Optional[Dict[str, float]] = None,
) -> None:
    """Log text/file artifacts plus final tags/metrics to an active MLflow run."""
    if not tracking:
        return

    mlflow = tracking["mlflow"]
    if tags:
        mlflow.set_tags(
            {
                str(key): truncate_mlflow_text(value, 5000)
                for key, value in tags.items()
                if value is not None
            }
        )
    if metrics:
        for key, value in metrics.items():
            if value is None:
                continue
            try:
                mlflow.log_metric(str(key), float(value))
            except Exception:
                continue
    for artifact_name, text in (text_artifacts or {}).items():
        if text is None:
            continue
        payload = str(text)
        if hasattr(mlflow, "log_text"):
            mlflow.log_text(payload, artifact_name)
        else:
            with NamedTemporaryFile("w", encoding="utf-8", suffix=Path(artifact_name).suffix or ".txt", delete=False) as tmp:
                tmp.write(payload)
                tmp_path = Path(tmp.name)
            try:
                mlflow.log_artifact(str(tmp_path), artifact_path=str(Path(artifact_name).parent))
            finally:
                tmp_path.unlink(missing_ok=True)
    for artifact in file_artifacts or []:
        if not artifact:
            continue
        artifact_path = Path(artifact).expanduser()
        if artifact_path.exists():
            mlflow.log_artifact(str(artifact_path))


def wrap_code_with_mlflow_resume(code: str) -> str:
    """Resume a controller-created MLflow run inside subprocess-executed user code."""
    body = code if code.endswith("\n") else code + "\n"
    indented = "".join(f"    {line}\n" for line in body.splitlines()) if body.strip() else "    pass\n"
    return (
        "import os\n"
        "_agilab_mlflow = None\n"
        "_agilab_active_run = None\n"
        "try:\n"
        "    import mlflow as _agilab_mlflow\n"
        "    _agilab_tracking_uri = os.environ.get('MLFLOW_TRACKING_URI')\n"
        "    if _agilab_tracking_uri:\n"
        "        _agilab_mlflow.set_tracking_uri(_agilab_tracking_uri)\n"
        f"    _agilab_run_id = os.environ.get('{MLFLOW_STEP_RUN_ID_ENV}') or os.environ.get('MLFLOW_RUN_ID')\n"
        "    if _agilab_run_id:\n"
        "        _agilab_active_run = _agilab_mlflow.start_run(run_id=_agilab_run_id)\n"
        "except Exception:\n"
        "    _agilab_mlflow = None\n"
        "    _agilab_active_run = None\n"
        "\n"
        "try:\n"
        f"{indented}"
        "finally:\n"
        "    if _agilab_active_run is not None and _agilab_mlflow is not None:\n"
        "        try:\n"
        "            _agilab_mlflow.end_run()\n"
        "        except Exception:\n"
        "            pass\n"
    )


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
    except Exception as exc:
        debug_log("Unable to ensure safe service template at %s: %s", template_path, exc)
        return None


def python_for_venv(venv_root: str | Path | None) -> Path:
    """Return a python executable for a runtime selection."""
    if not venv_root:
        return Path(sys.executable)

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

    return Path(sys.executable)


def is_valid_runtime_root(venv_root: str | Path | None) -> bool:
    """Return True when the runtime root points at an existing project/venv."""
    if not venv_root:
        return False
    try:
        root = Path(venv_root).expanduser()
    except Exception:
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
) -> str:
    """Run a shell command and stream its output into the run log."""
    process_env = os.environ.copy()
    process_env["uv_IGNORE_ACTIVE_VENV"] = "1"
    apps_root = getattr(env, "apps_path", None)
    extra_python_paths: List[str] = []
    if apps_root:
        try:
            apps_root = Path(apps_root).expanduser()
            src_root = apps_root.parent.parent
            if (src_root / "agilab").is_dir():
                extra_python_paths.append(str(src_root))
        except Exception:
            pass
    if extra_python_paths:
        existing = process_env.get("PYTHONPATH")
        joined = os.pathsep.join(extra_python_paths + ([existing] if existing else []))
        process_env["PYTHONPATH"] = joined
    if extra_env:
        process_env.update({str(key): str(value) for key, value in extra_env.items() if value is not None})

    lines: List[str] = []
    with subprocess.Popen(
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
            env_label = Path(venv_root).name if venv_root else "default env"
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
            with start_mlflow_run(
                env,
                run_name=f"{getattr(env, 'app', 'agilab')}:{Path(steps_file).parent.name}:step_{step + 1}",
                tags=step_tags,
                params=step_params,
            ) as step_tracking:
                step_env = build_mlflow_process_env(
                    env,
                    run_id=step_tracking["run"].info.run_id if step_tracking else None,
                )
                step_files: List[Any] = []
                if engine == "runpy":
                    run_output = run_lab(
                        [entry.get("D", ""), entry.get("Q", ""), code_to_run],
                        snippet_file,
                        env.copilot_file,
                        env_overrides=step_env,
                    )
                    step_files.append(Path(snippet_file))
                else:
                    script_path = (target_base / "AGI_run.py").resolve()
                    script_path.write_text(wrap_code_with_mlflow_resume(code_to_run))
                    step_files.append(script_path)
                    python_cmd = python_for_venv(venv_root)
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
                    log_mlflow_artifacts(
                        step_tracking,
                        text_artifacts={f"step_{step + 1}/stdout.txt": preview or ""},
                        file_artifacts=step_files,
                        tags={"agilab.status": "completed"},
                    )
        finally:
            st.session_state.pop(f"{index_page_str}__run_log_file", None)
    finally:
        release_pipeline_run_lock(lock_handle, index_page_str, stored_placeholder)
