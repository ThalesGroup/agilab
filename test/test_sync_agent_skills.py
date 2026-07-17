from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "sync_agent_skills.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "sync_agent_skills_test_module", MODULE_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_skill(root: Path, name: str, body: str = "Use this skill for tests.") -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Demo skill.\nlicense: BSD-3-Clause\n---\n\n# {name}\n\n{body}\n",
        encoding="utf-8",
    )
    return skill_dir


def _fake_repo(module, monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    repo_root = tmp_path / "repo"
    claude_root = repo_root / ".claude" / "skills"
    codex_root = repo_root / ".codex" / "skills"
    claude_root.mkdir(parents=True)
    codex_root.mkdir(parents=True)
    monkeypatch.setattr(module, "ROOT", repo_root)
    monkeypatch.setattr(module, "CLAUDE_ROOT", claude_root)
    monkeypatch.setattr(module, "CODEX_ROOT", codex_root)
    monkeypatch.setattr(module, "validate_skills_root", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "refresh_codex_skill_index", lambda **_kwargs: None)
    monkeypatch.setattr(module, "refresh_skill_badges", lambda **_kwargs: None)
    monkeypatch.setattr(module, "refresh_agent_skill_catalog", lambda **_kwargs: None)
    monkeypatch.setattr(module, "refresh_capability_manifest", lambda **_kwargs: None)
    return claude_root, codex_root


def _tokki_absent(module, monkeypatch) -> None:
    monkeypatch.setattr(module.shutil, "which", lambda _command: None)


def _tokki_reports(module, monkeypatch, names: list[str], returncode: int = 0) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake_run(command, **_kwargs):
        calls.append(list(command))
        payload = json.dumps({"skills": [{"name": name} for name in names]})
        return subprocess.CompletedProcess(command, returncode, payload, "")

    monkeypatch.setattr(module.shutil, "which", lambda _command: "/usr/bin/tokki")
    monkeypatch.setattr(module.subprocess, "run", fake_run)
    return calls


def test_check_mode_reports_drift_without_mutating_mirror(tmp_path, monkeypatch, capsys) -> None:
    module = _load_module()
    claude_root, codex_root = _fake_repo(module, monkeypatch, tmp_path)
    _tokki_absent(module, monkeypatch)
    _write_skill(claude_root, "alpha", body="New wording.")
    _write_skill(codex_root, "alpha", body="Stale wording.")
    _write_skill(claude_root, "beta")
    (codex_root / "alpha" / "extra.md").write_text("mirror-only\n", encoding="utf-8")

    exit_code = module.main(["--check"])

    assert exit_code == 1
    output = capsys.readouterr().out
    assert "alpha/SKILL.md: content differs" in output
    assert "alpha/extra.md: not in canonical source" in output
    assert "beta: missing from" in output
    assert "Stale wording." in (codex_root / "alpha" / "SKILL.md").read_text(encoding="utf-8")
    assert not (codex_root / "beta").exists()


def test_check_mode_flags_mirror_only_skills(tmp_path, monkeypatch, capsys) -> None:
    module = _load_module()
    claude_root, codex_root = _fake_repo(module, monkeypatch, tmp_path)
    _tokki_absent(module, monkeypatch)
    _write_skill(claude_root, "alpha")
    _write_skill(codex_root, "alpha")
    _write_skill(codex_root, "orphan")

    exit_code = module.main(["--check"])

    assert exit_code == 1
    assert "orphan: mirror-only skill" in capsys.readouterr().out


def test_check_mode_passes_when_trees_are_in_sync(tmp_path, monkeypatch, capsys) -> None:
    module = _load_module()
    claude_root, codex_root = _fake_repo(module, monkeypatch, tmp_path)
    _tokki_absent(module, monkeypatch)
    _write_skill(claude_root, "alpha")
    _write_skill(codex_root, "alpha")

    assert module.main(["--check"]) == 0
    output = capsys.readouterr().out
    assert "No drift" in output
    assert "skipped tokki skill visibility check" in output


def test_check_mode_ignores_skip_names_like_the_sync_copy(tmp_path, monkeypatch) -> None:
    module = _load_module()
    claude_root, codex_root = _fake_repo(module, monkeypatch, tmp_path)
    _tokki_absent(module, monkeypatch)
    _write_skill(claude_root, "alpha")
    (claude_root / "alpha" / "README.md").write_text("canonical only\n", encoding="utf-8")
    _write_skill(codex_root, "alpha")

    assert module.main(["--check"]) == 0


def test_check_mode_limits_drift_scan_to_selected_skills(tmp_path, monkeypatch, capsys) -> None:
    module = _load_module()
    claude_root, codex_root = _fake_repo(module, monkeypatch, tmp_path)
    _tokki_absent(module, monkeypatch)
    _write_skill(claude_root, "alpha")
    _write_skill(codex_root, "alpha")
    _write_skill(claude_root, "beta", body="Only in canonical.")

    assert module.main(["--skills", "alpha", "--check"]) == 0
    assert "beta" not in capsys.readouterr().out.replace("No drift", "")


def test_selection_is_required_without_check(tmp_path, monkeypatch) -> None:
    module = _load_module()
    _fake_repo(module, monkeypatch, tmp_path)

    with pytest.raises(SystemExit):
        module.main([])


def test_tokki_visibility_passes_when_all_skills_are_seen(tmp_path, monkeypatch, capsys) -> None:
    module = _load_module()
    claude_root, codex_root = _fake_repo(module, monkeypatch, tmp_path)
    _write_skill(claude_root, "alpha")
    _write_skill(codex_root, "alpha")
    calls = _tokki_reports(module, monkeypatch, ["alpha"])

    assert module.main(["--check"]) == 0
    assert "tokki sees 1 skill(s)" in capsys.readouterr().out
    assert calls and calls[0][:3] == ["/usr/bin/tokki", "skills", "list"]
    assert str(claude_root) in calls[0]


def test_tokki_visibility_fails_when_a_skill_is_missing(tmp_path, monkeypatch) -> None:
    module = _load_module()
    claude_root, codex_root = _fake_repo(module, monkeypatch, tmp_path)
    _write_skill(claude_root, "alpha")
    _write_skill(claude_root, "beta")
    _write_skill(codex_root, "alpha")
    _write_skill(codex_root, "beta")
    _tokki_reports(module, monkeypatch, ["alpha"])

    with pytest.raises(SystemExit, match="beta"):
        module.main(["--check"])


def test_tokki_visibility_fails_on_tokki_error(tmp_path, monkeypatch) -> None:
    module = _load_module()
    claude_root, codex_root = _fake_repo(module, monkeypatch, tmp_path)
    _write_skill(claude_root, "alpha")
    _write_skill(codex_root, "alpha")
    _tokki_reports(module, monkeypatch, ["alpha"], returncode=2)

    with pytest.raises(SystemExit, match="failed"):
        module.main(["--check"])


def test_sync_copies_skill_and_checks_tokki_visibility(tmp_path, monkeypatch, capsys) -> None:
    module = _load_module()
    claude_root, codex_root = _fake_repo(module, monkeypatch, tmp_path)
    _write_skill(claude_root, "alpha")
    calls = _tokki_reports(module, monkeypatch, ["alpha"])

    exit_code = module.main(["--skills", "alpha"])

    assert exit_code == 0
    assert (codex_root / "alpha" / "SKILL.md").exists()
    assert calls, "sync must run the tokki visibility check"
    assert "Synced 1 skill(s)" in capsys.readouterr().out


def test_sync_validates_canonical_tree_before_mutating_mirror(tmp_path, monkeypatch) -> None:
    module = _load_module()
    claude_root, codex_root = _fake_repo(module, monkeypatch, tmp_path)
    _tokki_absent(module, monkeypatch)
    _write_skill(claude_root, "alpha")

    def failing_validate(*_args, **_kwargs):
        raise SystemExit("front-matter issues")

    monkeypatch.setattr(module, "validate_skills_root", failing_validate)

    with pytest.raises(SystemExit, match="front-matter"):
        module.main(["--skills", "alpha"])
    assert not (codex_root / "alpha").exists()


def test_check_passes_for_symlinked_directory_content_after_sync(tmp_path, monkeypatch) -> None:
    module = _load_module()
    claude_root, codex_root = _fake_repo(module, monkeypatch, tmp_path)
    _tokki_absent(module, monkeypatch)
    skill_dir = _write_skill(claude_root, "alpha")
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "inner.md").write_text("shared content\n", encoding="utf-8")
    (skill_dir / "linkdir").symlink_to(shared, target_is_directory=True)

    assert module.main(["--skills", "alpha"]) == 0
    assert (codex_root / "alpha" / "linkdir" / "inner.md").is_file()
    assert module.main(["--check"]) == 0


