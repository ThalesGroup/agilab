from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


INSTALL_APPS_SH = Path(__file__).resolve().parents[1] / "src/agilab/install_apps.sh"


def _extract_function(script_text: str, function_name: str, next_function_name: str) -> str:
    start = script_text.index(f"{function_name}() {{")
    end = script_text.index(f"\n{next_function_name}()", start)
    return script_text[start:end]


def _run_discover_repo_dir(repo_root: Path, name: str) -> str:
    script_text = INSTALL_APPS_SH.read_text(encoding="utf-8")
    function_body = _extract_function(script_text, "discover_repo_dir", "resolve_physical_dir")
    bash_script = f"""#!/usr/bin/env bash
set -euo pipefail
{function_body}
discover_repo_dir "$1" "$2"
"""
    completed = subprocess.run(
        ["bash", "-c", bash_script, "discover_repo_dir_test", str(repo_root), name],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _run_refresh_repository_link(dest: Path, target: Path) -> str:
    script_text = INSTALL_APPS_SH.read_text(encoding="utf-8")
    start = script_text.index("backup_existing_path() {")
    end = script_text.index("\n# Destination base", start)
    function_body = script_text[start:end]
    bash_script = f"""#!/usr/bin/env bash
set -euo pipefail
BLUE=''
YELLOW=''
NC=''
{function_body}
refresh_repository_link App "$1" "$2"
"""
    completed = subprocess.run(
        ["bash", "-c", bash_script, "refresh_repository_link_test", str(dest), str(target)],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


@pytest.mark.parametrize(
    ("name", "direct_child", "nested_child"),
    [
        ("apps", "flight_project", "network_sim_project"),
        ("apps-pages", "home", "legacy"),
    ],
)
def test_discover_repo_dir_prefers_direct_child_over_nested_mirror(
    tmp_path: Path,
    name: str,
    direct_child: str,
    nested_child: str,
) -> None:
    repo_root = tmp_path / "thales_agilab"
    direct_root = repo_root / name
    direct_root.mkdir(parents=True)
    (direct_root / direct_child).mkdir()

    nested_root = (
        repo_root
        / "FCAS"
        / "codex-5.4-xhigh-investigation"
        / "source"
        / "thales_agilab"
        / name
    )
    nested_root.mkdir(parents=True)
    (nested_root / nested_child).mkdir()

    assert Path(_run_discover_repo_dir(repo_root, name)) == direct_root.resolve()


def test_refresh_repository_link_moves_existing_directory_aside(tmp_path: Path) -> None:
    target = tmp_path / "repo" / "apps" / "demo_project"
    target.mkdir(parents=True)
    dest = tmp_path / "install" / "apps" / "demo_project"
    dest.mkdir(parents=True)
    (dest / "local_edit.txt").write_text("local edit\n", encoding="utf-8")

    output = _run_refresh_repository_link(dest, target)

    assert dest.is_symlink()
    assert dest.resolve() == target.resolve()
    backups = sorted(dest.parent.glob("demo_project.previous.*"))
    assert len(backups) == 1
    assert (backups[0] / "local_edit.txt").read_text(encoding="utf-8") == "local edit\n"
    assert "Moved to" in output


def test_refresh_repository_link_recreates_existing_symlink(tmp_path: Path) -> None:
    old_target = tmp_path / "repo" / "old" / "demo_project"
    new_target = tmp_path / "repo" / "new" / "demo_project"
    old_target.mkdir(parents=True)
    new_target.mkdir(parents=True)
    dest = tmp_path / "install" / "apps" / "demo_project"
    dest.parent.mkdir(parents=True)
    dest.symlink_to(old_target, target_is_directory=True)

    _run_refresh_repository_link(dest, new_target)

    assert dest.is_symlink()
    assert dest.resolve() == new_target.resolve()
