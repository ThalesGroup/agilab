"""First-proof onboarding helpers for the AGILAB main page."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any, Callable, Dict, List
from urllib.parse import urlencode

import streamlit as st
from streamlit.errors import StreamlitAPIException


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
_pending_actions_module = import_agilab_module(
    "agilab.orchestrate_pending_actions",
    current_file=__file__,
    fallback_path=_AGILAB_ROOT / "orchestrate_pending_actions.py",
    fallback_name="agilab_orchestrate_pending_actions_onboarding_fallback",
)
_notebook_import_sample_module = import_agilab_module(
    "agilab.notebook_import_sample",
    current_file=__file__,
    fallback_path=_AGILAB_ROOT / "notebook_import_sample.py",
    fallback_name="agilab_notebook_import_sample_onboarding_fallback",
)

FIRST_PROOF_PROJECT = "flight_telemetry_project"
FIRST_PROOF_COMPATIBILITY_SLICE = _first_proof_wizard_module.FIRST_PROOF_RECOMMENDED_LABEL
FIRST_PROOF_HELPER_SCRIPT_PREFIXES = _first_proof_wizard_module.FIRST_PROOF_HELPER_SCRIPT_PREFIXES
NOTEBOOK_START_CREATE_MODE = "From notebook"
FIRST_PROOF_PAGE_ROUTES = {
    "project": Path("pages/1_PROJECT.py"),
    "orchestrate": Path("pages/2_ORCHESTRATE.py"),
    "analysis": Path("pages/4_ANALYSIS.py"),
}
FIRST_PROOF_NOTEBOOK_HINT = (
    "Creates `flight_telemetry_from_notebook_project`; then run `INSTALL` and `EXECUTE`."
)
FIRST_PROOF_SAMPLE_NOTEBOOK_NAME = _notebook_import_sample_module.SAMPLE_NOTEBOOK_DOWNLOAD_NAME
FIRST_PROOF_SAMPLE_NOTEBOOK_MIME = _notebook_import_sample_module.SAMPLE_NOTEBOOK_MIME
FIRST_PROOF_NOTEBOOK_QUERY_PARAMS = {"start": "notebook-import"}
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
            "button": "1. INSTALL",
            "hint": "Runs the ORCHESTRATE install.",
        },
        {
            "id": "run",
            "button": "2. RUN",
            "hint": "Starts the ORCHESTRATE run.",
        },
        {
            "id": "analysis",
            "button": "3. ANALYSIS",
            "hint": (
                "`view_maps`: "
                f"[Open]({_first_proof_analysis_view_maps_url()})."
            ),
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
        ["Import notebook", "Download example notebook", "Upload notebook", notebook_hint]
    )
    spec = [proof_width, _FIRST_PROOF_ACTION_SEPARATOR_WIDTH_PX, notebook_width]
    total_width = sum(spec) + (_FIRST_PROOF_ACTION_COLUMN_GAP_PX * (len(spec) - 1))
    return spec, total_width


def _first_proof_next_wizard_step_id(state: Dict[str, Any]) -> str:
    """Return the wizard step that should be visually promoted."""
    if state["run_manifest_passed"] or state["run_manifest_loaded"] or state["run_output_detected"]:
        return "analysis"
    return "install"


def _first_proof_page_route(action_id: str, page_routes: Dict[str, Any] | None) -> Any:
    """Return the registered Streamlit page object or a legacy file-path fallback."""
    if page_routes and action_id in page_routes:
        return page_routes[action_id]
    return FIRST_PROOF_PAGE_ROUTES[action_id]


def _first_proof_notebook_query_params(env: Any, state: Dict[str, Any]) -> Dict[str, str]:
    """Return query params that open PROJECT on the notebook-import create path."""
    query_params = dict(FIRST_PROOF_NOTEBOOK_QUERY_PARAMS)
    active_app = str(state.get("active_app_name") or getattr(env, "app", "") or "").strip()
    if active_app:
        query_params["active_app"] = active_app
    return query_params


def _render_first_proof_notebook_upload_control(
    env: Any,
    state: Dict[str, Any],
    page_routes: Dict[str, Any] | None,
) -> None:
    """Render a direct notebook upload control for the first-proof alternative."""
    query_params = _first_proof_notebook_query_params(env, state)
    uploaded_notebook = st.file_uploader(
        "Upload notebook",
        type="ipynb",
        key="create_notebook_upload",
        label_visibility="collapsed",
    )
    if uploaded_notebook is None:
        return

    st.session_state["sidebar_selection"] = "Create"
    st.session_state["create_mode"] = NOTEBOOK_START_CREATE_MODE
    st.session_state["first_proof_feedback"] = (
        "Notebook selected. PROJECT is open in Create mode; create the imported project, then run INSTALL and EXECUTE."
    )
    _first_proof_open_page(
        _first_proof_page_route("project", page_routes),
        "PROJECT",
        query_params=query_params,
    )


def _render_first_proof_sample_notebook_download() -> None:
    """Render the importable sample notebook download when packaged."""
    download_button = getattr(st, "download_button", None)
    if not callable(download_button):
        return
    try:
        sample_bytes = _notebook_import_sample_module.read_sample_notebook_bytes()
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        st.caption(f"Sample notebook unavailable: {exc}")
        return
    download_button(
        "Download example notebook",
        data=sample_bytes,
        file_name=FIRST_PROOF_SAMPLE_NOTEBOOK_NAME,
        mime=FIRST_PROOF_SAMPLE_NOTEBOOK_MIME,
        key="first_proof:wizard:sample_notebook",
        width="content",
    )


def _first_proof_open_page(
    page: Any,
    label: str,
    *,
    query_params: Dict[str, str] | None = None,
) -> None:
    """Open a Streamlit page, or explain the fallback when switch_page is unavailable."""
    switch_page = getattr(st, "switch_page", None)
    if not callable(switch_page):
        st.info(f"Open `{label}` from the sidebar to continue.")
        return
    try:
        switch_page(page, query_params=query_params)
    except StreamlitAPIException as exc:
        st.info(f"Open `{label}` from the sidebar to continue.")
        st.caption(str(exc))


def _first_proof_prepare_project(
    env: Any,
    state: Dict[str, Any],
    activate_project: Callable[[Any, Path], bool] | None,
) -> bool:
    """Select the first-proof project before moving to another wizard stage."""
    project_path = state.get("project_path")
    if not state["project_available"] or project_path is None:
        st.error("The built-in flight-telemetry project is missing. Restore it before continuing.")
        return False
    if state["current_app_matches"]:
        try:
            st.query_params["active_app"] = FIRST_PROOF_PROJECT
        except (AttributeError, RuntimeError, TypeError):
            pass
        return True
    if activate_project is None:
        st.error("Unable to select the built-in flight-telemetry project from this page.")
        return False
    selected = activate_project(env, Path(project_path))
    if selected:
        st.session_state["first_proof_feedback"] = "`flight_telemetry_project` selected."
    return selected


def _handle_first_proof_wizard_action(
    action_id: str,
    env: Any,
    state: Dict[str, Any],
    activate_project: Callable[[Any, Path], bool] | None,
    page_routes: Dict[str, Any] | None,
) -> None:
    """Run the action behind a first-proof wizard step."""
    query_params = {"active_app": FIRST_PROOF_PROJECT}
    if action_id == "project":
        if _first_proof_prepare_project(env, state, activate_project):
            st.session_state["first_proof_feedback"] = (
                "`flight_telemetry_project` selected. Next: open the run page."
            )
            rerun = getattr(st, "rerun", None)
            if callable(rerun):
                rerun()
        return
    if action_id == "install":
        if _first_proof_prepare_project(env, state, activate_project):
            _pending_actions_module.queue_pending_install_action(st.session_state)
            st.session_state["show_install"] = True
            _first_proof_open_page(
                _first_proof_page_route("orchestrate", page_routes),
                "ORCHESTRATE",
                query_params=query_params,
            )
        return
    if action_id == "run":
        if _first_proof_prepare_project(env, state, activate_project):
            _pending_actions_module.queue_pending_execute_action(st.session_state, "run")
            st.session_state["show_run"] = True
            _first_proof_open_page(
                _first_proof_page_route("orchestrate", page_routes),
                "ORCHESTRATE",
                query_params=query_params,
            )
        return
    if action_id == "analysis":
        if not _first_proof_prepare_project(env, state, activate_project):
            return
        _first_proof_open_page(
            _first_proof_page_route("analysis", page_routes),
            "ANALYSIS",
            query_params=query_params,
        )
        return
    if action_id == "notebook":
        active_app = str(state.get("active_app_name") or getattr(env, "app", "") or "")
        st.session_state["sidebar_selection"] = "Create"
        st.session_state["create_mode"] = NOTEBOOK_START_CREATE_MODE
        st.session_state["first_proof_feedback"] = (
            "Notebook start selected. PROJECT is open in Create mode; upload an `.ipynb` to create a reusable AGILAB project."
        )
        _first_proof_open_page(
            _first_proof_page_route("project", page_routes),
            "PROJECT",
            query_params={"active_app": active_app} if active_app else None,
        )


def _render_first_proof_wizard_actions(
    env: Any,
    state: Dict[str, Any],
    activate_project: Callable[[Any, Path], bool] | None,
    page_routes: Dict[str, Any] | None,
) -> None:
    """Render executable wizard actions for the first-proof pipeline."""
    st.markdown("**First proof with flight-telemetry-project**")
    next_step_id = _first_proof_next_wizard_step_id(state)
    proof_actions = [
        {
            "id": str(step["id"]),
            "button": str(step["button"]),
            "hint": str(step["hint"]),
            "type": "primary" if step["id"] == next_step_id else "secondary",
        }
        for step in _first_proof_wizard_steps(state)
    ]
    columns_spec, columns_width = _first_proof_action_columns_layout(proof_actions)
    proof_column, separator_column, notebook_column = st.columns(
        columns_spec,
        gap="small",
        vertical_alignment="top",
        width=columns_width,
    )
    with proof_column:
        for action in proof_actions:
            if st.button(
                action["button"],
                key=f"first_proof:wizard:{action['id']}",
                type=action["type"],
                width="content",
            ):
                _handle_first_proof_wizard_action(
                    action["id"],
                    env,
                    state,
                    activate_project,
                    page_routes,
                )
            st.caption(action["hint"])
    with separator_column:
        st.markdown("or")
    with notebook_column:
        if st.button(
            "Import notebook",
            key="first_proof:wizard:notebook",
            type="secondary",
            width="content",
        ):
            _handle_first_proof_wizard_action(
                "notebook",
                env,
                state,
                activate_project,
                page_routes,
            )
        st.caption(FIRST_PROOF_NOTEBOOK_HINT)
        _render_first_proof_sample_notebook_download()
        _render_first_proof_notebook_upload_control(env, state, page_routes)


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
