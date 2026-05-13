from __future__ import annotations

import builtins
import sys
from types import SimpleNamespace

import pytest

from agi_env import pagelib_runtime_support


def test_next_free_port_retries_busy_candidates():
    ports = iter([50101, 50102, 50103])

    chosen = pagelib_runtime_support.next_free_port(
        get_random_port_fn=lambda: next(ports),
        is_port_in_use_fn=lambda port: port != 50103,
    )

    assert chosen == 50103


def test_activate_mlflow_support_updates_session_state_and_env(tmp_path):
    messages: list[str] = []
    launched: list[tuple[list[str], str, dict[str, object]]] = []
    session_state = {}
    env = SimpleNamespace(MLFLOW_TRACKING_DIR="", home_abs=tmp_path)
    original_mlflow_cli_argv = pagelib_runtime_support.mlflow_store.mlflow_cli_argv
    pagelib_runtime_support.mlflow_store.mlflow_cli_argv = lambda args, **_kwargs: ["mlflow", *args]

    try:
        started = pagelib_runtime_support.activate_mlflow(
            env,
            session_state=session_state,
            streamlit=SimpleNamespace(error=lambda message: messages.append(str(message))),
            logger=SimpleNamespace(info=lambda _message: None),
            resolve_mlflow_tracking_dir_fn=lambda _env: tmp_path / ".mlflow",
            ensure_default_mlflow_experiment_fn=lambda _path: "sqlite:///tmp/mlflow.db",
            ensure_mlflow_backend_ready_fn=lambda _path: "sqlite:///tmp/mlflow.db",
            resolve_mlflow_artifact_dir_fn=lambda _path: tmp_path / "artifacts",
            next_free_port_fn=lambda: 50123,
            wait_for_listen_port_fn=lambda _port: True,
            subproc_fn=lambda command, cwd, **kwargs: launched.append((command, cwd, kwargs)),
            cwd=str(tmp_path),
        )
    finally:
        pagelib_runtime_support.mlflow_store.mlflow_cli_argv = original_mlflow_cli_argv

    assert started is True
    assert session_state["server_started"] is True
    assert session_state["mlflow_port"] == 50123
    assert env.MLFLOW_TRACKING_DIR == str(tmp_path / ".mlflow")
    assert launched
    command = launched[0][0]
    launch_kwargs = launched[0][2]
    assert command[:2] == ["mlflow", "server"]
    assert "-m" not in command
    assert command[command.index("--port") + 1] == "50123"
    assert launch_kwargs["env"]["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] == "python"
    assert messages == []


def test_pagelib_runtime_support_command_and_wait_helpers(tmp_path):
    from agi_env import pagelib_runtime_support as support

    class _Proc:
        def __init__(self, *, output, returncode=0, raises=None):
            self.output = output
            self.returncode = returncode
            self.raises = raises
            self.killed = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def communicate(self, timeout=None):
            if self.raises is not None:
                err = self.raises
                self.raises = None
                raise err
            return self.output, ""

        def kill(self):
            self.killed = True

    errors: list[str] = []
    popen_calls: list[tuple[list[str], dict[str, object]]] = []
    proc = _Proc(output="\u001b[31mok\u001b[0m")
    assert support.run_with_output(
        SimpleNamespace(apps_path=tmp_path),
        "echo ok",
        cwd=tmp_path,
        popen_factory=lambda *args, **kwargs: popen_calls.append((list(args[0]), kwargs)) or proc,
    ) == "ok"
    assert popen_calls[0][0] == ["echo", "ok"]
    assert popen_calls[0][1]["shell"] is False

    timed_out = _Proc(output="timed out", raises=support.subprocess.TimeoutExpired(cmd="echo", timeout=1))
    assert support.run_with_output(
        SimpleNamespace(apps_path=tmp_path),
        "echo ok",
        cwd=tmp_path,
        popen_factory=lambda *_args, **_kwargs: timed_out,
        streamlit=SimpleNamespace(error=lambda message: errors.append(str(message))),
    ) == "timed out"
    assert timed_out.killed is True

    calls = []
    with pytest.raises(SystemExit, match="4"):
        support.run(
            "echo broken",
            cwd=tmp_path,
            subprocess_module=SimpleNamespace(
                PIPE=support.subprocess.PIPE,
                CalledProcessError=support.subprocess.CalledProcessError,
                run=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    support.subprocess.CalledProcessError(
                        returncode=4,
                        cmd="echo broken",
                        output=b"out",
                        stderr=b"err",
                    )
                ),
            ),
            log_fn=calls.append,
            sys_module=SimpleNamespace(exit=lambda code: (_ for _ in ()).throw(SystemExit(code))),
        )
    assert any("Exit Code: 4" in line for line in calls)

    ticks = iter([0.0, 0.05, 0.10, 0.20])
    sleeps: list[float] = []
    assert support.wait_for_listen_port(
        50123,
        timeout_sec=0.15,
        poll_interval_sec=0.05,
        time_module=SimpleNamespace(monotonic=lambda: next(ticks), sleep=lambda delay: sleeps.append(delay)),
        is_port_in_use_fn=lambda port: len(sleeps) >= 1,
    ) is True
    assert sleeps == [0.05]

    ticks = iter([0.0, 0.05, 0.10, 0.20])
    sleeps.clear()
    assert support.wait_for_listen_port(
        50123,
        timeout_sec=0.15,
        poll_interval_sec=0.05,
        time_module=SimpleNamespace(monotonic=lambda: next(ticks), sleep=lambda delay: sleeps.append(delay)),
        is_port_in_use_fn=lambda port: False,
    ) is False


