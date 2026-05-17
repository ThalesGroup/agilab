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


def _extract_marked_json(stdout: str, marker: str) -> dict[str, object]:
    prefix = f"{marker}="
    for line in reversed(stdout.splitlines()):
        if line.startswith(prefix):
            payload = json.loads(line[len(prefix):])
            assert isinstance(payload, dict)
            return payload
    raise AssertionError(f"missing {marker} marker in output:\n{stdout[-4000:]}")


def _run_clone_notebook_import_proof(clone_root: Path) -> dict[str, object]:
    notebook_home = clone_root / "home-notebook-import"
    env = {
        **os.environ,
        "HOME": str(notebook_home),
        "AGILAB_DISABLE_BACKGROUND_SERVICES": "1",
        "AGI_CLUSTER_SHARE": str(notebook_home / "clustershare" / "agi"),
        "AGI_LOCAL_SHARE": str(notebook_home / "localshare"),
        "OPENAI_API_KEY": "sk-test-source-clone-notebook-proof-000000000000",
        "PYTHONUNBUFFERED": "1",
    }
    for key in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "UV_RUN_RECURSION_DEPTH"):
        env.pop(key, None)
    proof_code = r"""
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

from agi_env import AgiEnv

root = Path.cwd()
marker = "NOTEBOOK_IMPORT_RELEASE_SMOKE"
project_page = root / "src/agilab/pages/1_PROJECT.py"
spec = importlib.util.spec_from_file_location("agilab_project_notebook_release_smoke", project_page)
if spec is None or spec.loader is None:
    raise RuntimeError(f"unable to load PROJECT page from {project_page}")
project_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = project_module
spec.loader.exec_module(project_module)

cluster_share = Path(os.environ["AGI_CLUSTER_SHARE"]).expanduser()
local_share = Path(os.environ["AGI_LOCAL_SHARE"]).expanduser()
cluster_share.mkdir(parents=True, exist_ok=True)
local_share.mkdir(parents=True, exist_ok=True)

env = AgiEnv(apps_path=root / "src/agilab/apps", app="flight_telemetry_project", verbose=1)
sample = project_module._notebook_import_sample_module.get_sample_notebook("flight_telemetry")
notebook_bytes = project_module._notebook_import_sample_module.read_sample_notebook_bytes("flight_telemetry")
uploaded = SimpleNamespace(
    name=sample.download_name,
    type=project_module._notebook_import_sample_module.SAMPLE_NOTEBOOK_MIME,
    getvalue=lambda: notebook_bytes,
)
create_result = project_module._create_project_from_notebook_action(
    env,
    template_source=sample.recommended_template,
    raw_project_name=sample.project_name_hint,
    uploaded_notebook=uploaded,
    clone_env_strategy="detach_venv",
)
if create_result.status != "success":
    print(marker + "=" + json.dumps({
        "status": "fail",
        "phase": "create",
        "title": create_result.title,
        "detail": create_result.detail,
    }, sort_keys=True))
    raise SystemExit(1)

project_name = str(create_result.data["new_name"])
active_app = root / "src/agilab/apps" / project_name
expected_files = [
    "lab_stages.toml",
    "notebook_import_contract.json",
    "notebook_import_pipeline_view.json",
    "notebook_import_view_plan.json",
    "notebooks/source/flight_telemetry_from_notebook.ipynb",
    "src/flight_telemetry_from_notebook/flight_telemetry_from_notebook.py",
    "src/flight_telemetry_from_notebook_worker/flight_telemetry_from_notebook_worker.py",
]
missing_files = [name for name in expected_files if not (active_app / name).is_file()]
contract = json.loads((active_app / "notebook_import_contract.json").read_text(encoding="utf-8"))
stages = contract.get("stages", [])
if missing_files:
    print(marker + "=" + json.dumps({
        "status": "fail",
        "phase": "project_files",
        "project_name": project_name,
        "missing_files": missing_files,
    }, sort_keys=True))
    raise SystemExit(1)

payload = {
    "status": "pass",
    "project_name": project_name,
    "source_notebook": str(create_result.data["source_notebook"]),
    "stage_count": int(create_result.data["notebook_import_cell_count"]),
    "contract_schema": str(contract.get("schema")),
    "contract_stage_count": len(stages) if isinstance(stages, list) else 0,
    "runtime_roles": [stage.get("runtime_role") for stage in stages] if isinstance(stages, list) else [],
}
print(marker + "=" + json.dumps(payload, sort_keys=True))
"""
    log_path = clone_root / ".notebook-import-release-smoke.log"
    with log_path.open("w", encoding="utf-8") as log_stream:
        completed = subprocess.run(
            [
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "--extra",
                "ui",
                "python",
                "-c",
                proof_code,
            ],
            cwd=clone_root,
            check=False,
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            timeout=8 * 60,
        )
    output = log_path.read_text(encoding="utf-8", errors="replace")
    if completed.returncode:
        tail = "\n".join(output.splitlines()[-80:])
        raise AssertionError(
            f"notebook import release smoke failed with {completed.returncode}; "
            f"log={log_path}\n{tail}"
        )
    payload = _extract_marked_json(output, "NOTEBOOK_IMPORT_RELEASE_SMOKE")
    project_name = str(payload["project_name"])
    active_app = clone_root / "src" / "agilab" / "apps" / project_name

    install_log = clone_root / ".notebook-import-release-install.log"
    with install_log.open("w", encoding="utf-8") as log_stream:
        install = subprocess.run(
            [
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "--extra",
                "ui",
                "python",
                str(clone_root / "src" / "agilab" / "apps" / "install.py"),
                str(active_app),
                "--verbose",
                "1",
            ],
            cwd=clone_root,
            check=False,
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            timeout=8 * 60,
        )
    payload["install_returncode"] = install.returncode
    if install.returncode:
        tail = "\n".join(install_log.read_text(encoding="utf-8", errors="replace").splitlines()[-80:])
        raise AssertionError(
            f"notebook import install smoke failed with {install.returncode}; "
            f"log={install_log}\n{tail}"
        )

    return payload


def test_full_regression_passes_from_a_fresh_source_clone(tmp_path: Path) -> None:
    original_sys_path = list(sys.path)
    clone_root = _materialize_fresh_source_clone(tmp_path)
    try:
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
    finally:
        sys.path[:] = original_sys_path


@pytest.mark.release_proof
@pytest.mark.skipif(
    os.environ.get(RELEASE_PROOF_ENV) != "1",
    reason=f"set {RELEASE_PROOF_ENV}=1 to run the slow fresh-clone install proof",
)
def test_newcomer_first_proof_passes_from_fresh_source_clone(tmp_path: Path) -> None:
    clone_root = _materialize_fresh_source_clone(tmp_path)
    proof_payload = _run_clone_newcomer_proof(clone_root)
    notebook_payload = _run_clone_notebook_import_proof(clone_root)

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
    assert notebook_payload["status"] == "pass"
    assert notebook_payload["project_name"] == "flight_telemetry_from_notebook_project"
    assert notebook_payload["source_notebook"] == "notebooks/source/flight_telemetry_from_notebook.ipynb"
    assert notebook_payload["stage_count"] == 2
    assert notebook_payload["install_returncode"] == 0
    assert notebook_payload["contract_schema"] == "agilab.notebook_import_contract.v1"
    assert notebook_payload["contract_stage_count"] == 2
    assert notebook_payload["runtime_roles"] == ["manager", "manager"]
