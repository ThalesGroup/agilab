from __future__ import annotations

import importlib.util
import re
import shlex
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_NAMES = (
    "agilab-pypi-release-maintenance",
    "agilab-release-verification",
    "agilab-runbook",
)
RETIRED_PUBLISHER_FLAGS = {
    "--cleanup-only",
    "--delete-project",
    "--delete-pypi-release",
    "--purge-before",
    "--purge-after",
}


def _retention_module():
    spec = importlib.util.spec_from_file_location(
        "pypi_cleanup_skill_contract_retention",
        REPO_ROOT / "tools/pypi_release_retention.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _shell_commands(text: str):
    for block in re.findall(r"```(?:bash|sh)\s*\n(.*?)```", text, re.DOTALL):
        for line in block.replace("\\\n", " ").splitlines():
            yield shlex.split(line, comments=True)


@pytest.mark.parametrize("skill_name", SKILL_NAMES)
def test_cleanup_skills_route_to_current_local_procedure(skill_name: str) -> None:
    text = (REPO_ROOT / ".claude/skills" / skill_name / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "docs/pypi-cleanup-maintainer-guide.md" in text
    assert "Publication never runs cleanup" in text
    assert "package==version" in text
    assert "verified" in text and "backup" in text


@pytest.mark.parametrize("skill_name", SKILL_NAMES)
def test_cleanup_skills_do_not_restore_retired_hosted_retention(
    skill_name: str,
) -> None:
    text = (REPO_ROOT / ".claude/skills" / skill_name / "SKILL.md").read_text(
        encoding="utf-8"
    )
    for retired_instruction in (
        "PYPI_RELEASE_PRUNE_",
        "PYPI_CONFIRM_LOGIN_URL",
        "configured cleanup threshold",
        "strict one-release retention",
        "pypi_retention_min_published_releases",
    ):
        assert retired_instruction not in text


@pytest.mark.parametrize("skill_name", SKILL_NAMES)
def test_documented_cleanup_commands_match_current_cli(skill_name: str) -> None:
    text = (REPO_ROOT / ".claude/skills" / skill_name / "SKILL.md").read_text(
        encoding="utf-8"
    )
    module = _retention_module()
    for command in _shell_commands(text):
        if "tools/pypi_publish.py" in command:
            assert not RETIRED_PUBLISHER_FLAGS.intersection(command)
        if "tools/pypi_release_retention.py" not in command:
            continue
        start = command.index("tools/pypi_release_retention.py") + 1
        args = module.parse_args(command[start:])
        assert args.delete_release, "Cleanup examples must name an exact target"
        assert all(target.count("==") == 1 for target in args.delete_release)
        if args.confirm_delete:
            assert args.backup_dir, "Deletion examples must reuse a verified backup"
            assert not args.dry_run


def test_cleanup_skill_documents_plan_backup_and_local_confirmation() -> None:
    text = (
        REPO_ROOT / ".claude/skills/agilab-pypi-release-maintenance/SKILL.md"
    ).read_text(encoding="utf-8")
    module = _retention_module()
    operations = []
    for command in _shell_commands(text):
        if "tools/pypi_release_retention.py" in command:
            args = module.parse_args(
                command[command.index("tools/pypi_release_retention.py") + 1 :]
            )
            operations.append((args.confirm_delete, args.backup_dir is not None))
    assert operations == [(False, False), (False, True), (True, True)]
