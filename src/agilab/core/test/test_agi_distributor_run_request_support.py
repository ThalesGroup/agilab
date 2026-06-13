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
    with pytest.raises(ValueError, match="legacy key 'steps'"):
        RunRequest(params={"steps": []})
    with pytest.raises(ValueError, match=RUN_STAGES_KEY):
        RunRequest(params={RUN_STAGES_KEY: []})


def test_stage_request_requires_mapping_args() -> None:
    with pytest.raises(ValueError, match="StageRequest.name"):
        StageRequest(name="", args={})
    with pytest.raises(TypeError, match="StageRequest.args must be a mapping"):
        StageRequest(name="demo", args=["bad"])  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="RunRequest.stages entries"):
        RunRequest(stages=["bad"])  # type: ignore[list-item]


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


def test_run_request_executor_kind_normalizes_auto_to_none() -> None:
    assert RunRequest().executor_kind is None
    assert RunRequest(executor_kind="auto").executor_kind is None
    assert RunRequest(executor_kind="").executor_kind is None
    assert RunRequest(executor_kind="  THREAD ").executor_kind == "thread"
    assert RunRequest(executor_kind="Process").executor_kind == "process"


def test_run_request_executor_kind_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="executor_kind"):
        RunRequest(executor_kind="gpu")
    with pytest.raises(TypeError, match="executor_kind"):
        RunRequest(executor_kind=5)  # type: ignore[arg-type]


def test_run_request_with_execution_accepts_executor_kind() -> None:
    request = RunRequest()
    updated = request.with_execution(executor_kind="thread")
    assert updated.executor_kind == "thread"
    assert request.executor_kind is None


def test_run_request_start_method_normalizes_spawn_and_default_to_none() -> None:
    assert RunRequest().start_method is None
    assert RunRequest(start_method="spawn").start_method is None
    assert RunRequest(start_method="").start_method is None
    assert RunRequest(start_method="default").start_method is None
    assert RunRequest(start_method="  ForkServer ").start_method == "forkserver"


def test_run_request_start_method_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="start_method"):
        RunRequest(start_method="fork")
    with pytest.raises(TypeError, match="start_method"):
        RunRequest(start_method=5)  # type: ignore[arg-type]


def test_run_request_with_execution_accepts_start_method() -> None:
    request = RunRequest()
    updated = request.with_execution(start_method="forkserver")
    assert updated.start_method == "forkserver"
    assert request.start_method is None
