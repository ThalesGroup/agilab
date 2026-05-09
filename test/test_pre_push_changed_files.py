from __future__ import annotations

import importlib.util
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


def test_classify_docs_source_change_runs_docs_guard_only():
    state = pre_push_changed_files.classify_changed_files(["docs/source/getting-started.rst"])

    assert state.docs_changed
    assert not state.release_proof_changed


def test_classify_release_proof_change_runs_both_doc_related_guards():
    state = pre_push_changed_files.classify_changed_files(["docs/source/release-proof.rst"])

    assert state.docs_changed
    assert state.release_proof_changed


def test_classify_release_tool_change_runs_release_proof_guard_only():
    state = pre_push_changed_files.classify_changed_files(["tools/release_proof_report.py"])

    assert not state.docs_changed
    assert state.release_proof_changed


def test_pre_push_records_use_remote_sha_as_diff_base():
    calls = []

    def fake_git(args):
        calls.append(list(args))
        return "docs/source/getting-started.rst\nsrc/agilab/main_page.py"

    stdin_text = "refs/heads/topic localsha refs/heads/topic remotesha\n"
    changed = pre_push_changed_files.changed_files_from_pre_push(stdin_text, git=fake_git)

    assert changed == ("docs/source/getting-started.rst", "src/agilab/main_page.py")
    assert calls == [["diff", "--name-only", "--diff-filter=ACMR", "remotesha", "localsha"]]


def test_render_shell_is_eval_friendly():
    state = pre_push_changed_files.classify_changed_files(["docs/source/release-proof.rst"])

    assert pre_push_changed_files.render_shell(state).splitlines() == [
        "DOCS_CHANGED=1",
        "RELEASE_PROOF_CHANGED=1",
        "DETECTION_FAILED=0",
        "CHANGED_COUNT=1",
        "DETECTION_ERROR=",
    ]
