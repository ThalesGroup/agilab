from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path("tools/generate_skill_badges.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("generate_skill_badges_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_visible_skill_names_filters_hidden_dirs_and_files(tmp_path: Path) -> None:
    module = _load_module()
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "alpha").mkdir()
    (skills_dir / "beta").mkdir()
    (skills_dir / ".generated").mkdir()
    (skills_dir / "README.md").write_text("index", encoding="utf-8")

    names = module.visible_skill_names(skills_dir)

    assert names == {"alpha", "beta"}


def test_format_skill_count_handles_singular_and_plural() -> None:
    module = _load_module()

    assert module.format_skill_count(1) == "1 skill"
    assert module.format_skill_count(2) == "2 skills"


def test_repo_skill_names_unions_agent_trees_and_extra_repo_without_double_counting(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_module()
    repo_root = tmp_path / "agilab"
    extra_root = tmp_path / "thales_agilab"
    claude_dir = repo_root / ".claude" / "skills"
    codex_dir = repo_root / ".codex" / "skills"
    extra_claude_dir = extra_root / ".claude" / "skills"
    extra_codex_dir = extra_root / ".codex" / "skills"
    claude_dir.mkdir(parents=True)
    codex_dir.mkdir(parents=True)
    extra_claude_dir.mkdir(parents=True)
    extra_codex_dir.mkdir(parents=True)
    (claude_dir / "alpha").mkdir()
    (codex_dir / "alpha").mkdir()
    (codex_dir / "beta").mkdir()
    (extra_claude_dir / "beta").mkdir()
    (extra_codex_dir / "gamma").mkdir()
    monkeypatch.setattr(module, "REPO_ROOT", repo_root)

    names = module.repo_skill_names([str(extra_root)])

    assert names == {"alpha", "beta", "gamma"}


def test_main_generates_single_public_skill_badge_from_both_skill_trees(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    repo_root = tmp_path / "agilab"
    claude_skills = repo_root / ".claude" / "skills"
    codex_skills = repo_root / ".codex" / "skills"
    claude_skills.mkdir(parents=True)
    codex_skills.mkdir(parents=True)
    (claude_skills / "alpha").mkdir()
    (codex_skills / "alpha").mkdir()
    (codex_skills / "beta").mkdir()
    badge_dir = repo_root / "badges"
    monkeypatch.setattr(module, "REPO_ROOT", repo_root)
    monkeypatch.setattr(
        module,
        "SKILL_BADGE",
        {"label": "Skills", "badge": badge_dir / "skills.svg", "color": "#0F766E"},
    )
    monkeypatch.setattr(module, "AGENT_BADGES", {})
    monkeypatch.setattr(sys, "argv", ["generate_skill_badges.py"])

    result = module.main()

    assert result == 0
    assert (badge_dir / "skills.svg").exists()
    assert not (badge_dir / "skills-codex.svg").exists()
    assert not (badge_dir / "skills-claude.svg").exists()
    content = (badge_dir / "skills.svg").read_text(encoding="utf-8")
    assert "Skills" in content
    assert "2 skills" in content
    assert "repo skills" not in content
    assert "skills: 2 skills -> badges/skills.svg" in capsys.readouterr().out


def test_main_can_include_additional_local_repo_for_union_count(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    repo_root = tmp_path / "agilab"
    extra_root = tmp_path / "thales_agilab"
    codex_skills = repo_root / ".codex" / "skills"
    extra_codex_skills = extra_root / ".codex" / "skills"
    codex_skills.mkdir(parents=True)
    extra_codex_skills.mkdir(parents=True)
    (codex_skills / "alpha").mkdir()
    (codex_skills / "beta").mkdir()
    (extra_codex_skills / "beta").mkdir()
    (extra_codex_skills / "gamma").mkdir()
    badge_dir = repo_root / "badges"
    monkeypatch.setattr(module, "REPO_ROOT", repo_root)
    monkeypatch.setattr(
        module,
        "SKILL_BADGE",
        {"label": "Skills", "badge": badge_dir / "skills.svg", "color": "#0F766E"},
    )
    monkeypatch.setattr(module, "AGENT_BADGES", {})
    monkeypatch.setattr(
        sys,
        "argv",
        ["generate_skill_badges.py", "--include-repo", str(extra_root)],
    )

    result = module.main()

    assert result == 0
    content = (badge_dir / "skills.svg").read_text(encoding="utf-8")
    assert "3 skills" in content
    assert "repo skills" not in content
    assert "skills: 3 skills -> badges/skills.svg" in capsys.readouterr().out


def test_main_generates_public_agent_badges_by_default(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    claude_skills = tmp_path / ".claude" / "skills"
    codex_skills = tmp_path / ".codex" / "skills"
    claude_skills.mkdir(parents=True)
    codex_skills.mkdir(parents=True)
    (claude_skills / "alpha").mkdir()
    (claude_skills / "beta").mkdir()
    (codex_skills / "alpha").mkdir()
    badge_dir = tmp_path / "badges"
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        module,
        "SKILL_BADGE",
        {"label": "Skills", "badge": badge_dir / "skills.svg", "color": "#0F766E"},
    )
    monkeypatch.setattr(
        module,
        "AGENT_BADGES",
        {
            "standard": {
                "label": "Standard",
                "value": "Agent Skills",
                "badge": badge_dir / "agent-standard.svg",
                "color": "#5B6CFF",
            },
            "works-with": {
                "label": "Works with",
                "value": "Codex Claude Continue Aider OpenCode",
                "badge": badge_dir / "agent-works-with.svg",
                "color": "#0F766E",
            },
        },
    )
    monkeypatch.setattr(sys, "argv", ["generate_skill_badges.py"])

    result = module.main()

    assert result == 0
    assert "2 skills" in (badge_dir / "skills.svg").read_text(encoding="utf-8")
    assert "Agent Skills" in (badge_dir / "agent-standard.svg").read_text(encoding="utf-8")
    assert "Codex Claude Continue Aider OpenCode" in (
        badge_dir / "agent-works-with.svg"
    ).read_text(encoding="utf-8")
