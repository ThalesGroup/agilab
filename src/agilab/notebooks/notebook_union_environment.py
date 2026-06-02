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


def _iter_stage_entries(lab_stages: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    entries: list[dict[str, Any]] = []
    for module, stages in lab_stages.items():
        if module == "__meta__" or not isinstance(stages, list):
            continue
        for index, stage in enumerate(stages):
            if not isinstance(stage, dict):
                continue
            code = str(stage.get("C", "") or "")
            if not code.strip():
                continue
            entries.append(
                {
                    "module": str(module),
                    "module_index": index,
                    "description": str(stage.get("D", "") or ""),
                    "question": str(stage.get("Q", "") or ""),
                    "model": str(stage.get("M", "") or ""),
                    "code": code,
                    "runtime": _normalize_runtime(stage.get("R")),
                    "env": _normalize_env(stage.get("E")),
                }
            )
    return tuple(entries)


def _issue(location: str, message: str) -> NotebookUnionIssue:
    return NotebookUnionIssue(level="error", location=location, message=message)


def build_union_environment_plan(
    lab_stages: Mapping[str, Any],
    *,
    run_id: str = DEFAULT_RUN_ID,
) -> dict[str, Any]:
    stages = _iter_stage_entries(lab_stages)
    runtimes = sorted({stage["runtime"] for stage in stages})
    envs = sorted({stage["env"] for stage in stages})
    issues: list[NotebookUnionIssue] = []
    if not stages:
        issues.append(_issue("stages", "no executable pipeline stages found"))
    if len(runtimes) > 1:
        issues.append(_issue("runtime", f"mixed runtimes require supervisor export: {runtimes}"))
    if any(runtime != "runpy" for runtime in runtimes):
        issues.append(
            _issue("runtime", f"non-runpy runtime requires supervisor export: {runtimes}")
        )
    if len(envs) > 1:
        issues.append(
            _issue("environment", f"mixed stage environments require supervisor export: {envs}")
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
            "stage_count": len(stages),
            "runtime_count": len(runtimes),
            "environment_count": len(envs),
            "compatible": compatible,
            "issue_count": len(issues),
            "common_runtime": runtimes[0] if len(runtimes) == 1 else "",
            "common_environment": envs[0] if len(envs) == 1 else "",
        },
        "stages": list(stages),
        "issues": [issue.as_dict() for issue in issues],
        "provenance": {
            "executes_notebook": False,
            "supervisor_fallback_for_mixed_runtime": True,
            "preserves_stage_order": True,
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
    for index, stage in enumerate(plan.get("stages", []), start=1):
        if not isinstance(stage, dict):
            continue
        cells.append(
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    f"## Stage {index}: {stage.get('description', '')}\n",
                    f"- Runtime: `{stage.get('runtime', '')}`\n",
                    f"- Environment: `{stage.get('env', '') or 'current kernel'}`\n",
                ],
            }
        )
        cells.append(
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": str(stage.get("code", "") or "").splitlines(keepends=True),
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
                "stage_count": plan.get("summary", {}).get("stage_count"),
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
