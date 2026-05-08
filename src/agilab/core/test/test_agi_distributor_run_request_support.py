from __future__ import annotations

import pytest

from agi_cluster.agi_distributor import RunRequest, StageRequest
from agi_cluster.agi_distributor.run_request_support import RUN_STAGES_KEY


def test_run_request_separates_app_fields_from_dispatch_stages() -> None:
    request = RunRequest(
        params={"seed": 0},
        stages=[StageRequest(name="uav_graph_routing_ppo", args={"time_horizon": 16})],
        data_in="network_sim/pipeline",
        data_out="uav_graph_routing/pipeline",
        reset_target=False,
    )

    assert request.to_app_kwargs() == {
        "seed": 0,
        "data_in": "network_sim/pipeline",
        "data_out": "uav_graph_routing/pipeline",
        "reset_target": False,
    }
    assert request.to_dispatch_kwargs() == {
        "seed": 0,
        RUN_STAGES_KEY: [{"name": "uav_graph_routing_ppo", "args": {"time_horizon": 16}}],
        "data_in": "network_sim/pipeline",
        "data_out": "uav_graph_routing/pipeline",
        "reset_target": False,
    }


def test_run_request_rejects_legacy_top_level_args() -> None:
    with pytest.raises(ValueError, match="legacy key 'args'"):
        RunRequest(params={"args": [{"name": "demo", "args": {}}]})


def test_stage_request_requires_mapping_args() -> None:
    with pytest.raises(TypeError, match="StageRequest.args must be a mapping"):
        StageRequest(name="demo", args=["bad"])  # type: ignore[arg-type]


def test_run_request_with_execution_updates_only_runtime_controls() -> None:
    request = RunRequest(params={"seed": 0}, mode=0, scheduler="127.0.0.1")

    updated = request.with_execution(
        mode=4,
        workers={"127.0.0.1": 1},
        benchmark_best_single_node=True,
    )

    assert updated.params == {"seed": 0}
    assert updated.mode == 4
    assert updated.workers == {"127.0.0.1": 1}
    assert updated.benchmark_best_single_node is True
    assert request.mode == 0
    with pytest.raises(TypeError, match="Unknown execution field"):
        request.with_execution(params={"seed": 1})
