import logging
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import agi_env.process_support as process_support


def test_parse_level_recognizes_common_patterns():
    assert process_support.parse_level("12:34:56 INFO booting", logging.WARNING) == logging.INFO
    assert process_support.parse_level("level=error details", logging.INFO) == logging.ERROR
    assert process_support.parse_level("level=debug details", logging.INFO) == logging.DEBUG
    assert process_support.parse_level("plain text", logging.WARNING) == logging.WARNING


def test_strip_time_level_prefix_and_packaging_detection():
    assert process_support.strip_time_level_prefix("12:34:56 INFO started") == "started"
    assert process_support.strip_time_level_prefix("12:34:56,123 WARNING: be careful") == "be careful"
    assert process_support.is_packaging_cmd("uv pip install agilab") is True
    assert process_support.is_packaging_cmd("python -m pytest") is False


def test_normalize_path_and_windows_drive_fix(monkeypatch):
    assert process_support.normalize_path("relative/path") == "relative/path"
    assert process_support.normalize_path("") == "."

    monkeypatch.setattr(process_support.os, "name", "nt", raising=False)
    assert process_support.fix_windows_drive(r"C:Users\\agi") == r"C:\Users\\agi"
    assert process_support.fix_windows_drive(r"C:\\Users\\agi") == r"C:\\Users\\agi"


def test_fix_windows_drive_handles_regex_failure(monkeypatch):
    monkeypatch.setattr(process_support.os, "name", "nt", raising=False)
    fake_re = SimpleNamespace(match=lambda *_args, **_kwargs: (_ for _ in ()).throw(re.error("boom")))
    monkeypatch.setattr(process_support, "re", fake_re, raising=False)

    assert process_support.fix_windows_drive(r"C:Users\\agi") == r"C:Users\\agi"


def test_fix_windows_drive_returns_non_string_inputs_unchanged(monkeypatch):
    monkeypatch.setattr(process_support.os, "name", "nt", raising=False)
    marker = object()
    assert process_support.fix_windows_drive(marker) is marker


def test_normalize_path_windows_resolve_fallback(monkeypatch):
    original_os_name = os.name
    original_resolve = Path.resolve
    posix_path_cls = type(Path("/tmp"))
    monkeypatch.setattr(process_support.os, "name", "nt", raising=False)

    def _patched_resolve(self, *args, **kwargs):
        if self == posix_path_cls("demo"):
            raise OSError("boom")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", _patched_resolve, raising=False)
    assert process_support.normalize_path("demo").endswith("demo")
    monkeypatch.setattr(process_support.os, "name", original_os_name, raising=False)
    monkeypatch.setattr(Path, "resolve", original_resolve, raising=False)


def test_normalize_path_windows_unsupported_operation_fallback(monkeypatch):
    monkeypatch.setattr(process_support.os, "name", "nt", raising=False)

    def _patched_resolve(self, *args, **kwargs):
        raise process_support.UnsupportedOperation("windows path unsupported on host")

    monkeypatch.setattr(Path, "resolve", _patched_resolve, raising=False)

    assert process_support.normalize_path("demo").endswith("demo")


def test_normalize_path_windows_propagates_unexpected_runtime_bug(monkeypatch):
    monkeypatch.setattr(process_support.os, "name", "nt", raising=False)

    def _patched_resolve(self, *args, **kwargs):
        raise RuntimeError("resolve bug")

    monkeypatch.setattr(Path, "resolve", _patched_resolve, raising=False)

    with pytest.raises(RuntimeError, match="resolve bug"):
        process_support.normalize_path("demo")


def test_build_subprocess_env_strips_uv_run_recursion_depth(tmp_path: Path):
    base_env = {
        "UV_RUN_RECURSION_DEPTH": "1",
        "PYTHONPATH": "/tmp/demo",
        "PYTHONHOME": "/tmp/home",
        "PATH": "/usr/bin",
    }
    venv_dir = tmp_path / ".venv"
    (venv_dir / "bin").mkdir(parents=True)
    foreign_source = tmp_path / "foreign-source"
    foreign_source.mkdir()

    env = process_support.build_subprocess_env(
        base_env=base_env,
        venv=tmp_path,
        pythonpath_entries=[str(foreign_source)],
        sys_prefix=sys.prefix,
    )

    assert env.get("VIRTUAL_ENV") == str(tmp_path / ".venv")
    assert "UV_RUN_RECURSION_DEPTH" not in env
    assert "PYTHONPATH" not in env
    assert "PYTHONHOME" not in env


def test_build_subprocess_env_keeps_pythonpath_entries_for_staging_dir(tmp_path: Path):
    class_entries = [str(tmp_path / "alpha"), str(tmp_path / "beta")]
    base_env = {
        "PYTHONPATH": "/tmp/ignored",
        "PYTHONHOME": "/tmp/home",
        "PATH": "/usr/bin",
    }

    env = process_support.build_subprocess_env(
        base_env=base_env,
        venv=tmp_path,
        pythonpath_entries=class_entries,
        sys_prefix=sys.prefix,
    )

    assert env["VIRTUAL_ENV"] == str(tmp_path / ".venv")
    assert env["PYTHONPATH"] == os.pathsep.join(class_entries)
    assert "PYTHONHOME" not in env


