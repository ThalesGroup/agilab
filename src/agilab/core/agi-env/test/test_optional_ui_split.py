from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

from agi_env._optional_ui import require_python_ui


AGI_ENV_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = next(parent for parent in AGI_ENV_ROOT.parents if (parent / ".git").exists())
AGI_GUI_ROOT = REPO_ROOT / "src/agilab/lib/agi-gui"
AGI_WEB_ROOT = REPO_ROOT / "src/agilab/lib/agi-web"


def _requirement_name(requirement: str) -> str:
    return re.split(r"\s|\[|<|>|=|!|~", requirement, maxsplit=1)[0].lower()


def _project_version(pyproject_path: Path) -> str:
    return tomllib.loads(pyproject_path.read_text())["project"]["version"]


def _requirement_has_lower_bound_at_least(requirement: str, minimum: str) -> bool:
    parsed = Requirement(requirement)
    minimum_version = Version(minimum)
    lower_bound_operators = {">", ">=", "~=", "=="}
    return any(
        specifier.operator in lower_bound_operators
        and Version(specifier.version) >= minimum_version
        for specifier in parsed.specifier
    )


def _requirement_has_upper_bound_below(requirement: str, maximum: str) -> bool:
    parsed = Requirement(requirement)
    maximum_version = Version(maximum)
    upper_bound_operators = {"<", "<="}
    return any(
        specifier.operator in upper_bound_operators
        and Version(specifier.version) <= maximum_version
        for specifier in parsed.specifier
    )


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


def test_agi_env_declares_no_streamlit_or_ui_extra() -> None:
    data = tomllib.loads((AGI_ENV_ROOT / "pyproject.toml").read_text())

    base_dependencies = data["project"]["dependencies"]
    dev_dependencies = data["dependency-groups"]["dev"]

    assert "streamlit" not in {_requirement_name(dependency) for dependency in base_dependencies}
    assert "optional-dependencies" not in data["project"]
    assert "agi-gui" in dev_dependencies


def test_agi_env_resources_are_package_data_not_import_shadow_data_files() -> None:
    data = tomllib.loads((AGI_ENV_ROOT / "pyproject.toml").read_text())
    setuptools_config = data["tool"]["setuptools"]

    assert "data-files" not in setuptools_config
    assert "resources/**/*" in setuptools_config["package-data"]["agi_env"]


def test_agi_gui_declares_native_ui_runtime_without_streamlit() -> None:
    data = tomllib.loads((AGI_GUI_ROOT / "pyproject.toml").read_text())

    dependencies = data["project"]["dependencies"]

    assert f"agi-env=={_project_version(AGI_ENV_ROOT / 'pyproject.toml')}" in dependencies
    names = {_requirement_name(dependency) for dependency in dependencies}
    assert "streamlit" not in names
    assert "streamlit-code-editor" not in names
    native_provider = next(dependency for dependency in dependencies if _requirement_name(dependency) == "agi-web")
    assert _requirement_has_lower_bound_at_least(native_provider, _project_version(AGI_WEB_ROOT / "pyproject.toml"))
    assert _requirement_has_upper_bound_below(native_provider, "2027.0")
    assert "watchdog" in {_requirement_name(dependency) for dependency in dependencies}


def test_agilab_declares_agi_gui_only_for_ui_extra() -> None:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())

    base_dependencies = data["project"]["dependencies"]
    ui_dependencies = data["project"]["optional-dependencies"]["ui"]
    agi_gui_requirement = f"agi-gui=={_project_version(AGI_GUI_ROOT / 'pyproject.toml')}"

    assert agi_gui_requirement not in base_dependencies
    assert agi_gui_requirement in ui_dependencies
    assert all("agi-env[ui]" not in dependency for dependency in base_dependencies + ui_dependencies)


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
def test_ui_modules_explain_optional_extra_when_native_provider_is_missing(module_name: str) -> None:
    result = _run_python(
        f"""
        import importlib
        import importlib.abc
        import sys

        class BlockNativeProvider(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "agi_web" or fullname.startswith("agi_web."):
                    raise ModuleNotFoundError("blocked native UI provider", name="agi_web")
                return None

        sys.meta_path.insert(0, BlockNativeProvider())

        try:
            importlib.import_module({module_name!r})
        except ModuleNotFoundError as exc:
            if "agi-gui" in str(exc):
                raise SystemExit(0)
            raise SystemExit(f"unexpected error: {{exc}}")
        raise SystemExit("expected native UI provider import failure")
        """
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_require_native_ui_reports_ui_extra_for_missing_provider() -> None:
    def missing_provider(name, *args, **kwargs):
        assert name == "agi_web.python_ui"
        raise ModuleNotFoundError("No module named 'agi_web'", name="agi_web")

    with pytest.raises(ModuleNotFoundError, match="agi-gui"):
        require_python_ui(missing_provider)


def test_require_native_ui_preserves_transitive_import_failures() -> None:
    def missing_transitive_dependency(name, *args, **kwargs):
        raise ModuleNotFoundError("No module named 'watchdog'", name="watchdog")

    with pytest.raises(ModuleNotFoundError, match="watchdog"):
        require_python_ui(missing_transitive_dependency)
