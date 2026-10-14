from __future__ import annotations

import importlib.util
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

    def _run_once(**_kwargs):
        nonlocal callback_count
        callback_count += 1
        return {"summary_metrics": {"stage_completed": 1}}

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
    calls = []

    def run_once(**kwargs):
        calls.append(kwargs)
        return {"summary_metrics": {"packets_generated": 5, "packets_delivered": 5}}

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
