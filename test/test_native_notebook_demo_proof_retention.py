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
