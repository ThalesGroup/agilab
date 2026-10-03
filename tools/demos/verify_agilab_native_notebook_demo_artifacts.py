#!/usr/bin/env python3
"""Verify migrated notebook demos and refresh their SHA-bound public receipts."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
DEMOS = (
    "notebook_agent_demo", "notebook_agent_local_demo", "notebook_agent_rtx_demo",
    "free_threading_demo", "free_threading_demo_astra", "free_threading_demo_rtx",
    "milp_energy_demo", "milp_energy_demo_astra", "milp_energy_demo_rtx",
    "text_notebook_demo", "text_notebook_demo_astra", "text_notebook_demo_rtx",
    "forecast_notebook_demo", "forecast_notebook_demo_astra", "forecast_notebook_demo_rtx",
)
SCIENTIFIC_SECTIONS = ("workflow", "text", "forecast", "free_threading", "milp_energy")
INTERFACE_FILES = {"app.py", "pyproject.toml", "requirements.txt", "README.md"}


def hashes(project: Path, names) -> dict[str, str]:
    result = {}
    for name in names:
        if not isinstance(name, str) or Path(name).is_absolute() or ".." in Path(name).parts:
            raise ValueError("Invalid demo artifact path.")
        path = project / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Expected a regular demo artifact: {path}")
        result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def retain_scientific_proofs(project: Path, report: dict, verification: dict, current: dict,
                            test_verification: dict | None = None) -> tuple[dict, dict]:
    """Retain historical science evidence only for the identical scientific artifacts."""
    migration = report.get("native_ui_migration", {})
    original = migration.get("original_verification", report.get("verification", {}))
    baseline = migration.get("original_files", report.get("files", {}))
    sections = [name for name in SCIENTIFIC_SECTIONS if name in original]
    # These fields describe the historical autonomous build. Current native
    # acceptance is recorded separately, so its measurements cannot overwrite
    # the original independent scientific result or build verification.
    combined = deepcopy(original)
    tests = test_verification if test_verification is not None else migration.get("interface_test_verification", {})
    reverified = []
    if not sections:
        return combined, {}
    if set(baseline) != set(current):
        raise ValueError("Historical science evidence requires the same artifact inventory.")
    scientific = {name: digest for name, digest in baseline.items() if name not in INTERFACE_FILES}
    for name, digest in scientific.items():
        if current[name] == digest:
            continue
        # The Astra test suite only changed the UI harness import. Reversing
        # that exact import must reproduce its originally sealed bytes.
        if name == "tests.py":
            proof = tests.get(name, {})
            if proof.get("status") == "passed" and proof.get("sha256") == current[name]:
                reverified.append(name)
                continue
            source = (project / name).read_bytes()
            previous = source.replace(b"from agi_web.testing import AppTest",
                                      b"from streamlit.testing.v1 import AppTest")
            if hashlib.sha256(previous).hexdigest() == digest:
                continue
        raise ValueError(f"Scientific artifact changed; an independent verification is required: {name}")
    for name in sections:
        proof = original[name]
        if not isinstance(proof, dict) or proof.get("status") != "passed":
            raise ValueError(f"Historical scientific verification was not passed: {name}")
        combined[name] = deepcopy(proof)
    retained = {
        "scope": "historical independent scientific verification; unchanged scientific sources and data",
        "sections": sections,
        "original_artifacts_sha256": scientific,
        "current_artifacts_sha256": {name: current[name] for name in scientific},
        "excluded_interface_and_dependency_files": sorted(INTERFACE_FILES & set(baseline)),
        "independently_reverified_test_files": reverified,
    }
    return combined, retained


def restore_scientific_proofs(project: Path) -> dict:
    """Repair a native receipt without repeating its already completed execution."""
    receipt = project / "result.json"
    if receipt.is_symlink() or not receipt.is_file():
        raise ValueError("Expected a regular existing public receipt.")
    report = json.loads(receipt.read_text())
    migration = report.get("native_ui_migration", {})
    if (report.get("status") != "passed" or report.get("verification", {}).get("status") != "passed"
            or migration.get("interface_runtime") != "agi_web.python_ui"):
        raise ValueError("A passed native migration receipt is required.")
    current = hashes(project, report["files"])
    changed = {name for name, digest in current.items() if report["files"][name] != digest}
    if changed - {"README.md"}:
        raise ValueError("Native artifacts changed after their verification.")
    native = migration.get("native_verification", report["verification"])
    combined, retained = retain_scientific_proofs(project, report, native, current)
    migration.update(native_verification=deepcopy(native), scientific_proof_retention=retained)
    if changed:
        migration["documentation_refresh"] = {
            "scope": "documentation only; executable artifacts retain the completed native verification",
            "files_sha256": {name: current[name] for name in changed},
            "refreshed_at_utc": datetime.now(timezone.utc).isoformat(),
        }
    report.update(files=current, verification=combined, native_ui_migration=migration)
    receipt.write_text(json.dumps(report, indent=2) + "\n")
    return {"project": project.name, "status": "passed", "retained_scientific_sections": retained.get("sections", [])}


def verify_and_refresh(project: Path) -> dict:
    receipt = project / "result.json"
    if receipt.is_symlink() or not receipt.is_file():
        raise ValueError("Expected a regular existing public receipt.")
    report = json.loads(receipt.read_text())
    if report.get("schema") != "agilab.notebook_agent.public_demo.v1" or report.get("status") != "passed":
        raise ValueError("Only an existing verified public demo can be migrated.")
    names = report.get("files")
    if not isinstance(names, dict) or not {"app.py", "solution.ipynb"}.issubset(names):
        raise ValueError("Expected a complete existing demo artifact manifest.")
    before = hashes(project, names)
    verifier_module = "notebook_verifier" if project.name.startswith("notebook_agent") else "notebook_execution_verifier"
    metadata_fixture = False
    test_verification = deepcopy(report.get("native_ui_migration", {}).get("interface_test_verification", {}))
    with tempfile.TemporaryDirectory(prefix="agilab-native-demo-validation-") as temporary:
        checkout = Path(temporary) / "project"
        shutil.copytree(project, checkout, ignore=shutil.ignore_patterns("__pycache__", ".venv", ".pytest_cache"))
        if verifier_module == "notebook_execution_verifier" and not (checkout / "pyproject.toml").exists():
            metadata_fixture = True
            (checkout / "pyproject.toml").write_text(f'[project]\nname="{project.name.replace("_", "-")}"\nversion="0.0.0"\n')
        baseline = report.get("native_ui_migration", {}).get("original_files", report["files"])
        if "tests.py" in baseline and before["tests.py"] != baseline["tests.py"]:
            source = (checkout / "tests.py").read_bytes()
            old_harness = source.replace(b"from agi_web.testing import AppTest",
                                         b"from streamlit.testing.v1 import AppTest")
            prior_test = test_verification.get("tests.py", {})
            if (hashlib.sha256(old_harness).hexdigest() != baseline["tests.py"] and
                    not (prior_test.get("status") == "passed" and prior_test.get("sha256") == before["tests.py"])):
                start = time.monotonic()
                tested = subprocess.run([sys.executable, "tests.py"], cwd=checkout,
                                        text=True, capture_output=True, timeout=300)
                if tested.returncode:
                    raise ValueError(f"Changed demo tests failed for {project.name}: {tested.stderr[-3000:]}")
                test_verification["tests.py"] = {
                    "status": "passed", "sha256": before["tests.py"],
                    "command": "python tests.py", "checkout": "fresh temporary project copy",
                    "stdout_sha256": hashlib.sha256(tested.stdout.encode()).hexdigest(),
                    "stderr_sha256": hashlib.sha256(tested.stderr.encode()).hexdigest(),
                    "seconds": round(time.monotonic() - start, 3),
                    "summary": tested.stderr.strip().splitlines()[-3:],
                }
        result = subprocess.run([sys.executable, "-m", f"agilab.agent_runtime.{verifier_module}"],
                                cwd=checkout, check=False, text=True, capture_output=True)
        if result.returncode:
            detail = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else result.stderr.strip()
            raise ValueError(f"Native demo verification failed for {project.name}: {detail}")
    verification = json.loads(result.stdout.strip().splitlines()[-1])
    if verification.get("status") != "passed":
        raise ValueError("Native notebook verification did not pass.")
    if hashes(project, names) != before:
        raise ValueError("Demo source changed while it was being verified.")
    verifier = ROOT / "src/agilab/agent_runtime" / f"{verifier_module}.py"
    old_migration = report.get("native_ui_migration", {})
    migration = {
        "schema": "agilab.native_notebook_demo_migration.v1",
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "interface_runtime": "agi_web.python_ui",
        "original_files": old_migration.get("original_files", report.get("files", {})),
        "original_verification": old_migration.get("original_verification", report.get("verification", {})),
        "verifier_sha256": hashlib.sha256(verifier.read_bytes()).hexdigest(),
        "verification_checkout": "fresh temporary copy; canonical project unchanged",
        "temporary_project_metadata": metadata_fixture,
        "native_verification": deepcopy(verification),
        "interface_test_verification": test_verification,
    }
    combined, retained = retain_scientific_proofs(project, report, verification, before, test_verification)
    migration["scientific_proof_retention"] = retained
    # The original run identity, source credit and build timing stay historical.
    # The current executable artifact seal and the separate native acceptance
    # result are refreshed; the autonomous build verification stays historical.
    report.update(files=before, verification=combined, native_ui_migration=migration)
    receipt.write_text(json.dumps(report, indent=2) + "\n")
    return {"project": project.name, "status": "passed", "files": before,
            "checks": verification["checks"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", choices=DEMOS, action="append")
    parser.add_argument("--restore-scientific-proofs", action="store_true",
                        help="Restore SHA-verified historical science sections after a completed native verification.")
    args = parser.parse_args()
    operation = restore_scientific_proofs if args.restore_scientific_proofs else verify_and_refresh
    reports = [operation(ROOT / "src/agilab/demos/resources" / demo) for demo in (args.demo or DEMOS)]
    print(json.dumps(reports, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
