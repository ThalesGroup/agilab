# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Notebook-to-pipeline import model for AGILAB evidence reports."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping


SCHEMA = "agilab.notebook_pipeline_import.v1"
DEFAULT_RUN_ID = "notebook-pipeline-import-proof"
PERSISTENCE_FORMAT = "json"
CREATED_AT = "2026-04-25T00:00:20Z"
UPDATED_AT = "2026-04-25T00:00:20Z"
DEFAULT_NOTEBOOK_RELATIVE_PATH = Path("docs/source/data/notebook_pipeline_import_sample.ipynb")
ARTIFACT_SUFFIXES = (
    ".csv",
    ".json",
    ".parquet",
    ".png",
    ".jpg",
    ".jpeg",
    ".svg",
    ".html",
    ".txt",
    ".toml",
)


@dataclass(frozen=True)
class NotebookPipelineImportIssue:
    level: str
    location: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "level": self.level,
            "location": self.location,
            "message": self.message,
        }


@dataclass(frozen=True)
class NotebookPipelineImportProof:
    ok: bool
    issues: tuple[NotebookPipelineImportIssue, ...]
    path: str
    notebook_path: str
    notebook_import: dict[str, Any]
    reloaded_import: dict[str, Any]

    @property
    def round_trip_ok(self) -> bool:
        return self.notebook_import == self.reloaded_import

    @property
    def pipeline_step_count(self) -> int:
        return _summary_int(self.notebook_import, "pipeline_step_count")

    @property
    def env_hint_count(self) -> int:
        return _summary_int(self.notebook_import, "env_hint_count")

    @property
    def artifact_reference_count(self) -> int:
        return _summary_int(self.notebook_import, "artifact_reference_count")

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "issues": [issue.as_dict() for issue in self.issues],
            "path": self.path,
            "notebook_path": self.notebook_path,
            "round_trip_ok": self.round_trip_ok,
            "pipeline_step_count": self.pipeline_step_count,
            "env_hint_count": self.env_hint_count,
            "artifact_reference_count": self.artifact_reference_count,
            "notebook_import": self.notebook_import,
            "reloaded_import": self.reloaded_import,
        }


def _issue(location: str, message: str) -> NotebookPipelineImportIssue:
    return NotebookPipelineImportIssue(level="error", location=location, message=message)


def _summary_int(state: Mapping[str, Any], key: str) -> int:
    summary = state.get("summary", {})
    value = summary.get(key, 0) if isinstance(summary, dict) else 0
    return int(value or 0)


def _coerce_source_lines(cell_source: Any) -> list[str]:
    if cell_source is None:
        return []
    if isinstance(cell_source, str):
        return cell_source.splitlines(keepends=True)
    if isinstance(cell_source, Iterable):
        return [str(line) for line in cell_source]
    return [str(cell_source)]


def _source_text(cell: Mapping[str, Any]) -> str:
    return "".join(_coerce_source_lines(cell.get("source", [])))


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("notebook import expected a JSON object")
    return payload


def load_notebook(path: Path) -> dict[str, Any]:
    notebook = _read_json(path)
    cells = notebook.get("cells", [])
    if not isinstance(cells, list):
        raise ValueError("notebook format is invalid: cells must be a list")
    return notebook


def _hash_source(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]


def _module_root(name: str) -> str:
    return name.split(".", 1)[0]


def _extract_imports_from_ast(code: str) -> list[str]:
    tree = ast.parse(code)
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(_module_root(alias.name))
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(_module_root(node.module))
    return imports


def _extract_imports_with_regex(code: str) -> list[str]:
    imports: list[str] = []
    for line in code.splitlines():
        import_match = re.match(r"\s*import\s+([A-Za-z_][\w.]*)", line)
        from_match = re.match(r"\s*from\s+([A-Za-z_][\w.]*)\s+import\s+", line)
        if import_match:
            imports.append(_module_root(import_match.group(1)))
        elif from_match:
            imports.append(_module_root(from_match.group(1)))
    return imports


def extract_env_hints(code: str) -> list[str]:
    try:
        imports = _extract_imports_from_ast(code)
    except SyntaxError:
        imports = _extract_imports_with_regex(code)
    return sorted(dict.fromkeys(imports))


