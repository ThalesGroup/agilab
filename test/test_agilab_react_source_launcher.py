from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path


MODULE_PATH = Path("tools/agilab_react_source_launcher.py")
SPEC = importlib.util.spec_from_file_location("agilab_react_source_launcher_test_module", MODULE_PATH)
assert SPEC and SPEC.loader
agilab_react_source_launcher = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = agilab_react_source_launcher
SPEC.loader.exec_module(agilab_react_source_launcher)


def test_build_react_command_enables_ui_extra() -> None:
    root = Path("/repo")

    command = agilab_react_source_launcher.build_react_command(
        root,
        ["--openai-api-key", "your-key", "--apps-path", "src/agilab/apps"],
        "/usr/bin/uv",
    )

    assert command == [
        "/usr/bin/uv",
        "--preview-features",
        "extra-build-dependencies",
        "run",
        "--project",
        "/repo",
        "--extra",
        "ui",
        "python",
        "-m",
        "agilab",
        "--openai-api-key",
        "your-key",
        "--apps-path",
        "src/agilab/apps",
    ]


def test_build_react_command_can_preserve_no_sync_launches() -> None:
    root = Path("/repo")

    command = agilab_react_source_launcher.build_react_command(root, [], "/usr/bin/uv", no_sync=True)

    assert command[:10] == [
        "/usr/bin/uv",
        "--preview-features",
        "extra-build-dependencies",
        "run",
        "--project",
        "/repo",
        "--extra",
        "ui",
        "--no-sync",
        "python",
    ]


def test_child_environment_removes_parent_uv_recursion_controls_but_keeps_no_sync() -> None:
    child_env = agilab_react_source_launcher.build_child_environment(
        {
            "UV_NO_SYNC": "1",
            "UV_RUN_RECURSION_DEPTH": "1",
            "UV_PROJECT_ENVIRONMENT": "/tmp/agilab-dev",
            "VIRTUAL_ENV": "/stale/.venv",
            "IS_SOURCE_ENV": "1",
        }
    )

    assert child_env == {"UV_NO_SYNC": "1", "IS_SOURCE_ENV": "1"}


def test_uv_no_sync_enabled_parses_truthy_values() -> None:
    assert agilab_react_source_launcher.uv_no_sync_enabled({"UV_NO_SYNC": "1"}) is True
    assert agilab_react_source_launcher.uv_no_sync_enabled({"UV_NO_SYNC": "true"}) is True
    assert agilab_react_source_launcher.uv_no_sync_enabled({"UV_NO_SYNC": "0"}) is False
    assert agilab_react_source_launcher.uv_no_sync_enabled({}) is False


def test_parse_args_preserves_native_args_after_launcher_flag() -> None:
    args = agilab_react_source_launcher.parse_args(
        ["--print-command", "--port", "8502", "--no-browser"]
    )

    assert args.print_command is True
    assert args.app_args == ["--port", "8502", "--no-browser"]


def test_resolve_uv_binary_uses_home_fallback(monkeypatch, tmp_path: Path) -> None:
    fallback = tmp_path / ".local" / "bin" / "uv"
    fallback.parent.mkdir(parents=True)
    fallback.write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.setattr(agilab_react_source_launcher.shutil, "which", lambda _name: None)
    monkeypatch.setattr(agilab_react_source_launcher.Path, "home", lambda: tmp_path)

    assert agilab_react_source_launcher.resolve_uv_binary() == str(fallback)


def test_main_print_command_uses_ui_extra(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(agilab_react_source_launcher, "resolve_uv_binary", lambda: "/usr/bin/uv")
    monkeypatch.setattr(agilab_react_source_launcher, "repo_root", lambda: tmp_path)

    assert agilab_react_source_launcher.main(["--print-command", "--port", "8502"]) == 0

    output = capsys.readouterr().out.strip()
    assert "--extra ui" in output
    assert "python -m agilab" in output
    assert "--project " + str(tmp_path) in output
    assert "--port 8502" in output


def test_main_returns_127_when_uv_is_missing(monkeypatch, capsys) -> None:
    monkeypatch.setattr(agilab_react_source_launcher, "resolve_uv_binary", lambda: None)

    assert agilab_react_source_launcher.main([]) == 127

    assert "Unable to locate uv" in capsys.readouterr().err


def test_private_apps_wrapper_launches_native_ui_and_preserves_arguments(tmp_path: Path) -> None:
    checkout = tmp_path / "source checkout"
    apps = tmp_path / "external apps"
    stub_bin = tmp_path / "bin"
    checkout.mkdir()
    apps.mkdir()
    stub_bin.mkdir()
    (checkout / "install.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (checkout / "install.sh").chmod(0o755)
    log = tmp_path / "uv-commands.jsonl"
    stub_uv = stub_bin / "uv"
    stub_uv.write_text(
        "#!" + sys.executable + "\n"
        "import json, os, sys\n"
        "with open(os.environ['AGILAB_TEST_UV_LOG'], 'a', encoding='utf-8') as log:\n"
        "    log.write(json.dumps(sys.argv[1:]) + '\\n')\n",
        encoding="utf-8",
    )
    stub_uv.chmod(0o755)
    # Environment deletion is outside this launcher test; keep it fully isolated.
    (stub_bin / "rm").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (stub_bin / "rm").chmod(0o755)
    view_args = ["--address", "127.0.0.1", "--port", "8537", "--no-browser", "--", "--active-app", "my app"]

    completed = subprocess.run(
        ["bash", str(Path("install_private_apps_and_run.sh").resolve()), *view_args],
        env={
            **os.environ,
            "PATH": str(stub_bin) + os.pathsep + os.environ["PATH"],
            "AGILAB_CHECKOUT": str(checkout),
            "APPS_REPO": str(apps),
            "AGILAB_TEST_UV_LOG": str(log),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    commands = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert commands[-1] == [
        "--preview-features", "extra-build-dependencies", "run", "--extra", "ui",
        "python", "-m", "agilab", *view_args,
    ]
