"""Runtime and background-service helpers extracted from pagelib."""

from __future__ import annotations

import os
import random
import re
import shlex
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Sequence

from . import mlflow_store


_SHELL_METACHARS = frozenset(";&|<>\n\r`$")


def _command_argv(command: str | Sequence[str], *, os_module=os) -> list[str]:
    if isinstance(command, str):
        if any(char in command for char in _SHELL_METACHARS):
            raise ValueError(f"Shell metacharacters are not allowed in page runtime command: {command!r}")
        argv = shlex.split(command, posix=os_module.name != "nt")
    else:
        argv = [str(part) for part in command]
    if not argv:
        raise ValueError("Page runtime command must not be empty")
    return argv


def run_with_output(
    env,
    cmd,
    cwd: str | Path = "./",
    timeout=None,
    *,
    path_cls=Path,
    os_module=os,
    popen_factory=subprocess.Popen,
    ansi_strip_fn: Callable[[str], str] | None = None,
    streamlit=None,
    jump_to_main_exc=RuntimeError,
):
    """Execute a command and return stdout/stderr with ANSI escapes stripped."""
    ansi_strip = ansi_strip_fn or (lambda text: re.sub(r"\x1b[^m]*m", "", text))
    os_module.environ["uv_IGNORE_ACTIVE_VENV"] = "1"
    process_env = os_module.environ.copy()

    argv = _command_argv(cmd, os_module=os_module)
    with popen_factory(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        shell=False,
        cwd=path_cls(cwd).absolute(),
        env=process_env,
        text=True,
    ) as proc:
        try:
            outs, _ = proc.communicate(timeout=timeout)
            if "module not found" in outs:
                if not (env.apps_path / ".venv").exists():
                    raise jump_to_main_exc(outs)
            elif proc.returncode or "failed" in outs.lower() or "error" in outs.lower():
                pass
        except subprocess.TimeoutExpired as err:
            proc.kill()
            outs, _ = proc.communicate()
            if streamlit is not None:
                streamlit.error(err)
        except subprocess.CalledProcessError as err:
            outs, _ = proc.communicate()
            if streamlit is not None:
                streamlit.error(err)

        return ansi_strip(outs)


