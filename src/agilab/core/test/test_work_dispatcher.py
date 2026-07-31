from __future__ import annotations

import json
import datetime
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import numpy as np

import agi_node.agi_dispatcher.agi_dispatcher as dispatcher_module
import agi_env.runtime.atomic_write_support as atomic_write_support
from agi_node.agi_dispatcher import WorkDispatcher
from agi_node.agi_dispatcher.agi_dispatcher import RUN_STAGES_KEY
from agi_node.agi_dispatcher.distribution_cache_support import (
    DISTRIBUTION_CACHE_SCHEMA,
    build_cache_context,
)


def test_convert_functions_to_names_handles_nested_callables():
    plan = {
        "root": [
            lambda: None,
            (
                "tuple",
                {"cb": lambda: None},
            ),
        ]
    }

    converted = WorkDispatcher._convert_functions_to_names(plan)

    assert converted["root"][0] == "<lambda>"
    assert converted["root"][1][1]["cb"] == "<lambda>"


def test_dispatcher_init_sets_instance_args_without_class_state():
    payload = {"x": 1}
    first = WorkDispatcher(payload)
    second = WorkDispatcher({"x": 2})

    assert first.args == payload
    assert second.args == {"x": 2}
    assert "args" not in WorkDispatcher.__dict__


def test_distribution_cache_declared_inputs_augment_inferred_paths(tmp_path):
    data_in = tmp_path / "data"
    planner_state = tmp_path / "planner.state"
    data_in.mkdir()
    planner_state.write_text("state", encoding="utf-8")
    target = SimpleNamespace(
        args=SimpleNamespace(data_in=data_in),
        distribution_cache_inputs=lambda: [planner_state],
        build_distribution=lambda _workers: None,
    )

    context = build_cache_context(target, capacities=None)

    assert context["inputs"]["roots"] == sorted(
        [data_in.resolve().as_posix(), planner_state.resolve().as_posix()]
    )


def test_distribution_cache_declared_inputs_can_replace_inferred_paths(tmp_path):
    broad_data_in = tmp_path / "workflow"
    planner_input = broad_data_in / "upstream"
    unrelated_output = broad_data_in / "downstream" / "huge.json"
    planner_input.mkdir(parents=True)
    unrelated_output.parent.mkdir(parents=True)
    (planner_input / "input.csv").write_text("value\n1\n", encoding="utf-8")
    unrelated_output.write_text("must not be fingerprinted", encoding="utf-8")
    target = SimpleNamespace(
        args=SimpleNamespace(data_in=broad_data_in),
        distribution_cache_inputs_mode="replace",
        distribution_cache_inputs=lambda: [planner_input],
        build_distribution=lambda _workers: None,
    )

    context = build_cache_context(target, capacities=None)

    assert context["inputs"]["roots"] == [planner_input.resolve().as_posix()]
    assert unrelated_output.as_posix() not in json.dumps(context)


def test_dispatcher_run_stage_contract_rejects_legacy_and_invalid_payloads():
    with pytest.raises(TypeError, match="Legacy dispatch key"):
        WorkDispatcher._split_dispatch_args({"_agilab_run_steps": []})
    assert WorkDispatcher._split_dispatch_args({RUN_STAGES_KEY: None}) == ({}, [])
    with pytest.raises(TypeError, match="must be a list"):
        WorkDispatcher._split_dispatch_args({RUN_STAGES_KEY: {"stage": "train"}})

    with pytest.raises(TypeError, match="does not accept RunRequest.stages"):
        WorkDispatcher._apply_run_stages(SimpleNamespace(args={}), [{"name": "train"}])


def test_dispatcher_onerror_handles_readonly_and_unclassified_failures(monkeypatch):
    calls: list[str] = []
    chmod_calls: list[tuple[str, int]] = []

    monkeypatch.setattr(dispatcher_module.os, "access", lambda *_args: False)
    monkeypatch.setattr(
        dispatcher_module.os,
        "chmod",
        lambda path, mode: chmod_calls.append((path, mode)),
    )
    WorkDispatcher._onerror(lambda path: calls.append(path), "locked.txt", (OSError, OSError("locked"), None))

    assert calls == ["locked.txt"]
    assert chmod_calls == [("locked.txt", dispatcher_module.stat.S_IWUSR)]

    monkeypatch.setattr(dispatcher_module.os, "access", lambda *_args: True)
    with pytest.raises(ValueError, match="bad remove"):
        WorkDispatcher._onerror(lambda _path: None, "bad.txt", (ValueError, ValueError("bad remove"), None))
    with pytest.raises(RuntimeError, match="failed to remove"):
        WorkDispatcher._onerror(lambda _path: None, "unknown.txt", ())


@pytest.mark.asyncio
async def test_do_distrib_keeps_run_stages_out_of_constructor_and_injects_model_args(tmp_path, monkeypatch):
    plan_path = tmp_path / "plan.json"
    cluster_src = tmp_path / "cluster" / "src"
    cluster_src.mkdir(parents=True)
    sentinel_path = tmp_path / "already-on-path"
    monkeypatch.setattr(dispatcher_module.sys, "path", [str(sentinel_path)], raising=False)
    env = SimpleNamespace(
        target="DemoWorkflow",
        target_class="DemoWorkflow",
        app_src=tmp_path / "app",
        distribution_tree=plan_path,
    )
    env.app_src.mkdir(exist_ok=True)

    constructor_args = []
    stage_payload = [{"name": "train", "args": {"epochs": 2}}]

    class DemoWorkflow:
        def __init__(self, env, **kwargs):
            constructor_args.append(kwargs)
            self.args = SimpleNamespace(data_in=kwargs["data_in"], args=[])

        def build_distribution(self, assigned_workers):
            assert assigned_workers == {"127.0.0.1": 1}
            assert self.args.args == stage_payload
            return [["chunk"]], [{"meta": 1}], "partition", 1, 1.0

    monkeypatch.setattr(
        WorkDispatcher,
        "_load_module",
        AsyncMock(return_value=SimpleNamespace(DemoWorkflow=DemoWorkflow)),
    )

    loaded_workers, work_plan, metadata = await WorkDispatcher._do_distrib(
        env,
        {"127.0.0.1": 1},
        {"data_in": "network", RUN_STAGES_KEY: stage_payload},
    )

    assert constructor_args == [{"data_in": "network"}]
    assert dispatcher_module.sys.path == [str(sentinel_path)]
    assert str(cluster_src) not in dispatcher_module.sys.path
    assert loaded_workers == {"127.0.0.1": 1}
    assert work_plan == [["chunk"]]
    assert metadata == [{"meta": 1}]


