# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Bounded public certification profile for AGILAB compatibility paths."""

from __future__ import annotations

import json
from pathlib import Path
import tomllib
from typing import Any, Mapping


SCHEMA = "agilab.public_certification_profile.v1"
CREATED_AT = "2026-04-25T00:00:34Z"
UPDATED_AT = "2026-04-25T00:00:34Z"
DEFAULT_MATRIX_RELATIVE_PATH = Path("docs/source/data/compatibility_matrix.toml")
NEWCOMER_OPERATOR_PATHS = {
    "source-checkout-first-proof",
    "service-mode-operator-surface",
}


def _load_matrix(path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        payload = tomllib.load(stream)
    entries = payload.get("entries", [])
    if not isinstance(entries, list):
        raise TypeError("compatibility matrix entries must be a list")
    payload["entries"] = [entry for entry in entries if isinstance(entry, dict)]
    return payload


def _certification_row(entry: Mapping[str, Any]) -> dict[str, Any]:
    path_id = str(entry.get("id", "") or "")
    status = str(entry.get("status", "") or "")
    certified = status == "validated"
    return {
        "path_id": path_id,
        "label": str(entry.get("label", "") or ""),
        "surface": str(entry.get("surface", "") or ""),
        "compatibility_status": status,
        "certification_status": (
            "certified_public_evidence" if certified else "documented_not_certified"
        ),
        "certification_level": (
            "public-evidence-v1" if certified else "documentation-boundary-v1"
        ),
        "primary_proof": str(entry.get("primary_proof", "") or ""),
        "scope": str(entry.get("scope", "") or ""),
        "limits": [str(limit) for limit in entry.get("limits", [])],
        "evidence_required": certified,
        "production_certification_claimed": False,
        "extends_beyond_newcomer_operator": (
            certified and path_id not in NEWCOMER_OPERATOR_PATHS
        ),
    }


def build_public_certification_profile(
    repo_root: Path,
    *,
    matrix_path: Path | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    matrix_path = matrix_path or repo_root / DEFAULT_MATRIX_RELATIVE_PATH
    if not matrix_path.is_absolute():
        matrix_path = repo_root / matrix_path
    matrix = _load_matrix(matrix_path)
    rows = [_certification_row(entry) for entry in matrix.get("entries", [])]
    certified_rows = [
        row for row in rows if row["certification_status"] == "certified_public_evidence"
    ]
    documented_rows = [
        row for row in rows if row["certification_status"] == "documented_not_certified"
    ]
    broader_rows = [row for row in rows if row["extends_beyond_newcomer_operator"]]
    issues = []
    if len(certified_rows) < 4:
        issues.append(
            {
                "level": "error",
                "location": "certification.certified_public_evidence",
                "message": "expected at least four evidence-certified public paths",
            }
        )
    if not broader_rows:
        issues.append(
            {
                "level": "error",
                "location": "certification.broader_public_slices",
                "message": "expected certified slices beyond newcomer/operator paths",
            }
        )
    return {
        "schema": SCHEMA,
        "run_id": "public-certification-profile-proof",
        "created_at": CREATED_AT,
        "updated_at": UPDATED_AT,
        "run_status": "validated" if not issues else "invalid",
        "execution_mode": "public_certification_static",
        "source": {
            "matrix_path": str(matrix_path),
            "matrix_version": matrix.get("metadata", {}).get("version", ""),
            "matrix_updated": matrix.get("metadata", {}).get("updated", ""),
        },
        "summary": {
            "schema": SCHEMA,
            "certification_profile": "bounded_public_evidence",
            "path_count": len(rows),
            "certified_public_evidence_count": len(certified_rows),
            "documented_not_certified_count": len(documented_rows),
            "certified_beyond_newcomer_operator_count": len(broader_rows),
            "certified_beyond_newcomer_operator_paths": [
                row["path_id"] for row in broader_rows
            ],
            "production_certification_claimed": False,
            "formal_third_party_certification": False,
            "command_execution_count": 0,
            "network_probe_count": 0,
            "surfaces": sorted({row["surface"] for row in rows}),
        },
        "certification_paths": rows,
        "issues": issues,
        "provenance": {
            "source": "compatibility_matrix",
            "executes_commands": False,
            "queries_network": False,
            "safe_for_public_evidence": True,
        },
    }


def write_public_certification_profile(path: Path, state: Mapping[str, Any]) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_public_certification_profile(path: Path) -> dict[str, Any]:
    return json.loads(path.expanduser().read_text(encoding="utf-8"))


def persist_public_certification_profile(
    *,
    repo_root: Path,
    output_path: Path,
    matrix_path: Path | None = None,
) -> dict[str, Any]:
    state = build_public_certification_profile(repo_root, matrix_path=matrix_path)
    path = write_public_certification_profile(output_path, state)
    reloaded = load_public_certification_profile(path)
    return {
        "ok": state == reloaded and state.get("run_status") == "validated",
        "path": str(path),
        "state": state,
        "reloaded_state": reloaded,
        "round_trip_ok": state == reloaded,
    }
