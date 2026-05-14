from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st
import tomli_w
import tomllib
from code_editor import code_editor

from agi_gui.pagelib import export_df, get_css_text, get_custom_buttons, get_info_bar

import importlib.util

_import_guard_path = Path(__file__).resolve().parent / "import_guard.py"
_import_guard_spec = importlib.util.spec_from_file_location("agilab_import_guard_local", _import_guard_path)
if _import_guard_spec is None or _import_guard_spec.loader is None:
    raise ModuleNotFoundError(f"Unable to load import_guard.py from {_import_guard_path}")
_import_guard_module = importlib.util.module_from_spec(_import_guard_spec)
_import_guard_spec.loader.exec_module(_import_guard_module)
import_agilab_module = _import_guard_module.import_agilab_module

_code_editor_support_module = import_agilab_module(
    "agilab.code_editor_support",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "code_editor_support.py",
    fallback_name="agilab_code_editor_support_fallback",
)
normalize_custom_buttons = _code_editor_support_module.normalize_custom_buttons

_logging_utils_module = import_agilab_module(
    "agilab.logging_utils",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "logging_utils.py",
    fallback_name="agilab_logging_utils_fallback",
)
LOG_DETAIL_LIMIT = _logging_utils_module.LOG_DETAIL_LIMIT
LOG_PATH_LIMIT = _logging_utils_module.LOG_PATH_LIMIT
bound_log_value = _logging_utils_module.bound_log_value

_pipeline_runtime_module = import_agilab_module(
    "agilab.pipeline_runtime",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "pipeline_runtime.py",
    fallback_name="agilab_pipeline_runtime_fallback",
)
_is_valid_runtime_root = _pipeline_runtime_module.is_valid_runtime_root

_pipeline_stages_module = import_agilab_module(
    "agilab.pipeline_stages",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "pipeline_stages.py",
    fallback_name="agilab_pipeline_stages_fallback",
)
_bump_history_revision = _pipeline_stages_module.bump_history_revision
_ensure_primary_module_key = _pipeline_stages_module.ensure_primary_module_key
_prepare_lab_stages_for_write = _pipeline_stages_module.prepare_lab_stages_for_write
_is_displayable_stage = _pipeline_stages_module.is_displayable_stage
_looks_like_stage = _pipeline_stages_module.looks_like_stage
_module_keys = _pipeline_stages_module.module_keys
normalize_runtime_path = _pipeline_stages_module.normalize_runtime_path
_persist_sequence_preferences = _pipeline_stages_module.persist_sequence_preferences
_prune_invalid_entries = _pipeline_stages_module.prune_invalid_entries

_pipeline_stage_templates_module = import_agilab_module(
    "agilab.pipeline_stage_templates",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "pipeline_stage_templates.py",
    fallback_name="agilab_pipeline_stage_templates_fallback",
)
PIPELINE_STAGE_TEMPLATE_ID_KEY = _pipeline_stage_templates_module.PIPELINE_STAGE_TEMPLATE_ID_KEY
PIPELINE_STAGE_TEMPLATE_VERSION_KEY = _pipeline_stage_templates_module.PIPELINE_STAGE_TEMPLATE_VERSION_KEY

_notebook_export_support_module = import_agilab_module(
    "agilab.notebook_export_support",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "notebook_export_support.py",
    fallback_name="agilab_notebook_export_support_fallback",
)
build_notebook_document = _notebook_export_support_module.build_notebook_document
build_notebook_export_context = _notebook_export_support_module.build_notebook_export_context
pycharm_notebook_mirror_path = _notebook_export_support_module.pycharm_notebook_mirror_path
pycharm_notebook_sitecustomize_text = _notebook_export_support_module.pycharm_notebook_sitecustomize_text

_notebook_pipeline_import_module = import_agilab_module(
    "agilab.notebook_pipeline_import",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "notebook_pipeline_import.py",
    fallback_name="agilab_notebook_pipeline_import_fallback",
)
build_lab_stages_preview = _notebook_pipeline_import_module.build_lab_stages_preview
build_notebook_import_contract = _notebook_pipeline_import_module.build_notebook_import_contract
build_notebook_import_preflight = _notebook_pipeline_import_module.build_notebook_import_preflight
build_notebook_pipeline_import = _notebook_pipeline_import_module.build_notebook_pipeline_import
discover_notebook_import_view_manifest = _notebook_pipeline_import_module.discover_notebook_import_view_manifest
write_notebook_import_contract = _notebook_pipeline_import_module.write_notebook_import_contract
write_notebook_import_pipeline_view = _notebook_pipeline_import_module.write_notebook_import_pipeline_view
write_notebook_import_view_plan = _notebook_pipeline_import_module.write_notebook_import_view_plan

logger = logging.getLogger(__name__)
NOTEBOOK_IMPORT_ALL_STAGES = "__all__"


def _emit_streamlit_message(level: str, *args: Any, **kwargs: Any) -> None:
    """Call Streamlit messaging API when available without failing in tests/mocks."""
    fn = getattr(st, level, None)
    if callable(fn):
        fn(*args, **kwargs)


def _coerce_source_lines(cell_source: Any) -> list[str]:
    """Normalize a notebook cell source payload into a list of lines."""
    if cell_source is None:
        return []
    if isinstance(cell_source, str):
        return cell_source.splitlines(keepends=True)
    if isinstance(cell_source, Iterable):
        return [str(line) for line in cell_source]
    return [str(cell_source)]


def _is_uploaded_notebook(uploaded_file: Any) -> bool:
    """Return True if the uploaded object looks like a Jupyter notebook."""
    if not uploaded_file:
        return False
    filename = str(getattr(uploaded_file, "name", "") or "").lower()
    mime_type = str(getattr(uploaded_file, "type", "") or "").lower()
    has_metadata = bool(filename or mime_type)
    if filename.endswith(".ipynb"):
        return True
    if has_metadata and "ipynb" not in mime_type:
        return False
    if not has_metadata:
        return True
    return "ipynb" in mime_type


def _read_uploaded_text(uploaded_file: Any) -> str:
    """Read an uploaded file-like object and normalize into UTF-8 text."""
    raw = uploaded_file.read()
    if isinstance(raw, str):
        return raw
    if isinstance(raw, bytes):
        return raw.decode("utf-8")
    return str(raw)


