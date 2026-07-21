from __future__ import annotations

import re
import shlex
import subprocess
import sys
import tomllib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_INSTALLER = REPO_ROOT / "install.sh"
WINDOWS_INSTALLER = REPO_ROOT / "install.ps1"
CORE_INSTALLER = REPO_ROOT / "src/agilab/core/install.sh"
ENDUSER_INSTALLER = REPO_ROOT / "tools/install_enduser.sh"
APPS_INSTALLER = REPO_ROOT / "src/agilab/install_apps.sh"
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
    assert REPO_PYTHON_VERSION.read_text(encoding="utf-8").strip() == "3.13"


def test_windows_installer_default_follows_repo_python_pin() -> None:
    text = WINDOWS_INSTALLER.read_text(encoding="utf-8")

    assert 'Join-Path $CurrentPath ".python-version"' in text
    assert "$defaultPython = Get-RepoPythonDefault" in text
    assert 'Read-Host "Enter Python major version [$defaultPython]"' in text
    assert '$requested = $defaultPython' in text


def test_installers_read_validated_repo_python_default(tmp_path: Path) -> None:
    pin = tmp_path / ".python-version"
    pin.write_text("3.12.9\n", encoding="utf-8")

    for installer in (ROOT_INSTALLER, ENDUSER_INSTALLER):
        function = _extract_shell_function(
            installer.read_text(encoding="utf-8"),
            "repo_python_default",
        )
        completed = subprocess.run(
            [
                "bash",
                "-c",
                "\n".join(
                    (
                        "set -euo pipefail",
                        "RED=''",
                        "NC=''",
                        function,
                        f"repo_python_default {shlex.quote(str(pin))}",
                    )
                ),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        assert completed.stdout.strip() == "3.12.9"

        fallback = subprocess.run(
            [
                "bash",
                "-c",
                "\n".join(
                    (
                        "set -euo pipefail",
                        "RED=''",
                        "NC=''",
                        function,
                        f"repo_python_default {shlex.quote(str(tmp_path / 'missing'))}",
                    )
                ),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        assert fallback.stdout.strip() == "3.13"


def test_installers_reject_malformed_repo_python_default(tmp_path: Path) -> None:
    pin = tmp_path / ".python-version"
    pin.write_text("python-latest\n", encoding="utf-8")

    for installer in (ROOT_INSTALLER, ENDUSER_INSTALLER):
        function = _extract_shell_function(
            installer.read_text(encoding="utf-8"),
            "repo_python_default",
        )
        completed = subprocess.run(
            [
                "bash",
                "-c",
                "\n".join(
                    (
                        "set -euo pipefail",
                        "RED=''",
                        "NC=''",
                        function,
                        f"repo_python_default {shlex.quote(str(pin))}",
                    )
                ),
            ],
            capture_output=True,
            text=True,
        )
        assert completed.returncode != 0
        assert "Invalid repository Python pin" in completed.stderr


def test_standalone_app_installer_uses_repo_python_default(tmp_path: Path) -> None:
    pin = tmp_path / ".python-version"
    pin.write_text("3.12.8\n", encoding="utf-8")
    text = APPS_INSTALLER.read_text(encoding="utf-8")
    repo_default = _extract_shell_function(text, "repo_python_default")
    normalize = _extract_shell_function(text, "normalize_agi_python_version")
    completed = subprocess.run(
        [
            "bash",
            "-c",
            "\n".join(
                (
                    "set -euo pipefail",
                    "RED=''",
                    "NC=''",
                    repo_default,
                    f"repo_python_default {shlex.quote(str(pin))}",
                )
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.stdout.strip() == "3.12.8"
    assert '${AGI_PYTHON_VERSION:-3.14}' not in text
    assert 'cpython-[0-9]+\\.[0-9]+' in normalize


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
    selector_version = _extract_shell_function(text, "python_selector_version")
    validate_selector = _extract_shell_function(text, "validate_python_selector")
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
                    selector_version,
                    validate_selector,
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


def test_enduser_default_follows_repo_pin_and_mismatch_fails_fast(
    tmp_path: Path,
) -> None:
    pin = tmp_path / ".python-version"
    pin.write_text("3.13\n", encoding="utf-8")
    text = ENDUSER_INSTALLER.read_text(encoding="utf-8")
    functions = "\n\n".join(
        _extract_shell_function(text, name)
        for name in (
            "repo_python_default",
            "python_uv_spec_for_version",
            "python_selector_version",
            "validate_python_selector",
            "normalize_python_selection",
        )
    )
    common = (
        "set -euo pipefail",
        "RED=''",
        "NC=''",
        f"REPO_ROOT={shlex.quote(str(tmp_path))}",
        "unset AGI_PYTHON_VERSION AGI_PYTHON_UV_SPEC AGI_PYTHON_FREE_THREADED || true",
        functions,
    )
    defaulted = subprocess.run(
        [
            "bash",
            "-c",
            "\n".join(
                (
                    *common,
                    "normalize_python_selection",
                    'printf "%s|%s\\n" "$AGI_PYTHON_VERSION" "$AGI_PYTHON_UV_SPEC"',
                )
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert defaulted.stdout.strip() == "3.13|3.13"

    mismatched = subprocess.run(
        [
            "bash",
            "-c",
            "\n".join(
                (
                    *common,
                    "AGI_PYTHON_VERSION=3.13",
                    "AGI_PYTHON_UV_SPEC=3.14+gil",
                    "normalize_python_selection",
                    "printf 'must-not-run\\n'",
                )
            ),
        ],
        capture_output=True,
        text=True,
    )
    assert mismatched.returncode != 0
    assert "selects Python 3.14" in mismatched.stderr
    assert "must-not-run" not in mismatched.stdout

    freethreaded_selector = subprocess.run(
        [
            "bash",
            "-c",
            "\n".join(
                (
                    *common,
                    "AGI_PYTHON_VERSION=3.13",
                    "AGI_PYTHON_UV_SPEC=cpython-3.13.9t-windows-x86_64-none",
                    "normalize_python_selection",
                    "printf 'must-not-run\\n'",
                )
            ),
        ],
        capture_output=True,
        text=True,
    )
    assert freethreaded_selector.returncode != 0
    assert "standard GIL Python interpreter" in freethreaded_selector.stderr
    assert "must-not-run" not in freethreaded_selector.stdout

    first_normalize = text.index(
        "# Validate the interpreter contract before any existing venv can be removed."
    )
    assert first_normalize < text.index("rm -fr .venv uv.lock")


def test_enduser_bootstrap_repairs_polluted_metadata_and_guarantees_pip(
    tmp_path: Path,
) -> None:
    text = ENDUSER_INSTALLER.read_text(encoding="utf-8")
    function_names = (
        "python_uv_spec_for_version",
        "python_selector_version",
        "validate_python_selector",
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
