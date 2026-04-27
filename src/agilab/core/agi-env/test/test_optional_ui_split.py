from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
import tomllib
from pathlib import Path

import pytest

from agi_env._optional_ui import require_streamlit


AGI_ENV_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = next(parent for parent in AGI_ENV_ROOT.parents if (parent / ".git").exists())


def _requirement_name(requirement: str) -> str:
    return re.split(r"\s|\[|<|>|=|!|~", requirement, maxsplit=1)[0].lower()


def _run_python(script: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    package_src = str(AGI_ENV_ROOT / "src")
    pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = package_src if not pythonpath else os.pathsep.join([package_src, pythonpath])

    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_agi_env_declares_streamlit_only_as_ui_extra() -> None:
    data = tomllib.loads((AGI_ENV_ROOT / "pyproject.toml").read_text())

    base_dependencies = data["project"]["dependencies"]
    optional_ui = data["project"]["optional-dependencies"]["ui"]
    dev_dependencies = data["dependency-groups"]["dev"]

    assert "streamlit" not in {_requirement_name(dependency) for dependency in base_dependencies}
    assert any(
        _requirement_name(dependency) == "streamlit" and ">=1.55.0" in dependency for dependency in optional_ui
    )
    assert "agi-env[ui]" in dev_dependencies


def test_agilab_declares_agi_env_ui_extra_for_full_ui_runtime() -> None:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())

    assert "agi-env[ui]==2026.4.27.post2" in data["project"]["dependencies"]


def test_headless_import_does_not_require_streamlit() -> None:
    result = _run_python(
        """
        import builtins

        real_import = builtins.__import__

        def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "streamlit" or name.startswith("streamlit."):
                raise ModuleNotFoundError("blocked streamlit", name="streamlit")
            return real_import(name, globals, locals, fromlist, level)

        builtins.__import__ = blocked_import

        import agi_env

        assert hasattr(agi_env, "AgiEnv")
        """
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("module_name", ["agi_env.pagelib", "agi_env.streamlit_args"])
def test_ui_modules_explain_optional_extra_when_streamlit_is_missing(module_name: str) -> None:
    result = _run_python(
        f"""
        import builtins
        import importlib

        real_import = builtins.__import__

        def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "streamlit" or name.startswith("streamlit."):
                raise ModuleNotFoundError("blocked streamlit", name="streamlit")
            return real_import(name, globals, locals, fromlist, level)

        builtins.__import__ = blocked_import

        try:
            importlib.import_module({module_name!r})
        except ModuleNotFoundError as exc:
            if "agi-env[ui]" in str(exc):
                raise SystemExit(0)
            raise SystemExit(f"unexpected error: {{exc}}")
        raise SystemExit("expected Streamlit import failure")
        """
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_require_streamlit_reports_ui_extra_for_missing_streamlit() -> None:
    def missing_streamlit(name, *args, **kwargs):
        raise ModuleNotFoundError("No module named 'streamlit'", name="streamlit")

    with pytest.raises(ModuleNotFoundError, match=r"agi-env\[ui\]"):
        require_streamlit(missing_streamlit)


def test_require_streamlit_preserves_transitive_import_failures() -> None:
    def missing_transitive_dependency(name, *args, **kwargs):
        raise ModuleNotFoundError("No module named 'watchdog'", name="watchdog")

    with pytest.raises(ModuleNotFoundError, match="watchdog"):
        require_streamlit(missing_transitive_dependency)