def test_activate_mlflow_support_handles_none_timeout_and_runtime_failure(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    messages: list[str] = []
    session_state = {}
    monkeypatch.setattr(
        pagelib_runtime_support.mlflow_store,
        "mlflow_cli_argv",
        lambda args, **_kwargs: ["mlflow", *args],
    )

    assert pagelib_runtime_support.activate_mlflow(
        None,
        session_state=session_state,
        streamlit=SimpleNamespace(error=lambda message: messages.append(str(message))),
        logger=SimpleNamespace(info=lambda _message: None),
        resolve_mlflow_tracking_dir_fn=lambda _env: tmp_path / ".mlflow",
        ensure_default_mlflow_experiment_fn=lambda _path: "sqlite:///tmp/mlflow.db",
        ensure_mlflow_backend_ready_fn=lambda _path: "sqlite:///tmp/mlflow.db",
        resolve_mlflow_artifact_dir_fn=lambda _path: tmp_path / "artifacts",
        next_free_port_fn=lambda: 50123,
        wait_for_listen_port_fn=lambda _port: True,
        subproc_fn=lambda *_args: None,
        cwd=str(tmp_path),
    ) is None

    env = SimpleNamespace(MLFLOW_TRACKING_DIR="", home_abs=tmp_path)
    started = pagelib_runtime_support.activate_mlflow(
        env,
        session_state=session_state,
        streamlit=SimpleNamespace(error=lambda message: messages.append(str(message))),
        logger=SimpleNamespace(info=lambda _message: None),
        resolve_mlflow_tracking_dir_fn=lambda _env: tmp_path / ".mlflow",
        ensure_default_mlflow_experiment_fn=lambda _path: "sqlite:///tmp/mlflow.db",
        ensure_mlflow_backend_ready_fn=lambda _path: "sqlite:///tmp/mlflow.db",
        resolve_mlflow_artifact_dir_fn=lambda _path: tmp_path / "artifacts",
        next_free_port_fn=lambda: 50123,
        wait_for_listen_port_fn=lambda _port: False,
        subproc_fn=lambda *_args: None,
        cwd=str(tmp_path),
    )
    assert started is False

    started = pagelib_runtime_support.activate_mlflow(
        env,
        session_state=session_state,
        streamlit=SimpleNamespace(error=lambda message: messages.append(str(message))),
        logger=SimpleNamespace(info=lambda _message: None),
        resolve_mlflow_tracking_dir_fn=lambda _env: tmp_path / ".mlflow",
        ensure_default_mlflow_experiment_fn=lambda _path: (_ for _ in ()).throw(RuntimeError("backend bug")),
        ensure_mlflow_backend_ready_fn=lambda _path: "sqlite:///tmp/mlflow.db",
        resolve_mlflow_artifact_dir_fn=lambda _path: tmp_path / "artifacts",
        next_free_port_fn=lambda: 50123,
        wait_for_listen_port_fn=lambda _port: True,
        subproc_fn=lambda *_args: None,
        cwd=str(tmp_path),
    )
    assert started is False
    assert any("Failed to start the MLflow server" in message for message in messages)
    assert any("Failed to start the server" in message for message in messages)


def test_activate_gpt_oss_support_clears_empty_checkpoint_and_extra_args(monkeypatch):
    session_state = {
        "gpt_oss_checkpoint": "  ",
        "gpt_oss_extra_args": " ",
        "gpt_oss_checkpoint_active": "old",
        "gpt_oss_extra_args_active": "--old",
    }
    env = SimpleNamespace(envars={"GPT_OSS_BACKEND": "stub", "GPT_OSS_CHECKPOINT": "old"})
    launched: list[tuple[list[str], str]] = []
    monkeypatch.setitem(sys.modules, "gpt_oss", SimpleNamespace())

    started = pagelib_runtime_support.activate_gpt_oss(
        env,
        session_state=session_state,
        streamlit=SimpleNamespace(warning=lambda *_args, **_kwargs: None, error=lambda *_args, **_kwargs: None),
        next_free_port_fn=lambda: 50124,
        subproc_fn=lambda command, cwd: launched.append((command, cwd)),
        cwd="/tmp",
    )

    assert started is True
    assert env.envars["GPT_OSS_ENDPOINT"] == "http://127.0.0.1:50124/v1/responses"
    assert "GPT_OSS_CHECKPOINT" not in env.envars
    assert "GPT_OSS_EXTRA_ARGS" not in env.envars
    assert "gpt_oss_checkpoint_active" not in session_state
    assert "gpt_oss_extra_args_active" not in session_state
    assert launched
    command = launched[0][0]
    assert command[:3] == [sys.executable, "-m", "gpt_oss.responses_api.serve"]
    assert command[command.index("--inference-backend") + 1] == "stub"


def test_activate_gpt_oss_support_handles_existing_import_missing_checkpoint_and_start_failure(monkeypatch):
    session_state = {"gpt_oss_server_started": True}
    env = SimpleNamespace(envars={})

    assert pagelib_runtime_support.activate_gpt_oss(
        env,
        session_state=session_state,
        streamlit=SimpleNamespace(warning=lambda *_args, **_kwargs: None, error=lambda *_args, **_kwargs: None),
        next_free_port_fn=lambda: 50124,
        subproc_fn=lambda *_args: None,
        cwd="/tmp",
    ) is True

    session_state = {}
    warnings: list[str] = []
    original_import = builtins.__import__

    def _patched_import(name, *args, **kwargs):
        if name == "gpt_oss":
            raise ImportError("missing gpt_oss")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(
        builtins,
        "__import__",
        _patched_import,
    )
    try:
        assert pagelib_runtime_support.activate_gpt_oss(
            env,
            session_state=session_state,
            streamlit=SimpleNamespace(warning=lambda message: warnings.append(str(message)), error=lambda *_args, **_kwargs: None),
            next_free_port_fn=lambda: 50124,
            subproc_fn=lambda *_args: None,
            cwd="/tmp",
        ) is False
    finally:
        builtins.__import__ = original_import

    assert warnings and "Install `gpt-oss`" in warnings[0]

    env = SimpleNamespace(envars={})
    session_state = {"gpt_oss_backend": "vllm", "gpt_oss_checkpoint": ""}
    monkeypatch.setitem(sys.modules, "gpt_oss", SimpleNamespace())
    warnings.clear()
    assert pagelib_runtime_support.activate_gpt_oss(
        env,
        session_state=session_state,
        streamlit=SimpleNamespace(warning=lambda message: warnings.append(str(message)), error=lambda *_args, **_kwargs: None),
        next_free_port_fn=lambda: 50124,
        subproc_fn=lambda *_args: None,
        cwd="/tmp",
    ) is False
    assert any("requires a checkpoint" in message for message in warnings)

    errors: list[str] = []
    session_state = {"gpt_oss_backend": "stub"}
    assert pagelib_runtime_support.activate_gpt_oss(
        env,
        session_state=session_state,
        streamlit=SimpleNamespace(warning=lambda *_args, **_kwargs: None, error=lambda message: errors.append(str(message))),
        next_free_port_fn=lambda: 50124,
        subproc_fn=lambda *_args: (_ for _ in ()).throw(RuntimeError("spawn bug")),
        cwd="/tmp",
    ) is False
    assert any("Failed to start GPT-OSS server" in message for message in errors)

    errors.clear()
    session_state = {"gpt_oss_backend": "stub", "gpt_oss_extra_args": "--ok 1; touch injected"}
    assert pagelib_runtime_support.activate_gpt_oss(
        env,
        session_state=session_state,
        streamlit=SimpleNamespace(warning=lambda *_args, **_kwargs: None, error=lambda message: errors.append(str(message))),
        next_free_port_fn=lambda: 50124,
        subproc_fn=lambda *_args: (_ for _ in ()).throw(AssertionError("subproc should not be called")),
        cwd="/tmp",
    ) is False
    assert session_state["gpt_oss_autostart_failed"] is True
    assert any("Shell metacharacters are not allowed" in message for message in errors)


def test_run_with_output_reports_called_process_error(tmp_path):
    class _Proc:
        def __init__(self):
            self.calls = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def communicate(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise pagelib_runtime_support.subprocess.CalledProcessError(
                    returncode=7,
                    cmd="echo broken",
                    output="bad",
                    stderr="worse",
                )
            return "bad", ""

        def kill(self):
            raise AssertionError("kill should not be called for CalledProcessError")

    errors: list[str] = []
    output = pagelib_runtime_support.run_with_output(
        SimpleNamespace(apps_path=tmp_path),
        "echo broken",
        cwd=tmp_path,
        popen_factory=lambda *_args, **_kwargs: _Proc(),
        streamlit=SimpleNamespace(error=lambda message: errors.append(str(message))),
    )

    assert output == "bad"
    assert errors and "returned non-zero exit status 7" in errors[0]
