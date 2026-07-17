from __future__ import annotations

import importlib
import importlib.util
import json
import multiprocessing
import os
from pathlib import Path
import sys

import pytest


def _ensure_agilab_package_path() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    repo_root_text = str(repo_root)
    if repo_root_text not in sys.path:
        # Spawned test workers must be able to import this test package even
        # when pytest's importlib mode omits the checkout root from sys.path.
        sys.path.insert(0, repo_root_text)
    package_root = repo_root / "src" / "agilab"
    package_spec = importlib.util.spec_from_file_location(
        "agilab",
        package_root / "__init__.py",
        submodule_search_locations=[str(package_root)],
    )
    package = sys.modules.get("agilab")
    if package is None:
        assert package_spec is not None and package_spec.loader is not None
        package = importlib.util.module_from_spec(package_spec)
        sys.modules["agilab"] = package
        package_spec.loader.exec_module(package)
        return

    package_paths = list(getattr(package, "__path__", []) or [])
    package_root_text = str(package_root)
    if package_root_text not in package_paths:
        package.__path__ = [package_root_text, *package_paths]
    package.__spec__ = package_spec
    package.__file__ = str(package_root / "__init__.py")
    package.__package__ = "agilab"


_ensure_agilab_package_path()
dag_run_engine = importlib.import_module("agilab.dag_run_engine")
evidence_graph = importlib.import_module("agilab.evidence_graph")
workflow_run_manifest = importlib.import_module("agilab.workflow_run_manifest")
runtime_contract = importlib.import_module("agilab.workflow_runtime_contract")

LATEST_WORKFLOW_EVIDENCE_FILENAME = workflow_run_manifest.LATEST_WORKFLOW_EVIDENCE_FILENAME
WORKFLOW_EVIDENCE_DIRNAME = workflow_run_manifest.WORKFLOW_EVIDENCE_DIRNAME
load_evidence_ledger = workflow_run_manifest.load_evidence_ledger
load_workflow_run_manifest = workflow_run_manifest.load_workflow_run_manifest
sha256_payload = workflow_run_manifest.sha256_payload
workflow_manifest_summary = workflow_run_manifest.workflow_manifest_summary
write_workflow_run_evidence = workflow_run_manifest.write_workflow_run_evidence


def _workflow_evidence_writer(
    lab_dir: str,
    state_path: str,
    state: dict,
    start,
    results,
) -> None:
    start.wait(timeout=10)
    try:
        workflow_run_manifest.write_workflow_run_evidence(
            state=state,
            state_path=Path(state_path),
            repo_root=Path(lab_dir).parent,
            lab_dir=Path(lab_dir),
            trigger={"surface": "multiprocess", "action": "write"},
        )
    except BaseException as exc:
        results.put(("error", type(exc).__name__, str(exc)))
    else:
        results.put(("ok", "", ""))


def _workflow_evidence_trigger_writer(
    lab_dir: str,
    state_path: str,
    state: dict,
    trigger: dict,
    start,
    results,
) -> None:
    start.wait(timeout=10)
    try:
        bundle = workflow_run_manifest.write_workflow_run_evidence(
            state=state,
            state_path=Path(state_path),
            repo_root=Path(lab_dir).parent,
            lab_dir=Path(lab_dir),
            trigger=trigger,
        )
    except BaseException as exc:
        results.put(("error", type(exc).__name__, str(exc)))
    else:
        results.put(("ok", bundle.manifest["manifest_id"], trigger["action"]))


def _workflow_evidence_crash_writer(lab_dir: str, state_path: str, state: dict) -> None:
    real_write = workflow_run_manifest._write_json_fsync
    calls = 0

    def crash_after_partial_stage(path, payload):
        nonlocal calls
        calls += 1
        real_write(path, payload)
        if calls == 2:
            os._exit(23)

    workflow_run_manifest._write_json_fsync = crash_after_partial_stage
    workflow_run_manifest.write_workflow_run_evidence(
        state=state,
        state_path=Path(state_path),
        repo_root=Path(lab_dir).parent,
        lab_dir=Path(lab_dir),
        trigger={"surface": "crash", "action": "write"},
    )


def _start_spawn_processes(processes) -> None:
    """Start spawn workers without inheriting another test's synthetic main file."""
    main_module = sys.modules.get("__main__")
    if main_module is None:
        for process in processes:
            process.start()
        return

    missing = object()
    original_file = getattr(main_module, "__file__", missing)
    main_module.__file__ = __file__
    try:
        for process in processes:
            process.start()
    finally:
        if original_file is missing:
            delattr(main_module, "__file__")
        else:
            main_module.__file__ = original_file


def test_workflow_evidence_lock_times_out_instead_of_freezing_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock_path = tmp_path / ".publish.lock"
    monkeypatch.setattr(workflow_run_manifest, "_PUBLICATION_LOCK_TIMEOUT_SECONDS", 0.01)

    with workflow_run_manifest._exclusive_publication_lock(lock_path):
        with pytest.raises(TimeoutError, match="Another session"):
            with workflow_run_manifest._exclusive_publication_lock(lock_path):
                raise AssertionError("nested lock unexpectedly acquired")