def _emit_notebook_preflight_result(
    preflight: Dict[str, Any],
    contract_path: Path,
    view_plan_path: Path | None = None,
) -> None:
    summary = preflight.get("summary", {}) if isinstance(preflight, dict) else {}
    risk_counts = preflight.get("risk_counts", {}) if isinstance(preflight, dict) else {}
    status = str(preflight.get("status", "ready") if isinstance(preflight, dict) else "ready")
    warning_count = int(risk_counts.get("warning", 0) or 0)
    error_count = int(risk_counts.get("error", 0) or 0)
    message = (
        f"Notebook import preflight: {status}; "
        f"{int(summary.get('pipeline_stage_count', 0) or 0)} stage(s), "
        f"{int(summary.get('input_count', 0) or 0)} input(s), "
        f"{int(summary.get('output_count', 0) or 0)} output(s). "
        f"Contract: {contract_path.name}"
    )
    if view_plan_path is not None:
        message = f"{message}; View plan: {view_plan_path.name}"
    if error_count:
        _emit_streamlit_message("error", message)
    elif warning_count:
        _emit_streamlit_message("warning", message)
    else:
        _emit_streamlit_message("info", message)


def _notebook_import_preview_key(index_page: str) -> str:
    return f"{index_page}__notebook_import_preview"


def _notebook_import_module_name(module_dir: Path) -> str:
    module = Path(module_dir).name
    return module or "lab_stages"


def _notebook_import_preview_is_safe(preview: Dict[str, Any]) -> bool:
    preflight = preview.get("preflight", {})
    return isinstance(preflight, dict) and preflight.get("safe_to_import") is True


def _notebook_import_stage_identity(stage: Dict[str, Any], index: int) -> str:
    stage_id = str(stage.get("id", "") or "").strip()
    return stage_id or f"stage-{index}"


def _notebook_import_stages(preview: Dict[str, Any]) -> list[Dict[str, Any]]:
    notebook_import = preview.get("notebook_import", {})
    stages = notebook_import.get("pipeline_stages", []) if isinstance(notebook_import, dict) else []
    if not isinstance(stages, list):
        return []
    return [stage for stage in stages if isinstance(stage, dict)]


def _notebook_import_stage_label(stage: Dict[str, Any], index: int) -> str:
    stage_id = _notebook_import_stage_identity(stage, index)
    source_cell_index = int(stage.get("source_cell_index", 0) or 0)
    description = str(stage.get("description", "") or "").strip()
    question = str(stage.get("question", "") or "").strip()
    summary = description or question or stage_id
    if len(summary) > 64:
        summary = f"{summary[:61]}..."
    return f"Cell {source_cell_index} ({stage_id}): {summary}"


def _notebook_import_stage_options(preview: Dict[str, Any]) -> list[Dict[str, Any]]:
    return [
        {
            "id": _notebook_import_stage_identity(stage, index),
            "label": _notebook_import_stage_label(stage, index),
            "stage": stage,
        }
        for index, stage in enumerate(_notebook_import_stages(preview), start=1)
    ]


def _notebook_import_stage_detail(stage: Dict[str, Any]) -> str:
    source_cell_index = int(stage.get("source_cell_index", 0) or 0)
    artifacts = _artifact_paths_from_notebook_stage(stage)
    env_hints = _stage_env_hints_from_notebook_stage(stage)
    artifact_text = ", ".join(artifacts[:3]) if artifacts else "none"
    if len(artifacts) > 3:
        artifact_text = f"{artifact_text}, +{len(artifacts) - 3} more"
    env_text = ", ".join(env_hints[:4]) if env_hints else "none"
    if len(env_hints) > 4:
        env_text = f"{env_text}, +{len(env_hints) - 4} more"
    return (
        f"Selected cell {source_cell_index}; "
        f"artifacts: {artifact_text}; "
        f"environment hints: {env_text}."
    )


def _stage_env_hints_from_notebook_stage(stage: Dict[str, Any]) -> list[str]:
    hints = stage.get("env_hints", [])
    if not isinstance(hints, list):
        return []
    return [str(hint) for hint in hints if str(hint)]


def _artifact_paths_from_notebook_stage(stage: Dict[str, Any]) -> list[str]:
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


def _filter_notebook_import_for_stage_ids(
    notebook_import: Dict[str, Any],
    selected_stage_ids: Iterable[str],
) -> Dict[str, Any]:
    selected_ids = list(dict.fromkeys(str(stage_id) for stage_id in selected_stage_ids if str(stage_id)))
    selected_id_set = set(selected_ids)
    stages = notebook_import.get("pipeline_stages", [])
    stage_list = stages if isinstance(stages, list) else []
    selected_stages = [
        dict(stage)
        for index, stage in enumerate(stage_list, start=1)
        if isinstance(stage, dict) and _notebook_import_stage_identity(stage, index) in selected_id_set
    ]

    context_ids: list[str] = []
    env_hints: list[str] = []
    artifact_references: list[Dict[str, Any]] = []
    execution_count_present = 0
    for stage in selected_stages:
        for context_id in stage.get("context_ids", []):
            context_id_text = str(context_id)
            if context_id_text and context_id_text not in context_ids:
                context_ids.append(context_id_text)
        env_hints.extend(_stage_env_hints_from_notebook_stage(stage))
        references = stage.get("artifact_references", [])
        if isinstance(references, list):
            artifact_references.extend(reference for reference in references if isinstance(reference, dict))
        if stage.get("execution_count") is not None:
            execution_count_present += 1

    context_blocks = notebook_import.get("context_blocks", [])
    context_block_list = context_blocks if isinstance(context_blocks, list) else []
    selected_context_blocks = [
        dict(block)
        for block in context_block_list
        if isinstance(block, dict) and str(block.get("id", "") or "") in context_ids
    ]
    unique_env_hints = sorted(dict.fromkeys(env_hints))
    summary = dict(notebook_import.get("summary", {}) if isinstance(notebook_import.get("summary", {}), dict) else {})
    summary.update(
        {
            "pipeline_stage_count": len(selected_stages),
            "code_cell_count": len(selected_stages),
            "context_block_count": len(selected_context_blocks),
            "env_hint_count": len(unique_env_hints),
            "artifact_reference_count": len(artifact_references),
            "execution_count_present_count": execution_count_present,
            "stage_ids": [str(stage.get("id", "") or "") for stage in selected_stages],
            "context_ids": context_ids,
            "selected_stage_ids": selected_ids,
        }
    )

    source = dict(notebook_import.get("source", {}) if isinstance(notebook_import.get("source", {}), dict) else {})
    source["selection_mode"] = "selected_notebook_cells"
    source["selected_stage_ids"] = selected_ids
    provenance = dict(
        notebook_import.get("provenance", {})
        if isinstance(notebook_import.get("provenance", {}), dict)
        else {}
    )
    provenance["selection_mode"] = "selected_notebook_cells"
    provenance["selected_stage_ids"] = selected_ids

    filtered = dict(notebook_import)
    filtered.update(
        {
            "source": source,
            "summary": summary,
            "pipeline_stages": selected_stages,
            "context_blocks": selected_context_blocks,
            "env_hints": unique_env_hints,
            "artifact_references": artifact_references,
            "provenance": provenance,
        }
    )
    return filtered


