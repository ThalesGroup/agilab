from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path("tools/agent_skill_catalog.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("agent_skill_catalog_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_skill(root: Path, name: str, description: str = "Demo skill.") -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"""---
name: {name}
description: {description}
license: BSD-3-Clause
metadata:
  updated: 2026-05-19
---

# {name}

Use this skill for deterministic tests.
""",
        encoding="utf-8",
    )
    return skill_dir


def test_catalog_outputs_include_badge_contract_and_skill_entries(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    skills_root = tmp_path / ".claude" / "skills"
    _write_skill(skills_root, "alpha-skill", "Alpha workflow guidance.")
    monkeypatch.setattr(module, "DEFAULT_MARKDOWN_OUT", tmp_path / "AGENT_SKILLS.md")
    monkeypatch.setattr(module, "DEFAULT_LLMS_OUT", tmp_path / "llms.txt")
    monkeypatch.setattr(module, "DEFAULT_LLMS_FULL_OUT", tmp_path / "llms-full.txt")

    outputs = module.generate_outputs(skills_root)
    changed = module.write_outputs(outputs)

    assert {path.name for path in changed} == {"AGENT_SKILLS.md", "llms.txt", "llms-full.txt"}
    markdown = (tmp_path / "AGENT_SKILLS.md").read_text(encoding="utf-8")
    llms = (tmp_path / "llms.txt").read_text(encoding="utf-8")
    full = (tmp_path / "llms-full.txt").read_text(encoding="utf-8")
    assert "Skills: 1 skill" in markdown
    assert "Standard: Agent Skills style" in markdown
    assert "Works with: Codex, Claude Code, Aider, OpenCode" in markdown
    assert "Catalog-compatible: Continue" in markdown
    assert "tools/agent_skill_quality_guard.py" in markdown
    assert "Continue can consume this generated catalog" in llms
    assert "alpha-skill: Alpha workflow guidance." in llms
    assert "license: BSD-3-Clause" in full
    assert "tools/agent_skill_quality_guard.py" in full
    assert module.check_outputs(outputs) == []


def test_real_agent_skill_catalog_is_current() -> None:
    module = _load_module()
    outputs = module.generate_outputs(module.DEFAULT_SKILLS_ROOT)

    assert module.check_outputs(outputs) == []
