from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


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
    fake_secret = "sk-live-" + "12345678901234567890"
    skill_dir = _write_skill(
        tmp_path,
        "risky",
        f'Use /Users/alice/private-data and set api_key = "{fake_secret}".',
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


def test_default_skill_selection_covers_both_roots(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    roots = [tmp_path / ".claude" / "skills", tmp_path / ".codex" / "skills"]
    expected = [
        _write_skill(root, f"default-{index}", "Use this workflow.")
        for index, root in enumerate(roots)
    ]
    monkeypatch.setattr(module, "DEFAULT_ROOTS", roots)
    report = tmp_path / "agilab-security-default-skill-selection-validation.json"

    result = module.main(["--json-output", str(report)])

    assert result == 0
    assert set(json.loads(report.read_text(encoding="utf-8"))["skills_scanned"]) == {
        str(path.resolve()) for path in expected
    }


@pytest.mark.parametrize(
    "empty_directory", [False, True], ids=["missing-directory", "missing-entrypoint"]
)
@pytest.mark.parametrize(
    "include_valid", [False, True], ids=["invalid-only", "mixed-valid-invalid"]
)
def test_explicit_skill_selection_keeps_invalid_requests(
    tmp_path: Path, empty_directory: bool, include_valid: bool
) -> None:
    module = _load_module()
    default_root = tmp_path / "default-skills"
    _write_skill(
        default_root, "unrelated", "This skill is outside the requested scope."
    )
    invalid = tmp_path / "requested-invalid"
    if empty_directory:
        invalid.mkdir()
    requested = [invalid]
    if include_valid:
        requested.append(
            _write_skill(tmp_path, "requested-valid", "Use this workflow.")
        )
    report = tmp_path / "agilab-security-explicit-skill-selection-validation.json"
    argv = [
        "--roots",
        str(default_root),
        "--fail-on",
        "critical",
    ]
    for path in requested:
        argv.extend(["--skill-dir", str(path)])
    argv.extend(["--json-output", str(report)])

    result = module.main(argv)

    assert result == 2
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert set(payload["skills_scanned"]) == {str(path.resolve()) for path in requested}
    missing = [
        finding
        for finding in payload["findings"]
        if finding["rule"] == "missing-skill-md"
    ]
    assert len(missing) == 1
    assert missing[0]["path"] == str(invalid.resolve())
    assert missing[0]["severity"] == "critical"


def test_explicit_skill_selection_stays_scoped_when_valid(tmp_path: Path) -> None:
    module = _load_module()
    default_root = tmp_path / "default-skills"
    unrelated = default_root / "unrelated-missing-entrypoint"
    unrelated.mkdir(parents=True)
    requested = _write_skill(tmp_path, "requested-valid", "Use this workflow.")
    report = tmp_path / "agilab-security-explicit-skill-selection-validation.json"

    result = module.main(
        [
            "--roots",
            str(default_root),
            "--skill-dir",
            str(requested),
            "--fail-on",
            "critical",
            "--json-output",
            str(report),
        ]
    )

    assert result == 0
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["skills_scanned"] == [str(requested.resolve())]
    assert payload["findings"] == []


def test_default_skill_selection_tolerates_absent_optional_provider(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_module()
    roots = [tmp_path / ".claude" / "skills", tmp_path / ".codex" / "skills"]
    expected = _write_skill(roots[0], "available-provider", "Use this workflow.")
    monkeypatch.setattr(module, "DEFAULT_ROOTS", roots)
    report = tmp_path / "agilab-security-default-skill-root-validation.json"

    result = module.main(["--json-output", str(report)])

    assert result == 0
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["skills_scanned"] == [str(expected.resolve())]
    assert payload["findings"] == []


@pytest.mark.parametrize("bad_kind", ["missing", "file"])
@pytest.mark.parametrize(
    "include_valid", [False, True], ids=["bad-root-only", "mixed-roots"]
)
@pytest.mark.parametrize(
    "changed_only", [False, True], ids=["full-scan", "no-changed-skills"]
)
def test_explicit_skill_roots_require_directories(
    tmp_path: Path, bad_kind: str, include_valid: bool, changed_only: bool
) -> None:
    module = _load_module()
    bad_root = tmp_path / "requested-bad-root"
    if bad_kind == "file":
        bad_root.write_text("This is a file, not a skill root.\n", encoding="utf-8")
    roots = [bad_root]
    if include_valid:
        roots.append(module.DEFAULT_ROOTS[0])
    report = tmp_path / "agilab-security-requested-skill-root-validation.json"
    argv = [
        "--roots",
        *(str(root) for root in roots),
        "--fail-on",
        "critical",
    ]
    if changed_only:
        argv.extend(["--changed-only", "--base-ref", "HEAD"])
    argv.extend(["--json-output", str(report)])

    result = module.main(argv)

    assert result == 2
    payload = json.loads(report.read_text(encoding="utf-8"))
    missing = [
        finding
        for finding in payload["findings"]
        if finding["rule"] == "missing-skill-root"
    ]
    assert len(missing) == 1
    assert missing[0]["path"] == str(bad_root.resolve())
    assert missing[0]["severity"] == "critical"
    if changed_only:
        assert payload["skills_scanned"] == []


def test_explicit_existing_empty_skill_root_is_allowed(tmp_path: Path) -> None:
    module = _load_module()
    root = tmp_path / "existing-empty-skill-root"
    root.mkdir()
    report = tmp_path / "agilab-security-empty-skill-root-validation.json"

    result = module.main(
        [
            "--roots",
            str(root),
            "--json-output",
            str(report),
        ]
    )

    assert result == 0
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["skills_scanned"] == []
    assert payload["findings"] == []


def test_no_changed_skills_is_allowed(tmp_path: Path) -> None:
    module = _load_module()
    report = tmp_path / "agilab-security-unchanged-skill-selection-validation.json"

    result = module.main(
        [
            "--changed-only",
            "--base-ref",
            "HEAD",
            "--json-output",
            str(report),
        ]
    )

    assert result == 0
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["skills_scanned"] == []
    assert payload["findings"] == []


@pytest.mark.parametrize(
    "selection", ["missing-directory", "missing-entrypoint", "valid", "mixed"]
)
def test_explicit_and_changed_only_selection_modes_are_rejected(
    tmp_path: Path, selection: str, capsys
) -> None:
    module = _load_module()
    requested = [tmp_path / "requested-invalid"]
    if selection == "missing-entrypoint":
        requested[0].mkdir()
    elif selection == "valid":
        requested = [_write_skill(tmp_path, "requested-valid", "Use this workflow.")]
    elif selection == "mixed":
        requested.append(
            _write_skill(tmp_path, "requested-valid", "Use this workflow.")
        )
    argv = ["--changed-only", "--base-ref", "HEAD"]
    for path in requested:
        argv.extend(["--skill-dir", str(path)])

    with pytest.raises(SystemExit) as excinfo:
        module.main(argv)

    assert excinfo.value.code == 2
    diagnostic = capsys.readouterr().err
    assert "--skill-dir" in diagnostic
    assert "--changed-only" in diagnostic
    assert "not allowed with argument" in diagnostic


@pytest.mark.parametrize(
    "delete_entire_skill", [False, True], ids=["deleted-entrypoint", "deleted-skill"]
)
def test_changed_skill_deletion_retains_only_existing_directories(
    tmp_path: Path, monkeypatch, delete_entire_skill: bool
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
    git("config", "commit.gpgsign", "false")
    git("config", "core.hooksPath", "/dev/null")
    skills_root = repo / ".codex/skills"
    skill_dir = _write_skill(skills_root, "demo", "Use this workflow.")
    reference = skill_dir / "guide.md"
    reference.write_text("Supporting guidance.\n", encoding="utf-8")
    git("add", ".codex/skills/demo")
    git("commit", "--quiet", "-m", "add skill")
    base = git("rev-parse", "HEAD")

    (skill_dir / "SKILL.md").unlink()
    if delete_entire_skill:
        reference.unlink()
        skill_dir.rmdir()
    git("add", "--all")
    git("commit", "--quiet", "-m", "delete skill entrypoint")
    monkeypatch.setattr(module, "REPO_ROOT", repo)
    report = tmp_path / "agilab-security-deleted-skill-validation.json"

    selected = module.changed_skill_dirs(base, [skills_root])
    result = module.main(
        [
            "--roots",
            str(skills_root),
            "--changed-only",
            "--base-ref",
            base,
            "--fail-on",
            "critical",
            "--json-output",
            str(report),
        ]
    )

    payload = json.loads(report.read_text(encoding="utf-8"))
    if delete_entire_skill:
        assert selected == []
        assert result == 0
        assert payload["findings"] == []
    else:
        assert selected == [skill_dir.resolve()]
        assert result == 2
        assert [finding["rule"] for finding in payload["findings"]] == [
            "missing-skill-md"
        ]
        assert payload["findings"][0]["severity"] == "critical"