def test_workflow_evidence_mutable_reads_retry_windows_sharing_violation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = tmp_path / "runner_state.json"
    state = {"run_id": "demo", "updated_at": "2026-07-16T10:00:00Z"}
    state_path.write_text(json.dumps(state), encoding="utf-8")
    real_read_bytes = Path.read_bytes
    attempts = 0

    def _transient_read_bytes(path: Path):
        nonlocal attempts
        if path == state_path:
            attempts += 1
            if attempts == 1:
                raise PermissionError("sharing violation")
        return real_read_bytes(path)

    monkeypatch.setattr(workflow_run_manifest, "_is_windows", lambda: True)
    monkeypatch.setattr(workflow_run_manifest.time, "sleep", lambda _delay: None)
    monkeypatch.setattr(Path, "read_bytes", _transient_read_bytes)

    assert workflow_run_manifest._read_matching_runner_state(
        state=state,
        state_path=state_path,
    ) == state
    assert attempts == 2


def test_latest_workflow_evidence_retries_windows_stat_read_and_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    latest_path = tmp_path / "latest_workflow_evidence.json"
    current = {
        "kind": "agilab.latest_workflow_evidence",
        "manifest_id": "current",
        "revision": {"updated_at": "2026-07-16T10:00:00Z", "event_count": 1},
    }
    newer = {
        "kind": "agilab.latest_workflow_evidence",
        "manifest_id": "newer",
        "revision": {"updated_at": "2026-07-16T10:01:00Z", "event_count": 2},
    }
    latest_path.write_text(json.dumps(current), encoding="utf-8")
    real_stat = Path.stat
    real_read_text = Path.read_text
    real_replace = workflow_run_manifest.os.replace
    attempts = {"stat": 0, "read": 0, "replace": 0}

    def _transient_stat(path: Path, *args, **kwargs):
        if path == latest_path:
            attempts["stat"] += 1
            if attempts["stat"] == 1:
                raise PermissionError("sharing violation")
        return real_stat(path, *args, **kwargs)

    def _transient_read(path: Path, *args, **kwargs):
        if path == latest_path:
            attempts["read"] += 1
            if attempts["read"] == 1:
                raise PermissionError("sharing violation")
        return real_read_text(path, *args, **kwargs)

    def _transient_replace(source, destination):
        if Path(destination) == latest_path:
            attempts["replace"] += 1
            if attempts["replace"] == 1:
                raise PermissionError("sharing violation")
        return real_replace(source, destination)

    monkeypatch.setattr(workflow_run_manifest, "_is_windows", lambda: True)
    monkeypatch.setattr(workflow_run_manifest.time, "sleep", lambda _delay: None)
    monkeypatch.setattr(Path, "stat", _transient_stat)
    monkeypatch.setattr(Path, "read_text", _transient_read)
    monkeypatch.setattr(workflow_run_manifest.os, "replace", _transient_replace)

    assert workflow_run_manifest._write_latest_if_newer(latest_path, newer) is True
    assert json.loads(real_read_text(latest_path, encoding="utf-8"))["manifest_id"] == "newer"
    assert attempts == {"stat": 2, "read": 2, "replace": 2}


def _sample_state(*, run_status: str = "completed") -> dict[str, object]:
    return {
        "schema": "agilab.global_pipeline_runner_state.v1",
        "run_id": "demo-run",
        "run_status": run_status,
        "created_at": "2026-05-12T08:00:00Z",
        "updated_at": "2026-05-12T08:01:00Z",
        "source": {
            "source_type": "multi_app_dag",
            "dag_path": "src/agilab/apps/builtin/uav_queue_project/dag_templates/uav_queue_to_relay.json",
            "plan_schema": "agilab.multi_app_dag.v1",
            "plan_runner_status": "controlled_contract_stage_execution",
            "execution_order": ["queue_context", "relay_review"],
        },
        "summary": {
            "unit_count": 2,
            "completed_count": 2,
            "failed_count": 0,
            "available_artifact_ids": ["queue_metrics", "relay_metrics"],
        },
        "units": [
            {
                "id": "queue_context",
                "order_index": 0,
                "app": "uav_queue_project",
                "dispatch_status": "completed",
                "depends_on": [],
                "produces": [
                    {"artifact": "queue_metrics", "kind": "summary_metrics", "path": "queue/metrics.json"}
                ],
                "artifact_dependencies": [],
                "execution_contract": {"entrypoint": "uav_queue_project.queue_context"},
            },
            {
                "id": "relay_review",
                "order_index": 1,
                "app": "uav_relay_queue_project",
                "dispatch_status": "completed" if run_status == "completed" else "failed",
                "depends_on": ["queue_context"],
                "produces": [
                    {"artifact": "relay_metrics", "kind": "summary_metrics", "path": "relay/metrics.json"}
                ],
                "artifact_dependencies": [
                    {
                        "artifact": "queue_metrics",
                        "from": "queue_context",
                        "from_app": "uav_queue_project",
                        "source_path": "queue/metrics.json",
                    }
                ],
                "execution_contract": {"entrypoint": "uav_relay_queue_project.relay_review"},
            },
        ],
        "artifacts": [],
        "events": [
            {
                "timestamp": "2026-05-12T08:01:00Z",
                "kind": "unit_completed",
                "unit_id": "relay_review",
                "from_status": "running",
                "to_status": run_status,
                "detail": "sample state",
            }
        ],
    }


