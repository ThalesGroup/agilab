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


def test_selected_provider_items_preserves_requested_subset_order() -> None:
    module = _load_module()

    selected = module.selected_provider_items(["claude", "codex"])

    assert [name for name, _ in selected] == ["claude", "codex"]


def test_selected_provider_items_defaults_to_all_providers() -> None:
    module = _load_module()

    selected = module.selected_provider_items(None)

    assert [name for name, _ in selected] == list(module.PROVIDERS)


def test_provider_skill_names_unions_additional_repo_without_double_counting(tmp_path: Path) -> None:
    module = _load_module()
    repo_root = tmp_path / "agilab"
    extra_root = tmp_path / "thales_agilab"
    primary_dir = repo_root / ".codex" / "skills"
    extra_dir = extra_root / ".codex" / "skills"
    primary_dir.mkdir(parents=True)
    extra_dir.mkdir(parents=True)
    (primary_dir / "alpha").mkdir()
    (primary_dir / "beta").mkdir()
    (extra_dir / "beta").mkdir()
    (extra_dir / "gamma").mkdir()
    module.REPO_ROOT = repo_root

    names = module.provider_skill_names(
        {
            "label": "Codex skills",
            "skills_dir": primary_dir,
            "badge": repo_root / "badges" / "skills-codex.svg",
            "color": "#00A67E",
        },
        [str(extra_root)],
    )

    assert names == {"alpha", "beta", "gamma"}


def test_main_generates_selected_provider_badge_from_public_skill_dirs(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = _load_module()
    codex_skills = tmp_path / ".codex" / "skills"
    claude_skills = tmp_path / ".claude" / "skills"
    codex_skills.mkdir(parents=True)
    claude_skills.mkdir(parents=True)
    (codex_skills / "alpha").mkdir()
    (codex_skills / "beta").mkdir()
    (claude_skills / "gamma").mkdir()
    badge_dir = tmp_path / "badges"
    monkeypatch.setattr(
        module,
        "PROVIDERS",
        {
            "codex": {
                "label": "Codex skills",
                "skills_dir": codex_skills,
                "badge": badge_dir / "skills-codex.svg",
                "color": "#00A67E",
            },
            "claude": {
                "label": "Claude skills",
                "skills_dir": claude_skills,
                "badge": badge_dir / "skills-claude.svg",
                "color": "#D97706",
            },
        },
    )
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["generate_skill_badges.py", "--providers", "codex"])

    result = module.main()

    assert result == 0
    assert (badge_dir / "skills-codex.svg").exists()
    assert not (badge_dir / "skills-claude.svg").exists()
    assert "Codex skills" in (badge_dir / "skills-codex.svg").read_text(encoding="utf-8")
    assert "2 skills" in (badge_dir / "skills-codex.svg").read_text(encoding="utf-8")
    assert "codex: 2 skills -> badges/skills-codex.svg" in capsys.readouterr().out


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
    monkeypatch.setattr(
        module,
        "PROVIDERS",
        {
            "codex": {
                "label": "Codex skills",
                "skills_dir": codex_skills,
                "badge": badge_dir / "skills-codex.svg",
                "color": "#00A67E",
            },
        },
    )
    monkeypatch.setattr(module, "REPO_ROOT", repo_root)
    monkeypatch.setattr(
        sys,
        "argv",
        ["generate_skill_badges.py", "--providers", "codex", "--include-repo", str(extra_root)],
    )

    result = module.main()

    assert result == 0
    content = (badge_dir / "skills-codex.svg").read_text(encoding="utf-8")
    assert "3 skills" in content
    assert "codex: 3 skills -> badges/skills-codex.svg" in capsys.readouterr().out
