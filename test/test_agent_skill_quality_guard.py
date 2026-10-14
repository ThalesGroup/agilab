from __future__ import annotations

import importlib.util
import json
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


def test_default_skill_selection_covers_both_roots(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    roots = [tmp_path / ".claude" / "skills", tmp_path / ".codex" / "skills"]
    expected = [
        _write_skill(root, f"default-{index}", "Use this workflow.")
        for index, root in enumerate(roots)
    ]
    monkeypatch.setattr(module, "DEFAULT_ROOTS", roots)
    report = tmp_path / "agilab-default-skill-selection-validation.json"

    result = module.main(["--external-validator", "off", "--json-output", str(report)])

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
    report = tmp_path / "agilab-explicit-skill-selection-validation.json"
    argv = [
        "--roots",
        str(default_root),
        "--external-validator",
        "off",
        "--fail-on",
        "high",
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
    report = tmp_path / "agilab-explicit-skill-selection-validation.json"

    result = module.main(
        [
            "--roots",
            str(default_root),
            "--skill-dir",
            str(requested),
            "--external-validator",
            "off",
            "--fail-on",
            "high",
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
    report = tmp_path / "agilab-default-skill-root-validation.json"

    result = module.main(["--external-validator", "off", "--json-output", str(report)])

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
    report = tmp_path / "agilab-requested-skill-root-validation.json"
    argv = [
        "--roots",
        *(str(root) for root in roots),
        "--external-validator",
        "off",
        "--fail-on",
        "high",
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
    report = tmp_path / "agilab-empty-skill-root-validation.json"

    result = module.main(
        [
            "--roots",
            str(root),
            "--external-validator",
            "off",
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
    report = tmp_path / "agilab-unchanged-skill-selection-validation.json"

    result = module.main(
        [
            "--changed-only",
            "--base-ref",
            "HEAD",
            "--external-validator",
            "off",
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
    argv = ["--changed-only", "--base-ref", "HEAD", "--external-validator", "off"]
    for path in requested:
        argv.extend(["--skill-dir", str(path)])

    with pytest.raises(SystemExit) as excinfo:
        module.main(argv)

    assert excinfo.value.code == 2
    diagnostic = capsys.readouterr().err
    assert "--skill-dir" in diagnostic
    assert "--changed-only" in diagnostic
    assert "not allowed with argument" in diagnostic


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



def _installed_validator_fixture(module, tmp_path: Path, monkeypatch):
    command = "agilab-external-validator-fixture"
    script = tmp_path / "agilab-external-validator-fixture.py"
    log = tmp_path / "agilab-external-validator-argv-evidence.jsonl"
    script.write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        f"log = Path({str(log)!r})\n"
        "with log.open('a', encoding='utf-8') as handle:\n"
        "    handle.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "assert sys.argv[1:4] == ['check', '--allow-extra-frontmatter', '--allow-dirs=agents,templates']\n"
        "assert len(sys.argv) == 5\n"
        "target = Path(sys.argv[-1])\n"
        "skills = [target] if (target / 'SKILL.md').is_file() else list(target.iterdir())\n"
        "if any((skill / 'agilab-external-validator-rejection.txt').is_file() for skill in skills):\n"
        "    print('unrelated skill rejected by fixture validator', file=sys.stderr)\n"
        "    raise SystemExit(1)\n",
        encoding="utf-8",
    )
    original_which = module.shutil.which
    original_run = module.subprocess.run

    def run(argv, **kwargs):
        if argv[:2] == [sys.executable, "check"]:
            return original_run([sys.executable, str(script), *argv[1:]], **kwargs)
        return original_run(argv, **kwargs)

    monkeypatch.setattr(
        module.shutil,
        "which",
        lambda requested: (
            sys.executable if requested == command else original_which(requested)
        ),
    )
    monkeypatch.setattr(module.subprocess, "run", run)
    return command, log


def _validator_calls(log: Path) -> list[list[str]]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def _validator_repo(module, tmp_path: Path, monkeypatch):
    repo = tmp_path / "agilab-external-validator-repro-repository"
    root = repo / ".codex/skills"
    requested = _write_skill(root, "requested-safe", "Use this reviewed workflow.")
    unrelated = _write_skill(
        root, "unrelated-safe", "This skill is outside the requested scope."
    )
    (unrelated / "agilab-external-validator-rejection.txt").write_text(
        "The external validator rejects this unselected fixture.\n", encoding="utf-8"
    )
    hooks = repo / "agilab-empty-fixture-hooks"
    hooks.mkdir()
    for args in (
        ("init", "--quiet"),
        ("config", "user.name", "AGILAB Test"),
        ("config", "user.email", "agilab-test@example.invalid"),
        ("config", "commit.gpgsign", "false"),
        ("config", "core.hooksPath", str(hooks)),
        ("add", ".codex/skills"),
        ("commit", "--quiet", "-m", "add validator fixtures"),
    ):
        subprocess.run(
            ["git", *args], cwd=repo, check=True, capture_output=True, text=True
        )
    monkeypatch.setattr(module, "REPO_ROOT", repo)
    monkeypatch.setattr(module, "DEFAULT_ROOTS", (root,))
    return repo, root, requested


@pytest.mark.parametrize("selection", ["explicit", "changed-only"])
def test_external_validator_follows_selected_skills(
    tmp_path: Path, monkeypatch, selection: str
) -> None:
    module = _load_module()
    repo, root, requested = _validator_repo(module, tmp_path, monkeypatch)
    base = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()
    skill_md = requested / "SKILL.md"
    skill_md.write_text(
        skill_md.read_text(encoding="utf-8") + "\nReviewed guidance changed.\n",
        encoding="utf-8",
    )
    for args in (
        ("add", str(skill_md.relative_to(repo))),
        ("commit", "--quiet", "-m", "change selected validator fixture"),
    ):
        subprocess.run(
            ["git", *args], cwd=repo, check=True, capture_output=True, text=True
        )
    command, log = _installed_validator_fixture(module, tmp_path, monkeypatch)
    report = tmp_path / "agilab-external-validator-selected-skills-validation.json"
    argv = [
        "--roots",
        str(root),
        "--external-validator",
        "require",
        "--external-validator-command",
        command,
        "--json-output",
        str(report),
    ]
    if selection == "explicit":
        argv.extend(["--skill-dir", str(requested)])
    else:
        argv.extend(["--changed-only", "--base-ref", base])

    result = module.main(argv)

    assert result == 0
    assert [call[-1] for call in _validator_calls(log)] == [str(requested.resolve())]
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["skills_scanned"] == [".codex/skills/requested-safe"]
    assert payload["findings"] == []
    assert payload["external_validator"]["executed"] is True


@pytest.mark.parametrize(
    "explicit_roots", [False, True], ids=["default-roots", "requested-roots"]
)
def test_external_validator_preserves_full_root_validation(
    tmp_path: Path, monkeypatch, explicit_roots: bool
) -> None:
    module = _load_module()
    _, root, _ = _validator_repo(module, tmp_path, monkeypatch)
    command, log = _installed_validator_fixture(module, tmp_path, monkeypatch)
    report = tmp_path / "agilab-external-validator-full-root-validation.json"
    argv = [
        "--external-validator",
        "require",
        "--external-validator-command",
        command,
        "--json-output",
        str(report),
    ]
    if explicit_roots:
        argv.extend(["--roots", str(root)])

    result = module.main(argv)

    assert result == 2
    assert [call[-1] for call in _validator_calls(log)] == [str(root)]
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert len(payload["skills_scanned"]) == 2
    assert any(
        finding["rule"] == "external-validator-failed"
        for finding in payload["findings"]
    )
    assert payload["external_validator"]["executed"] is True


def test_external_validator_skips_unchanged_skills(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    _validator_repo(module, tmp_path, monkeypatch)
    command, log = _installed_validator_fixture(module, tmp_path, monkeypatch)
    report = tmp_path / "agilab-external-validator-no-changes-validation.json"

    result = module.main(
        [
            "--changed-only",
            "--base-ref",
            "HEAD",
            "--external-validator",
            "require",
            "--external-validator-command",
            command,
            "--json-output",
            str(report),
        ]
    )

    assert result == 0
    assert _validator_calls(log) == []
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["skills_scanned"] == []
    assert payload["findings"] == []
    assert payload["external_validator"]["available"] is True
    assert payload["external_validator"]["executed"] is False


def test_external_validator_failure_on_foreign_root_emits_json(tmp_path: Path) -> None:
    foreign = tmp_path / "agilab-foreign-validator-root"
    skill = _write_skill(foreign, "foreign-safe", "Use this reviewed workflow.")
    report = tmp_path / "agilab-foreign-validator-failure-validation.json"
    repo = MODULE_PATH.parents[1]
    assert not (repo / "check").exists()
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(MODULE_PATH),
            "--roots",
            str(foreign),
            "--external-validator",
            "require",
            "--external-validator-command",
            sys.executable,
            "--fail-on",
            "medium",
            "--json-output",
            str(report),
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2, result.stderr
    assert "Traceback" not in result.stderr
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["skills_scanned"] == [skill.resolve().as_posix()]
    assert len(payload["findings"]) == 1
    finding = payload["findings"][0]
    assert finding["rule"] == "external-validator-failed"
    assert finding["severity"] == "medium"
    assert foreign.as_posix() in finding["message"]
    assert payload["external_validator"]["available"] is True
    assert payload["external_validator"]["executed"] is True