@pytest.mark.asyncio
async def test_do_distrib_rejects_run_stages_for_non_workflow_app(tmp_path, monkeypatch):
    plan_path = tmp_path / "plan.json"
    env = SimpleNamespace(
        target="SimpleApp",
        target_class="SimpleApp",
        app_src=tmp_path / "app",
        distribution_tree=plan_path,
    )
    env.app_src.mkdir(exist_ok=True)

    class SimpleApp:
        def __init__(self, env, **kwargs):
            self.args = SimpleNamespace(data_in=kwargs.get("data_in"))

        def build_distribution(self, assigned_workers):  # pragma: no cover - should not run
            return [["chunk"]], [{"meta": 1}], "partition", 1, 1.0

    monkeypatch.setattr(
        WorkDispatcher,
        "_load_module",
        AsyncMock(return_value=SimpleNamespace(SimpleApp=SimpleApp)),
    )

    with pytest.raises(TypeError, match="does not accept RunRequest.stages"):
        await WorkDispatcher._do_distrib(
            env,
            {"127.0.0.1": 1},
            {"data_in": "network", RUN_STAGES_KEY: [{"name": "train", "args": {}}]},
        )


@pytest.mark.asyncio
async def test_do_distrib_builds_and_caches_plan(tmp_path, monkeypatch):
    plan_path = tmp_path / "plan.json"
    env = SimpleNamespace(
        target="DemoWorker",
        target_class="DemoWorker",
        app_src=tmp_path / "app",
        distribution_tree=plan_path,
    )
    env.app_src.mkdir(exist_ok=True)

    workers = {"127.0.0.1": 1}
    args = {"alpha": 1}

    class DemoWorker:
        build_calls = 0

        def __init__(self, env, **kwargs):
            self.received_env = env
            self.received_args = kwargs

        def build_distribution(self, assigned_workers):
            type(self).build_calls += 1
            assert assigned_workers == workers
            return [["chunk"]], [{"meta": 1}], "partition", 1, 1.0

    module = SimpleNamespace(DemoWorker=DemoWorker)
    monkeypatch.setattr(WorkDispatcher, "_load_module", AsyncMock(return_value=module))

    loaded_workers, work_plan, metadata = await WorkDispatcher._do_distrib(env, workers, args)

    assert loaded_workers == {"127.0.0.1": 1}
    assert work_plan == [["chunk"]]
    assert metadata == [{"meta": 1}]
    assert DemoWorker.build_calls == 1

    data = json.loads(plan_path.read_text(encoding="utf-8"))
    assert data["workers"] == workers
    assert data["target_args"] == args

    await WorkDispatcher._do_distrib(env, workers, args)
    assert DemoWorker.build_calls == 1  # cached, no rebuild


@pytest.mark.asyncio
async def test_do_distrib_invalidates_cache_for_input_add_delete_and_content_mutation(
    tmp_path,
    monkeypatch,
):
    plan_path = tmp_path / "plan.json"
    input_dir = tmp_path / "inputs"
    input_dir.mkdir()
    first_input = input_dir / "a.txt"
    first_input.write_text("alpha", encoding="utf-8")
    planner_state = tmp_path / "planner.state"
    planner_state.write_text("one", encoding="utf-8")
    env = SimpleNamespace(
        target="InputWorker",
        target_class="InputWorker",
        app_src=tmp_path / "app",
        distribution_tree=plan_path,
    )
    env.app_src.mkdir()

    class InputWorker:
        build_calls = 0

        def __init__(self, _env, **kwargs):
            self.args = SimpleNamespace(data_in=Path(kwargs["data_in"]))
            self.planner_state = Path(kwargs["planner_state"])

        def distribution_cache_inputs(self):
            return [self.planner_state]

        def build_distribution(self, assigned_workers):
            type(self).build_calls += 1
            assert assigned_workers == {"127.0.0.1": 1}
            payload = [
                f"{path.name}:{path.read_text(encoding='utf-8')}"
                for path in sorted(self.args.data_in.glob("*.txt"))
            ]
            return (
                [[payload]],
                [[
                    {
                        "files": len(payload),
                        "planner_state": self.planner_state.read_text(encoding="utf-8"),
                    }
                ]],
                "file",
                len(payload),
                "items",
            )

    monkeypatch.setattr(
        WorkDispatcher,
        "_load_module",
        AsyncMock(return_value=SimpleNamespace(InputWorker=InputWorker)),
    )
    args = {"data_in": str(input_dir), "planner_state": str(planner_state)}
    workers = {"127.0.0.1": 1}

    first_result = await WorkDispatcher._do_distrib(env, workers, args)
    await WorkDispatcher._do_distrib(env, workers, args)
    assert InputWorker.build_calls == 1
    assert first_result[1] == [[["a.txt:alpha"]]]

    planner_state.write_text("two", encoding="utf-8")
    hook_result = await WorkDispatcher._do_distrib(env, workers, args)
    assert InputWorker.build_calls == 2
    assert hook_result[2][0][0]["planner_state"] == "two"

    second_input = input_dir / "b.txt"
    second_input.write_text("bravo", encoding="utf-8")
    added_result = await WorkDispatcher._do_distrib(env, workers, args)
    assert InputWorker.build_calls == 3
    assert added_result[1] == [[["a.txt:alpha", "b.txt:bravo"]]]

    first_input.write_text("ALPHA", encoding="utf-8")
    mutated_result = await WorkDispatcher._do_distrib(env, workers, args)
    assert InputWorker.build_calls == 4
    assert mutated_result[1][0][0][0] == "a.txt:ALPHA"

    second_input.unlink()
    deleted_result = await WorkDispatcher._do_distrib(env, workers, args)
    assert InputWorker.build_calls == 5
    assert deleted_result[1] == [[["a.txt:ALPHA"]]]


