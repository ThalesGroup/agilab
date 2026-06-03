from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path("tools/launch_agilab_streamlit.py")
SPEC = importlib.util.spec_from_file_location("launch_agilab_streamlit_test_module", MODULE_PATH)
assert SPEC and SPEC.loader
launch_agilab_streamlit = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = launch_agilab_streamlit
SPEC.loader.exec_module(launch_agilab_streamlit)


def test_build_streamlit_command_enables_ui_extra() -> None:
    root = Path("/repo")

    command = launch_agilab_streamlit.build_streamlit_command(
        root,
        ["--openai-api-key", "your-key", "--apps-path", "src/agilab/apps"],
        "/usr/bin/uv",
    )

    assert command == [
        "/usr/bin/uv",
        "--preview-features",
        "extra-build-dependencies",
        "run",
        "--extra",
        "ui",
        "python",
        "-m",
        "streamlit",
        "run",
        "/repo/src/agilab/main_page.py",
        "--",
        "--openai-api-key",
        "your-key",
        "--apps-path",
        "src/agilab/apps",
    ]


def test_child_environment_removes_parent_uv_sync_controls() -> None:
    child_env = launch_agilab_streamlit.build_child_environment(
        {
            "UV_NO_SYNC": "1",
            "UV_RUN_RECURSION_DEPTH": "1",
            "VIRTUAL_ENV": "/stale/.venv",
            "IS_SOURCE_ENV": "1",
        }
    )

    assert child_env == {"IS_SOURCE_ENV": "1"}


def test_parse_args_preserves_streamlit_args_after_launcher_flag() -> None:
    args = launch_agilab_streamlit.parse_args(
        ["--print-command", "--server.port", "8502", "--browser.gatherUsageStats=false"]
    )

    assert args.print_command is True
    assert args.app_args == ["--server.port", "8502", "--browser.gatherUsageStats=false"]


def test_resolve_uv_binary_uses_home_fallback(monkeypatch, tmp_path: Path) -> None:
    fallback = tmp_path / ".local" / "bin" / "uv"
    fallback.parent.mkdir(parents=True)
    fallback.write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.setattr(launch_agilab_streamlit.shutil, "which", lambda _name: None)
    monkeypatch.setattr(launch_agilab_streamlit.Path, "home", lambda: tmp_path)

    assert launch_agilab_streamlit.resolve_uv_binary() == str(fallback)


def test_main_print_command_uses_ui_extra(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(launch_agilab_streamlit, "resolve_uv_binary", lambda: "/usr/bin/uv")
    monkeypatch.setattr(launch_agilab_streamlit, "repo_root", lambda: tmp_path)

    assert launch_agilab_streamlit.main(["--print-command", "--server.port", "8502"]) == 0

    output = capsys.readouterr().out.strip()
    assert "--extra ui" in output
    assert str(tmp_path / "src" / "agilab" / "main_page.py") in output
    assert "--server.port 8502" in output


def test_main_returns_127_when_uv_is_missing(monkeypatch, capsys) -> None:
    monkeypatch.setattr(launch_agilab_streamlit, "resolve_uv_binary", lambda: None)

    assert launch_agilab_streamlit.main([]) == 127

    assert "Unable to locate uv" in capsys.readouterr().err
