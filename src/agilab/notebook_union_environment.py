# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Union-environment notebook planning for AGILAB pipeline evidence."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


SCHEMA = "agilab.notebook_union_environment.v1"
DEFAULT_RUN_ID = "notebook-union-environment-proof"
CREATED_AT = "2026-04-25T00:00:21Z"
UPDATED_AT = "2026-04-25T00:00:21Z"


@dataclass(frozen=True)
class NotebookUnionIssue:
    level: str
    location: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "level": self.level,
            "location": self.location,
            "message": self.message,
        }


def _normalize_runtime(value: Any) -> str:
    text = str(value or "").strip()
    return text or "runpy"


def _normalize_env(value: Any) -> str:
    return str(value or "").strip()


def _iter_step_entries(lab_steps: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    entries: list[dict[str, Any]] = []
    for module, steps in lab_steps.items():
        if module == "__meta__" or not isinstance(steps, list):
            continue
        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            code = str(step.get("C", "") or "")
            if not code.strip():
                continue
            entries.append(
                {
                    "module": str(module),
                    "module_index": index,
                    "description": str(step.get("D", "") or ""),
                    "question": str(step.get("Q", "") or ""),
                    "model": str(step.get("M", "") or ""),
                    "code": code,
                    "runtime": _normalize_runtime(step.get("R")),
                    "env": _normalize_env(step.get("E")),
                }
            )
    return tuple(entries)


def _issue(location: str, message: str) -> NotebookUnionIssue:
    return NotebookUnionIssue(level="error", location=location, message=message)


def build_union_environment_plan(
    lab_steps: Mapping[str, Any],
    *,
    run_id: str = DEFAULT_RUN_ID,
) -> dict[str, Any]:
    steps = _iter_step_entries(lab_steps)
    runtimes = sorted({step["runtime"] for step in steps})
    envs = sorted({step["env"] for step in steps})
    issues: list[NotebookUnionIssue] = []
    if not steps:
        issues.append(_issue("steps", "no executable pipeline steps found"))
    if len(runtimes) > 1:
        issues.append(_issue("runtime", f"mixed runtimes require supervisor export: {runtimes}"))
    if any(runtime != "runpy" for runtime in runtimes):
        issues.append(
            _issue("runtime", f"non-runpy runtime requires supervisor export: {runtimes}")
        )
    if len(envs) > 1:
        issues.append(
            _issue("environment", f"mixed step environments require supervisor export: {envs}")
        )

    compatible = not issues
    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "created_at": CREATED_AT,
        "updated_at": UPDATED_AT,
        "run_status": "union_candidate" if compatible else "supervisor_required",
        "execution_mode": "not_executed_union_plan",
        "union_mode": (
            "single_kernel_union_candidate"
            if compatible
            else "supervisor_notebook_required"
        ),
        "summary": {
            "step_count": len(steps),
            "runtime_count": len(runtimes),
            "environment_count": len(envs),
            "compatible": compatible,
            "issue_count": len(issues),
            "common_runtime": runtimes[0] if len(runtimes) == 1 else "",
            "common_environment": envs[0] if len(envs) == 1 else "",
        },
        "steps": list(steps),
        "issues": [issue.as_dict() for issue in issues],
        "provenance": {
            "executes_notebook": False,
            "supervisor_fallback_for_mixed_runtime": True,
            "preserves_step_order": True,
        },
    }


def build_union_notebook(plan: Mapping[str, Any]) -> dict[str, Any]:
    if plan.get("union_mode") != "single_kernel_union_candidate":
        raise ValueError("union notebook can only be built for compatible plans")
    cells: list[dict[str, Any]] = [
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "# AGILAB Union-Environment Notebook\n",
                "\n",
                "This notebook is a non-executed single-kernel candidate.\n",
            ],
        }
    ]
    for index, step in enumerate(plan.get("steps", []), start=1):
        if not isinstance(step, dict):
            continue
        cells.append(
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    f"## Step {index}: {step.get('description', '')}\n",
                    f"- Runtime: `{step.get('runtime', '')}`\n",
                    f"- Environment: `{step.get('env', '') or 'current kernel'}`\n",
                ],
            }
        )
        cells.append(
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": str(step.get("code", "") or "").splitlines(keepends=True),
            }
        )
    return {
        "cells": cells,
        "metadata": {
            "agilab": {
                "schema": SCHEMA,
                "run_id": plan.get("run_id", DEFAULT_RUN_ID),
                "union_mode": plan.get("union_mode"),
                "execution_mode": plan.get("execution_mode"),
                "step_count": plan.get("summary", {}).get("step_count"),
            },
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def write_union_environment_plan(path: Path, plan: Mapping[str, Any]) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_union_notebook(path: Path, notebook: Mapping[str, Any]) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(notebook, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
