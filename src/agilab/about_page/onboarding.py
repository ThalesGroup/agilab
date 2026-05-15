"""First-proof onboarding helpers for the AGILAB main page."""

from __future__ import annotations

import importlib.util
from html import escape
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

FIRST_PROOF_PROJECT = "flight_telemetry_project"
FIRST_PROOF_COMPATIBILITY_SLICE = _first_proof_wizard_module.FIRST_PROOF_RECOMMENDED_LABEL
FIRST_PROOF_HELPER_SCRIPT_PREFIXES = _first_proof_wizard_module.FIRST_PROOF_HELPER_SCRIPT_PREFIXES
FIRST_PROOF_PAGE_ROUTES = {
    "project": Path("pages/1_PROJECT.py"),
    "orchestrate": Path("pages/2_ORCHESTRATE.py"),
    "analysis": Path("pages/4_ANALYSIS.py"),
}


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
        f"<li><strong>{escape(str(label))}</strong>: {escape(str(detail))}</li>"
        for label, detail in content["steps"]
    )
    success_html = "".join(
        f"<li>{escape(str(item))}</li>"
        for item in content["success_criteria"]
    )
    st.markdown(
        f"""
        <style>
          .agilab-proof-static {{
            margin: 1rem 0 1.25rem;
            padding: 1.15rem 1.25rem;
            border: 1px solid rgba(10, 31, 51, 0.12);
            border-radius: 20px;
            background:
              radial-gradient(circle at 100% 0%, rgba(255, 190, 94, 0.20), transparent 34%),
              linear-gradient(135deg, #ffffff 0%, #f5f8f4 100%);
            box-shadow: 0 14px 40px rgba(12, 27, 42, 0.08);
            font-family: "Aptos", "Avenir Next", "Gill Sans", "Trebuchet MS", sans-serif;
          }}
          .agilab-proof-static h3 {{
            margin: 0 0 0.45rem;
            color: #0a1f33;
            letter-spacing: -0.02em;
          }}
          .agilab-proof-static p,
          .agilab-proof-static li {{
            color: #4b6258;
            line-height: 1.5;
          }}
          .agilab-proof-static strong {{
            color: #0a1f33;
          }}
        </style>
        <div class="agilab-proof-static">
          <h3>{escape(str(content["title"]))}</h3>
          <p style="margin-bottom: 0.75rem;">{escape(str(content["intro"]))}</p>
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
        project_detail = (
            "The built-in flight demo (`flight_telemetry_project`) is missing from the app list."
        )
    elif state["current_app_matches"]:
        project_status = "Done"
        project_detail = "The built-in flight demo is selected."
    else:
        project_status = "Next"
        project_detail = f"Active project is `{active_app}`; choose the built-in flight demo."

    if state["run_manifest_loaded"] or state["run_output_detected"]:
        run_status = "Done"
        run_detail = f"Run evidence found under `{output_dir}`."
    elif state["current_app_matches"]:
        run_status = "Next"
        run_detail = "Go to `ORCHESTRATE`. Click INSTALL, then EXECUTE."
    else:
        run_status = "Waiting"
        run_detail = "Select the built-in flight demo before running."

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


def _first_proof_status_tone(status: str) -> str:
    """Return a stable CSS tone for a first-proof status label."""
    normalized = status.strip().lower()
    if normalized == "done":
        return "done"
    if normalized == "next":
        return "next"
    if normalized in {"attention", "blocked"}:
        return "attention"
    return "waiting"


def _first_proof_next_action_model(state: Dict[str, Any]) -> Dict[str, str]:
    """Return first-run microcopy for the next visible user action."""
    active_app = str(state.get("active_app_name") or "none")
    next_step = str(state.get("next_step") or "").strip()
    if not state["project_available"]:
        return {
            "tone": "attention",
            "phase": "Fix setup",
            "title": "Restore the built-in flight demo",
            "detail": (
                next_step
                or "The built-in flight demo (`flight_telemetry_project`) is missing from the app list."
            ),
            "cta_label": "Open troubleshooting",
            "proof_hint": "The built-in demo must exist before the first proof can run.",
        }
    if not state["current_app_matches"]:
        return {
            "tone": "next",
            "phase": "Stage 1",
            "title": "Select the built-in flight demo",
            "detail": (
                f"You are on `{active_app}`. Switch to `flight_telemetry_project`, "
                "the guided demo with sample data, before running anything."
            ),
            "cta_label": "Use built-in demo",
            "proof_hint": "This keeps the first proof on the documented, supportable route.",
        }
    if state["run_manifest_passed"]:
        return {
            "tone": "done",
            "phase": "Complete",
            "title": "First proof is green",
            "detail": "The manifest passes. Keep it as evidence before trying another demo.",
            "cta_label": "Try another demo",
            "proof_hint": "`run_manifest.json` is valid for the first-proof route.",
        }
    if state["run_manifest_loaded"] or state["run_output_detected"]:
        return {
            "tone": "attention",
            "phase": "Stage 3",
            "title": "Finish the evidence",
            "detail": next_step or "Generate or repair `run_manifest.json` before moving on.",
            "cta_label": "Show proof details",
            "proof_hint": "Done when `run_manifest.json` passes the compatibility checks.",
        }
    return {
        "tone": "next",
        "phase": "Stage 2",
        "title": "Install, then execute",
        "detail": "Open `ORCHESTRATE`; click `INSTALL`, then `EXECUTE` with cluster and service mode off.",
        "cta_label": "Go to `ORCHESTRATE`",
        "proof_hint": "Done when ANALYSIS opens and `run_manifest.json` appears.",
    }


def _first_proof_wizard_steps(state: Dict[str, Any]) -> List[Dict[str, str]]:
    """Return clickable wizard steps for the newcomer proof path."""
    project_label = "1. Open PROJECT" if state["current_app_matches"] else "1. Select demo"
    project_detail = (
        "The built-in flight demo is already selected."
        if state["current_app_matches"]
        else "Select the demo project and keep later steps on the validated path."
    )
    analysis_ready = (
        state["run_manifest_passed"]
        or state["run_manifest_loaded"]
        or state["run_output_detected"]
    )
    analysis_label = "3. Open ANALYSIS" if analysis_ready else "3. Run first"
    analysis_detail = (
        "Open the generated results."
        if analysis_ready
        else "No run evidence yet; this takes you to ORCHESTRATE first."
    )
    return [
        {
            "id": "project",
            "title": "PROJECT",
            "button": project_label,
            "detail": project_detail,
        },
        {
            "id": "orchestrate",
            "title": "ORCHESTRATE",
            "button": "2. Open ORCHESTRATE",
            "detail": "Install and execute the demo with cluster and service mode off.",
        },
        {
            "id": "analysis",
            "title": "ANALYSIS",
            "button": analysis_label,
            "detail": analysis_detail,
        },
    ]


def _first_proof_next_wizard_step_id(state: Dict[str, Any]) -> str:
    """Return the wizard step that should be visually promoted."""
    if not state["project_available"] or not state["current_app_matches"]:
        return "project"
    if state["run_manifest_passed"] or state["run_manifest_loaded"] or state["run_output_detected"]:
        return "analysis"
    return "orchestrate"


def _first_proof_open_page(page: Path, label: str) -> None:
    """Open a Streamlit page, or explain the fallback when switch_page is unavailable."""
    switch_page = getattr(st, "switch_page", None)
    if not callable(switch_page):
        st.info(f"Open `{label}` from the sidebar to continue.")
        return
    switch_page(page)


def _first_proof_prepare_project(
    env: Any,
    state: Dict[str, Any],
    activate_project: Callable[[Any, Path], bool] | None,
) -> bool:
    """Select the first-proof project before moving to another wizard stage."""
    project_path = state.get("project_path")
    if not state["project_available"] or project_path is None:
        st.error("The built-in flight demo is missing. Restore it before continuing.")
        return False
    if state["current_app_matches"]:
        try:
            st.query_params["active_app"] = FIRST_PROOF_PROJECT
        except (AttributeError, RuntimeError, TypeError):
            pass
        return True
    if activate_project is None:
        st.error("Unable to select the built-in flight demo from this page.")
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
) -> None:
    """Run the action behind a first-proof wizard step."""
    if action_id == "project":
        if _first_proof_prepare_project(env, state, activate_project):
            _first_proof_open_page(FIRST_PROOF_PAGE_ROUTES["project"], "PROJECT")
        return
    if action_id == "orchestrate":
        if _first_proof_prepare_project(env, state, activate_project):
            _first_proof_open_page(FIRST_PROOF_PAGE_ROUTES["orchestrate"], "ORCHESTRATE")
        return
    if action_id == "analysis":
        if not _first_proof_prepare_project(env, state, activate_project):
            return
        if state["run_manifest_passed"] or state["run_manifest_loaded"] or state["run_output_detected"]:
            _first_proof_open_page(FIRST_PROOF_PAGE_ROUTES["analysis"], "ANALYSIS")
            return
        st.session_state["first_proof_feedback"] = (
            "Run the built-in flight demo from ORCHESTRATE before opening ANALYSIS."
        )
        _first_proof_open_page(FIRST_PROOF_PAGE_ROUTES["orchestrate"], "ORCHESTRATE")


def _render_first_proof_wizard_actions(
    env: Any,
    state: Dict[str, Any],
    activate_project: Callable[[Any, Path], bool] | None,
) -> None:
    """Render executable wizard actions for the first-proof pipeline."""
    st.markdown("**Wizard pipeline**")
    st.caption("Click a step: AGILAB selects the demo when needed, then opens the right page.")
    next_step_id = _first_proof_next_wizard_step_id(state)
    for step in _first_proof_wizard_steps(state):
        st.markdown(f"**{step['title']}**")
        st.caption(step["detail"])
        button_type = "primary" if step["id"] == next_step_id else "secondary"
        if st.button(
            step["button"],
            key=f"first_proof:wizard:{step['id']}",
            type=button_type,
            width="stretch",
        ):
            _handle_first_proof_wizard_action(step["id"], env, state, activate_project)


def _first_proof_overview_html(
    content: Dict[str, Any],
    state: Dict[str, Any],
    rows: List[Dict[str, str]],
) -> str:
    """Render the first-proof cockpit card."""
    next_action = _first_proof_next_action_model(state)
    cards_html = "".join(
        (
            f"""<article class="agilab-proof__status agilab-proof__status--{_first_proof_status_tone(row['status'])}">
                  <span>{escape(str(row["status"]))}</span>
                  <strong>{escape(str(row["step"]))}</strong>
                  <p>{escape(str(row["detail"]))}</p>
                </article>"""
        )
        for row in rows
    )
    target_seconds = float(state.get("target_seconds") or 0.0)
    active_app = str(state.get("active_app_name") or "none")
    route = str(state.get("recommended_path_label") or "recommended path")
    return f"""
        <style>
          .agilab-proof {{
            margin: 0.25rem 0 1.05rem;
            padding: clamp(1rem, 2.2vw, 1.45rem);
            border: 1px solid rgba(10, 31, 51, 0.11);
            border-radius: 24px;
            background:
              radial-gradient(circle at 8% 0%, rgba(255, 190, 94, 0.24), transparent 32%),
              radial-gradient(circle at 92% 15%, rgba(52, 211, 153, 0.16), transparent 32%),
              linear-gradient(135deg, #ffffff 0%, #f4f8f5 100%);
            box-shadow: 0 18px 48px rgba(12, 27, 42, 0.09);
            font-family: "Aptos", "Avenir Next", "Gill Sans", "Trebuchet MS", sans-serif;
          }}
          .agilab-proof__head {{
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: 1rem;
            align-items: start;
          }}
          .agilab-proof__kicker {{
            margin: 0 0 0.45rem;
            color: #39513f;
            font-size: 0.72rem;
            font-weight: 900;
            letter-spacing: 0.14em;
            text-transform: uppercase;
          }}
          .agilab-proof h2 {{
            margin: 0;
            color: #0a1f33;
            font-size: clamp(1.55rem, 3vw, 2.25rem);
            letter-spacing: -0.055em;
            line-height: 1.02;
          }}
          .agilab-proof__intro {{
            max-width: 760px;
            margin: 0.75rem 0 0;
            color: #587064;
            line-height: 1.55;
            font-size: 0.98rem;
          }}
          .agilab-proof__seal {{
            min-width: 170px;
            padding: 0.75rem 0.85rem;
            border: 1px solid rgba(10, 31, 51, 0.10);
            border-radius: 18px;
            background: rgba(255, 255, 255, 0.72);
            text-align: right;
          }}
          .agilab-proof__seal span {{
            display: block;
            color: #77877f;
            font-size: 0.72rem;
            font-weight: 800;
            letter-spacing: 0.08em;
            text-transform: uppercase;
          }}
          .agilab-proof__seal strong {{
            display: block;
            margin-top: 0.15rem;
            color: #0a1f33;
            font-size: 1.08rem;
          }}
          .agilab-proof__action {{
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: 0.85rem;
            align-items: center;
            margin-top: 1rem;
            padding: 0.9rem;
            border: 1px solid rgba(10, 31, 51, 0.12);
            border-radius: 20px;
            background:
              linear-gradient(135deg, rgba(10, 31, 51, 0.92), rgba(35, 58, 50, 0.90));
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.10);
          }}
          .agilab-proof__action--done {{
            background: linear-gradient(135deg, #14532d, #2f5c40);
          }}
          .agilab-proof__action--attention {{
            background: linear-gradient(135deg, #7f1d1d, #86450b);
          }}
          .agilab-proof__action span {{
            display: inline-flex;
            margin-bottom: 0.32rem;
            color: #ffd28a;
            font-size: 0.72rem;
            font-weight: 900;
            letter-spacing: 0.12em;
            text-transform: uppercase;
          }}
          .agilab-proof__action strong {{
            display: block;
            color: #fffaf0;
            font-size: 1.05rem;
          }}
          .agilab-proof__action p {{
            margin: 0.28rem 0 0;
            color: rgba(255, 250, 240, 0.78);
            line-height: 1.45;
          }}
          .agilab-proof__action aside {{
            min-width: 190px;
            padding: 0.7rem 0.75rem;
            border: 1px solid rgba(255, 255, 255, 0.18);
            border-radius: 16px;
            background: rgba(255, 255, 255, 0.09);
            color: rgba(255, 250, 240, 0.86);
            font-size: 0.84rem;
            font-weight: 800;
            text-align: right;
          }}
          .agilab-proof__action aside small {{
            display: block;
            margin-top: 0.25rem;
            color: rgba(255, 250, 240, 0.62);
            font-weight: 650;
            line-height: 1.35;
          }}
          .agilab-proof__rail {{
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 0.72rem;
            margin-top: 1rem;
          }}
          .agilab-proof__status {{
            min-height: 132px;
            padding: 0.9rem;
            border: 1px solid rgba(10, 31, 51, 0.10);
            border-radius: 18px;
            background: rgba(255, 255, 255, 0.76);
          }}
          .agilab-proof__status span {{
            display: inline-flex;
            margin-bottom: 0.65rem;
            padding: 0.18rem 0.52rem;
            border-radius: 999px;
            font-size: 0.72rem;
            font-weight: 900;
            letter-spacing: 0.06em;
            text-transform: uppercase;
          }}
          .agilab-proof__status--done span {{
            color: #14532d;
            background: rgba(34, 197, 94, 0.16);
          }}
          .agilab-proof__status--next span {{
            color: #7c4a03;
            background: rgba(255, 190, 94, 0.24);
          }}
          .agilab-proof__status--attention span {{
            color: #8a1f11;
            background: rgba(248, 113, 113, 0.16);
          }}
          .agilab-proof__status--waiting span {{
            color: #475569;
            background: rgba(100, 116, 139, 0.13);
          }}
          .agilab-proof__status strong {{
            display: block;
            margin-bottom: 0.35rem;
            color: #0a1f33;
          }}
          .agilab-proof__status p {{
            margin: 0;
            color: #60736c;
            font-size: 0.9rem;
            line-height: 1.42;
          }}
          .agilab-proof__meta {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            margin-top: 0.9rem;
          }}
          .agilab-proof__meta span {{
            padding: 0.42rem 0.62rem;
            border: 1px solid rgba(10, 31, 51, 0.10);
            border-radius: 999px;
            background: rgba(255, 255, 255, 0.62);
            color: #4d655b;
            font-size: 0.84rem;
            font-weight: 750;
          }}
          @media (max-width: 900px) {{
            .agilab-proof__head,
            .agilab-proof__rail,
            .agilab-proof__action {{
              grid-template-columns: 1fr;
            }}
            .agilab-proof__seal {{
              text-align: left;
            }}
            .agilab-proof__action aside {{
              text-align: left;
            }}
          }}
        </style>
        <section class="agilab-proof" aria-label="First proof onboarding">
          <div class="agilab-proof__head">
            <div>
              <p class="agilab-proof__kicker">First proof path</p>
              <h2>{escape(str(content["title"]))}</h2>
              <p class="agilab-proof__intro">{escape(str(content["intro"]))}</p>
            </div>
            <div class="agilab-proof__seal">
              <span>Target</span>
              <strong>&lt;= {target_seconds:.0f}s</strong>
            </div>
          </div>
          <div class="agilab-proof__action agilab-proof__action--{escape(next_action['tone'])}">
            <div>
              <span>{escape(next_action["phase"])}</span>
              <strong>{escape(next_action["title"])}</strong>
              <p>{escape(next_action["detail"])}</p>
            </div>
            <aside>
              {escape(next_action["cta_label"])}
              <small>{escape(next_action["proof_hint"])}</small>
            </aside>
          </div>
          <div class="agilab-proof__rail">{cards_html}</div>
          <div class="agilab-proof__meta">
            <span>Route: {escape(route)}</span>
            <span>Active project: {escape(active_app)}</span>
            <span>PROJECT / ORCHESTRATE / ANALYSIS</span>
          </div>
        </section>
        """


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
            width="stretch",
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

    progress_rows = _first_proof_progress_rows(state)
    st.markdown(
        _first_proof_overview_html(content, state, progress_rows),
        unsafe_allow_html=True,
    )
    st.markdown("**1. Goal**")
    st.write(content["intro"])
    _render_first_proof_wizard_actions(env, state, activate_project)

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
