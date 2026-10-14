"""Recovery freezes actual native command evidence and notebook build inputs."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys

import pytest

from agilab.agent_runtime.agent_run import create_agent_run_config, run_agent_command
from agilab.agent_runtime import notebook_build_checkpoint as checkpoint
from agilab.evidence.evidence_contract import sha256_file, sha256_payload


@pytest.fixture
def completed_build(tmp_path):
    project = tmp_path / "fixture_project"
    source_dir = project / "source"
    source_dir.mkdir(parents=True)
    original = source_dir / "original.ipynb"
    original.write_text('{"nbformat":4,"cells":[]}')
    (project / "solution.ipynb").write_text(original.read_text())
    (project / "app.py").write_text("answer = 42\n")
    (project / "helpers.py").write_text("ANSWER = 42\n")
    (project / "data").mkdir()
    data = project / "data" / "input.csv"
    data.write_text("answer\n42\n")
    source = {"source_kind": "local", "sha256": sha256_file(original)}
    prerequisites = {
        "safe_to_build": True,
        "supplied_inputs": [
            {
                "path": "data/input.csv",
                "bytes": data.stat().st_size,
                "sha256": sha256_file(data),
            }
        ],
    }
    (source_dir / "prerequisites.json").write_text(json.dumps(prerequisites))
    protected = {}
    for name in ("verify_app", "verify_workflow.py"):
        path = tmp_path / name
        path.write_text("# trusted controller verifier\n")
        protected[name] = sha256_file(path)
    result = run_agent_command(
        create_agent_run_config(
            [sys.executable, "-c", "print('native command completed')"],
            agent="checkpoint-fixture",
            label="Notebook recovery fixture",
            cwd=project,
            output_dir=tmp_path / "agent",
            timeout_seconds=30,
            permission_level="standard",
            metadata={"source_sha256": source["sha256"]},
        )
    )
    assert result.returncode == 0, result.manifest
    return tmp_path, {
        "project_name": project.name,
        "source": source,
        "prerequisites": prerequisites,
        "provider_manifest": result.manifest,
        "protected_files": protected,
        "seconds_before_verification": 1.25,
    }


def capture(completed_build):
    root, arguments = completed_build
    return checkpoint.capture_checkpoint(root, **arguments)


def persist_manifest(root, manifest):
    (root / "agent" / "agent_run_manifest.json").write_text(json.dumps(manifest))


def test_native_checkpoint_roundtrip_freezes_controller_metadata(completed_build):
    root, arguments = completed_build
    saved = capture(completed_build)
    assert saved == checkpoint.load_checkpoint(root)
    assert saved["schema"] == checkpoint.SCHEMA
    assert "fixture_project/helpers.py" in saved["project_files"]
    assert "fixture_project/data/input.csv" in saved["project_files"]
    arguments["source"]["sha256"] = "0" * 64
    arguments["prerequisites"]["safe_to_build"] = False
    assert checkpoint.load_checkpoint(root) == saved
    with pytest.raises(FileExistsError, match="already exists"):
        checkpoint.capture_checkpoint(root, **arguments)


@pytest.mark.parametrize("operation", ["change_data", "change_helper", "add", "remove"])
def test_generated_inventory_change_blocks_recovery(completed_build, operation):
    root, _ = completed_build
    capture(completed_build)
    project = root / "fixture_project"
    if operation == "change_data":
        (project / "data" / "input.csv").write_text("answer\n43\n")
    elif operation == "change_helper":
        (project / "helpers.py").write_text("ANSWER = 43\n")
    elif operation == "add":
        (project / "new.py").write_text("print('added')\n")
    else:
        (project / "helpers.py").unlink()
    with pytest.raises(ValueError, match="changed"):
        checkpoint.load_checkpoint(root)


def test_only_exact_derived_root_outputs_and_caches_may_change(completed_build):
    root, _ = completed_build
    capture(completed_build)
    project = root / "fixture_project"
    for name in (
        "results.json",
        "metrics.json",
        "lab_stages.toml",
        "notebook_import.json",
    ):
        (project / name).write_text("verification-derived output")
    cache = project / "__pycache__"
    cache.mkdir()
    (cache / "app.pyc").write_bytes(b"compiled cache")
    checkpoint.load_checkpoint(root)
    (project / "data" / "results.json").write_text("unrecorded nested input")
    with pytest.raises(ValueError, match="inventory changed"):
        checkpoint.load_checkpoint(root)


@pytest.mark.parametrize(
    "relative",
    [
        "verify_app",
        "fixture_project/source/original.ipynb",
        "fixture_project/source/prerequisites.json",
    ],
)
def test_protected_source_and_prerequisites_cannot_change(completed_build, relative):
    root, _ = completed_build
    capture(completed_build)
    (root / relative).write_text("changed")
    with pytest.raises(ValueError):
        checkpoint.load_checkpoint(root)


@pytest.mark.parametrize(
    "relative",
    ["agent/stdout.txt", "agent/agent_events.ndjson", "agent/agent_run_manifest.json"],
)
def test_native_provider_evidence_cannot_change(completed_build, relative):
    root, _ = completed_build
    capture(completed_build)
    with (root / relative).open("a") as stream:
        stream.write("changed")
    with pytest.raises(ValueError):
        checkpoint.load_checkpoint(root)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_capture",
        "timeout",
        "bool_returncode",
        "bool_process_returncode",
        "missing_hash",
        "missing_trace",
        "wrong_cwd",
        "wrong_source",
        "escape",
    ],
)
def test_incomplete_or_unbound_native_result_cannot_be_checkpointed(
    completed_build, mutation
):
    root, arguments = completed_build
    manifest = copy.deepcopy(arguments["provider_manifest"])
    if mutation == "missing_capture":
        del manifest["capture_outcome"]
    elif mutation == "timeout":
        manifest["capture_outcome"]["reason"] = "timeout"
    elif mutation == "bool_returncode":
        manifest["returncode"] = False
    elif mutation == "bool_process_returncode":
        manifest["capture_outcome"]["process_returncode"] = False
    elif mutation == "missing_hash":
        del manifest["artifacts"]["claim"]["sha256"]
    elif mutation == "missing_trace":
        del manifest["artifacts"]["agent_trace"]["events"]
    elif mutation == "wrong_cwd":
        manifest["command"]["cwd"] = str(root)
    elif mutation == "wrong_source":
        manifest["context"]["metadata"]["source_sha256"] = "0" * 64
    else:
        manifest["artifacts"]["stdout"]["path"] = str(root / "verify_app")
    persist_manifest(root, manifest)
    arguments["provider_manifest"] = manifest
    with pytest.raises(ValueError):
        capture(completed_build)
    assert not (root / checkpoint.CHECKPOINT_FILENAME).exists()


@pytest.mark.parametrize(
    "relative",
    [
        "fixture_project/new.py",
        "fixture_project/results.json",
        "fixture_project/__pycache__",
        "agent/alias",
    ],
)
def test_symlinks_are_rejected_even_for_excluded_outputs(completed_build, relative):
    root, _ = completed_build
    capture(completed_build)
    (root / relative).symlink_to(root / "verify_app")
    with pytest.raises(ValueError, match="symlinks"):
        checkpoint.load_checkpoint(root)


@pytest.mark.skipif(os.name == "nt", reason="FIFO files are a POSIX boundary")
def test_special_files_cannot_enter_project_inventory(completed_build):
    root, _ = completed_build
    capture(completed_build)
    os.mkfifo(root / "fixture_project" / "pipe")
    with pytest.raises(ValueError, match="special files"):
        checkpoint.load_checkpoint(root)


@pytest.mark.parametrize(
    "mutation", ["duplicate", "unknown", "project_escape", "protection_escape"]
)
def test_malformed_or_unsafe_checkpoint_is_rejected(completed_build, mutation):
    root, _ = completed_build
    payload = capture(completed_build)
    path = root / checkpoint.CHECKPOINT_FILENAME
    if mutation == "duplicate":
        raw = path.read_text()
        path.write_text(raw.replace('"schema":', '"schema": "duplicate", "schema":', 1))
    else:
        if mutation == "unknown":
            payload["unknown"] = True
        elif mutation == "project_escape":
            payload["project_name"] = "../fixture_project"
        else:
            payload["protected_files"] = {"../outside": "0" * 64}
        payload["sha256"] = sha256_payload(
            {k: v for k, v in payload.items() if k != "sha256"}
        )
        path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        checkpoint.load_checkpoint(root)


def test_runtime_drift_blocks_recovery(completed_build, monkeypatch):
    root, _ = completed_build
    saved = capture(completed_build)
    changed = {**saved["runtime"], "python_version": "other runtime"}
    monkeypatch.setattr(checkpoint, "_runtime", lambda: changed)
    with pytest.raises(ValueError, match="runtime or implementation changed"):
        checkpoint.load_checkpoint(root)


@pytest.mark.parametrize("prefix", ["prefix", "base_prefix"])
def test_rebound_python_environment_blocks_recovery(
    completed_build, monkeypatch, prefix
):
    root, _ = completed_build
    saved = capture(completed_build)
    monkeypatch.setattr(sys, prefix, str(root / "another_python_environment"))
    rebound = checkpoint._runtime()
    assert rebound["python_executable"] == saved["runtime"]["python_executable"]
    assert rebound["implementation_sha256"] == saved["runtime"]["implementation_sha256"]
    with pytest.raises(ValueError, match="runtime or implementation changed"):
        checkpoint.load_checkpoint(root)


def complete_files(root):
    names = [
        "result.json",
        "completion_receipt.json",
        "verification.log",
        "workflow_verification.log",
        "fixture_project/lab_stages.toml",
        "fixture_project/notebook_import.json",
        "fixture_project/results.json",
    ]
    for name in names:
        (root / name).write_text("successful verification evidence")
    (root / "result.json").write_text(
        json.dumps({"status": "passed", "project": str(root / "fixture_project")})
    )
    (root / "completion_receipt.json").write_text('{"status":"passed"}')
    return names


def test_completion_seal_preserves_snapshot_and_binds_success(completed_build):
    root, _ = completed_build
    original = capture(completed_build)
    names = complete_files(root)
    checkpoint.seal_completion(root, names)
    sealed = checkpoint.load_checkpoint(root)
    assert set(sealed["completion_files"]) == set(names)
    for name in ("runtime", "source", "provider_files", "project_files"):
        assert sealed[name] == original[name]
    with pytest.raises(FileExistsError, match="already sealed"):
        checkpoint.seal_completion(root, names)


@pytest.mark.parametrize(
    "name",
    [
        "result.json",
        "completion_receipt.json",
        "verification.log",
        "workflow_verification.log",
        "fixture_project/lab_stages.toml",
        "fixture_project/notebook_import.json",
        "fixture_project/results.json",
    ],
)
def test_cached_completion_change_blocks_recovery(completed_build, name):
    root, _ = completed_build
    capture(completed_build)
    checkpoint.seal_completion(root, complete_files(root))
    (root / name).write_text("changed completion evidence")
    with pytest.raises(ValueError, match="completion evidence changed"):
        checkpoint.load_checkpoint(root)


@pytest.mark.parametrize("mutation", ["missing", "extra", "failed", "snapshot"])
def test_completion_seal_cannot_hide_incomplete_or_changed_build(
    completed_build, mutation
):
    root, _ = completed_build
    capture(completed_build)
    names = complete_files(root)
    if mutation == "missing":
        names.remove("verification.log")
    elif mutation == "extra":
        names.append("fixture_project/app.py")
    elif mutation == "failed":
        (root / "result.json").write_text('{"status":"failed"}')
    else:
        (root / "fixture_project" / "helpers.py").write_text("changed")
    with pytest.raises(ValueError):
        checkpoint.seal_completion(root, names)
    assert "completion_files" not in json.loads(
        (root / checkpoint.CHECKPOINT_FILENAME).read_text()
    )


@pytest.mark.parametrize(
    "mutation",
    [
        None,
        "missing_report",
        "missing_claim",
        "other_attempt",
        "failed_report",
        "changed_claim",
    ],
)
def test_completion_seal_binds_one_recovery_attempt(completed_build, mutation):
    root, _ = completed_build
    capture(completed_build)
    names = complete_files(root)
    names.remove("verification.log")
    names.remove("workflow_verification.log")
    attempt = "notebook_recovery_attempts/20261014T124500Z-a1b2c3d4"
    (root / attempt).mkdir(parents=True)
    for role in (
        "notebook_verification.log",
        "notebook_workflow_verification.log",
        "notebook_recovery_attempt.json",
        "notebook_recovery_result.json",
    ):
        name = f"{attempt}/{role}"
        (root / name).write_text('{"status":"passed"}')
        names.append(name)
    if mutation == "missing_report":
        names.remove(f"{attempt}/notebook_recovery_result.json")
    elif mutation == "missing_claim":
        names.remove(f"{attempt}/notebook_recovery_attempt.json")
    elif mutation == "other_attempt":
        names[-1] = names[-1].replace("a1b2c3d4", "other")
    elif mutation == "failed_report":
        (root / attempt / "notebook_recovery_result.json").write_text(
            '{"status":"failed"}'
        )
    if mutation in {None, "changed_claim"}:
        checkpoint.seal_completion(root, names)
        assert set(checkpoint.load_checkpoint(root)["completion_files"]) == set(names)
        if mutation == "changed_claim":
            (root / attempt / "notebook_recovery_attempt.json").write_text(
                '{"checkpoint_sha256":"changed"}'
            )
            with pytest.raises(ValueError, match="completion evidence changed"):
                checkpoint.load_checkpoint(root)
    else:
        with pytest.raises(ValueError):
            checkpoint.seal_completion(root, names)


def test_build_lock_refuses_concurrent_use_and_preserves_inode(tmp_path):
    with checkpoint.build_lock(tmp_path):
        inode = (tmp_path / checkpoint.LOCK_FILENAME).stat().st_ino
        with pytest.raises(RuntimeError, match="already running"):
            with checkpoint.build_lock(tmp_path):
                pytest.fail("concurrent lock accepted")
    with checkpoint.build_lock(tmp_path):
        assert (tmp_path / checkpoint.LOCK_FILENAME).stat().st_ino == inode


def test_build_lock_is_released_when_its_process_exits(tmp_path):
    code = (
        "import os, sys\nfrom pathlib import Path\n"
        "from agilab.agent_runtime.notebook_build_checkpoint import build_lock\n"
        "with build_lock(Path(sys.argv[1])):\n    os._exit(0)\n"
    )
    finished = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert finished.returncode == 0, finished.stderr
    assert (tmp_path / checkpoint.LOCK_FILENAME).is_file()
    with checkpoint.build_lock(tmp_path):
        pass


def test_build_lock_refuses_symlink(tmp_path):
    target = tmp_path / "another.lock"
    target.write_text("untouched")
    (tmp_path / checkpoint.LOCK_FILENAME).symlink_to(target)
    with pytest.raises(ValueError, match="symlinks"):
        with checkpoint.build_lock(tmp_path):
            pass
    assert target.read_text() == "untouched"
