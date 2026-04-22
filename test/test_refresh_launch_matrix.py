from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys


MODULE_PATH = Path("tools/refresh_launch_matrix.py")
SPEC = importlib.util.spec_from_file_location("refresh_launch_matrix_test_module", MODULE_PATH)
assert SPEC and SPEC.loader
refresh_launch_matrix = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = refresh_launch_matrix
SPEC.loader.exec_module(refresh_launch_matrix)


def test_tracked_runconfigs_skips_missing_git_tracked_files(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    runconfig_dir = repo_root / ".idea" / "runConfigurations"
    runconfig_dir.mkdir(parents=True)
    existing = runconfig_dir / "present.xml"
    existing.write_text("<component />", encoding="utf-8")
    missing_rel = Path(".idea/runConfigurations/missing.xml")

    def _fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=f"{existing.relative_to(repo_root)}\n{missing_rel}\n",
        )

    monkeypatch.setattr(refresh_launch_matrix.subprocess, "run", _fake_run)

    files = refresh_launch_matrix.tracked_runconfigs(repo_root, runconfig_dir)

    assert files == [existing]


def test_parse_run_configs_skips_missing_files_from_tracked_list(tmp_path: Path, monkeypatch) -> None:
    runconfig_dir = tmp_path / ".idea" / "runConfigurations"
    runconfig_dir.mkdir(parents=True)
    existing = runconfig_dir / "present.xml"
    existing.write_text(
        """<component name="ProjectRunConfigurationManager">
  <configuration name="demo" type="PythonConfigurationType" factoryName="Python">
    <option name="SCRIPT_NAME" value="demo.py" />
  </configuration>
</component>
""",
        encoding="utf-8",
    )
    missing = runconfig_dir / "missing.xml"

    monkeypatch.setattr(
        refresh_launch_matrix,
        "tracked_runconfigs",
        lambda _repo_root, _rc_dir: [missing, existing],
    )

    rows = refresh_launch_matrix.parse_run_configs(runconfig_dir)

    assert len(rows) == 1
    assert rows[0][1] == "demo"