def run(command, cwd=None, *, subprocess_module=subprocess, log_fn=None, sys_module=sys):
    """Execute a command and terminate on failure like the legacy pagelib helper."""
    try:
        subprocess_module.run(
            _command_argv(command, os_module=os),
            shell=False,
            check=True,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if log_fn is not None:
            log_fn(f"Executed: {command}")
    except subprocess.CalledProcessError as exc:
        if log_fn is not None:
            log_fn(f"Error executing command: {command}")
            log_fn(f"Exit Code: {exc.returncode}")
            log_fn(f"Output: {exc.output.decode().strip()}")
            log_fn(f"Error Output: {exc.stderr.decode().strip()}")
        sys_module.exit(exc.returncode)


def subproc(command, cwd, *, subprocess_module=subprocess, os_module=os, env=None):
    """Execute a command in the background and return its stdout pipe."""
    process_env = dict(env) if env is not None else os_module.environ.copy()
    return subprocess_module.Popen(
        _command_argv(command, os_module=os_module),
        shell=False,
        cwd=os_module.path.abspath(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=process_env,
        text=True,
    ).stdout


def _launch_mlflow_server(subproc_fn, cmd: list[str], cwd) -> None:
    env = mlflow_store.mlflow_subprocess_env()
    try:
        subproc_fn(cmd, cwd, env=env)
    except TypeError as exc:
        if "env" not in str(exc):
            raise
        subproc_fn(cmd, cwd)


def is_port_in_use(target_port, *, socket_module=socket) -> bool:
    """Return True when localhost listens on ``target_port``."""
    with socket_module.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex(("localhost", target_port)) == 0


def get_random_port(*, random_module=random) -> int:
    """Return a random background-service port in the AGILAB reserved range."""
    return random_module.randint(8800, 9900)


def next_free_port(*, get_random_port_fn, is_port_in_use_fn) -> int:
    """Keep sampling until a free localhost port is found."""
    port = get_random_port_fn()
    while is_port_in_use_fn(port):
        port = get_random_port_fn()
    return port


def wait_for_listen_port(
    port: int,
    *,
    timeout_sec: float = 15.0,
    poll_interval_sec: float = 0.1,
    time_module=time,
    is_port_in_use_fn: Callable[[int], bool],
) -> bool:
    """Poll until ``port`` starts listening or the timeout expires."""
    deadline = time_module.monotonic() + max(timeout_sec, 0.0)
    while time_module.monotonic() < deadline:
        if is_port_in_use_fn(port):
            return True
        time_module.sleep(max(poll_interval_sec, 0.01))
    return is_port_in_use_fn(port)


def activate_mlflow(
    env=None,
    *,
    session_state,
    streamlit,
    logger,
    resolve_mlflow_tracking_dir_fn,
    ensure_default_mlflow_experiment_fn,
    ensure_mlflow_backend_ready_fn,
    resolve_mlflow_artifact_dir_fn,
    next_free_port_fn,
    wait_for_listen_port_fn,
    subproc_fn,
    cwd,
) -> bool | None:
    """Start the local MLflow server and persist its runtime state."""
    if not env:
        return None
    if session_state.get("mlflow_autostart_disabled"):
        return False

    session_state["rapids_default"] = True
    tracking_dir = resolve_mlflow_tracking_dir_fn(env)
    if not tracking_dir.exists():
        logger.info(f"mkdir {tracking_dir}")
    tracking_dir.mkdir(parents=True, exist_ok=True)
    env.MLFLOW_TRACKING_DIR = str(tracking_dir)

    port = next_free_port_fn()
    try:
        backend_uri = ensure_default_mlflow_experiment_fn(tracking_dir) or ensure_mlflow_backend_ready_fn(
            tracking_dir
        )
        artifact_uri = resolve_mlflow_artifact_dir_fn(tracking_dir).as_uri()
        cmd = mlflow_store.mlflow_cli_argv(
            [
                "server",
                "--backend-store-uri",
                backend_uri,
                "--default-artifact-root",
                artifact_uri,
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            sys_executable=sys.executable,
        )
        _launch_mlflow_server(subproc_fn, cmd, cwd)
        if not wait_for_listen_port_fn(port):
            session_state["server_started"] = False
            session_state.pop("mlflow_port", None)
            streamlit.error(
                "Failed to start the MLflow server: the process did not open its listening port."
            )
            return False
        session_state["server_started"] = True
        session_state["mlflow_port"] = port
        return True
    except mlflow_store.MissingMlflowCliError as exc:
        session_state["server_started"] = False
        session_state["mlflow_autostart_disabled"] = True
        session_state["mlflow_status_message"] = str(exc)
        session_state.pop("mlflow_port", None)
        warning = getattr(streamlit, "warning", None)
        if callable(warning):
            warning(f"MLflow is optional and was not started automatically. {exc}")
        return False
    except (RuntimeError, OSError, ValueError, AttributeError) as exc:
        session_state["server_started"] = False
        session_state.pop("mlflow_port", None)
        streamlit.error(f"Failed to start the server: {exc}")
        return False


def activate_gpt_oss(
    env=None,
    *,
    session_state,
    streamlit,
    next_free_port_fn,
    subproc_fn,
    cwd,
    os_module=os,
    sys_module=sys,
) -> bool:
    """Start a local GPT-OSS Responses API server when the dependency is available."""
    if not env:
        return False

    if session_state.get("gpt_oss_server_started"):
        return True

    session_state.pop("gpt_oss_autostart_failed", None)
    try:
        import gpt_oss  # noqa: F401
    except ImportError:
        streamlit.warning("Install `gpt-oss` (`pip install gpt-oss`) to enable the offline assistant.")
        session_state["gpt_oss_autostart_failed"] = True
        return False

    backend = (
        session_state.get("gpt_oss_backend")
        or env.envars.get("GPT_OSS_BACKEND")
        or os_module.getenv("GPT_OSS_BACKEND")
        or "stub"
    ).strip() or "stub"
    checkpoint = (
        session_state.get("gpt_oss_checkpoint")
        or env.envars.get("GPT_OSS_CHECKPOINT")
        or os_module.getenv("GPT_OSS_CHECKPOINT")
        or ("gpt2" if backend == "transformers" else "")
    ).strip()
    extra_args = (
        session_state.get("gpt_oss_extra_args")
        or env.envars.get("GPT_OSS_EXTRA_ARGS")
        or os_module.getenv("GPT_OSS_EXTRA_ARGS")
        or ""
    ).strip()
    python_exec = env.envars.get("GPT_OSS_PYTHON") or os_module.getenv("GPT_OSS_PYTHON") or sys_module.executable

    requires_checkpoint = backend in {"transformers", "metal", "triton", "vllm"}
    if requires_checkpoint and not checkpoint:
        streamlit.warning(
            "GPT-OSS backend requires a checkpoint. Set `GPT_OSS_CHECKPOINT` in the sidebar or environment."
        )
        session_state["gpt_oss_autostart_failed"] = True
        return False

    try:
        extra_argv = _command_argv(extra_args, os_module=os_module) if extra_args else []
    except ValueError as exc:
        streamlit.error(f"Failed to start GPT-OSS server: {exc}")
        session_state["gpt_oss_autostart_failed"] = True
        return False

    env.envars["GPT_OSS_BACKEND"] = backend
    if checkpoint:
        env.envars["GPT_OSS_CHECKPOINT"] = checkpoint
    else:
        env.envars.pop("GPT_OSS_CHECKPOINT", None)
    if extra_args:
        env.envars["GPT_OSS_EXTRA_ARGS"] = extra_args
    else:
        env.envars.pop("GPT_OSS_EXTRA_ARGS", None)

    port = next_free_port_fn()
    cmd = [
        python_exec,
        "-m",
        "gpt_oss.responses_api.serve",
        "--inference-backend",
        backend,
        "--port",
        str(int(port)),
    ]
    if checkpoint and backend != "stub":
        cmd.extend(["--checkpoint", checkpoint])
    cmd.extend(extra_argv)

    try:
        subproc_fn(cmd, cwd)
    except (RuntimeError, OSError, ValueError) as exc:
        streamlit.error(f"Failed to start GPT-OSS server: {exc}")
        session_state["gpt_oss_autostart_failed"] = True
        return False

    endpoint = f"http://127.0.0.1:{port}/v1/responses"
    session_state["gpt_oss_server_started"] = True
    session_state["gpt_oss_port"] = port
    session_state["gpt_oss_endpoint"] = endpoint
    env.envars["GPT_OSS_ENDPOINT"] = endpoint
    session_state["gpt_oss_backend_active"] = backend
    if checkpoint:
        session_state["gpt_oss_checkpoint_active"] = checkpoint
    else:
        session_state.pop("gpt_oss_checkpoint_active", None)
    if extra_args:
        session_state["gpt_oss_extra_args_active"] = extra_args
    else:
        session_state.pop("gpt_oss_extra_args_active", None)
    session_state.pop("gpt_oss_autostart_failed", None)
    return True