@pytest.mark.asyncio
async def test_do_distrib_recovers_from_corrupt_cache_and_publishes_current_schema(
    tmp_path,
    monkeypatch,
):
    plan_path = tmp_path / "plan.json"
    plan_path.write_text('{"work_plan":', encoding="utf-8")
    env = SimpleNamespace(
        target="DemoWorker",
        target_class="DemoWorker",
        app_src=tmp_path / "app",
        distribution_tree=plan_path,
    )
    env.app_src.mkdir()

    class DemoWorker:
        build_calls = 0

        def __init__(self, _env, **_kwargs):
            pass

        def build_distribution(self, _assigned_workers):
            type(self).build_calls += 1
            return [["fresh"]], [[{"fresh": True}]], "partition", 1, "items"

    monkeypatch.setattr(
        WorkDispatcher,
        "_load_module",
        AsyncMock(return_value=SimpleNamespace(DemoWorker=DemoWorker)),
    )

    result = await WorkDispatcher._do_distrib(
        env,
        {"127.0.0.1": 1},
        {"alpha": 1},
    )

    assert result[1] == [["fresh"]]
    assert DemoWorker.build_calls == 1
    assert json.loads(plan_path.read_text(encoding="utf-8"))["schema"] == DISTRIBUTION_CACHE_SCHEMA


@pytest.mark.asyncio
async def test_do_distrib_atomic_cache_publication_preserves_previous_plan_on_interruption(
    tmp_path,
    monkeypatch,
):
    plan_path = tmp_path / "plan.json"
    input_dir = tmp_path / "inputs"
    input_dir.mkdir()
    input_path = input_dir / "payload.txt"
    input_path.write_text("before", encoding="utf-8")
    env = SimpleNamespace(
        target="InputWorker",
        target_class="InputWorker",
        app_src=tmp_path / "app",
        distribution_tree=plan_path,
    )
    env.app_src.mkdir()

    class InputWorker:
        def __init__(self, _env, **kwargs):
            self.args = SimpleNamespace(data_in=Path(kwargs["data_in"]))

        def build_distribution(self, _assigned_workers):
            value = input_path.read_text(encoding="utf-8")
            return [[value]], [[{"value": value}]], "partition", 1, "items"

    monkeypatch.setattr(
        WorkDispatcher,
        "_load_module",
        AsyncMock(return_value=SimpleNamespace(InputWorker=InputWorker)),
    )
    args = {"data_in": str(input_dir)}
    workers = {"127.0.0.1": 1}
    await WorkDispatcher._do_distrib(env, workers, args)
    previous_cache = plan_path.read_bytes()
    input_path.write_text("after", encoding="utf-8")

    def _interrupt_publication(_operation):
        raise OSError("simulated interrupted publication")

    monkeypatch.setattr(
        atomic_write_support,
        "run_with_windows_file_sharing_retry",
        _interrupt_publication,
    )
    with pytest.raises(OSError, match="simulated interrupted publication"):
        await WorkDispatcher._do_distrib(env, workers, args)

    assert plan_path.read_bytes() == previous_cache
    assert list(tmp_path.glob(".plan.json.*.tmp")) == []


@pytest.mark.asyncio
async def test_do_distrib_invalidates_cache_when_planner_changes(tmp_path, monkeypatch):
    plan_path = tmp_path / "plan.json"
    env = SimpleNamespace(
        target="DemoWorker",
        target_class="DemoWorker",
        app_src=tmp_path / "app",
        distribution_tree=plan_path,
    )
    env.app_src.mkdir()
    build_calls = []

    class DemoWorker:
        def __init__(self, _env, **_kwargs):
            pass

        def build_distribution(self, _assigned_workers):
            build_calls.append("first")
            return [["first"]], [[]], "partition", 1, "items"

    monkeypatch.setattr(
        WorkDispatcher,
        "_load_module",
        AsyncMock(return_value=SimpleNamespace(DemoWorker=DemoWorker)),
    )
    workers = {"127.0.0.1": 1}
    first_result = await WorkDispatcher._do_distrib(env, workers, {})

    def _replacement_plan(self, _assigned_workers):
        build_calls.append("replacement")
        return [["replacement"]], [[]], "partition", 1, "items"

    monkeypatch.setattr(DemoWorker, "build_distribution", _replacement_plan)
    replacement_result = await WorkDispatcher._do_distrib(env, workers, {})

    assert first_result[1] == [["first"]]
    assert replacement_result[1] == [["replacement"]]
    assert build_calls == ["first", "replacement"]


