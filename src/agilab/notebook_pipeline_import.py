# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Notebook-to-pipeline import model for AGILAB evidence reports."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass
import fnmatch
import hashlib
import json
from pathlib import Path
import re
import tomllib
from typing import Any, Mapping

import tomli_w


SCHEMA = "agilab.notebook_pipeline_import.v1"
PREFLIGHT_SCHEMA = "agilab.notebook_import_preflight.v1"
CONTRACT_SCHEMA = "agilab.notebook_import_contract.v1"
PIPELINE_VIEW_SCHEMA = "agilab.notebook_import_pipeline_view.v1"
VIEW_PLAN_SCHEMA = "agilab.notebook_import_view_plan.v1"
VIEW_MANIFEST_SCHEMA = "agilab.notebook_import_views.v1"
VIEW_MANIFEST_NAME = "notebook_import_views.toml"
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

INPUT_PATH_PREFIXES = ("data/", "input/", "inputs/", "raw/")
OUTPUT_PATH_PREFIXES = ("artifact", "artifacts/", "output/", "outputs/", "result", "results/")
READ_MARKERS = (
    "read_csv",
    "read_parquet",
    "read_json",
    "read_table",
    "read_excel",
    ".read_text",
    ".read_bytes",
    "json.load",
    "tomllib.load",
    "open(",
)
WRITE_MARKERS = (
    ".to_csv",
    ".to_parquet",
    ".to_json",
    ".to_excel",
    ".write_text",
    ".write_bytes",
    "json.dump",
    "tomli_w.dump",
    "savefig",
    ".save(",
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
    def pipeline_stage_count(self) -> int:
        return _summary_int(self.notebook_import, "pipeline_stage_count")

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
            "pipeline_stage_count": self.pipeline_stage_count,
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


def _risk(
    level: str,
    rule: str,
    location: str,
    message: str,
    *,
    evidence: str = "",
) -> dict[str, str]:
    result = {
        "level": level,
        "rule": rule,
        "location": location,
        "message": message,
    }
    if evidence:
        result["evidence"] = evidence
    return result


def _risk_counts(risks: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    counts = {"error": 0, "warning": 0, "info": 0}
    for risk in risks:
        level = str(risk.get("level", "") or "info")
        counts[level] = counts.get(level, 0) + 1
    return counts


def _is_absolute_path_text(value: str) -> bool:
    if not value:
        return False
    if re.match(r"^[A-Za-z]:[\\/]", value):
        return True
    try:
        return Path(value).is_absolute()
    except (OSError, RuntimeError, TypeError, ValueError):
        return value.startswith("/")


def _path_role_from_prefix(path: str) -> str:
    normalized = path.strip().replace("\\", "/").lstrip("./").lower()
    if normalized.startswith(INPUT_PATH_PREFIXES):
        return "input"
    if normalized.startswith(OUTPUT_PATH_PREFIXES):
        return "output"
    return "unknown"


def _line_role_for_path(line: str, path: str) -> str:
    if path not in line:
        return "unknown"
    lowered = line.lower()
    read_seen = any(marker in lowered for marker in READ_MARKERS)
    write_seen = any(marker in lowered for marker in WRITE_MARKERS)
    if read_seen and write_seen:
        return "input_output"
    if write_seen:
        return "output"
    if read_seen:
        return "input"
    return "unknown"


def _combine_artifact_roles(current: str, candidate: str) -> str:
    if current == candidate or candidate == "unknown":
        return current
    if current == "unknown":
        return candidate
    roles = {current, candidate}
    if "input_output" in roles or roles == {"input", "output"}:
        return "input_output"
    return current


def _infer_artifact_role(path: str, source: str) -> str:
    role = _path_role_from_prefix(path)
    for line in source.splitlines():
        role = _combine_artifact_roles(role, _line_role_for_path(line, path))
    return role


def _pipeline_stage_sources(notebook_import: Mapping[str, Any]) -> list[tuple[str, int, str]]:
    stages = notebook_import.get("pipeline_stages", [])
    if not isinstance(stages, list):
        return []
    sources: list[tuple[str, int, str]] = []
    for stage in stages:
        if not isinstance(stage, dict):
            continue
        stage_id = str(stage.get("id", "") or "")
        source_cell_index = int(stage.get("source_cell_index", 0) or 0)
        sources.append((stage_id, source_cell_index, _source_from_stage(stage)))
    return sources


def _safe_node_id(prefix: str, value: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip()).strip("_").lower()
    if not stem:
        stem = "node"
    digest = _hash_source(value)[:8]
    return f"{prefix}_{stem}_{digest}"


def _detect_line_risks(stage_id: str, source: str) -> list[dict[str, str]]:
    risks: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for line_number, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        lowered = stripped.lower()
        location = f"{stage_id}:line-{line_number}" if stage_id else f"line-{line_number}"
        candidates: list[dict[str, str]] = []
        if re.search(r"(^[!%]\s*(pip|conda)\s+install\b|\bpip\s+install\b)", lowered):
            candidates.append(
                _risk(
                    "warning",
                    "dependency_install",
                    location,
                    "Notebook cell installs dependencies at runtime; move them to project metadata.",
                    evidence=stripped,
                )
            )
        if (
            stripped.startswith("!")
            or stripped.startswith("%%bash")
            or stripped.startswith("%%sh")
            or "subprocess." in lowered
            or "os.system" in lowered
        ):
            candidates.append(
                _risk(
                    "warning",
                    "shell_execution",
                    location,
                    "Notebook cell uses shell or subprocess execution; review before pipeline import.",
                    evidence=stripped,
                )
            )
        if (
            "http://" in lowered
            or "https://" in lowered
            or "requests." in lowered
            or "urllib." in lowered
        ):
            candidates.append(
                _risk(
                    "warning",
                    "network_access",
                    location,
                    "Notebook cell references network access; keep credentials and remote availability explicit.",
                    evidence=stripped,
                )
            )
        if "ipywidgets" in lowered or "interact(" in lowered or ".observe(" in lowered:
            candidates.append(
                _risk(
                    "warning",
                    "interactive_widget",
                    location,
                    "Notebook cell depends on interactive widget state; replace with explicit parameters.",
                    evidence=stripped,
                )
            )
        if "get_ipython(" in lowered or "%store" in lowered or "globals()" in lowered:
            candidates.append(
                _risk(
                    "warning",
                    "hidden_notebook_state",
                    location,
                    "Notebook cell reaches notebook runtime state; make required inputs explicit.",
                    evidence=stripped,
                )
            )
        if re.search(r"['\"](/Users/|/home/|/tmp/|[A-Za-z]:[\\/])", stripped):
            candidates.append(
                _risk(
                    "warning",
                    "absolute_path",
                    location,
                    "Notebook cell contains an absolute path; use project or artifact-relative paths.",
                    evidence=stripped,
                )
            )

        for candidate in candidates:
            key = (candidate["rule"], candidate["location"])
            if key not in seen:
                seen.add(key)
                risks.append(candidate)
    return risks


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


def _agilab_export_payload(notebook: Mapping[str, Any]) -> dict[str, Any]:
    metadata = notebook.get("metadata", {})
    agilab_payload = metadata.get("agilab", {}) if isinstance(metadata, dict) else {}
    return agilab_payload if isinstance(agilab_payload, dict) else {}


def _agilab_supervisor_stages(notebook: Mapping[str, Any]) -> list[dict[str, Any]]:
    payload = _agilab_export_payload(notebook)
    stages = payload.get("stages", [])
    if not isinstance(stages, list):
        return []
    return [stage for stage in stages if isinstance(stage, dict)]


def _supervisor_context_text(stage: Mapping[str, Any]) -> str:
    parts = [
        str(stage.get("description", "") or "").strip(),
        str(stage.get("question", "") or "").strip(),
    ]
    return "\n\n".join(part for part in parts if part)


def _build_from_supervisor_metadata(
    *,
    notebook: Mapping[str, Any],
    source_notebook: Path | str,
    run_id: str,
    supervisor_stages: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = _agilab_export_payload(notebook)
    cells = _notebook_cells(notebook)
    pipeline_stages: list[dict[str, Any]] = []
    context_blocks: list[dict[str, Any]] = []
    all_env_hints: list[str] = []
    all_artifact_references: list[dict[str, Any]] = []

    for stage_index, stage in enumerate(supervisor_stages, start=1):
        source = str(stage.get("code", "") or "")
        if not source.strip():
            continue
        context_id = f"agilab-stage-{stage_index}-context"
        context_text = _supervisor_context_text(stage)
        context_blocks.append(
            {
                "id": context_id,
                "source_cell_index": 0,
                "source_lines": context_text.splitlines(keepends=True),
                "text": context_text,
            }
        )
        env_hints = extract_env_hints(source)
        artifact_references = extract_artifact_references(source, stage_index)
        all_env_hints.extend(env_hints)
        all_artifact_references.extend(artifact_references)
        pipeline_stages.append(
            {
                "id": f"supervisor-stage-{stage_index}",
                "order": len(pipeline_stages) + 1,
                "source_cell_index": stage_index,
                "cell_type": "code",
                "execution_count": None,
                "source_lines": source.splitlines(keepends=True),
                "source_hash": _hash_source(source),
                "context_ids": [context_id],
                "env_hints": env_hints,
                "artifact_references": artifact_references,
                "runnable": True,
                "description": str(stage.get("description", "") or ""),
                "question": str(stage.get("question", "") or ""),
                "model": str(stage.get("model", "") or ""),
                "runtime": str(stage.get("runtime", "") or ""),
                "env": str(stage.get("env", "") or ""),
                "pipeline_mapping": {
                    "format": "lab_stages.toml-preview",
                    "description_field": "D",
                    "question_field": "Q",
                    "model_field": "M",
                    "code_field": "C",
                    "runtime_field": "R",
                    "environment_field": "E",
                },
            }
        )

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
            "import_mode": "agilab_supervisor_metadata",
            "nbformat": notebook.get("nbformat"),
            "nbformat_minor": notebook.get("nbformat_minor"),
            "kernel_name": _kernel_name(notebook),
            "export_mode": str(payload.get("export_mode", "") or ""),
            "project_name": str(payload.get("project_name", "") or ""),
            "stages_file": str(payload.get("stages_file", "") or ""),
        },
        "summary": {
            "cell_count": len(cells),
            "code_cell_count": code_cell_count,
            "markdown_cell_count": markdown_cell_count,
            "supervisor_stage_count": len(supervisor_stages),
            "pipeline_stage_count": len(pipeline_stages),
            "context_block_count": len(context_blocks),
            "env_hint_count": len(env_hints_unique),
            "artifact_reference_count": len(all_artifact_references),
            "execution_count_present_count": 0,
            "stage_ids": [stage["id"] for stage in pipeline_stages],
            "context_ids": [block["id"] for block in context_blocks],
        },
        "pipeline_stages": pipeline_stages,
        "context_blocks": context_blocks,
        "env_hints": env_hints_unique,
        "artifact_references": all_artifact_references,
        "provenance": {
            "projection_mode": "agilab_supervisor_notebook_metadata",
            "executes_notebook": False,
            "preserves_markdown_context": True,
            "preserves_code_cells": True,
            "preserves_execution_counts": True,
            "extracts_environment_hints": True,
            "extracts_artifact_references": True,
            "preserves_lab_stages_fields": True,
        },
    }


def build_notebook_pipeline_import(
    *,
    notebook: Mapping[str, Any],
    source_notebook: Path | str,
    run_id: str = DEFAULT_RUN_ID,
) -> dict[str, Any]:
    supervisor_stages = _agilab_supervisor_stages(notebook)
    if supervisor_stages:
        return _build_from_supervisor_metadata(
            notebook=notebook,
            source_notebook=source_notebook,
            run_id=run_id,
            supervisor_stages=supervisor_stages,
        )

    cells = _notebook_cells(notebook)
    pipeline_stages: list[dict[str, Any]] = []
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
        pipeline_stages.append(
            {
                "id": f"cell-{cell_index}",
                "order": len(pipeline_stages) + 1,
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
                    "format": "lab_stages.toml-preview",
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
            "pipeline_stage_count": len(pipeline_stages),
            "context_block_count": len(context_blocks),
            "env_hint_count": len(env_hints_unique),
            "artifact_reference_count": len(all_artifact_references),
            "execution_count_present_count": execution_count_present,
            "stage_ids": [stage["id"] for stage in pipeline_stages],
            "context_ids": [block["id"] for block in context_blocks],
        },
        "pipeline_stages": pipeline_stages,
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


def _context_lookup(notebook_import: Mapping[str, Any]) -> dict[str, str]:
    blocks = notebook_import.get("context_blocks", [])
    result: dict[str, str] = {}
    if not isinstance(blocks, list):
        return result
    for block in blocks:
        if not isinstance(block, dict):
            continue
        context_id = str(block.get("id", ""))
        if context_id:
            result[context_id] = str(block.get("text", "") or "")
    return result


def _context_summary(context_ids: list[str], contexts: Mapping[str, str]) -> str:
    for context_id in context_ids:
        text = contexts.get(context_id, "")
        for line in text.splitlines():
            summary = line.strip().lstrip("#").strip()
            if summary:
                return summary
    return ""


def _source_from_stage(stage: Mapping[str, Any]) -> str:
    return "".join(_coerce_source_lines(stage.get("source_lines", [])))


def _default_imported_stage_question(stage: Mapping[str, Any]) -> str:
    stage_id = str(stage.get("id", "") or "").strip()
    if stage_id:
        return f"Imported {stage_id} from notebook"
    return "Imported notebook cell"


def _artifact_paths(stage: Mapping[str, Any]) -> list[str]:
    references = stage.get("artifact_references", [])
    if not isinstance(references, list):
        return []
    paths: list[str] = []
    for reference in references:
        if not isinstance(reference, dict):
            continue
        path = str(reference.get("path", "") or "")
        if path:
            paths.append(path)
    return paths


def _stage_env_hints(stage: Mapping[str, Any]) -> list[str]:
    hints = stage.get("env_hints", [])
    if isinstance(hints, list):
        return [str(hint) for hint in hints]
    return []


def build_lab_stages_preview(
    notebook_import: Mapping[str, Any],
    *,
    module_name: str = "notebook_import_project",
) -> dict[str, list[dict[str, Any]]]:
    """Project imported notebook metadata into AGILAB lab_stages TOML entries."""
    module_name = str(module_name or "lab_stages")
    contexts = _context_lookup(notebook_import)
    source = notebook_import.get("source", {})
    source_notebook = ""
    if isinstance(source, dict):
        source_notebook = str(source.get("source_notebook", "") or "")
    execution_mode = str(notebook_import.get("execution_mode", "not_executed_import"))
    stages = notebook_import.get("pipeline_stages", [])
    if not isinstance(stages, list):
        return {module_name: []}

    entries: list[dict[str, Any]] = []
    for stage in stages:
        if not isinstance(stage, dict):
            continue
        code = _source_from_stage(stage)
        if not code.strip():
            continue
        context_ids = [
            str(context_id)
            for context_id in stage.get("context_ids", [])
            if str(context_id)
        ]
        entry: dict[str, Any] = {
            "D": str(stage.get("description", "") or "")
            or _context_summary(context_ids, contexts),
            "Q": str(stage.get("question", "") or "")
            or _default_imported_stage_question(stage),
            "C": code,
            "M": str(stage.get("model", "") or ""),
            "NB_CELL_ID": str(stage.get("id", "")),
            "NB_CELL_INDEX": int(stage.get("source_cell_index", 0) or 0),
            "NB_CONTEXT_IDS": context_ids,
            "NB_ENV_HINTS": _stage_env_hints(stage),
            "NB_ARTIFACT_REFERENCES": _artifact_paths(stage),
            "NB_EXECUTION_MODE": execution_mode,
            "NB_SOURCE_NOTEBOOK": source_notebook,
        }
        execution_count = stage.get("execution_count")
        if execution_count is not None:
            entry["NB_EXECUTION_COUNT"] = int(execution_count)
        runtime = str(stage.get("runtime", "") or "")
        if runtime:
            entry["R"] = runtime
        env = str(stage.get("env", "") or "")
        if env:
            entry["E"] = env
        entries.append(entry)
    return {module_name: entries}


def build_notebook_artifact_contract(notebook_import: Mapping[str, Any]) -> dict[str, Any]:
    """Build an app-neutral input/output contract from imported notebook metadata."""
    stage_sources = {
        source_cell_index: source
        for _stage_id, source_cell_index, source in _pipeline_stage_sources(notebook_import)
    }
    references = notebook_import.get("artifact_references", [])
    iterable_references = references if isinstance(references, list) else []
    by_path: dict[str, dict[str, Any]] = {}

    for reference in iterable_references:
        if not isinstance(reference, dict):
            continue
        path = str(reference.get("path", "") or "")
        if not path:
            continue
        source_cell_index = int(reference.get("source_cell_index", 0) or 0)
        source = stage_sources.get(source_cell_index, "")
        inferred_role = _infer_artifact_role(path, source)
        entry = by_path.setdefault(
            path,
            {
                "path": path,
                "suffix": str(reference.get("suffix", "") or Path(path).suffix.lower()),
                "role": "unknown",
                "source_cell_indices": [],
            },
        )
        entry["role"] = _combine_artifact_roles(str(entry.get("role", "unknown")), inferred_role)
        if source_cell_index and source_cell_index not in entry["source_cell_indices"]:
            entry["source_cell_indices"].append(source_cell_index)

    ordered = sorted(by_path.values(), key=lambda item: str(item.get("path", "")))
    inputs = [str(item["path"]) for item in ordered if item.get("role") in {"input", "input_output"}]
    outputs = [str(item["path"]) for item in ordered if item.get("role") in {"output", "input_output"}]
    unknown = [str(item["path"]) for item in ordered if item.get("role") == "unknown"]
    return {
        "schema": "agilab.notebook_artifact_contract.v1",
        "inputs": inputs,
        "outputs": outputs,
        "unknown": unknown,
        "references": ordered,
    }


def build_notebook_import_preflight(notebook_import: Mapping[str, Any]) -> dict[str, Any]:
    """Return a generic, non-executing readiness report for a notebook import."""
    summary = notebook_import.get("summary", {})
    summary_map = summary if isinstance(summary, dict) else {}
    artifact_contract = build_notebook_artifact_contract(notebook_import)
    risks: list[dict[str, str]] = []

    pipeline_stage_count = int(summary_map.get("pipeline_stage_count", 0) or 0)
    markdown_cell_count = int(summary_map.get("markdown_cell_count", 0) or 0)
    execution_count_present = int(summary_map.get("execution_count_present_count", 0) or 0)

    if pipeline_stage_count <= 0:
        risks.append(
            _risk(
                "error",
                "no_code_cells",
                "notebook",
                "Notebook import produced no runnable code cells.",
            )
        )
    if markdown_cell_count <= 0 and pipeline_stage_count > 0:
        risks.append(
            _risk(
                "warning",
                "missing_markdown_context",
                "notebook",
                "Notebook has code cells but no markdown context for stage names.",
            )
        )
    if execution_count_present > 0:
        risks.append(
            _risk(
                "info",
                "execution_history_present",
                "notebook",
                "Notebook includes execution counts; import remains non-executing.",
            )
        )

    for stage_id, _source_cell_index, source in _pipeline_stage_sources(notebook_import):
        risks.extend(_detect_line_risks(stage_id, source))

    for item in artifact_contract.get("references", []):
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", "") or "")
        if _is_absolute_path_text(path):
            risks.append(
                _risk(
                    "warning",
                    "absolute_artifact_path",
                    "artifact_contract",
                    "Artifact reference is absolute; prefer project-relative inputs and outputs.",
                    evidence=path,
                )
            )

    counts = _risk_counts(risks)
    if counts.get("error", 0):
        risk_status = "blocked"
    elif counts.get("warning", 0):
        risk_status = "review"
    else:
        risk_status = "ready"

    return {
        "schema": PREFLIGHT_SCHEMA,
        "status": risk_status,
        "safe_to_import": counts.get("error", 0) == 0 and pipeline_stage_count > 0,
        "cleanup_required": counts.get("warning", 0) > 0,
        "risk_counts": counts,
        "summary": {
            "cell_count": int(summary_map.get("cell_count", 0) or 0),
            "code_cell_count": int(summary_map.get("code_cell_count", 0) or 0),
            "markdown_cell_count": markdown_cell_count,
            "pipeline_stage_count": pipeline_stage_count,
            "env_hint_count": int(summary_map.get("env_hint_count", 0) or 0),
            "artifact_reference_count": int(summary_map.get("artifact_reference_count", 0) or 0),
            "input_count": len(artifact_contract.get("inputs", [])),
            "output_count": len(artifact_contract.get("outputs", [])),
            "unknown_artifact_count": len(artifact_contract.get("unknown", [])),
        },
        "env_hints": list(notebook_import.get("env_hints", []) or []),
        "artifact_contract": artifact_contract,
        "risks": risks,
    }


def build_notebook_import_contract(
    notebook_import: Mapping[str, Any],
    *,
    preflight: Mapping[str, Any] | None = None,
    module_name: str = "notebook_import_project",
) -> dict[str, Any]:
    """Return a generic sidecar contract for a notebook-to-pipeline import."""
    preflight_state = dict(preflight or build_notebook_import_preflight(notebook_import))
    risks = preflight_state.get("risks", [])
    iterable_risks = risks if isinstance(risks, list) else []
    source = notebook_import.get("source", {})
    summary = notebook_import.get("summary", {})
    stages = notebook_import.get("pipeline_stages", [])
    iterable_stages = stages if isinstance(stages, list) else []

    contract_stages: list[dict[str, Any]] = []
    for stage in iterable_stages:
        if not isinstance(stage, dict):
            continue
        contract_stages.append(
            {
                "id": str(stage.get("id", "") or ""),
                "order": int(stage.get("order", 0) or 0),
                "source_cell_index": int(stage.get("source_cell_index", 0) or 0),
                "description": str(stage.get("description", "") or ""),
                "question": str(stage.get("question", "") or ""),
                "context_ids": list(stage.get("context_ids", []) or []),
                "env_hints": list(stage.get("env_hints", []) or []),
                "artifact_references": _artifact_paths(stage),
                "execution_count": stage.get("execution_count"),
            }
        )

    return {
        "schema": CONTRACT_SCHEMA,
        "module_name": str(module_name or "notebook_import_project"),
        "source": source if isinstance(source, dict) else {},
        "summary": summary if isinstance(summary, dict) else {},
        "preflight": {
            "schema": preflight_state.get("schema"),
            "status": preflight_state.get("status"),
            "safe_to_import": preflight_state.get("safe_to_import"),
            "cleanup_required": preflight_state.get("cleanup_required"),
            "risk_counts": preflight_state.get("risk_counts", {}),
        },
        "environment": {
            "imports": list(notebook_import.get("env_hints", []) or []),
        },
        "artifact_contract": preflight_state.get("artifact_contract", {}),
        "warnings": [
            risk
            for risk in iterable_risks
            if isinstance(risk, dict) and risk.get("level") == "warning"
        ],
        "errors": [
            risk
            for risk in iterable_risks
            if isinstance(risk, dict) and risk.get("level") == "error"
        ],
        "stages": contract_stages,
    }


def build_notebook_import_pipeline_view(
    notebook_import: Mapping[str, Any],
    *,
    preflight: Mapping[str, Any] | None = None,
    module_name: str = "notebook_import_project",
) -> dict[str, Any]:
    """Build an app-neutral conceptual pipeline view for a notebook import."""
    preflight_state = dict(preflight or build_notebook_import_preflight(notebook_import))
    artifact_contract = preflight_state.get("artifact_contract", {})
    references = artifact_contract.get("references", []) if isinstance(artifact_contract, dict) else []
    reference_roles = {
        str(reference.get("path", "") or ""): str(reference.get("role", "unknown") or "unknown")
        for reference in references
        if isinstance(reference, dict) and str(reference.get("path", "") or "")
    }
    source = notebook_import.get("source", {})
    source_notebook = str(source.get("source_notebook", "") or "") if isinstance(source, dict) else ""

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    node_ids: set[str] = set()
    edge_keys: set[tuple[str, str, str, str]] = set()

    def add_node(node: dict[str, Any]) -> None:
        node_id = str(node.get("id", "") or "")
        if not node_id or node_id in node_ids:
            return
        node_ids.add(node_id)
        nodes.append(node)

    def add_edge(source_id: str, target_id: str, kind: str, *, artifact: str = "") -> None:
        if not source_id or not target_id:
            return
        key = (source_id, target_id, kind, artifact)
        if key in edge_keys:
            return
        edge_keys.add(key)
        edge: dict[str, Any] = {"from": source_id, "to": target_id, "kind": kind}
        if artifact:
            edge["artifact"] = artifact
        edges.append(edge)

    artifact_node_ids: dict[str, str] = {}
    for reference in references if isinstance(references, list) else []:
        if not isinstance(reference, dict):
            continue
        path = str(reference.get("path", "") or "")
        if not path:
            continue
        role = str(reference.get("role", "unknown") or "unknown")
        node_id = _safe_node_id("artifact", path)
        artifact_node_ids[path] = node_id
        add_node(
            {
                "id": node_id,
                "label": path,
                "kind": "artifact",
                "role": role,
                "path": path,
                "suffix": str(reference.get("suffix", "") or Path(path).suffix.lower()),
                "source_cell_indices": list(reference.get("source_cell_indices", []) or []),
            }
        )

    context_node_ids: dict[str, str] = {}
    context_texts: dict[str, str] = {}
    context_blocks = notebook_import.get("context_blocks", [])
    for block in context_blocks if isinstance(context_blocks, list) else []:
        if not isinstance(block, dict):
            continue
        context_id = str(block.get("id", "") or "")
        if not context_id:
            continue
        node_id = _safe_node_id("context", context_id)
        context_node_ids[context_id] = node_id
        text = str(block.get("text", "") or "")
        context_texts[context_id] = text
        label = _context_summary([context_id], {context_id: text}) or context_id
        add_node(
            {
                "id": node_id,
                "label": label,
                "kind": "markdown_context",
                "role": "context",
                "source_cell_index": int(block.get("source_cell_index", 0) or 0),
                "context_id": context_id,
            }
        )

    stage_node_ids: list[str] = []
    stages = notebook_import.get("pipeline_stages", [])
    for stage in stages if isinstance(stages, list) else []:
        if not isinstance(stage, dict):
            continue
        stage_id = str(stage.get("id", "") or "")
        if not stage_id:
            continue
        node_id = _safe_node_id("cell", stage_id)
        stage_node_ids.append(node_id)
        context_ids = [str(context_id) for context_id in stage.get("context_ids", []) if str(context_id)]
        label = (
            str(stage.get("description", "") or "")
            or str(stage.get("question", "") or "")
            or _context_summary(context_ids, context_texts)
            or f"Notebook cell {stage_id}"
        )
        artifact_paths = _artifact_paths(stage)
        add_node(
            {
                "id": node_id,
                "label": label,
                "kind": "notebook_code_cell",
                "role": "pipeline_stage",
                "source_cell_index": int(stage.get("source_cell_index", 0) or 0),
                "source_cell_id": stage_id,
                "context_ids": context_ids,
                "env_hints": _stage_env_hints(stage),
                "artifact_references": artifact_paths,
            }
        )
        for context_id in context_ids:
            context_node_id = context_node_ids.get(context_id)
            if context_node_id:
                add_edge(context_node_id, node_id, "context_for")

        for path in artifact_paths:
            artifact_node_id = artifact_node_ids.get(path)
            if not artifact_node_id:
                artifact_node_id = _safe_node_id("artifact", path)
                artifact_node_ids[path] = artifact_node_id
                add_node(
                    {
                        "id": artifact_node_id,
                        "label": path,
                        "kind": "artifact",
                        "role": reference_roles.get(path, "unknown"),
                        "path": path,
                        "suffix": Path(path).suffix.lower(),
                        "source_cell_indices": [int(stage.get("source_cell_index", 0) or 0)],
                    }
                )
            role = reference_roles.get(path, "unknown")
            if role in {"input", "input_output", "unknown"}:
                add_edge(artifact_node_id, node_id, "artifact_input", artifact=path)
            if role in {"output", "input_output", "unknown"}:
                add_edge(node_id, artifact_node_id, "artifact_output", artifact=path)

    analysis_consumes: list[str] = []
    if isinstance(artifact_contract, dict):
        analysis_consumes = [
            str(path)
            for path in [
                *list(artifact_contract.get("outputs", []) or []),
                *list(artifact_contract.get("unknown", []) or []),
            ]
        ]

    analysis_node_id = "analysis_consumer"
    add_node(
        {
            "id": analysis_node_id,
            "label": "Generic ANALYSIS artifact consumer",
            "kind": "analysis_consumer",
            "role": "analysis_placeholder",
            "consumes": analysis_consumes,
            "note": "Placeholder for a generic artifact viewer; no app-specific analysis is generated.",
        }
    )
    for path in analysis_consumes:
        artifact_node_id = artifact_node_ids.get(path)
        if artifact_node_id:
            add_edge(artifact_node_id, analysis_node_id, "analysis_consumes", artifact=path)
    if not edges and stage_node_ids:
        add_edge(stage_node_ids[-1], analysis_node_id, "analysis_candidate")

    return {
        "schema": PIPELINE_VIEW_SCHEMA,
        "direction": "LR",
        "module_name": str(module_name or "notebook_import_project"),
        "source_notebook": source_notebook,
        "graph": {
            "label": "Notebook import pipeline view",
        },
        "node": {
            "shape": "box",
        },
        "edge": {
            "arrowsize": 0.8,
        },
        "summary": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "context_node_count": sum(1 for node in nodes if node.get("kind") == "markdown_context"),
            "code_cell_node_count": sum(1 for node in nodes if node.get("kind") == "notebook_code_cell"),
            "artifact_node_count": sum(1 for node in nodes if node.get("kind") == "artifact"),
        },
        "artifact_contract": artifact_contract,
        "nodes": nodes,
        "edges": edges,
    }


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_items: Iterable[Any] = [value]
    elif isinstance(value, Mapping) or value is None:
        raw_items = []
    elif isinstance(value, Iterable):
        raw_items = value
    else:
        raw_items = [value]

    items: list[str] = []
    seen: set[str] = set()
    for raw_item in raw_items:
        item = str(raw_item or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        items.append(item)
    return items


def _safe_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): item
        for key, item in value.items()
        if str(key or "").strip()
    }


