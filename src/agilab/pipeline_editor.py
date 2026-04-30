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

_pipeline_steps_module = import_agilab_module(
    "agilab.pipeline_steps",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "pipeline_steps.py",
    fallback_name="agilab_pipeline_steps_fallback",
)
_bump_history_revision = _pipeline_steps_module.bump_history_revision
_ensure_primary_module_key = _pipeline_steps_module.ensure_primary_module_key
_prepare_lab_steps_for_write = _pipeline_steps_module.prepare_lab_steps_for_write
_is_displayable_step = _pipeline_steps_module.is_displayable_step
_looks_like_step = _pipeline_steps_module.looks_like_step
_module_keys = _pipeline_steps_module.module_keys
normalize_runtime_path = _pipeline_steps_module.normalize_runtime_path
_persist_sequence_preferences = _pipeline_steps_module.persist_sequence_preferences
_prune_invalid_entries = _pipeline_steps_module.prune_invalid_entries

_pipeline_step_templates_module = import_agilab_module(
    "agilab.pipeline_step_templates",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "pipeline_step_templates.py",
    fallback_name="agilab_pipeline_step_templates_fallback",
)
PIPELINE_STEP_TEMPLATE_ID_KEY = _pipeline_step_templates_module.PIPELINE_STEP_TEMPLATE_ID_KEY
PIPELINE_STEP_TEMPLATE_VERSION_KEY = _pipeline_step_templates_module.PIPELINE_STEP_TEMPLATE_VERSION_KEY

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
build_lab_steps_preview = _notebook_pipeline_import_module.build_lab_steps_preview
build_notebook_import_preflight = _notebook_pipeline_import_module.build_notebook_import_preflight
build_notebook_pipeline_import = _notebook_pipeline_import_module.build_notebook_pipeline_import
write_notebook_import_contract = _notebook_pipeline_import_module.write_notebook_import_contract

logger = logging.getLogger(__name__)


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


def _emit_notebook_preflight_result(preflight: Dict[str, Any], contract_path: Path) -> None:
    summary = preflight.get("summary", {}) if isinstance(preflight, dict) else {}
    risk_counts = preflight.get("risk_counts", {}) if isinstance(preflight, dict) else {}
    status = str(preflight.get("status", "ready") if isinstance(preflight, dict) else "ready")
    warning_count = int(risk_counts.get("warning", 0) or 0)
    error_count = int(risk_counts.get("error", 0) or 0)
    message = (
        f"Notebook import preflight: {status}; "
        f"{int(summary.get('pipeline_step_count', 0) or 0)} step(s), "
        f"{int(summary.get('input_count', 0) or 0)} input(s), "
        f"{int(summary.get('output_count', 0) or 0)} output(s). "
        f"Contract: {contract_path.name}"
    )
    if error_count:
        _emit_streamlit_message("error", message)
    elif warning_count:
        _emit_streamlit_message("warning", message)
    else:
        _emit_streamlit_message("info", message)


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


def get_steps_list(module: Path, steps_file: Path) -> List[Any]:
    """Get the list of steps for a module from a TOML file."""
    module_path = Path(module)
    try:
        with open(steps_file, "rb") as f:
            steps = tomllib.load(f)
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        return []

    for key in _module_keys(module_path):
        entries = steps.get(key)
        if isinstance(entries, list):
            return entries
    return []


def get_steps_dict(module: Path, steps_file: Path) -> Dict[str, Any]:
    """Get the steps dictionary from a TOML file."""
    module_path = Path(module)
    try:
        with open(steps_file, "rb") as f:
            steps = tomllib.load(f)
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        steps = {}
    else:
        keys = _module_keys(module_path)
        primary = keys[0]
        for alt_key in keys[1:]:
            if alt_key != primary:
                steps.pop(alt_key, None)
    return steps


