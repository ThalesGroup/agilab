from __future__ import annotations

from types import SimpleNamespace

import pytest

from agi_env.pagelib_execution_support import run_agi, run_lab


def test_run_lab_restores_environment(tmp_path, monkeypatch):
    snippet = tmp_path / "snippet.py"
    codex = tmp_path / "codex.py"
    codex.write_text("print('demo')\n", encoding="utf-8")
    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)

    output = run_lab(
        ["D", "Q", "print('hello')"],
        snippet,
        codex,
        env_overrides={"MLFLOW_TRACKING_URI": "file:///tmp/mlflow"},
        runpy_module=SimpleNamespace(run_path=lambda _path: exec("import os\nprint(os.environ['MLFLOW_TRACKING_URI'])\n", {})),
    )

    assert snippet.read_text(encoding="utf-8") == "print('hello')"
    assert "file:///tmp/mlflow" in output
    assert "MLFLOW_TRACKING_URI" not in __import__("os").environ


def test_run_agi_reports_missing_target_and_permission_errors(tmp_path):
    class _Stop(RuntimeError):
        pass

    messages: list[tuple[str, str]] = []
    env = SimpleNamespace(agi_env=tmp_path / ".venv", target="demo_project", runenv=tmp_path / "runenv")
    fake_st = SimpleNamespace(
        warning=lambda message: messages.append(("warning", str(message))),
        info=lambda message: messages.append(("info", str(message))),
        error=lambda message: messages.append(("error", str(message))),
        stop=lambda: (_ for _ in ()).throw(_Stop("stop")),
    )

    assert run_agi(
        [],
        env=env,
        streamlit=fake_st,
        logger=SimpleNamespace(info=lambda _message: None),
        run_with_output_fn=lambda *_args, **_kwargs: None,
        diagnose_data_directory_fn=lambda _path: "hint",
    ) is None

    with pytest.raises(_Stop):
        run_agi(
            "print('x')",
            env=env,
            path=tmp_path / "missing",
            streamlit=fake_st,
            logger=SimpleNamespace(info=lambda _message: None),
            run_with_output_fn=lambda *_args, **_kwargs: None,
            diagnose_data_directory_fn=lambda _path: "hint",
        )

    assert any(kind == "info" and "Please do an install first" in message for kind, message in messages)
