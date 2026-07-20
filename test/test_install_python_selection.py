from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_INSTALLER = REPO_ROOT / "install.sh"
CORE_INSTALLER = REPO_ROOT / "src/agilab/core/install.sh"
ENDUSER_INSTALLER = REPO_ROOT / "tools/install_enduser.sh"
REPO_PYTHON_VERSION = REPO_ROOT / ".python-version"


def _extract_shell_function(text: str, name: str) -> str:
    match = re.search(rf"^{name}\(\)" + r".*?^}", text, re.MULTILINE | re.DOTALL)
    assert match, f"{name}() not found"
    return match.group(0)


def test_root_installer_does_not_enable_freethreaded_python_by_default() -> None:
    choose_python_version = _extract_shell_function(
        ROOT_INSTALLER.read_text(encoding="utf-8"), "choose_python_version"
    )

    assert "chosen_python_free=" not in choose_python_version
    assert "AGI_PYTHON_FREE_THREADED=1" not in choose_python_version
    assert "AGI_PYTHON_FREE_THREADED=0" in choose_python_version
    assert "No standard CPython interpreter found" in choose_python_version


def test_installers_repair_incompatible_generated_virtualenvs() -> None:
    root_text = ROOT_INSTALLER.read_text(encoding="utf-8")
    core_text = CORE_INSTALLER.read_text(encoding="utf-8")

    assert "remove_incompatible_project_venv" in root_text
    assert (
        'remove_incompatible_project_venv "$AGI_INSTALL_PATH" "repository root"'
        in root_text
    )
    assert "remove_incompatible_project_venv" in core_text
    for package in ("agi-env", "agi-node", "agi-cluster", "agi-core"):
        assert f'remove_incompatible_project_venv "$PWD" "{package}"' in core_text
    assert 'rm -rf -- "$venv_dir"' in core_text
    assert "abiflags" in core_text


def test_repo_default_python_pin_uses_standard_gil_build() -> None:
    assert REPO_PYTHON_VERSION.read_text(encoding="utf-8").strip() == "3.14+gil"


def test_root_installer_syncs_ui_dependencies_before_root_tests() -> None:
    root_tests = _extract_shell_function(
        ROOT_INSTALLER.read_text(encoding="utf-8"), "run_root_tests"
    )

    sync = '$UV sync -p "${AGI_PYTHON_UV_SPEC:-$AGI_PYTHON_VERSION}" --extra ui'
    run = (
        '$UV run -p "${AGI_PYTHON_UV_SPEC:-$AGI_PYTHON_VERSION}" '
        "--extra ui --no-sync -m pytest src/agilab/test"
    )
    assert sync in root_tests
    assert run in root_tests
    assert root_tests.index(sync) < root_tests.index(run)


def test_core_installer_rejects_freethreaded_python_version_text() -> None:
    core_text = CORE_INSTALLER.read_text(encoding="utf-8")
    normalize = _extract_shell_function(core_text, "normalize_agi_python_version")

    assert "*freethreaded*" in normalize
    assert "python3\\.[0-9]+t" in normalize
    assert "standard GIL Python interpreter" in normalize


def test_enduser_installer_uses_gil_python_for_314_local_source_installs() -> None:
    text = ENDUSER_INSTALLER.read_text(encoding="utf-8")
    python_uv_spec = _extract_shell_function(text, "python_uv_spec_for_version")
    normalize_python = _extract_shell_function(text, "normalize_python_selection")
    completed = subprocess.run(
        [
            "bash",
            "-c",
            f"set -euo pipefail\n{python_uv_spec}\npython_uv_spec_for_version 3.14.6",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout.strip() == "3.14.6+gil"
    normalized = subprocess.run(
        [
            "bash",
            "-c",
            "\n".join(
                [
                    "set -euo pipefail",
                    "RED=''",
                    "NC=''",
                    "AGI_PYTHON_VERSION='3.14.6'",
                    "AGI_PYTHON_UV_SPEC='3.14.6'",
                    python_uv_spec,
                    normalize_python,
                    "normalize_python_selection",
                    "printf '%s\\n' \"$AGI_PYTHON_UV_SPEC\"",
                ]
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert normalized.stdout.strip() == "3.14.6+gil"
    assert "ensure_enduser_venv" in text
    assert "remove_incompatible_enduser_venv" in text
    assert "AGI_PYTHON_FREE_THREADED=0" in text
    assert "freethreaded" in text
    assert 'pip install --python "${VENV}/bin/python"' in text
    assert "bootstrap_enduser_environment" in text
    assert 'python pin "$AGI_PYTHON_UV_SPEC"' in text
    assert 'sync -p "$AGI_PYTHON_UV_SPEC"' in text
    assert "ensurepip --upgrade || true" not in text
    assert 'if ! "${VENV}/bin/python" -m pip list | grep' not in text


def test_enduser_bootstrap_repairs_polluted_metadata_and_guarantees_pip(
    tmp_path: Path,
) -> None:
    text = ENDUSER_INSTALLER.read_text(encoding="utf-8")
    function_names = (
        "python_uv_spec_for_version",
        "normalize_python_selection",
        "remove_incompatible_enduser_venv",
        "ensure_enduser_venv",
        "ensure_enduser_project_python",
        "ensure_enduser_pip",
        "bootstrap_enduser_environment",
    )
    functions = "\n\n".join(
        _extract_shell_function(text, name) for name in function_names
    )
    agi_space = tmp_path / "agi-space"
    agi_space.mkdir()
    project_file = agi_space / "pyproject.toml"
    project_file.write_text(
        "\n".join(
            (
                "[project]",
                'name = "agi-space"',
                'version = "0.1.0"',
                'requires-python = ">=9.99"',
                "dependencies = []",
                "",
            )
        ),
        encoding="utf-8",
    )
    current_version = ".".join(str(part) for part in sys.version_info[:3])
    completed = subprocess.run(
        [
            "bash",
            "-c",
            "\n".join(
                (
                    "set -euo pipefail",
                    "RED=''",
                    "GREEN=''",
                    "BLUE=''",
                    "YELLOW=''",
                    "NC=''",
                    "UV_PREVIEW=(uv --preview-features extra-build-dependencies)",
                    f"AGI_SPACE={str(agi_space)!r}",
                    'VENV="$AGI_SPACE/.venv"',
                    f"AGI_PYTHON_VERSION={current_version!r}",
                    f"AGI_PYTHON_UV_SPEC={current_version!r}",
                    "AGI_PYTHON_FREE_THREADED=0",
                    functions,
                    'cd "$AGI_SPACE"',
                    "bootstrap_enduser_environment",
                )
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "Aligned agi-space requires-python" in completed.stderr
    project = tomllib.loads(project_file.read_text(encoding="utf-8"))["project"]
    assert project["requires-python"] == f">={current_version}"
    pinned = (agi_space / ".python-version").read_text(encoding="utf-8").strip()
    expected_pin = (
        f"{current_version}+gil" if sys.version_info[:2] == (3, 14) else current_version
    )
    assert pinned == expected_pin

    venv_python = agi_space / ".venv" / "bin" / "python"
    version_probe = subprocess.run(
        [
            str(venv_python),
            "-c",
            (
                "import sys; "
                "assert '.'.join(map(str, sys.version_info[:3])) == "
                f"{current_version!r}; "
                "assert getattr(sys, '_is_gil_enabled', lambda: True)()"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert version_probe.returncode == 0
    pip_probe = subprocess.run(
        [str(venv_python), "-m", "pip", "--version"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "pip " in pip_probe.stdout
