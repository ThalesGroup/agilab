from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "pre_push_changed_files.py"

spec = importlib.util.spec_from_file_location("pre_push_changed_files", MODULE_PATH)
assert spec is not None and spec.loader is not None
pre_push_changed_files = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = pre_push_changed_files
spec.loader.exec_module(pre_push_changed_files)


def test_classify_source_only_change_skips_docs_and_release_proof_guards():
    state = pre_push_changed_files.classify_changed_files(["src/agilab/about_page/bootstrap.py"])

    assert not state.docs_changed
    assert not state.release_proof_changed
    assert not state.app_contracts_changed
    assert not state.agi_core_protected_changed
    assert not state.agent_instructions_changed


def test_classify_docs_source_change_runs_docs_guard_only():
    state = pre_push_changed_files.classify_changed_files(["docs/source/getting-started.rst"])

    assert state.docs_changed
    assert not state.release_proof_changed
    assert not state.app_contracts_changed


def test_classify_release_proof_change_runs_both_doc_related_guards():
    state = pre_push_changed_files.classify_changed_files(["docs/source/release-proof.rst"])

    assert state.docs_changed
    assert state.release_proof_changed
    assert not state.app_contracts_changed


def test_classify_release_tool_change_runs_release_proof_guard_only():
    state = pre_push_changed_files.classify_changed_files(["tools/release_proof_report.py"])

    assert not state.docs_changed
    assert state.release_proof_changed
    assert not state.app_contracts_changed


def test_classify_app_contract_change_runs_app_contract_guard_only():
    state = pre_push_changed_files.classify_changed_files(["src/agilab/pypi_app_packages.py"])

    assert not state.docs_changed
    assert not state.release_proof_changed
    assert state.app_contracts_changed
    assert not state.agi_core_protected_changed


def test_classify_agi_core_change_runs_owner_guard_only():
    state = pre_push_changed_files.classify_changed_files(
        ["src/agilab/core/agi-core/src/agi_core/runtime.py"]
    )

    assert not state.docs_changed
    assert not state.release_proof_changed
    assert not state.app_contracts_changed
    assert state.agi_core_protected_changed


def test_classify_public_app_catalog_change_runs_docs_and_app_contract_guards():
    state = pre_push_changed_files.classify_changed_files(["docs/source/public-app-catalog.rst"])

    assert state.docs_changed
    assert not state.release_proof_changed
    assert state.app_contracts_changed


def test_classify_infra_scopes_do_not_count_as_mixed_push_scope():
    state = pre_push_changed_files.classify_changed_files(
        [
            "AGENTS.md",
            ".githooks/pre-push",
            "tools/agilab_dev.py",
            "test/test_agilab_dev_shortcuts.py",
        ]
    )

    assert not state.mixed_scope
    assert state.scope_count == 0


def test_pre_push_docs_guard_accepts_an_isolated_canonical_source():
    hook = (ROOT / ".githooks" / "pre-push").read_text(encoding="utf-8")

    assert 'if [[ -n "${AGILAB_DOCS_SOURCE:-}" ]]' in hook
    assert 'docs_source_args=(--source "$AGILAB_DOCS_SOURCE")' in hook
    assert '"${docs_source_args[@]}" \\' in hook


