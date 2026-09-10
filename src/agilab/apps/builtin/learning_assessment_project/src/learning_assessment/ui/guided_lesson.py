"""Guided prediction, execution and reflection for the drift policy lesson."""

from __future__ import annotations

import hashlib
from pathlib import Path

from learning_assessment.domain.guided_lesson import (
    BASELINE,
    export_lesson,
    import_lesson,
    lesson_case,
    lesson_progress,
    new_lesson,
    run_checkpoint,
    save_explanation,
    validate_lesson,
)

ACTION_LABELS = {
    "normal": "Serve with monitoring",
    "fallback": "Abstain and request review",
}
METRIC_LABELS = {
    "drift_score": "Drift score",
    "empirical_coverage": "Empirical coverage",
}


def render_guided_lesson(active_app: Path | None = None) -> None:
    import streamlit as st

    scope = str(active_app.resolve()) if active_app is not None else "bundled"
    prefix = "guided_lesson_" + hashlib.sha256(scope.encode()).hexdigest()[:12]
    state_key = prefix + "_progress"
    generation_key = prefix + "_generation"
    st.session_state.setdefault(generation_key, 0)
    if state_key not in st.session_state:
        st.session_state[state_key] = new_lesson()
    error_key = prefix + "_error"

    def resume(data: bytes) -> None:
        try:
            restored = import_lesson(data)
        except ValueError as exc:
            st.session_state[error_key] = str(exc)
        else:
            st.session_state[state_key] = restored
            st.session_state[generation_key] += 1
            st.session_state.pop(error_key, None)

    def restart() -> None:
        st.session_state[state_key] = new_lesson()
        st.session_state.pop(error_key, None)

    def record(index: int, widget_prefix: str) -> None:
        observations = dict(BASELINE)
        if index:
            metric = st.session_state[widget_prefix + "_metric"]
            observations[metric] = st.session_state[widget_prefix + "_" + metric]
        prediction = st.session_state[widget_prefix + f"_prediction_{index}"]
        try:
            st.session_state[state_key] = run_checkpoint(
                st.session_state[state_key], observations, prediction
            )
        except ValueError as exc:
            st.session_state[error_key] = str(exc)
        else:
            st.session_state.pop(error_key, None)

    def explain(widget_key: str) -> None:
        try:
            st.session_state[state_key] = save_explanation(
                st.session_state[state_key], st.session_state[widget_key]
            )
        except ValueError as exc:
            st.session_state[error_key] = str(exc)
        else:
            st.session_state.pop(error_key, None)

    st.subheader("When should a prediction be held for review?")
    st.write(
        "Predict a decision, run the policy, then change one input and explain the difference. "
        "This short lesson executes a deterministic policy on synthetic observations."
    )
    with st.expander("Resume saved lesson"):
        uploaded = st.file_uploader(
            "Lesson evidence JSON", type=["json"], key=prefix + "_upload"
        )
        st.button(
            "Resume lesson",
            disabled=uploaded is None,
            key=prefix + "_resume",
            on_click=resume,
            args=(uploaded.getvalue() if uploaded is not None else b"",),
        )

    st.button(
        "Start a new lesson",
        key=prefix + "_restart",
        help="Clears this lesson's current progress. Download the evidence first to keep it.",
        on_click=restart,
    )
    if st.session_state.get(error_key):
        st.error(st.session_state[error_key])
    try:
        state = validate_lesson(st.session_state[state_key])
    except ValueError as exc:
        st.error(str(exc))
        return
    run_key = (
        prefix + "_" + state["started_at"] + "_" + str(st.session_state[generation_key])
    )
    policy = lesson_case()["decision_policy"]
    thresholds = policy["thresholds"]
    st.caption(
        f"Policy: request review when drift is greater than {thresholds['maximum_drift_score']} "
        f"or coverage is below {thresholds['minimum_empirical_coverage']}."
    )
    attempts = state["attempts"]
    unsaved_explanation = False
    if attempts:
        st.dataframe(
            [
                {
                    "Run": attempt["step"],
                    "Drift score": attempt["observations"]["drift_score"],
                    "Empirical coverage": attempt["observations"]["empirical_coverage"],
                    "Your prediction": ACTION_LABELS[attempt["prediction"]],
                    "Observed action": ACTION_LABELS[attempt["decision"]["status"]],
                    "Prediction matched": attempt["prediction"]
                    == attempt["decision"]["status"],
                }
                for attempt in attempts
            ],
            hide_index=True,
            width="stretch",
        )

    if len(attempts) < 2:
        index = len(attempts)
        observations = dict(BASELINE)
        if index == 0:
            st.markdown("**1. Predict and run the baseline**")
            st.write(
                f"Drift score: {BASELINE['drift_score']} · Empirical coverage: {BASELINE['empirical_coverage']}"
            )
        else:
            st.markdown("**2. Change one input and predict again**")
            metric = st.selectbox(
                "Input to change",
                list(METRIC_LABELS),
                format_func=METRIC_LABELS.__getitem__,
                key=run_key + "_metric",
            )
            observations[metric] = st.number_input(
                METRIC_LABELS[metric],
                min_value=0.0,
                max_value=1.0,
                value=BASELINE[metric],
                step=0.01,
                key=run_key + "_" + metric,
            )
            unchanged = next(key for key in BASELINE if key != metric)
            st.caption(f"{METRIC_LABELS[unchanged]} stays at {BASELINE[unchanged]}.")
        prediction = st.selectbox(
            "Predicted action",
            list(ACTION_LABELS),
            index=None,
            placeholder="Choose before running",
            format_func=ACTION_LABELS.__getitem__,
            key=run_key + f"_prediction_{index}",
        )
        changed = index == 0 or observations != BASELINE
        st.button(
            "Run baseline" if index == 0 else "Run changed input",
            key=run_key + f"_run_{index}",
            type="primary",
            disabled=prediction is None or not changed,
            on_click=record,
            args=(index, run_key),
        )
    else:
        st.markdown("**3. Explain the comparison**")
        first, second = attempts
        same = first["decision"]["status"] == second["decision"]["status"]
        st.info("The action stayed the same." if same else "The action changed.")
        for attempt in attempts:
            triggers = attempt["decision"]["triggers"]
            detail = (
                "; ".join(
                    f"{METRIC_LABELS[item['metric']]} {item['observed']} {item['operator']} {item['threshold']}"
                    for item in triggers
                )
                or "Neither review threshold was crossed."
            )
            st.write(f"{attempt['step'].capitalize()}: {detail}")
        explanation = st.text_area(
            "Which threshold explains the result, and what would happen exactly at that threshold?",
            value=state["explanation"],
            max_chars=4000,
            key=run_key + "_explanation",
        )
        st.button(
            "Save explanation",
            key=run_key + "_save",
            on_click=explain,
            args=(run_key + "_explanation",),
        )
        unsaved_explanation = explanation.strip() != state["explanation"]

    progress = lesson_progress(state)
    if progress["status"] == "completed" and not unsaved_explanation:
        st.success("Lesson recorded. Your explanation is ready for review.")
    if progress["review_queue"]:
        st.warning(
            "Practice again: " + ", ".join(progress["review_queue"]) + " prediction."
        )
    st.write("Next practice: " + progress["next_practice"])
    st.caption(
        "Progress is kept for this browser session. Download it to resume later. Explanations await review."
    )
    if unsaved_explanation:
        st.info("Save your explanation to include the edits in the evidence.")
    st.download_button(
        "Download lesson evidence",
        export_lesson(state),
        file_name="drift_decision_lesson.json",
        mime="application/json",
        key=prefix + "_download",
        on_click="ignore",
        disabled=unsaved_explanation,
    )
