from __future__ import annotations

import importlib.util
import hashlib
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest


REPORT_PATH = Path("tools/global_pipeline_app_dispatch_smoke_report.py").resolve()
CORE_PATH = Path("src/agilab/global_pipeline_app_dispatch_smoke.py").resolve()


def _load_report_module():
    spec = importlib.util.spec_from_file_location("global_pipeline_app_dispatch_smoke_report_test_module", REPORT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_core_module():
    spec = importlib.util.spec_from_file_location("global_pipeline_app_dispatch_smoke_test_module", CORE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_app_dispatch_smoke_report_executes_queue_and_relay(tmp_path: Path) -> None:
    module = _load_report_module()
    output_path = tmp_path / "app_dispatch_smoke.json"

    report = module.build_report(
        repo_root=Path.cwd(),
        output_path=output_path,
        workspace_path=tmp_path / "workspace",
    )

    assert report["report"] == "Global pipeline app dispatch smoke report"
    assert report["status"] == "pass"
    assert output_path.is_file()
    assert report["summary"]["schema"] == "agilab.global_pipeline_dispatch_state.v1"
    assert report["summary"]["smoke_schema"] == "agilab.global_pipeline_app_dispatch_smoke.v1"
    assert report["summary"]["run_id"] == "multi-app-dag-real-dispatch-smoke"
    assert report["summary"]["run_status"] == "completed"
    assert report["summary"]["persistence_format"] == "json"
    assert report["summary"]["round_trip_ok"] is True
    assert report["summary"]["unit_count"] == 2
    assert report["summary"]["completed_unit_ids"] == ["queue_baseline", "relay_followup"]
    assert report["summary"]["runnable_unit_ids"] == []
    assert report["summary"]["real_executed_unit_ids"] == ["queue_baseline", "relay_followup"]
    assert report["summary"]["readiness_only_unit_ids"] == []
    assert report["summary"]["real_execution_scope"] == "full_dag_smoke"
    assert report["summary"]["queue_packets_generated"] > 0
    assert report["summary"]["relay_packets_generated"] > 0
    assert report["summary"]["packets_generated"] > 0
    assert report["summary"]["available_artifact_ids"] == [
        "queue_metrics",
        "queue_reduce_summary",
        "relay_metrics",
        "relay_reduce_summary",
    ]
    assert {check["id"] for check in report["checks"]} == {
        "global_pipeline_app_dispatch_smoke_schema",
        "global_pipeline_app_dispatch_smoke_real_queue",
        "global_pipeline_app_dispatch_smoke_real_relay",
        "global_pipeline_app_dispatch_smoke_artifacts",
        "global_pipeline_app_dispatch_smoke_full_dag",
        "global_pipeline_app_dispatch_smoke_persistence",
        "global_pipeline_app_dispatch_smoke_provenance",
        "global_pipeline_app_dispatch_smoke_docs_reference",
    }


def test_app_dispatch_smoke_state_contains_real_artifacts(tmp_path: Path) -> None:
    module = _load_core_module()

    proof = module.persist_app_dispatch_smoke(
        repo_root=Path.cwd(),
        output_path=tmp_path / "app_dispatch_smoke.json",
        run_root=tmp_path / "workspace",
    )

    assert proof.ok is True
    assert proof.round_trip_ok is True
    state = proof.dispatch_state
    queue, relay = state["units"]
    queue_metrics = queue["real_execution"]["summary_metrics"]
    relay_metrics = relay["real_execution"]["summary_metrics"]
    workspace = Path(queue["real_execution"]["workspace"])
    assert state["provenance"]["real_app_execution"] is True
    assert state["provenance"]["real_execution_scope"] == "full_dag_smoke"
    assert state["summary"]["real_executed_unit_ids"] == ["queue_baseline", "relay_followup"]
    assert state["summary"]["readiness_only_unit_ids"] == []
    assert queue["dispatch_status"] == "completed"
    assert queue["execution_mode"] == "real_app_entry"
    assert queue_metrics["routing_policy"] == "queue_aware"
    assert queue_metrics["packets_generated"] > 0
    assert relay["dispatch_status"] == "completed"
    assert relay["execution_mode"] == "real_app_entry"
    assert relay["unblocked_by"] == ["queue_metrics"]
    assert [
        {key: row[key] for key in ("artifact", "path", "producer")}
        for row in relay["real_execution"]["consumed_artifacts"]
    ] == [
        {
            "artifact": "queue_metrics",
            "path": queue["real_execution"]["summary_metrics_path"],
            "producer": "queue_baseline",
        }
    ]
    assert relay_metrics["routing_policy"] == "queue_aware"
    assert relay_metrics["packets_generated"] > 0
    assert (workspace / queue["real_execution"]["summary_metrics_path"]).is_file()
    assert (workspace / queue["real_execution"]["reduce_artifact_path"]).is_file()
    assert (workspace / relay["real_execution"]["summary_metrics_path"]).is_file()
    assert (workspace / relay["real_execution"]["reduce_artifact_path"]).is_file()


def test_app_dispatch_smoke_executes_worker_class_selected_by_sdk(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from agi_node.agi_dispatcher import base_worker_runtime_support as runtime_support

    module = _load_core_module()
    sdk_load_worker = runtime_support.load_worker
    selections: list[tuple[str, str, int]] = []
    lifecycle: list[tuple[str, str]] = []

    def _load_selected_worker(env, mode, **kwargs):
        selections.append((env.target_worker, env.target_worker_class, mode))
        selected_class = sdk_load_worker(env, mode, **kwargs)
        package_name = env.target_worker

        class SelectedWorker(selected_class):
            def start(self):
                lifecycle.append((package_name, "start"))
                return super().start()

            def work_pool(self, source):
                lifecycle.append((package_name, "work_pool"))
                return super().work_pool(source)

            def work_done(self, result):
                lifecycle.append((package_name, "work_done"))
                return super().work_done(result)

        return SelectedWorker

    monkeypatch.setattr(runtime_support, "load_worker", _load_selected_worker)

    proof = module.persist_app_dispatch_smoke(
        repo_root=Path.cwd(),
        output_path=tmp_path / "app_dispatch_smoke.json",
        run_root=tmp_path / "workspace",
    )

    assert proof.ok is True
    assert proof.completed_unit_ids == ("queue_baseline", "relay_followup")
    assert selections == [
        ("uav_queue_worker", "UavQueueWorker", 0),
        ("uav_relay_queue_worker", "UavRelayQueueWorker", 0),
    ]
    assert lifecycle == [
        (package, step)
        for package in ("uav_queue_worker", "uav_relay_queue_worker")
        for step in ("start", "work_pool", "work_done")
    ]


def test_app_dispatch_smoke_ignores_stale_uav_modules(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from agi_node.agi_dispatcher import base_worker_runtime_support as runtime_support

    module = _load_core_module()
    stale_modules: dict[str, ModuleType] = {}
    for package_name in (
        "uav_queue",
        "uav_queue_worker",
        "uav_relay_queue",
        "uav_relay_queue_worker",
    ):
        stale_package = ModuleType(package_name)
        stale_package.__path__ = []
        stale_modules[package_name] = stale_package
        monkeypatch.setitem(sys.modules, package_name, stale_package)
        if package_name.endswith("_worker"):
            worker_module_name = f"{package_name}.{package_name}"
            stale_worker = ModuleType(worker_module_name)
            stale_modules[worker_module_name] = stale_worker
            monkeypatch.setitem(sys.modules, worker_module_name, stale_worker)

    sdk_load_worker = runtime_support.load_worker
    selected_packages: list[str] = []

    def _load_fresh_worker(env, mode, **kwargs):
        package_name = env.target_worker
        worker_module_name = f"{package_name}.{package_name}"
        assert sys.modules[package_name] is stale_modules[package_name]
        assert sys.modules[worker_module_name] is stale_modules[worker_module_name]
        worker_class = sdk_load_worker(env, mode, **kwargs)
        assert sys.modules[package_name] is not stale_modules[package_name]
        assert sys.modules[worker_module_name] is not stale_modules[worker_module_name]
        selected_packages.append(package_name)
        return worker_class

    monkeypatch.setattr(runtime_support, "load_worker", _load_fresh_worker)

    proof = module.persist_app_dispatch_smoke(
        repo_root=Path.cwd(),
        output_path=tmp_path / "app_dispatch_smoke.json",
        run_root=tmp_path / "workspace",
    )

    assert proof.ok is True
    assert proof.completed_unit_ids == ("queue_baseline", "relay_followup")
    assert selected_packages == ["uav_queue_worker", "uav_relay_queue_worker"]


def test_app_dispatch_smoke_sdk_load_failure_cannot_complete_or_run_relay(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from agi_node.agi_dispatcher import base_worker_runtime_support as runtime_support

    module = _load_core_module()
    selected_modules: list[tuple[str, str]] = []
    relay_calls: list[dict] = []
    output_path = tmp_path / "app_dispatch_smoke.json"
    run_root = tmp_path / "workspace"

    def _missing_selected_worker(module_name, class_name):
        selected_modules.append((module_name, class_name))
        raise ModuleNotFoundError("SDK-selected worker is unavailable")

    def _run_relay(**kwargs):
        relay_calls.append(kwargs)
        raise AssertionError("Relay must not execute after worker loading fails")

    monkeypatch.setattr(runtime_support, "load_module", _missing_selected_worker)
    monkeypatch.setattr(module, "run_relay_followup_app", _run_relay)

    with pytest.raises(RuntimeError, match="SDK-selected worker is unavailable"):
        module.persist_app_dispatch_smoke(
            repo_root=Path.cwd(),
            output_path=output_path,
            run_root=run_root,
        )

    assert selected_modules == [("uav_queue_worker.uav_queue_worker", "UavQueueWorker")]
    assert relay_calls == []
    assert not output_path.exists()
    assert not list((run_root / "export").rglob("*_summary_metrics.json"))
    assert not list((run_root / "export").rglob("reduce_summary_worker_*.json"))


def test_app_dispatch_smoke_moves_target_project_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_core_module()
    repo_root = Path.cwd()
    src_root = repo_root / "src" / "agilab" / "apps" / "builtin" / "uav_relay_queue_project" / "src"
    monkeypatch.setattr(
        module.sys,
        "path",
        ["shadow-package-root", str(src_root), "other-package-root"],
    )

    result = module._ensure_app_project_on_path(repo_root, "uav_relay_queue_project")

    assert result == src_root
    assert module.sys.path[:3] == [str(src_root), "shadow-package-root", "other-package-root"]
    assert module.sys.path.count(str(src_root)) == 1


def test_app_entrypoint_reuses_completed_token_without_repeating_callback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_core_module()
    callback_count = 0
    source = tmp_path / "run" / "scenario.json"
    source.parent.mkdir(parents=True)
    source.write_text("{}", encoding="utf-8")

    def _run_once(**_kwargs):
        nonlocal callback_count
        callback_count += 1
        return {
            "summary_metrics": {"stage_completed": 1},
            "source_scenario": str(source),
            "source_scenario_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        }

    monkeypatch.setattr(module, "_run_queue_family_app_once", _run_once)
    kwargs = {
        "repo_root": tmp_path,
        "run_root": tmp_path / "run",
        "project_name": "uav_queue_project",
        "manager_package": "uav_queue",
        "worker_package": "uav_queue_worker",
        "manager_class_name": "UavQueue",
        "args_class_name": "UavQueueArgs",
        "worker_class_name": "UavQueueWorker",
        "target": "queue_baseline",
        "app_entry": "fake",
        "idempotency_token": "direct-app:queue_baseline",
    }

    first = module._run_queue_family_app(**kwargs)
    second = module._run_queue_family_app(**kwargs)

    assert callback_count == 1
    assert second == first
    assert second["idempotency_token"] == "direct-app:queue_baseline"


def test_app_dispatch_smoke_report_handles_load_failure(tmp_path: Path) -> None:
    module = _load_report_module()
    missing = tmp_path / "missing.json"

    report = module.build_report(
        repo_root=Path.cwd(),
        dag_path=missing,
        output_path=tmp_path / "app_dispatch_smoke.json",
        workspace_path=tmp_path / "workspace",
    )

    assert report["status"] == "fail"
    assert report["checks"] == [
        {
            "details": {
                "error": f"[Errno 2] No such file or directory: '{missing}'",
            },
            "evidence": [str(missing)],
            "id": "global_pipeline_app_dispatch_smoke_load",
            "label": "Global pipeline app dispatch smoke load",
            "status": "fail",
            "summary": "global pipeline app dispatch smoke could not be persisted",
        }
    ]


def test_app_dispatch_smoke_helper_properties_handle_malformed_state(tmp_path: Path) -> None:
    module = _load_core_module()
    issue = module._issue("state", "bad")
    proof = module.AppDispatchSmokeProof(
        ok=False,
        issues=(issue,),
        path=str(tmp_path / "state.json"),
        dispatch_state={
            "summary": {
                "real_executed_unit_ids": ["queue", "", None],
                "readiness_only_unit_ids": ["relay", ""],
            },
            "units": "bad",
            "artifacts": "bad",
            "events": "bad",
        },
        reloaded_state={},
    )

    assert issue.as_dict() == {"level": "error", "location": "state", "message": "bad"}
    assert proof.round_trip_ok is False
    assert proof.completed_unit_ids == ()
    assert proof.runnable_unit_ids == ()
    assert proof.available_artifact_ids == ()
    assert proof.summary_metric_paths == ()
    assert proof.event_count == 0
    assert proof.packet_count == 0
    assert proof.as_dict()["issues"] == [issue.as_dict()]
    assert module._unit_rows({"units": "bad"}) == ()
    assert module._queue_metrics({"units": [{"id": module.QUEUE_UNIT_ID, "real_execution": {"summary_metrics": "bad"}}]}) == {}
    assert module._queue_metrics({"units": []}) == {}
    assert module._relative(tmp_path / "outside.txt", tmp_path / "root") == str(tmp_path / "outside.txt")


def test_app_dispatch_smoke_persist_reports_round_trip_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_core_module()
    state = {
        "schema": "agilab.global_pipeline_dispatch_state.v1",
        "summary": {},
        "units": [],
        "artifacts": [],
        "events": [],
    }
    monkeypatch.setattr(module, "build_app_dispatch_smoke_state", lambda **_kwargs: state)
    monkeypatch.setattr(module, "load_dispatch_state", lambda _path: {"changed": True})

    proof = module.persist_app_dispatch_smoke(
        repo_root=Path.cwd(),
        output_path=tmp_path / "smoke.json",
    )

    assert proof.ok is False
    assert proof.issues[0].location == "persistence.round_trip"


def test_app_dispatch_smoke_queue_runner_requires_expected_outputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from agi_node.agi_dispatcher import base_worker_runtime_support as runtime_support

    module = _load_core_module()
    env = module._make_env(tmp_path / "run", target="target")
    source = Path(env.AGI_LOCAL_SHARE) / "scenario.json"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("{}", encoding="utf-8")

    class FakeManager:
        def __init__(self, _env, *, args):
            args.data_in = source.parent
            args.model_dump = lambda mode="json": {}
            self.args = args

        def reset_data(self):
            return None

        def init(self):
            return None

    class FakeWorker:
        def start(self):
            self.data_out = tmp_path / "worker-out"
            return None

        def work_pool(self, _source):
            return {"summary_metrics": {"artifact_stem": "missing"}}

        def work_done(self, _result):
            return None

    monkeypatch.setattr(module.importlib, "import_module", lambda _name: module.SimpleNamespace(
        UavQueue=FakeManager,
        UavQueueArgs=lambda **_kwargs: module.SimpleNamespace(),
    ))
    monkeypatch.setattr(
        runtime_support, "load_worker", lambda _env, _mode, **_kwargs: FakeWorker
    )

    with pytest.raises(RuntimeError, match="summary metrics"):
        module._run_queue_family_app(
            repo_root=tmp_path,
            run_root=tmp_path / "run",
            project_name="uav_queue_project",
            manager_package="uav_queue",
            worker_package="uav_queue",
            manager_class_name="UavQueue",
            args_class_name="UavQueueArgs",
            worker_class_name="UavQueueWorker",
            target="target",
            app_entry="fake",
            idempotency_token="missing-summary:queue_baseline",
        )


def test_app_dispatch_smoke_queue_runner_requires_reduce_artifact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from agi_node.agi_dispatcher import base_worker_runtime_support as runtime_support

    module = _load_core_module()
    run_root = tmp_path / "run"
    source = run_root / "share" / "scenario.json"
    source.parent.mkdir(parents=True)
    source.write_text("{}", encoding="utf-8")

    class FakeManager:
        def __init__(self, _env, *, args):
            args.data_in = source.parent
            args.model_dump = lambda mode="json": {}
            self.args = args

    class FakeWorker:
        def start(self):
            self.data_out = tmp_path / "worker-out"

        def work_pool(self, _source):
            return {"summary_metrics": {"artifact_stem": "missing-reduce"}}

        def work_done(self, result):
            export_root = run_root / "export" / "target" / "queue_analysis" / "missing-reduce"
            export_root.mkdir(parents=True)
            (export_root / "missing-reduce_summary_metrics.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(module.importlib, "import_module", lambda _name: module.SimpleNamespace(
        UavQueue=FakeManager,
        UavQueueArgs=lambda **_kwargs: module.SimpleNamespace(),
    ))
    monkeypatch.setattr(
        runtime_support, "load_worker", lambda _env, _mode, **_kwargs: FakeWorker
    )

    with pytest.raises(RuntimeError, match="reduce artifact"):
        module._run_queue_family_app(
            repo_root=tmp_path,
            run_root=run_root,
            project_name="uav_queue_project",
            manager_package="uav_queue",
            worker_package="uav_queue",
            manager_class_name="UavQueue",
            args_class_name="UavQueueArgs",
            worker_class_name="UavQueueWorker",
            target="target",
            app_entry="fake",
            idempotency_token="missing-reduce:queue_baseline",
        )


def test_relay_rejects_unreadable_upstream_context_before_loading_worker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from agi_node.agi_dispatcher import base_worker_runtime_support as runtime_support

    module = _load_core_module()
    path = tmp_path / "queue_summary.json"
    path.write_text("{invalid JSON", encoding="utf-8")
    selections = []
    sdk_loader = runtime_support.load_worker

    def load_worker(*args, **kwargs):
        selections.append(args[0].target_worker)
        return sdk_loader(*args, **kwargs)

    monkeypatch.setattr(runtime_support, "load_worker", load_worker)
    with pytest.raises(ValueError, match="queue_metrics"):
        module.run_relay_followup_app(
            repo_root=Path.cwd(),
            run_root=tmp_path / "relay",
            queue_result={"summary_metrics_path": str(path)},
            idempotency_token="invalid-context:relay",
        )
    assert selections == []


@pytest.mark.parametrize(
    "contract",
    [
        {"command": ["ignored"]},
        {"stages": ["ignored"]},
        {"params": {"unknown_arg": 1}},
        {"params": {"sim_time_s": float("nan")}},
        {"params": {"routing_policy": "invalid"}},
        {"params": {"nfile": 2}},
        {"params": {"files": "../*.json"}},
        {"data_in": "/tmp/external-input"},
        {"data_out": "/tmp/external-output"},
        {"data_out": "../outside"},
        {"data_out": "."},
        {"data_in": "same", "data_out": "same"},
        {"data_in": "parent/input", "data_out": "parent", "reset_target": True},
        {"entrypoint": "another_project.run"},
    ],
)
def test_authored_uav_invalid_settings_do_not_select_worker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    contract: dict,
) -> None:
    from agi_node.agi_dispatcher import base_worker_runtime_support as runtime_support

    module = _load_core_module()
    calls = []
    monkeypatch.setattr(
        runtime_support, "load_worker", lambda *a, **kw: calls.append(a)
    )
    with pytest.raises((ValueError, RuntimeError)):
        module.run_queue_baseline_app(
            repo_root=Path.cwd(),
            run_root=tmp_path / "run",
            execution_contract=contract,
            idempotency_token="invalid-settings:queue",
        )
    assert calls == []
    assert not (tmp_path / "run" / "share").exists()


@pytest.mark.parametrize("which", ["data_in", "data_out"])
def test_authored_uav_rejects_symlink_escape_before_manager_seeding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    which: str,
) -> None:
    from agi_node.agi_dispatcher import base_worker_runtime_support as runtime_support

    module = _load_core_module()
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_text("preserve", encoding="utf-8")
    share = tmp_path / "run" / "share"
    share.mkdir(parents=True)
    (share / "escape").symlink_to(outside, target_is_directory=True)
    calls = []
    monkeypatch.setattr(
        runtime_support, "load_worker", lambda *a, **kw: calls.append(a)
    )
    with pytest.raises(RuntimeError, match="owned share|contains a symlink"):
        module.run_queue_baseline_app(
            repo_root=Path.cwd(),
            run_root=tmp_path / "run",
            execution_contract={which: "escape", "reset_target": True},
            idempotency_token="symlink-escape:queue",
        )
    assert calls == []
    assert list(outside.iterdir()) == [sentinel]
    assert sentinel.read_text(encoding="utf-8") == "preserve"


def test_authored_uav_uses_typed_parameters_paths_and_preserves_reset_false(
    tmp_path: Path,
) -> None:
    module = _load_core_module()
    run_root = tmp_path / "run"
    sentinel = run_root / "share" / "authored/results/sentinel"
    sentinel.parent.mkdir(parents=True)
    sentinel.write_text("preserve", encoding="utf-8")
    params = {
        "routing_policy": "queue_aware",
        "sim_time_s": 3.0,
        "sampling_interval_s": 0.25,
        "source_rate_pps": 7.0,
        "queue_weight": 8.0,
        "random_seed": 19,
    }
    result = module.run_queue_baseline_app(
        repo_root=Path.cwd(),
        run_root=run_root,
        execution_contract={
            "params": params,
            "data_in": "authored/scenarios",
            "data_out": "authored/results",
            "reset_target": False,
        },
        idempotency_token="authored-settings:queue",
    )
    assert {key: result["summary_metrics"][key] for key in params} == params
    assert result["effective_args"]["data_in"] == str(
        run_root / "share/authored/scenarios"
    )
    assert result["effective_args"]["data_out"] == str(
        run_root / "share/authored/results"
    )
    assert result["effective_args"]["reset_target"] is False
    assert sentinel.read_text(encoding="utf-8") == "preserve"


@pytest.mark.parametrize("drift", ["contract", "scenario"])
def test_queue_same_token_rejects_changed_inputs_without_repeating_worker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    drift: str,
) -> None:
    from agi_node.agi_dispatcher import base_worker_runtime_support as runtime_support

    module = _load_core_module()
    loader = runtime_support.load_worker
    calls = []

    def select_worker(*args, **kwargs):
        calls.append(args[0].target_worker)
        return loader(*args, **kwargs)

    monkeypatch.setattr(runtime_support, "load_worker", select_worker)
    kwargs = dict(
        repo_root=Path.cwd(),
        run_root=tmp_path / "run",
        execution_contract={"params": {"sim_time_s": 2.0}},
        idempotency_token="same-token:queue",
    )
    result = module.run_queue_baseline_app(**kwargs)
    if drift == "contract":
        kwargs["execution_contract"] = {"params": {"sim_time_s": 3.0}}
    else:
        source = kwargs["run_root"] / result["source_scenario"]
        source.write_bytes(source.read_bytes() + b" ")
    with pytest.raises(ValueError, match="different"):
        module.run_queue_baseline_app(**kwargs)
    assert calls == ["uav_queue_worker"]


@pytest.fixture
def scenario_cache_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from agi_node.agi_dispatcher import base_worker_runtime_support as runtime_support

    implementation_path = CORE_PATH.parent / "global_pipeline" / CORE_PATH.name
    spec = importlib.util.spec_from_file_location(
        "scenario_cache_app_dispatch_smoke_test_module", implementation_path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    assert Path(module.__file__).resolve() == implementation_path
    run_root = tmp_path / "run"
    source = run_root / "share/input/scenario.json"
    source.parent.mkdir(parents=True)
    original = b'{"version":1}'
    source.write_bytes(original)
    case = module.SimpleNamespace(
        module=module, source=source, original=original, trace=[], consumed=[],
        executed_paths=[], hooks={}, phase="", mutate=None,
    )
    args = module.SimpleNamespace(
        data_in=source.parent, data_out=run_root / "share/results", files="*.json"
    )
    args.model_dump = lambda **_kwargs: {
        "data_in": str(args.data_in), "data_out": str(args.data_out)
    }

    def mutate_at(phase):
        if phase in case.hooks:
            case.hooks[phase]()
        if case.phase == phase and case.mutate is not None:
            case.mutate()

    class FakeManager:
        def __init__(self, _env, *, args):
            self.args = args

    class FakeWorker:
        def start(self):
            case.trace.append("start")
            assert Path(self.args["data_in"]) == source.parent
            assert Path(self.args["data_out"]) == args.data_out
            self.data_out = args.data_out
            mutate_at("start")

        def work_pool(self, path):
            case.trace.append("pool")
            case.executed_paths.append(Path(path))
            case.consumed.append(Path(path).read_bytes())
            mutate_at("pool")
            return {"summary_metrics": {"artifact_stem": "fixture"}}

        def work_done(self, result):
            case.trace.append("done")
            output = self.env.AGILAB_EXPORT_ABS / self.env.target / "queue_analysis/fixture"
            output.mkdir(parents=True)
            (output / "fixture_summary_metrics.json").write_text(
                json.dumps(result["summary_metrics"]), encoding="utf-8"
            )
            (output / "reduce_summary_worker_0.json").write_text("{}", encoding="utf-8")
            mutate_at("done")

    def load_worker(_env, mode, **_kwargs):
        assert mode == 0
        case.trace.append("load")
        return FakeWorker

    monkeypatch.setattr(module, "_ensure_app_project_on_path", lambda *_args: None)
    monkeypatch.setattr(module, "_drop_app_module_cache", lambda *_args: None)
    monkeypatch.setattr(module, "_queue_family_args", lambda *_args, **_kwargs: args)
    monkeypatch.setattr(module.importlib, "import_module", lambda _name: module.SimpleNamespace(
        FixtureManager=FakeManager, FixtureArgs=object,
    ))
    monkeypatch.setattr(runtime_support, "load_worker", load_worker)

    def run():
        return module._run_queue_family_app(
            repo_root=tmp_path, run_root=run_root, project_name="fixture_project",
            manager_package="fixture", worker_package="fixture_worker",
            manager_class_name="FixtureManager", args_class_name="FixtureArgs",
            worker_class_name="FixtureWorker", target="fixture", app_entry="fixture",
            idempotency_token="scenario-fixture", execution_contract={},
        )

    def ledger_path():
        paths = sorted((run_root / ".agilab-idempotency").glob("*.json"))
        assert len(paths) == 1
        return paths[0]

    def ledger():
        return json.loads(ledger_path().read_text(encoding="utf-8"))

    case.run = run
    case.ledger = ledger
    case.ledger_path = ledger_path
    return case


@pytest.mark.parametrize("phase", ["start", "pool", "done"])
@pytest.mark.parametrize("drift", ["change", "delete"])
def test_scenario_cache_rejects_source_drift_during_execution(
    scenario_cache_case, phase: str, drift: str,
) -> None:
    case = scenario_cache_case
    case.phase = phase
    case.mutate = (
        (lambda: case.source.write_bytes(b'{"version":2}'))
        if drift == "change" else case.source.unlink
    )

    with pytest.raises(RuntimeError):
        case.run()

    recorded = case.ledger()
    assert recorded["status"] == "failed"
    assert "result" not in recorded
    assert case.trace == ["load", "start", "pool", "done"]
    trace = list(case.trace)
    with pytest.raises(RuntimeError, match="already failed"):
        case.run()
    assert case.trace == trace
    assert all(not path.exists() for path in case.executed_paths)


@pytest.mark.parametrize("raw", [b'{"version":1}', b""])
def test_scenario_cache_binds_initial_bytes_and_reuses_completed_token(
    scenario_cache_case, raw: bytes,
) -> None:
    case = scenario_cache_case
    case.source.write_bytes(raw)
    first = case.run()
    assert case.run() == first
    assert first["source_scenario_sha256"] == hashlib.sha256(raw).hexdigest()
    assert case.consumed == [raw]
    assert case.trace == ["load", "start", "pool", "done"]
    assert case.ledger()["result"]["source_scenario_sha256"] == first["source_scenario_sha256"]
    assert case.executed_paths[0] != case.source
    assert case.executed_paths[0].name == case.source.name
    assert not case.executed_paths[0].exists()


def test_scenario_cache_worker_consumes_snapshot_despite_source_change_and_restore(
    scenario_cache_case,
) -> None:
    case = scenario_cache_case
    case.hooks["start"] = lambda: case.source.write_bytes(b'{"version":2}')
    case.hooks["done"] = lambda: case.source.write_bytes(case.original)

    result = case.run()

    assert case.consumed == [case.original]
    assert result["source_scenario_sha256"] == hashlib.sha256(case.original).hexdigest()
    assert case.source.read_bytes() == case.original
    assert not case.executed_paths[0].exists()
    assert case.run() == result
    assert case.trace == ["load", "start", "pool", "done"]


@pytest.mark.parametrize("drift", ["change", "delete"])
def test_scenario_cache_rejects_modified_execution_snapshot(
    scenario_cache_case, drift: str,
) -> None:
    case = scenario_cache_case
    case.phase = "done"

    def mutate_snapshot():
        path = case.executed_paths[0]
        path.chmod(0o600)
        if drift == "change":
            path.write_bytes(b'{"version":2}')
        else:
            path.unlink()

    case.mutate = mutate_snapshot
    with pytest.raises(RuntimeError):
        case.run()
    assert case.ledger()["status"] == "failed"
    assert "result" not in case.ledger()
    assert all(not path.exists() for path in case.executed_paths)


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_scenario_sha256", "missing"),
        ("source_scenario_sha256", None),
        ("source_scenario_sha256", ""),
        ("source_scenario_sha256", False),
        ("source_scenario_sha256", "g" * 64),
        ("source_scenario_sha256", "f" * 63),
        ("source_scenario", "missing"),
        ("source_scenario", None),
        ("source_scenario", ""),
        ("source_scenario", 42),
    ],
)
def test_scenario_cache_legacy_incomplete_provenance_is_not_rebaselined(
    scenario_cache_case, field: str, value,
) -> None:
    case = scenario_cache_case
    case.run()
    recorded = case.ledger()
    if value == "missing":
        del recorded["result"][field]
    else:
        recorded["result"][field] = value
    path = case.ledger_path()
    path.write_text(json.dumps(recorded), encoding="utf-8")
    previous = path.read_bytes()

    with pytest.raises(ValueError, match="provenance"):
        case.run()
    assert path.read_bytes() == previous
    assert case.trace == ["load", "start", "pool", "done"]


@pytest.mark.parametrize("missing_hash", [False, True])
def test_scenario_cache_incomplete_new_receipt_never_completes(
    scenario_cache_case, monkeypatch: pytest.MonkeyPatch, missing_hash: bool,
) -> None:
    case = scenario_cache_case
    receipt = {"source_scenario": str(case.source)}
    if not missing_hash:
        receipt["source_scenario_sha256"] = None
    monkeypatch.setattr(
        case.module, "_run_queue_family_app_once", lambda **_kwargs: receipt
    )
    with pytest.raises(RuntimeError, match="provenance"):
        case.run()
    assert case.ledger()["status"] == "failed"
    assert "result" not in case.ledger()
    assert case.trace == []


@pytest.mark.parametrize("missing", ["file", "directory"])
def test_scenario_cache_missing_input_never_selects_worker(
    scenario_cache_case, missing: str,
) -> None:
    case = scenario_cache_case
    case.source.unlink()
    if missing == "directory":
        case.source.parent.rmdir()

    with pytest.raises(RuntimeError, match="No scenario"):
        case.run()
    assert case.trace == []
    assert case.ledger()["status"] == "failed"


def test_scenario_cache_source_disappearing_before_read_never_selects_worker(
    scenario_cache_case, monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = scenario_cache_case
    read_bytes = Path.read_bytes

    def remove_before_read(path):
        if path == case.source:
            path.unlink(missing_ok=True)
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", remove_before_read)
    with pytest.raises(RuntimeError):
        case.run()
    assert case.trace == []
    assert case.ledger()["status"] == "failed"


@pytest.mark.parametrize("drift", ["change", "delete"])
def test_scenario_cache_replay_rejects_changed_or_deleted_source_without_worker(
    scenario_cache_case, drift: str,
) -> None:
    case = scenario_cache_case
    first = case.run()
    if drift == "change":
        case.source.write_bytes(b'{"version":2}')
    else:
        case.source.unlink()

    with pytest.raises((ValueError, FileNotFoundError)):
        case.run()
    assert case.trace == ["load", "start", "pool", "done"]
    assert case.ledger()["result"] == first
    case.source.write_bytes(case.original)
    assert case.run() == first
    assert case.trace == ["load", "start", "pool", "done"]


@pytest.mark.parametrize(
    "bad_context",
    [
        "missing",
        "{}",
        "[]",
        '{"packets_generated": NaN, "packets_delivered": 0}',
        '{"packets_generated": 1, "packets_delivered": 2}',
        '{"packets_generated": true, "packets_delivered": 0}',
    ],
)
def test_relay_invalid_context_never_selects_worker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    bad_context: str,
) -> None:
    from agi_node.agi_dispatcher import base_worker_runtime_support as runtime_support

    module = _load_core_module()
    path = tmp_path / "queue.json"
    if bad_context != "missing":
        path.write_text(bad_context, encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        runtime_support, "load_worker", lambda *a, **kw: calls.append(a)
    )
    with pytest.raises(ValueError, match="queue_metrics"):
        module.run_relay_followup_app(
            repo_root=Path.cwd(),
            run_root=tmp_path / "relay",
            queue_result={"summary_metrics_path": str(path)},
            idempotency_token="invalid-context:relay",
        )
    assert calls == []


@pytest.mark.parametrize("mismatch", ["metrics", "hash", "producer"])
def test_relay_context_must_match_completed_producer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mismatch: str,
) -> None:
    from agi_node.agi_dispatcher import base_worker_runtime_support as runtime_support

    module = _load_core_module()
    path = tmp_path / "queue.json"
    path.write_text(
        '{"packets_generated": 8, "packets_delivered": 7}', encoding="utf-8"
    )
    queue = {"summary_metrics_path": str(path)}
    if mismatch == "metrics":
        queue["summary_metrics"] = {"packets_generated": 9, "packets_delivered": 7}
    elif mismatch == "hash":
        queue["summary_metrics_sha256"] = "0" * 64
    else:
        queue["producer"] = "another_stage"
    calls = []
    monkeypatch.setattr(
        runtime_support, "load_worker", lambda *a, **kw: calls.append(a)
    )
    with pytest.raises(ValueError, match="queue_metrics"):
        module.run_relay_followup_app(
            repo_root=Path.cwd(),
            run_root=tmp_path / "relay",
            queue_result=queue,
            idempotency_token="mismatched-context:relay",
        )
    assert calls == []


