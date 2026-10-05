"""Scientific receipts remain SHA-bound when a notebook UI changes runtime."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


_path = Path(__file__).resolve().parents[1] / "tools/demos/verify_agilab_native_notebook_demo_artifacts.py"
_spec = importlib.util.spec_from_file_location("native_demo_verifier", _path)
verifier = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verifier)


def _receipt(project):
    for name, content in {"app.py": "render_native_view()\n", "core.py": "answer = 42\n",
                          "solution.ipynb": "{}\n", "README.md": "Old instructions\n"}.items():
        (project / name).write_text(content)
    files = verifier.hashes(project, ("app.py", "core.py", "solution.ipynb", "README.md"))
    science = {"status": "passed", "checks": ["independent_oracle"], "measurement": 42}
    native = {"status": "passed", "checks": ["native_input_and_callback"]}
    report = {"status": "passed", "files": files, "verification": native,
              "seconds": 17, "source": {"sha256": "historical-source"},
              "native_ui_migration": {"interface_runtime": "agi_web.python_ui",
                                      "verified_at_utc": "original-native-timestamp",
                                      "original_files": deepcopy(files),
                                      "original_verification": {"status": "passed", "text": science}}}
    (project / "result.json").write_text(json.dumps(report))
    return report


def test_retains_identical_science_and_documents_documentation_only_refresh(tmp_path):
    original = _receipt(tmp_path)
    (tmp_path / "README.md").write_text("Native launch instructions\n")
    verifier.restore_scientific_proofs(tmp_path)
    restored = json.loads((tmp_path / "result.json").read_text())
    assert restored["verification"]["text"] == original["native_ui_migration"]["original_verification"]["text"]
    assert restored["native_ui_migration"]["native_verification"] == original["verification"]
    assert restored["native_ui_migration"]["verified_at_utc"] == "original-native-timestamp"
    assert restored["seconds"] == 17 and restored["source"] == original["source"]
    assert restored["native_ui_migration"]["scientific_proof_retention"]["sections"] == ["text"]
    assert restored["files"]["README.md"] == hashlib.sha256((tmp_path / "README.md").read_bytes()).hexdigest()


def test_changed_executable_cannot_reuse_completed_native_verification(tmp_path):
    _receipt(tmp_path)
    (tmp_path / "app.py").write_text("different_view()\n")
    before = (tmp_path / "result.json").read_bytes()
    with pytest.raises(ValueError, match="Native artifacts changed"):
        verifier.restore_scientific_proofs(tmp_path)
    assert (tmp_path / "result.json").read_bytes() == before


def test_restoration_cannot_follow_a_symlinked_receipt(tmp_path):
    _receipt(tmp_path)
    receipt = tmp_path / "result.json"
    target = tmp_path / "historical_receipt.json"
    receipt.rename(target)
    original = target.read_bytes()
    receipt.symlink_to(target)
    with pytest.raises(ValueError, match="regular existing public receipt"):
        verifier.restore_scientific_proofs(tmp_path)
    assert target.read_bytes() == original


def test_newly_sealed_science_cannot_reuse_an_old_independent_oracle(tmp_path):
    report = _receipt(tmp_path)
    (tmp_path / "core.py").write_text("answer = 99\n")
    report["files"]["core.py"] = hashlib.sha256((tmp_path / "core.py").read_bytes()).hexdigest()
    (tmp_path / "result.json").write_text(json.dumps(report))
    before = (tmp_path / "result.json").read_bytes()
    with pytest.raises(ValueError, match="Scientific artifact changed"):
        verifier.restore_scientific_proofs(tmp_path)
    assert (tmp_path / "result.json").read_bytes() == before


def test_ui_harness_import_can_retain_science_but_other_changes_need_test_proof(tmp_path):
    report = _receipt(tmp_path)
    (tmp_path / "tests.py").write_text("from agi_web.testing import AppTest\nassert 2 + 2 == 4\n")
    old = b"from streamlit.testing.v1 import AppTest\nassert 2 + 2 == 4\n"
    report["native_ui_migration"]["original_files"]["tests.py"] = hashlib.sha256(old).hexdigest()
    report["files"]["tests.py"] = hashlib.sha256((tmp_path / "tests.py").read_bytes()).hexdigest()
    combined, _ = verifier.retain_scientific_proofs(tmp_path, report, report["verification"], report["files"])
    assert combined["text"]["status"] == "passed"
    (tmp_path / "tests.py").write_text("from agi_web.testing import AppTest\nassert 2 + 2 == 5\n")
    report["files"]["tests.py"] = hashlib.sha256((tmp_path / "tests.py").read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="Scientific artifact changed;.*tests.py"):
        verifier.retain_scientific_proofs(tmp_path, report, report["verification"], report["files"])
    test_proof = {"tests.py": {"status": "passed", "sha256": report["files"]["tests.py"]}}
    _, retained = verifier.retain_scientific_proofs(tmp_path, report, report["verification"], report["files"], test_proof)
    assert retained["independently_reverified_test_files"] == ["tests.py"]
    test_proof["tests.py"]["sha256"] = "outdated test seal"
    with pytest.raises(ValueError, match="Scientific artifact changed;.*tests.py"):
        verifier.retain_scientific_proofs(tmp_path, report, report["verification"], report["files"], test_proof)

def _text_science_fixture(tmp_path, monkeypatch, proof):
    project = tmp_path / "text_notebook_demo"
    project.mkdir()
    report = _receipt(project)
    root = tmp_path / "verifier_root"
    tool = root / "tools/demos/export_text_notebook_demo.py"
    tool.parent.mkdir(parents=True)
    tool.write_text("def verify_current_project(project, files, *, workflow):\n"
                    "    return " + repr(proof) + "\n")
    monkeypatch.setattr(verifier, "ROOT", root)
    return project, report


def test_text_reverification_rejects_a_proof_for_old_artifact_bytes(tmp_path, monkeypatch):
    project, report = _text_science_fixture(
        tmp_path, monkeypatch,
        {"status": "passed", "files_sha256": {"core.py": "old seal"},
         "sections": {"text": {"status": "passed"}}})
    with pytest.raises(ValueError, match="incomplete"):
        verifier.reverify_text_science(project, report, verifier.hashes(project, report["files"]))


def test_text_reverification_requires_every_original_scientific_section(tmp_path, monkeypatch):
    project, report = _text_science_fixture(tmp_path, monkeypatch, {})
    current = verifier.hashes(project, report["files"])
    report["native_ui_migration"]["original_verification"]["workflow"] = {"status": "passed"}
    tool = verifier.ROOT / "tools/demos/export_text_notebook_demo.py"
    tool.write_text("def verify_current_project(project, files, *, workflow):\n"
                    "    return " + repr({"status": "passed", "files_sha256": current,
                                         "sections": {"text": {"status": "passed"}}}) + "\n")
    with pytest.raises(ValueError, match="incomplete"):
        verifier.reverify_text_science(project, report, current)


def test_unavailable_scientific_verifier_cannot_reseal_a_different_demo(tmp_path):
    report = _receipt(tmp_path)
    with pytest.raises(ValueError, match="No independent verifier"):
        verifier.reverify_text_science(tmp_path, report, report["files"])


def test_fresh_text_science_is_distinct_from_the_original_build(tmp_path, monkeypatch):
    from types import SimpleNamespace
    project = tmp_path / "text_notebook_demo"
    project.mkdir()
    original = _receipt(project)
    original["schema"] = "agilab.notebook_agent.public_demo.v1"
    (project / "result.json").write_text(json.dumps(original))
    (project / "core.py").write_text("answer = 99\n")
    current = verifier.hashes(project, original["files"])
    native = {"status": "passed", "checks": ["fresh_notebook_execution", "app_startup"]}
    fresh = {"status": "passed", "files_sha256": current,
             "sections": {"text": {"status": "passed", "measurement": 99}}}
    monkeypatch.setattr(verifier.subprocess, "run",
                        lambda *args, **kwargs: SimpleNamespace(
                            returncode=0, stdout=json.dumps(native), stderr=""))
    monkeypatch.setattr(verifier, "reverify_text_science", lambda *args: fresh)
    runtime = tmp_path / "src/agilab/agent_runtime/notebook_execution_verifier.py"
    runtime.parent.mkdir(parents=True)
    runtime.write_text("fresh_native_verifier = True\n")
    monkeypatch.setattr(verifier, "ROOT", tmp_path)
    verifier.verify_and_refresh(project)
    report = json.loads((project / "result.json").read_text())
    migration = report["native_ui_migration"]
    assert migration["original_verification"] == original["native_ui_migration"]["original_verification"]
    assert migration["original_files"] == original["native_ui_migration"]["original_files"]
    assert report["verification"]["text"]["measurement"] == 99
    assert migration["original_verification"]["text"]["measurement"] == 42
    assert migration["current_scientific_verification"] == fresh
    assert migration["scientific_proof_retention"]["sections"] == []
    assert migration["scientific_proof_retention"]["reverified_sections"] == ["text"]
    assert report["seconds"] == 17 and report["source"] == original["source"]