def test_check_mode_flags_executable_bit_drift(tmp_path, monkeypatch, capsys) -> None:
    module = _load_module()
    claude_root, codex_root = _fake_repo(module, monkeypatch, tmp_path)
    _tokki_absent(module, monkeypatch)
    for root in (claude_root, codex_root):
        _write_skill(root, "alpha")
        script = root / "alpha" / "scripts" / "run.py"
        script.parent.mkdir()
        script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    (claude_root / "alpha" / "scripts" / "run.py").chmod(0o755)
    (codex_root / "alpha" / "scripts" / "run.py").chmod(0o644)

    assert module.main(["--check"]) == 1
    assert "executable bit differs" in capsys.readouterr().out


def test_tokki_model_free_route_is_limited_to_check() -> None:
    routes = (REPO_ROOT / ".tokki" / "model-free-commands").read_text(encoding="utf-8")
    sync_lines = [
        line.strip() for line in routes.splitlines() if "sync_agent_skills" in line
    ]
    assert sync_lines == ["exact python3 tools/sync_agent_skills.py --check"]


def test_sync_proceeds_gracefully_when_tokki_binary_is_absent(tmp_path, monkeypatch, capsys) -> None:
    module = _load_module()
    claude_root, codex_root = _fake_repo(module, monkeypatch, tmp_path)
    _write_skill(claude_root, "alpha")
    _tokki_absent(module, monkeypatch)

    exit_code = module.main(["--skills", "alpha"])

    assert exit_code == 0
    assert (codex_root / "alpha" / "SKILL.md").exists()
    assert "skipped tokki skill visibility check" in capsys.readouterr().out
