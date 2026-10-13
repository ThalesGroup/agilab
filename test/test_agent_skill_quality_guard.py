from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


MODULE_PATH = Path("tools/agent_skill_quality_guard.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("agent_skill_quality_guard_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_skill(root: Path, name: str, body: str) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"""---
name: {name}
description: Demo skill.
license: BSD-3-Clause
---

{body}
""",
        encoding="utf-8",
    )
    return skill_dir


def test_scan_skill_flags_broken_internal_link_and_root_readme(tmp_path: Path) -> None:
    module = _load_module()
    skill_dir = _write_skill(tmp_path, "broken", "Read [missing](references/missing.md).")
    (skill_dir / "README.md").write_text("Human-only duplicate.", encoding="utf-8")

    findings = module.scan_skill(skill_dir)
    rules = {finding.rule for finding in findings}

    assert "broken-internal-link" in rules
    assert "nonstandard-root-file" in rules
    assert any(finding.severity == "high" for finding in findings)


@pytest.mark.parametrize(
    "recipe",
    [
        "uv run --extra ui streamlit run src/agilab/main_page.py",
        "streamlit.testing.v1.AppTest.from_file('page.py')",
    ],
)
def test_scan_agilab_skill_rejects_retired_ui_recipes(tmp_path: Path, recipe: str) -> None:
    module = _load_module()
    skill_dir = _write_skill(tmp_path, "agilab-runbook", recipe)

    findings = module.scan_skill(skill_dir)

    assert any(
        finding.rule == "retired-agilab-ui-recipe" and finding.severity == "high"
        for finding in findings
    )


def test_scan_skill_accepts_native_ui_and_compatibility_names(tmp_path: Path) -> None:
    module = _load_module()
    skill_dir = _write_skill(
        tmp_path,
        "agilab-streamlit-pages",
        "Use agi_web.python_ui and agi_web.testing.AppTest.\n"
        "Run python -m agi_web.react_python_host page.py --address 127.0.0.1.\n"
        "Keep agi_env.streamlit_args; external Streamlit projects may use streamlit skills --global.\n",
    )

    assert module.scan_skill(skill_dir) == []


def test_scan_skill_keeps_external_streamlit_recipes_outside_agilab_scope(tmp_path: Path) -> None:
    module = _load_module()
    skill_dir = _write_skill(tmp_path, "external-framework", "Run streamlit run app.py.")

    assert module.scan_skill(skill_dir) == []


def test_evidence_skill_requires_existing_local_command_targets(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    skill_dir = _write_skill(
        tmp_path / ".claude" / "skills",
        "agilab-evidence-contracts",
        "uv run python tools/release_proof_check.py\n",
    )

    findings = module.scan_skill(skill_dir)

    assert any(
        finding.rule == "missing-agilab-command-target"
        and "tools/release_proof_check.py" in finding.message
        for finding in findings
    )
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "release_proof_report.py").write_text("# Existing verifier\n", encoding="utf-8")
    (skill_dir / "SKILL.md").write_text(
        "uv run python tools/release_proof_report.py --check --compact\n", encoding="utf-8"
    )

    assert module.scan_skill(skill_dir) == []


def test_external_adapted_evidence_skill_uses_its_own_command_root(tmp_path: Path) -> None:
    module = _load_module()
    foreign_root = tmp_path / "thales_agilab"
    tools_dir = foreign_root / "tools"
    tools_dir.mkdir(parents=True)
    (tools_dir / "sync_codex_skills.py").write_text("# Private repo helper\n", encoding="utf-8")
    skill_dir = _write_skill(
        foreign_root / ".codex" / "skills",
        "agilab-evidence-contracts",
        "uv run python tools/sync_codex_skills.py --check\n",
    )

    assert module.scan_skill(skill_dir) == []

    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        skill_md.read_text(encoding="utf-8") + "streamlit.testing.v1.AppTest.from_file('page.py')\n",
        encoding="utf-8",
    )
    findings = module.scan_skill(skill_dir)

    assert {finding.rule for finding in findings} == {"retired-agilab-ui-recipe"}


def test_current_agilab_skill_command_recipes_are_valid() -> None:
    module = _load_module()
    selected = module.skill_dirs(module.DEFAULT_ROOTS, [])

    findings = module.scan(selected)

    assert not [
        finding
        for finding in findings
        if finding.rule in {"retired-agilab-ui-recipe", "missing-agilab-command-target"}
    ]


def test_scan_skill_reports_unreferenced_support_file_as_low(tmp_path: Path) -> None:
    module = _load_module()
    skill_dir = _write_skill(tmp_path, "orphan", "Use this concise workflow.")
    references = skill_dir / "references"
    references.mkdir()
    (references / "guide.md").write_text("Extra details.", encoding="utf-8")

    findings = module.scan_skill(skill_dir)

    assert any(finding.rule == "unreferenced-support-file" for finding in findings)
    assert {finding.severity for finding in findings} == {"low"}


def test_changed_skill_deleting_skill_md_blocks_quality_gate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args: str) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()

    git("init", "--quiet")
    git("config", "user.name", "AGILAB Test")
    git("config", "user.email", "agilab-test@example.invalid")
    skills_root = repo / ".codex/skills"
    skill_dir = _write_skill(skills_root, "demo", "Use this workflow.")
    references = skill_dir / "references"
    references.mkdir()
    (references / "guide.md").write_text("Supporting guidance.\n", encoding="utf-8")
    git("add", ".codex/skills/demo")
    git("commit", "--quiet", "-m", "add skill")
    base = git("rev-parse", "HEAD")

    (skill_dir / "SKILL.md").unlink()
    git("add", "--all")
    git("commit", "--quiet", "-m", "delete skill entrypoint")
    monkeypatch.setattr(module, "REPO_ROOT", repo)

    selected = module.changed_skill_dirs(base, [skills_root])
    findings = module.scan(selected)

    assert selected == [skill_dir.resolve()]
    assert any(finding.rule == "missing-skill-md" for finding in findings)
    assert (
        module.main(
            [
                "--roots",
                str(skills_root),
                "--changed-only",
                "--base-ref",
                base,
                "--external-validator",
                "off",
                "--fail-on",
                "high",
            ]
        )
        == 2
    )


def test_external_validator_can_be_required_or_skipped(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module.shutil, "which", lambda _command: None)

    skipped, skipped_findings = module.run_external_validator([], mode="if-available", command="skill-validator")
    required, required_findings = module.run_external_validator([], mode="require", command="skill-validator")

    assert skipped.available is False
    assert skipped.executed is False
    assert skipped_findings == []
    assert required_findings[0].rule == "external-validator-unavailable"
    assert required_findings[0].severity == "critical"


def test_render_markdown_includes_external_validator_status(tmp_path: Path) -> None:
    module = _load_module()
    status = module.ExternalValidatorStatus("if-available", "skill-validator", False, False)

    text = module.render_markdown([], [tmp_path / "skill"], status)

    assert "Skills scanned: 1" in text
    assert "External skill-validator: not executed" in text
    assert "No findings." in text