def _normalize_view_manifest_record(raw_view: Mapping[str, Any], index: int) -> dict[str, Any]:
    module = str(raw_view.get("module") or raw_view.get("page") or raw_view.get("id") or "").strip()
    view_id = str(raw_view.get("id") or module or f"view_{index + 1}").strip()
    try:
        priority = int(raw_view.get("priority", index) or index)
    except (TypeError, ValueError):
        priority = index

    required = _string_list(raw_view.get("required_artifacts") or raw_view.get("required"))
    required_any = _string_list(
        raw_view.get("required_artifacts_any")
        or raw_view.get("required_any_artifacts")
        or raw_view.get("required_any")
    )
    optional = _string_list(raw_view.get("optional_artifacts") or raw_view.get("optional"))
    if not required and not required_any:
        required_any = _string_list(raw_view.get("artifacts"))

    return {
        "id": view_id,
        "module": module,
        "label": str(raw_view.get("label") or module or view_id),
        "description": str(raw_view.get("description") or ""),
        "priority": priority,
        "required_artifacts": required,
        "required_artifacts_any": required_any,
        "optional_artifacts": optional,
        "settings_hints": _safe_mapping(raw_view.get("settings_hints")),
        "query_params": _safe_mapping(raw_view.get("query_params")),
        "launch_note": str(raw_view.get("launch_note") or ""),
    }


