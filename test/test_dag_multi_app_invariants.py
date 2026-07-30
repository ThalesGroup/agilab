# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Invariants that make the multi-app DAG demo a *multi-app* demo.

These are the contracts an app-consolidation pass will hit first. They were
discovered the expensive way: absorbing ``uav_queue_project`` into
``uav_relay_queue_project`` looked like removing a 95% duplicate, and only after
the merge was written did ~29 tests fail because

* :func:`multi_app_dag.validate_multi_app_dag` requires two *distinct* app ids,
  so a merged app makes the shared template single-app and invalid, and
* the queue-to-relay adapter is the only DAG that executes real managers and
  workers; its peer flight-to-weather is contract-only.

Both apps therefore have to keep existing as separate ids. Asserting that here
makes a future consolidation attempt fail immediately, with the reason, instead
of after a broad refactor.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agilab.dag import multi_app_dag
from agilab.dag.dag_execution_registry import (
    CONTROLLED_RUNNER_STATUS,
    REGISTERED_DAG_EXECUTION_ADAPTERS,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
BUILTIN_APPS = REPO_ROOT / "src" / "agilab" / "apps" / "builtin"


@pytest.mark.parametrize(
    "adapter", REGISTERED_DAG_EXECUTION_ADAPTERS, ids=lambda a: a.adapter_id
)
def test_registered_adapter_spans_at_least_two_apps(adapter) -> None:
    """A controlled adapter must chain distinct apps, or it is not a multi-app DAG.

    ``validate_multi_app_dag`` rejects a single-app DAG, so an adapter whose
    stages all name one app can never produce a valid template. Merging two
    apps that appear in the same adapter breaks this.
    """

    apps = {requirement.app for requirement in adapter.stage_requirements}
    assert len(apps) >= 2, (
        f"{adapter.adapter_id} maps every stage to {apps}; "
        "multi_app_dag.validate_multi_app_dag requires at least two distinct apps, "
        "so these apps cannot be consolidated while this adapter exists"
    )


@pytest.mark.parametrize(
    "adapter", REGISTERED_DAG_EXECUTION_ADAPTERS, ids=lambda a: a.adapter_id
)
def test_registered_adapter_apps_exist(adapter) -> None:
    for requirement in adapter.stage_requirements:
        assert (BUILTIN_APPS / requirement.app).is_dir(), (
            f"{adapter.adapter_id} requires built-in app {requirement.app}, which is "
            "missing; retiring an app referenced by a controlled adapter must retarget "
            "or remove the adapter in the same change"
        )


def test_real_stage_execution_capability_is_not_lost() -> None:
    """At least one adapter must still execute real managers and workers.

    ``controlled_real_stage_execution`` is a distinct intent from
    ``controlled_contract_stage_execution``: the former enters real app
    entrypoints, the latter validates a contract. Retiring the only adapter that
    provides it silently downgrades what the WORKFLOW page can prove.
    """

    real = [
        adapter
        for adapter in REGISTERED_DAG_EXECUTION_ADAPTERS
        if adapter.runner_status == CONTROLLED_RUNNER_STATUS
    ]
    assert real, (
        "no registered adapter provides controlled_real_stage_execution; a DAG that "
        "runs real app entrypoints is a distinct capability from a contract-only DAG "
        "and must be retargeted, not dropped"
    )


def test_validate_multi_app_dag_rejects_a_single_app_graph() -> None:
    """Pin the rule itself so the invariant above keeps meaning something."""

    payload = {
        "schema": "agilab.multi_app_dag.v1",
        "dag_id": "single-app",
        "label": "Single app",
        "nodes": [
            {"id": "a", "app": "only_project", "artifacts": [{"id": "x", "path": "x.json"}]},
            {"id": "b", "app": "only_project"},
        ],
        "edges": [{"from": "a", "to": "b", "artifact": "x"}],
    }
    result = multi_app_dag.validate_multi_app_dag(payload, repo_root=REPO_ROOT)
    assert not result.ok
    assert any("at least two apps" in issue.message for issue in result.issues)
