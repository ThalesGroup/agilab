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


def _write_page_project(page_dir: Path, *, entrypoint: bool = True, source: bool = True) -> None:
    page_dir.mkdir(parents=True)
    pyproject_lines = [
        "[project]",
        f'name = "{page_dir.name.replace("_", "-")}"',
        'version = "0.1.0"',
        'requires-python = ">=3.11"',
    ]
    if entrypoint:
        pyproject_lines.extend(
            [
                "",
                '[project.entry-points."agilab.pages"]',
                f'{page_dir.name} = "{page_dir.name}:bundle_root"',
            ]
        )
    (page_dir / "pyproject.toml").write_text("\n".join(pyproject_lines) + "\n", encoding="utf-8")

    if source:
        source_dir = page_dir / "src" / page_dir.name
        source_dir.mkdir(parents=True)
        (source_dir / f"{page_dir.name}.py").write_text("def render():\n    return None\n", encoding="utf-8")


def _run_discover_page_projects(pages_root: Path) -> list[str]:
    script_text = INSTALL_APPS_SH.read_text(encoding="utf-8")
    function_body = _extract_function(script_text, "page_has_required_sources", "app_has_collectable_pytests")
    bash_script = f"""#!/usr/bin/env bash
set -euo pipefail
{function_body}
declare -a pages=()
while IFS= read -r -d '' dir; do
  dir_name="$(basename -- "$dir")"
  if page_has_required_sources "$dir"; then
    pages+=("$dir_name")
  fi
done < <(find "$1" -mindepth 1 -maxdepth 1 -type d -print0)
if (( ${{#pages[@]}} )); then
  printf '%s\n' "${{pages[@]}}"
fi
"""
    completed = subprocess.run(
        ["bash", "-c", bash_script, "page_discovery_test", str(pages_root)],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.splitlines()


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


def _run_validate_apps_repository_policy(
    repo_root: Path,
    *,
    strict: bool,
    allowlist: str = "",
    allow_floating: bool = False,
) -> subprocess.CompletedProcess[str]:
    script_text = INSTALL_APPS_SH.read_text(encoding="utf-8")
    start = script_text.index("parse_list_to_array() {")
    end = script_text.index("\n# Detect whether", start)
    function_body = script_text[start:end]
    bash_script = f"""#!/usr/bin/env bash
set -euo pipefail
RED=''
YELLOW=''
BLUE=''
NC=''
{function_body}
validate_apps_repository_policy "$1"
"""
    env = {
        "AGILAB_STRICT_APPS_REPOSITORY": "1" if strict else "0",
        "AGILAB_APPS_REPOSITORY_ALLOWLIST": allowlist,
        "AGILAB_ALLOW_FLOATING_APPS_REPOSITORY": "1" if allow_floating else "0",
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin",
    }
    return subprocess.run(
        ["bash", "-c", bash_script, "validate_apps_repository_policy_test", str(repo_root)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_page_discovery_keeps_only_installable_entrypoint_projects(tmp_path: Path) -> None:
    pages_root = tmp_path / "apps-pages"
    _write_page_project(pages_root / "view_demo")
    _write_page_project(pages_root / "__pycache__")
    _write_page_project(pages_root / "view_demo.previous.20260513010101")
    _write_page_project(pages_root / "templates")
    _write_page_project(pages_root / "view_legacy", entrypoint=False)
    (pages_root / "view_notes").mkdir(parents=True)

    assert _run_discover_page_projects(pages_root) == ["view_demo"]


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


def test_validate_apps_repository_policy_rejects_floating_branch_in_strict_mode(tmp_path: Path) -> None:
    repo_root = tmp_path / "apps_repo"
    repo_root.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_root, check=True, capture_output=True, text=True)

    result = _run_validate_apps_repository_policy(
        repo_root,
        strict=True,
        allowlist=str(repo_root.resolve()),
    )

    assert result.returncode == 1
    assert "floating branch" in result.stderr


def test_validate_apps_repository_policy_requires_allowlist_in_strict_mode(tmp_path: Path) -> None:
    repo_root = tmp_path / "apps_repo"
    repo_root.mkdir()

    result = _run_validate_apps_repository_policy(repo_root, strict=True)

    assert result.returncode == 1
    assert "AGILAB_APPS_REPOSITORY_ALLOWLIST" in result.stderr
