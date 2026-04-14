from __future__ import annotations

import sys
from types import SimpleNamespace

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
    launched: list[tuple[str, str]] = []
    session_state = {}
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
        wait_for_listen_port_fn=lambda _port: True,
        subproc_fn=lambda command, cwd: launched.append((command, cwd)),
        cwd=str(tmp_path),
    )

    assert started is True
    assert session_state["server_started"] is True
    assert session_state["mlflow_port"] == 50123
    assert env.MLFLOW_TRACKING_DIR == str(tmp_path / ".mlflow")
    assert launched and sys.executable in launched[0][0]
    assert "--port 50123" in launched[0][0]
    assert messages == []


def test_activate_gpt_oss_support_clears_empty_checkpoint_and_extra_args(monkeypatch):
    session_state = {
        "gpt_oss_checkpoint": "  ",
        "gpt_oss_extra_args": " ",
        "gpt_oss_checkpoint_active": "old",
        "gpt_oss_extra_args_active": "--old",
    }
    env = SimpleNamespace(envars={"GPT_OSS_BACKEND": "stub", "GPT_OSS_CHECKPOINT": "old"})
    launched: list[tuple[str, str]] = []
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
    assert launched and "--inference-backend stub" in launched[0][0]
