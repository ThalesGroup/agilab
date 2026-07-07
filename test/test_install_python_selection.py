from __future__ import annotations

import re
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_INSTALLER = REPO_ROOT / "install.sh"
CORE_INSTALLER = REPO_ROOT / "src/agilab/core/install.sh"
ENDUSER_INSTALLER = REPO_ROOT / "tools/install_enduser.sh"


def _extract_shell_function(text: str, name: str) -> str:
    match = re.search(rf"^{name}\(\)" + r".*?^}", text, re.MULTILINE | re.DOTALL)
    assert match, f"{name}() not found"
    return match.group(0)


def test_root_installer_does_not_enable_freethreaded_python_by_default() -> None:
    choose_python_version = _extract_shell_function(ROOT_INSTALLER.read_text(encoding="utf-8"), "choose_python_version")

    assert "chosen_python_free=" not in choose_python_version
    assert "AGI_PYTHON_FREE_THREADED=1" not in choose_python_version
    assert "AGI_PYTHON_FREE_THREADED=0" in choose_python_version
    assert "No standard CPython interpreter found" in choose_python_version


def test_installers_repair_incompatible_generated_virtualenvs() -> None:
    root_text = ROOT_INSTALLER.read_text(encoding="utf-8")
    core_text = CORE_INSTALLER.read_text(encoding="utf-8")

    assert "remove_incompatible_project_venv" in root_text
    assert 'remove_incompatible_project_venv "$AGI_INSTALL_PATH" "repository root"' in root_text
    assert "remove_incompatible_project_venv" in core_text
    for package in ("agi-env", "agi-node", "agi-cluster", "agi-core"):
        assert f'remove_incompatible_project_venv "$PWD" "{package}"' in core_text
    assert 'rm -rf -- "$venv_dir"' in core_text
    assert "abiflags" in core_text


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
        ["bash", "-c", f"set -euo pipefail\n{python_uv_spec}\npython_uv_spec_for_version 3.14.6"],
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
    assert 'ensure_enduser_venv' in text
    assert 'remove_incompatible_enduser_venv' in text
    assert 'AGI_PYTHON_FREE_THREADED=0' in text
    assert 'freethreaded' in text
    assert 'pip install --python "${VENV}/bin/python"' in text