@pytest.mark.asyncio
async def test_do_distrib_uses_capacity_ratio_and_invalidates_capacity_cache(
    tmp_path,
    monkeypatch,
):
    plan_path = tmp_path / "plan.json"
    env = SimpleNamespace(
        target="CapacityWorker",
        target_class="CapacityWorker",
        app_src=tmp_path / "app",
        distribution_tree=plan_path,
    )
    env.app_src.mkdir()

    class CapacityWorker:
        build_calls = 0

        def __init__(self, _env, **_kwargs):
            pass

        def build_distribution(self, assigned_workers):
            type(self).build_calls += 1
            chunks = WorkDispatcher.make_chunks(
                5,
                [(f"job-{index}", 1.0) for index in range(5)],
                workers=assigned_workers,
                threshold=0,
            )
            return chunks, [[] for _ in chunks], "job", 5, "items"

    monkeypatch.setattr(
        WorkDispatcher,
        "_load_module",
        AsyncMock(return_value=SimpleNamespace(CapacityWorker=CapacityWorker)),
    )
    workers = {"node-a": 2}

    first = await WorkDispatcher._do_distrib(
        env,
        workers,
        {},
        capacities=[1.0, 4.0],
    )
    cached = await WorkDispatcher._do_distrib(
        env,
        workers,
        {},
        capacities=[1.0, 4.0],
    )
    reversed_capacity = await WorkDispatcher._do_distrib(
        env,
        workers,
        {},
        capacities=[4.0, 1.0],
    )

    assert [len(chunk) for chunk in first[1]] == [1, 4]
    assert cached == first
    assert [len(chunk) for chunk in reversed_capacity[1]] == [4, 1]
    assert CapacityWorker.build_calls == 2


@pytest.mark.asyncio
async def test_do_distrib_preserves_multiple_worker_assignments(tmp_path, monkeypatch):
    plan_path = tmp_path / "plan.json"
    env = SimpleNamespace(
        target="DemoWorker",
        target_class="DemoWorker",
        app_src=tmp_path / "app",
        distribution_tree=plan_path,
    )
    env.app_src.mkdir(exist_ok=True)

    workers = {"192.168.20.111": 1, "192.168.20.130": 1}
    args = {"alpha": 1}

    class DemoWorker:
        def __init__(self, env, **kwargs):
            self.received_env = env
            self.received_args = kwargs

        def build_distribution(self, assigned_workers):
            assert assigned_workers == workers
            return [["chunk-a"], ["chunk-b"]], [{"meta": 1}, {"meta": 2}], "partition", 2, 1.0

    module = SimpleNamespace(DemoWorker=DemoWorker)
    monkeypatch.setattr(WorkDispatcher, "_load_module", AsyncMock(return_value=module))

    loaded_workers, work_plan, metadata = await WorkDispatcher._do_distrib(env, workers, args)

    assert loaded_workers == {"192.168.20.111": 1, "192.168.20.130": 1}
    assert work_plan == [["chunk-a"], ["chunk-b"]]
    assert metadata == [{"meta": 1}, {"meta": 2}]


@pytest.mark.asyncio
async def test_do_distrib_invalidates_cache_when_worker_slot_order_changes(
    tmp_path,
    monkeypatch,
):
    plan_path = tmp_path / "plan.json"
    env = SimpleNamespace(
        target="OrderedWorker",
        target_class="OrderedWorker",
        app_src=tmp_path / "app",
        distribution_tree=plan_path,
    )
    env.app_src.mkdir()

    class OrderedWorker:
        build_calls = 0

        def __init__(self, _env, **_kwargs):
            pass

        def build_distribution(self, assigned_workers):
            type(self).build_calls += 1
            slots = [
                worker
                for worker, count in assigned_workers.items()
                for _ in range(count)
            ]
            return [[worker] for worker in slots], [[] for _ in slots], "worker", 1, "items"

    monkeypatch.setattr(
        WorkDispatcher,
        "_load_module",
        AsyncMock(return_value=SimpleNamespace(OrderedWorker=OrderedWorker)),
    )

    first = await WorkDispatcher._do_distrib(env, {"worker-a": 1, "worker-b": 1}, {})
    reordered = await WorkDispatcher._do_distrib(
        env,
        {"worker-b": 1, "worker-a": 1},
        {},
    )

    assert first[1] == [["worker-a"], ["worker-b"]]
    assert reordered[1] == [["worker-b"], ["worker-a"]]
    assert OrderedWorker.build_calls == 2


@pytest.mark.asyncio
async def test_do_distrib_rebuilds_stale_cache_serializes_dates_and_skips_empty_chunks(tmp_path, monkeypatch):
    plan_path = tmp_path / "plan.json"
    env = SimpleNamespace(
        target="DemoWorker",
        target_class="DemoWorker",
        app_src=tmp_path / "app",
        distribution_tree=plan_path,
    )
    env.app_src.mkdir(exist_ok=True)

    cached = {
        "workers": {"127.0.0.1": 1},
        "target_args": {"alpha": 0},
        "work_plan": None,
        "work_plan_metadata": [],
    }
    plan_path.write_text(json.dumps(cached), encoding="utf-8")

    workers = {"127.0.0.1": 3}
    args = {"alpha": 1}

    class DemoWorker:
        build_calls = 0

        def __init__(self, env, **kwargs):
            self.received_env = env
            self.received_args = kwargs

        def build_distribution(self, assigned_workers):
            type(self).build_calls += 1
            assert assigned_workers == workers
            return (
                [["chunk-a"], []],
                [
                    {
                        "day": datetime.date(2026, 4, 13),
                        "ts": datetime.datetime(2026, 4, 13, 9, 30, 0),
                    }
                ],
                "partition",
                2,
                1.0,
            )

    monkeypatch.setattr(
        WorkDispatcher,
        "_load_module",
        AsyncMock(return_value=SimpleNamespace(DemoWorker=DemoWorker)),
    )

    loaded_workers, work_plan, metadata = await WorkDispatcher._do_distrib(env, workers, args)

    assert DemoWorker.build_calls == 1
    assert loaded_workers == {"127.0.0.1": 1}
    assert work_plan == [["chunk-a"]]
    # New contract: the rebuild path returns the same JSON-normalized payload
    # as a cache hit, so dates come back as isoformat strings on both paths.
    assert metadata[0]["day"] == "2026-04-13"

    data = json.loads(plan_path.read_text(encoding="utf-8"))
    assert data["workers"] == workers
    assert data["target_args"] == args
    assert data["work_plan"] == [["chunk-a"], []]
    assert data["work_plan_metadata"][0]["day"] == "2026-04-13"
    assert data["work_plan_metadata"][0]["ts"].startswith("2026-04-13T09:30:00")


