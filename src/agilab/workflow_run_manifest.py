from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import platform
from pathlib import Path
import re
import sys
from typing import Any, Mapping, Sequence

from agilab.evidence_graph import (
    EVIDENCE_GRAPH_KIND,
    build_evidence_graph_from_workflow_manifest,
    validate_evidence_graph,
)
from agilab.workflow_runtime_contract import (
    build_workflow_runtime_contract,
    validate_workflow_runtime_contract,
)


WORKFLOW_RUN_MANIFEST_SCHEMA_VERSION = 3
SUPPORTED_WORKFLOW_RUN_MANIFEST_SCHEMAS = {2, WORKFLOW_RUN_MANIFEST_SCHEMA_VERSION}
WORKFLOW_RUN_MANIFEST_KIND = "agilab.workflow_run_manifest"
EVIDENCE_LEDGER_SCHEMA_VERSION = 1
EVIDENCE_LEDGER_KIND = "agilab.evidence_ledger"
WORKFLOW_EVIDENCE_DIRNAME = "workflow_evidence"
WORKFLOW_RUN_MANIFEST_FILENAME = "workflow_run_manifest.json"
EVIDENCE_LEDGER_FILENAME = "evidence_ledger.json"
EVIDENCE_GRAPH_FILENAME = "evidence_graph.json"
LATEST_WORKFLOW_EVIDENCE_FILENAME = "latest_workflow_evidence.json"
SUPPORTED_STATUSES = {"pass", "fail", "unknown"}


