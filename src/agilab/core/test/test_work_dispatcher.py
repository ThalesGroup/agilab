from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

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


def test_onerror_handles_permission_issue(monkeypatch):
    monkeypatch.setattr("os.access", lambda path, mode: False)
    captured: dict[str, str] = {}

    def fake_chmod(path, mode):
        captured["path"] = path

    monkeypatch.setattr("os.chmod", fake_chmod)

    WorkDispatcher._onerror(lambda _: None, "dummy_path", ("exc", "value", "tb"))

    assert captured["path"] == "dummy_path"


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
