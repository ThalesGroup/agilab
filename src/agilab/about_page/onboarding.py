"""First-proof onboarding helpers for the AGILab About page."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Callable, Dict, List

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

FIRST_PROOF_PROJECT = "flight_project"
FIRST_PROOF_COMPATIBILITY_SLICE = _first_proof_wizard_module.FIRST_PROOF_RECOMMENDED_LABEL
FIRST_PROOF_HELPER_SCRIPT_PREFIXES = _first_proof_wizard_module.FIRST_PROOF_HELPER_SCRIPT_PREFIXES


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
    """Render the legacy concise newcomer checklist used by helper tests."""
    content = _newcomer_first_proof_content()
    steps_html = "".join(
        f"<li><strong>{label}</strong>: {detail}</li>"
        for label, detail in content["steps"]
    )
    success_html = "".join(
        f"<li>{item}</li>"
        for item in content["success_criteria"]
    )
    st.markdown(
        f"""
        <div style="border: 1px solid rgba(120, 120, 120, 0.35); border-radius: 12px; padding: 1rem 1.2rem; margin: 1rem 0 1.25rem 0; background: rgba(250, 250, 250, 0.82);">
          <h3 style="margin-top: 0;">{content["title"]}</h3>
          <p style="margin-bottom: 0.75rem;">{content["intro"]}</p>
          <p style="margin-bottom: 0.35rem;"><strong>Do this now</strong></p>
          <ol style="margin-top: 0.1rem; margin-bottom: 0.75rem;">{steps_html}</ol>
          <p style="margin-bottom: 0.35rem;"><strong>Done when</strong></p>
          <ul style="margin-top: 0.1rem; margin-bottom: 0.5rem;">{success_html}</ul>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _first_proof_progress_rows(state: Dict[str, Any]) -> List[Dict[str, str]]:
    """Return compact first-proof progress rows for the onboarding card."""
    active_app = str(state.get("active_app_name") or "none")
    manifest_path = str(state.get("run_manifest_path") or "")
    output_dir = str(state.get("output_dir") or "")

    if not state["project_available"]:
        project_status = "Blocked"
        project_detail = "`flight_project` is missing from the app list."
    elif state["current_app_matches"]:
        project_status = "Done"
        project_detail = "Active app is `flight_project`."
    else:
        project_status = "Next"
        project_detail = f"Active app is `{active_app}`; choose `flight_project`."

    if state["run_manifest_loaded"] or state["run_output_detected"]:
        run_status = "Done"
        run_detail = f"Run evidence found under `{output_dir}`."
    elif state["current_app_matches"]:
        run_status = "Next"
        run_detail = "Go to `ORCHESTRATE`. Click INSTALL, then EXECUTE."
    else:
        run_status = "Waiting"
        run_detail = "Select `flight_project` before running."

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

    table = ["| Step | Status | Detail |", "| --- | --- | --- |"]
    table.extend(
        (
            f"| {_cell(row['step'])} | {_cell(row['status'])} | "
            f"{_cell(row['detail'])} |"
        )
        for row in rows
    )
    return "\n".join(table)


def _render_first_proof_next_action(
    env: Any,
    state: Dict[str, Any],
    activate_project: Callable[[Any, Path], bool] | None,
) -> None:
    """Render the primary next action before diagnostics."""
    st.markdown("**Next action**")
    if not state["project_available"]:
        st.error(state["next_step"])
    elif not state["current_app_matches"]:
        st.warning(f"Next action: {state['next_step']}")
        if st.button(
            "Use `flight_project`",
            key="first_proof:activate",
            type="primary",
            use_container_width=True,
        ):
            if activate_project is not None and activate_project(env, state["project_path"]):
                st.session_state["first_proof_feedback"] = "`flight_project` selected."
                st.rerun()
    elif state["run_manifest_passed"]:
        st.success(f"Next action: {state['next_step']}")
    elif state["run_manifest_loaded"] or state["run_output_detected"]:
        st.warning(f"Next action: {state['next_step']}")
    else:
        st.info(f"Next action: {state['next_step']}")


def render_newcomer_first_proof(
    env: Any | None = None,
    *,
    activate_project: Callable[[Any, Path], bool] | None = None,
    display_landing_page: Callable[[Path], None] | None = None,
) -> None:
    """Render the first-proof onboarding surface."""
    if env is None:
        _render_newcomer_first_proof_static()
        return

    state = _newcomer_first_proof_state(env)
    content = state["content"]
    feedback = st.session_state.pop("first_proof_feedback", None)
    if feedback:
        st.success(str(feedback))

    with st.expander(content["title"], expanded=True):
        st.markdown("**1. Goal**")
        st.write(content["intro"])
        _render_first_proof_next_action(env, state, activate_project)

        st.markdown("**2. Do this now**")
        step_lines = [
            f"{index}. {detail}"
            for index, (_, detail) in enumerate(content["steps"], start=1)
        ]
        st.markdown("\n".join(step_lines))

        if state["visible_outputs"]:
            preview = ", ".join(path.name for path in state["visible_outputs"][:3])
            if len(state["visible_outputs"]) > 3:
                preview += ", ..."
            st.caption(f"Generated files found: {preview}")

        st.markdown("**3. Done when**")
        st.markdown("\n".join(f"- {item}" for item in content["success_criteria"]))
        st.caption("After that: try another demo. Keep cluster and service mode for later.")

        with st.expander("If it fails / proof details", expanded=False):
            st.markdown("**Progress**")
            st.markdown(_first_proof_progress_markdown(_first_proof_progress_rows(state)))
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