@pytest.mark.asyncio
async def test_do_distrib_cache_miss_and_hit_return_identical_payloads(tmp_path, monkeypatch):
    # Regression: the rebuild path used to return the raw build_distribution
    # output (callables, tuples) while a cache hit returned the JSON-degraded
    # plan, so the same run dispatched different payloads on re-invocation.
    plan_path = tmp_path / "plan.json"
    env = SimpleNamespace(
        target="DemoWorker",
        target_class="DemoWorker",
        app_src=tmp_path / "app",
        distribution_tree=plan_path,
    )
    env.app_src.mkdir(exist_ok=True)

    workers = {"127.0.0.1": 1}
    args = {"alpha": 1}

    def my_step():
        return None

    class DemoWorker:
        def __init__(self, env, **kwargs):
            pass

        def build_distribution(self, assigned_workers):
            return [[("part-a", 2), my_step]], [[("part-a", 2)]], "partition", 1, 1.0

    monkeypatch.setattr(
        WorkDispatcher,
        "_load_module",
        AsyncMock(return_value=SimpleNamespace(DemoWorker=DemoWorker)),
    )

    miss_result = await WorkDispatcher._do_distrib(env, workers, args)
    hit_result = await WorkDispatcher._do_distrib(env, workers, args)

    assert miss_result == hit_result
    assert miss_result[1] == [[["part-a", 2], "my_step"]]


@pytest.mark.asyncio
async def test_do_distrib_filters_plan_and_metadata_in_lockstep(tmp_path, monkeypatch):
    # Regression: empty chunks were filtered out of the plan but not the
    # metadata, breaking the per-worker index alignment between the two.
    plan_path = tmp_path / "plan.json"
    env = SimpleNamespace(
        target="DemoWorker",
        target_class="DemoWorker",
        app_src=tmp_path / "app",
        distribution_tree=plan_path,
    )
    env.app_src.mkdir(exist_ok=True)

    workers = {"127.0.0.1": 3}

    class DemoWorker:
        def __init__(self, env, **kwargs):
            pass

        def build_distribution(self, assigned_workers):
            return (
                [[], ["w1"], ["w2"]],
                [[], ["m1"], ["m2"]],
                "partition",
                2,
                1.0,
            )

    monkeypatch.setattr(
        WorkDispatcher,
        "_load_module",
        AsyncMock(return_value=SimpleNamespace(DemoWorker=DemoWorker)),
    )

    _loaded, work_plan, metadata = await WorkDispatcher._do_distrib(env, workers, {"alpha": 1})

    assert work_plan == [["w1"], ["w2"]]
    assert metadata == [["m1"], ["m2"]]


@pytest.mark.asyncio
async def test_do_distrib_raises_when_module_cannot_be_loaded(tmp_path, monkeypatch):
    plan_path = tmp_path / "plan.json"
    env = SimpleNamespace(
        target="MissingWorker",
        target_class="MissingWorker",
        app_src=tmp_path / "app",
        distribution_tree=plan_path,
    )
    env.app_src.mkdir(exist_ok=True)

    monkeypatch.setattr(WorkDispatcher, "_load_module", AsyncMock(return_value=None))
    with pytest.raises(RuntimeError):
        await WorkDispatcher._do_distrib(env, {"127.0.0.1": 1}, {"alpha": 1})


@pytest.mark.asyncio
async def test_do_distrib_raises_for_nonserializable_cache_payload(tmp_path, monkeypatch):
    plan_path = tmp_path / "plan.json"
    env = SimpleNamespace(
        target="DemoWorker",
        target_class="DemoWorker",
        app_src=tmp_path / "app",
        distribution_tree=plan_path,
    )
    env.app_src.mkdir(exist_ok=True)

    class DemoWorker:
        def __init__(self, env, **kwargs):
            self.received_env = env
            self.received_args = kwargs

        def build_distribution(self, assigned_workers):
            assert assigned_workers == {"127.0.0.1": 1}
            return [["chunk"]], [{"bad": object()}], "partition", 1, 1.0

    monkeypatch.setattr(
        WorkDispatcher,
        "_load_module",
        AsyncMock(return_value=SimpleNamespace(DemoWorker=DemoWorker)),
    )

    with pytest.raises(TypeError, match="not serializable"):
        await WorkDispatcher._do_distrib(env, {"127.0.0.1": 1}, {"alpha": 1})


def test_onerror_handles_permission_issue(monkeypatch):
    monkeypatch.setattr("os.access", lambda path, mode: False)
    captured: dict[str, str] = {}

    def fake_chmod(path, mode):
        captured["path"] = path

    monkeypatch.setattr("os.chmod", fake_chmod)

    WorkDispatcher._onerror(lambda _: None, "dummy_path", ("exc", "value", "tb"))

    assert captured["path"] == "dummy_path"


def test_onerror_reraises_non_permission_issue(monkeypatch):
    monkeypatch.setattr("os.access", lambda path, mode: True)
    original = RuntimeError("remove failed")

    with pytest.raises(RuntimeError, match="remove failed") as caught:
        WorkDispatcher._onerror(lambda _: None, "dummy_path", (RuntimeError, original, None))

    assert caught.value is original