def remove_step(
    module: Path,
    step: str,
    steps_file: Path,
    index_page: str,
) -> int:
    """Remove a step from the steps file."""
    module_path = Path(module)
    steps = get_steps_dict(module_path, steps_file)
    module_keys = _module_keys(module_path)
    module_key = next((key for key in module_keys if key in steps), module_keys[0])
    steps.setdefault(module_key, [])
    nsteps = len(steps.get(module_key, []))
    index_step = int(step)
    details_key = f"{index_page}__details"
    details_store = st.session_state.setdefault(details_key, {})
    venv_key = f"{index_page}__venv_map"
    venv_store = st.session_state.setdefault(venv_key, {})
    engine_key = f"{index_page}__engine_map"
    engine_store = st.session_state.setdefault(engine_key, {})
    sequence_key = f"{index_page}__run_sequence"
    sequence_store = st.session_state.setdefault(sequence_key, list(range(nsteps)))
    if 0 <= index_step < nsteps:
        del steps[module_key][index_step]
        nsteps -= 1
        st.session_state[index_page][0] = max(0, nsteps - 1)
        st.session_state[index_page][-1] = nsteps
        shifted: Dict[int, str] = {}
        vshifted: Dict[int, str] = {}
        eshifted: Dict[int, str] = {}
        for idx, text in details_store.items():
            if idx < index_step:
                shifted[idx] = text
            elif idx > index_step:
                shifted[idx - 1] = text
        st.session_state[details_key] = shifted
        for idx, path in venv_store.items():
            if idx < index_step:
                vshifted[idx] = path
            elif idx > index_step:
                vshifted[idx - 1] = path
        st.session_state[venv_key] = vshifted
        for idx, engine in engine_store.items():
            if idx < index_step:
                eshifted[idx] = engine
            elif idx > index_step:
                eshifted[idx - 1] = engine
        st.session_state[engine_key] = eshifted
        new_sequence: List[int] = []
        for idx in sequence_store:
            if idx == index_step:
                continue
            new_idx = idx - 1 if idx > index_step else idx
            if 0 <= new_idx < nsteps and new_idx not in new_sequence:
                new_sequence.append(new_idx)
        if nsteps > 0 and not new_sequence:
            new_sequence = list(range(nsteps))
        st.session_state[sequence_key] = new_sequence
    else:
        st.session_state[index_page][0] = 0
        st.session_state[venv_key] = venv_store
        st.session_state[engine_key] = engine_store
        st.session_state[sequence_key] = [idx for idx in sequence_store if idx < nsteps]

    steps[module_key] = _prune_invalid_entries(steps[module_key])
    nsteps = len(steps[module_key])
    st.session_state[index_page][-1] = nsteps
    current_sequence = st.session_state.get(sequence_key, [])
    _persist_sequence_preferences(module_path, steps_file, current_sequence)

    try:
        serializable_steps = convert_paths_to_strings(_prepare_lab_steps_for_write(steps))
        with open(steps_file, "wb") as f:
            tomli_w.dump(serializable_steps, f)
    except (OSError, TypeError, ValueError) as e:
        st.error(f"Failed to save steps file: {e}")
        logger.error(
            "Error writing TOML in remove_step: %s",
            bound_log_value(e, LOG_DETAIL_LIMIT),
        )

    _bump_history_revision()
    return nsteps


def _normalize_pipeline_step_entry(raw_entry: Any) -> Dict[str, Any] | None:
    """Normalize core editor fields while preserving versioned step metadata."""
    if not isinstance(raw_entry, dict):
        return None

    normalized = dict(raw_entry)
    normalized["D"] = raw_entry.get("D", "")
    normalized["Q"] = raw_entry.get("Q", "")
    normalized["M"] = raw_entry.get("M", "")
    normalized["C"] = raw_entry.get("C", "")
    normalized["E"] = normalize_runtime_path(raw_entry.get("E", "")) if raw_entry.get("E") else ""
    normalized["R"] = str(raw_entry.get("R", "") or "")

    for key in (PIPELINE_STEP_TEMPLATE_ID_KEY, PIPELINE_STEP_TEMPLATE_VERSION_KEY):
        if key in raw_entry:
            normalized[key] = raw_entry[key]
    return normalized


def _write_steps_for_module(
    module: Path,
    steps_file: Path,
    module_steps: List[Dict[str, Any]],
) -> int:
    """Overwrite the module step list in ``steps_file`` and refresh notebook export."""
    module_path = Path(module)
    steps = get_steps_dict(module_path, steps_file)
    module_key = _module_keys(module_path)[0]

    normalized_steps: List[Dict[str, Any]] = []
    for raw_entry in module_steps:
        normalized_entry = _normalize_pipeline_step_entry(raw_entry)
        if normalized_entry is not None:
            normalized_steps.append(normalized_entry)

    steps[module_key] = _prune_invalid_entries(normalized_steps)
    serializable_steps = convert_paths_to_strings(_prepare_lab_steps_for_write(steps))
    with open(steps_file, "wb") as f:
        tomli_w.dump(serializable_steps, f)
    toml_to_notebook(steps, steps_file)
    return len(steps[module_key])


