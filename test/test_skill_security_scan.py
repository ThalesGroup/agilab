from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path("tools/skill_security_scan.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("skill_security_scan_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_skill(root: Path, name: str, body: str, front_matter_extra: str = "") -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"""---
name: {name}
description: Demo skill.
license: BSD-3-Clause
{front_matter_extra}---

{body}
""",
        encoding="utf-8",
    )
    return skill_dir


def test_scan_skill_flags_literal_secret_and_machine_local_path(tmp_path: Path) -> None:
    module = _load_module()
    skill_dir = _write_skill(
        tmp_path,
        "risky",
        'Use /Users/alice/private-data and set api_key = "sk-live-12345678901234567890".',
    )

    findings = module.scan_skill(skill_dir)
    rules = {finding.rule for finding in findings}

    assert "literal-secret" in rules
    assert "private-absolute-path" in rules
    assert any(finding.severity == "critical" for finding in findings)


def test_scan_skill_reports_env_network_and_compatibility_boundary(tmp_path: Path) -> None:
    module = _load_module()
    skill_dir = _write_skill(
        tmp_path,
        "networked",
        "Fetch https://example.com with requests and read OPENAI_API_KEY from the environment.",
    )

    findings = module.scan_skill(skill_dir)
    rules = {finding.rule for finding in findings}

    assert "env-and-network" in rules
    assert "missing-compatibility" in rules


def test_scan_skill_suppresses_compatibility_hint_for_local_only_skill(tmp_path: Path) -> None:
    module = _load_module()
    skill_dir = _write_skill(tmp_path, "local", "Read the local README and run no tools.")

    findings = module.scan_skill(skill_dir)

    assert {finding.rule for finding in findings} == set()


def test_render_markdown_summarizes_noop_scan(tmp_path: Path) -> None:
    module = _load_module()

    text = module.render_markdown([], [tmp_path / "skill"])

    assert "Skills scanned: 1" in text
    assert "No findings." in text
