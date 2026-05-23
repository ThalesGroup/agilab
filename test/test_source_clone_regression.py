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

    execute_code = r"""
import asyncio
import json
import os
from pathlib import Path
import tomllib

from agi_cluster.agi_distributor import AGI, RunRequest
from agi_env import AgiEnv
from streamlit.testing.v1 import AppTest

root = Path.cwd()
marker = "NOTEBOOK_IMPORT_EXECUTE_ANALYSIS_SMOKE"
project_name = os.environ["AGILAB_NOTEBOOK_IMPORT_PROJECT"]
apps_path = root / "src/agilab/apps"


def _resolve_shared_path(env: AgiEnv, raw_path: object) -> Path | None:
    if raw_path in (None, ""):
        return None
    path = Path(str(raw_path)).expanduser()
    if path.is_absolute():
        return path
    return env.resolve_share_path(path)


async def main() -> None:
    app_env = AgiEnv(apps_path=apps_path, app=project_name, verbose=1)
    app_env.init_done = True
    settings = tomllib.loads(Path(app_env.app_settings_file).read_text(encoding="utf-8"))
    run_args = dict(settings.get("args") or {})
    data_in = run_args.pop("data_in", None)
    data_out = run_args.pop("data_out", None)
    reset_target = run_args.pop("reset_target", None)
    request = RunRequest(
        params=run_args,
        data_in=data_in,
        data_out=data_out,
        reset_target=reset_target,
        mode=AGI.PYTHON_MODE,
        scheduler="127.0.0.1",
        workers={"127.0.0.1": 1},
    )
    result = await AGI.run(app_env, request=request)
    output_root = _resolve_shared_path(app_env, data_out)
    output_files = []
    if output_root is not None and output_root.exists():
        output_files = sorted(
            path.relative_to(output_root).as_posix()
            for path in output_root.rglob("*")
            if path.is_file()
        )

    analysis_env = AgiEnv(apps_path=apps_path, app=project_name, verbose=0)
    analysis_env.init_done = True
    analysis = AppTest.from_file(str(root / "src/agilab/pages/4_ANALYSIS.py"), default_timeout=90)
    analysis.query_params["current_page"] = "main"
    analysis.session_state["env"] = analysis_env
    analysis.run(timeout=90)
    analysis_exceptions = [str(item) for item in analysis.exception]
    sidebar_markdown = "\n".join(str(item.value) for item in analysis.sidebar.markdown)
    notebook_label = "source/flight_telemetry_from_notebook.ipynb"

    print(marker + "=" + json.dumps({
        "status": "pass" if not analysis_exceptions and output_files else "fail",
        "project_name": project_name,
        "run_result_type": type(result).__name__,
        "run_mode": int(request.mode),
        "data_in": str(data_in),
        "data_out": str(data_out),
        "output_root": str(output_root) if output_root is not None else "",
        "output_files": output_files,
        "analysis_exception_count": len(analysis_exceptions),
        "analysis_exceptions": analysis_exceptions,
        "analysis_has_notebook_link": (
            "current_notebook=" in sidebar_markdown and notebook_label in sidebar_markdown
        ),
        "analysis_has_view_links": "agilab-analysis-view-links" in sidebar_markdown,
    }, sort_keys=True))


asyncio.run(main())
"""
    execute_log = clone_root / ".notebook-import-release-execute-analysis.log"
    execute_env = {**env, "AGILAB_NOTEBOOK_IMPORT_PROJECT": project_name}
    with execute_log.open("w", encoding="utf-8") as log_stream:
        execute = subprocess.run(
            [
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "--extra",
                "ui",
                "python",
                "-c",
                execute_code,
            ],
            cwd=clone_root,
            check=False,
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            text=True,
            env=execute_env,
            timeout=8 * 60,
        )
    payload["execute_returncode"] = execute.returncode
    execute_output = execute_log.read_text(encoding="utf-8", errors="replace")
    if execute.returncode:
        tail = "\n".join(execute_output.splitlines()[-100:])
        raise AssertionError(
            f"notebook import execute/analysis smoke failed with {execute.returncode}; "
            f"log={execute_log}\n{tail}"
        )
    execute_payload = _extract_marked_json(
        execute_output,
        "NOTEBOOK_IMPORT_EXECUTE_ANALYSIS_SMOKE",
    )
    payload["execute_analysis"] = execute_payload
    if execute_payload.get("status") != "pass":
        tail = "\n".join(execute_output.splitlines()[-100:])
        raise AssertionError(
            "notebook import execute/analysis smoke did not pass; "
            f"payload={execute_payload!r}; log={execute_log}\n{tail}"
        )

    export_code = r"""
import json
import os
from pathlib import Path

from agi_env import AgiEnv
from agilab.notebook_export_support import (
    build_notebook_export_context,
    notebook_export_manifest_path,
    verify_notebook_export_manifest,
)
from agilab.pipeline_editor import refresh_notebook_export

root = Path.cwd()
marker = "NOTEBOOK_IMPORT_EXPORT_HANDOFF_SMOKE"
project_name = os.environ["AGILAB_NOTEBOOK_IMPORT_PROJECT"]
apps_path = root / "src/agilab/apps"
app_root = apps_path / project_name
stages_file = app_root / "lab_stages.toml"

app_env = AgiEnv(apps_path=apps_path, app=project_name, verbose=0)
app_env.init_done = True
export_context = build_notebook_export_context(
    app_env,
    project_name,
    stages_file,
    project_name=project_name,
)
notebook_path = refresh_notebook_export(stages_file, export_context=export_context)
if notebook_path is None:
    print(marker + "=" + json.dumps({"status": "fail", "phase": "refresh"}, sort_keys=True))
    raise SystemExit(1)

manifest_path = notebook_export_manifest_path(notebook_path)
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
notebook = json.loads(Path(notebook_path).read_text(encoding="utf-8"))
verification = verify_notebook_export_manifest(notebook_path)
stage_records = [stage for stage in manifest.get("stages", []) if isinstance(stage, dict)]
stage_cells = [cell for cell in manifest.get("stage_cells", []) if isinstance(cell, dict)]
source_cells = [cell for cell in stage_cells if cell.get("kind") == "source"]
runner_cells = [cell for cell in stage_cells if cell.get("kind") == "runner"]
stage_imports = [
    stage.get("notebook_import", {})
    for stage in stage_records
    if isinstance(stage.get("notebook_import", {}), dict)
]
source_imports = [
    cell.get("notebook_import", {})
    for cell in source_cells
    if isinstance(cell.get("notebook_import", {}), dict)
]

compile_errors = []
for index, cell in enumerate(notebook.get("cells", [])):
    if not isinstance(cell, dict) or cell.get("cell_type") != "code":
        continue
    source = cell.get("source", [])
    source_text = source if isinstance(source, str) else "".join(str(line) for line in source)
    try:
        compile(source_text, f"{notebook_path}#cell-{index}", "exec")
    except SyntaxError as exc:
        compile_errors.append(f"cell-{index}: {exc}")

artifact_references = sorted(
    {
        str(artifact)
        for metadata in stage_imports
        for artifact in metadata.get("artifact_references", [])
        if str(artifact)
    }
)
env_hints = sorted(
    {
        str(hint)
        for metadata in stage_imports
        for hint in metadata.get("env_hints", [])
        if str(hint)
    }
)
source_cell_indexes = [
    metadata.get("source_cell_index")
    for metadata in stage_imports
    if metadata.get("source_cell_index") is not None
]
source_notebooks = sorted(
    {
        str(metadata.get("source_notebook"))
        for metadata in stage_imports
        if str(metadata.get("source_notebook", ""))
    }
)
runtime_roles = [str(stage.get("runtime_role", "")) for stage in stage_records]
mirror_path_text = str(manifest.get("mirror_path", "") or "")
mirror_exists = bool(mirror_path_text and Path(mirror_path_text).is_file())
handoff_path_text = str(manifest.get("handoff_path", "") or "")
handoff_text = Path(handoff_path_text).read_text(encoding="utf-8") if handoff_path_text else ""

checks = {
    "verification_ok": bool(verification.get("ok")),
    "stage_count": manifest.get("stage_count") == 2,
    "source_cell_count": len(source_cells) == 2,
    "runner_cell_count": len(runner_cells) == 2,
    "stage_import_count": len(stage_imports) == 2,
    "source_import_count": len(source_imports) == 2,
    "source_cell_indexes": source_cell_indexes == [2, 4],
    "artifact_references": {
        "data/flights.csv",
        "artifacts/summary.json",
    }.issubset(set(artifact_references)),
    "env_hints": {"pandas", "pathlib"}.issubset(set(env_hints)),
    "runtime_roles": runtime_roles == ["manager", "manager"],
    "source_notebook": source_notebooks == ["notebooks/source/flight_telemetry_from_notebook.ipynb"],
    "mirror_exists": mirror_exists,
    "handoff_has_validation": "validate_agilab_export()" in handoff_text,
    "compile": not compile_errors,
}
failed_checks = sorted(name for name, ok in checks.items() if not ok)
print(marker + "=" + json.dumps({
    "status": "pass" if not failed_checks else "fail",
    "project_name": project_name,
    "notebook_path": str(notebook_path),
    "manifest_path": str(manifest_path),
    "handoff_path": handoff_path_text,
    "mirror_path": mirror_path_text,
    "manifest_schema": str(manifest.get("schema", "")),
    "stage_count": manifest.get("stage_count"),
    "source_cell_count": len(source_cells),
    "runner_cell_count": len(runner_cells),
    "source_cell_indexes": source_cell_indexes,
    "artifact_references": artifact_references,
    "env_hints": env_hints,
    "runtime_roles": runtime_roles,
    "source_notebooks": source_notebooks,
    "verification_ok": bool(verification.get("ok")),
    "verification_failed_checks": [
        str(check.get("id", ""))
        for check in verification.get("checks", [])
        if isinstance(check, dict) and check.get("status") != "pass"
    ],
    "failed_checks": failed_checks,
    "compile_errors": compile_errors,
}, sort_keys=True))
"""
    export_log = clone_root / ".notebook-import-release-export-handoff.log"
    with export_log.open("w", encoding="utf-8") as log_stream:
        export = subprocess.run(
            [
                "uv",
                "--preview-features",
                "extra-build-dependencies",
                "run",
                "--extra",
                "ui",
                "python",
                "-c",
                export_code,
            ],
            cwd=clone_root,
            check=False,
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            text=True,
            env=execute_env,
            timeout=4 * 60,
        )
    payload["export_returncode"] = export.returncode
    export_output = export_log.read_text(encoding="utf-8", errors="replace")
    if export.returncode:
        tail = "\n".join(export_output.splitlines()[-100:])
        raise AssertionError(
            f"notebook import export handoff smoke failed with {export.returncode}; "
            f"log={export_log}\n{tail}"
        )
    export_payload = _extract_marked_json(
        export_output,
        "NOTEBOOK_IMPORT_EXPORT_HANDOFF_SMOKE",
    )
    payload["export_handoff"] = export_payload
    if export_payload.get("status") != "pass":
        tail = "\n".join(export_output.splitlines()[-100:])
        raise AssertionError(
            "notebook import export handoff smoke did not pass; "
            f"payload={export_payload!r}; log={export_log}\n{tail}"
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
    assert notebook_payload["execute_returncode"] == 0
    assert notebook_payload["export_returncode"] == 0
    assert notebook_payload["contract_schema"] == "agilab.notebook_import_contract.v1"
    assert notebook_payload["contract_stage_count"] == 2
    assert notebook_payload["runtime_roles"] == ["manager", "manager"]
    execute_analysis = notebook_payload["execute_analysis"]
    assert execute_analysis["project_name"] == "flight_telemetry_from_notebook_project"
    assert execute_analysis["data_in"] == "flight_telemetry_from_notebook/dataset"
    assert execute_analysis["data_out"] == "flight_telemetry_from_notebook/dataframe"
    assert execute_analysis["run_mode"] == 1
    assert execute_analysis["analysis_exception_count"] == 0
    assert execute_analysis["analysis_has_notebook_link"] is True
    assert execute_analysis["analysis_has_view_links"] is True
    assert any(
        output_file.endswith((".parquet", ".csv", ".json"))
        for output_file in execute_analysis["output_files"]
    )
    export_handoff = notebook_payload["export_handoff"]
    assert export_handoff["status"] == "pass"
    assert export_handoff["project_name"] == "flight_telemetry_from_notebook_project"
    assert export_handoff["manifest_schema"] == "agilab.notebook_export_manifest.v1"
    assert export_handoff["stage_count"] == 2
    assert export_handoff["source_cell_count"] == 2
    assert export_handoff["runner_cell_count"] == 2
    assert export_handoff["source_cell_indexes"] == [2, 4]
    assert export_handoff["runtime_roles"] == ["manager", "manager"]
    assert export_handoff["source_notebooks"] == [
        "notebooks/source/flight_telemetry_from_notebook.ipynb"
    ]
    assert {"data/flights.csv", "artifacts/summary.json"}.issubset(
        set(export_handoff["artifact_references"])
    )
    assert {"pandas", "pathlib"}.issubset(set(export_handoff["env_hints"]))
    assert export_handoff["verification_ok"] is True
    assert export_handoff["verification_failed_checks"] == []
    assert export_handoff["failed_checks"] == []
    assert export_handoff["compile_errors"] == []