def test_make_chunks_selects_optimal_or_fastest(monkeypatch):
    monkeypatch.setattr(WorkDispatcher, "_make_chunks_optimal", lambda *_args, **_kwargs: [["optimal"]])
    monkeypatch.setattr(WorkDispatcher, "_make_chunks_fastest", lambda *_args, **_kwargs: [["fastest"]])

    small = [("a", 3), ("b", 1)]
    large = [("a", 3), ("b", 1), ("c", 2), ("d", 4)]

    # The gate follows the number of weighted works, not ``nchunk2``.
    assert WorkDispatcher.make_chunks(
        len(small), small, workers={"127.0.0.1": 1}, threshold=3
    ) == [["optimal"]]
    assert WorkDispatcher.make_chunks(
        len(large), large, workers={"127.0.0.1": 1}, threshold=3
    ) == [["fastest"]]

    # Regression: an understated ``nchunk2`` must not force a large work list down
    # the exponential path. This previously selected ``_make_chunks_optimal``.
    assert WorkDispatcher.make_chunks(
        1, large, workers={"127.0.0.1": 1}, threshold=3
    ) == [["fastest"]]


def test_make_chunks_understated_nchunk2_cannot_trigger_exponential_hang():
    """Run the real partitioner: an understated ``nchunk2`` must stay bounded.

    Before the gate was derived from ``len(weights)``, ``make_chunks(1, weights, ...)``
    routed any work list into the exponential branch-and-bound. Measured on this
    surface: 16 works completed in ~0.2s while 20 works exceeded 20s, so plan
    construction hung with no diagnostic. Nothing is monkeypatched here — the point
    is that the real code path terminates.
    """
    weights = [(f"job-{index}", float((index % 7) + 1)) for index in range(24)]

    started = time.perf_counter()
    chunks = WorkDispatcher.make_chunks(
        1, weights, workers={"127.0.0.1": 4}, threshold=12
    )
    elapsed = time.perf_counter() - started

    assert elapsed < 5.0, f"partitioning 24 works took {elapsed:.1f}s; exponential path reachable"
    # Every work must be placed exactly once, whichever algorithm ran.
    placed = [item for chunk in chunks for item in chunk]
    assert sorted(placed) == sorted(weights)


def test_make_chunks_uses_default_workers_and_builds_default_capacities(monkeypatch):
    captured = {}

    def _fake_optimal(weights, capacities):
        captured["weights"] = weights
        captured["capacities"] = capacities.tolist()
        return [["optimal"]]

    monkeypatch.setattr(WorkDispatcher, "_make_chunks_optimal", _fake_optimal)

    weights = [("a", 3), ("b", 1)]
    assert WorkDispatcher.make_chunks(2, weights, workers=None, capacities=None, threshold=3) == [["optimal"]]
    assert captured["weights"] == weights
    assert captured["capacities"] == [1]


def test_make_chunks_fastest_uses_float_capacity_normalized_lpt():
    weights = [(f"job-{index}", 1.0) for index in range(10)]

    chunks = WorkDispatcher._make_chunks_fastest(weights.copy(), (capacity for capacity in [1.0, 4.0]))

    assert [len(chunk) for chunk in chunks] == [2, 8]
    normalized_loads = [
        sum(weight for _name, weight in chunk) / capacity
        for chunk, capacity in zip(chunks, [1.0, 4.0])
    ]
    assert normalized_loads == pytest.approx([2.0, 2.0])


def test_make_chunks_fastest_does_not_mutate_caller_subsets():
    # Regression: the LPT scheduler used to sort the caller-supplied ``subsets``
    # list in place, mutating shared caller state.
    subsets = [("a", 1), ("b", 3), ("c", 2)]
    original = list(subsets)

    WorkDispatcher._make_chunks_fastest(subsets, [1.0, 1.0])

    assert subsets == original


@pytest.mark.parametrize("capacities", [[0], [-1], [float("inf")], [float("nan")]])
def test_make_chunks_rejects_invalid_capacities(capacities):
    with pytest.raises(ValueError, match="worker capacities must be finite positive values"):
        WorkDispatcher.make_chunks(
            2,
            [("a", 2), ("b", 1)],
            capacities=capacities,
            workers={"127.0.0.1": 1},
        )


def test_make_chunks_rejects_invalid_work_item_weights():
    with pytest.raises(ValueError, match="work item weights must be finite non-negative values"):
        WorkDispatcher._make_chunks_fastest([("bad", -1)], [1.0])


def test_make_chunks_single_weight_returns_nested_shape():
    # New contract: the single-weight branch returns the same per-worker shape
    # as the multi-weight branches (one chunk holding (label, size) tuples),
    # so consumers can always do `for label, size in chunk`.
    chunks = WorkDispatcher.make_chunks(1, [("single", 1)], workers={"127.0.0.1": 1})
    assert chunks == [[("single", 1)]]


def test_make_chunks_optimal_respects_non_unit_capacities():
    # Regression: the prune bound used to divide the already capacity-
    # normalized working sizes by the capacities a second time, pruning
    # branches that could still improve the assignment.
    chunks = WorkDispatcher._make_chunks_optimal(
        [("a", 8), ("b", 8), ("c", 1), ("d", 1)], [2, 2]
    )

    normalized_loads = sorted(
        sum(weight for _name, weight in chunk) / 2 for chunk in chunks
    )
    assert normalized_loads == [4.5, 4.5]


def test_make_chunks_optimal_and_fastest_real_paths():
    subsets = [("a", 4), ("b", 3), ("c", 2)]
    weights = np.array([1, 1])
    optimal = WorkDispatcher._make_chunks_optimal(subsets.copy(), weights)
    fastest = WorkDispatcher._make_chunks_fastest(subsets.copy(), weights)

    assert len(optimal) == 2
    assert len(fastest) == 2
    assert sum(len(chunk) for chunk in optimal) == 3
    assert sum(len(chunk) for chunk in fastest) == 3