def test_pre_push_docs_source_override_fails_closed_when_missing(
    tmp_path: Path,
) -> None:
    hook_root = tmp_path / "repo"
    hooks_dir = hook_root / ".githooks"
    hooks_dir.mkdir(parents=True)
    hook_path = hooks_dir / "pre-push"
    hook_path.write_text(
        (ROOT / ".githooks" / "pre-push").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    hook_path.chmod(0o755)
    (hooks_dir / "guard_python.sh").write_text(
        """run_guard_python() {
  if [[ "$1" == "tools/pre_push_changed_files.py" ]]; then
    printf '%s\\n' 'DOCS_CHANGED=1' 'RELEASE_PROOF_CHANGED=0' \\
      'APP_CONTRACTS_CHANGED=0' 'AGI_CORE_PROTECTED_CHANGED=0' \\
      'AGENT_INSTRUCTIONS_CHANGED=0' 'MIXED_SCOPE=0' 'DETECTION_FAILED=0'
  fi
}
""",
        encoding="utf-8",
    )
    missing_source = tmp_path / "missing-canonical-source"
    env = dict(os.environ)
    env["AGILAB_DOCS_SOURCE"] = str(missing_source)

    completed = subprocess.run(
        [str(hook_path)],
        cwd=hook_root,
        input="",
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert completed.returncode == 1
    assert f"AGILAB_DOCS_SOURCE is not a directory: {missing_source}" in completed.stderr


def test_classify_agent_instruction_change_runs_agent_instruction_guard_only():
    state = pre_push_changed_files.classify_changed_files(["AGENTS.md"])

    assert not state.docs_changed
    assert not state.release_proof_changed
    assert not state.app_contracts_changed
    assert not state.agi_core_protected_changed
    assert state.agent_instructions_changed


def test_classify_agent_skill_change_runs_agent_instruction_guard_only():
    state = pre_push_changed_files.classify_changed_files(
        [".codex/skills/agilab-runbook/SKILL.md"]
    )

    assert not state.docs_changed
    assert not state.release_proof_changed
    assert not state.app_contracts_changed
    assert not state.agi_core_protected_changed
    assert state.agent_instructions_changed


def test_classify_many_product_scopes_blocks_mixed_push_scope():
    state = pre_push_changed_files.classify_changed_files(
        [
            "src/agilab/apps/builtin/flight_telemetry_project/README.md",
            "src/agilab/apps/builtin/mission_decision_project/README.md",
            "src/agilab/apps-pages/view_maps/pyproject.toml",
        ],
        max_scopes=2,
    )

    assert state.mixed_scope
    assert state.scope_count == 3


def test_pre_push_records_use_default_branch_merge_base_for_topic_update():
    calls = []

    def fake_git(args):
        calls.append(list(args))
        if args[:2] == ["merge-base", "localsha"]:
            return "default-base-sha"
        return "docs/source/getting-started.rst\0src/agilab/main_page.py\0"

    stdin_text = "refs/heads/topic localsha refs/heads/topic remotesha\n"
    changed = pre_push_changed_files.changed_files_from_pre_push(stdin_text, git=fake_git)

    assert changed == ("docs/source/getting-started.rst", "src/agilab/main_page.py")
    assert calls == [
        ["merge-base", "localsha", "origin/main"],
        [
            "diff",
            "--no-renames",
            "--name-only",
            "-z",
            "default-base-sha",
            "localsha",
        ],
    ]


def test_pre_push_records_keep_remote_sha_for_main_update():
    calls = []

    def fake_git(args):
        calls.append(list(args))
        return "tools/release_plan.py\0"

    stdin_text = "refs/heads/main localsha refs/heads/main remotesha\n"
    changed = pre_push_changed_files.changed_files_from_pre_push(
        stdin_text,
        git=fake_git,
    )

    assert changed == ("tools/release_plan.py",)
    assert calls == [
        ["diff", "--no-renames", "--name-only", "-z", "remotesha", "localsha"]
    ]


def test_main_reads_pre_push_spec_file_for_hook_guard_state(tmp_path, monkeypatch, capsys):
    spec_file = tmp_path / "pre-push-spec.txt"
    spec_text = "refs/heads/topic localsha refs/heads/topic remotesha\n"
    spec_file.write_text(spec_text, encoding="utf-8")
    seen = []

    def fake_changed_files_from_pre_push(stdin_text):
        seen.append(stdin_text)
        return ("docs/source/getting-started.rst",)

    monkeypatch.setattr(
        pre_push_changed_files,
        "changed_files_from_pre_push",
        fake_changed_files_from_pre_push,
    )

    assert pre_push_changed_files.main(["--pre-push-spec", str(spec_file)]) == 0

    assert seen == [spec_text]
    output = capsys.readouterr().out
    assert "DOCS_CHANGED=1" in output
    assert "CHANGED_COUNT=1" in output


def test_render_shell_is_eval_friendly():
    state = pre_push_changed_files.classify_changed_files(["docs/source/release-proof.rst"])

    assert pre_push_changed_files.render_shell(state).splitlines() == [
        "DOCS_CHANGED=1",
        "RELEASE_PROOF_CHANGED=1",
        "APP_CONTRACTS_CHANGED=0",
        "AGI_CORE_PROTECTED_CHANGED=0",
        "AGENT_INSTRUCTIONS_CHANGED=0",
        "MIXED_SCOPE=0",
        "SCOPE_COUNT=0",
        "SCOPE_LIMIT=2",
        "DETECTION_FAILED=0",
        "CHANGED_COUNT=1",
        "DETECTION_ERROR=",
    ]
