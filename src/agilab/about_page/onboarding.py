"""First-proof onboarding helpers for the AGILAB main page."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any, Callable, Dict, List
from urllib.parse import urlencode

import streamlit as st


_IMPORT_GUARD_PATH = Path(__file__).resolve().parents[1] / "import_guard.py"
_IMPORT_GUARD_SPEC = importlib.util.spec_from_file_location(
    "agilab_import_guard_onboarding",
    _IMPORT_GUARD_PATH,
)
if _IMPORT_GUARD_SPEC is None or _IMPORT_GUARD_SPEC.loader is None:
    raise ModuleNotFoundError(f"Unable to load import_guard.py from {_IMPORT_GUARD_PATH}")
_IMPORT_GUARD_MODULE = importlib.util.module_from_spec(_IMPORT_GUARD_SPEC)
_IMPORT_GUARD_SPEC.loader.exec_module(_IMPORT_GUARD_MODULE)
import_agilab_module = _IMPORT_GUARD_MODULE.import_agilab_module

_AGILAB_ROOT = Path(__file__).resolve().parents[1]
_first_proof_wizard_module = import_agilab_module(
    "agilab.first_proof_wizard",
    current_file=__file__,
    fallback_path=_AGILAB_ROOT / "first_proof_wizard.py",
    fallback_name="agilab_first_proof_wizard_onboarding_fallback",
)
FIRST_PROOF_PROJECT = "flight_telemetry_project"
FIRST_PROOF_COMPATIBILITY_SLICE = _first_proof_wizard_module.FIRST_PROOF_RECOMMENDED_LABEL
FIRST_PROOF_HELPER_SCRIPT_PREFIXES = _first_proof_wizard_module.FIRST_PROOF_HELPER_SCRIPT_PREFIXES
FIRST_PROOF_NOTEBOOK_BUTTON = "Create from built-in notebook"
FIRST_PROOF_NOTEBOOK_HINT = (
    "No file to find or upload: AGILAB opens PROJECT with its bundled notebook already selected."
)
FIRST_PROOF_NOTEBOOK_LANE_LABEL = "Notebook import: included sample"
FIRST_PROOF_NOTEBOOK_PROJECT = "flight_telemetry_from_notebook_project"
FIRST_PROOF_NOTEBOOK_AFTER_HINT = (
    f"Then click PROJECT `Create`; it builds `{FIRST_PROOF_NOTEBOOK_PROJECT}`."
)
FIRST_PROOF_NOTEBOOK_RUN_HINT = "After creation, run ORCHESTRATE `INSTALL` and `EXECUTE`."
FIRST_PROOF_NOTEBOOK_QUERY_PARAMS = {"start": "notebook-import"}
FIRST_PROOF_NOTEBOOK_SAMPLE_QUERY_KEY = "sample"
FIRST_PROOF_NOTEBOOK_SAMPLE_QUERY_VALUE = "agilab-first-proof"
FIRST_PROOF_ACTION_QUERY_KEY = "first_proof_action"
FIRST_PROOF_VIEW_MAPS_PATH = (
    _AGILAB_ROOT
    / "apps-pages"
    / "view_maps"
    / "src"
    / "view_maps"
    / "view_maps.py"
)
_FIRST_PROOF_ACTION_CHAR_WIDTH_PX = 7
_FIRST_PROOF_ACTION_TEXT_PADDING_PX = 28
_FIRST_PROOF_ACTION_MIN_COLUMN_WIDTH_PX = 128
_FIRST_PROOF_ACTION_SEPARATOR_WIDTH_PX = 20
_FIRST_PROOF_ACTION_COLUMN_GAP_PX = 16
_MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\([^)]+\)")


def _newcomer_first_proof_content() -> Dict[str, Any]:
    """Return the first-proof onboarding contract shown on the landing page."""
    return _first_proof_wizard_module.newcomer_first_proof_content()


def _newcomer_first_proof_project_path(env: Any) -> Path | None:
    """Return the preferred built-in first-proof app path when available."""
    return _first_proof_wizard_module.newcomer_first_proof_project_path(env)


def _first_proof_output_dir(env: Any) -> Path:
    """Return the log directory used by the built-in first-proof route."""
    return _first_proof_wizard_module.first_proof_output_dir(env)


def _list_first_proof_outputs(output_dir: Path) -> list[Path]:
    """Return evidence-like outputs, excluding seeded AGI helper scripts."""
    return list(_first_proof_wizard_module.list_first_proof_outputs(output_dir))


def _newcomer_first_proof_state(env: Any) -> Dict[str, Any]:
    """Return concrete wizard state for the in-product first-proof path."""
    return _first_proof_wizard_module.newcomer_first_proof_state(env)


def _render_newcomer_first_proof_static() -> None:
    """Render the concise newcomer checklist used by helper tests."""
    content = _newcomer_first_proof_content()
    steps_markdown = "\n".join(
        f"{index}. **{label}**: {detail}"
        for index, (label, detail) in enumerate(content["steps"], start=1)
    )
    success_markdown = "\n".join(f"- {item}" for item in content["success_criteria"])
    st.markdown(
        f"""