def test_make_chunks_optimal_backtracks_without_deepcopy_or_input_mutation():
    subsets = [("small", 1), ("large", 4), ("mid", 3), ("other", 2)]
    original = list(subsets)

    chunks = WorkDispatcher._make_chunks_optimal(subsets, np.array([1, 1]))

    assert "deepcopy" not in WorkDispatcher._make_chunks_optimal.__code__.co_names
    assert subsets == original
    assert sorted(item for chunk in chunks for item in chunk) == sorted(original)
    assert sorted(sum(weight for _name, weight in chunk) for chunk in chunks) == [5, 5]


@pytest.mark.asyncio
async def test_load_module_refuses_runtime_auto_install_by_default(monkeypatch, tmp_path):
    def fake_import(_name):
        raise ModuleNotFoundError("No module named 'missing_pkg'", name="missing_pkg")

    async def fake_run(_cmd, _app_path):  # pragma: no cover - must not run
        raise AssertionError("runtime auto-install should be opt-in")

    monkeypatch.setattr(dispatcher_module.importlib, "import_module", fake_import)
    monkeypatch.setattr(dispatcher_module.AgiEnv, "run", fake_run)
    monkeypatch.delenv("AGILAB_RUNTIME_AUTO_INSTALL", raising=False)

    env = SimpleNamespace(
        uv="uv",
        active_app=tmp_path,
    )

    with pytest.raises(ModuleNotFoundError):
        await WorkDispatcher._load_module("demo", env=env)


@pytest.mark.asyncio
async def test_load_module_requests_install_when_explicitly_enabled(monkeypatch, tmp_path):
    import_calls = []

    def fake_import(name):
        import_calls.append(name)
        if len(import_calls) == 1:
            raise ModuleNotFoundError("No module named 'missing_pkg'", name="missing_pkg")
        return "module"

    recorded: list[tuple[str, Path]] = []
    events: list[dict[str, str]] = []

    async def fake_run(cmd, app_path):
        recorded.append((cmd, app_path))

    monkeypatch.setattr(dispatcher_module.importlib, "import_module", fake_import)
    monkeypatch.setattr(dispatcher_module.AgiEnv, "run", fake_run)
    monkeypatch.setenv("AGILAB_RUNTIME_AUTO_INSTALL", "1")

    env = SimpleNamespace(
        uv="uv",
        active_app=tmp_path,
        record_provenance_event=events.append,
    )

    result = await WorkDispatcher._load_module("demo", env=env)

    assert result == "module"
    assert recorded == [("uv add --upgrade missing_pkg", tmp_path)]
    assert events == [
        {
            "event": "runtime_dependency_auto_install",
            "module": "missing_pkg",
            "command": "uv add --upgrade missing_pkg",
            "app_path": str(tmp_path),
        }
    ]
    assert len(import_calls) == 2


@pytest.mark.asyncio
async def test_load_module_maps_import_name_to_distribution_name(monkeypatch, tmp_path):
    # Regression: ModuleNotFoundError carries the *import* name (e.g. "yaml"),
    # but `uv add` needs the PyPI distribution name (e.g. "pyyaml").
    import_calls = []

    def fake_import(name):
        import_calls.append(name)
        if len(import_calls) == 1:
            raise ModuleNotFoundError("No module named 'yaml'", name="yaml")
        return "module"

    recorded: list[tuple[str, Path]] = []

    async def fake_run(cmd, app_path):
        recorded.append((cmd, app_path))

    monkeypatch.setattr(dispatcher_module.importlib, "import_module", fake_import)
    monkeypatch.setattr(dispatcher_module.AgiEnv, "run", fake_run)
    monkeypatch.setenv("AGILAB_RUNTIME_AUTO_INSTALL", "1")

    env = SimpleNamespace(uv="uv", active_app=tmp_path)

    result = await WorkDispatcher._load_module("demo", env=env)

    assert result == "module"
    assert recorded == [("uv add --upgrade pyyaml", tmp_path)]


def test_missing_module_name_preserves_case():
    # Regression: PyPI/dist names are case-sensitive, so the auto-install name
    # must keep the original casing instead of being lowercased.
    exc = ModuleNotFoundError("No module named 'PyYAML'", name="PyYAML")
    assert WorkDispatcher._missing_module_name(exc) == "PyYAML"

    fallback = ModuleNotFoundError("No module named 'MixedCasePkg'")
    assert WorkDispatcher._missing_module_name(fallback) == "MixedCasePkg"


@pytest.mark.asyncio
async def test_load_module_uses_case_preserving_name_for_install(monkeypatch, tmp_path):
    import_calls = []

    def fake_import(name):
        import_calls.append(name)
        if len(import_calls) == 1:
            raise ModuleNotFoundError("No module named 'MixedCasePkg'", name="MixedCasePkg")
        return "module"

    recorded: list[tuple[str, Path]] = []

    async def fake_run(cmd, app_path):
        recorded.append((cmd, app_path))

    monkeypatch.setattr(dispatcher_module.importlib, "import_module", fake_import)
    monkeypatch.setattr(dispatcher_module.AgiEnv, "run", fake_run)
    monkeypatch.setenv("AGILAB_RUNTIME_AUTO_INSTALL", "1")

    env = SimpleNamespace(uv="uv", active_app=tmp_path)

    result = await WorkDispatcher._load_module("demo", env=env)

    assert result == "module"
    assert recorded == [("uv add --upgrade MixedCasePkg", tmp_path)]


