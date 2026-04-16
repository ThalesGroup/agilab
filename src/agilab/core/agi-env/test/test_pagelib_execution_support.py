from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from agi_env.pagelib_execution_support import run_agi, run_lab


def test_pagelib_execution_support_helpers_cover_fallbacks(tmp_path):
    from agi_env import pagelib_execution_support as support

    assert support._coerce_code_text([]) == ""
    assert support._coerce_code_text([1]) == "1"
    assert support._coerce_code_text(None) == ""

    class _BrokenPathFactory:
        def __call__(self, value):
            if value == "broken":
                raise TypeError("bad path")
            return Path(value)

    resolved = support._resolve_target_path(
        "broken",
        env_agi_env=tmp_path / ".venv",
        path_cls=_BrokenPathFactory(),
    )
    assert resolved == tmp_path


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


def test_run_lab_handles_empty_query_and_execution_error(tmp_path):
    warnings: list[str] = []
    snippet = tmp_path / "snippet.py"
    codex = tmp_path / "codex.py"
    codex.write_text("print('demo')\n", encoding="utf-8")

    assert run_lab(None, snippet, codex) is None

    output = run_lab(
        ["D", "Q", "print('hello')"],
        snippet,
        codex,
        warning_fn=warnings.append,
        runpy_module=SimpleNamespace(run_path=lambda _path: (_ for _ in ()).throw(ValueError("lab bug"))),
    )

    assert output == "Error: lab bug"
    assert warnings == ["Error: lab bug"]


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


def test_run_agi_executes_existing_target_and_reports_access_failures(tmp_path):
    class _Stop(RuntimeError):
        pass

    messages: list[tuple[str, str]] = []
    executed: list[tuple[str, str, str]] = []
    env = SimpleNamespace(agi_env=tmp_path / ".venv", target="demo_project", runenv=tmp_path / "runenv")
    fake_st = SimpleNamespace(
        warning=lambda message: messages.append(("warning", str(message))),
        info=lambda message: messages.append(("info", str(message))),
        error=lambda message: messages.append(("error", str(message))),
        stop=lambda: (_ for _ in ()).throw(_Stop("stop")),
    )
    target_dir = tmp_path / "installed"
    target_dir.mkdir()

    result = run_agi(
        ["D", "Q", "await Agi.run()"],
        env=env,
        path=target_dir,
        streamlit=fake_st,
        logger=SimpleNamespace(info=lambda _message: None),
        run_with_output_fn=lambda current_env, command, cwd: executed.append((current_env.target, command, cwd)) or "ok",
        diagnose_data_directory_fn=lambda _path: "hint",
    )

    assert result == "ok"
    assert executed and executed[0][0] == "demo_project"
    assert executed[0][2] == str(target_dir)

    broken_path = tmp_path / "forbidden"

    path_type = type(tmp_path)

    class _BrokenPath(path_type):

        def exists(self):
            raise PermissionError("denied")

    with pytest.raises(_Stop):
        run_agi(
            "print('x')",
            env=env,
            path=str(broken_path),
            streamlit=fake_st,
            logger=SimpleNamespace(info=lambda _message: None),
            run_with_output_fn=lambda *_args, **_kwargs: None,
            diagnose_data_directory_fn=lambda _path: "hint",
            path_cls=_BrokenPath,
        )

    class _OSErrorPath(path_type):

        def exists(self):
            raise OSError("io failed")

    with pytest.raises(_Stop):
        run_agi(
            "print('x')",
            env=env,
            path=str(broken_path),
            streamlit=fake_st,
            logger=SimpleNamespace(info=lambda _message: None),
            run_with_output_fn=lambda *_args, **_kwargs: None,
            diagnose_data_directory_fn=lambda _path: "hint",
            path_cls=_OSErrorPath,
        )

    assert any(kind == "error" and "Permission denied" in message for kind, message in messages)
    assert any(kind == "error" and "Unable to access" in message for kind, message in messages)