def _normalize_import_view_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    import_cfg = payload.get("notebook_import_views", {})
    cfg = import_cfg if isinstance(import_cfg, Mapping) else payload
    raw_views = cfg.get("views", payload.get("views", [])) if isinstance(cfg, Mapping) else []
    source_schema = str(payload.get("schema") or VIEW_MANIFEST_SCHEMA)

    if not raw_views and isinstance(payload.get("notebook_export"), Mapping):
        source_schema = "agilab.notebook_export.v1"
        export_cfg = payload["notebook_export"]
        raw_views = export_cfg.get("related_pages", [])
        normalized_export_views: list[dict[str, Any]] = []
        for index, raw_page in enumerate(raw_views if isinstance(raw_views, list) else []):
            if not isinstance(raw_page, Mapping):
                continue
            normalized_export_views.append(
                _normalize_view_manifest_record(
                    {
                        "id": raw_page.get("module", ""),
                        "module": raw_page.get("module", ""),
                        "label": raw_page.get("label", ""),
                        "description": raw_page.get("description", ""),
                        "required_artifacts_any": raw_page.get("artifacts", []),
                        "launch_note": raw_page.get("launch_note", ""),
                    },
                    index,
                )
            )
        return {
            "schema": VIEW_MANIFEST_SCHEMA,
            "source_schema": source_schema,
            "app": str(payload.get("app") or ""),
            "description": "",
            "views": sorted(normalized_export_views, key=lambda view: (view["priority"], view["id"])),
        }

    normalized_views = [
        _normalize_view_manifest_record(raw_view, index)
        for index, raw_view in enumerate(raw_views if isinstance(raw_views, list) else [])
        if isinstance(raw_view, Mapping)
    ]
    return {
        "schema": VIEW_MANIFEST_SCHEMA,
        "source_schema": source_schema,
        "app": str(cfg.get("app") or payload.get("app") or "") if isinstance(cfg, Mapping) else "",
        "description": str(cfg.get("description") or payload.get("description") or "") if isinstance(cfg, Mapping) else "",
        "views": sorted(normalized_views, key=lambda view: (view["priority"], view["id"])),
    }