def test_relay_persists_exact_context_and_rejects_same_token_context_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import hashlib
    import json

    module = _load_core_module()
    path = tmp_path / "queue.json"
    metrics = {"packets_generated": 8, "packets_delivered": 7}
    path.write_text(json.dumps(metrics), encoding="utf-8")
    source = tmp_path / "relay" / "scenario.json"
    source.parent.mkdir(parents=True)
    source.write_text("{}", encoding="utf-8")
    calls = []

    def run_once(**kwargs):
        calls.append(kwargs)
        return {
            "summary_metrics": {"packets_generated": 5, "packets_delivered": 5},
            "source_scenario": str(source),
            "source_scenario_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        }

    monkeypatch.setattr(module, "_run_queue_family_app_once", run_once)
    kwargs = dict(
        repo_root=Path.cwd(),
        run_root=tmp_path / "relay",
        queue_result={"summary_metrics_path": str(path), "summary_metrics": metrics},
        idempotency_token="same-context-token:relay",
    )
    result = module.run_relay_followup_app(**kwargs)
    assert module.run_relay_followup_app(**kwargs) == result
    receipt = result["consumed_artifacts"][0]
    assert receipt["summary_metrics"] == metrics
    assert receipt["size_bytes"] == len(path.read_bytes())
    assert receipt["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert receipt["numerically_conditioned"] is False
    assert result["relay_numerically_conditioned_on_queue_metrics"] is False
    metrics["packets_generated"] = 9
    path.write_text(json.dumps(metrics), encoding="utf-8")
    with pytest.raises(ValueError, match="different execution inputs"):
        module.run_relay_followup_app(**kwargs)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "pollution", ["result_child", "export_root", "export_child", "internal_alias"]
)
def test_authored_uav_rejects_polluted_output_trees_before_worker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    pollution: str,
) -> None:
    from agi_node.agi_dispatcher import base_worker_runtime_support as runtime_support

    module = _load_core_module()
    run_root = tmp_path / "run"
    outside = (
        run_root / "aliased_output"
        if pollution == "internal_alias"
        else tmp_path / "outside"
    )
    outside.mkdir(parents=True)
    sentinel = outside / "sentinel"
    sentinel.write_text("preserve", encoding="utf-8")
    stem = "uav_queue_hotspot_shortest_path_seed2026"
    if pollution in {"result_child", "internal_alias"}:
        link = run_root / "share/uav_queue/results" / stem
    elif pollution == "export_root":
        link = run_root / "export"
    else:
        link = (
            run_root / "export/multi_app_dag_dispatch_smoke_queue/queue_analysis" / stem
        )
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside, target_is_directory=True)
    loader = runtime_support.load_worker
    calls = []

    def select_worker(*args, **kwargs):
        calls.append(args[0].target_worker)
        return loader(*args, **kwargs)

    monkeypatch.setattr(runtime_support, "load_worker", select_worker)
    with pytest.raises((ValueError, RuntimeError), match="output|export|symlink"):
        module.run_queue_baseline_app(
            repo_root=Path.cwd(),
            run_root=run_root,
            execution_contract={"params": {"sim_time_s": 2.0}, "reset_target": False},
            idempotency_token="polluted-output:queue",
        )
    assert calls == []
    assert list(outside.iterdir()) == [sentinel]
    assert sentinel.read_text(encoding="utf-8") == "preserve"