def test_workflow_run_manifest_writes_immutable_manifest_and_ledger(tmp_path: Path) -> None:
    lab_dir = tmp_path / "lab"
    state_path = lab_dir / ".agilab" / "runner_state.json"
    state_path.parent.mkdir(parents=True)
    state = _sample_state()
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    first = write_workflow_run_evidence(
        state=state,
        state_path=state_path,
        repo_root=tmp_path,
        lab_dir=lab_dir,
        trigger={"surface": "test", "action": "write"},
    )
    second = write_workflow_run_evidence(
        state=state,
        state_path=state_path,
        repo_root=tmp_path,
        lab_dir=lab_dir,
        trigger={"surface": "test", "action": "write"},
    )

    assert first.manifest_path == second.manifest_path
    assert first.ledger_path == second.ledger_path
    assert first.graph_path == second.graph_path
    assert first.latest_path == lab_dir / ".agilab" / WORKFLOW_EVIDENCE_DIRNAME / LATEST_WORKFLOW_EVIDENCE_FILENAME

    manifest = load_workflow_run_manifest(first.manifest_path)
    ledger = load_evidence_ledger(first.ledger_path)
    graph = json.loads(first.graph_path.read_text(encoding="utf-8"))
    summary = workflow_manifest_summary(manifest)

    assert manifest["schema_version"] == workflow_run_manifest.WORKFLOW_RUN_MANIFEST_SCHEMA_VERSION
    assert "-v4-" in manifest["manifest_id"]
    assert manifest["status"] == "pass"
    assert first.graph == graph
    assert first.graph_path == first.manifest_path.parent / workflow_run_manifest.EVIDENCE_GRAPH_FILENAME
    assert evidence_graph.validate_evidence_graph(graph) == ()
    assert graph["summary"]["node_kinds"]["stage"] == 2
    assert summary["unit_count"] == 2
    assert summary["produced_count"] == 2
    assert summary["consumed_count"] == 1
    assert summary["phase"] == "completed"
    assert summary["event_count"] == 1
    assert manifest["runtime_contract"]["schema"] == runtime_contract.WORKFLOW_RUNTIME_CONTRACT_SCHEMA
    assert manifest["runtime_contract"]["phase"] == "completed"
    assert runtime_contract.enabled_workflow_control_labels(manifest["runtime_contract"]) == ()
    assert manifest["runner_state"]["sha256"]
    assert manifest["runner_state"]["snapshot_sha256"]
    assert manifest["runner_state"]["path"] == str(state_path)
    assert manifest["runner_state"]["source_path"] == str(state_path)
    assert manifest["runner_state"]["snapshot_path"] == str(first.state_snapshot_path)
    assert json.loads(first.state_snapshot_path.read_text(encoding="utf-8")) == state
    assert manifest["runner_state"]["sha256"] == workflow_run_manifest._sha256_file_or_empty(
        first.state_snapshot_path
    )
    state_artifact = next(
        artifact
        for artifact in manifest["artifacts"]
        if artifact["name"] == workflow_run_manifest.RUNNER_STATE_SNAPSHOT_FILENAME
    )
    assert state_artifact["path"] == str(first.state_snapshot_path)
    assert state_artifact["source_path"] == str(state_path)
    assert state_artifact["sha256"] == manifest["runner_state"]["sha256"]
    assert ledger["manifest_id"] == manifest["manifest_id"]
    assert ledger["claims"]
    assert {
        artifact["name"]
        for artifact in ledger["artifacts"]
    } >= {workflow_run_manifest.EVIDENCE_GRAPH_FILENAME, workflow_run_manifest.WORKFLOW_RUN_MANIFEST_FILENAME}
    assert workflow_run_manifest.RUNNER_STATE_SNAPSHOT_FILENAME in {
        artifact["name"] for artifact in ledger["artifacts"]
    }
    assert {
        evidence["sha256"]
        for claim in ledger["claims"]
        for evidence in claim["evidence"]
        if evidence["kind"] == "agilab.workflow_run_manifest"
    } == {sha256_payload(manifest)}
    completion = json.loads(
        (first.manifest_path.parent / workflow_run_manifest.WORKFLOW_EVIDENCE_COMPLETION_FILENAME).read_text(
            encoding="utf-8"
        )
    )
    assert completion["manifest_id"] == manifest["manifest_id"]
    assert completion["files"][workflow_run_manifest.RUNNER_STATE_SNAPSHOT_FILENAME] == (
        manifest["runner_state"]["sha256"]
    )
    workflow_run_manifest._validate_completion_marker(first.manifest_path.parent, manifest["manifest_id"])