@pytest.mark.asyncio
async def test_load_module_refuses_install_for_unsafe_module_name(monkeypatch, tmp_path):
    # Regression: the auto-install command is shell-routed, so a module name
    # carrying shell metacharacters must be refused instead of interpolated.
    def fake_import(_name):
        raise ModuleNotFoundError(
            "No module named 'evil; rm -rf ~'", name="evil; rm -rf ~"
        )

    async def fake_run(_cmd, _app_path):  # pragma: no cover - must not run
        raise AssertionError("unsafe module name must not reach the shell")

    monkeypatch.setattr(dispatcher_module.importlib, "import_module", fake_import)
    monkeypatch.setattr(dispatcher_module.AgiEnv, "run", fake_run)
    monkeypatch.setenv("AGILAB_RUNTIME_AUTO_INSTALL", "1")

    env = SimpleNamespace(uv="uv", active_app=tmp_path)

    with pytest.raises(ModuleNotFoundError):
        await WorkDispatcher._load_module("demo", env=env)


@pytest.mark.asyncio
async def test_load_module_with_package_and_path(monkeypatch, tmp_path):
    src_root = tmp_path / "workspace" / "src"
    src_root.mkdir(parents=True, exist_ok=True)
    sentinel = object()
    import_calls = []

    def fake_import(name):
        import_calls.append(name)
        return sentinel

    monkeypatch.setattr(dispatcher_module.importlib, "import_module", fake_import)
    before = set(dispatcher_module.sys.path)
    result = await WorkDispatcher._load_module("demo_module", package="demo_pkg", path=src_root)

    assert result is sentinel
    assert import_calls == ["demo_pkg.demo_module"]
    assert str(src_root.resolve()) in dispatcher_module.sys.path

    # Keep global sys.path tidy for subsequent tests.
    dispatcher_module.sys.path[:] = [p for p in dispatcher_module.sys.path if p in before]


@pytest.mark.asyncio
async def test_load_module_handles_file_path_and_direct_import(monkeypatch, tmp_path):
    module_file = tmp_path / "workspace" / "src" / "demo_module.py"
    module_file.parent.mkdir(parents=True, exist_ok=True)
    module_file.write_text("# demo", encoding="utf-8")

    sentinel = object()
    import_calls = []

    def fake_import(name):
        import_calls.append(name)
        return sentinel

    monkeypatch.setattr(dispatcher_module.importlib, "import_module", fake_import)
    before = set(dispatcher_module.sys.path)

    result = await WorkDispatcher._load_module("demo_module", path=module_file)

    assert result is sentinel
    assert import_calls == ["demo_module"]
    assert str(module_file.parent.resolve()) in dispatcher_module.sys.path
    assert str(module_file.parent.parent.parent.resolve()) in dispatcher_module.sys.path

    dispatcher_module.sys.path[:] = [p for p in dispatcher_module.sys.path if p in before]


@pytest.mark.asyncio
async def test_load_module_without_env_does_not_attempt_install(monkeypatch):
    monkeypatch.setattr(
        dispatcher_module.importlib,
        "import_module",
        lambda _name: (_ for _ in ()).throw(ModuleNotFoundError("No module named 'x'")),
    )
    with pytest.raises(ModuleNotFoundError):
        await WorkDispatcher._load_module("missing")


@pytest.mark.asyncio
async def test_load_module_ignores_sys_path_insertion_failures(monkeypatch, tmp_path):
    src_root = tmp_path / "workspace" / "src"
    src_root.mkdir(parents=True, exist_ok=True)
    sentinel = object()

    class _BrokenPath(list):
        def insert(self, index, value):
            raise OSError("insert failed")

    broken_path = _BrokenPath(dispatcher_module.sys.path)
    monkeypatch.setattr(dispatcher_module.sys, "path", broken_path, raising=False)
    monkeypatch.setattr(dispatcher_module.importlib, "import_module", lambda _name: sentinel)

    result = await WorkDispatcher._load_module("demo_module", package="demo_pkg", path=src_root)

    assert result is sentinel


@pytest.mark.asyncio
async def test_load_module_propagates_unexpected_sys_path_insert_bug(monkeypatch, tmp_path):
    src_root = tmp_path / "workspace" / "src"
    src_root.mkdir(parents=True, exist_ok=True)

    class _BrokenPath(list):
        def insert(self, index, value):
            raise RuntimeError("insert bug")

    broken_path = _BrokenPath(dispatcher_module.sys.path)
    monkeypatch.setattr(dispatcher_module.sys, "path", broken_path, raising=False)

    with pytest.raises(RuntimeError, match="insert bug"):
        await WorkDispatcher._load_module("demo_module", package="demo_pkg", path=src_root)


@pytest.mark.asyncio
async def test_load_module_ignores_path_resolution_failures(monkeypatch, tmp_path):
    src_root = tmp_path / "workspace" / "src"
    src_root.mkdir(parents=True, exist_ok=True)
    sentinel = object()
    original_resolve = Path.resolve

    def _patched_resolve(self, *args, **kwargs):
        if self == src_root:
            raise OSError("resolve failed")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(dispatcher_module.Path, "resolve", _patched_resolve, raising=False)
    monkeypatch.setattr(dispatcher_module.importlib, "import_module", lambda _name: sentinel)

    result = await WorkDispatcher._load_module("demo_module", package="demo_pkg", path=src_root)

    assert result is sentinel


@pytest.mark.asyncio
async def test_load_module_propagates_unexpected_path_resolution_bug(monkeypatch, tmp_path):
    src_root = tmp_path / "workspace" / "src"
    src_root.mkdir(parents=True, exist_ok=True)
    original_resolve = Path.resolve

    def _patched_resolve(self, *args, **kwargs):
        if self == src_root:
            raise RuntimeError("resolve bug")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(dispatcher_module.Path, "resolve", _patched_resolve, raising=False)

    with pytest.raises(RuntimeError, match="resolve bug"):
        await WorkDispatcher._load_module("demo_module", package="demo_pkg", path=src_root)