def _capture_pipeline_snapshot(index_page: str, steps: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Capture the current pipeline state so delete actions can be undone."""
    steps_snapshot: List[Dict[str, Any]] = []
    for raw_entry in steps:
        normalized_entry = _normalize_pipeline_step_entry(raw_entry)
        if normalized_entry is not None:
            steps_snapshot.append(normalized_entry)

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
        if 0 <= idx < len(steps_snapshot):
            details_snapshot[idx] = str(text or "")

    venv_snapshot: Dict[int, str] = {}
    for raw_idx, raw_path in st.session_state.get(venv_key, {}).items():
        try:
            idx = int(raw_idx)
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(steps_snapshot):
            normalized = normalize_runtime_path(raw_path)
            if normalized:
                venv_snapshot[idx] = normalized

    engine_snapshot: Dict[int, str] = {}
    for raw_idx, engine in st.session_state.get(engine_key, {}).items():
        try:
            idx = int(raw_idx)
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(steps_snapshot):
            engine_snapshot[idx] = str(engine or "")

    raw_sequence = st.session_state.get(sequence_key, list(range(len(steps_snapshot))))
    sequence_snapshot: List[int] = []
    for raw_idx in raw_sequence:
        try:
            idx = int(raw_idx)
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(steps_snapshot) and idx not in sequence_snapshot:
            sequence_snapshot.append(idx)
    if len(steps_snapshot) > 0 and not sequence_snapshot:
        sequence_snapshot = list(range(len(steps_snapshot)))

    page_state = st.session_state.get(index_page, [0])
    try:
        active_step = int(page_state[0]) if isinstance(page_state, list) and page_state else 0
    except (TypeError, ValueError):
        active_step = 0

    return {
        "steps": steps_snapshot,
        "details": details_snapshot,
        "venv_map": venv_snapshot,
        "engine_map": engine_snapshot,
        "sequence": sequence_snapshot,
        "active_step": active_step,
        "selected_venv": normalize_runtime_path(st.session_state.get("lab_selected_venv", "")),
        "selected_engine": str(st.session_state.get("lab_selected_engine", "") or ""),
    }


def _reset_pipeline_editor_state(index_page: str) -> None:
    """Drop per-step widget keys so restored snapshots reseed editor state from disk."""
    safe_prefix = index_page.replace("/", "_")
    key_prefixes = (
        f"{safe_prefix}_q_step_",
        f"{safe_prefix}_code_step_",
        f"{safe_prefix}_venv_",
        f"{safe_prefix}_editor_rev_",
        f"{safe_prefix}_pending_q_",
        f"{safe_prefix}_pending_c_",
        f"{safe_prefix}_step_init_",
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
    steps_file: Path,
    index_page: str,
    sequence_widget_key: str,
    snapshot: Dict[str, Any],
) -> Optional[str]:
    """Restore steps and UI state from a previously captured snapshot."""
    try:
        steps_snapshot = snapshot.get("steps", [])
        if not isinstance(steps_snapshot, list):
            steps_snapshot = []
        nsteps = _write_steps_for_module(module_path, steps_file, steps_snapshot)

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
            if 0 <= idx < nsteps:
                details_map[idx] = str(text or "")
        st.session_state[details_key] = details_map

        venv_map: Dict[int, str] = {}
        for raw_idx, raw_path in snapshot.get("venv_map", {}).items():
            try:
                idx = int(raw_idx)
            except (TypeError, ValueError):
                continue
            if 0 <= idx < nsteps:
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
            if 0 <= idx < nsteps:
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
                if 0 <= idx < nsteps and idx not in restored_sequence:
                    restored_sequence.append(idx)
        if nsteps > 0 and not restored_sequence:
            restored_sequence = list(range(nsteps))
        st.session_state[sequence_key] = restored_sequence
        _persist_sequence_preferences(module_path, steps_file, restored_sequence)
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

        if nsteps > 0:
            try:
                active_step = int(snapshot.get("active_step", 0))
            except (TypeError, ValueError):
                active_step = 0
            active_step = max(0, min(active_step, nsteps - 1))
            active_entry = steps_snapshot[active_step] if active_step < len(steps_snapshot) else {}
            if not isinstance(active_entry, dict):
                active_entry = {}
            page_state[0] = active_step
            page_state[1:6] = [
                active_entry.get("D", ""),
                active_entry.get("Q", ""),
                active_entry.get("M", ""),
                active_entry.get("C", ""),
                details_map.get(active_step, ""),
            ]
            restored_selected_venv = normalize_runtime_path(snapshot.get("selected_venv", ""))
            if not restored_selected_venv:
                restored_selected_venv = normalize_runtime_path(venv_map.get(active_step, ""))
            st.session_state["lab_selected_venv"] = (
                restored_selected_venv if _is_valid_runtime_root(restored_selected_venv) else ""
            )
            restored_selected_engine = str(snapshot.get("selected_engine", "") or "")
            if not restored_selected_engine:
                restored_selected_engine = engine_map.get(active_step, "") or (
                    "agi.run" if st.session_state.get("lab_selected_venv") else "runpy"
                )
            st.session_state["lab_selected_engine"] = restored_selected_engine
        else:
            page_state[:] = [0, "", "", "", "", "", 0]
            st.session_state["lab_selected_venv"] = ""
            st.session_state["lab_selected_engine"] = "runpy"

        page_state[-1] = nsteps
        _bump_history_revision()
        return None
    except (AttributeError, IndexError, KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
        logger.error(
            "Undo restore failed for %s: %s",
            bound_log_value(steps_file, LOG_PATH_LIMIT),
            bound_log_value(exc, LOG_DETAIL_LIMIT),
        )
        return str(exc)


def resolve_pycharm_notebook_path(
    steps_file: Path,
    export_context: Any | None = None,
) -> Path | None:
    """Return the repo-local PyCharm notebook path when a source checkout is available."""
    mirror_path = str(pycharm_notebook_mirror_path(steps_file, export_context=export_context) or "").strip()
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
    """Convert TOML steps data to a Jupyter notebook file."""
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
    steps_file: Path,
    index_page: str,
) -> None:
    """Save the query to the steps file if valid."""
    module_path = Path(module)
    if is_query_valid(query):
        venv_map = st.session_state.get(f"{index_page}__venv_map", {})
        engine_map = st.session_state.get(f"{index_page}__engine_map", {})
        # Persist only D, Q, M, and C
        query[-1], _ = save_step(
            module_path,
            query[1:5],
            query[0],
            query[-1],
            steps_file,
            venv_map=venv_map,
            engine_map=engine_map,
        )
        _bump_history_revision()
    export_df()


def save_step(
    module: Path,
    query: List[Any],
    current_step: int,
    nsteps: int,
    steps_file: Path,
    venv_map: Optional[Dict[int, str]] = None,
    engine_map: Optional[Dict[int, str]] = None,
    extra_fields: Optional[Dict[str, Any]] = None,
) -> Tuple[int, Dict[str, Any]]:
    """Save a step in the steps file."""
    st.session_state["_experiment_last_save_skipped"] = False
    module_path = Path(module)
    # Normalize types
    try:
        nsteps = int(nsteps)
    except (TypeError, ValueError):
        nsteps = 0
    try:
        index_step = int(current_step)
    except (TypeError, ValueError):
        index_step = 0
    if steps_file.exists():
        with open(steps_file, "rb") as f:
            steps = tomllib.load(f)
    else:
        os.makedirs(steps_file.parent, exist_ok=True)
        steps = {}

    module_keys = _module_keys(module_path)
    module_str = module_keys[0]
    steps.setdefault(module_str, [])
    for alt_key in module_keys[1:]:
        if alt_key in steps:
            alt_entries = steps.pop(alt_key)
            if not steps[module_str] or len(alt_entries) > len(steps[module_str]):
                steps[module_str] = alt_entries

    # Capture any existing entry so we can preserve values when maps aren't provided
    existing_entry: Dict[str, Any] = {}
    if 0 <= index_step < len(steps[module_str]):
        current_entry = steps[module_str][index_step]
        if isinstance(current_entry, dict):
            existing_entry = current_entry

    # Persist D, Q, M, and C (+ E/R when provided). Preserve existing metadata
    # fields (for locked snippets and future extension keys).
    # - [D, Q, M, C]
    # - [step, D, Q, M, C, ...]
    if len(query) >= 5 and _looks_like_step(query[0]):
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
            entry["E"] = normalize_runtime_path(venv_map.get(index_step, ""))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            entry["E"] = ""
    elif "E" in existing_entry:
        entry["E"] = normalize_runtime_path(existing_entry.get("E", ""))

    if engine_map is not None:
        try:
            entry["R"] = str(engine_map.get(index_step, "") or "")
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

    nsteps_saved = len(steps[module_str])
    nsteps = max(int(nsteps), nsteps_saved)

    if index_step < nsteps_saved:
        steps[module_str][index_step] = entry
    else:
        steps[module_str].append(entry)

    steps[module_str] = _prune_invalid_entries(steps[module_str], keep_index=index_step)
    nsteps = len(steps[module_str])

    try:
        serializable_steps = convert_paths_to_strings(_prepare_lab_steps_for_write(steps))
        with open(steps_file, "wb") as f:
            tomli_w.dump(serializable_steps, f)
    except (OSError, TypeError, ValueError) as e:
        st.error(f"Failed to save steps file: {e}")
        logger.error(
            "Error writing TOML in save_step: %s",
            bound_log_value(e, LOG_DETAIL_LIMIT),
        )
        st.session_state["_experiment_last_save_skipped"] = True
        return nsteps, entry

    toml_to_notebook(steps, steps_file)
    return nsteps, entry


def _force_persist_step(
    module_path: Path,
    steps_file: Path,
    step_idx: int,
    entry: Dict[str, Any],
) -> None:
    """Ensure the given entry is written to steps_file at step_idx."""
    try:
        module_key = _module_keys(module_path)[0]
        steps: Dict[str, Any] = {}
        if steps_file.exists():
            with open(steps_file, "rb") as f:
                steps = tomllib.load(f)
        steps.setdefault(module_key, [])
        while len(steps[module_key]) <= step_idx:
            steps[module_key].append({})
        current = steps[module_key][step_idx]
        merged = dict(current) if isinstance(current, dict) else {}
        merged.update(convert_paths_to_strings(entry))
        steps[module_key][step_idx] = merged
        steps_file.parent.mkdir(parents=True, exist_ok=True)
        with open(steps_file, "wb") as f:
            tomli_w.dump(convert_paths_to_strings(_prepare_lab_steps_for_write(steps)), f)
    except (OSError, TypeError, ValueError, tomllib.TOMLDecodeError) as exc:
        logger.error(
            "Force persist failed for step %s -> %s: %s",
            step_idx,
            bound_log_value(steps_file, LOG_PATH_LIMIT),
            bound_log_value(exc, LOG_DETAIL_LIMIT),
        )

def notebook_to_toml(
    uploaded_file: Any,
    toml_file_name: str,
    module_dir: Path,
) -> int:
    """Convert uploaded Jupyter notebook file to a TOML file."""
    if not uploaded_file:
        _emit_streamlit_message("error", "No uploaded notebook provided.")
        return 0
    if not _is_uploaded_notebook(uploaded_file):
        _emit_streamlit_message("error", "Please upload a .ipynb file.")
        return 0
    toml_path = Path(module_dir) / toml_file_name
    toml_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        file_content = _read_uploaded_text(uploaded_file)
        notebook_content = json.loads(file_content)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        _emit_streamlit_message("error", f"Unable to parse notebook: {exc}")
        return 0
    if not isinstance(notebook_content, dict):
        _emit_streamlit_message("error", "Invalid notebook format: expected a JSON object.")
        return 0
    module = module_dir.name
    if not module:
        module = "lab_steps"
    source_name = str(getattr(uploaded_file, "name", "") or "uploaded.ipynb")
    notebook_import = build_notebook_pipeline_import(
        notebook=notebook_content,
        source_notebook=source_name,
    )
    preflight = build_notebook_import_preflight(notebook_import)
    toml_content = build_lab_steps_preview(notebook_import, module_name=module)
    cell_count = int(notebook_import.get("summary", {}).get("pipeline_step_count", 0) or 0)
    try:
        with open(toml_path, "wb") as toml_file:
            tomli_w.dump(convert_paths_to_strings(_prepare_lab_steps_for_write(toml_content)), toml_file)
    except (OSError, TypeError, ValueError) as e:
        _emit_streamlit_message("error", f"Failed to save TOML file: {e}")
        logger.error(
            "Error writing TOML in notebook_to_toml: %s",
            bound_log_value(e, LOG_DETAIL_LIMIT),
        )
        return cell_count
    contract_path = Path(module_dir) / "notebook_import_contract.json"
    try:
        write_notebook_import_contract(
            contract_path,
            notebook_import,
            preflight=preflight,
            module_name=module,
        )
        _emit_notebook_preflight_result(preflight, contract_path)
    except (OSError, TypeError, ValueError) as exc:
        _emit_streamlit_message("warning", f"Unable to save notebook import contract: {exc}")
        logger.warning(
            "Unable to save notebook import contract in notebook_to_toml: %s",
            bound_log_value(exc, LOG_DETAIL_LIMIT),
        )
    return cell_count


def refresh_notebook_export(
    steps_file: Path,
    export_context: Any | None = None,
) -> Path | None:
    """Rebuild the notebook export for a given steps file and return its path."""
    if not steps_file.exists():
        return None
    try:
        with open(steps_file, "rb") as f:
            steps = tomllib.load(f)
    except (OSError, TypeError, tomllib.TOMLDecodeError) as exc:
        _emit_streamlit_message(
            "error",
            f"Unable to export notebook: failed to load {steps_file}: {exc}",
        )
        logger.error("Unable to load steps file %s for notebook export: %s", steps_file, exc)
        return None
    toml_to_notebook(steps, steps_file, export_context=export_context)
    return steps_file.with_suffix(".ipynb")


def on_import_notebook(
    key: str,
    module_dir: Path,
    steps_file: Path,
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
        steps_file.name,
        module_dir,
    )
    if cell_count > 0:
        _emit_streamlit_message("success", f"Imported {cell_count} notebook code cell(s).")
    elif cell_count == 0:
        _emit_streamlit_message("warning", "Notebook imported, but no code cells were found.")

    if index_page in st.session_state and isinstance(st.session_state[index_page], list):
        st.session_state[index_page][-1] = cell_count
    st.session_state.page_broken = True

def display_history_tab(steps_file: Path, module_path: Path) -> None:
    """Display the HISTORY tab with code editor for steps file."""
    if steps_file.exists():
        with open(steps_file, "rb") as f:
            raw_data = tomllib.load(f)
        cleaned: Dict[str, List[Dict[str, Any]]] = {}
        for mod, entries in raw_data.items():
            if isinstance(entries, list):
                filtered = [entry for entry in entries if _is_displayable_step(entry)]
                if filtered:
                    cleaned[mod] = filtered
        code = json.dumps(cleaned, indent=2)
    else:
        code = "{}"
    history_rev = st.session_state.get("history_rev", 0)
    action_onsteps = code_editor(
        code,
        height=min(30, len(code)),
        theme="contrast",
        buttons=normalize_custom_buttons(get_custom_buttons()),
        info=get_info_bar(),
        component_props=get_css_text(),
        props={"style": {"borderRadius": "0px 0px 8px 8px"}},
        key=f"steps_{module_path}_{history_rev}",
    )
    if action_onsteps["type"] == "save":
        try:
            data = json.loads(action_onsteps["text"] or "{}")
            cleaned: Dict[str, List[Dict[str, Any]]] = {}
            for mod, entries in data.items():
                if isinstance(entries, list):
                    filtered = [entry for entry in entries if _is_displayable_step(entry)]
                    if filtered:
                        cleaned[mod] = filtered
            with open(steps_file, "wb") as f:
                tomli_w.dump(convert_paths_to_strings(_prepare_lab_steps_for_write(cleaned)), f)
            _bump_history_revision()
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as e:
            st.error(f"Failed to save steps file from editor: {e}")
            logger.error(
                "Error saving steps file from editor: %s",
                bound_log_value(e, LOG_DETAIL_LIMIT),
            )
