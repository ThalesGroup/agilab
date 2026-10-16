"""Review an ordinary notebook refresh without executing or discarding project code.

The existing import writer owns persistence. This module verifies the preserved
source and replaces one shared notebook stage, leaving authored workflow fields
and all other stages intact. Recovery bundles contain local source bytes, not
execution evidence or an attestation.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .notebook_execution_plan import compile_notebook_stage
from .notebook_pipeline_import import (
    CONTRACT_SCHEMA,
    NOTEBOOK_DOCUMENT_SCHEMA,
    build_lab_stages_preview,
    build_notebook_pipeline_import,
)

SCHEMA = "agilab.notebook_import_update.v1"
BACKUP_SCHEMA = "agilab.notebook_import_update_backup.v1"
TARGET_NAMES = (
    "notebook_import_contract.json",
    "notebook_import_pipeline_view.json",
    "notebook_import_view_plan.json",
    "lab_stages.toml",
)


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _document(payload: Mapping[str, Any]) -> dict[str, Any]:
    record = payload.get("notebook_document")
    if (
        not isinstance(record, Mapping)
        or record.get("schema") != NOTEBOOK_DOCUMENT_SCHEMA
    ):
        raise ValueError(
            "Notebook update needs the preserved source notebook contract."
        )
    notebook = record.get("notebook")
    if not isinstance(notebook, dict) or sha256(canonical_json(notebook)) != record.get(
        "sha256"
    ):
        raise ValueError("The preserved notebook source fingerprint does not match.")
    cells = notebook.get("cells")
    if not isinstance(cells, list):
        raise ValueError("The preserved notebook has no cell inventory.")
    identities: set[str] = set()
    for cell in cells:
        if not isinstance(cell, Mapping):
            raise ValueError("The preserved notebook has an invalid cell.")
        if cell.get("cell_type") != "code":
            continue
        source = cell.get("source", "")
        text = "".join(source) if isinstance(source, list) else str(source)
        if not text.strip():
            continue
        cell_id = cell.get("id")
        if not isinstance(cell_id, str) or not cell_id.strip() or cell_id in identities:
            raise ValueError(
                "Notebook update requires unique, stable Jupyter code cell IDs; review the source notebook first."
            )
        identities.add(cell_id)
    return notebook


def _verified_stage(
    stage: Mapping[str, Any],
    payload: Mapping[str, Any],
    source_name: str,
) -> list[dict[str, Any]]:
    notebook = _document(payload)
    baseline = build_notebook_pipeline_import(
        notebook=notebook, source_notebook=source_name
    )
    entries = build_lab_stages_preview(baseline, module_name="notebook")["notebook"]
    for entry in entries:
        for key in ("R", "E", "NB_RUNTIME_ROLE"):
            if key in stage:
                entry[key] = stage[key]
            else:
                entry.pop(key, None)
    compiled = compile_notebook_stage(entries)
    if not compiled:
        raise ValueError("Notebook update needs runnable code cells.")
    expected = compiled[0]
    keys = (
        "C",
        "NB_EXECUTION_PLAN_SCHEMA",
        "NB_EXECUTION_STRATEGY",
        "NB_SOURCE_CELLS",
        "NB_SOURCE_SHA256",
        "NB_COMPILED_SHA256",
        "NB_CELL_ID",
    )
    if any(stage.get(key) != expected.get(key) for key in keys):
        raise ValueError(
            "Notebook stage code or source metadata conflicts with its preserved notebook. "
            "Keep your project edits or reconcile them in the notebook before updating."
        )
    return expected["NB_SOURCE_CELLS"]


def plan_notebook_import_update(
    current_content: Mapping[str, Any],
    incoming_content: Mapping[str, Any],
    *,
    notebook_import: Mapping[str, Any],
    previous_contract: Mapping[str, Any],
    module_name: str,
) -> dict[str, Any]:
    """Replace one fully reviewed ordinary notebook stage in place, without writes."""
    if (
        previous_contract.get("schema") != CONTRACT_SCHEMA
        or previous_contract.get("module_name") != module_name
    ):
        raise ValueError(
            "The previous notebook import contract does not belong to this workflow module."
        )
    source = notebook_import.get("source", {})
    previous_source = previous_contract.get("source", {})
    if not isinstance(source, Mapping) or not isinstance(previous_source, Mapping):
        raise ValueError("Notebook source lineage is missing.")
    if any(
        record.get("import_mode") == "agilab_supervisor_metadata"
        for record in (source, previous_source)
    ):
        raise ValueError(
            "Exported workflows use their existing supervisor round-trip, not ordinary notebook update."
        )
    source_name = str(source.get("source_notebook", "") or "")
    if not source_name or previous_source.get("source_notebook") != source_name:
        raise ValueError(
            "The previous import contract names a different source notebook; select the original notebook source."
        )
    incoming = incoming_content.get(module_name)
    current = current_content.get(module_name)
    if (
        not isinstance(incoming, list)
        or len(incoming) != 1
        or not isinstance(incoming[0], Mapping)
    ):
        raise ValueError(
            "Update all runnable cells with Preserve notebook state to replace one notebook-backed stage."
        )
    if not isinstance(current, list):
        raise ValueError("There is no existing notebook stage in this workflow module.")
    candidates = [
        (index, entry)
        for index, entry in enumerate(current)
        if isinstance(entry, Mapping) and entry.get("NB_SOURCE_NOTEBOOK") == source_name
    ]
    if len(candidates) != 1:
        raise ValueError(
            "Notebook update needs exactly one existing stage from this source; resolve missing or ambiguous imports first."
        )
    index, old = candidates[0]
    new = incoming[0]
    if any(
        stage.get("NB_EXECUTION_STRATEGY") != "shared_namespace" for stage in (old, new)
    ):
        raise ValueError(
            "Notebook update requires an existing shared-state notebook stage and Preserve notebook state."
        )
    if new.get("NB_SOURCE_NOTEBOOK") != source_name:
        raise ValueError("The incoming stage names a different notebook source.")
    old_cells = _verified_stage(old, previous_contract, source_name)
    new_cells = _verified_stage(new, notebook_import, source_name)
    old_by_id = {cell["id"]: cell for cell in old_cells}
    new_by_id = {cell["id"]: cell for cell in new_cells}
    common = old_by_id.keys() & new_by_id.keys()
    if not common:
        raise ValueError(
            "No stable source cell IDs match the previous import; review the notebook lineage before replacing it."
        )
    for key in ("R", "E", "NB_RUNTIME_ROLE"):
        if old.get(key, "") != new.get(key, ""):
            raise ValueError(
                "Notebook runtime or environment conflicts with the existing stage; review consistent runtime choices before updating."
            )
    old_order = [cell["id"] for cell in old_cells if cell["id"] in common]
    new_order = [cell["id"] for cell in new_cells if cell["id"] in common]
    moved = set()
    if old_order != new_order:
        moved = {
            cell_id for i, cell_id in enumerate(new_order) if old_order[i] != cell_id
        }
    changes = {
        "added": [cell_id for cell_id in new_by_id if cell_id not in old_by_id],
        "changed": [
            cell_id
            for cell_id in new_by_id
            if cell_id in common
            and new_by_id[cell_id]["sha256"] != old_by_id[cell_id]["sha256"]
        ],
        "removed": [cell_id for cell_id in old_by_id if cell_id not in new_by_id],
        "moved": [cell_id for cell_id in new_by_id if cell_id in moved],
        "unchanged": [
            cell_id
            for cell_id in new_by_id
            if cell_id in common
            and new_by_id[cell_id]["sha256"] == old_by_id[cell_id]["sha256"]
        ],
    }
    # D/Q, runtime, explicit stage IDs, dependencies, templates and custom fields
    # are authored project choices. Only notebook-owned source fields change.
    replacement = copy.deepcopy(dict(old))
    for key in list(replacement):
        if key.startswith("NB_"):
            replacement.pop(key)
    replacement.update(
        {
            key: copy.deepcopy(value)
            for key, value in new.items()
            if key.startswith("NB_") or key == "C"
        }
    )
    merged = copy.deepcopy(dict(current_content))
    merged[module_name][index] = replacement
    return {
        "schema": SCHEMA,
        "module_name": module_name,
        "source_name": source_name,
        "stage_index": index,
        "source_before_sha256": old["NB_SOURCE_SHA256"],
        "source_after_sha256": new["NB_SOURCE_SHA256"],
        "cell_changes": changes,
        "merged_content": merged,
    }


def read_import_targets(stages_file: Path) -> dict[str, bytes | None]:
    """Snapshot the four established import targets; never follow a target link."""
    stages_file = Path(stages_file)
    if stages_file.name != "lab_stages.toml" or stages_file.parent.is_symlink():
        raise ValueError(
            "Notebook updates require a regular lab_stages.toml import directory."
        )
    targets: dict[str, bytes | None] = {}
    for name in TARGET_NAMES:
        target = stages_file.parent / name
        if target.is_symlink():
            raise ValueError(f"Notebook update cannot follow a symbolic link: {name}.")
        try:
            targets[name] = target.read_bytes()
        except FileNotFoundError:
            targets[name] = None
    return targets


def target_signatures(targets: Mapping[str, bytes | None]) -> dict[str, str | None]:
    return {
        name: sha256(data) if data is not None else None
        for name, data in targets.items()
    }


def write_update_backup(
    stages_file: Path, targets: Mapping[str, bytes | None], *, review_signature: str
) -> Path:
    """Retain exact prior bytes in an immutable, content-addressed local bundle."""
    records = {
        name: {
            "status": "present" if data is not None else "absent",
            "size_bytes": len(data) if data is not None else 0,
            "sha256": sha256(data) if data is not None else None,
            "base64": base64.b64encode(data).decode("ascii")
            if data is not None
            else None,
        }
        for name, data in targets.items()
    }
    bundle = {
        "schema": BACKUP_SCHEMA,
        "producer": "agilab.notebook_import_update",
        "review_signature": review_signature,
        "targets": records,
        "scope": "local_source_recovery_only; no execution or authenticity claim",
    }
    encoded = canonical_json(bundle) + b"\n"
    path = Path(stages_file).with_name(
        f"notebook_import_before_update_{sha256(encoded)[:16]}.json"
    )
    if path.is_symlink():
        raise ValueError("Notebook recovery bundle cannot be a symbolic link.")
    try:
        with path.open("xb") as handle:
            handle.write(encoded)
    except FileExistsError:
        if path.read_bytes() != encoded:
            raise ValueError(
                "The existing notebook recovery bundle has different content."
            ) from None
    return path


def verify_update_backup(path: Path) -> dict[str, bytes | None]:
    """Inspect a recovery download without writing files or executing notebook code."""
    if Path(path).is_symlink():
        raise ValueError("Notebook recovery bundle cannot be a symbolic link.")
    bundle = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(bundle, dict) or bundle.get("schema") != BACKUP_SCHEMA:
        raise ValueError("Invalid notebook recovery bundle schema.")
    records = bundle.get("targets")
    if not isinstance(records, dict) or set(records) != set(TARGET_NAMES):
        raise ValueError("Invalid notebook recovery target inventory.")
    restored: dict[str, bytes | None] = {}
    for name, record in records.items():
        if not isinstance(record, dict) or record.get("status") not in {
            "present",
            "absent",
        }:
            raise ValueError("Invalid notebook recovery target status.")
        try:
            data = (
                base64.b64decode(record["base64"], validate=True)
                if record["status"] == "present"
                else None
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Invalid notebook recovery bytes.") from exc
        if record.get("size_bytes") != (
            len(data) if data is not None else 0
        ) or record.get("sha256") != (sha256(data) if data is not None else None):
            raise ValueError(
                "Notebook recovery bytes do not match their recorded hash or size."
            )
        if data is None and record.get("base64") is not None:
            raise ValueError("An absent recovery target must not contain bytes.")
        restored[name] = data
    return restored
