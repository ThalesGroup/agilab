from __future__ import annotations

import importlib.util
import sys
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

    assert command[:10] == [
        "uv",
        "--no-cache",
        "--preview-features",
        "extra-build-dependencies",
        "run",
        "--project",
        ".",
        "--with",
        "pytest",
        "--with",
    ]
    assert "pytest-asyncio" in command
    assert "--import-mode=importlib" in command
    assert command[-1] == "test"


def test_build_pytest_command_keeps_forwarded_args_after_separator():
    command = builtin_app_tests.build_pytest_command(["--", "-k", "weather"])

    assert command[-2:] == ["-k", "weather"]


def test_subprocess_env_uses_isolated_app_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("VIRTUAL_ENV", "/repo/.venv")
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", "/repo/.venv-dev")
    monkeypatch.setenv("UV_PYTHON", "/polluted/project/.venv/bin/python")
    monkeypatch.setenv("UV_RUN_RECURSION_DEPTH", "1")
    monkeypatch.setenv("AGILAB_BUILTIN_APP_TEST_ENV_ROOT", str(tmp_path / "app-envs"))
    target = builtin_app_tests.BuiltinAppTestTarget(
        name="execution_pandas_project",
        path=tmp_path / "execution_pandas_project",
    )

    env = builtin_app_tests.subprocess_env(target)

    assert "VIRTUAL_ENV" not in env
    assert "UV_RUN_RECURSION_DEPTH" not in env
    assert env["UV_PROJECT_ENVIRONMENT"] == str(tmp_path / "app-envs" / target.name)
    assert env["UV_PYTHON"] == sys.executable


def test_app_test_env_root_uses_temporary_directory_by_default(monkeypatch):
    monkeypatch.delenv("AGILAB_BUILTIN_APP_TEST_ENV_ROOT", raising=False)

    with builtin_app_tests.app_test_env_root() as env_root:
        assert env_root.name.startswith("agilab-builtin-app-tests-")
        assert env_root.exists()

    assert not env_root.exists()