def _selected_notebook_import_preview(
    preview: Dict[str, Any],
    selected_stage_ids: Iterable[str] | None,
) -> Dict[str, Any]:
    selected_ids = [str(stage_id) for stage_id in (selected_stage_ids or []) if str(stage_id)]
    if not selected_ids or NOTEBOOK_IMPORT_ALL_STAGES in selected_ids:
        return preview
    notebook_import = preview.get("notebook_import", {})
    if not isinstance(notebook_import, dict):
        return preview
    selected_import = _filter_notebook_import_for_stage_ids(notebook_import, selected_ids)
    module = str(preview.get("module", "") or "lab_stages")
    preflight = build_notebook_import_preflight(selected_import)
    selected_preview = dict(preview)
    selected_preview.update(
        {
            "cell_count": int(
                selected_import.get("summary", {}).get("pipeline_stage_count", 0)
                if isinstance(selected_import.get("summary", {}), dict)
                else 0
            ),
            "notebook_import": selected_import,
            "preflight": preflight,
            "toml_content": build_lab_stages_preview(selected_import, module_name=module),
            "contract": build_notebook_import_contract(
                selected_import,
                preflight=preflight,
                module_name=module,
            ),
            "selection_mode": "selected_notebook_cells",
            "selected_stage_ids": selected_ids,
        }
    )
    return selected_preview


def _notebook_import_blocking_detail(preflight: Any) -> str:
    if not isinstance(preflight, dict):
        return "Notebook preflight did not produce a valid report."
    risks = preflight.get("risks", [])
    if isinstance(risks, list):
        messages: list[str] = []
        for risk in risks:
            if not isinstance(risk, dict) or risk.get("level") != "error":
                continue
            message = str(risk.get("message") or risk.get("rule") or "").strip()
            if message:
                messages.append(message)
        if messages:
            return "; ".join(messages[:3])
    return "Notebook import preflight marked this notebook unsafe to import."


def build_notebook_import_preview(
    uploaded_file: Any,
    module_dir: Path,
) -> Dict[str, Any] | None:
    """Build notebook import preview data without writing lab_stages.toml."""
    if not uploaded_file:
        _emit_streamlit_message("error", "No uploaded notebook provided.")
        return None
    if not _is_uploaded_notebook(uploaded_file):
        _emit_streamlit_message("error", "Please upload a .ipynb file.")
        return None
    try:
        file_content = _read_uploaded_text(uploaded_file)
        notebook_content = json.loads(file_content)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        _emit_streamlit_message("error", f"Unable to parse notebook: {exc}")
        return None
    if not isinstance(notebook_content, dict):
        _emit_streamlit_message("error", "Invalid notebook format: expected a JSON object.")
        return None

    module = _notebook_import_module_name(module_dir)
    source_name = str(getattr(uploaded_file, "name", "") or "uploaded.ipynb")
    try:
        notebook_import = build_notebook_pipeline_import(
            notebook=notebook_content,
            source_notebook=source_name,
        )
        preflight = build_notebook_import_preflight(notebook_import)
        toml_content = build_lab_stages_preview(notebook_import, module_name=module)
        contract = build_notebook_import_contract(
            notebook_import,
            preflight=preflight,
            module_name=module,
        )
    except (TypeError, ValueError) as exc:
        _emit_streamlit_message("error", f"Invalid notebook format: {exc}")
        return None
    return {
        "source_name": source_name,
        "module": module,
        "cell_count": int(notebook_import.get("summary", {}).get("pipeline_stage_count", 0) or 0),
        "toml_content": toml_content,
        "notebook_import": notebook_import,
        "preflight": preflight,
        "contract": contract,
    }


def write_notebook_import_preview(
    preview: Dict[str, Any],
    module_dir: Path,
    stages_file: Path,
    *,
    view_manifest_dir: Path | None = None,
) -> int:
    """Persist a previously built notebook import preview."""
    module_dir = Path(module_dir)
    stages_file = Path(stages_file)
    toml_content = preview.get("toml_content", {})
    preflight = preview.get("preflight", {})
    notebook_import = preview.get("notebook_import", {})
    module = str(preview.get("module", "") or _notebook_import_module_name(module_dir))
    cell_count = int(preview.get("cell_count", 0) or 0)

    stages_file.parent.mkdir(parents=True, exist_ok=True)
    temp_stages_file = stages_file.with_name(f".{stages_file.name}.{os.getpid()}.tmp")
    try:
        with open(temp_stages_file, "wb") as toml_file:
            tomli_w.dump(convert_paths_to_strings(_prepare_lab_stages_for_write(toml_content)), toml_file)
        temp_stages_file.replace(stages_file)
    except (OSError, TypeError, ValueError):
        try:
            temp_stages_file.unlink()
        except OSError:
            pass
        raise

    contract_path = module_dir / "notebook_import_contract.json"
    pipeline_view_path = module_dir / "notebook_import_pipeline_view.json"
    view_plan_path = module_dir / "notebook_import_view_plan.json"
    view_manifest_path = discover_notebook_import_view_manifest(view_manifest_dir or module_dir)
    write_notebook_import_contract(
        contract_path,
        notebook_import,
        preflight=preflight,
        module_name=module,
    )
    write_notebook_import_pipeline_view(
        pipeline_view_path,
        notebook_import,
        preflight=preflight,
        module_name=module,
    )
    write_notebook_import_view_plan(
        view_plan_path,
        notebook_import,
        preflight=preflight,
        module_name=module,
        manifest_path=view_manifest_path,
    )
    _emit_notebook_preflight_result(preflight, contract_path, view_plan_path=view_plan_path)
    return cell_count


