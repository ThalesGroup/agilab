from __future__ import annotations

import json
import importlib.util
import io
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
RELEASE_PROOF_ENV = "AGILAB_RUN_RELEASE_PROOF_SLOW"


def _load_module(path: Path, name: str):
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _materialize_fresh_source_clone(tmp_path: Path) -> Path:
    clone_root = tmp_path / "source-clone"
    clone_root.mkdir()
    completed = subprocess.run(
        ["git", "archive", "--format=tar", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    with tarfile.open(fileobj=io.BytesIO(completed.stdout)) as archive:
        archive.extractall(clone_root, filter="data")
    return clone_root


def _run_clone_newcomer_proof(clone_root: Path) -> dict[str, object]:
    active_app = clone_root / "src" / "agilab" / "apps" / "builtin" / "flight_telemetry_project"
    env = {
        **os.environ,
        "HOME": str(clone_root / "home"),
        "AGILAB_DISABLE_BACKGROUND_SERVICES": "1",
        "OPENAI_API_KEY": "sk-test-source-clone-proof-000000000000",
        "PYTHONUNBUFFERED": "1",
    }
    # A fresh source clone proof must not inherit the caller's active venv.
    # Nested uv commands intentionally choose the clone/app environments.
    for key in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "UV_RUN_RECURSION_DEPTH"):
        env.pop(key, None)
    completed = subprocess.run(
        [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            str(clone_root / "tools" / "newcomer_first_proof.py"),
            "--active-app",
            str(active_app),
            "--with-install",
            "--json",
            "--no-manifest",
        ],
        cwd=clone_root,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return json.loads(completed.stdout)


def test_full_regression_passes_from_a_fresh_source_clone(tmp_path: Path) -> None:
    clone_root = _materialize_fresh_source_clone(tmp_path)
    stray_project_src = clone_root / "temporary_demo_project" / "src"
    stray_project_src.mkdir(parents=True)

    release_module = _load_module(
        clone_root / "tools" / "release_proof_report.py",
        "agilab_release_proof_report_clone_test",
    )
    public_module = _load_module(
        clone_root / "tools" / "public_proof_scenarios.py",
        "agilab_public_proof_scenarios_clone_test",
    )
    compatibility_module = _load_module(
        clone_root / "tools" / "compatibility_report.py",
        "agilab_compatibility_report_clone_test",
    )
    conf_module = _load_module(
        clone_root / "docs" / "source" / "conf.py",
        "agilab_docs_conf_clone_test",
    )

    assert conf_module.project_root == clone_root
    assert conf_module._is_generated_root_project_src(stray_project_src) is True

    release_report = release_module.build_report(
        manifest_path=clone_root / "docs" / "source" / "data" / "release_proof.toml",
        output_path=clone_root / "docs" / "source" / "release-proof.rst",
        repo_root=clone_root,
        check_github_runs=False,
    )
    public_report = public_module.build_report(repo_root=clone_root)
    compatibility_report = compatibility_module.build_report(
        repo_root=clone_root,
        include_default_manifests=False,
    )

    assert release_report["status"] == "pass"
    assert release_report["summary"]["failed"] == 0
    assert release_report["checks"][-1]["id"] == "rendered_page"
    assert public_report["status"] == "pass"
    assert public_report["summary"]["failed"] == 0
    assert compatibility_report["status"] == "pass"
    assert compatibility_report["summary"]["failed"] == 0
    assert compatibility_report["summary"]["manifest_evidence"]["load_failures"] == 0


@pytest.mark.release_proof
@pytest.mark.skipif(
    os.environ.get(RELEASE_PROOF_ENV) != "1",
    reason=f"set {RELEASE_PROOF_ENV}=1 to run the slow fresh-clone install proof",
)
def test_newcomer_first_proof_passes_from_fresh_source_clone(tmp_path: Path) -> None:
    clone_root = _materialize_fresh_source_clone(tmp_path)
    proof_payload = _run_clone_newcomer_proof(clone_root)

    assert proof_payload["active_app"] == str(clone_root / "src" / "agilab" / "apps" / "builtin" / "flight_telemetry_project")
    assert proof_payload["with_install"] is True
    assert proof_payload["success"] is True
    assert proof_payload["passed_steps"] == proof_payload["expected_steps"] == 4
    assert [step["label"] for step in proof_payload["steps"]] == [
        "preinit smoke",
        "source ui smoke",
        "flight install smoke",
        "seeded script check",
    ]
