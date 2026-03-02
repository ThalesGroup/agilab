from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import numpy as np

import agi_node.agi_dispatcher.agi_dispatcher as dispatcher_module
from agi_node.agi_dispatcher import WorkDispatcher


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
async def test_load_module_without_env_does_not_attempt_install(monkeypatch):
    monkeypatch.setattr(
        dispatcher_module.importlib,
        "import_module",
        lambda _name: (_ for _ in ()).throw(ModuleNotFoundError("No module named 'x'")),
    )
    with pytest.raises(ModuleNotFoundError):
        await WorkDispatcher._load_module("missing")