def test_build_subprocess_env_uses_pythonpath_entries_without_venv(tmp_path: Path):
    class_entries = [str(tmp_path / "alpha"), str(tmp_path / "beta")]
    base_env = {
        "UV_RUN_RECURSION_DEPTH": "3",
        "PYTHONPATH": "/tmp/ignored",
        "PYTHONHOME": "/tmp/home",
    }

    env = process_support.build_subprocess_env(
        base_env=base_env,
        pythonpath_entries=class_entries,
        sys_prefix=sys.prefix,
    )

    assert "VIRTUAL_ENV" not in env
    assert env["PYTHONPATH"] == os.pathsep.join(class_entries)
    assert "PYTHONHOME" not in env
    assert "UV_RUN_RECURSION_DEPTH" not in env


def test_build_subprocess_env_keeps_pythonpath_entries_for_current_venv(tmp_path: Path):
    current_venv = Path(sys.prefix).resolve()
    instance_entries = [str(tmp_path / "src-one"), str(tmp_path / "src-two")]
    base_env = {
        "PYTHONPATH": "/tmp/ignored",
        "PYTHONHOME": "/tmp/home",
        "PATH": "/usr/bin",
    }

    env = process_support.build_subprocess_env(
        base_env=base_env,
        venv=current_venv,
        pythonpath_entries=instance_entries,
        sys_prefix=current_venv,
    )

    assert env["VIRTUAL_ENV"] == str(current_venv)
    assert env["PATH"].split(os.pathsep)[0] == str(current_venv / "bin")
    assert env["PYTHONPATH"] == os.pathsep.join(instance_entries)
    assert "PYTHONHOME" not in env


def test_last_non_empty_output_line_skips_blank_entries():
    lines = [None, "   ", "\n", " useful detail  "]

    assert process_support.last_non_empty_output_line(lines) == "useful detail"


def test_last_non_empty_output_line_returns_none_for_empty_input():
    assert process_support.last_non_empty_output_line([None, "", "   "]) is None


def test_format_command_failure_message_falls_back_to_command_and_appends_hint():
    message = process_support.format_command_failure_message(
        7,
        "demo command",
        lines=[None, "", "   "],
        diagnostic_hint="check worker manifest",
    )

    assert message == "Command failed with exit code 7: demo command\ncheck worker manifest"


def test_format_command_failure_message_uses_last_detail_and_strips_error_prefix():
    message = process_support.format_command_failure_message(
        3,
        "demo command",
        lines=["noise", "ValueError: useful detail"],
        diagnostic_hint=None,
    )

    assert message == "Command failed with exit code 3: useful detail"


def test_command_failure_hint_detects_networked_pip_errors():
    hint = process_support.command_failure_hint(
        "pip install demo",
        ["Failed to establish a new connection while reaching index"],
    )

    assert "network access is required" in hint
    assert process_support.command_failure_hint("python -m pytest", ["Failed to establish a new connection"]) is None
    assert process_support.command_failure_hint("pip install demo", ["normal failure"]) is None


def test_inject_uv_preview_flag_and_apply_inline_path_export(monkeypatch):
    assert process_support.inject_uv_preview_flag("uv pip install demo").startswith(
        "uv --preview-features extra-build-dependencies "
    )
    assert process_support.inject_uv_preview_flag("python -m pytest") == "python -m pytest"

    env = {"PATH": "/usr/bin"}
    monkeypatch.setenv("PATH", "/usr/local/bin")
    cmd = process_support.apply_inline_path_export('export PATH="~/.local/bin:$PATH"; uv self update', env)

    assert cmd == "uv self update"
    assert env["PATH"].startswith(str(Path("~/.local/bin").expanduser()))
    assert "/usr/bin" in env["PATH"]


def test_apply_inline_path_export_returns_input_for_non_string_or_non_matching_commands():
    env = {"PATH": "/usr/bin"}

    marker = object()
    assert process_support.apply_inline_path_export(marker, env) is marker
    assert process_support.apply_inline_path_export("uv self update", env) == "uv self update"


def test_inject_uv_preview_flag_handles_regex_failure(monkeypatch):
    monkeypatch.setattr(
        process_support.re,
        "sub",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(re.error("regex failure")),
    )

    assert process_support.inject_uv_preview_flag("uv pip install demo") == "uv pip install demo"


def test_inject_uv_preview_flag_propagates_unexpected_runtime_bug(monkeypatch):
    monkeypatch.setattr(
        process_support.re,
        "sub",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("regex bug")),
    )

    with pytest.raises(RuntimeError, match="regex bug"):
        process_support.inject_uv_preview_flag("uv pip install demo")


def test_apply_inline_path_export_handles_operational_failure(monkeypatch):
    monkeypatch.setattr(
        process_support.os.path,
        "expanduser",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("expanduser failed")),
    )

    env = {"PATH": "/usr/bin"}
    cmd = 'export PATH="~/.local/bin:$PATH"; uv self update'

    assert process_support.apply_inline_path_export(cmd, env) == cmd
    assert env["PATH"] == "/usr/bin"


def test_apply_inline_path_export_propagates_unexpected_runtime_bug(monkeypatch):
    monkeypatch.setattr(
        process_support.os.path,
        "expanduser",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("expanduser bug")),
    )

    with pytest.raises(RuntimeError, match="expanduser bug"):
        process_support.apply_inline_path_export(
            'export PATH="~/.local/bin:$PATH"; uv self update',
            {"PATH": "/usr/bin"},
        )