def load_notebook_import_view_manifest(path: Path) -> dict[str, Any]:
    """Load an app-owned notebook import view manifest."""
    manifest_path = Path(path).expanduser()
    with open(manifest_path, "rb") as stream:
        payload = tomllib.load(stream)
    return _normalize_import_view_manifest(payload)


def discover_notebook_import_view_manifest(module_dir: str | Path | None) -> Path | None:
    """Return the first app-owned notebook import view manifest for a module."""
    if not module_dir:
        return None
    try:
        root = Path(module_dir).expanduser()
    except (OSError, TypeError, ValueError):
        return None
    candidates = (
        root / VIEW_MANIFEST_NAME,
        root / "src" / VIEW_MANIFEST_NAME,
        root / "notebook_export.toml",
        root / "src" / "notebook_export.toml",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _artifact_entries_for_view_plan(artifact_contract: Mapping[str, Any]) -> tuple[list[str], dict[str, str]]:
    references = artifact_contract.get("references", [])
    paths: list[str] = []
    roles: dict[str, str] = {}
    if isinstance(references, list):
        for reference in references:
            if not isinstance(reference, Mapping):
                continue
            path = str(reference.get("path", "") or "").strip()
            if not path:
                continue
            paths.append(path)
            roles[path] = str(reference.get("role", "unknown") or "unknown")
    for role_key, role_name in (
        ("inputs", "input"),
        ("outputs", "output"),
        ("unknown", "unknown"),
    ):
        for path in _string_list(artifact_contract.get(role_key, [])):
            paths.append(path)
            roles.setdefault(path, role_name)
    unique_paths = sorted(dict.fromkeys(paths))
    return unique_paths, roles


def _normalize_artifact_match_value(value: str) -> str:
    return str(value or "").strip().replace("\\", "/").lstrip("./")


def _match_artifact_patterns(patterns: list[str], artifact_paths: list[str]) -> dict[str, list[str]]:
    matches: dict[str, list[str]] = {}
    normalized_paths = {
        path: _normalize_artifact_match_value(path)
        for path in artifact_paths
    }
    for pattern in patterns:
        normalized_pattern = _normalize_artifact_match_value(pattern)
        matches[pattern] = [
            path
            for path, normalized_path in normalized_paths.items()
            if fnmatch.fnmatchcase(normalized_path, normalized_pattern)
        ]
    return matches


def _flatten_match_paths(match_map: Mapping[str, list[str]]) -> list[str]:
    paths: list[str] = []
    for matched_paths in match_map.values():
        paths.extend(matched_paths)
    return sorted(dict.fromkeys(paths))


def _build_single_view_plan(view: Mapping[str, Any], artifact_paths: list[str]) -> dict[str, Any]:
    required_patterns = _string_list(view.get("required_artifacts", []))
    required_any_patterns = _string_list(view.get("required_artifacts_any", []))
    optional_patterns = _string_list(view.get("optional_artifacts", []))

    required_matches = _match_artifact_patterns(required_patterns, artifact_paths)
    required_any_matches = _match_artifact_patterns(required_any_patterns, artifact_paths)
    optional_matches = _match_artifact_patterns(optional_patterns, artifact_paths)

    missing_required = [
        pattern for pattern, matched_paths in required_matches.items() if not matched_paths
    ]
    required_any_artifacts = _flatten_match_paths(required_any_matches)
    missing_required_any = required_any_patterns if required_any_patterns and not required_any_artifacts else []
    matched_artifacts = sorted(
        dict.fromkeys(
            [
                *_flatten_match_paths(required_matches),
                *required_any_artifacts,
                *_flatten_match_paths(optional_matches),
            ]
        )
    )
    status = "ready" if not missing_required and not missing_required_any else "incomplete"
    return {
        "id": str(view.get("id", "") or ""),
        "module": str(view.get("module", "") or ""),
        "label": str(view.get("label", "") or ""),
        "description": str(view.get("description", "") or ""),
        "priority": int(view.get("priority", 0) or 0),
        "status": status,
        "matched_artifacts": matched_artifacts,
        "matched_required": required_matches,
        "matched_required_any": required_any_matches,
        "matched_optional": optional_matches,
        "missing_required": missing_required,
        "missing_required_any": missing_required_any,
        "settings_hints": _safe_mapping(view.get("settings_hints")),
        "query_params": _safe_mapping(view.get("query_params")),
        "launch_note": str(view.get("launch_note") or ""),
    }


def build_notebook_import_view_plan(
    notebook_import: Mapping[str, Any],
    *,
    preflight: Mapping[str, Any] | None = None,
    module_name: str = "notebook_import_project",
    manifest: Mapping[str, Any] | None = None,
    manifest_path: str | Path | None = None,
    warnings: Iterable[str] = (),
) -> dict[str, Any]:
    """Match notebook artifacts against app-owned view declarations.

    The matcher is intentionally app-manifest-only: it does not infer views from
    cell text, imports, markdown, or dataframe variable names.
    """
    preflight_state = dict(preflight or build_notebook_import_preflight(notebook_import))
    artifact_contract = preflight_state.get("artifact_contract", {})
    artifact_contract = artifact_contract if isinstance(artifact_contract, Mapping) else {}
    artifact_paths, artifact_roles = _artifact_entries_for_view_plan(artifact_contract)
    source = notebook_import.get("source", {})
    source_notebook = str(source.get("source_notebook", "") or "") if isinstance(source, Mapping) else ""

    normalized_manifest = _normalize_import_view_manifest(manifest) if isinstance(manifest, Mapping) else None
    view_records = (
        [
            _build_single_view_plan(view, artifact_paths)
            for view in normalized_manifest.get("views", [])
            if isinstance(view, Mapping)
        ]
        if normalized_manifest
        else []
    )
    ready_views = [view for view in view_records if view.get("status") == "ready"]
    ready_artifacts = {
        artifact
        for view in ready_views
        for artifact in view.get("matched_artifacts", [])
        if isinstance(artifact, str)
    }
    plan_warnings = list(warnings)
    if normalized_manifest is None:
        plan_warnings.append(
            "No app-owned notebook import view manifest was provided; no UI view was inferred."
        )
    elif not view_records:
        plan_warnings.append("Notebook import view manifest declares no views.")
    if not artifact_paths:
        plan_warnings.append("Notebook import artifact contract does not declare artifacts to match.")

    status = "matched" if ready_views else "incomplete" if view_records else "unmatched"
    return {
        "schema": VIEW_PLAN_SCHEMA,
        "module_name": str(module_name or "notebook_import_project"),
        "status": status,
        "matching_policy": "app_manifest_only",
        "note": (
            "View suggestions come only from app-owned manifests matched against "
            "artifact paths; notebook cells are not inspected for UI semantics."
        ),
        "source_notebook": source_notebook,
        "manifest": {
            "path": str(manifest_path or ""),
            "schema": normalized_manifest.get("schema", "") if normalized_manifest else "",
            "source_schema": normalized_manifest.get("source_schema", "") if normalized_manifest else "",
            "app": normalized_manifest.get("app", "") if normalized_manifest else "",
            "description": normalized_manifest.get("description", "") if normalized_manifest else "",
        },
        "summary": {
            "artifact_count": len(artifact_paths),
            "declared_view_count": len(view_records),
            "ready_view_count": len(ready_views),
            "incomplete_view_count": len(view_records) - len(ready_views),
            "unmatched_artifact_count": len([path for path in artifact_paths if path not in ready_artifacts]),
        },
        "artifact_paths": artifact_paths,
        "artifact_roles": artifact_roles,
        "matched_views": ready_views,
        "views": view_records,
        "unmatched_artifacts": [path for path in artifact_paths if path not in ready_artifacts],
        "warnings": plan_warnings,
    }


def write_notebook_import_contract(
    path: Path,
    notebook_import: Mapping[str, Any],
    *,
    preflight: Mapping[str, Any] | None = None,
    module_name: str = "notebook_import_project",
) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    contract = build_notebook_import_contract(
        notebook_import,
        preflight=preflight,
        module_name=module_name,
    )
    path.write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_notebook_import_pipeline_view(
    path: Path,
    notebook_import: Mapping[str, Any],
    *,
    preflight: Mapping[str, Any] | None = None,
    module_name: str = "notebook_import_project",
) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    view = build_notebook_import_pipeline_view(
        notebook_import,
        preflight=preflight,
        module_name=module_name,
    )
    path.write_text(json.dumps(view, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_notebook_import_view_plan(
    path: Path,
    notebook_import: Mapping[str, Any],
    *,
    preflight: Mapping[str, Any] | None = None,
    module_name: str = "notebook_import_project",
    manifest: Mapping[str, Any] | None = None,
    manifest_path: str | Path | None = None,
) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    plan_warnings: list[str] = []
    loaded_manifest = manifest
    if loaded_manifest is None and manifest_path:
        candidate = Path(manifest_path).expanduser()
        if candidate.is_file():
            try:
                loaded_manifest = load_notebook_import_view_manifest(candidate)
            except (OSError, TypeError, ValueError, tomllib.TOMLDecodeError) as exc:
                plan_warnings.append(f"Unable to load notebook import view manifest {candidate}: {exc}")
        else:
            plan_warnings.append(f"Notebook import view manifest not found: {candidate}")
    view_plan = build_notebook_import_view_plan(
        notebook_import,
        preflight=preflight,
        module_name=module_name,
        manifest=loaded_manifest,
        manifest_path=manifest_path,
        warnings=plan_warnings,
    )
    path.write_text(json.dumps(view_plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_lab_stages_preview(
    path: Path,
    preview: Mapping[str, list[Mapping[str, Any]]],
) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as stream:
        tomli_w.dump(preview, stream)
    return path


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
    if not notebook_import.get("pipeline_stages"):
        issues.append(_issue("pipeline_stages", "notebook import produced no pipeline stages"))

    return NotebookPipelineImportProof(
        ok=not issues,
        issues=tuple(issues),
        path=str(path),
        notebook_path=str(notebook_path),
        notebook_import=notebook_import,
        reloaded_import=reloaded,
    )
