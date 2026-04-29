from __future__ import annotations

import json
import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import numpy as np

import agi_node.agi_dispatcher.agi_dispatcher as dispatcher_module
from agi_node.agi_dispatcher import WorkDispatcher
from agi_node.agi_dispatcher.agi_dispatcher import RUN_STEPS_KEY


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


def test_dispatcher_init_sets_class_args():
    payload = {"x": 1}
    WorkDispatcher(payload)
    assert WorkDispatcher.args == payload


@pytest.mark.asyncio
async def test_do_distrib_keeps_run_steps_out_of_constructor_and_injects_model_args(tmp_path, monkeypatch):
    plan_path = tmp_path / "plan.json"
    cluster_src = tmp_path / "cluster" / "src"
    cluster_src.mkdir(parents=True)
    env = SimpleNamespace(
        target="DemoWorkflow",
        target_class="DemoWorkflow",
        agi_cluster=cluster_src.parent,
        app_src=tmp_path / "app",
        distribution_tree=plan_path,
    )
    env.app_src.mkdir(exist_ok=True)

    constructor_args = []
    step_payload = [{"name": "train", "args": {"epochs": 2}}]

    class DemoWorkflow:
        def __init__(self, env, **kwargs):
            constructor_args.append(kwargs)
            self.args = SimpleNamespace(data_in=kwargs["data_in"], args=[])
            WorkDispatcher.args = {"data_in": kwargs["data_in"], "args": []}

        def build_distribution(self, assigned_workers):
            assert assigned_workers == {"127.0.0.1": 1}
            assert self.args.args == step_payload
            assert WorkDispatcher.args["args"] == step_payload
            return [["chunk"]], [{"meta": 1}], "partition", 1, 1.0

    monkeypatch.setattr(
        WorkDispatcher,
        "_load_module",
        AsyncMock(return_value=SimpleNamespace(DemoWorkflow=DemoWorkflow)),
    )

    loaded_workers, work_plan, metadata = await WorkDispatcher._do_distrib(
        env,
        {"127.0.0.1": 1},
        {"data_in": "network", RUN_STEPS_KEY: step_payload},
    )

    assert constructor_args == [{"data_in": "network"}]
    assert loaded_workers == {"127.0.0.1": 1}
    assert work_plan == [["chunk"]]
    assert metadata == [{"meta": 1}]


@pytest.mark.asyncio
async def test_do_distrib_rejects_run_steps_for_non_workflow_app(tmp_path, monkeypatch):
    plan_path = tmp_path / "plan.json"
    cluster_src = tmp_path / "cluster" / "src"
    cluster_src.mkdir(parents=True)
    env = SimpleNamespace(
        target="SimpleApp",
        target_class="SimpleApp",
        agi_cluster=cluster_src.parent,
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

    with pytest.raises(TypeError, match="does not accept RunRequest.steps"):
        await WorkDispatcher._do_distrib(
            env,
            {"127.0.0.1": 1},
            {"data_in": "network", RUN_STEPS_KEY: [{"name": "train", "args": {}}]},
        )


@pytest.mark.asyncio
async def test_do_distrib_builds_and_caches_plan(tmp_path, monkeypatch):
    plan_path = tmp_path / "plan.json"
    cluster_src = tmp_path / "cluster" / "src"
    cluster_src.mkdir(parents=True)
    env = SimpleNamespace(
        target="DemoWorker",
        target_class="DemoWorker",
        agi_cluster=cluster_src.parent,
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
async def test_do_distrib_preserves_multiple_worker_assignments(tmp_path, monkeypatch):
    plan_path = tmp_path / "plan.json"
    cluster_src = tmp_path / "cluster" / "src"
    cluster_src.mkdir(parents=True)
    env = SimpleNamespace(
        target="DemoWorker",
        target_class="DemoWorker",
        agi_cluster=cluster_src.parent,
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
async def test_do_distrib_rebuilds_stale_cache_serializes_dates_and_skips_empty_chunks(tmp_path, monkeypatch):
    plan_path = tmp_path / "plan.json"
    cluster_src = tmp_path / "cluster" / "src"
    cluster_src.mkdir(parents=True)
    env = SimpleNamespace(
        target="DemoWorker",
        target_class="DemoWorker",
        agi_cluster=cluster_src.parent,
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
    assert metadata[0]["day"] == datetime.date(2026, 4, 13)

    data = json.loads(plan_path.read_text(encoding="utf-8"))
    assert data["workers"] == workers
    assert data["target_args"] == args
    assert data["work_plan"] == [["chunk-a"], []]
    assert data["work_plan_metadata"][0]["day"] == "2026-04-13"
    assert data["work_plan_metadata"][0]["ts"].startswith("2026-04-13T09:30:00")


@pytest.mark.asyncio
async def test_do_distrib_raises_when_module_cannot_be_loaded(tmp_path, monkeypatch):
    plan_path = tmp_path / "plan.json"
    cluster_src = tmp_path / "cluster" / "src"
    cluster_src.mkdir(parents=True)
    env = SimpleNamespace(
        target="MissingWorker",
        target_class="MissingWorker",
        agi_cluster=cluster_src.parent,
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
    cluster_src = tmp_path / "cluster" / "src"
    cluster_src.mkdir(parents=True)
    env = SimpleNamespace(
        target="DemoWorker",
        target_class="DemoWorker",
        agi_cluster=cluster_src.parent,
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


def test_make_chunks_selects_optimal_or_fastest(monkeypatch):
    monkeypatch.setattr(WorkDispatcher, "_make_chunks_optimal", lambda *_args, **_kwargs: [["optimal"]])
    monkeypatch.setattr(WorkDispatcher, "_make_chunks_fastest", lambda *_args, **_kwargs: [["fastest"]])

    weights = [("a", 3), ("b", 1)]
    assert WorkDispatcher.make_chunks(2, weights, workers={"127.0.0.1": 1}, threshold=3) == [["optimal"]]
    assert WorkDispatcher.make_chunks(5, weights, workers={"127.0.0.1": 1}, threshold=3) == [["fastest"]]


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
    chunks = WorkDispatcher.make_chunks(1, [("single", 1)], workers={"127.0.0.1": 1})
    assert chunks == [[[("single", 1)]]]


def test_make_chunks_optimal_and_fastest_real_paths():
    subsets = [("a", 4), ("b", 3), ("c", 2)]
    weights = np.array([1, 1])
    optimal = WorkDispatcher._make_chunks_optimal(subsets.copy(), weights)
    fastest = WorkDispatcher._make_chunks_fastest(subsets.copy(), weights)

    assert len(optimal) == 2
    assert len(fastest) == 2
    assert sum(len(chunk) for chunk in optimal) == 3
    assert sum(len(chunk) for chunk in fastest) == 3


@pytest.mark.asyncio
async def test_load_module_requests_install(monkeypatch, tmp_path):
    import_calls = []

    def fake_import(name):
        import_calls.append(name)
        if len(import_calls) == 1:
            raise ModuleNotFoundError("No module named 'missing_pkg'")
        return "module"

    recorded: list[tuple[str, Path]] = []

    async def fake_run(cmd, app_path):
        recorded.append((cmd, app_path))

    monkeypatch.setattr(dispatcher_module.importlib, "import_module", fake_import)
    monkeypatch.setattr(dispatcher_module.AgiEnv, "run", fake_run)

    env = SimpleNamespace(
        uv="uv",
        active_app=tmp_path,
    )

    result = await WorkDispatcher._load_module("demo", env=env)

    assert result == "module"
    assert recorded == [("uv add --upgrade missing_pkg", tmp_path)]
    assert len(import_calls) == 2


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
