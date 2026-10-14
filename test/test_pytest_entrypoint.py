from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap
from types import SimpleNamespace

from tools.testing import pytest_entrypoint


def test_cleaned_environment_removes_only_uv_target_controls() -> None:
    cleaned = pytest_entrypoint.cleaned_test_environment(
        {
            "UV_PROJECT_ENVIRONMENT": "/unsafe/shared-venv",
            "UV_RUN_RECURSION_DEPTH": "1",
            "VIRTUAL_ENV": "/unsafe/active-venv",
            "AGILAB_TEST_SENTINEL": "preserved",
        }
    )

    assert "UV_PROJECT_ENVIRONMENT" not in cleaned
    assert "UV_RUN_RECURSION_DEPTH" not in cleaned
    assert "VIRTUAL_ENV" not in cleaned
    assert cleaned["AGILAB_TEST_SENTINEL"] == "preserved"


def test_main_clears_uv_target_before_pytest_runs(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def _pytest_main(argv):
        seen["argv"] = list(argv)
        seen["environment"] = dict(os.environ)
        return 0

    monkeypatch.setitem(sys.modules, "pytest", SimpleNamespace(main=_pytest_main))
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", "/unsafe/shared-venv")
    monkeypatch.setenv("UV_RUN_RECURSION_DEPTH", "1")
    monkeypatch.setenv("VIRTUAL_ENV", "/unsafe/active-venv")
    monkeypatch.setenv("AGILAB_TEST_SENTINEL", "preserved")

    assert pytest_entrypoint.main(["-q", "test/example.py"]) == 0

    assert seen["argv"] == ["-q", "test/example.py"]
    environment = seen["environment"]
    assert isinstance(environment, dict)
    assert "UV_PROJECT_ENVIRONMENT" not in environment
    assert "UV_RUN_RECURSION_DEPTH" not in environment
    assert "VIRTUAL_ENV" not in environment
    assert environment["AGILAB_TEST_SENTINEL"] == "preserved"


def test_importlib_spawn_uses_test_namespace_in_agilab_named_checkout(tmp_path) -> None:
    repo_root = Path(pytest_entrypoint.__file__).resolve().parents[2]
    checkout = tmp_path / "agilab"
    source_package = checkout / "src" / "agilab"
    source_package.mkdir(parents=True)
    (source_package / "__init__.py").write_text(
        "SOURCE_PACKAGE = True\n", encoding="utf-8"
    )
    test_package = checkout / "test"
    test_package.mkdir()
    shutil.copy2(repo_root / "test" / "__init__.py", test_package / "__init__.py")
    launcher_package = checkout / "tools" / "testing"
    launcher_package.mkdir(parents=True)
    shutil.copy2(
        Path(pytest_entrypoint.__file__), launcher_package / "pytest_entrypoint.py"
    )
    # Recreate the checked-in markers, including a root marker if reintroduced.
    # An empty root marker made importlib collect these as agilab.test.* while
    # spawn imported the distinct src/agilab product package.
    root_marker = repo_root / "__init__.py"
    if root_marker.exists():
        shutil.copy2(root_marker, checkout / "__init__.py")
    (checkout / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\npythonpath = ["src", "."]\n'
        'addopts = ["--import-mode=importlib"]\n',
        encoding="utf-8",
    )
    (test_package / "test_agilab_spawn_namespace.py").write_text(
        textwrap.dedent("""\
            import multiprocessing

            def _report_source_package(queue):
                import agilab
                queue.put((__name__, agilab.SOURCE_PACKAGE))

            def test_spawn_imports_the_collected_test_function():
                context = multiprocessing.get_context("spawn")
                queue = context.Queue()
                worker = context.Process(target=_report_source_package, args=(queue,))
                worker.start()
                try:
                    worker.join(timeout=10)
                    assert not worker.is_alive(), "spawn worker did not finish"
                    assert worker.exitcode == 0
                    assert queue.get(timeout=2) == ("test.test_agilab_spawn_namespace", True)
                finally:
                    if worker.is_alive():
                        worker.terminate()
                        worker.join(timeout=5)
                    queue.close()
                    queue.join_thread()
            """),
        encoding="utf-8",
    )
    for app_name in ("first_project", "second_project"):
        app_tests = source_package / "apps" / "builtin" / app_name / "test"
        app_tests.mkdir(parents=True)
        (app_tests / "test_app_isolation.py").write_text(
            f'APP_MARKER = "{app_name}"\n\n'
            "def test_same_filename_keeps_app_module_isolated():\n"
            f'    assert APP_MARKER == "{app_name}"\n',
            encoding="utf-8",
        )
    env = pytest_entrypoint.cleaned_test_environment()
    # Use the actual launcher bytes from this checkout without adding another
    # checkout's top-level test package to the fixture's import path.
    env["PYTHONPATH"] = os.pathsep.join([str(checkout / "src"), str(checkout)])

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.testing.pytest_entrypoint",
            "-q",
            "test",
            "src/agilab/apps/builtin",
        ],
        cwd=checkout,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "3 passed" in completed.stdout