**{content["title"]}**

{content["intro"]}

**Follow these steps**

{steps_markdown}

**Success criteria**

{success_markdown}
        """
    )


def _first_proof_progress_rows(state: Dict[str, Any]) -> List[Dict[str, str]]:
    """Return compact first-proof progress rows for the diagnostics expander."""
    active_app = str(state.get("active_app_name") or "none")
    manifest_path = str(state.get("run_manifest_path") or "")
    output_dir = str(state.get("output_dir") or "")

    if not state["project_available"]:
        project_status = "Blocked"
        project_detail = (
            "The built-in flight-telemetry project (`flight_telemetry_project`) is missing from the app list."
        )
    elif state["current_app_matches"]:
        project_status = "Done"
        project_detail = "The built-in flight-telemetry project is selected."
    else:
        project_status = "Next"
        project_detail = f"Active project is `{active_app}`; choose the built-in flight-telemetry project."

    if state["run_manifest_loaded"] or state["run_output_detected"]:
        run_status = "Done"
        run_detail = f"Run evidence found under `{output_dir}`."
    elif state["current_app_matches"]:
        run_status = "Next"
        run_detail = "Go to `ORCHESTRATE`. Click INSTALL, then EXECUTE."
    else:
        run_status = "Waiting"
        run_detail = "Select the built-in flight-telemetry project before running."

    if state["run_manifest_passed"]:
        manifest_status = "Done"
        manifest_detail = f"`{manifest_path}` passes the first-proof checks."
    elif state["run_manifest_loaded"]:
        manifest_status = "Attention"
        manifest_detail = (
            f"`{manifest_path}` is {state['run_manifest_status']}; "
            "use the checklist below."
        )
    else:
        manifest_status = "Waiting"
        manifest_detail = f"Expected at `{manifest_path}`."

    return [
        {"step": "Project selected", "status": project_status, "detail": project_detail},
        {"step": "Run executed", "status": run_status, "detail": run_detail},
        {"step": "Evidence manifest", "status": manifest_status, "detail": manifest_detail},
    ]


def _first_proof_progress_markdown(rows: List[Dict[str, str]]) -> str:
    """Render progress rows as a small Markdown table."""
    def _cell(value: str) -> str:
        return value.replace("|", "\\|").replace("\n", " ")

    table = ["| Stage | Status | Detail |", "| --- | --- | --- |"]
    table.extend(
        (
            f"| {_cell(row['step'])} | {_cell(row['status'])} | "
            f"{_cell(row['detail'])} |"
        )
        for row in rows
    )
    return "\n".join(table)


def _first_proof_next_action_model(state: Dict[str, Any]) -> Dict[str, str]:
    """Return first-proof microcopy for the next visible user action."""
    active_app = str(state.get("active_app_name") or "none")
    next_step = str(state.get("next_step") or "").strip()
    if not state["project_available"]:
        return {
            "tone": "attention",
            "phase": "Fix setup",
            "title": "Restore the built-in flight-telemetry project",
            "detail": (
                next_step
                or "The built-in flight-telemetry project (`flight_telemetry_project`) is missing from the app list."
            ),
            "cta_label": "Open troubleshooting",
            "proof_hint": "The built-in flight-telemetry project must exist before the first proof can run.",
        }
    if not state["current_app_matches"]:
        return {
            "tone": "next",
            "phase": "Next action",
            "title": "Start with the known demo project",
            "detail": (
                f"You are on `{active_app}`. Select `flight_telemetry_project` first, "
                "so any failure is an AGILAB setup issue rather than custom app code."
            ),
            "cta_label": "Select demo",
            "proof_hint": "Known data, known path, no cluster or service mode.",
        }
    if state["run_manifest_passed"]:
        return {
            "tone": "done",
            "phase": "Proof complete",
            "title": "First proof is green",
            "detail": "The manifest passes. Keep it as evidence before trying another demo.",
            "cta_label": "Try another demo",
            "proof_hint": "`run_manifest.json` is valid for the first-proof route.",
        }
    if state["run_manifest_loaded"] or state["run_output_detected"]:
        return {
            "tone": "attention",
            "phase": "Needs evidence",
            "title": "Finish or inspect the evidence",
            "detail": next_step or "Generate or repair `run_manifest.json` before moving on.",
            "cta_label": "Check proof details",
            "proof_hint": "Done when `run_manifest.json` passes the compatibility checks.",
        }
    return {
        "tone": "next",
        "phase": "Next action",
        "title": "Run the demo once",
        "detail": "Open `ORCHESTRATE`; keep cluster, benchmark, and service mode off; click `INSTALL`, then `EXECUTE`.",
        "cta_label": "Open run page",
        "proof_hint": "Done when ANALYSIS opens and `run_manifest.json` is written.",
    }


def _first_proof_wizard_steps(state: Dict[str, Any]) -> List[Dict[str, str]]:
    """Return clickable wizard steps for the newcomer proof path."""
    return [
        {
            "id": "install",
            "button": "1. INSTALL demo",
            "hint": "Runs ORCHESTRATE `INSTALL` for `flight_telemetry_project`.",
        },
        {
            "id": "run",
            "button": "2. EXECUTE demo",
            "hint": "Runs ORCHESTRATE `EXECUTE` for the same demo.",
        },
        {
            "id": "analysis",
            "button": "3. OPEN ANALYSIS",
            "hint": "Opens ANALYSIS on `view_maps` for the generated evidence.",
        },
    ]


def _first_proof_page_url(page_name: str, query_params: Dict[str, str] | None = None) -> str:
    """Build a relative Streamlit navigation URL for first-proof links."""
    query = urlencode(query_params or {})
    suffix = f"?{query}" if query else ""
    return f"/{page_name}{suffix}"


def _first_proof_analysis_view_maps_url() -> str:
    """Return an ANALYSIS URL that opens the built-in view_maps page directly."""
    return _first_proof_page_url(
        "ANALYSIS",
        {
            "active_app": FIRST_PROOF_PROJECT,
            "current_page": str(FIRST_PROOF_VIEW_MAPS_PATH.resolve(strict=False)),
        },
    )


def _first_proof_orchestrate_action_url(action_id: str) -> str:
    """Return an ORCHESTRATE URL carrying a one-shot first-proof action."""
    return _first_proof_page_url(
        "ORCHESTRATE",
        {
            "active_app": FIRST_PROOF_PROJECT,
            FIRST_PROOF_ACTION_QUERY_KEY: action_id,
        },
    )


def _first_proof_action_url(action_id: str) -> str:
    """Return the new-tab URL for a first-proof wizard action."""
    if action_id in {"install", "run"}:
        return _first_proof_orchestrate_action_url(action_id)
    if action_id == "analysis":
        return _first_proof_analysis_view_maps_url()
    return _first_proof_page_url("PROJECT", {"active_app": FIRST_PROOF_PROJECT})


def _first_proof_visible_text_length(text: str) -> int:
    """Return the approximate visible character count for compact layout sizing."""
    visible_text = _MARKDOWN_LINK_PATTERN.sub(r"\1", text)
    return len(visible_text.replace("`", ""))


def _first_proof_text_column_width_px(texts: List[str]) -> int:
    """Estimate the minimum readable pixel width for a column of short labels."""
    max_chars = max((_first_proof_visible_text_length(text) for text in texts), default=0)
    return max(
        _FIRST_PROOF_ACTION_MIN_COLUMN_WIDTH_PX,
        (max_chars * _FIRST_PROOF_ACTION_CHAR_WIDTH_PX)
        + _FIRST_PROOF_ACTION_TEXT_PADDING_PX,
    )


def _first_proof_action_columns_layout(
    proof_actions: List[Dict[str, str]],
    *,
    notebook_hint: str = FIRST_PROOF_NOTEBOOK_HINT,
) -> tuple[List[int], int]:
    """Return content-sized Streamlit column weights and total pixel width."""
    proof_texts = [
        text
        for action in proof_actions
        for text in (str(action["button"]), str(action["hint"]))
    ]
    proof_width = _first_proof_text_column_width_px(proof_texts)
    notebook_width = _first_proof_text_column_width_px(
        [
            FIRST_PROOF_NOTEBOOK_BUTTON,
            FIRST_PROOF_NOTEBOOK_LANE_LABEL,
            notebook_hint,
            FIRST_PROOF_NOTEBOOK_AFTER_HINT,
            FIRST_PROOF_NOTEBOOK_RUN_HINT,
        ]
    )
    spec = [proof_width, _FIRST_PROOF_ACTION_SEPARATOR_WIDTH_PX, notebook_width]
    total_width = sum(spec) + (_FIRST_PROOF_ACTION_COLUMN_GAP_PX * (len(spec) - 1))
    return spec, total_width


def _notebook_to_validated_app_project_path(env: Any) -> Path | None:
    """Return the expected project path for the packaged notebook lane."""
    apps_path = getattr(env, "apps_path", None)
    if not apps_path:
        return None
    apps_root = Path(apps_path)
    candidates = [
        apps_root / FIRST_PROOF_NOTEBOOK_PROJECT,
        apps_root / "builtin" / FIRST_PROOF_NOTEBOOK_PROJECT,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _notebook_to_validated_app_rows(env: Any) -> List[Dict[str, str]]:
    """Return the visible proof contract for the notebook-to-app path."""
    project_path = _notebook_to_validated_app_project_path(env)
    project_exists = bool(project_path and project_path.exists())
    project_detail = (
        f"`{FIRST_PROOF_NOTEBOOK_PROJECT}` exists."
        if project_exists
        else f"`{FIRST_PROOF_NOTEBOOK_PROJECT}` will be created."
    )
    return [
        {
            "stage": "Import",
            "status": "Done" if project_exists else "Start",
            "action": f"Click `{FIRST_PROOF_NOTEBOOK_BUTTON}`, then PROJECT `Create`.",
            "proof": project_detail,
        },
        {
            "stage": "Install",
            "status": "Next" if project_exists else "Waiting",
            "action": "Open ORCHESTRATE and click `INSTALL`.",
            "proof": "A project environment and worker environment are prepared.",
        },
        {
            "stage": "Execute",
            "status": "Next" if project_exists else "Waiting",
            "action": "Click ORCHESTRATE `EXECUTE` with cluster and service mode off.",
            "proof": "The imported notebook stages run as an AGILAB app.",
        },
        {
            "stage": "Analyze",
            "status": "Next" if project_exists else "Waiting",
            "action": "Open ANALYSIS and inspect the generated outputs.",
            "proof": "The result is visible outside the original notebook kernel.",
        },
        {
            "stage": "Exit path",
            "status": "Required proof",
            "action": "Open WORKFLOW and click `Download pipeline notebook`.",
            "proof": "`lab_stages.ipynb` can be kept if AGILAB is no longer needed.",
        },
    ]


def _notebook_to_validated_app_markdown(rows: List[Dict[str, str]]) -> str:
    """Render the notebook proof contract as a compact Markdown table."""
    def _cell(value: str) -> str:
        return value.replace("|", "\\|").replace("\n", " ")

    table = ["| Step | Status | Action | Evidence |", "| --- | --- | --- | --- |"]
    table.extend(
        (
            f"| {_cell(row['stage'])} | {_cell(row['status'])} | "
            f"{_cell(row['action'])} | {_cell(row['proof'])} |"
        )
        for row in rows
    )
    return "\n".join(table)


def _first_proof_export_notebook_candidates(env: Any, state: Dict[str, Any]) -> List[Path]:
    """Return project-local notebook export locations that prove a no-lock-in handoff."""
    candidates: List[Path] = []

    def _append_project(project_path: Any) -> None:
        if not project_path:
            return
        candidates.append(Path(project_path) / "notebooks" / "lab_stages.ipynb")

    _append_project(state.get("project_path"))
    _append_project(_notebook_to_validated_app_project_path(env))

    apps_path = getattr(env, "apps_path", None)
    active_app = str(state.get("active_app_name") or getattr(env, "app", "") or "").strip()
    if apps_path and active_app:
        apps_root = Path(apps_path)
        _append_project(apps_root / active_app)
        _append_project(apps_root / "builtin" / active_app)

    unique: List[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def _first_existing_path(paths: List[Path]) -> Path | None:
    """Return the first existing path from a deterministic candidate list."""
    for path in paths:
        if path.exists():
            return path
    return None


def _first_proof_adoption_gate(env: Any, state: Dict[str, Any]) -> Dict[str, str]:
    """Return the visible readiness gate before widening adoption beyond one user."""
    manifest_passed = bool(state.get("run_manifest_passed"))
    outputs_seen = bool(state.get("run_output_detected") or state.get("visible_outputs"))
    export_candidates = _first_proof_export_notebook_candidates(env, state)
    exported_notebook = _first_existing_path(export_candidates)
    expected_export = export_candidates[0] if export_candidates else None

    if manifest_passed and exported_notebook:
        return {
            "status": "Ready for a controlled team trial",
            "action": "Keep the manifest and exported notebook; add secrets, auth/TLS, quotas, and pinning before shared use.",
            "evidence": f"`{state.get('run_manifest_path')}` and `{exported_notebook}`.",
        }
    if manifest_passed:
        expected = f"`{expected_export}`" if expected_export else "`notebooks/lab_stages.ipynb`"
        return {
            "status": "Stay local: export missing",
            "action": "Open WORKFLOW and download the pipeline notebook before handoff.",
            "evidence": f"`run_manifest.json` passed; expected {expected}.",
        }
    if outputs_seen:
        return {
            "status": "Stay local: proof incomplete",
            "action": "Generate a passing `run_manifest.json`, then export `lab_stages.ipynb`.",
            "evidence": "Outputs exist, but no passing first-proof manifest was found.",
        }
    return {
        "status": "Not ready yet",
        "action": "Run one local proof first; keep cluster, service mode, and team sharing for later.",
        "evidence": "No passing first-proof evidence was found.",
    }


def _first_proof_adoption_gate_caption(gate: Dict[str, str]) -> str:
    """Render the adoption gate as one compact onboarding line."""
    return (
        f"Adoption gate: {gate['status']}. "
        f"{gate['action']} Evidence: {gate['evidence']}"
    )


def _first_proof_compatibility_command(state: Dict[str, Any]) -> str:
    """Return the compatibility-report command to attach to a handoff bundle."""
    for command in state.get("evidence_commands", ()):
        if "compatibility_report.py" in str(command):
            return str(command)
    manifest_path = str(state.get("run_manifest_path") or "~/log/execute/flight_telemetry/run_manifest.json")
    return f"python tools/compatibility_report.py --manifest {manifest_path} --compact"


def _first_proof_handoff_bundle_rows(env: Any, state: Dict[str, Any]) -> List[Dict[str, str]]:
    """Return the minimal evidence package to share after a first proof."""
    export_candidates = _first_proof_export_notebook_candidates(env, state)
    exported_notebook = _first_existing_path(export_candidates)
    expected_export = export_candidates[0] if export_candidates else Path("notebooks/lab_stages.ipynb")
    manifest_path = str(state.get("run_manifest_path") or "~/log/execute/flight_telemetry/run_manifest.json")
    manifest_status = "Ready" if state.get("run_manifest_passed") else "Missing or not passing"
    notebook_status = "Ready" if exported_notebook else "Export from WORKFLOW"
    notebook_path = exported_notebook or expected_export
    return [
        {
            "item": "Run proof",
            "status": manifest_status,
            "evidence": f"`{manifest_path}`",
        },
        {
            "item": "No-lock-in notebook",
            "status": notebook_status,
            "evidence": f"`{notebook_path}`",
        },
        {
            "item": "Compatibility report",
            "status": "Run before handoff",
            "evidence": f"`{_first_proof_compatibility_command(state)}`",
        },
        {
            "item": "Local security check",
            "status": "Run before team use",
            "evidence": "`agilab security-check --json --strict`",
        },
    ]


def _first_proof_handoff_bundle_markdown(rows: List[Dict[str, str]]) -> str:
    """Render the adoption handoff bundle as a compact Markdown table."""
    def _cell(value: str) -> str:
        return value.replace("|", "\\|").replace("\n", " ")

    table = ["| Include | Status | Path or command |", "| --- | --- | --- |"]
    table.extend(
        f"| {_cell(row['item'])} | {_cell(row['status'])} | {_cell(row['evidence'])} |"
        for row in rows
    )
    return "\n".join(table)


def _first_proof_handoff_bundle_caption(rows: List[Dict[str, str]]) -> str:
    """Return the one-line visible cue for the portable first-proof package."""
    ready_core = rows[0]["status"] == "Ready" and rows[1]["status"] == "Ready"
    if ready_core:
        return (
            "Handoff bundle: core proof files are ready; attach the compatibility "
            "report and strict security-check output before team sharing."
        )
    return (
        "Handoff bundle: keep the passing run manifest, exported pipeline notebook, "
        "compatibility report, and strict security-check output before team sharing."
    )


def _first_proof_notebook_query_params(env: Any, state: Dict[str, Any]) -> Dict[str, str]:
    """Return query params that open PROJECT on the notebook-import create path."""
    query_params = dict(FIRST_PROOF_NOTEBOOK_QUERY_PARAMS)
    query_params[FIRST_PROOF_NOTEBOOK_SAMPLE_QUERY_KEY] = FIRST_PROOF_NOTEBOOK_SAMPLE_QUERY_VALUE
    active_app = str(state.get("active_app_name") or getattr(env, "app", "") or "").strip()
    if active_app:
        query_params["active_app"] = active_app
    return query_params


def _first_proof_link_button(
    label: str,
    url: str,
    *,
    key: str,
    button_type: str = "secondary",
    disabled: bool = False,
) -> None:
    """Render a first-proof action that opens a new browser tab/session."""
    link_button = getattr(st, "link_button", None)
    if callable(link_button):
        link_button(
            label,
            url,
            key=key,
            type=button_type,
            disabled=disabled,
            help="Opens in a new browser tab.",
            width="content",
        )
        return

    if disabled:
        st.caption(f"{label}: unavailable.")
        return
    st.markdown(f"[{label}]({url})")


def _render_first_proof_wizard_actions(
    env: Any,
    state: Dict[str, Any],
    activate_project: Callable[[Any, Path], bool] | None,
    page_routes: Dict[str, Any] | None,
) -> None:
    """Render executable wizard actions for the first-proof pipeline."""
    st.markdown("**First proof: built-in demo**")
    st.caption(
        "Recommended path: run the built-in flight telemetry demo, then inspect the generated "
        "evidence."
    )
    proof_actions = [
        {
            "id": str(step["id"]),
            "button": str(step["button"]),
            "hint": str(step["hint"]),
            "type": "secondary",
        }
        for step in _first_proof_wizard_steps(state)
    ]
    for column, action in zip(st.columns(len(proof_actions)), proof_actions):
        with column:
            _first_proof_link_button(
                action["button"],
                _first_proof_action_url(action["id"]),
                key=f"first_proof:wizard:{action['id']}",
                button_type=action["type"],
                disabled=not state["project_available"],
            )
            st.caption(action["hint"])

    with st.expander("Notebook-first option", expanded=False):
        st.caption(FIRST_PROOF_NOTEBOOK_LANE_LABEL)
        _first_proof_link_button(
            FIRST_PROOF_NOTEBOOK_BUTTON,
            _first_proof_page_url("PROJECT", _first_proof_notebook_query_params(env, state)),
            key="first_proof:wizard:sample_notebook",
            button_type="secondary",
        )
        st.caption(FIRST_PROOF_NOTEBOOK_HINT)
        st.caption(FIRST_PROOF_NOTEBOOK_AFTER_HINT)
        st.caption(FIRST_PROOF_NOTEBOOK_RUN_HINT)

    with st.expander("Notebook to validated app: full proof", expanded=False):
        st.caption(
            "Use this lane when the starting asset is a notebook and the target is "
            "a reusable app with a no-lock-in handoff."
        )
        st.markdown(_notebook_to_validated_app_markdown(_notebook_to_validated_app_rows(env)))
        st.caption(_first_proof_adoption_gate_caption(_first_proof_adoption_gate(env, state)))
        st.caption(_first_proof_handoff_bundle_caption(_first_proof_handoff_bundle_rows(env, state)))


def _render_first_proof_next_action(
    env: Any,
    state: Dict[str, Any],
    activate_project: Callable[[Any, Path], bool] | None,
) -> None:
    """Render the primary next action before diagnostics."""
    action = _first_proof_next_action_model(state)
    st.markdown("**Next action**")
    if not state["project_available"]:
        st.error(f"Next action: {action['title']} - {action['detail']}")
    elif not state["current_app_matches"]:
        st.warning(f"Next action: {action['title']} - {action['detail']}")
        if st.button(
            action["cta_label"],
            key="first_proof:activate",
            type="primary",
            width="content",
        ):
            if activate_project is not None and activate_project(env, state["project_path"]):
                st.session_state["first_proof_feedback"] = "`flight_telemetry_project` selected."
                st.rerun()
    elif state["run_manifest_passed"]:
        st.success(f"Next action: {action['title']} - {action['detail']}")
    elif state["run_manifest_loaded"] or state["run_output_detected"]:
        st.warning(f"Next action: {action['title']} - {action['detail']}")
    else:
        st.info(f"Next action: {action['title']} - {action['detail']}")


def render_newcomer_first_proof(
    env: Any | None = None,
    *,
    activate_project: Callable[[Any, Path], bool] | None = None,
    display_landing_page: Callable[[Path], None] | None = None,
    page_routes: Dict[str, Any] | None = None,
) -> None:
    """Render the first-proof onboarding surface."""
    if env is None:
        _render_newcomer_first_proof_static()
        return

    state = _newcomer_first_proof_state(env)
    feedback = st.session_state.pop("first_proof_feedback", None)
    if feedback:
        st.success(str(feedback))

    progress_rows = _first_proof_progress_rows(state)
    _render_first_proof_wizard_actions(env, state, activate_project, page_routes)

    if state["visible_outputs"]:
        preview = ", ".join(path.name for path in state["visible_outputs"][:3])
        if len(state["visible_outputs"]) > 3:
            preview += ", ..."
        st.caption(f"Generated files found: {preview}")

    with st.expander("If it fails / proof details", expanded=False):
        st.markdown("**Progress**")
        st.markdown(_first_proof_progress_markdown(progress_rows))
        st.markdown("**Handoff bundle**")
        st.markdown(_first_proof_handoff_bundle_markdown(_first_proof_handoff_bundle_rows(env, state)))
        st.caption(
            "This is review evidence for a controlled team trial; it is not "
            "production, public exposure, or multi-tenant certification."
        )
        st.caption(
            "Validated path: "
            f"{state['recommended_path_label']} "
            f"({state['compatibility_status']}; report: {state['compatibility_report_status']})."
        )
        st.caption(
            "CLI proof command: "
            f"`{state['cli_command']}` "
            f"({', '.join(state['proof_command_labels'])}; "
            f"target <= {state['target_seconds']:.0f}s)."
        )
        if state["run_manifest_loaded"]:
            manifest_summary = state["run_manifest_summary"]
            st.caption(
                "Run manifest: "
                f"`{state['run_manifest_path']}` "
                f"({state['run_manifest_status']}; "
                f"{manifest_summary.get('artifact_count', 0)} artifact refs)."
            )
        else:
            st.caption(f"Run manifest expected at: `{state['run_manifest_path']}`.")

        if state["remediation_status"] == "passed":
            st.caption(state["remediation_title"])
        elif state["remediation_status"] in {"missing", "missing_manifest_with_outputs"}:
            st.info(state["remediation_title"])
        else:
            st.warning(state["remediation_title"])

        st.markdown("**Recovery checklist**")
        st.markdown("\n".join(f"- {item}" for item in state["remediation_actions"]))
        st.markdown("**Evidence commands**")
        st.code("\n".join(state["evidence_commands"]), language="bash")
        if state["run_manifest_validation_rows"] and state["remediation_status"] != "passed":
            validation_preview = "; ".join(
                f"{row['label']}={row['status']}"
                for row in state["run_manifest_validation_rows"]
            )
            st.caption(f"Manifest validations: {validation_preview}")
        st.caption(
            "Evidence links: "
            + " | ".join(
                f"[{label}]({url})"
                for label, url in state["remediation_links"]
            )
        )

    st.divider()
    if display_landing_page is not None:
        display_landing_page(Path(env.st_resources))