def test_workflow_evidence_rejects_state_that_differs_from_single_persisted_read(
    tmp_path: Path,
) -> None:
    lab_dir = tmp_path / "lab"
    state_path = lab_dir / ".agilab" / "runner_state.json"
    state_path.parent.mkdir(parents=True)
    persisted_state = _sample_state()
    stale_state = json.loads(json.dumps(persisted_state))
    stale_state["updated_at"] = "2026-05-12T07:59:00Z"
    state_path.write_text(json.dumps(persisted_state, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Runner state changed before evidence publication"):
        write_workflow_run_evidence(
            state=stale_state,
            state_path=state_path,
            repo_root=tmp_path,
            lab_dir=lab_dir,
        )

    assert not workflow_run_manifest.workflow_evidence_root(lab_dir).exists()


def test_two_process_state_a_b_publication_rejects_stale_a(tmp_path: Path) -> None:
    lab_dir = tmp_path / "lab"
    state_path = lab_dir / ".agilab" / "runner_state.json"
    state_path.parent.mkdir(parents=True)
    state_a = _sample_state()
    state_b = json.loads(json.dumps(state_a))
    state_b["updated_at"] = "2026-05-12T08:02:00Z"
    state_path.write_text(json.dumps(state_b, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    results = context.Queue()
    processes = [
        context.Process(
            target=_workflow_evidence_writer,
            args=(str(lab_dir), str(state_path), state, start, results),
        )
        for state in (state_a, state_b)
    ]
    _start_spawn_processes(processes)
    start.set()
    outcomes = [results.get(timeout=15) for _ in processes]
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0

    assert sum(outcome[0] == "ok" for outcome in outcomes) == 1
    errors = [outcome for outcome in outcomes if outcome[0] == "error"]
    assert len(errors) == 1
    assert errors[0][1] == "ValueError"
    assert "Runner state changed before evidence publication" in errors[0][2]
    latest = json.loads(
        (
            workflow_run_manifest.workflow_evidence_root(lab_dir)
            / LATEST_WORKFLOW_EVIDENCE_FILENAME
        ).read_text(encoding="utf-8")
    )
    manifest = load_workflow_run_manifest(Path(latest["manifest_path"]))
    assert manifest["created_at"] == state_b["updated_at"]


def test_workflow_evidence_publication_is_multiprocess_safe(tmp_path: Path) -> None:
    lab_dir = tmp_path / "lab"
    state_path = lab_dir / ".agilab" / "runner_state.json"
    state_path.parent.mkdir(parents=True)
    state = _sample_state()
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    results = context.Queue()
    processes = [
        context.Process(
            target=_workflow_evidence_writer,
            args=(str(lab_dir), str(state_path), state, start, results),
        )
        for _ in range(2)
    ]
    _start_spawn_processes(processes)
    start.set()
    outcomes = [results.get(timeout=15) for _ in processes]
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0

    assert outcomes == [("ok", "", ""), ("ok", "", "")]
    root = workflow_run_manifest.workflow_evidence_root(lab_dir)
    assert list(root.glob(".*.staging")) == []
    latest = json.loads((root / LATEST_WORKFLOW_EVIDENCE_FILENAME).read_text(encoding="utf-8"))
    bundle_dir = Path(latest["manifest_path"]).parent
    workflow_run_manifest._validate_completion_marker(bundle_dir, latest["manifest_id"])


def test_same_state_different_triggers_publish_distinct_bundles_concurrently(tmp_path: Path) -> None:
    lab_dir = tmp_path / "lab"
    state_path = lab_dir / ".agilab" / "runner_state.json"
    state_path.parent.mkdir(parents=True)
    state = _sample_state()
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    results = context.Queue()
    triggers = [
        {"surface": "test", "action": "one"},
        {"surface": "test", "action": "two"},
    ]
    processes = [
        context.Process(
            target=_workflow_evidence_trigger_writer,
            args=(str(lab_dir), str(state_path), state, trigger, start, results),
        )
        for trigger in triggers
    ]

    _start_spawn_processes(processes)
    start.set()
    outcomes = [results.get(timeout=15) for _ in processes]
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0

    assert {outcome[0] for outcome in outcomes} == {"ok"}
    manifest_ids = {outcome[1] for outcome in outcomes}
    assert len(manifest_ids) == 2
    assert {outcome[2] for outcome in outcomes} == {"one", "two"}
    root = workflow_run_manifest.workflow_evidence_root(lab_dir)
    for manifest_id in manifest_ids:
        manifest_path = root / manifest_id / workflow_run_manifest.WORKFLOW_RUN_MANIFEST_FILENAME
        manifest = load_workflow_run_manifest(manifest_path)
        assert manifest["trigger"]["action"] in {"one", "two"}


@pytest.mark.parametrize(
    ("filename", "mutate"),
    [
        (
            workflow_run_manifest.WORKFLOW_RUN_MANIFEST_FILENAME,
            lambda payload: {**payload, "status": "fail"},
        ),
        (
            workflow_run_manifest.EVIDENCE_LEDGER_FILENAME,
            lambda payload: {**payload, "tampered": True},
        ),
        (
            workflow_run_manifest.EVIDENCE_GRAPH_FILENAME,
            lambda payload: {**payload, "tampered": True},
        ),
    ],
)
def test_v4_manifest_load_rejects_valid_json_bundle_tampering(
    tmp_path: Path,
    filename: str,
    mutate,
) -> None:
    lab_dir = tmp_path / "lab"
    state_path = lab_dir / ".agilab" / "runner_state.json"
    state_path.parent.mkdir(parents=True)
    state = _sample_state()
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    bundle = write_workflow_run_evidence(
        state=state,
        state_path=state_path,
        repo_root=tmp_path,
        lab_dir=lab_dir,
    )
    tampered_path = bundle.manifest_path.parent / filename
    payload = json.loads(tampered_path.read_text(encoding="utf-8"))
    tampered_path.write_text(
        json.dumps(mutate(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=f"completion hash mismatch for .*{filename}"):
        load_workflow_run_manifest(bundle.manifest_path)


def test_v4_manifest_load_rejects_schema_downgrade_tampering(tmp_path: Path) -> None:
    lab_dir = tmp_path / "lab"
    state_path = lab_dir / ".agilab" / "runner_state.json"
    state_path.parent.mkdir(parents=True)
    state = _sample_state()
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    bundle = write_workflow_run_evidence(
        state=state,
        state_path=state_path,
        repo_root=tmp_path,
        lab_dir=lab_dir,
    )
    payload = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
    payload["schema_version"] = 3
    bundle.manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=f"completion hash mismatch for .*{workflow_run_manifest.WORKFLOW_RUN_MANIFEST_FILENAME}",
    ):
        load_workflow_run_manifest(bundle.manifest_path)


def test_manifest_load_hashes_the_same_bytes_it_parses(tmp_path: Path, monkeypatch) -> None:
    lab_dir = tmp_path / "lab"
    state_path = lab_dir / ".agilab" / "runner_state.json"
    state_path.parent.mkdir(parents=True)
    state = _sample_state()
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    bundle = write_workflow_run_evidence(
        state=state,
        state_path=state_path,
        repo_root=tmp_path,
        lab_dir=lab_dir,
    )
    original_bytes = bundle.manifest_path.read_bytes()
    tampered = json.loads(original_bytes)
    tampered["status"] = "fail"
    bundle.manifest_path.write_text(
        json.dumps(tampered, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    original_validator = workflow_run_manifest.validate_workflow_runtime_contract

    def restore_manifest_during_validation(runtime_contract):
        bundle.manifest_path.write_bytes(original_bytes)
        return original_validator(runtime_contract)

    monkeypatch.setattr(
        workflow_run_manifest,
        "validate_workflow_runtime_contract",
        restore_manifest_during_validation,
    )

    with pytest.raises(
        ValueError,
        match=f"completion hash mismatch for .*{workflow_run_manifest.WORKFLOW_RUN_MANIFEST_FILENAME}",
    ):
        load_workflow_run_manifest(bundle.manifest_path)


def test_delayed_older_bundle_cannot_replace_newer_latest_pointer(tmp_path: Path) -> None:
    lab_dir = tmp_path / "lab"
    state_path = lab_dir / ".agilab" / "runner_state.json"
    state_path.parent.mkdir(parents=True)
    state_a = _sample_state()
    state_a["updated_at"] = "2026-05-12T08:01:00Z"
    state_b = json.loads(json.dumps(state_a))
    state_b["updated_at"] = "2026-05-12T08:02:00Z"

    state_path.write_text(json.dumps(state_b, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    newer = write_workflow_run_evidence(
        state=state_b,
        state_path=state_path,
        repo_root=tmp_path,
        lab_dir=lab_dir,
    )
    state_path.write_text(json.dumps(state_a, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    older = write_workflow_run_evidence(
        state=state_a,
        state_path=state_path,
        repo_root=tmp_path,
        lab_dir=lab_dir,
    )

    assert older.manifest_path.is_file()
    latest = json.loads(newer.latest_path.read_text(encoding="utf-8"))
    assert latest["manifest_id"] == newer.manifest["manifest_id"]
    assert latest["manifest_id"] != older.manifest["manifest_id"]
    assert latest["revision"] == {
        "run_created_at": state_b["created_at"],
        "updated_at": state_b["updated_at"],
        "event_count": len(state_b["events"]),
        "tie_breaker": newer.manifest["manifest_id"],
    }


def test_workflow_evidence_crash_before_publish_leaves_no_visible_partial_bundle(
    tmp_path: Path,
    monkeypatch,
) -> None:
    lab_dir = tmp_path / "lab"
    state_path = lab_dir / ".agilab" / "runner_state.json"
    state_path.parent.mkdir(parents=True)
    state = _sample_state()
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = workflow_run_manifest.build_workflow_run_manifest(
        state=state,
        state_path=state_path,
        repo_root=tmp_path,
        lab_dir=lab_dir,
    )
    final_dir = workflow_run_manifest.workflow_evidence_paths(
        lab_dir, str(manifest["manifest_id"])
    )[0].parent
    real_write = workflow_run_manifest._write_json_fsync
    calls = 0

    def fail_during_stage(path, payload):
        nonlocal calls
        calls += 1
        real_write(path, payload)
        if calls == 2:
            raise OSError("simulated publication crash")

    monkeypatch.setattr(workflow_run_manifest, "_write_json_fsync", fail_during_stage)
    with pytest.raises(OSError, match="simulated publication crash"):
        write_workflow_run_evidence(
            state=state,
            state_path=state_path,
            repo_root=tmp_path,
            lab_dir=lab_dir,
        )

    root = workflow_run_manifest.workflow_evidence_root(lab_dir)
    assert not final_dir.exists()
    assert not (root / LATEST_WORKFLOW_EVIDENCE_FILENAME).exists()
    assert list(root.glob(".*.staging")) == []


def test_workflow_evidence_process_crash_is_ignored_and_recovered(tmp_path: Path) -> None:
    lab_dir = tmp_path / "lab"
    state_path = lab_dir / ".agilab" / "runner_state.json"
    state_path.parent.mkdir(parents=True)
    state = _sample_state()
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    context = multiprocessing.get_context("spawn")
    process = context.Process(
        target=_workflow_evidence_crash_writer,
        args=(str(lab_dir), str(state_path), state),
    )
    _start_spawn_processes([process])
    process.join(timeout=15)
    assert process.exitcode == 23

    root = workflow_run_manifest.workflow_evidence_root(lab_dir)
    assert not (root / LATEST_WORKFLOW_EVIDENCE_FILENAME).exists()
    assert list(root.glob(".*.staging"))

    bundle = write_workflow_run_evidence(
        state=state,
        state_path=state_path,
        repo_root=tmp_path,
        lab_dir=lab_dir,
        trigger={"surface": "crash", "action": "write"},
    )

    assert list(root.glob(".*.staging")) == []
    workflow_run_manifest._validate_completion_marker(bundle.manifest_path.parent, bundle.manifest["manifest_id"])


def test_workflow_evidence_repairs_partial_legacy_completion_marker(tmp_path: Path) -> None:
    lab_dir = tmp_path / "lab"
    state_path = lab_dir / ".agilab" / "runner_state.json"
    state_path.parent.mkdir(parents=True)
    state = _sample_state()
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    bundle = write_workflow_run_evidence(
        state=state,
        state_path=state_path,
        repo_root=tmp_path,
        lab_dir=lab_dir,
    )
    completion_path = (
        bundle.manifest_path.parent / workflow_run_manifest.WORKFLOW_EVIDENCE_COMPLETION_FILENAME
    )
    completion_path.write_text('{"schema_version":', encoding="utf-8")

    repaired = write_workflow_run_evidence(
        state=state,
        state_path=state_path,
        repo_root=tmp_path,
        lab_dir=lab_dir,
    )

    workflow_run_manifest._validate_completion_marker(
        repaired.manifest_path.parent,
        repaired.manifest["manifest_id"],
    )
    assert list(completion_path.parent.glob(f".{completion_path.name}.*.tmp")) == []


def test_legacy_bundle_completion_backfill_does_not_require_state_snapshot(
    tmp_path: Path,
) -> None:
    bundle_dir = tmp_path / "legacy-v3"
    bundle_dir.mkdir()
    manifest_id = "legacy-v3-run"
    workflow_run_manifest._write_json(
        bundle_dir / workflow_run_manifest.WORKFLOW_RUN_MANIFEST_FILENAME,
        {
            "schema_version": 3,
            "kind": workflow_run_manifest.WORKFLOW_RUN_MANIFEST_KIND,
            "manifest_id": manifest_id,
            "state_snapshot": {"sha256": "legacy-digest", "event_count": 1},
        },
    )
    workflow_run_manifest._write_json(
        bundle_dir / workflow_run_manifest.EVIDENCE_GRAPH_FILENAME,
        {"kind": "legacy-graph"},
    )
    workflow_run_manifest._write_json(
        bundle_dir / workflow_run_manifest.EVIDENCE_LEDGER_FILENAME,
        {"kind": "legacy-ledger"},
    )

    completion_path = workflow_run_manifest._backfill_completion_marker(
        bundle_dir,
        manifest_id,
    )

    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    assert set(completion["files"]) == {
        workflow_run_manifest.WORKFLOW_RUN_MANIFEST_FILENAME,
        workflow_run_manifest.EVIDENCE_GRAPH_FILENAME,
        workflow_run_manifest.EVIDENCE_LEDGER_FILENAME,
    }
    workflow_run_manifest._validate_completion_marker(bundle_dir, manifest_id)


def test_immutable_json_publish_failure_leaves_no_partial_final_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    immutable_path = tmp_path / workflow_run_manifest.WORKFLOW_EVIDENCE_COMPLETION_FILENAME

    def fail_publish(_source, _destination):
        raise OSError("simulated atomic publish failure")

    monkeypatch.setattr(workflow_run_manifest.os, "replace", fail_publish)
    with pytest.raises(OSError, match="simulated atomic publish failure"):
        workflow_run_manifest._write_immutable_json(immutable_path, {"a": 1})

    assert not immutable_path.exists()
    assert list(tmp_path.glob(f".{immutable_path.name}.*.tmp")) == []


def test_immutable_json_publication_does_not_require_hard_links(
    tmp_path: Path,
    monkeypatch,
) -> None:
    immutable_path = tmp_path / "immutable.json"

    def reject_hard_link(_source, _destination):
        raise AssertionError("hard links must not be used")

    monkeypatch.setattr(workflow_run_manifest.os, "link", reject_hard_link)
    workflow_run_manifest._write_immutable_json(immutable_path, {"a": 1})

    assert json.loads(immutable_path.read_text(encoding="utf-8")) == {"a": 1}


def test_workflow_run_manifest_loads_legacy_schema_v2_without_graph(tmp_path: Path) -> None:
    legacy_path = tmp_path / "legacy_workflow_run_manifest.json"
    legacy_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "kind": workflow_run_manifest.WORKFLOW_RUN_MANIFEST_KIND,
                "manifest_id": "legacy-demo",
                "run_id": "legacy-run",
                "status": "unknown",
                "workflow": {"unit_count": 0},
                "artifact_contracts": {"produced_count": 0, "consumed_count": 0},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    manifest = load_workflow_run_manifest(legacy_path)
    summary = workflow_manifest_summary(manifest)

    assert manifest["schema_version"] == 2
    assert summary["manifest_id"] == "legacy-demo"
    assert summary["phase"] == "unknown"
    assert "evidence_graph" not in manifest


def test_workflow_manifest_loaders_and_helpers_cover_error_paths(tmp_path: Path, monkeypatch) -> None:
    manifest_path = tmp_path / "workflow_run_manifest.json"
    ledger_path = tmp_path / "evidence_ledger.json"

    manifest_path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a JSON object"):
        load_workflow_run_manifest(manifest_path)
    for payload, message in (
        ({"schema_version": 999}, "Unsupported workflow run manifest schema"),
        ({"schema_version": 3, "kind": "wrong"}, "Unsupported workflow run manifest kind"),
        (
            {
                "schema_version": 3,
                "kind": workflow_run_manifest.WORKFLOW_RUN_MANIFEST_KIND,
                "status": "weird",
            },
            "Unsupported workflow run manifest status",
        ),
        (
            {
                "schema_version": 3,
                "kind": workflow_run_manifest.WORKFLOW_RUN_MANIFEST_KIND,
                "status": "unknown",
                "runtime_contract": "bad",
            },
            "runtime_contract must be a JSON object",
        ),
        (
            {
                "schema_version": 3,
                "kind": workflow_run_manifest.WORKFLOW_RUN_MANIFEST_KIND,
                "status": "unknown",
                "runtime_contract": {"schema": "bad"},
            },
            "Invalid workflow runtime contract",
        ),
        (
            {
                "schema_version": 3,
                "kind": workflow_run_manifest.WORKFLOW_RUN_MANIFEST_KIND,
                "status": "unknown",
                "evidence_graph": "bad",
            },
            "evidence_graph must be a JSON object",
        ),
    ):
        manifest_path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError, match=message):
            load_workflow_run_manifest(manifest_path)

    ledger_path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="evidence ledger must be a JSON object"):
        load_evidence_ledger(ledger_path)
    for payload, message in (
        ({"schema_version": 2}, "Unsupported evidence ledger schema"),
        ({"schema_version": 1, "kind": "wrong"}, "Unsupported evidence ledger kind"),
    ):
        ledger_path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError, match=message):
            load_evidence_ledger(ledger_path)

    assert workflow_run_manifest.workflow_evidence_paths(tmp_path, "bad id!") == (
        tmp_path
        / ".agilab"
        / workflow_run_manifest.WORKFLOW_EVIDENCE_DIRNAME
        / "bad-id"
        / workflow_run_manifest.WORKFLOW_RUN_MANIFEST_FILENAME,
        tmp_path
        / ".agilab"
        / workflow_run_manifest.WORKFLOW_EVIDENCE_DIRNAME
        / "bad-id"
        / workflow_run_manifest.EVIDENCE_LEDGER_FILENAME,
        tmp_path
        / ".agilab"
        / workflow_run_manifest.WORKFLOW_EVIDENCE_DIRNAME
        / workflow_run_manifest.LATEST_WORKFLOW_EVIDENCE_FILENAME,
    )
    assert workflow_run_manifest.workflow_evidence_graph_path(tmp_path, "bad id!").name == (
        workflow_run_manifest.EVIDENCE_GRAPH_FILENAME
    )
    assert workflow_run_manifest._safe_id("  ") == "workflow-run"
    assert workflow_run_manifest._json_safe({"p": tmp_path, "items": (1, tmp_path), "custom": object()})[
        "items"
    ] == [1, str(tmp_path)]
    assert workflow_run_manifest._sha256_file_or_empty(tmp_path / "missing") == ""
    assert workflow_run_manifest._repo_relative_text(tmp_path / "outside.txt", tmp_path / "repo") == str(
        tmp_path / "outside.txt"
    )
    assert workflow_run_manifest._workflow_source_path({}, None, tmp_path) == ""
    assert workflow_run_manifest._workflow_source_path({"source_dag": "legacy.json"}, tmp_path / "x", tmp_path) == (
        "legacy.json"
    )
    assert workflow_run_manifest._state_timestamp({"events": [{"timestamp": ""}, {"timestamp": "event-ts"}]}) == (
        "event-ts"
    )
    monkeypatch.setattr(workflow_run_manifest, "utc_now", lambda: "now-ts")
    assert workflow_run_manifest._state_timestamp({"events": "bad"}) == "now-ts"
    assert workflow_run_manifest._unit_rows({"units": "bad"}) == []
    assert workflow_run_manifest._unit_sort_key({"order_index": "bad", "id": "x"}) == (999_999, "x")

    produced, consumed = workflow_run_manifest._artifact_contracts(
        [
            {
                "id": "unit",
                "app": "app",
                "produces": ["bad", {"id": "artifact-from-id"}, {"artifact": ""}],
                "artifact_dependencies": ["bad", {"artifact": ""}, {"artifact": "input"}],
            }
        ]
    )
    assert produced[0]["artifact"] == "artifact-from-id"
    assert consumed[0]["artifact"] == "input"
    stage = workflow_run_manifest._stage_record(
        {
            "id": "unit",
            "depends_on": "bad",
            "produces": ["bad", {"id": "artifact-from-id"}],
            "execution_contract": "bad",
        }
    )
    assert stage["depends_on"] == []
    assert stage["produces"] == ["artifact-from-id"]
    assert stage["execution_contract_sha256"] == ""
    assert workflow_run_manifest._manifest_status({"run_status": "failed"}, []) == "fail"
    assert workflow_run_manifest._manifest_status({}, [{"dispatch_status": "failed"}]) == "fail"
    validations = workflow_run_manifest._manifest_validations(
        state={},
        units=[{"id": "bad", "dispatch_status": "failed"}],
        produced_artifacts=[],
        consumed_artifacts=[],
    )
    assert [item["status"] for item in validations] == ["fail", "unknown", "fail"]
    assert workflow_run_manifest._run_outcome_summary("failed", 1, 0, []) == (
        "workflow failed; failed units: unknown"
    )
    directory_record = workflow_run_manifest._file_record(tmp_path, name="dir", kind="directory")
    assert directory_record["exists"] is True
    assert directory_record["size_bytes"] is None

    written = workflow_run_manifest._write_json(tmp_path / "out" / "payload.json", {"p": tmp_path})
    assert json.loads(written.read_text(encoding="utf-8")) == {"p": str(tmp_path)}
    immutable = tmp_path / "immutable.json"
    workflow_run_manifest._write_immutable_json(immutable, {"a": 1})
    assert workflow_run_manifest._write_immutable_json(immutable, {"a": 1}) == immutable
    with pytest.raises(FileExistsError, match="Refusing to overwrite immutable"):
        workflow_run_manifest._write_immutable_json(immutable, {"a": 2})


def test_write_workflow_evidence_rejects_invalid_generated_graph(tmp_path: Path, monkeypatch) -> None:
    state_path = tmp_path / "state.json"
    state = {"run_id": "demo"}
    state_path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(workflow_run_manifest, "build_evidence_graph_from_workflow_manifest", lambda _manifest: {})
    monkeypatch.setattr(workflow_run_manifest, "validate_evidence_graph", lambda _graph: ("bad graph",))

    with pytest.raises(ValueError, match="Invalid workflow evidence graph: bad graph"):
        write_workflow_run_evidence(
            state=state,
            state_path=state_path,
            repo_root=tmp_path,
            lab_dir=tmp_path,
        )


def test_dag_run_engine_emits_workflow_evidence_on_state_writes(tmp_path: Path) -> None:
    repo_root = Path.cwd()

    def _fake_queue_run(
        *, repo_root: Path, run_root: Path, idempotency_token: str
    ) -> dict[str, object]:
        assert idempotency_token.endswith(":queue_baseline")
        return {
            "summary_metrics_path": str(run_root / "queue_metrics.json"),
            "reduce_artifact_path": str(run_root / "queue_reduce.json"),
            "summary_metrics": {"packets_generated": 3, "packets_delivered": 3},
        }

    engine = dag_run_engine.DagRunEngine(
        repo_root=repo_root,
        lab_dir=tmp_path,
        dag_path=repo_root / dag_run_engine.GLOBAL_DAG_SAMPLE_RELATIVE_PATH,
        run_queue_fn=_fake_queue_run,
        now_fn=lambda: "2026-05-12T08:00:00Z",
    )

    state, state_path, _dag_path = engine.load_or_create_state()
    latest_path = tmp_path / ".agilab" / WORKFLOW_EVIDENCE_DIRNAME / LATEST_WORKFLOW_EVIDENCE_FILENAME
    planned_latest = json.loads(latest_path.read_text(encoding="utf-8"))
    planned_manifest = load_workflow_run_manifest(Path(planned_latest["manifest_path"]))
    assert planned_manifest["status"] == "unknown"

    result = engine.run_next_controlled_stage_transaction(state)
    assert result.ok is True

    executed_latest = json.loads(latest_path.read_text(encoding="utf-8"))
    executed_manifest = load_workflow_run_manifest(Path(executed_latest["manifest_path"]))
    executed_ledger = load_evidence_ledger(Path(executed_latest["ledger_path"]))

    assert state_path == tmp_path / ".agilab" / "runner_state.json"
    assert executed_latest["manifest_id"] != planned_latest["manifest_id"]
    assert executed_manifest["runner_state"]["path"] == str(state_path)
    assert executed_manifest["artifact_contracts"]["produced_count"] >= 1
    assert executed_ledger["manifest_id"] == executed_manifest["manifest_id"]
