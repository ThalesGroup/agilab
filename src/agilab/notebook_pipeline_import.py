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

import tomli_w


SCHEMA = "agilab.notebook_pipeline_import.v1"
PREFLIGHT_SCHEMA = "agilab.notebook_import_preflight.v1"
CONTRACT_SCHEMA = "agilab.notebook_import_contract.v1"
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


def _pipeline_step_sources(notebook_import: Mapping[str, Any]) -> list[tuple[str, int, str]]:
    steps = notebook_import.get("pipeline_steps", [])
    if not isinstance(steps, list):
        return []
    sources: list[tuple[str, int, str]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        step_id = str(step.get("id", "") or "")
        source_cell_index = int(step.get("source_cell_index", 0) or 0)
        sources.append((step_id, source_cell_index, _source_from_step(step)))
    return sources


def _detect_line_risks(step_id: str, source: str) -> list[dict[str, str]]:
    risks: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for line_number, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        lowered = stripped.lower()
        location = f"{step_id}:line-{line_number}" if step_id else f"line-{line_number}"
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


def _agilab_supervisor_steps(notebook: Mapping[str, Any]) -> list[dict[str, Any]]:
    payload = _agilab_export_payload(notebook)
    steps = payload.get("steps", [])
    if not isinstance(steps, list):
        return []
    return [step for step in steps if isinstance(step, dict)]


def _supervisor_context_text(step: Mapping[str, Any]) -> str:
    parts = [
        str(step.get("description", "") or "").strip(),
        str(step.get("question", "") or "").strip(),
    ]
    return "\n\n".join(part for part in parts if part)


def _build_from_supervisor_metadata(
    *,
    notebook: Mapping[str, Any],
    source_notebook: Path | str,
    run_id: str,
    supervisor_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = _agilab_export_payload(notebook)
    cells = _notebook_cells(notebook)
    pipeline_steps: list[dict[str, Any]] = []
    context_blocks: list[dict[str, Any]] = []
    all_env_hints: list[str] = []
    all_artifact_references: list[dict[str, Any]] = []

    for step_index, step in enumerate(supervisor_steps, start=1):
        source = str(step.get("code", "") or "")
        if not source.strip():
            continue
        context_id = f"agilab-step-{step_index}-context"
        context_text = _supervisor_context_text(step)
        context_blocks.append(
            {
                "id": context_id,
                "source_cell_index": 0,
                "source_lines": context_text.splitlines(keepends=True),
                "text": context_text,
            }
        )
        env_hints = extract_env_hints(source)
        artifact_references = extract_artifact_references(source, step_index)
        all_env_hints.extend(env_hints)
        all_artifact_references.extend(artifact_references)
        pipeline_steps.append(
            {
                "id": f"supervisor-step-{step_index}",
                "order": len(pipeline_steps) + 1,
                "source_cell_index": 0,
                "cell_type": "code",
                "execution_count": None,
                "source_lines": source.splitlines(keepends=True),
                "source_hash": _hash_source(source),
                "context_ids": [context_id],
                "env_hints": env_hints,
                "artifact_references": artifact_references,
                "runnable": True,
                "description": str(step.get("description", "") or ""),
                "question": str(step.get("question", "") or ""),
                "model": str(step.get("model", "") or ""),
                "runtime": str(step.get("runtime", "") or ""),
                "env": str(step.get("env", "") or ""),
                "pipeline_mapping": {
                    "format": "lab_steps.toml-preview",
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
            "steps_file": str(payload.get("steps_file", "") or ""),
        },
        "summary": {
            "cell_count": len(cells),
            "code_cell_count": code_cell_count,
            "markdown_cell_count": markdown_cell_count,
            "supervisor_step_count": len(supervisor_steps),
            "pipeline_step_count": len(pipeline_steps),
            "context_block_count": len(context_blocks),
            "env_hint_count": len(env_hints_unique),
            "artifact_reference_count": len(all_artifact_references),
            "execution_count_present_count": 0,
            "step_ids": [step["id"] for step in pipeline_steps],
            "context_ids": [block["id"] for block in context_blocks],
        },
        "pipeline_steps": pipeline_steps,
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
            "preserves_lab_steps_fields": True,
        },
    }


def build_notebook_pipeline_import(
    *,
    notebook: Mapping[str, Any],
    source_notebook: Path | str,
    run_id: str = DEFAULT_RUN_ID,
) -> dict[str, Any]:
    supervisor_steps = _agilab_supervisor_steps(notebook)
    if supervisor_steps:
        return _build_from_supervisor_metadata(
            notebook=notebook,
            source_notebook=source_notebook,
            run_id=run_id,
            supervisor_steps=supervisor_steps,
        )

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


def _source_from_step(step: Mapping[str, Any]) -> str:
    return "".join(_coerce_source_lines(step.get("source_lines", [])))


def _artifact_paths(step: Mapping[str, Any]) -> list[str]:
    references = step.get("artifact_references", [])
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


def _step_env_hints(step: Mapping[str, Any]) -> list[str]:
    hints = step.get("env_hints", [])
    if isinstance(hints, list):
        return [str(hint) for hint in hints]
    return []


def build_lab_steps_preview(
    notebook_import: Mapping[str, Any],
    *,
    module_name: str = "notebook_import_project",
) -> dict[str, list[dict[str, Any]]]:
    """Project imported notebook metadata into AGILAB lab_steps TOML entries."""
    module_name = str(module_name or "lab_steps")
    contexts = _context_lookup(notebook_import)
    source = notebook_import.get("source", {})
    source_notebook = ""
    if isinstance(source, dict):
        source_notebook = str(source.get("source_notebook", "") or "")
    execution_mode = str(notebook_import.get("execution_mode", "not_executed_import"))
    steps = notebook_import.get("pipeline_steps", [])
    if not isinstance(steps, list):
        return {module_name: []}

    entries: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        code = _source_from_step(step)
        if not code.strip():
            continue
        context_ids = [
            str(context_id)
            for context_id in step.get("context_ids", [])
            if str(context_id)
        ]
        entry: dict[str, Any] = {
            "D": str(step.get("description", "") or "")
            or _context_summary(context_ids, contexts),
            "Q": str(step.get("question", "") or "")
            or f"Imported notebook cell {step.get('id', '')}",
            "C": code,
            "M": str(step.get("model", "") or ""),
            "NB_CELL_ID": str(step.get("id", "")),
            "NB_CELL_INDEX": int(step.get("source_cell_index", 0) or 0),
            "NB_CONTEXT_IDS": context_ids,
            "NB_ENV_HINTS": _step_env_hints(step),
            "NB_ARTIFACT_REFERENCES": _artifact_paths(step),
            "NB_EXECUTION_MODE": execution_mode,
            "NB_SOURCE_NOTEBOOK": source_notebook,
        }
        execution_count = step.get("execution_count")
        if execution_count is not None:
            entry["NB_EXECUTION_COUNT"] = int(execution_count)
        runtime = str(step.get("runtime", "") or "")
        if runtime:
            entry["R"] = runtime
        env = str(step.get("env", "") or "")
        if env:
            entry["E"] = env
        entries.append(entry)
    return {module_name: entries}


def build_notebook_artifact_contract(notebook_import: Mapping[str, Any]) -> dict[str, Any]:
    """Build an app-neutral input/output contract from imported notebook metadata."""
    step_sources = {
        source_cell_index: source
        for _step_id, source_cell_index, source in _pipeline_step_sources(notebook_import)
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
        source = step_sources.get(source_cell_index, "")
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

    pipeline_step_count = int(summary_map.get("pipeline_step_count", 0) or 0)
    markdown_cell_count = int(summary_map.get("markdown_cell_count", 0) or 0)
    execution_count_present = int(summary_map.get("execution_count_present_count", 0) or 0)

    if pipeline_step_count <= 0:
        risks.append(
            _risk(
                "error",
                "no_code_cells",
                "notebook",
                "Notebook import produced no runnable code cells.",
            )
        )
    if markdown_cell_count <= 0 and pipeline_step_count > 0:
        risks.append(
            _risk(
                "warning",
                "missing_markdown_context",
                "notebook",
                "Notebook has code cells but no markdown context for step names.",
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

    for step_id, _source_cell_index, source in _pipeline_step_sources(notebook_import):
        risks.extend(_detect_line_risks(step_id, source))

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
        "safe_to_import": counts.get("error", 0) == 0 and pipeline_step_count > 0,
        "cleanup_required": counts.get("warning", 0) > 0,
        "risk_counts": counts,
        "summary": {
            "cell_count": int(summary_map.get("cell_count", 0) or 0),
            "code_cell_count": int(summary_map.get("code_cell_count", 0) or 0),
            "markdown_cell_count": markdown_cell_count,
            "pipeline_step_count": pipeline_step_count,
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
    steps = notebook_import.get("pipeline_steps", [])
    iterable_steps = steps if isinstance(steps, list) else []

    contract_steps: list[dict[str, Any]] = []
    for step in iterable_steps:
        if not isinstance(step, dict):
            continue
        contract_steps.append(
            {
                "id": str(step.get("id", "") or ""),
                "order": int(step.get("order", 0) or 0),
                "source_cell_index": int(step.get("source_cell_index", 0) or 0),
                "description": str(step.get("description", "") or ""),
                "question": str(step.get("question", "") or ""),
                "context_ids": list(step.get("context_ids", []) or []),
                "env_hints": list(step.get("env_hints", []) or []),
                "artifact_references": _artifact_paths(step),
                "execution_count": step.get("execution_count"),
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
        "steps": contract_steps,
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


def write_lab_steps_preview(
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
