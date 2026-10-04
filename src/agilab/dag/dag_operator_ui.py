"""Native UI controls for explicit, persistent operator branch replay."""

from __future__ import annotations

from typing import Any, Mapping

from .dag_operator_replay import replay_unit_ids
from agilab.global_pipeline.global_pipeline_runner_state import (
    RunnerStateConflictError,
    RunnerStateRecoveryRequiredError,
)


def render_operator_replay_controls(
    ui: Any,
    *,
    engine: Any,
    state: Mapping[str, Any],
    key_prefix: str,
) -> bool:
    """Return true when an action consumed this render; never execute app code."""
    prepare = getattr(engine, "prepare_operator_replay_transaction", None)
    if not callable(prepare):
        return False
    units = state.get("units", [])
    candidates = [
        unit for unit in units
        if isinstance(unit, Mapping) and unit.get("dispatch_status") in {"failed", "completed"}
    ]
    if not candidates:
        return False
    with ui.expander("Retry or rerun a branch", expanded=True):
        by_id = {str(unit["id"]): unit for unit in candidates}
        selected = ui.selectbox(
            "Stage to replay", list(by_id), key=f"{key_prefix}_replay_stage",
            format_func=lambda value: f"{value} ({by_id[value]['dispatch_status']})",
        )
        unit = by_id.get(str(selected))
        if unit is None:
            return False
        action = "retry" if unit.get("dispatch_status") == "failed" else "partial_rerun"
        affected = replay_unit_ids(state, str(selected))
        ui.caption(f"Stages to prepare: {', '.join(affected)}. Other completed branches remain available.")
        ui.caption("Preparing invalidates this branch's output handoffs. Run the ready stage below to execute it.")
        clicked = ui.button(
            "Prepare retry" if action == "retry" else "Prepare partial rerun",
            key=f"{key_prefix}_prepare_{action}",
        )
        if not clicked:
            return False
        try:
            result = prepare(state, unit_id=str(selected), action=action)
        except RunnerStateConflictError as exc:
            ui.warning("Workflow state changed in another session. Reloading the latest state.")
            ui.caption(str(exc))
            ui.rerun()
        except RunnerStateRecoveryRequiredError as exc:
            ui.warning("Recover the active execution attempt before preparing a replay.")
            ui.caption(str(exc))
        except ValueError as exc:
            ui.warning(str(exc))
        else:
            ui.success(result.message)
            ui.rerun()
        return True
