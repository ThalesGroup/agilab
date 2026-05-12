from __future__ import annotations

import importlib.util
import io
import subprocess
import sys
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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