def _string_constants_from_ast(code: str) -> list[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    constants: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            constants.append(node.value)
    return constants


def _string_literals_with_regex(code: str) -> list[str]:
    return [
        match.group("value")
        for match in re.finditer(
            r"(?P<quote>['\"])(?P<value>[^'\"]+)(?P=quote)",
            code,
        )
    ]


def _looks_like_artifact(value: str) -> bool:
    lowered = value.lower()
    return any(lowered.endswith(suffix) for suffix in ARTIFACT_SUFFIXES)


def extract_artifact_references(code: str, source_cell_index: int) -> list[dict[str, Any]]:
    candidates = [*_string_constants_from_ast(code), *_string_literals_with_regex(code)]
    references: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = candidate.strip()
        if not normalized or normalized in seen or not _looks_like_artifact(normalized):
            continue
        seen.add(normalized)
        references.append(
            {
                "path": normalized,
                "suffix": Path(normalized).suffix.lower(),
                "source_cell_index": source_cell_index,
            }
        )
    return references


def _notebook_cells(notebook: Mapping[str, Any]) -> list[dict[str, Any]]:
    cells = notebook.get("cells", [])
    if not isinstance(cells, list):
        raise ValueError("notebook format is invalid: cells must be a list")
    return [cell for cell in cells if isinstance(cell, dict)]


def _kernel_name(notebook: Mapping[str, Any]) -> str:
    metadata = notebook.get("metadata", {})
    kernelspec = metadata.get("kernelspec", {}) if isinstance(metadata, dict) else {}
    if isinstance(kernelspec, dict):
        return str(kernelspec.get("name", "") or "")
    return ""


def build_notebook_pipeline_import(
    *,
    notebook: Mapping[str, Any],
    source_notebook: Path | str,
    run_id: str = DEFAULT_RUN_ID,
) -> dict[str, Any]:
    cells = _notebook_cells(notebook)
    pipeline_steps: list[dict[str, Any]] = []
    context_blocks: list[dict[str, Any]] = []
    pending_context_ids: list[str] = []
    all_env_hints: list[str] = []
    all_artifact_references: list[dict[str, Any]] = []
    execution_count_present = 0

    for cell_index, cell in enumerate(cells, start=1):
        cell_type = str(cell.get("cell_type", ""))
        lines = _coerce_source_lines(cell.get("source", []))
        source = "".join(lines)
        if cell_type == "markdown":
            context_id = f"markdown-{cell_index}"
            context_blocks.append(
                {
                    "id": context_id,
                    "source_cell_index": cell_index,
                    "source_lines": lines,
                    "text": source,
                }
            )
            pending_context_ids.append(context_id)
            continue
        if cell_type != "code" or not source.strip():
            continue

        env_hints = extract_env_hints(source)
        artifact_references = extract_artifact_references(source, cell_index)
        all_env_hints.extend(env_hints)
        all_artifact_references.extend(artifact_references)
        if cell.get("execution_count") is not None:
            execution_count_present += 1
        pipeline_steps.append(
            {
                "id": f"cell-{cell_index}",
                "order": len(pipeline_steps) + 1,
                "source_cell_index": cell_index,
                "cell_type": cell_type,
                "execution_count": cell.get("execution_count"),
                "source_lines": lines,
                "source_hash": _hash_source(source),
                "context_ids": list(pending_context_ids),
                "env_hints": env_hints,
                "artifact_references": artifact_references,
                "runnable": True,
                "pipeline_mapping": {
                    "format": "lab_steps.toml-preview",
                    "description_field": "D",
                    "question_field": "Q",
                    "model_field": "M",
                    "code_field": "C",
                },
            }
        )
        pending_context_ids.clear()

    code_cell_count = sum(1 for cell in cells if cell.get("cell_type") == "code")
    markdown_cell_count = sum(1 for cell in cells if cell.get("cell_type") == "markdown")
    env_hints_unique = sorted(dict.fromkeys(all_env_hints))
    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "persistence_format": PERSISTENCE_FORMAT,
        "run_status": "imported",
        "execution_mode": "not_executed_import",
        "created_at": CREATED_AT,
        "updated_at": UPDATED_AT,
        "source": {
            "source_notebook": str(source_notebook),
            "source_format": "ipynb",
            "nbformat": notebook.get("nbformat"),
            "nbformat_minor": notebook.get("nbformat_minor"),
            "kernel_name": _kernel_name(notebook),
        },
        "summary": {
            "cell_count": len(cells),
            "code_cell_count": code_cell_count,
            "markdown_cell_count": markdown_cell_count,
            "pipeline_step_count": len(pipeline_steps),
            "context_block_count": len(context_blocks),
            "env_hint_count": len(env_hints_unique),
            "artifact_reference_count": len(all_artifact_references),
            "execution_count_present_count": execution_count_present,
            "step_ids": [step["id"] for step in pipeline_steps],
            "context_ids": [block["id"] for block in context_blocks],
        },
        "pipeline_steps": pipeline_steps,
        "context_blocks": context_blocks,
        "env_hints": env_hints_unique,
        "artifact_references": all_artifact_references,
        "provenance": {
            "projection_mode": "notebook_to_pipeline_metadata",
            "executes_notebook": False,
            "preserves_markdown_context": True,
            "preserves_code_cells": True,
            "preserves_execution_counts": True,
            "extracts_environment_hints": True,
            "extracts_artifact_references": True,
        },
    }


def write_notebook_pipeline_import(path: Path, notebook_import: Mapping[str, Any]) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(notebook_import, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_notebook_pipeline_import(path: Path) -> dict[str, Any]:
    return _read_json(path)


def persist_notebook_pipeline_import(
    *,
    repo_root: Path,
    output_path: Path,
    notebook_path: Path | None = None,
    run_id: str = DEFAULT_RUN_ID,
) -> NotebookPipelineImportProof:
    repo_root = repo_root.resolve()
    output_path = output_path.expanduser()
    notebook_path = notebook_path or (repo_root / DEFAULT_NOTEBOOK_RELATIVE_PATH)
    if not notebook_path.is_absolute():
        notebook_path = repo_root / notebook_path
    notebook = load_notebook(notebook_path)
    notebook_import = build_notebook_pipeline_import(
        notebook=notebook,
        source_notebook=notebook_path,
        run_id=run_id,
    )
    path = write_notebook_pipeline_import(output_path, notebook_import)
    reloaded = load_notebook_pipeline_import(path)

    issues: list[NotebookPipelineImportIssue] = []
    if notebook_import != reloaded:
        issues.append(
            _issue(
                "persistence.round_trip",
                "notebook import changed after JSON write/read",
            )
        )
    if notebook_import.get("schema") != SCHEMA:
        issues.append(_issue("schema", "notebook import schema is invalid"))
    if notebook_import.get("execution_mode") != "not_executed_import":
        issues.append(_issue("execution_mode", "notebook import must not execute cells"))
    if not notebook_import.get("pipeline_steps"):
        issues.append(_issue("pipeline_steps", "notebook import produced no pipeline steps"))

    return NotebookPipelineImportProof(
        ok=not issues,
        issues=tuple(issues),
        path=str(path),
        notebook_path=str(notebook_path),
        notebook_import=notebook_import,
        reloaded_import=reloaded,
    )