@dataclass(frozen=True)
class WorkflowEvidenceBundle:
    manifest_path: Path
    ledger_path: Path
    graph_path: Path
    latest_path: Path
    manifest: dict[str, Any]
    ledger: dict[str, Any]
    graph: dict[str, Any]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def canonical_json_bytes(payload: Mapping[str, Any] | Sequence[Any]) -> bytes:
    return json.dumps(
        _json_safe(payload),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_payload(payload: Mapping[str, Any] | Sequence[Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def workflow_state_digest(state: Mapping[str, Any]) -> str:
    return sha256_payload(dict(state))


def workflow_evidence_root(lab_dir: Path) -> Path:
    return lab_dir.expanduser() / ".agilab" / WORKFLOW_EVIDENCE_DIRNAME


def workflow_evidence_paths(lab_dir: Path, manifest_id: str) -> tuple[Path, Path, Path]:
    root = workflow_evidence_root(lab_dir)
    evidence_dir = root / _safe_id(manifest_id)
    return (
        evidence_dir / WORKFLOW_RUN_MANIFEST_FILENAME,
        evidence_dir / EVIDENCE_LEDGER_FILENAME,
        root / LATEST_WORKFLOW_EVIDENCE_FILENAME,
    )


def workflow_evidence_graph_path(lab_dir: Path, manifest_id: str) -> Path:
    return workflow_evidence_root(lab_dir) / _safe_id(manifest_id) / EVIDENCE_GRAPH_FILENAME


def build_workflow_run_manifest(
    *,
    state: Mapping[str, Any],
    state_path: Path,
    repo_root: Path,
    lab_dir: Path,
    dag_path: Path | None = None,
    trigger: Mapping[str, Any] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build a stable workflow/DAG run manifest from persisted runner state."""
    state_snapshot = _json_safe(dict(state))
    state_sha256 = workflow_state_digest(state)
    run_id = _safe_id(str(state.get("run_id", "") or "workflow-run"))
    manifest_id = f"{run_id}-v{WORKFLOW_RUN_MANIFEST_SCHEMA_VERSION}-{state_sha256[:12]}"
    manifest_path, ledger_path, _latest_path = workflow_evidence_paths(lab_dir, manifest_id)
    graph_path = workflow_evidence_graph_path(lab_dir, manifest_id)
    units = _unit_rows(state)
    produced_artifacts, consumed_artifacts = _artifact_contracts(units)
    status = _manifest_status(state, units)
    runtime_contract = build_workflow_runtime_contract(state)
    source = state.get("source", {})
    source = source if isinstance(source, Mapping) else {}
    summary = state.get("summary", {})
    summary = summary if isinstance(summary, Mapping) else {}
    timestamp = created_at or _state_timestamp(state)

    validations = _manifest_validations(
        state=state,
        units=units,
        produced_artifacts=produced_artifacts,
        consumed_artifacts=consumed_artifacts,
    )
    return {
        "schema_version": WORKFLOW_RUN_MANIFEST_SCHEMA_VERSION,
        "kind": WORKFLOW_RUN_MANIFEST_KIND,
        "manifest_id": manifest_id,
        "run_id": str(state.get("run_id", "") or ""),
        "status": status,
        "created_at": timestamp,
        "workflow": {
            "source_type": str(source.get("source_type", "") or "multi_app_dag"),
            "dag_path": _workflow_source_path(source, dag_path, repo_root),
            "stages_file": str(source.get("stages_file", "") or ""),
            "plan_schema": str(source.get("plan_schema", "") or ""),
            "plan_runner_status": str(source.get("plan_runner_status", "") or ""),
            "execution_order": [str(item) for item in source.get("execution_order", [])]
            if isinstance(source.get("execution_order"), list)
            else [str(unit.get("id", "")) for unit in units if str(unit.get("id", ""))],
            "unit_count": len(units),
        },
        "runtime": {
            "python_version": platform.python_version(),
            "python_executable": sys.executable,
            "platform": platform.platform(),
            "repo_root": str(repo_root.expanduser().resolve(strict=False)),
            "lab_dir": str(lab_dir.expanduser().resolve(strict=False)),
        },
        "trigger": _json_safe(dict(trigger or {})),
        "runner_state": {
            "path": str(state_path.expanduser()),
            "exists": state_path.expanduser().is_file(),
            "sha256": _sha256_file_or_empty(state_path),
            "snapshot_sha256": state_sha256,
            "schema": str(state.get("schema", "") or ""),
            "run_status": str(state.get("run_status", "") or ""),
            "summary": _json_safe(dict(summary)),
        },
        "artifact_contracts": {
            "produced_count": len(produced_artifacts),
            "consumed_count": len(consumed_artifacts),
            "produced": produced_artifacts,
            "consumed": consumed_artifacts,
        },
        "stages": [_stage_record(unit) for unit in units],
        "artifacts": [_file_record(state_path, name="runner_state", kind="runner_state")],
        "validations": validations,
        "runtime_contract": runtime_contract,
        "evidence_ledger": {
            "path": str(ledger_path),
            "kind": EVIDENCE_LEDGER_KIND,
        },
        "evidence_graph": {
            "path": str(graph_path),
            "kind": EVIDENCE_GRAPH_KIND,
        },
        "state_snapshot": {
            "sha256": state_sha256,
            "event_count": len(state_snapshot.get("events", []))
            if isinstance(state_snapshot.get("events"), list)
            else 0,
        },
    }


def build_evidence_ledger(
    manifest: Mapping[str, Any],
    *,
    manifest_path: Path,
    ledger_path: Path,
    extra_artifacts: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    manifest_digest = sha256_payload(dict(manifest))
    manifest_id = str(manifest.get("manifest_id", "") or "")
    claims = []
    for validation in manifest.get("validations", []):
        if not isinstance(validation, Mapping):
            continue
        claim_id = str(validation.get("id", "") or validation.get("label", "") or "validation")
        claims.append(
            {
                "id": claim_id,
                "status": str(validation.get("status", "unknown") or "unknown"),
                "summary": str(validation.get("summary", "") or ""),
                "evidence": [
                    {
                        "kind": WORKFLOW_RUN_MANIFEST_KIND,
                        "manifest_id": manifest_id,
                        "path": str(manifest_path),
                        "sha256": manifest_digest,
                    }
                ],
            }
        )
    artifacts = [
        {
            "name": WORKFLOW_RUN_MANIFEST_FILENAME,
            "kind": WORKFLOW_RUN_MANIFEST_KIND,
            "path": str(manifest_path),
            "sha256": manifest_digest,
        },
        {
            "name": EVIDENCE_LEDGER_FILENAME,
            "kind": EVIDENCE_LEDGER_KIND,
            "path": str(ledger_path),
        },
    ]
    artifacts.extend(_json_safe(dict(artifact)) for artifact in extra_artifacts or [])
    return {
        "schema_version": EVIDENCE_LEDGER_SCHEMA_VERSION,
        "kind": EVIDENCE_LEDGER_KIND,
        "ledger_id": f"ledger-{manifest_id}",
        "manifest_id": manifest_id,
        "run_id": str(manifest.get("run_id", "") or ""),
        "status": str(manifest.get("status", "unknown") or "unknown"),
        "created_at": str(manifest.get("created_at", "") or utc_now()),
        "claims": claims,
        "artifacts": artifacts,
    }


def write_workflow_run_evidence(
    *,
    state: Mapping[str, Any],
    state_path: Path,
    repo_root: Path,
    lab_dir: Path,
    dag_path: Path | None = None,
    trigger: Mapping[str, Any] | None = None,
    created_at: str | None = None,
) -> WorkflowEvidenceBundle:
    manifest = build_workflow_run_manifest(
        state=state,
        state_path=state_path,
        repo_root=repo_root,
        lab_dir=lab_dir,
        dag_path=dag_path,
        trigger=trigger,
        created_at=created_at,
    )
    manifest_path, ledger_path, latest_path = workflow_evidence_paths(
        lab_dir,
        str(manifest["manifest_id"]),
    )
    graph_path = workflow_evidence_graph_path(lab_dir, str(manifest["manifest_id"]))
    graph = build_evidence_graph_from_workflow_manifest(manifest)
    graph_issues = validate_evidence_graph(graph)
    if graph_issues:
        raise ValueError(f"Invalid workflow evidence graph: {'; '.join(graph_issues)}")
    ledger = build_evidence_ledger(
        manifest,
        manifest_path=manifest_path,
        ledger_path=ledger_path,
        extra_artifacts=[
            {
                "name": EVIDENCE_GRAPH_FILENAME,
                "kind": EVIDENCE_GRAPH_KIND,
                "path": str(graph_path),
                "sha256": sha256_payload(graph),
            }
        ],
    )
    _write_immutable_json(manifest_path, manifest)
    _write_immutable_json(graph_path, graph)
    _write_immutable_json(ledger_path, ledger)
    _write_json(
        latest_path,
        {
            "schema_version": 1,
            "kind": "agilab.latest_workflow_evidence",
            "manifest_id": manifest["manifest_id"],
            "status": manifest["status"],
            "manifest_path": str(manifest_path),
            "ledger_path": str(ledger_path),
            "graph_path": str(graph_path),
            "updated_at": manifest["created_at"],
        },
    )
    return WorkflowEvidenceBundle(
        manifest_path=manifest_path,
        ledger_path=ledger_path,
        graph_path=graph_path,
        latest_path=latest_path,
        manifest=manifest,
        ledger=ledger,
        graph=graph,
    )


def load_workflow_run_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"workflow run manifest must be a JSON object: {path}")
    if int(payload.get("schema_version", 0)) not in SUPPORTED_WORKFLOW_RUN_MANIFEST_SCHEMAS:
        raise ValueError(f"Unsupported workflow run manifest schema: {payload.get('schema_version')!r}")
    if str(payload.get("kind", "")) != WORKFLOW_RUN_MANIFEST_KIND:
        raise ValueError(f"Unsupported workflow run manifest kind: {payload.get('kind')!r}")
    status = str(payload.get("status", "unknown"))
    if status not in SUPPORTED_STATUSES:
        raise ValueError(f"Unsupported workflow run manifest status: {status!r}")
    runtime_contract = payload.get("runtime_contract")
    if runtime_contract is not None:
        if not isinstance(runtime_contract, Mapping):
            raise ValueError("workflow run manifest runtime_contract must be a JSON object")
        issues = validate_workflow_runtime_contract(runtime_contract)
        if issues:
            raise ValueError(f"Invalid workflow runtime contract: {'; '.join(issues)}")
    evidence_graph = payload.get("evidence_graph")
    if evidence_graph is not None and not isinstance(evidence_graph, Mapping):
        raise ValueError("workflow run manifest evidence_graph must be a JSON object")
    return payload


def load_evidence_ledger(path: Path) -> dict[str, Any]:
    payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"evidence ledger must be a JSON object: {path}")
    if int(payload.get("schema_version", 0)) != EVIDENCE_LEDGER_SCHEMA_VERSION:
        raise ValueError(f"Unsupported evidence ledger schema: {payload.get('schema_version')!r}")
    if str(payload.get("kind", "")) != EVIDENCE_LEDGER_KIND:
        raise ValueError(f"Unsupported evidence ledger kind: {payload.get('kind')!r}")
    return payload


def workflow_manifest_summary(manifest: Mapping[str, Any]) -> dict[str, Any]:
    workflow = manifest.get("workflow", {})
    workflow = workflow if isinstance(workflow, Mapping) else {}
    contracts = manifest.get("artifact_contracts", {})
    contracts = contracts if isinstance(contracts, Mapping) else {}
    runtime_contract = manifest.get("runtime_contract", {})
    runtime_contract = runtime_contract if isinstance(runtime_contract, Mapping) else {}
    return {
        "manifest_id": str(manifest.get("manifest_id", "") or ""),
        "run_id": str(manifest.get("run_id", "") or ""),
        "status": str(manifest.get("status", "unknown") or "unknown"),
        "phase": str(runtime_contract.get("phase", "unknown") or "unknown"),
        "dag_path": str(workflow.get("dag_path", "") or ""),
        "unit_count": int(workflow.get("unit_count", 0) or 0),
        "produced_count": int(contracts.get("produced_count", 0) or 0),
        "consumed_count": int(contracts.get("consumed_count", 0) or 0),
        "event_count": int(runtime_contract.get("event_count", 0) or 0),
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_safe(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _write_immutable_json(path: Path, payload: Mapping[str, Any]) -> Path:
    path = path.expanduser()
    text = json.dumps(_json_safe(payload), indent=2, sort_keys=True) + "\n"
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if existing != text:
            raise FileExistsError(f"Refusing to overwrite immutable workflow evidence: {path}")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _safe_id(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")
    return safe or "workflow-run"


def _sha256_file_or_empty(path: Path) -> str:
    path = path.expanduser()
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repo_relative_text(path: Path, repo_root: Path) -> str:
    try:
        return path.expanduser().resolve(strict=False).relative_to(
            repo_root.expanduser().resolve(strict=False)
        ).as_posix()
    except ValueError:
        return str(path.expanduser())


def _workflow_source_path(
    source: Mapping[str, Any],
    dag_path: Path | None,
    repo_root: Path,
) -> str:
    source_dag = str(source.get("dag_path", "") or source.get("source_dag", "") or "").strip()
    if source_dag:
        return source_dag
    if dag_path is None:
        return ""
    return _repo_relative_text(dag_path, repo_root)


def _state_timestamp(state: Mapping[str, Any]) -> str:
    for key in ("updated_at", "created_at"):
        value = str(state.get(key, "") or "").strip()
        if value:
            return value
    events = state.get("events", [])
    if isinstance(events, Sequence) and not isinstance(events, (str, bytes)):
        for event in reversed(events):
            if isinstance(event, Mapping):
                timestamp = str(event.get("timestamp", "") or "").strip()
                if timestamp:
                    return timestamp
    return utc_now()


def _unit_rows(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = state.get("units", [])
    if not isinstance(rows, list):
        return []
    units = [dict(row) for row in rows if isinstance(row, Mapping)]
    units.sort(key=_unit_sort_key)
    return units


def _unit_sort_key(unit: Mapping[str, Any]) -> tuple[int, str]:
    try:
        index = int(unit.get("order_index", 999_999))
    except (TypeError, ValueError):
        index = 999_999
    return index, str(unit.get("id", ""))


def _artifact_contracts(units: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    produced: list[dict[str, str]] = []
    consumed: list[dict[str, str]] = []
    for unit in units:
        unit_id = str(unit.get("id", "") or "")
        app = str(unit.get("app", "") or "")
        for artifact in unit.get("produces", []):
            if not isinstance(artifact, Mapping):
                continue
            artifact_id = str(artifact.get("artifact", "") or artifact.get("id", "") or "").strip()
            if not artifact_id:
                continue
            produced.append(
                {
                    "artifact": artifact_id,
                    "producer": unit_id,
                    "app": app,
                    "kind": str(artifact.get("kind", "") or ""),
                    "path": str(artifact.get("path", "") or ""),
                    "status": str(artifact.get("status", "") or ""),
                }
            )
        for dependency in unit.get("artifact_dependencies", []):
            if not isinstance(dependency, Mapping):
                continue
            artifact_id = str(dependency.get("artifact", "") or "").strip()
            if not artifact_id:
                continue
            consumed.append(
                {
                    "artifact": artifact_id,
                    "consumer": unit_id,
                    "app": app,
                    "from": str(dependency.get("from", "") or ""),
                    "from_app": str(dependency.get("from_app", "") or ""),
                    "source_path": str(dependency.get("source_path", "") or ""),
                }
            )
    return produced, consumed


def _stage_record(unit: Mapping[str, Any]) -> dict[str, Any]:
    contract = unit.get("execution_contract", {})
    contract_payload = dict(contract) if isinstance(contract, Mapping) else {}
    return {
        "id": str(unit.get("id", "") or ""),
        "app": str(unit.get("app", "") or ""),
        "status": str(unit.get("dispatch_status", "") or ""),
        "order_index": unit.get("order_index"),
        "depends_on": [str(item) for item in unit.get("depends_on", [])]
        if isinstance(unit.get("depends_on"), list)
        else [],
        "produces": [
            str(item.get("artifact", "") or item.get("id", ""))
            for item in unit.get("produces", [])
            if isinstance(item, Mapping) and str(item.get("artifact", "") or item.get("id", ""))
        ],
        "execution_contract_sha256": sha256_payload(contract_payload) if contract_payload else "",
    }


def _manifest_status(state: Mapping[str, Any], units: Sequence[Mapping[str, Any]]) -> str:
    run_status = str(state.get("run_status", "") or "").strip().lower()
    statuses = {str(unit.get("dispatch_status", "") or "").strip().lower() for unit in units}
    if run_status == "failed" or "failed" in statuses:
        return "fail"
    if run_status == "completed" or (units and statuses == {"completed"}):
        return "pass"
    return "unknown"


def _manifest_validations(
    *,
    state: Mapping[str, Any],
    units: Sequence[Mapping[str, Any]],
    produced_artifacts: Sequence[Mapping[str, str]],
    consumed_artifacts: Sequence[Mapping[str, str]],
) -> list[dict[str, Any]]:
    run_status = str(state.get("run_status", "") or "").strip().lower()
    runner_schema = str(state.get("schema", "") or "").strip()
    failed_units = [
        str(unit.get("id", "") or "")
        for unit in units
        if str(unit.get("dispatch_status", "") or "").strip().lower() == "failed"
    ]
    completed_units = [
        str(unit.get("id", "") or "")
        for unit in units
        if str(unit.get("dispatch_status", "") or "").strip().lower() == "completed"
    ]
    return [
        {
            "id": "runner_state_schema",
            "status": "pass" if runner_schema else "fail",
            "summary": "runner state declares a schema" if runner_schema else "runner state schema is missing",
            "details": {"schema": runner_schema},
        },
        {
            "id": "artifact_contracts",
            "status": "pass" if produced_artifacts else "unknown",
            "summary": (
                f"{len(produced_artifacts)} produced and {len(consumed_artifacts)} consumed artifact contract(s)"
            ),
            "details": {
                "produced_count": len(produced_artifacts),
                "consumed_count": len(consumed_artifacts),
            },
        },
        {
            "id": "run_outcome",
            "status": "fail" if failed_units or run_status == "failed" else "pass"
            if units and len(completed_units) == len(units)
            else "unknown",
            "summary": _run_outcome_summary(run_status, len(units), len(completed_units), failed_units),
            "details": {
                "run_status": run_status,
                "unit_count": len(units),
                "completed_unit_count": len(completed_units),
                "failed_unit_ids": failed_units,
            },
        },
    ]


def _run_outcome_summary(
    run_status: str,
    unit_count: int,
    completed_count: int,
    failed_units: Sequence[str],
) -> str:
    if failed_units or run_status == "failed":
        return f"workflow failed; failed units: {', '.join(failed_units) or 'unknown'}"
    if unit_count and completed_count == unit_count:
        return f"workflow completed all {unit_count} unit(s)"
    return f"workflow status is {run_status or 'unknown'}; {completed_count}/{unit_count} unit(s) completed"


def _file_record(path: Path, *, name: str, kind: str) -> dict[str, Any]:
    expanded = path.expanduser()
    exists = expanded.exists()
    return {
        "name": name,
        "path": str(expanded),
        "kind": kind,
        "exists": exists,
        "size_bytes": expanded.stat().st_size if exists and expanded.is_file() else None,
        "sha256": _sha256_file_or_empty(expanded),
    }