def convert_paths_to_strings(obj: Any) -> Any:
    """Recursively convert pathlib.Path objects to strings for serialization."""
    if isinstance(obj, dict):
        return {k: convert_paths_to_strings(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [convert_paths_to_strings(item) for item in obj]
    if isinstance(obj, Path):
        return str(obj)
    return obj

def is_query_valid(query: Any) -> bool:
    """Check if a query is valid."""
    return isinstance(query, list) and bool(query[2])


def get_stages_list(module: Path, stages_file: Path) -> List[Any]:
    """Get the list of stages for a module from a TOML file."""
    module_path = Path(module)
    try:
        with open(stages_file, "rb") as f:
            stages = tomllib.load(f)
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        return []

    for key in _module_keys(module_path):
        entries = stages.get(key)
        if isinstance(entries, list):
            return entries
    return []


def get_stages_dict(module: Path, stages_file: Path) -> Dict[str, Any]:
    """Get the stages dictionary from a TOML file."""
    module_path = Path(module)
    try:
        with open(stages_file, "rb") as f:
            stages = tomllib.load(f)
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        stages = {}
    else:
        keys = _module_keys(module_path)
        primary = keys[0]
        for alt_key in keys[1:]:
            if alt_key != primary:
                stages.pop(alt_key, None)
    return stages


def remove_stage(
    module: Path,
    stage: str,
    stages_file: Path,
    index_page: str,
) -> int:
    """Remove a stage from the lab_stages contract."""
    module_path = Path(module)
    stages = get_stages_dict(module_path, stages_file)
    module_keys = _module_keys(module_path)
    module_key = next((key for key in module_keys if key in stages), module_keys[0])
    stages.setdefault(module_key, [])
    nstages = len(stages.get(module_key, []))
    index_stage = int(stage)
    details_key = f"{index_page}__details"
    details_store = st.session_state.setdefault(details_key, {})
    venv_key = f"{index_page}__venv_map"
    venv_store = st.session_state.setdefault(venv_key, {})
    engine_key = f"{index_page}__engine_map"
    engine_store = st.session_state.setdefault(engine_key, {})
    sequence_key = f"{index_page}__run_sequence"
    sequence_store = st.session_state.setdefault(sequence_key, list(range(nstages)))
    if 0 <= index_stage < nstages:
        del stages[module_key][index_stage]
        nstages -= 1
        st.session_state[index_page][0] = max(0, nstages - 1)
        st.session_state[index_page][-1] = nstages
        shifted: Dict[int, str] = {}
        vshifted: Dict[int, str] = {}
        eshifted: Dict[int, str] = {}
        for idx, text in details_store.items():
            if idx < index_stage:
                shifted[idx] = text
            elif idx > index_stage:
                shifted[idx - 1] = text
        st.session_state[details_key] = shifted
        for idx, path in venv_store.items():
            if idx < index_stage:
                vshifted[idx] = path
            elif idx > index_stage:
                vshifted[idx - 1] = path
        st.session_state[venv_key] = vshifted
        for idx, engine in engine_store.items():
            if idx < index_stage:
                eshifted[idx] = engine
            elif idx > index_stage:
                eshifted[idx - 1] = engine
        st.session_state[engine_key] = eshifted
        new_sequence: List[int] = []
        for idx in sequence_store:
            if idx == index_stage:
                continue
            new_idx = idx - 1 if idx > index_stage else idx
            if 0 <= new_idx < nstages and new_idx not in new_sequence:
                new_sequence.append(new_idx)
        if nstages > 0 and not new_sequence:
            new_sequence = list(range(nstages))
        st.session_state[sequence_key] = new_sequence
    else:
        st.session_state[index_page][0] = 0
        st.session_state[venv_key] = venv_store
        st.session_state[engine_key] = engine_store
        st.session_state[sequence_key] = [idx for idx in sequence_store if idx < nstages]

    stages[module_key] = _prune_invalid_entries(stages[module_key])
    nstages = len(stages[module_key])
    st.session_state[index_page][-1] = nstages
    current_sequence = st.session_state.get(sequence_key, [])
    _persist_sequence_preferences(module_path, stages_file, current_sequence)

    try:
        serializable_stages = convert_paths_to_strings(_prepare_lab_stages_for_write(stages))
        with open(stages_file, "wb") as f:
            tomli_w.dump(serializable_stages, f)
    except (OSError, TypeError, ValueError) as e:
        st.error(f"Failed to save stage contract: {e}")
        logger.error(
            "Error writing TOML in remove_stage: %s",
            bound_log_value(e, LOG_DETAIL_LIMIT),
        )

    _bump_history_revision()
    return nstages


def _normalize_pipeline_stage_entry(raw_entry: Any) -> Dict[str, Any] | None:
    """Normalize core editor fields while preserving versioned stage metadata."""
    if not isinstance(raw_entry, dict):
        return None

    normalized = dict(raw_entry)
    normalized["D"] = raw_entry.get("D", "")
    normalized["Q"] = raw_entry.get("Q", "")
    normalized["M"] = raw_entry.get("M", "")
    normalized["C"] = raw_entry.get("C", "")
    normalized["E"] = normalize_runtime_path(raw_entry.get("E", "")) if raw_entry.get("E") else ""
    normalized["R"] = str(raw_entry.get("R", "") or "")

    for key in (PIPELINE_STAGE_TEMPLATE_ID_KEY, PIPELINE_STAGE_TEMPLATE_VERSION_KEY):
        if key in raw_entry:
            normalized[key] = raw_entry[key]
    return normalized


def _write_stages_for_module(
    module: Path,
    stages_file: Path,
    module_stages: List[Dict[str, Any]],
) -> int:
    """Overwrite the module stage list in ``stages_file`` and refresh notebook export."""
    module_path = Path(module)
    stages = get_stages_dict(module_path, stages_file)
    module_key = _module_keys(module_path)[0]

    normalized_stages: List[Dict[str, Any]] = []
    for raw_entry in module_stages:
        normalized_entry = _normalize_pipeline_stage_entry(raw_entry)
        if normalized_entry is not None:
            normalized_stages.append(normalized_entry)

    stages[module_key] = _prune_invalid_entries(normalized_stages)
    serializable_stages = convert_paths_to_strings(_prepare_lab_stages_for_write(stages))
    with open(stages_file, "wb") as f:
        tomli_w.dump(serializable_stages, f)
    toml_to_notebook(stages, stages_file)
    return len(stages[module_key])


def _capture_pipeline_snapshot(index_page: str, stages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Capture the current pipeline state so delete actions can be undone."""
    stages_snapshot: List[Dict[str, Any]] = []
    for raw_entry in stages:
        normalized_entry = _normalize_pipeline_stage_entry(raw_entry)
        if normalized_entry is not None:
            stages_snapshot.append(normalized_entry)

    details_key = f"{index_page}__details"
    venv_key = f"{index_page}__venv_map"
    engine_key = f"{index_page}__engine_map"
    sequence_key = f"{index_page}__run_sequence"

    details_snapshot: Dict[int, str] = {}
    for raw_idx, text in st.session_state.get(details_key, {}).items():
        try:
            idx = int(raw_idx)
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(stages_snapshot):
            details_snapshot[idx] = str(text or "")

    venv_snapshot: Dict[int, str] = {}
    for raw_idx, raw_path in st.session_state.get(venv_key, {}).items():
        try:
            idx = int(raw_idx)
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(stages_snapshot):
            normalized = normalize_runtime_path(raw_path)
            if normalized:
                venv_snapshot[idx] = normalized

    engine_snapshot: Dict[int, str] = {}
    for raw_idx, engine in st.session_state.get(engine_key, {}).items():
        try:
            idx = int(raw_idx)
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(stages_snapshot):
            engine_snapshot[idx] = str(engine or "")

    raw_sequence = st.session_state.get(sequence_key, list(range(len(stages_snapshot))))
    sequence_snapshot: List[int] = []
    for raw_idx in raw_sequence:
        try:
            idx = int(raw_idx)
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(stages_snapshot) and idx not in sequence_snapshot:
            sequence_snapshot.append(idx)
    if len(stages_snapshot) > 0 and not sequence_snapshot:
        sequence_snapshot = list(range(len(stages_snapshot)))

    page_state = st.session_state.get(index_page, [0])
    try:
        active_stage = int(page_state[0]) if isinstance(page_state, list) and page_state else 0
    except (TypeError, ValueError):
        active_stage = 0

    return {
        "stages": stages_snapshot,
        "details": details_snapshot,
        "venv_map": venv_snapshot,
        "engine_map": engine_snapshot,
        "sequence": sequence_snapshot,
        "active_stage": active_stage,
        "selected_venv": normalize_runtime_path(st.session_state.get("lab_selected_venv", "")),
        "selected_engine": str(st.session_state.get("lab_selected_engine", "") or ""),
    }


def _reset_pipeline_editor_state(index_page: str) -> None:
    """Drop per-stage widget keys so restored snapshots reseed editor state from disk."""
    safe_prefix = index_page.replace("/", "_")
    key_prefixes = (
        f"{safe_prefix}_q_stage_",
        f"{safe_prefix}_code_stage_",
        f"{safe_prefix}_venv_",
        f"{safe_prefix}_editor_rev_",
        f"{safe_prefix}_pending_q_",
        f"{safe_prefix}_pending_c_",
        f"{safe_prefix}_stage_init_",
        f"{safe_prefix}_editor_resync_sig_",
        f"{safe_prefix}_ignore_blank_editor_",
        f"{safe_prefix}_undo_",
        f"{safe_prefix}_confirm_delete_",
    )
    for key in list(st.session_state.keys()):
        if key.startswith(key_prefixes) or key.startswith(f"{safe_prefix}a"):
            st.session_state.pop(key, None)


def _restore_pipeline_snapshot(
    module_path: Path,
    stages_file: Path,
    index_page: str,
    sequence_widget_key: str,
    snapshot: Dict[str, Any],
) -> Optional[str]:
    """Restore stages and UI state from a previously captured snapshot."""
    try:
        stages_snapshot = snapshot.get("stages", [])
        if not isinstance(stages_snapshot, list):
            stages_snapshot = []
        nstages = _write_stages_for_module(module_path, stages_file, stages_snapshot)

        details_key = f"{index_page}__details"
        venv_key = f"{index_page}__venv_map"
        engine_key = f"{index_page}__engine_map"
        sequence_key = f"{index_page}__run_sequence"

        details_map: Dict[int, str] = {}
        for raw_idx, text in snapshot.get("details", {}).items():
            try:
                idx = int(raw_idx)
            except (TypeError, ValueError):
                continue
            if 0 <= idx < nstages:
                details_map[idx] = str(text or "")
        st.session_state[details_key] = details_map

        venv_map: Dict[int, str] = {}
        for raw_idx, raw_path in snapshot.get("venv_map", {}).items():
            try:
                idx = int(raw_idx)
            except (TypeError, ValueError):
                continue
            if 0 <= idx < nstages:
                normalized = normalize_runtime_path(raw_path)
                if normalized:
                    venv_map[idx] = normalized
        st.session_state[venv_key] = venv_map

        engine_map: Dict[int, str] = {}
        for raw_idx, engine in snapshot.get("engine_map", {}).items():
            try:
                idx = int(raw_idx)
            except (TypeError, ValueError):
                continue
            if 0 <= idx < nstages:
                engine_map[idx] = str(engine or "")
        st.session_state[engine_key] = engine_map

        raw_sequence = snapshot.get("sequence", [])
        restored_sequence: List[int] = []
        if isinstance(raw_sequence, list):
            for raw_idx in raw_sequence:
                try:
                    idx = int(raw_idx)
                except (TypeError, ValueError):
                    continue
                if 0 <= idx < nstages and idx not in restored_sequence:
                    restored_sequence.append(idx)
        if nstages > 0 and not restored_sequence:
            restored_sequence = list(range(nstages))
        st.session_state[sequence_key] = restored_sequence
        _persist_sequence_preferences(module_path, stages_file, restored_sequence)
        st.session_state.pop(sequence_widget_key, None)
        st.session_state.pop(f"{index_page}__clear_q", None)
        st.session_state.pop(f"{index_page}__force_blank_q", None)
        st.session_state.pop(f"{index_page}__q_rev", None)
        st.session_state.pop(f"{index_page}_confirm_delete_all", None)
        _reset_pipeline_editor_state(index_page)

        page_state = st.session_state.get(index_page)
        if not isinstance(page_state, list) or len(page_state) < 7:
            page_state = [0, "", "", "", "", "", 0]
            st.session_state[index_page] = page_state

        if nstages > 0:
            try:
                active_stage = int(snapshot.get("active_stage", 0))
            except (TypeError, ValueError):
                active_stage = 0
            active_stage = max(0, min(active_stage, nstages - 1))
            active_entry = stages_snapshot[active_stage] if active_stage < len(stages_snapshot) else {}
            if not isinstance(active_entry, dict):
                active_entry = {}
            page_state[0] = active_stage
            page_state[1:6] = [
                active_entry.get("D", ""),
                active_entry.get("Q", ""),
                active_entry.get("M", ""),
                active_entry.get("C", ""),
                details_map.get(active_stage, ""),
            ]
            restored_selected_venv = normalize_runtime_path(snapshot.get("selected_venv", ""))
            if not restored_selected_venv:
                restored_selected_venv = normalize_runtime_path(venv_map.get(active_stage, ""))
            st.session_state["lab_selected_venv"] = (
                restored_selected_venv if _is_valid_runtime_root(restored_selected_venv) else ""
            )
            restored_selected_engine = str(snapshot.get("selected_engine", "") or "")
            if not restored_selected_engine:
                restored_selected_engine = engine_map.get(active_stage, "") or (
                    "agi.run" if st.session_state.get("lab_selected_venv") else "runpy"
                )
            st.session_state["lab_selected_engine"] = restored_selected_engine
        else:
            page_state[:] = [0, "", "", "", "", "", 0]
            st.session_state["lab_selected_venv"] = ""
            st.session_state["lab_selected_engine"] = "runpy"

        page_state[-1] = nstages
        _bump_history_revision()
        return None
    except (AttributeError, IndexError, KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
        logger.error(
            "Undo restore failed for %s: %s",
            bound_log_value(stages_file, LOG_PATH_LIMIT),
            bound_log_value(exc, LOG_DETAIL_LIMIT),
        )
        return str(exc)


def resolve_pycharm_notebook_path(
    stages_file: Path,
    export_context: Any | None = None,
) -> Path | None:
    """Return the repo-local PyCharm notebook path when a source checkout is available."""
    mirror_path = str(pycharm_notebook_mirror_path(stages_file, export_context=export_context) or "").strip()
    if not mirror_path:
        return None
    try:
        return Path(mirror_path)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def _write_notebook_json(notebook_data: Dict[str, Any], notebook_path: Path) -> None:
    notebook_path.parent.mkdir(parents=True, exist_ok=True)
    with open(notebook_path, "w", encoding="utf-8") as nb_file:
        json.dump(notebook_data, nb_file, indent=2)


def _write_pycharm_sitecustomize(notebook_path: Path) -> None:
    sitecustomize_path = notebook_path.parent / "sitecustomize.py"
    sitecustomize_path.parent.mkdir(parents=True, exist_ok=True)
    with open(sitecustomize_path, "w", encoding="utf-8") as stream:
        stream.write(pycharm_notebook_sitecustomize_text())


def toml_to_notebook(
    toml_data: Dict[str, Any],
    toml_path: Path,
    export_context: Any | None = None,
) -> None:
    """Convert TOML stage data to a Jupyter notebook file."""
    notebook_data = build_notebook_document(toml_data, toml_path, export_context=export_context)
    notebook_path = toml_path.with_suffix(".ipynb")
    try:
        _write_notebook_json(notebook_data, notebook_path)
    except (OSError, TypeError, ValueError) as e:
        st.error(f"Failed to save notebook: {e}")
        logger.error(
            "Error saving notebook in toml_to_notebook: %s",
            bound_log_value(e, LOG_DETAIL_LIMIT),
        )
        return

    pycharm_path = resolve_pycharm_notebook_path(toml_path, export_context=export_context)
    if pycharm_path is None:
        return
    if pycharm_path != notebook_path:
        try:
            _write_notebook_json(notebook_data, pycharm_path)
        except (OSError, TypeError, ValueError) as exc:
            logger.warning("Unable to write PyCharm notebook mirror %s: %s", pycharm_path, exc)
            return
    try:
        _write_pycharm_sitecustomize(pycharm_path)
    except (OSError, TypeError, ValueError) as exc:
        logger.warning("Unable to write PyCharm notebook sitecustomize for %s: %s", pycharm_path, exc)


def save_query(
    module: Path,
    query: List[Any],
    stages_file: Path,
    index_page: str,
) -> None:
    """Save the query to the stage contract if valid."""
    module_path = Path(module)
    if is_query_valid(query):
        venv_map = st.session_state.get(f"{index_page}__venv_map", {})
        engine_map = st.session_state.get(f"{index_page}__engine_map", {})
        # Persist only D, Q, M, and C
        query[-1], _ = save_stage(
            module_path,
            query[1:5],
            query[0],
            query[-1],
            stages_file,
            venv_map=venv_map,
            engine_map=engine_map,
        )
        _bump_history_revision()
    export_df()


def save_stage(
    module: Path,
    query: List[Any],
    current_stage: int,
    nstages: int,
    stages_file: Path,
    venv_map: Optional[Dict[int, str]] = None,
    engine_map: Optional[Dict[int, str]] = None,
    extra_fields: Optional[Dict[str, Any]] = None,
) -> Tuple[int, Dict[str, Any]]:
    """Save a stage in the lab_stages contract."""
    st.session_state["_experiment_last_save_skipped"] = False
    module_path = Path(module)
    # Normalize types
    try:
        nstages = int(nstages)
    except (TypeError, ValueError):
        nstages = 0
    try:
        index_stage = int(current_stage)
    except (TypeError, ValueError):
        index_stage = 0
    if stages_file.exists():
        with open(stages_file, "rb") as f:
            stages = tomllib.load(f)
    else:
        os.makedirs(stages_file.parent, exist_ok=True)
        stages = {}

    module_keys = _module_keys(module_path)
    module_str = module_keys[0]
    stages.setdefault(module_str, [])
    for alt_key in module_keys[1:]:
        if alt_key in stages:
            alt_entries = stages.pop(alt_key)
            if not stages[module_str] or len(alt_entries) > len(stages[module_str]):
                stages[module_str] = alt_entries

    # Capture any existing entry so we can preserve values when maps aren't provided
    existing_entry: Dict[str, Any] = {}
    if 0 <= index_stage < len(stages[module_str]):
        current_entry = stages[module_str][index_stage]
        if isinstance(current_entry, dict):
            existing_entry = current_entry

    # Persist D, Q, M, and C (+ E/R when provided). Preserve existing metadata
    # fields (for locked snippets and future extension keys).
    # - [D, Q, M, C]
    # - [stage, D, Q, M, C, ...]
    if len(query) >= 5 and _looks_like_stage(query[0]):
        d_idx, q_idx, m_idx, c_idx = 1, 2, 3, 4
    else:
        d_idx, q_idx, m_idx, c_idx = 0, 1, 2, 3

    entry: Dict[str, Any] = dict(existing_entry) if isinstance(existing_entry, dict) else {}
    entry["D"] = query[d_idx] if d_idx < len(query) else ""
    entry["Q"] = query[q_idx] if q_idx < len(query) else ""
    entry["M"] = query[m_idx] if m_idx < len(query) else ""
    entry["C"] = query[c_idx] if c_idx < len(query) else ""

    # Prefer the current env's OPENAI_MODEL (or Azure deployment) when available
    try:
        env = st.session_state.get("env")
        if env and env.envars:
            model_from_env = env.envars.get("OPENAI_MODEL") or env.envars.get("AZURE_OPENAI_DEPLOYMENT")
            if model_from_env:
                entry["M"] = model_from_env
    except (AttributeError, RuntimeError, TypeError):
        pass
    if venv_map is not None:
        try:
            entry["E"] = normalize_runtime_path(venv_map.get(index_stage, ""))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            entry["E"] = ""
    elif "E" in existing_entry:
        entry["E"] = normalize_runtime_path(existing_entry.get("E", ""))

    if engine_map is not None:
        try:
            entry["R"] = str(engine_map.get(index_stage, "") or "")
        except (AttributeError, RuntimeError, TypeError, ValueError):
            entry["R"] = ""
    elif "R" in existing_entry:
        entry["R"] = str(existing_entry.get("R", "") or "")

    code_text = entry.get("C", "")
    if not isinstance(code_text, str):
        code_text = str(code_text or "")
    entry["C"] = code_text
    if extra_fields:
        for key, value in extra_fields.items():
            if value is None:
                entry.pop(key, None)
            else:
                entry[key] = value

    nstages_saved = len(stages[module_str])
    nstages = max(int(nstages), nstages_saved)

    if index_stage < nstages_saved:
        stages[module_str][index_stage] = entry
    else:
        stages[module_str].append(entry)

    stages[module_str] = _prune_invalid_entries(stages[module_str], keep_index=index_stage)
    nstages = len(stages[module_str])

    try:
        serializable_stages = convert_paths_to_strings(_prepare_lab_stages_for_write(stages))
        with open(stages_file, "wb") as f:
            tomli_w.dump(serializable_stages, f)
    except (OSError, TypeError, ValueError) as e:
        st.error(f"Failed to save stage contract: {e}")
        logger.error(
            "Error writing TOML in save_stage: %s",
            bound_log_value(e, LOG_DETAIL_LIMIT),
        )
        st.session_state["_experiment_last_save_skipped"] = True
        return nstages, entry

    toml_to_notebook(stages, stages_file)
    return nstages, entry


def _force_persist_stage(
    module_path: Path,
    stages_file: Path,
    stage_idx: int,
    entry: Dict[str, Any],
) -> None:
    """Ensure the given entry is written to stages_file at stage_idx."""
    try:
        module_key = _module_keys(module_path)[0]
        stages: Dict[str, Any] = {}
        if stages_file.exists():
            with open(stages_file, "rb") as f:
                stages = tomllib.load(f)
        stages.setdefault(module_key, [])
        while len(stages[module_key]) <= stage_idx:
            stages[module_key].append({})
        current = stages[module_key][stage_idx]
        merged = dict(current) if isinstance(current, dict) else {}
        merged.update(convert_paths_to_strings(entry))
        stages[module_key][stage_idx] = merged
        stages_file.parent.mkdir(parents=True, exist_ok=True)
        with open(stages_file, "wb") as f:
            tomli_w.dump(convert_paths_to_strings(_prepare_lab_stages_for_write(stages)), f)
    except (OSError, TypeError, ValueError, tomllib.TOMLDecodeError) as exc:
        logger.error(
            "Force persist failed for stage %s -> %s: %s",
            stage_idx,
            bound_log_value(stages_file, LOG_PATH_LIMIT),
            bound_log_value(exc, LOG_DETAIL_LIMIT),
        )

def notebook_to_toml(
    uploaded_file: Any,
    toml_file_name: str,
    module_dir: Path,
    *,
    view_manifest_dir: Path | None = None,
) -> int | None:
    """Convert uploaded Jupyter notebook file to a TOML file."""
    preview = build_notebook_import_preview(uploaded_file, module_dir)
    if preview is None:
        return None
    if not _notebook_import_preview_is_safe(preview):
        detail = _notebook_import_blocking_detail(preview.get("preflight", {}))
        _emit_streamlit_message("error", f"Notebook import is blocked: {detail}")
        return None
    try:
        stages_file = Path(module_dir) / toml_file_name
        return write_notebook_import_preview(
            preview,
            module_dir,
            stages_file,
            view_manifest_dir=view_manifest_dir,
        )
    except (OSError, TypeError, ValueError) as e:
        _emit_streamlit_message("error", f"Failed to save TOML file: {e}")
        logger.error(
            "Error writing TOML in notebook_to_toml: %s",
            bound_log_value(e, LOG_DETAIL_LIMIT),
        )
        return None


def on_preview_notebook_import(
    key: str,
    module_dir: Path,
    index_page: str,
    view_manifest_dir: Path | None = None,
) -> None:
    """Build a notebook import preview from the sidebar uploader without writing files."""
    uploaded_file = st.session_state.get(key)
    preview_key = _notebook_import_preview_key(index_page)
    if not uploaded_file:
        st.session_state.pop(preview_key, None)
        _emit_streamlit_message("error", "No notebook file was uploaded.")
        return
    if not _is_uploaded_notebook(uploaded_file):
        st.session_state.pop(preview_key, None)
        return

    preview = build_notebook_import_preview(uploaded_file, module_dir)
    if preview is None:
        st.session_state.pop(preview_key, None)
        return
    st.session_state[preview_key] = preview
    preflight = preview.get("preflight", {})
    summary = preflight.get("summary", {}) if isinstance(preflight, dict) else {}
    _emit_streamlit_message(
        "info",
        (
            "Notebook import preview ready: "
            f"{int(summary.get('pipeline_stage_count', 0) or 0)} stage(s), "
            f"{int(summary.get('input_count', 0) or 0)} input(s), "
            f"{int(summary.get('output_count', 0) or 0)} output(s)."
        ),
    )


def confirm_notebook_import_preview(
    module_dir: Path,
    stages_file: Path,
    index_page: str,
    *,
    view_manifest_dir: Path | None = None,
    selected_stage_ids: Iterable[str] | None = None,
) -> int:
    """Persist the current notebook import preview and update editor state."""
    preview_key = _notebook_import_preview_key(index_page)
    preview = st.session_state.get(preview_key)
    if not isinstance(preview, dict):
        _emit_streamlit_message("error", "No notebook import preview is available.")
        return 0
    preview_to_write = _selected_notebook_import_preview(preview, selected_stage_ids)
    if not _notebook_import_preview_is_safe(preview):
        detail = _notebook_import_blocking_detail(preview.get("preflight", {}))
        _emit_streamlit_message("error", f"Notebook import is blocked: {detail}")
        return 0
    if not _notebook_import_preview_is_safe(preview_to_write):
        detail = _notebook_import_blocking_detail(preview_to_write.get("preflight", {}))
        _emit_streamlit_message("error", f"Notebook cell promotion is blocked: {detail}")
        return 0
    try:
        cell_count = write_notebook_import_preview(
            preview_to_write,
            module_dir,
            stages_file,
            view_manifest_dir=view_manifest_dir,
        )
    except (OSError, TypeError, ValueError) as exc:
        _emit_streamlit_message("error", f"Failed to save notebook import preview: {exc}")
        logger.error(
            "Error writing notebook import preview: %s",
            bound_log_value(exc, LOG_DETAIL_LIMIT),
        )
        return 0

    selected_ids = [
        str(stage_id)
        for stage_id in (selected_stage_ids or [])
        if str(stage_id) and str(stage_id) != NOTEBOOK_IMPORT_ALL_STAGES
    ]
    if selected_ids and cell_count > 0:
        _emit_streamlit_message(
            "success",
            f"Promoted notebook cell {', '.join(selected_ids)} to AGILAB stage.",
        )
    elif cell_count > 0:
        _emit_streamlit_message("success", f"Imported {cell_count} notebook code cell(s).")
    else:
        _emit_streamlit_message("warning", "Notebook imported, but no code cells were found.")
    if index_page in st.session_state and isinstance(st.session_state[index_page], list):
        st.session_state[index_page][-1] = cell_count
    st.session_state.page_broken = True
    st.session_state.pop(preview_key, None)
    _bump_history_revision()
    return cell_count


def cancel_notebook_import_preview(index_page: str) -> None:
    """Discard the current notebook import preview."""
    st.session_state.pop(_notebook_import_preview_key(index_page), None)


def render_notebook_import_preview(
    module_dir: Path,
    stages_file: Path,
    index_page: str,
    *,
    view_manifest_dir: Path | None = None,
) -> None:
    """Render confirm/cancel controls for the current notebook import preview."""
    preview = st.session_state.get(_notebook_import_preview_key(index_page))
    if not isinstance(preview, dict):
        return
    preflight = preview.get("preflight", {})
    summary = preflight.get("summary", {}) if isinstance(preflight, dict) else {}
    risk_counts = preflight.get("risk_counts", {}) if isinstance(preflight, dict) else {}
    sidebar = getattr(st, "sidebar", st)
    caption = getattr(sidebar, "caption", None)
    if callable(caption):
        caption(
            "Notebook preview: "
            f"{int(summary.get('pipeline_stage_count', 0) or 0)} stage(s), "
            f"{int(summary.get('input_count', 0) or 0)} input(s), "
            f"{int(summary.get('output_count', 0) or 0)} output(s), "
            f"{int(risk_counts.get('warning', 0) or 0)} warning(s)."
        )
    if not _notebook_import_preview_is_safe(preview):
        error = getattr(sidebar, "error", None)
        if callable(error):
            error(f"Notebook import blocked: {_notebook_import_blocking_detail(preflight)}")
    button = getattr(sidebar, "button", None)
    if not callable(button):
        return
    selected_stage_ids: list[str] | None = None
    if _notebook_import_preview_is_safe(preview):
        stage_options = _notebook_import_stage_options(preview)
        selectbox = getattr(sidebar, "selectbox", None)
        if stage_options and callable(selectbox):
            all_label = "All runnable cells"
            labels = [all_label, *[str(option["label"]) for option in stage_options]]
            selected_label = selectbox(
                "Notebook cell to promote",
                labels,
                key=f"{index_page}__notebook_import_stage",
                help=(
                    "Choose one notebook cell when you want a focused AGILAB stage, "
                    "or keep all cells for the full import."
                ),
            )
            if selected_label != all_label:
                selected_option = next(
                    (
                        option
                        for option in stage_options
                        if str(option.get("label", "")) == str(selected_label)
                    ),
                    None,
                )
                if selected_option is not None:
                    selected_stage_ids = [str(selected_option["id"])]
                    if callable(caption):
                        caption(_notebook_import_stage_detail(selected_option["stage"]))
    import_label = "Promote selected cell" if selected_stage_ids else "Import preview"
    if _notebook_import_preview_is_safe(preview) and button(
        import_label,
        key=f"{index_page}__confirm_notebook_import",
    ):
        confirm_notebook_import_preview(
            module_dir,
            stages_file,
            index_page,
            view_manifest_dir=view_manifest_dir,
            selected_stage_ids=selected_stage_ids,
        )
    if button("Cancel import", key=f"{index_page}__cancel_notebook_import"):
        cancel_notebook_import_preview(index_page)


def refresh_notebook_export(
    stages_file: Path,
    export_context: Any | None = None,
) -> Path | None:
    """Rebuild the notebook export for a given stage contract and return its path."""
    if not stages_file.exists():
        return None
    try:
        with open(stages_file, "rb") as f:
            stages = tomllib.load(f)
    except (OSError, TypeError, tomllib.TOMLDecodeError) as exc:
        _emit_streamlit_message(
            "error",
            f"Unable to export notebook: failed to load {stages_file}: {exc}",
        )
        logger.error("Unable to load stage contract %s for notebook export: %s", stages_file, exc)
        return None
    toml_to_notebook(stages, stages_file, export_context=export_context)
    return stages_file.with_suffix(".ipynb")


def on_import_notebook(
    key: str,
    module_dir: Path,
    stages_file: Path,
    index_page: str,
) -> None:
    """Handle notebook file import via sidebar uploader."""
    uploaded_file = st.session_state.get(key)
    if not uploaded_file:
        _emit_streamlit_message("error", "No notebook file was uploaded.")
        return
    if not _is_uploaded_notebook(uploaded_file):
        return

    cell_count = notebook_to_toml(
        uploaded_file,
        stages_file.name,
        module_dir,
    )
    if cell_count is None:
        return
    if cell_count > 0:
        _emit_streamlit_message("success", f"Imported {cell_count} notebook code cell(s).")
    else:
        _emit_streamlit_message("warning", "Notebook imported, but no code cells were found.")

    if index_page in st.session_state and isinstance(st.session_state[index_page], list):
        st.session_state[index_page][-1] = cell_count
    st.session_state.page_broken = True

def display_history_tab(stages_file: Path, module_path: Path) -> None:
    """Display the HISTORY tab with code editor for the stage contract."""
    if stages_file.exists():
        with open(stages_file, "rb") as f:
            raw_data = tomllib.load(f)
        cleaned: Dict[str, List[Dict[str, Any]]] = {}
        for mod, entries in raw_data.items():
            if isinstance(entries, list):
                filtered = [entry for entry in entries if _is_displayable_stage(entry)]
                if filtered:
                    cleaned[mod] = filtered
        code = json.dumps(cleaned, indent=2)
    else:
        code = "{}"
    history_rev = st.session_state.get("history_rev", 0)
    action_on_stages = code_editor(
        code,
        height=min(30, len(code)),
        theme="contrast",
        buttons=normalize_custom_buttons(get_custom_buttons()),
        info=get_info_bar(),
        component_props=get_css_text(),
        props={"style": {"borderRadius": "0px 0px 8px 8px"}},
        key=f"stages_{module_path}_{history_rev}",
    )
    if action_on_stages["type"] == "save":
        try:
            data = json.loads(action_on_stages["text"] or "{}")
            cleaned: Dict[str, List[Dict[str, Any]]] = {}
            for mod, entries in data.items():
                if isinstance(entries, list):
                    filtered = [entry for entry in entries if _is_displayable_stage(entry)]
                    if filtered:
                        cleaned[mod] = filtered
            with open(stages_file, "wb") as f:
                tomli_w.dump(convert_paths_to_strings(_prepare_lab_stages_for_write(cleaned)), f)
            _bump_history_revision()
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as e:
            st.error(f"Failed to save stage contract from editor: {e}")
            logger.error(
                "Error saving stage contract from editor: %s",
                bound_log_value(e, LOG_DETAIL_LIMIT),
            )
