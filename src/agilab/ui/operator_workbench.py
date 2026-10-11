"""Discover operator contexts without loading workers or starting an execution."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


_PROFILES = (
    ("local", "Local app", "orchestrate", "context", "Configure and run the selected app locally."),
    ("cluster", "Cluster app", "orchestrate", "diagnostics", "Review resources, deployment and distributed execution settings."),
    ("notebook", "Notebook", "workflow", "context", "Edit the pipeline and export editable Python cells to Jupyter."),
    ("evidence", "Run evidence", "analysis", "activity", "Inspect outputs, provenance and comparisons from project views."),
    ("worker", "Worker environment", "orchestrate", "diagnostics", "Inspect and deploy the worker environment through the AGI SDK."),
    ("demo", "Public demo", "agent_demo", "context", "Open the demonstration and its existing proof controls."),
    ("release", "Release proof", "analysis", "commands", "Open analysis and select the Release Decision evidence view."),
)

_NAVIGATION_COMMANDS = (
    ("project-status", "Open project status", "project", "Inspect project data and environment diagnostics."),
    ("local-settings", "Configure local execution", "orchestrate", "Review current execution settings before running."),
    ("worker-deployment", "Open worker deployment", "orchestrate", "Use Resources to deploy the scheduler and workers."),
    ("notebook-export", "Open notebook export", "workflow", "Review pipeline stages and export the supervisor notebook."),
    ("run-evidence", "Open run evidence", "analysis", "Choose an analysis view to inspect outputs and provenance."),
    ("release-evidence", "Open release evidence", "analysis", "Select Release Decision to review promotion evidence."),
    ("demo-proof", "Open demo proof", "agent_demo", "Use the demonstration's existing proof and replay controls."),
)


def workbench_data(
    data: Mapping[str, Any], *, session_state: Mapping[str, Any], query_params: Mapping[str, Any],
) -> dict[str, Any]:
    """Publish a small, credential-free registry derived from the current host.

    Discovery uses the already refreshed project catalog and registered routes.
    It performs no filesystem/network probes and never imports application workers.
    """
    route_ids = {row["id"] for row in data["routes"]}
    project = data["project"]
    profiles = [
        {"id": key, "label": label, "route": route, "pane_id": pane,
         "description": description, "disabled": not bool(project),
         "reason": "Select a project first." if not project else ""}
        for key, label, route, pane, description in _PROFILES if route in route_ids
    ]
    commands = [
        {"id": key, "label": label, "description": description, "kind": "navigate",
         "value": route, "requires_review": False, "disabled": not bool(project),
         "reason": "Select a project first." if not project else ""}
        for key, label, route, description in _NAVIGATION_COMMANDS if route in route_ids
    ]
    if "orchestrate" in route_ids:
        commands.extend(
            {"id": f"project-{action}", "label": label, "description": description,
             "kind": "orchestrate_action", "value": action, "requires_review": True,
             "disabled": not bool(project), "reason": "Select a project first." if not project else ""}
            for action, label, description in (
                ("install", "Install selected app", "Install the selected app with its current settings. This can download dependencies."),
                ("run", "Run configured project", "Run the selected app with its current ORCHESTRATE settings. Worker readiness is checked before execution."),
            )
        )
    commands.extend(
        {"id": f"select-project:{name}", "label": f"Switch to {name}",
         "description": "Switch the active app and refresh its environment and page inputs.",
         "kind": "project", "value": name, "requires_review": True, "disabled": False, "reason": ""}
        for name in data["projects"] if name != project
    )
    child_surface = query_params.get("current_notebook") or query_params.get("current_page")
    last_run = "Not recorded in this session"
    if session_state.get("_last_execute_failed"):
        last_run = "Failed — inspect Run logs in ORCHESTRATE"
    diagnostics = [
        {"id": "project", "label": "Active project", "value": project or "No project selected"},
        {"id": "route", "label": "Current workspace", "value": data["route"].upper()},
        {"id": "version", "label": "AGILAB version", "value": data.get("version") or "Not supplied by this host"},
        {"id": "last-run", "label": "Last execution", "value": last_run},
    ]
    if isinstance(child_surface, str) and child_surface and child_surface != "main":
        diagnostics.append({"id": "child-surface", "label": "Open view", "value": child_surface})
    return {
        "schema_version": 1, "profiles": profiles, "commands": commands, "diagnostics": diagnostics,
        "panes": [
            {"id": "context", "label": "Project context", "kind": "context",
             "description": "Profiles use the active project and its existing workspace settings."},
            {"id": "diagnostics", "label": "Compact diagnostics", "kind": "diagnostics",
             "description": "Inspect detailed resource checks and execution logs in ORCHESTRATE."},
            {"id": "commands", "label": "Available commands", "kind": "commands",
             "description": "Choose a command from the palette. Installation, execution and project switches require review."},
            {"id": "activity", "label": "Execution evidence", "kind": "activity", "description": last_run},
        ],
    }


def resolve_workbench_command(action: Mapping[str, Any], data: Mapping[str, Any]) -> dict[str, Any] | None:
    """Resolve only the server's registry; client targets and descriptions are ignored."""
    registry = data.get("workbench", {}).get("commands", ())
    command = next((row for row in registry if row["id"] == action.get("value")), None)
    if command is None or command.get("disabled"):
        return None
    if command.get("requires_review") and action.get("reviewed") is not True:
        return None
    return {"kind": command["kind"], "value": command["value"]}


def queue_workbench_execution(session_state: Any, action: str) -> None:
    """Reuse ORCHESTRATE's pending-action lifecycle and its SDK readiness checks."""
    from agilab.orchestrate.orchestrate_pending_actions import (
        queue_pending_execute_action,
        queue_pending_install_action,
    )

    if action == "install":
        queue_pending_install_action(session_state)
    elif action == "run":
        queue_pending_execute_action(session_state, "run")
    else:
        raise ValueError("Unsupported workbench execution action")
