"""Regression tests for the installer's minimal+last-session default selection."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = REPO_ROOT / "src/agilab/install_apps.sh"


def _extract_function(name: str) -> str:
    text = INSTALLER.read_text(encoding="utf-8")
    match = re.search(rf"^{name}\(\)" + r".*?^}", text, re.MULTILINE | re.DOTALL)
    assert match, f"{name}() not found in install_apps.sh"
    return match.group(0)


def _run_detection(tmp_path: Path, *, state_toml: str | None, touched: dict[str, str]) -> list[str]:
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir(parents=True, exist_ok=True)
    for app, stamp in touched.items():
        target = apps_dir / app
        target.mkdir()
        subprocess.run(["touch", "-t", stamp, str(target)], check=True)
    state_file = tmp_path / "app_state.toml"
    if state_toml is not None:
        state_file.write_text(state_toml, encoding="utf-8")
    script = tmp_path / "drive.sh"
    script.write_text(
        _extract_function("detect_last_session_apps")
        + "\ndeclare -a LAST_SESSION_APPS=()\n"
        + f'AGILAB_APP_STATE_FILE="{state_file}"\n'
        + f'AGILAB_WORKSPACE_APPS_DIR="{apps_dir}"\n'
        + "detect_last_session_apps\n"
        + 'printf "%s\\n" "${LAST_SESSION_APPS[@]-}"\n',
        encoding="utf-8",
    )
    result = subprocess.run(["bash", str(script)], capture_output=True, text=True, check=True)
    return [line for line in result.stdout.splitlines() if line]


def test_last_session_detection_combines_state_and_recent_workspace(tmp_path: Path) -> None:
    detected = _run_detection(
        tmp_path,
        state_toml='last_active_app = "/x/apps/builtin/mission_decision_project"\n',
        touched={
            "flight_telemetry_project": "202606111000",
            "sat_trajectory_project": "202606110900",
            "old_project": "202601010000",
        },
    )
    assert "mission_decision_project" in detected
    assert "flight_telemetry_project" in detected
    assert "sat_trajectory_project" in detected
    assert "old_project" not in detected


def test_last_session_detection_handles_missing_evidence(tmp_path: Path) -> None:
    detected = _run_detection(tmp_path, state_toml=None, touched={})
    assert detected == []


def test_default_selection_is_minimal_core_plus_last_session() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    assert "MINIMAL_DEFAULT_APPS=(" in text
    assert "minimal_app_project" in text.split("MINIMAL_DEFAULT_APPS=(", 1)[1].split(")", 1)[0]
    assert "detect_last_session_apps" in text
    # The old broad default selection must not silently return.
    assert "sb3_trainer_project" not in text.split("MINIMAL_DEFAULT_APPS=(", 1)[1].split(")", 1)[0]
