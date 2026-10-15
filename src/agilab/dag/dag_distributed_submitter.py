from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import tempfile
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from stat import S_ISREG
from typing import Any, Callable, Mapping, TextIO

from .dag_artifact_contracts import (
    ArtifactOutputSnapshot,
    artifact_file_identity,
    bind_artifact_identities,
    artifact_result_path_key as _artifact_result_path_key,
    is_contract_receipt_artifact,
    reported_artifact_paths,
    require_artifact_identity,
    require_artifact_location,
)
from .dag_idempotency import execute_idempotently, write_json_atomic

from agilab.orchestrate.orchestrate_page_support import compute_run_mode


@dataclass(frozen=True)
class DagDistributedStageConfig:
    scheduler: str
    workers: dict[str, int]
    workers_data_path: str
    mode: int
    verbose: int = 0

    @property
    def worker_nodes(self) -> int:
        return len(self.workers)

    @property
    def worker_slots(self) -> int:
        return sum(self.workers.values())


DagStageRunner = Callable[..., Mapping[str, Any]]
_REMOTE_LOG_STREAM_INTERVAL_SECONDS = 0.5


def load_dag_distributed_settings(env: Any, app_settings: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Load active app settings, with in-memory Streamlit settings taking precedence."""
    file_settings = _load_settings_file(getattr(env, "app_settings_file", None))
    if not isinstance(app_settings, Mapping):
        return file_settings

    merged = dict(file_settings)
    for key, value in app_settings.items():
        if key == "cluster" and isinstance(value, Mapping):
            file_cluster = merged.get("cluster")
            cluster = dict(file_cluster) if isinstance(file_cluster, Mapping) else {}
            cluster.update(dict(value))
            merged["cluster"] = cluster
        else:
            merged[key] = value
    return merged


def dag_distributed_stage_config_from_settings(
    settings: Mapping[str, Any],
    *,
    verbose: int = 0,
) -> DagDistributedStageConfig | None:
    cluster_params = settings.get("cluster")
    if not isinstance(cluster_params, Mapping) or not bool(cluster_params.get("cluster_enabled", False)):
        return None

    scheduler = str(cluster_params.get("scheduler", "") or "").strip()
    workers = _coerce_workers(cluster_params.get("workers"))
    workers_data_path = str(cluster_params.get("workers_data_path", "") or "").strip()
    if not scheduler or not workers or not workers_data_path:
        return None

    mode = compute_run_mode(cluster_params, cluster_enabled=True)
    return DagDistributedStageConfig(
        scheduler=scheduler,
        workers=workers,
        workers_data_path=workers_data_path,
        mode=mode,
        verbose=int(verbose or 0),
    )


def build_multi_app_dag_distributed_stage_submitter(
    *,
    env: Any,
    app_settings: Mapping[str, Any] | None = None,
    verbose: int = 0,
    runner_fn: DagStageRunner | None = None,
) -> Callable[..., Mapping[str, Any]] | None:
    settings = load_dag_distributed_settings(env, app_settings)
    config = dag_distributed_stage_config_from_settings(settings, verbose=verbose)
    if config is None:
        return None
    runner = runner_fn or run_agilab_stage_subprocess

    def _submit_stage(
        *,
        repo_root: Path,
        lab_dir: Path,
        run_root: Path,
        unit: dict[str, Any],
        artifact: dict[str, Any],
        execution_contract: dict[str, Any],
        timestamp: str,
        idempotency_token: str,
        input_artifacts: list[dict[str, Any]] | None = None,
    ) -> Mapping[str, Any]:
        return submit_distributed_stage(
            config=config,
            runner_fn=runner,
            repo_root=repo_root,
            lab_dir=lab_dir,
            run_root=run_root,
            unit=unit,
            artifact=artifact,
            execution_contract=execution_contract,
            timestamp=timestamp,
            idempotency_token=idempotency_token,
            input_artifacts=input_artifacts,
        )

    return _submit_stage


def build_distributed_request_preview_rows(
    state: Mapping[str, Any],
    *,
    repo_root: Path,
    config: DagDistributedStageConfig,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    units = state.get("units")
    if not isinstance(units, list):
        return rows
    for unit in units:
        if not isinstance(unit, Mapping):
            continue
        contract = unit.get("execution_contract")
        if not isinstance(contract, Mapping) or not contract:
            continue
        unit_id = str(unit.get("id", "") or "stage").strip() or "stage"
        app_name = str(unit.get("app", "") or "").strip()
        request_payload = request_payload_from_execution_contract(contract)
        rows.append(
            {
                "Stage": unit_id,
                "App": app_name or "-",
                "Status": str(unit.get("dispatch_status", "") or "-"),
                "Backend": "distributed",
                "Nodes": str(config.worker_nodes),
                "Worker slots": str(config.worker_slots),
                "Scheduler": config.scheduler,
                "Workers Data Path": config.workers_data_path,
                "Mode": str(config.mode),
                "Apps path": _preview_apps_path(repo_root, app_name),
                "Request": _compact_json(request_payload),
            }
        )
    return rows



_INPUT_IDENTITY_FIELDS = (
    "artifact", "producer", "kind", "path", "resolved_path", "size_bytes", "sha256",
    "identity_kind", "entry_count", "producer_run_root",
)


def _verified_distributed_inputs(inputs: Any) -> list[dict[str, Any]]:
    """Verify frozen producer bindings without deriving a replacement identity."""
    if not isinstance(inputs, list) or any(not isinstance(row, Mapping) for row in inputs):
        raise ValueError("Declared upstream artifacts require a list of original producer bindings.")
    normalized = []
    for row in inputs:
        item = {key: row[key] for key in _INPUT_IDENTITY_FIELDS if key in row}
        item["artifact"] = str(row.get("artifact", "") or row.get("id", "")).strip()
        item["producer"] = str(row.get("producer", "")).strip()
        item["kind"] = str(row.get("kind", "")).strip()
        if not all(item.get(key) for key in ("artifact", "producer", "kind", "path")):
            raise ValueError("Declared upstream artifact has an incomplete producer reference.")
        if not isinstance(item["path"], (str, Path)):
            raise ValueError("Declared upstream artifact has an invalid producer path.")
        path = Path(item["path"])
        if not path.is_absolute():
            raise ValueError("Declared upstream artifact requires its original absolute producer path.")
        item["path"] = str(path)
        if "producer_run_root" in item:
            root = item["producer_run_root"]
            if not isinstance(root, (str, Path)) or not Path(root).is_absolute():
                raise ValueError("Declared upstream artifact has an invalid producer stage root.")
            item["producer_run_root"] = str(root)
        normalized.append(item)
    # Check all location/identity metadata before opening any artifact target.
    for item in normalized:
        require_artifact_location(
            Path(item["path"]), artifact_id=item["artifact"], expected=item,
        )
        size, digest = item.get("size_bytes"), item.get("sha256")
        if (
            isinstance(size, bool) or not isinstance(size, int) or size < 0
            or not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise ValueError("Declared upstream artifact has no valid original byte identity.")
        if item.get("identity_kind") not in (None, "directory"):
            raise ValueError("Declared upstream artifact has an invalid identity kind.")
        if "entry_count" in item and item.get("identity_kind") != "directory":
            raise ValueError("Declared upstream artifact has an invalid directory identity.")
        if item.get("identity_kind") == "directory":
            count = item.get("entry_count")
            if (
                isinstance(count, bool) or not isinstance(count, int) or count < 1
                or "producer_run_root" not in item
            ):
                raise ValueError("Declared upstream artifact has no original directory identity context.")
    for item in normalized:
        path = Path(item["path"])
        require_artifact_identity(
            path, artifact_id=item["artifact"], expected=item,
            run_root=Path(item.get("producer_run_root", path.parent)),
        )
    return normalized


def validate_distributed_stage_inputs(
    unit: Mapping[str, Any], input_artifacts: Any = None,
) -> list[dict[str, Any]]:
    """Resolve only declared, producer-qualified original references for transport."""
    dependencies = unit.get("artifact_dependencies", [])
    if not isinstance(dependencies, list):
        raise ValueError("Declared upstream artifact dependencies must be a list.")
    supplied = [] if input_artifacts is None else input_artifacts
    if not isinstance(supplied, list) or any(not isinstance(row, Mapping) for row in supplied):
        raise ValueError("Declared upstream artifacts require original producer bindings.")
    selected = []
    for dependency in dependencies:
        if not isinstance(dependency, Mapping):
            raise ValueError("Declared upstream artifact dependency must be a mapping.")
        artifact_id = str(dependency.get("artifact", "") or dependency.get("id", "")).strip()
        producer = str(dependency.get("from", "")).strip()
        matches = [
            row for row in supplied
            if artifact_id
            and str(row.get("artifact", "") or row.get("id", "")).strip() == artifact_id
            and (not producer or str(row.get("producer", "")).strip() == producer)
        ]
        if len(matches) != 1:
            raise ValueError(f"Declared upstream artifact `{artifact_id}` is missing or ambiguous.")
        selected.append(matches[0])
    if len(selected) != len(supplied) or len({id(row) for row in selected}) != len(selected):
        raise ValueError("Declared upstream artifacts differ from the supplied producer references.")
    return _verified_distributed_inputs(selected)


def _input_artifact_fingerprint(inputs: list[dict[str, Any]]) -> str:
    return hashlib.sha256(
        json.dumps(inputs, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def require_distributed_input_receipts(
    result: Mapping[str, Any], inputs: list[dict[str, Any]], *, app_name: str,
) -> None:
    """Keep completed caches bound to the original inputs and child read receipts."""
    fingerprint = _input_artifact_fingerprint(inputs)
    if inputs or "input_artifact_fingerprint" in result:
        if result.get("input_artifact_fingerprint") != fingerprint:
            raise ValueError("Cached distributed stage has different or missing original upstream inputs.")
    if not inputs:
        return
    receipts = result.get("consumed_artifacts")
    if not isinstance(receipts, list) or len(receipts) != len(inputs):
        raise ValueError("Distributed stage has no complete upstream consumption receipt.")
    for item, receipt in zip(inputs, receipts):
        if not isinstance(receipt, Mapping) or any(
            receipt.get(key) != value for key, value in item.items()
        ):
            raise ValueError("Distributed upstream receipt differs from its original producer binding.")
        queue_context = app_name == "uav_relay_queue_project" and item["artifact"] == "queue_metrics"
        if queue_context:
            if (
                receipt.get("role") != "upstream_context"
                or receipt.get("read_scope") != "child_orchestrator"
                or receipt.get("numerically_conditioned") is not False
                or not isinstance(receipt.get("summary_metrics"), Mapping)
                or not receipt["summary_metrics"]
            ):
                raise ValueError("Distributed stage has no actual queue context consumption receipt.")
        elif receipt.get("role") != "declared_input_reference":
            raise ValueError("Distributed stage has no verified declared input reference receipt.")


def submit_distributed_stage(
    *,
    config: DagDistributedStageConfig,
    runner_fn: DagStageRunner,
    repo_root: Path,
    lab_dir: Path,
    run_root: Path,
    unit: Mapping[str, Any],
    artifact: Mapping[str, Any],
    execution_contract: Mapping[str, Any],
    timestamp: str,
    idempotency_token: str,
    input_artifacts: list[dict[str, Any]] | None = None,
) -> Mapping[str, Any]:
    unit_id = str(unit.get("id", "") or "stage").strip() or "stage"
    token = str(idempotency_token).strip()
    if not token:
        raise RuntimeError(f"Distributed DAG stage `{unit_id}` requires an idempotency token.")
    inputs = validate_distributed_stage_inputs(unit, input_artifacts)
    result = execute_idempotently(
        run_root=run_root,
        unit_id=unit_id,
        idempotency_token=token,
        scope="distributed-submitter",
        callback=lambda: _submit_distributed_stage_once(
            config=config,
            runner_fn=runner_fn,
            repo_root=repo_root,
            lab_dir=lab_dir,
            run_root=run_root,
            unit=unit,
            artifact=artifact,
            execution_contract=execution_contract,
            timestamp=timestamp,
            idempotency_token=token,
            input_artifacts=inputs,
        ),
    )
    require_distributed_input_receipts(result, inputs, app_name=str(unit.get("app", "")))
    if "produced_artifacts" not in result:
        raise ValueError(
            "Cached produced artifacts have no original byte identities. Run a fresh explicit attempt."
        )
    paths = reported_artifact_paths(result)
    outputs = unit.get("produces")
    declared_outputs = outputs if isinstance(outputs, list) else [artifact]
    expected_ids = {
        str(output.get("artifact", "") or output.get("id", "")).strip()
        for output in declared_outputs
        if isinstance(output, Mapping)
    } - {""}
    if not paths or set(paths) != expected_ids:
        raise ValueError(
            "Cached produced artifacts differ from the declared output contract."
        )
    records = {
        str(output.get("artifact", "") or output.get("id", "")).strip(): output
        for output in result["produced_artifacts"]
    }
    primary_id = str(artifact.get("artifact", "") or artifact.get("id", "")).strip()
    for output in declared_outputs:
        if not isinstance(output, Mapping):
            continue
        artifact_id = str(output.get("artifact", "") or output.get("id", "")).strip()
        if not artifact_id:
            continue
        kind = str(output.get("kind", "")).strip()
        if records[artifact_id].get("kind") != kind:
            raise ValueError(
                f"Cached produced artifact `{artifact_id}` has a different declared kind."
            )
        if artifact_id == primary_id:
            alias = Path(str(result.get(_artifact_result_path_key(kind), "")))
            alias = alias if alias.is_absolute() else run_root / alias
            path = Path(paths[artifact_id])
            path = path if path.is_absolute() else run_root / path
            if alias.resolve() != path.resolve():
                raise ValueError(
                    f"Cached produced artifact `{artifact_id}` has a different primary path."
                )
    bind_artifact_identities(
        result["produced_artifacts"], run_root=run_root, bind_new=False
    )
    return result


def _submit_distributed_stage_once(
    *,
    config: DagDistributedStageConfig,
    runner_fn: DagStageRunner,
    repo_root: Path,
    lab_dir: Path,
    run_root: Path,
    unit: Mapping[str, Any],
    artifact: Mapping[str, Any],
    execution_contract: Mapping[str, Any],
    timestamp: str,
    idempotency_token: str,
    input_artifacts: list[dict[str, Any]] | None = None,
) -> Mapping[str, Any]:
    unit_id = str(unit.get("id", "") or "stage").strip() or "stage"
    app_name = str(unit.get("app", "") or "").strip()
    if not app_name:
        raise RuntimeError(f"Distributed DAG stage `{unit_id}` is missing its app name.")
    token = str(idempotency_token).strip()
    if not token:
        raise RuntimeError(f"Distributed DAG stage `{unit_id}` requires an idempotency token.")

    inputs = validate_distributed_stage_inputs(unit, input_artifacts)
    apps_path = resolve_stage_apps_path(repo_root, app_name)
    request_payload = request_payload_from_execution_contract(execution_contract)
    request_payload["idempotency_token"] = token
    if inputs:
        request_payload["input_artifacts"] = inputs
    run_root.mkdir(parents=True, exist_ok=True)
    outputs = unit.get("produces")
    declared_outputs = outputs if isinstance(outputs, list) else [artifact]
    roots, output_roots = _distributed_output_roots(config, run_root, request_payload)
    declared_paths = [
        candidate
        for output in declared_outputs
        if isinstance(output, Mapping)
        for candidate in _distributed_path_candidates(
            str(output.get("path", "")).strip(), output_roots
        )
        if any(candidate.resolve().is_relative_to(root) for root in roots)
    ]
    freshness = ArtifactOutputSnapshot(
        workspaces=[run_root, *output_roots[len(roots) :]],
        declared_paths=declared_paths,
    )

    runner_result = dict(
        runner_fn(
            config=config,
            repo_root=repo_root,
            lab_dir=lab_dir,
            run_root=run_root,
            apps_path=apps_path,
            app_name=app_name,
            unit=dict(unit),
            artifact=dict(artifact),
            execution_contract=dict(execution_contract),
            request_payload=request_payload,
            timestamp=timestamp,
            idempotency_token=token,
        )
    )
    if runner_result.get("status") == "error" or runner_result.get("returncode", 0):
        raise RuntimeError(
            f"Distributed DAG stage `{unit_id}` runner reported a failed result."
        )
    if inputs:
        # The endpoint must return what its child orchestrator actually consumed.
        runner_result["input_artifact_fingerprint"] = _input_artifact_fingerprint(inputs)
        require_distributed_input_receipts(runner_result, inputs, app_name=app_name)
    evidence_path = _distributed_evidence_path(run_root, artifact)
    evidence_payload = {
        "schema": "agilab.distributed_dag_stage_submission.v1",
        "unit_id": unit_id,
        "app": app_name,
        "apps_path": str(apps_path),
        "artifact": dict(artifact),
        "created_at": timestamp,
        "idempotency_token": token,
        "execution_contract": dict(execution_contract),
        "request_payload": request_payload,
        "cluster": {
            "scheduler": config.scheduler,
            "workers": config.workers,
            "workers_data_path": config.workers_data_path,
            "mode": config.mode,
            "worker_nodes": config.worker_nodes,
            "worker_slots": config.worker_slots,
        },
        "runner_result": _jsonable(runner_result),
    }

    default_metrics = {
        "stage_completed": 1,
        "distributed_submissions": 1,
        "worker_nodes": config.worker_nodes,
        "worker_slots": config.worker_slots,
    }
    runner_metrics = runner_result.get("summary_metrics")
    if isinstance(runner_metrics, Mapping):
        default_metrics.update(runner_metrics)

    result: dict[str, Any] = {
        "submission_evidence_path": str(evidence_path),
        "summary_metrics": default_metrics,
        "distributed_submission": {
            "app": app_name,
            "apps_path": str(apps_path),
            "scheduler": config.scheduler,
            "workers": config.workers,
            "workers_data_path": config.workers_data_path,
            "mode": config.mode,
            "idempotency_token": token,
        },
        "idempotency_token": token,
    }
    result.update(runner_result)
    result["summary_metrics"] = default_metrics
    result["submission_evidence_path"] = str(evidence_path)
    verified_outputs: list[dict[str, Any]] = []
    worker_output_collection: list[dict[str, Any]] = []
    primary_id = str(artifact.get("artifact", "") or artifact.get("id", "")).strip()
    validation_passed = False
    try:
        for output in declared_outputs:
            if not isinstance(output, Mapping):
                continue
            artifact_id = str(
                output.get("artifact", "") or output.get("id", "")
            ).strip()
            if not artifact_id:
                continue
            kind = str(output.get("kind", "")).strip()
            if kind == "contract_artifact":
                output_path = evidence_path
            else:
                try:
                    output_path = _distributed_output_path(
                        config=config,
                        run_root=run_root,
                        output=output,
                        request_payload=request_payload,
                        runner_result=runner_result,
                        primary_artifact_id=primary_id,
                        primary_kind=str(artifact.get("kind", "")),
                        primary_declared_path=str(artifact.get("path", "")),
                        freshness=freshness,
                    )
                except _MissingDistributedOutput:
                    reported = reported_artifact_paths(runner_result)
                    if (
                        kind != "summary_metrics"
                        or reported.get(artifact_id)
                        or runner_result.get(_artifact_result_path_key(kind))
                        or sum(
                            isinstance(item, Mapping)
                            and item.get("kind") == "summary_metrics"
                            for item in declared_outputs
                        ) != 1
                    ):
                        raise
                    output_path, metrics, collection = _collect_worker_summary_output(
                        config=config, run_root=run_root, output=output,
                        request_payload=request_payload, freshness=freshness,
                    )
                    default_metrics.update(metrics)
                    worker_output_collection.append(collection)
                    result["worker_output_collection"] = worker_output_collection
                freshness.require_fresh(output_path, artifact_id=artifact_id)
            record = {"artifact": artifact_id, "kind": kind, "path": str(output_path)}
            if kind != "contract_artifact":
                bind_artifact_identities([record], run_root=run_root, bind_new=True)
            verified_outputs.append(record)
            if artifact_id == primary_id:
                result[_artifact_result_path_key(kind)] = str(output_path)
        validation_passed = bool(verified_outputs)
    finally:
        # Persist submission evidence only after observing output generations.
        # Writing the receipt must not itself make a scientific directory fresh.
        if worker_output_collection:
            evidence_payload["worker_output_collection"] = worker_output_collection
        evidence_payload["artifact_validation"] = {
            "status": "passed" if validation_passed else "failed",
            "produced_artifacts": verified_outputs,
        }
        write_json_atomic(evidence_path, evidence_payload)
    if not verified_outputs:
        raise RuntimeError(
            f"Distributed DAG stage `{unit_id}` has no declared output artifact."
        )
    # The receipt now exists, so contract-artifact identities can bind its final bytes.
    bind_artifact_identities(verified_outputs, run_root=run_root, bind_new=True)
    result["produced_artifacts"] = verified_outputs
    result["receipt_only"] = all(
        output["kind"] == "contract_artifact" for output in verified_outputs
    )
    return result


def _distributed_output_path(
    *,
    config: DagDistributedStageConfig,
    run_root: Path,
    output: Mapping[str, Any],
    request_payload: Mapping[str, Any],
    runner_result: Mapping[str, Any],
    primary_artifact_id: str,
    primary_kind: str,
    primary_declared_path: str = "",
    freshness: ArtifactOutputSnapshot | None = None,
) -> Path:
    """Find real outputs in the stage workspace or the SDK's worker data share."""
    artifact_id = str(output.get("artifact", "") or output.get("id", "")).strip()
    kind = str(output.get("kind", "")).strip()
    key = _artifact_result_path_key(kind)
    reported_paths = reported_artifact_paths(runner_result)
    reported_path = reported_paths.get(artifact_id, "")
    explicit_path = bool(reported_path)
    if not explicit_path:
        reported_path = str(runner_result.get(key, "")).strip()
        if artifact_id != primary_artifact_id and key == _artifact_result_path_key(
            primary_kind
        ):
            reported_path = ""
    declared_path = str(output.get("path", "")).strip()
    roots, output_roots = _distributed_output_roots(config, run_root, request_payload)
    candidates: list[Path] = []
    for value in (reported_path, declared_path):
        candidates.extend(_distributed_path_candidates(value, output_roots))
    for candidate in candidates:
        resolved = candidate.resolve()
        if artifact_id != primary_artifact_id and not explicit_path:
            primary_reported = (
                reported_paths.get(primary_artifact_id, "")
                or str(
                    runner_result.get(_artifact_result_path_key(primary_kind), "")
                ).strip()
                or primary_declared_path
            )
            if primary_reported:
                primary_candidates = _distributed_path_candidates(
                    primary_reported, output_roots
                )
                if any(resolved == primary.resolve() for primary in primary_candidates):
                    # Legacy kind aliases can all describe the primary output.
                    continue
        if not any(resolved.is_relative_to(root) for root in roots):
            continue
        if resolved.exists() and (
            kind not in {"summary_metrics", "reduce_summary"} or resolved.is_file()
        ):
            if is_contract_receipt_artifact(resolved):
                raise RuntimeError(
                    f"Submission or contract receipt cannot satisfy scientific artifact `{artifact_id}`."
                )
            if freshness is not None:
                try:
                    freshness.require_fresh(candidate, artifact_id=artifact_id)
                except RuntimeError:
                    continue
            return resolved
    raise _MissingDistributedOutput(
        f"Distributed DAG stage did not produce declared artifact `{artifact_id}` "
        "in its stage workspace or configured worker data share."
    )



class _MissingDistributedOutput(RuntimeError):
    """A successful runner did not publish a fresh, explicitly named output."""


def _require_unlinked_collection_path(path: Path, root: Path) -> None:
    try:
        relative = path.absolute().relative_to(root.absolute())
    except ValueError as exc:
        raise ValueError("Worker output collection path escapes its workspace.") from exc
    current = root
    for component in (None, *relative.parts):
        if component is not None:
            current = current / component
        if current.is_symlink() or current.is_junction():
            raise ValueError(f"Worker output collection contains a symlink or junction: {current}")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Worker output collection path escapes its workspace.")


def _collect_worker_summary_output(
    *,
    config: DagDistributedStageConfig,
    run_root: Path,
    output: Mapping[str, Any],
    request_payload: Mapping[str, Any],
    freshness: ArtifactOutputSnapshot,
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    """Bind one fresh SDK summary to its authored alias without rerunning science."""
    artifact_id = str(output.get("artifact", "") or output.get("id", "")).strip()
    declared = Path(str(output.get("path", "")).strip())
    if not declared.parts or declared.is_absolute() or ".." in declared.parts:
        raise ValueError("Collected worker summaries require a relative stage output alias.")
    destination = run_root / declared
    _require_unlinked_collection_path(destination, run_root)

    roots, _ = _distributed_output_roots(config, run_root, request_payload)
    data_out = Path(str(request_payload.get("data_out", "") or "").strip())
    if not str(request_payload.get("data_out", "") or "").strip() or ".." in data_out.parts:
        raise RuntimeError("Worker summary collection requires an explicit bounded data_out.")
    candidates: dict[Path, tuple[Path, Path]] = {}
    searched_roots: list[Path] = []
    visited = 0

    def walk_error(error: OSError) -> None:
        raise error

    for share_root in roots[1:]:
        scoped_root = share_root / data_out
        if not scoped_root.absolute().is_relative_to(share_root.absolute()):
            continue
        _require_unlinked_collection_path(scoped_root, share_root)
        searched_roots.append(scoped_root)
        try:
            scoped_root.stat()
        except (FileNotFoundError, NotADirectoryError):
            continue
        for current, directories, files in os.walk(
            scoped_root, followlinks=False, onerror=walk_error,
        ):
            parent = Path(current)
            visited += len(directories) + len(files)
            if visited > 4096 or (
                len(parent.relative_to(scoped_root).parts) >= 8 and directories
            ):
                raise RuntimeError("Worker summary output inventory exceeds its bounded collection limit.")
            for name in directories:
                _require_unlinked_collection_path(parent / name, scoped_root)
            for name in files:
                if not name.endswith("_summary_metrics.json"):
                    continue
                source = parent / name
                _require_unlinked_collection_path(source, scoped_root)
                try:
                    freshness.require_fresh(source, artifact_id=artifact_id)
                except RuntimeError:
                    continue
                candidates[source] = (scoped_root, share_root)
    if len(candidates) != 1:
        problem = "missing" if not candidates else "ambiguous"
        searched = ", ".join(str(root)[:500] for root in searched_roots)
        raise RuntimeError(
            f"Worker summary artifact {artifact_id!r} is {problem}: found "
            f"{len(candidates)} fresh summaries; searched data_out roots: {searched or '(none)'}."
        )
    source, (source_root, source_share) = next(iter(candidates.items()))
    limit = 1024 * 1024

    def source_generation(descriptor: int | None = None) -> tuple[int, ...]:
        _require_unlinked_collection_path(source, source_share)
        stat = source.stat() if descriptor is None else os.fstat(descriptor)
        if not S_ISREG(stat.st_mode):
            raise ValueError("Collected worker summary must be a regular file.")
        if stat.st_size > limit:
            raise RuntimeError("Worker summary JSON exceeds the bounded collection size.")
        return (
            stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns,
        )

    generation = source_generation()
    with source.open("rb") as stream:
        if source_generation(stream.fileno()) != generation:
            raise RuntimeError("Worker summary opened a different file generation.")
        raw = stream.read(limit + 1)
        if source_generation(stream.fileno()) != generation:
            raise RuntimeError("Worker summary descriptor changed to a different file generation.")
    if len(raw) > limit:
        raise RuntimeError("Worker summary JSON exceeds the bounded collection size.")
    if source_generation() != generation or len(raw) != generation[2]:
        raise RuntimeError("Worker summary changed while its output bytes were collected.")
    if is_contract_receipt_artifact(source):
        raise RuntimeError("A submission or contract receipt cannot satisfy a worker summary.")
    source_identity = {
        "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
    }
    metrics = json.loads(raw)
    if not isinstance(metrics, dict) or not metrics:
        raise ValueError("Worker summary must contain a nonempty JSON metrics object.")
    json.dumps(metrics, allow_nan=False)
    if set(metrics).issubset({
        "stage_completed", "distributed_submissions", "worker_nodes", "worker_slots",
    }):
        raise ValueError("Operational submission counters cannot satisfy a scientific worker summary.")
    _require_unlinked_collection_path(destination, run_root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=destination.parent,
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
        _require_unlinked_collection_path(destination, run_root)
        if source_generation() != generation:
            raise RuntimeError("Worker summary changed before its collected alias was published.")
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    if artifact_file_identity(destination) != source_identity:
        raise RuntimeError("Collected worker summary bytes differ from their original identity.")
    receipt = {
        "schema": "agilab.distributed_worker_output_collection.v1",
        "artifact": artifact_id, "kind": "summary_metrics",
        "source_path": str(source), "source_identity": source_identity,
        "path": str(destination), "copied_sha256": source_identity["sha256"],
        "requested_workers_data_path": config.workers_data_path,
        "observed_output_share_root": str(source_share),
        "observed_data_out_root": str(source_root),
    }
    return destination, metrics, receipt


def _distributed_output_roots(
    config: DagDistributedStageConfig,
    run_root: Path,
    request_payload: Mapping[str, Any],
) -> tuple[list[Path], list[Path]]:
    roots = [run_root.resolve()]
    # Reuse the SDK's home-relative share and module-scoped data-root semantics.
    from agi_cluster.agi_distributor.runtime.runtime_misc_support import (
        _absolute_workers_data_share_root,
        normalize_workers_data_path,
    )

    normalized_share = normalize_workers_data_path(
        config.workers_data_path,
        args=dict(request_payload),
        worker_args=dict(request_payload.get("params") or {}),
    )
    if normalized_share:
        requested_root = _absolute_workers_data_share_root(None, normalized_share)
        roots.append(requested_root)
        # SDK workers can reconstruct their environment independently of the
        # manager's workflow root and use the configured physical cluster share.
        # Admit only that explicit ancestor of the requested workflow, then
        # snapshot/search the authored data_out under it, never the whole share.
        cluster_share = str(os.environ.get("AGI_CLUSTER_SHARE", "") or "").strip()
        if cluster_share:
            physical_root = _absolute_workers_data_share_root(None, cluster_share)
            if requested_root != physical_root and requested_root.is_relative_to(physical_root):
                roots.append(physical_root)
    data_out = str(request_payload.get("data_out", "") or "").strip()
    data_root = Path(data_out).expanduser() if data_out else None
    output_roots = list(roots)
    if data_root is not None and ".." not in data_root.parts:
        for share_root in roots[1:]:
            scoped_root = (share_root / data_root).resolve()
            if scoped_root.is_relative_to(share_root):
                output_roots.append(scoped_root)
    return roots, output_roots


def _distributed_path_candidates(value: str, roots: list[Path]) -> list[Path]:
    if not value:
        return []
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return [candidate]
    return [root / candidate for root in roots] if ".." not in candidate.parts else []


def run_agilab_stage_subprocess(
    *,
    config: DagDistributedStageConfig,
    repo_root: Path,
    run_root: Path,
    apps_path: Path,
    app_name: str,
    request_payload: Mapping[str, Any],
    timestamp: str,
    idempotency_token: str,
    **kwargs: Any,
) -> Mapping[str, Any]:
    token = str(idempotency_token).strip()
    if not token:
        raise RuntimeError(f"Distributed DAG stage `{app_name}` requires an idempotency token.")
    inputs = _verified_distributed_inputs(request_payload.get("input_artifacts", []))
    result = execute_idempotently(
        run_root=run_root,
        unit_id=app_name,
        idempotency_token=token,
        scope="distributed-subprocess",
        callback=lambda: _run_agilab_stage_subprocess_once(
            config=config,
            repo_root=repo_root,
            run_root=run_root,
            apps_path=apps_path,
            app_name=app_name,
            request_payload=request_payload,
            timestamp=timestamp,
            idempotency_token=token,
            **kwargs,
        ),
    )
    require_distributed_input_receipts(result, inputs, app_name=app_name)
    return result


def _run_agilab_stage_subprocess_once(
    *,
    config: DagDistributedStageConfig,
    repo_root: Path,
    run_root: Path,
    apps_path: Path,
    app_name: str,
    request_payload: Mapping[str, Any],
    timestamp: str,
    idempotency_token: str,
    **_kwargs: Any,
) -> Mapping[str, Any]:
    token = str(idempotency_token).strip()
    if not token:
        raise RuntimeError(f"Distributed DAG stage `{app_name}` requires an idempotency token.")
    inputs = _verified_distributed_inputs(request_payload.get("input_artifacts", []))
    stage_request = dict(request_payload)
    recorded_token = str(stage_request.get("idempotency_token", "")).strip()
    if recorded_token and recorded_token != token:
        raise RuntimeError(
            f"Distributed DAG stage `{app_name}` request token does not match its execution token."
        )
    stage_request["idempotency_token"] = token
    run_root.mkdir(parents=True, exist_ok=True)
    script_path = run_root / "run_distributed_stage.py"
    script_path.write_text(
        _stage_run_script(
            config=config,
            apps_path=apps_path,
            app_name=app_name,
            request_payload=stage_request,
        ),
        encoding="utf-8",
    )
    command = [sys.executable, str(script_path)]
    stdout_path = run_root / "distributed_stage.stdout.log"
    stderr_path = run_root / "distributed_stage.stderr.log"
    # Do not use capture_output here: AGI stages may launch background Dask
    # processes which inherit pipe file descriptors and prevent EOF.
    with stdout_path.open("w", encoding="utf-8") as stdout_handle, stderr_path.open(
        "w",
        encoding="utf-8",
    ) as stderr_handle:
        log_offsets = {str(stdout_path): 0, str(stderr_path): 0}
        stop_log_tee = threading.Event()
        log_tee_thread = threading.Thread(
            target=_run_worker_log_file_tee,
            args=(stdout_path, stderr_path, log_offsets, stop_log_tee),
            daemon=True,
        )
        log_tee_thread.start()
        try:
            command_env = os.environ.copy()
            command_env["AGILAB_IDEMPOTENCY_TOKEN"] = token
            completed = subprocess.run(
                command,
                cwd=repo_root,
                env=command_env,
                text=True,
                stdout=stdout_handle,
                stderr=stderr_handle,
                check=False,
            )
        finally:
            stdout_handle.flush()
            stderr_handle.flush()
            stop_log_tee.set()
            log_tee_thread.join(timeout=_REMOTE_LOG_STREAM_INTERVAL_SECONDS + 1.0)
            _tee_worker_log_file_updates(stdout_path, stderr_path, log_offsets)
    stdout_tail = _tail_file(stdout_path)
    stderr_tail = _tail_file(stderr_path)
    payload = {
        "created_at": timestamp,
        "command": command,
        "script": str(script_path),
        "returncode": completed.returncode,
        "stdout_log": str(stdout_path),
        "stderr_log": str(stderr_path),
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
        "idempotency_token": token,
    }
    if completed.returncode:
        detail = stderr_tail.strip() or stdout_tail.strip() or f"exit {completed.returncode}"
        raise RuntimeError(f"Distributed DAG stage `{app_name}` failed: {_tail(detail, max_chars=3800)}")
    failure_detail = _stage_result_failure(stdout_tail)
    if failure_detail:
        # Defense in depth: AGI.run can swallow ProcessError/ConnectionError
        # and the script may still print a null/error result; never record
        # success evidence for such a stage.
        raise RuntimeError(
            f"Distributed DAG stage `{app_name}` failed: {_tail(failure_detail, max_chars=3800)}"
        )
    if inputs:
        payload["input_artifact_fingerprint"] = _input_artifact_fingerprint(inputs)
    stage_result = _stage_result_payload(stdout_tail)
    if isinstance(stage_result, Mapping):
        reported_artifact_paths(stage_result)
        for key in (
            "contract_artifact_path",
            "reduce_artifact_path",
            "summary_metrics_path",
            "summary_metrics",
            "produced_artifacts",
            "consumed_artifacts",
        ):
            if key in stage_result:
                payload[key] = stage_result[key]
    require_distributed_input_receipts(payload, inputs, app_name=app_name)
    return payload


def _stage_result_payload(stdout_tail: str) -> Any:
    for line in reversed(stdout_tail.strip().splitlines()):
        try:
            parsed = json.loads(line.strip())
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, Mapping) and "result" in parsed:
            return parsed["result"]
    return None


def _run_worker_log_file_tee(
    stdout_path: Path,
    stderr_path: Path,
    offsets: dict[str, int],
    stop_event: threading.Event,
) -> None:
    """Forward appended worker log-file content while the stage process runs."""
    while not stop_event.wait(_REMOTE_LOG_STREAM_INTERVAL_SECONDS):
        _tee_worker_log_file_updates(stdout_path, stderr_path, offsets)


def _tee_worker_log_file_updates(stdout_path: Path, stderr_path: Path, offsets: dict[str, int]) -> None:
    _tee_log_file_update(stdout_path, sys.stdout, offsets)
    _tee_log_file_update(stderr_path, sys.stderr, offsets)


def _tee_log_file_update(path: Path, stream: TextIO, offsets: dict[str, int]) -> None:
    key = str(path)
    offset = offsets.get(key, 0)
    try:
        with path.open("r", encoding="utf-8", errors="replace") as log_file:
            log_file.seek(offset)
            text = log_file.read()
            offsets[key] = log_file.tell()
    except OSError:
        return
    if text:
        try:
            stream.write(text)
            stream.flush()
        except (OSError, ValueError):
            return


def _stage_result_failure(stdout_tail: str) -> str | None:
    """Return a failure description when the stage printed a null/error result."""
    for line in reversed(stdout_tail.strip().splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, Mapping) or "result" not in parsed:
            continue
        result = parsed.get("result")
        if result is None:
            return "AGI.run returned no result (worker launch or environment failure)"
        if isinstance(result, Mapping) and result.get("status") == "error":
            return str(result.get("message") or "AGI.run reported an error result")
        return None
    return None


def resolve_stage_apps_path(repo_root: Path, app_name: str) -> Path:
    candidates = (
        repo_root / "src" / "agilab" / "apps" / "builtin",
        repo_root / "src" / "agilab" / "apps",
    )
    for apps_path in candidates:
        app_path = apps_path / app_name
        if app_path.is_dir():
            return apps_path
    raise RuntimeError(
        f"Distributed DAG stage app `{app_name}` was not found under "
        "`src/agilab/apps/builtin` or `src/agilab/apps`."
    )


def request_payload_from_execution_contract(contract: Mapping[str, Any]) -> dict[str, Any]:
    params = contract.get("params") or contract.get("run_params") or {}
    if "steps" in contract or "run_steps" in contract:
        raise ValueError("Execution contracts must use 'stages'; legacy 'steps'/'run_steps' keys are not supported.")
    stages = contract.get("stages") or []
    payload: dict[str, Any] = {
        "params": dict(params) if isinstance(params, Mapping) else {},
        "stages": list(stages) if isinstance(stages, list) else [],
        "data_in": contract.get("data_in"),
        "data_out": contract.get("data_out"),
        "reset_target": contract.get("reset_target"),
        "rapids_enabled": bool(contract.get("rapids_enabled", False)),
        "benchmark_best_single_node": bool(contract.get("benchmark_best_single_node", False)),
    }
    return payload


def _preview_apps_path(repo_root: Path, app_name: str) -> str:
    if not app_name:
        return "-"
    try:
        apps_path = resolve_stage_apps_path(repo_root, app_name)
    except RuntimeError:
        return "missing"
    try:
        return apps_path.resolve(strict=False).relative_to(repo_root.resolve(strict=False)).as_posix()
    except ValueError:
        return str(apps_path)


def _compact_json(value: Mapping[str, Any]) -> str:
    return json.dumps(_jsonable(dict(value)), sort_keys=True, separators=(",", ":"))


def _stage_run_script(
    *,
    config: DagDistributedStageConfig,
    apps_path: Path,
    app_name: str,
    request_payload: Mapping[str, Any],
) -> str:
    request_json = json.dumps(dict(request_payload), sort_keys=True)
    workers_json = json.dumps(config.workers, sort_keys=True)
    return f'''\
import asyncio
import json
import os
import sys

from agi_cluster.agi_distributor import AGI, RunRequest, StageRequest
from agi_env import AgiEnv
from agilab.dag.dag_distributed_submitter import _verified_distributed_inputs
from agilab.global_pipeline.global_pipeline_app_dispatch_smoke import _read_queue_context


APPS_PATH = {str(apps_path)!r}
APP = {app_name!r}
REQUEST_PAYLOAD = json.loads({request_json!r})
WORKERS = json.loads({workers_json!r})
os.environ["AGILAB_IDEMPOTENCY_TOKEN"] = str(REQUEST_PAYLOAD["idempotency_token"])


async def main():
    inputs = _verified_distributed_inputs(REQUEST_PAYLOAD.get("input_artifacts", []))
    consumed_artifacts = []
    for item in inputs:
        receipt = dict(item)
        receipt.update(role="declared_input_reference", numerically_conditioned=False)
        if APP == "uav_relay_queue_project" and item["artifact"] == "queue_metrics":
            receipt.update(_read_queue_context({{
                "producer": item["producer"],
                "summary_metrics_path": item["path"],
                "summary_metrics_sha256": item["sha256"],
            }}))
            receipt["read_scope"] = "child_orchestrator"
        consumed_artifacts.append(receipt)

    app_env = AgiEnv(apps_path=APPS_PATH, app=APP, verbose={int(config.verbose)!r})
    await AGI.install(
        app_env,
        scheduler={config.scheduler!r},
        workers=WORKERS,
        workers_data_path={config.workers_data_path!r},
        modes_enabled={int(config.mode)!r},
        verbose={int(config.verbose)!r},
    )
    stages = [
        StageRequest(name=stage["name"], args=stage.get("args") or {{}})
        for stage in REQUEST_PAYLOAD.get("stages", [])
    ]
    request = RunRequest(
        params=REQUEST_PAYLOAD.get("params") or {{}},
        stages=stages,
        data_in=REQUEST_PAYLOAD.get("data_in"),
        data_out=REQUEST_PAYLOAD.get("data_out"),
        reset_target=REQUEST_PAYLOAD.get("reset_target"),
        scheduler={config.scheduler!r},
        workers=WORKERS,
        workers_data_path={config.workers_data_path!r},
        verbose={int(config.verbose)!r},
        mode={int(config.mode)!r},
        rapids_enabled=bool(REQUEST_PAYLOAD.get("rapids_enabled", False)),
        benchmark_best_single_node=bool(REQUEST_PAYLOAD.get("benchmark_best_single_node", False)),
    )
    result = await AGI.run(app_env, request=request)
    # No success consumption receipt is emitted for a failed AGI.run.
    if result is None or (isinstance(result, dict) and result.get("status") == "error"):
        print(json.dumps({{"result": result}}, default=str))
        sys.exit(1)
    if inputs:
        result = dict(result) if isinstance(result, dict) else {{"value": result}}
        result["consumed_artifacts"] = consumed_artifacts
    print(json.dumps({{"result": result}}, default=str))


if __name__ == "__main__":
    asyncio.run(main())
'''


def _distributed_evidence_path(run_root: Path, artifact: Mapping[str, Any]) -> Path:
    artifact_id = str(artifact.get("artifact", "") or artifact.get("id", "") or "stage_result").strip()
    safe_artifact_id = (
        re.sub(r"[^A-Za-z0-9_.-]+", "-", artifact_id).strip(".-") or "stage-result"
    )
    return (
        run_root
        / "distributed_submission_evidence"
        / f"{safe_artifact_id}-distributed-submission-evidence.json"
    )


def _load_settings_file(path_value: Any) -> dict[str, Any]:
    if path_value in (None, ""):
        return {}
    path = Path(path_value)
    try:
        # Keep the optional agi-env dependency out of base-package imports.
        from agi_env.app_settings_support import read_app_settings
    except ModuleNotFoundError as exc:
        if not str(getattr(exc, "name", "") or "").startswith("agi_env"):
            raise
        loaded = _read_settings_file_stdlib(path)
    else:
        try:
            loaded = read_app_settings(path)
        except (OSError, ValueError):
            return {}
    return dict(loaded) if isinstance(loaded, Mapping) else {}


def _read_settings_file_stdlib(path: Path) -> dict[str, Any]:
    """Read settings when the optional ``agi-env`` package is unavailable."""

    deadline = time.monotonic() + 0.5
    while True:
        try:
            with path.open("rb") as stream:
                loaded = tomllib.load(stream)
            return dict(loaded) if isinstance(loaded, Mapping) else {}
        except PermissionError:
            if os.name != "nt":
                return {}
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {}
            time.sleep(min(0.01, remaining))
        except (OSError, tomllib.TOMLDecodeError):
            return {}


def _coerce_workers(value: Any) -> dict[str, int]:
    if isinstance(value, str):
        value = _loads_mapping_text(value)
    if not isinstance(value, Mapping):
        return {}
    workers: dict[str, int] = {}
    for host, slots in value.items():
        host_text = str(host).strip()
        try:
            slot_count = int(slots)
        except (TypeError, ValueError):
            continue
        if host_text and slot_count > 0:
            workers[host_text] = slot_count
    return workers


def _loads_mapping_text(value: str) -> Mapping[str, Any] | None:
    text = value.strip()
    if not text:
        return None
    for loader in (json.loads, ast.literal_eval):
        try:
            loaded = loader(text)
        except (ValueError, SyntaxError, TypeError, json.JSONDecodeError):
            continue
        return loaded if isinstance(loaded, Mapping) else None
    return None


def _tail(text: str, *, max_chars: int = 20000) -> str:
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _tail_file(path: Path, *, max_chars: int = 20000) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - (max_chars * 4)))
            data = handle.read()
    except OSError:
        return ""
    return _tail(data.decode("utf-8", errors="replace"), max_chars=max_chars)


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        if isinstance(value, Mapping):
            return {str(key): _jsonable(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [_jsonable(item) for item in value]
        return str(value)
