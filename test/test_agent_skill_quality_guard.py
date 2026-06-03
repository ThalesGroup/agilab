from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


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


def test_scan_skill_reports_unreferenced_support_file_as_low(tmp_path: Path) -> None:
    module = _load_module()
    skill_dir = _write_skill(tmp_path, "orphan", "Use this concise workflow.")
    references = skill_dir / "references"
    references.mkdir()
    (references / "guide.md").write_text("Extra details.", encoding="utf-8")

    findings = module.scan_skill(skill_dir)

    assert any(finding.rule == "unreferenced-support-file" for finding in findings)
    assert {finding.severity for finding in findings} == {"low"}


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
