from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "builtin_app_tests.py"

spec = importlib.util.spec_from_file_location("builtin_app_tests", MODULE_PATH)
assert spec is not None and spec.loader is not None
builtin_app_tests = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builtin_app_tests)


def test_discover_builtin_app_tests_returns_sorted_projects_with_tests(tmp_path):
    root = tmp_path / "builtin"
    (root / "z_project" / "test").mkdir(parents=True)
    (root / "z_project" / "test" / "test_z.py").write_text("def test_z(): pass\n")
    (root / "a_project" / "test").mkdir(parents=True)
    (root / "a_project" / "test" / "test_a.py").write_text("def test_a(): pass\n")
    (root / "empty_project" / "test").mkdir(parents=True)
    (root / "not_a_builtin_app" / "test").mkdir(parents=True)
    (root / "not_a_builtin_app" / "test" / "test_skip.py").write_text("def test_skip(): pass\n")

    targets = builtin_app_tests.discover_builtin_app_tests(root)

    assert [target.name for target in targets] == ["a_project", "z_project"]


def test_build_pytest_command_uses_app_local_project_and_importlib_mode():
    command = builtin_app_tests.build_pytest_command()

    assert command[:8] == [
        "uv",
        "--preview-features",
        "extra-build-dependencies",
        "run",
        "--project",
        ".",
        "--with",
        "pytest",
    ]
    assert "--import-mode=importlib" in command
    assert command[-1] == "test"


def test_build_pytest_command_keeps_forwarded_args_after_separator():
    command = builtin_app_tests.build_pytest_command(["--", "-k", "weather"])

    assert command[-2:] == ["-k", "weather"]


def test_subprocess_env_removes_active_root_virtualenv(monkeypatch):
    monkeypatch.setenv("VIRTUAL_ENV", "/repo/.venv")

    env = builtin_app_tests.subprocess_env()

    assert "VIRTUAL_ENV" not in env
