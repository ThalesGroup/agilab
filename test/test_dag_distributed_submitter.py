from __future__ import annotations

import builtins
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


def _ensure_agilab_package_path() -> None:
    package_root = Path("src/agilab").resolve()
    package_spec = importlib.util.spec_from_file_location(
        "agilab",
        package_root / "__init__.py",
        submodule_search_locations=[str(package_root)],
    )
    package = sys.modules.get("agilab")
    if package is None:
        assert package_spec is not None and package_spec.loader is not None
        package = importlib.util.module_from_spec(package_spec)
        sys.modules["agilab"] = package
        package_spec.loader.exec_module(package)
        return

    package_paths = list(getattr(package, "__path__", []) or [])
    package_root_text = str(package_root)
    if package_root_text not in package_paths:
        package.__path__ = [package_root_text, *package_paths]
    package.__spec__ = package_spec
    package.__file__ = str(package_root / "__init__.py")
    package.__package__ = "agilab"


def _load_dag_distributed_submitter():
    _ensure_agilab_package_path()
    module_path = Path("src/agilab/dag_distributed_submitter.py")
    spec = importlib.util.spec_from_file_location("agilab.dag_distributed_submitter", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["agilab.dag_distributed_submitter"] = module
    spec.loader.exec_module(module)
    return module


dag_distributed_submitter = _load_dag_distributed_submitter()


def _write_app(repo_root: Path, apps_root: str, app_name: str) -> None:
    app_dir = repo_root / apps_root / app_name
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "pyproject.toml").write_text(
        f"[project]\nname = \"{app_name}\"\nversion = \"0.0.0\"\n",
        encoding="utf-8",
    )


def test_stage_config_requires_complete_enabled_cluster_settings() -> None:
    assert dag_distributed_submitter.dag_distributed_stage_config_from_settings({}) is None
    assert (
        dag_distributed_submitter.dag_distributed_stage_config_from_settings(
            {"cluster": {"cluster_enabled": True, "scheduler": "192.168.20.111"}}
        )
        is None
    )

    config = dag_distributed_submitter.dag_distributed_stage_config_from_settings(
        {
            "cluster": {
                "cluster_enabled": True,
                "scheduler": "192.168.20.111:8786",
                "workers": '{"192.168.20.111": 1, "192.168.20.15": 2}',
                "workers_data_path": "clustershare/agi",
                "pool": True,
                "cython": True,
                "rapids": False,
            }
        },
        verbose=2,
    )

    assert config is not None
    assert config.scheduler == "192.168.20.111:8786"
    assert config.workers == {"192.168.20.111": 1, "192.168.20.15": 2}
    assert config.workers_data_path == "clustershare/agi"
    assert config.mode == 7
    assert config.worker_nodes == 2
    assert config.worker_slots == 3
    assert config.verbose == 2


def test_load_distributed_settings_merges_session_cluster_over_file(tmp_path: Path) -> None:
    settings_file = tmp_path / "app_settings.toml"
    settings_file.write_text(
        """
[cluster]
cluster_enabled = false
scheduler = "127.0.0.1:8786"
workers_data_path = ""

[cluster.workers]
"127.0.0.1" = 1
""".strip()
        + "\n",
        encoding="utf-8",
    )
    env = SimpleNamespace(app_settings_file=settings_file)

    settings = dag_distributed_submitter.load_dag_distributed_settings(
        env,
        {
            "cluster": {
                "cluster_enabled": True,
                "scheduler": "192.168.20.111:8786",
                "workers_data_path": "clustershare/agi",
            }
        },
    )

    assert settings["cluster"]["cluster_enabled"] is True
    assert settings["cluster"]["scheduler"] == "192.168.20.111:8786"
    assert settings["cluster"]["workers_data_path"] == "clustershare/agi"
    assert settings["cluster"]["workers"] == {"127.0.0.1": 1}


def test_load_distributed_settings_handles_missing_invalid_and_extra_values(tmp_path: Path) -> None:
    missing = SimpleNamespace(app_settings_file=None)
    assert dag_distributed_submitter.load_dag_distributed_settings(missing, None) == {}

    broken_settings_file = tmp_path / "broken.toml"
    broken_settings_file.write_text("[cluster\n", encoding="utf-8")
    broken = SimpleNamespace(app_settings_file=broken_settings_file)
    assert dag_distributed_submitter.load_dag_distributed_settings(broken, None) == {}

    settings_file = tmp_path / "app_settings.toml"
    settings_file.write_text(
        """
[cluster]
cluster_enabled = true
scheduler = "127.0.0.1:8786"
workers_data_path = "clustershare/agi"

[cluster.workers]
"127.0.0.1" = 1
""".strip()
        + "\n",
        encoding="utf-8",
    )
    env = SimpleNamespace(app_settings_file=settings_file)

    merged = dag_distributed_submitter.load_dag_distributed_settings(
        env,
        {"label": "demo", "cluster": {"scheduler": "192.168.20.111:8786"}},
    )

    assert merged["label"] == "demo"
    assert merged["cluster"]["scheduler"] == "192.168.20.111:8786"
    assert merged["cluster"]["workers"] == {"127.0.0.1": 1}


def test_load_distributed_settings_uses_stdlib_without_optional_agi_env(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings_file = tmp_path / "app_settings.toml"
    settings_file.write_text(
        '[cluster]\ncluster_enabled = true\nscheduler = "127.0.0.1:8786"\n',
        encoding="utf-8",
    )
    real_import = builtins.__import__

    def _without_agi_env(name, *args, **kwargs):
        if name.startswith("agi_env"):
            raise ModuleNotFoundError(
                "No module named 'agi_env'",
                name="agi_env",
            )
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _without_agi_env)

    loaded = dag_distributed_submitter.load_dag_distributed_settings(
        SimpleNamespace(app_settings_file=settings_file),
        None,
    )

    assert loaded == {
        "cluster": {
            "cluster_enabled": True,
            "scheduler": "127.0.0.1:8786",
        }
    }


def test_build_global_submitter_runs_configured_runner(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _write_app(repo_root, "src/agilab/apps/builtin", "flight_telemetry_project")
    env = SimpleNamespace(app_settings_file=None)
    calls: list[dict[str, object]] = []

    def _runner(**kwargs):
        calls.append(kwargs)
        return {"summary_metrics": {"factory_runner": 1}}

    submitter = dag_distributed_submitter.build_multi_app_dag_distributed_stage_submitter(
        env=env,
        app_settings={
            "cluster": {
                "cluster_enabled": True,
                "scheduler": "192.168.20.111:8786",
                "workers": {"192.168.20.111": 1},
                "workers_data_path": "clustershare/agi",
            }
        },
        verbose=3,
        runner_fn=_runner,
    )

    assert submitter is not None
    result = submitter(
        repo_root=repo_root,
        lab_dir=tmp_path / "lab",
        run_root=tmp_path / "run",
        unit={"id": "flight_context", "app": "flight_telemetry_project"},
        artifact={"artifact": "stage_result", "kind": "contract_artifact"},
        execution_contract={"params": {}, "stages": []},
        timestamp="2026-05-07T00:00:00Z",
        idempotency_token="factory-attempt:flight_context",
    )

    assert calls[0]["config"].verbose == 3
    assert calls[0]["idempotency_token"] == "factory-attempt:flight_context"
    assert calls[0]["request_payload"]["idempotency_token"] == (
        "factory-attempt:flight_context"
    )
    assert result["summary_metrics"]["factory_runner"] == 1


def test_build_global_submitter_returns_none_without_cluster() -> None:
    submitter = dag_distributed_submitter.build_multi_app_dag_distributed_stage_submitter(
        env=SimpleNamespace(app_settings_file=None),
        app_settings={"cluster": {"cluster_enabled": False}},
    )

    assert submitter is None


def test_submit_distributed_stage_runs_fake_runner_and_writes_evidence(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _write_app(repo_root, "src/agilab/apps/builtin", "flight_telemetry_project")
    config = dag_distributed_submitter.DagDistributedStageConfig(
        scheduler="192.168.20.111:8786",
        workers={"192.168.20.111": 1, "192.168.20.15": 2},
        workers_data_path="clustershare/agi",
        mode=7,
        verbose=1,
    )
    calls: list[dict[str, object]] = []

    def _runner(**kwargs):
        calls.append(kwargs)
        output_path = kwargs["run_root"] / "flight/reduce.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text('{"scientific_output": true}\n', encoding="utf-8")
        return {
            "reduce_artifact_path": str(output_path),
            "summary_metrics": {"runner_confirmed": 1},
        }

    result = dag_distributed_submitter.submit_distributed_stage(
        config=config,
        runner_fn=_runner,
        repo_root=repo_root,
        lab_dir=tmp_path / "lab",
        run_root=tmp_path / "lab/.agilab/multi_app_dag_real_runs/flight_context",
        unit={"id": "flight_context", "app": "flight_telemetry_project"},
        artifact={"artifact": "flight_reduce_summary", "kind": "reduce_summary", "path": "flight/reduce.json"},
        execution_contract={
            "entrypoint": "flight_telemetry_project.flight_context",
            "params": {"scenario": "demo"},
            "stages": [{"name": "prepare", "args": {"n": 2}}],
        },
        timestamp="2026-05-07T00:00:00Z",
        idempotency_token="distributed-attempt:flight_context",
    )
    duplicate = dag_distributed_submitter.submit_distributed_stage(
        config=config,
        runner_fn=_runner,
        repo_root=repo_root,
        lab_dir=tmp_path / "lab",
        run_root=tmp_path / "lab/.agilab/multi_app_dag_real_runs/flight_context",
        unit={"id": "flight_context", "app": "flight_telemetry_project"},
        artifact={
            "artifact": "flight_reduce_summary",
            "kind": "reduce_summary",
            "path": "flight/reduce.json",
        },
        execution_contract={
            "entrypoint": "flight_telemetry_project.flight_context",
            "params": {"scenario": "demo"},
            "stages": [{"name": "prepare", "args": {"n": 2}}],
        },
        timestamp="2026-05-07T00:00:00Z",
        idempotency_token="distributed-attempt:flight_context",
    )

    assert len(calls) == 1
    assert duplicate == result
    assert calls[0]["apps_path"] == repo_root / "src/agilab/apps/builtin"
    assert calls[0]["app_name"] == "flight_telemetry_project"
    assert calls[0]["request_payload"]["params"] == {"scenario": "demo"}
    assert calls[0]["request_payload"]["stages"] == [{"name": "prepare", "args": {"n": 2}}]
    assert calls[0]["request_payload"]["idempotency_token"] == (
        "distributed-attempt:flight_context"
    )
    assert calls[0]["idempotency_token"] == "distributed-attempt:flight_context"
    evidence_path = Path(result["submission_evidence_path"])
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["schema"] == "agilab.distributed_dag_stage_submission.v1"
    assert evidence["app"] == "flight_telemetry_project"
    assert evidence["idempotency_token"] == "distributed-attempt:flight_context"
    assert evidence["request_payload"]["idempotency_token"] == (
        "distributed-attempt:flight_context"
    )
    assert evidence["cluster"]["worker_nodes"] == 2
    assert result["reduce_artifact_path"] != str(evidence_path)
    assert json.loads(Path(result["reduce_artifact_path"]).read_text()) == {
        "scientific_output": True
    }
    assert result["summary_metrics"]["worker_slots"] == 3
    assert result["summary_metrics"]["runner_confirmed"] == 1
    assert result["idempotency_token"] == "distributed-attempt:flight_context"
    assert result["distributed_submission"]["idempotency_token"] == (
        "distributed-attempt:flight_context"
    )

    non_mapping_result = dag_distributed_submitter.submit_distributed_stage(
        config=config,
        runner_fn=lambda **_kwargs: {"summary_metrics": ["ignored"]},
        repo_root=repo_root,
        lab_dir=tmp_path / "lab",
        run_root=tmp_path / "lab/.agilab/multi_app_dag_real_runs/default_metrics",
        unit={"id": "flight_context", "app": "flight_telemetry_project"},
        artifact={"artifact": "default_metrics", "kind": "contract_artifact"},
        execution_contract={},
        timestamp="2026-05-07T00:00:01Z",
        idempotency_token="distributed-attempt:default_metrics",
    )
    assert non_mapping_result["summary_metrics"] == {
        "stage_completed": 1,
        "distributed_submissions": 1,
        "worker_nodes": 2,
        "worker_slots": 3,
    }


def test_build_distributed_request_preview_rows_shows_exact_stage_request(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _write_app(repo_root, "src/agilab/apps/builtin", "flight_telemetry_project")
    config = dag_distributed_submitter.DagDistributedStageConfig(
        scheduler="192.168.20.111:8786",
        workers={"192.168.20.111": 1, "192.168.20.15": 1},
        workers_data_path="clustershare/agi",
        mode=15,
        verbose=1,
    )

    rows = dag_distributed_submitter.build_distributed_request_preview_rows(
        {
            "units": [
                {
                    "id": "flight_context",
                    "app": "flight_telemetry_project",
                    "dispatch_status": "runnable",
                    "execution_contract": {
                        "entrypoint": "flight_telemetry_project.flight_context",
                        "params": {"scenario": "demo"},
                        "stages": [{"name": "prepare", "args": {"n": 2}}],
                        "data_in": "flight_telemetry/dataset",
                        "data_out": "flight_telemetry/dataframe",
                        "reset_target": False,
                    },
                }
            ]
        },
        repo_root=repo_root,
        config=config,
    )

    assert rows == [
        {
            "Stage": "flight_context",
            "App": "flight_telemetry_project",
            "Status": "runnable",
            "Backend": "distributed",
            "Nodes": "2",
            "Worker slots": "2",
            "Scheduler": "192.168.20.111:8786",
            "Workers Data Path": "clustershare/agi",
            "Mode": "15",
            "Apps path": "src/agilab/apps/builtin",
            "Request": (
                '{"benchmark_best_single_node":false,"data_in":"flight_telemetry/dataset",'
                '"data_out":"flight_telemetry/dataframe","params":{"scenario":"demo"},'
                '"rapids_enabled":false,"reset_target":false,'
                '"stages":[{"args":{"n":2},"name":"prepare"}]}'
            ),
        }
    ]


def test_distributed_request_preview_rows_cover_empty_and_missing_apps(monkeypatch, tmp_path: Path) -> None:
    config = dag_distributed_submitter.DagDistributedStageConfig(
        scheduler="192.168.20.111:8786",
        workers={"192.168.20.111": 1},
        workers_data_path="clustershare/agi",
        mode=7,
    )

    assert dag_distributed_submitter.build_distributed_request_preview_rows(
        {"units": "not-a-list"},
        repo_root=tmp_path,
        config=config,
    ) == []

    rows = dag_distributed_submitter.build_distributed_request_preview_rows(
        {
            "units": [
                "invalid",
                {"id": "no_contract"},
                {"id": "empty_app", "app": "", "execution_contract": {"params": {}}},
                {"id": "missing_app", "app": "ghost_project", "execution_contract": {"params": {}}},
            ]
        },
        repo_root=tmp_path,
        config=config,
    )

    assert rows[0]["App"] == "-"
    assert rows[0]["Apps path"] == "-"
    assert rows[1]["App"] == "ghost_project"
    assert rows[1]["Apps path"] == "missing"

    monkeypatch.setattr(
        dag_distributed_submitter,
        "resolve_stage_apps_path",
        lambda _repo_root, _app_name: tmp_path.parent / "external_apps",
    )
    external_rows = dag_distributed_submitter.build_distributed_request_preview_rows(
        {"units": [{"id": "external", "app": "external_project", "execution_contract": {"params": {}}}]},
        repo_root=tmp_path,
        config=config,
    )
    assert external_rows[0]["Apps path"] == str(tmp_path.parent / "external_apps")


def test_resolve_stage_apps_path_supports_repository_apps(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _write_app(repo_root, "src/agilab/apps", "custom_project")

    assert dag_distributed_submitter.resolve_stage_apps_path(repo_root, "custom_project") == (
        repo_root / "src/agilab/apps"
    )


def test_submit_distributed_stage_rejects_missing_or_unknown_app(tmp_path: Path) -> None:
    config = dag_distributed_submitter.DagDistributedStageConfig(
        scheduler="192.168.20.111:8786",
        workers={"192.168.20.111": 1},
        workers_data_path="clustershare/agi",
        mode=7,
    )

    with pytest.raises(RuntimeError, match="missing its app name"):
        dag_distributed_submitter.submit_distributed_stage(
            config=config,
            runner_fn=lambda **_kwargs: {},
            repo_root=tmp_path,
            lab_dir=tmp_path / "lab",
            run_root=tmp_path / "run",
            unit={"id": "bad_stage"},
            artifact={},
            execution_contract={},
            timestamp="2026-05-07T00:00:00Z",
            idempotency_token="bad-attempt:bad_stage",
        )

    with pytest.raises(RuntimeError, match="was not found"):
        dag_distributed_submitter.resolve_stage_apps_path(tmp_path, "ghost_project")


def test_payload_worker_and_evidence_helpers_cover_fallbacks(tmp_path: Path) -> None:
    payload = dag_distributed_submitter.request_payload_from_execution_contract(
        {
            "run_params": {"scenario": "fallback"},
            "stages": [{"name": "fallback_stage"}],
            "params": "not-a-mapping",
            "rapids_enabled": 1,
            "benchmark_best_single_node": "yes",
        }
    )
    assert payload["params"] == {}
    assert payload["stages"] == [{"name": "fallback_stage"}]
    assert payload["rapids_enabled"] is True
    assert payload["benchmark_best_single_node"] is True

    with pytest.raises(ValueError, match="legacy 'steps'/'run_steps'"):
        dag_distributed_submitter.request_payload_from_execution_contract(
            {"run_params": {"scenario": "fallback"}, "run_steps": [{"name": "fallback_stage"}]}
        )

    assert dag_distributed_submitter._coerce_workers("") == {}
    assert dag_distributed_submitter._coerce_workers("not valid") == {}
    assert dag_distributed_submitter._coerce_workers({"": 1, "valid": "2", "zero": 0, "bad": "x"}) == {"valid": 2}

    run_root = tmp_path / "run"
    assert dag_distributed_submitter._distributed_evidence_path(
        run_root, {"artifact": "safe", "path": "safe/out.json"}
    ) == (
        run_root
        / "distributed_submission_evidence/safe-distributed-submission-evidence.json"
    )
    assert dag_distributed_submitter._distributed_evidence_path(
        run_root, {"id": "fallback", "path": "../unsafe"}
    ) == (
        run_root
        / "distributed_submission_evidence/fallback-distributed-submission-evidence.json"
    )
    assert dag_distributed_submitter._distributed_evidence_path(
        run_root, {"path": str(tmp_path / "absolute")}
    ) == (
        run_root
        / "distributed_submission_evidence/stage_result-distributed-submission-evidence.json"
    )

    assert dag_distributed_submitter._tail("abcdef", max_chars=3) == "def"
    assert dag_distributed_submitter._jsonable({"items": [object()]})["items"][0].startswith("<object object")


def test_tail_file_trims_and_handles_unreadable_paths(tmp_path: Path) -> None:
    log_path = tmp_path / "worker.log"
    log_path.write_bytes(b"prefix-" + ("é".encode("utf-8") * 16) + b"-suffix")

    assert dag_distributed_submitter._tail_file(log_path, max_chars=8) == "é-suffix"
    assert dag_distributed_submitter._tail_file(tmp_path, max_chars=8) == ""


def test_stage_subprocess_runner_generates_isolated_agilab_run_script(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    call_count = 0

    def _fake_run(command, **kwargs):
        nonlocal call_count
        call_count += 1
        captured["command"] = command
        captured["kwargs"] = kwargs
        kwargs["stdout"].write('{"result": "ok"}\n')
        kwargs["stderr"].write("")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(dag_distributed_submitter.subprocess, "run", _fake_run)
    config = dag_distributed_submitter.DagDistributedStageConfig(
        scheduler="192.168.20.111:8786",
        workers={"192.168.20.111": 1},
        workers_data_path="clustershare/agi",
        mode=7,
        verbose=1,
    )
    result = dag_distributed_submitter.run_agilab_stage_subprocess(
        config=config,
        repo_root=tmp_path,
        run_root=tmp_path / "run",
        apps_path=tmp_path / "src/agilab/apps/builtin",
        app_name="flight_telemetry_project",
        request_payload={"params": {}, "stages": []},
        timestamp="2026-05-07T00:00:00Z",
        idempotency_token="subprocess-attempt:flight_context",
    )
    duplicate = dag_distributed_submitter.run_agilab_stage_subprocess(
        config=config,
        repo_root=tmp_path,
        run_root=tmp_path / "run",
        apps_path=tmp_path / "src/agilab/apps/builtin",
        app_name="flight_telemetry_project",
        request_payload={"params": {}, "stages": []},
        timestamp="2026-05-07T00:00:00Z",
        idempotency_token="subprocess-attempt:flight_context",
    )

    script = (tmp_path / "run/run_distributed_stage.py").read_text(encoding="utf-8")
    assert "await AGI.install(" in script
    assert "modes_enabled=7" in script
    assert "await AGI.run(app_env, request=request)" in script
    assert "workers_data_path='clustershare/agi'" in script
    assert 'os.environ["AGILAB_IDEMPOTENCY_TOKEN"]' in script
    assert captured["kwargs"]["env"]["AGILAB_IDEMPOTENCY_TOKEN"] == (
        "subprocess-attempt:flight_context"
    )
    assert captured["command"][0] == sys.executable
    assert captured["kwargs"]["stdout"] is not subprocess.PIPE
    assert captured["kwargs"]["stderr"] is not subprocess.PIPE
    assert "capture_output" not in captured["kwargs"]
    assert result["returncode"] == 0
    # New contract: a null AGI.run result now fails the stage, so the success
    # path must print a real result payload.
    assert result["stdout_tail"] == '{"result": "ok"}\n'
    assert result["stdout_log"].endswith("distributed_stage.stdout.log")
    assert result["stderr_log"].endswith("distributed_stage.stderr.log")
    assert result["idempotency_token"] == "subprocess-attempt:flight_context"
    assert duplicate == result
    assert call_count == 1


def test_stage_subprocess_preserves_per_artifact_output_paths(
    monkeypatch, tmp_path: Path
) -> None:
    outputs = [
        {"artifact": "x", "kind": "dataset", "path": "x.csv"},
        {"artifact": "y", "kind": "dataset", "path": "y.csv"},
    ]

    def fake_run(command, **kwargs):
        kwargs["stdout"].write(
            json.dumps({"result": {"produced_artifacts": outputs}}) + "\n"
        )
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(dag_distributed_submitter.subprocess, "run", fake_run)
    result = dag_distributed_submitter.run_agilab_stage_subprocess(
        config=dag_distributed_submitter.DagDistributedStageConfig(
            "local-test", {"local": 1}, "share", 4
        ),
        repo_root=tmp_path,
        run_root=tmp_path / "run",
        apps_path=tmp_path / "apps",
        app_name="uav_queue_project",
        request_payload={"params": {}, "stages": []},
        timestamp="now",
        idempotency_token="per-artifact-output-test",
    )
    assert result["produced_artifacts"] == outputs


def test_stage_subprocess_runner_streams_worker_logs_before_completion(monkeypatch, tmp_path: Path) -> None:
    class _Recorder:
        def __init__(self) -> None:
            self.text = ""

        def write(self, text: str) -> None:
            self.text += text

        def flush(self) -> None:
            pass

    stdout_recorder = _Recorder()
    stderr_recorder = _Recorder()
    streamed_before_return: dict[str, bool] = {}

    def _fake_run(command, **kwargs):
        kwargs["stdout"].write("live worker stdout\n")
        kwargs["stdout"].flush()
        kwargs["stderr"].write("live worker stderr\n")
        kwargs["stderr"].flush()
        time.sleep(0.05)
        streamed_before_return["stdout"] = "live worker stdout" in stdout_recorder.text
        streamed_before_return["stderr"] = "live worker stderr" in stderr_recorder.text
        kwargs["stdout"].write('{"result": "ok"}\n')
        kwargs["stdout"].flush()
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(dag_distributed_submitter.subprocess, "run", _fake_run)
    monkeypatch.setattr(dag_distributed_submitter.sys, "stdout", stdout_recorder)
    monkeypatch.setattr(dag_distributed_submitter.sys, "stderr", stderr_recorder)
    monkeypatch.setattr(dag_distributed_submitter, "_REMOTE_LOG_STREAM_INTERVAL_SECONDS", 0.01)
    config = dag_distributed_submitter.DagDistributedStageConfig(
        scheduler="192.168.20.111:8786",
        workers={"192.168.20.111": 1},
        workers_data_path="clustershare/agi",
        mode=7,
        verbose=1,
    )

    result = dag_distributed_submitter.run_agilab_stage_subprocess(
        config=config,
        repo_root=tmp_path,
        run_root=tmp_path / "run",
        apps_path=tmp_path / "src/agilab/apps/builtin",
        app_name="flight_telemetry_project",
        request_payload={"params": {}, "stages": []},
        timestamp="2026-05-07T00:00:00Z",
        idempotency_token="stream-attempt:flight_context",
    )

    assert streamed_before_return == {"stdout": True, "stderr": True}
    assert "live worker stdout" in stdout_recorder.text
    assert "live worker stderr" in stderr_recorder.text
    assert result["stdout_tail"].endswith('{"result": "ok"}\n')


@pytest.mark.parametrize(
    ("stdout_payload", "expected_detail"),
    (
        ('{"result": null}\n', "returned no result"),
        (
            '{"result": {"status": "error", "message": "scheduler unreachable", "kind": "connection"}}\n',
            "scheduler unreachable",
        ),
    ),
)
def test_stage_subprocess_runner_rejects_null_or_error_results(
    monkeypatch, tmp_path: Path, stdout_payload: str, expected_detail: str
) -> None:
    # AGI.run swallows ProcessError/ConnectionError; a zero exit code with a
    # null/error result must not produce success evidence.
    def _fake_run(command, **kwargs):
        kwargs["stdout"].write(stdout_payload)
        kwargs["stderr"].write("")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(dag_distributed_submitter.subprocess, "run", _fake_run)
    config = dag_distributed_submitter.DagDistributedStageConfig(
        scheduler="192.168.20.111:8786",
        workers={"192.168.20.111": 1},
        workers_data_path="clustershare/agi",
        mode=7,
    )

    with pytest.raises(RuntimeError, match=expected_detail):
        dag_distributed_submitter.run_agilab_stage_subprocess(
            config=config,
            repo_root=tmp_path,
            run_root=tmp_path / "run",
            apps_path=tmp_path / "src/agilab/apps/builtin",
            app_name="flight_telemetry_project",
            request_payload={"params": {}, "stages": []},
            timestamp="2026-05-07T00:00:00Z",
            idempotency_token="failure-attempt:flight_context",
        )

    script = (tmp_path / "run/run_distributed_stage.py").read_text(encoding="utf-8")
    assert "sys.exit(1)" in script


def test_stage_subprocess_runner_raises_with_trimmed_failure(monkeypatch, tmp_path: Path) -> None:
    def _fake_run(command, **kwargs):
        kwargs["stderr"].write("x" * 5000)
        return subprocess.CompletedProcess(command, 2)

    monkeypatch.setattr(dag_distributed_submitter.subprocess, "run", _fake_run)
    config = dag_distributed_submitter.DagDistributedStageConfig(
        scheduler="192.168.20.111:8786",
        workers={"192.168.20.111": 1},
        workers_data_path="clustershare/agi",
        mode=7,
    )

    with pytest.raises(RuntimeError) as err:
        dag_distributed_submitter.run_agilab_stage_subprocess(
            config=config,
            repo_root=tmp_path,
            run_root=tmp_path / "run",
            apps_path=tmp_path / "src/agilab/apps/builtin",
            app_name="flight_telemetry_project",
            request_payload={},
            timestamp="2026-05-07T00:00:00Z",
            idempotency_token="exit-attempt:flight_context",
        )

    message = str(err.value)
    assert "Distributed DAG stage `flight_telemetry_project` failed" in message
    assert len(message) < 4100


def test_worker_log_forwarding_resumes_at_last_offset_and_tolerates_closed_consumer(tmp_path):
    import io
    module = importlib.import_module("agilab.dag.dag_distributed_submitter")
    path = tmp_path / "worker.log"
    offsets = {}
    stream = io.StringIO()
    module._tee_log_file_update(path, stream, offsets)
    assert offsets == {}
    path.write_text("first\n")
    module._tee_log_file_update(path, stream, offsets)
    with path.open("a") as output:
        output.write("second\n")
    module._tee_log_file_update(path, stream, offsets)
    assert stream.getvalue() == "first\nsecond\n"
    stream.close()
    with path.open("a") as output:
        output.write("third\n")
    module._tee_log_file_update(path, stream, offsets)
    assert offsets[str(path)] == path.stat().st_size


@pytest.mark.parametrize(("text", "expected"), [
    ("worker log\n{invalid\n{}", None),
    ('{"result":null}', "AGI.run returned no result"),
    ('{"result":{"status":"error"}}', "AGI.run reported an error result"),
    ('{"result":{"status":"error","message":"worker unavailable"}}', "worker unavailable"),
    ('{"result":{"status":"ok"}}\ntrailing worker log', None),
])
def test_distributed_result_parser_uses_last_valid_result(text, expected):
    module = importlib.import_module("agilab.dag.dag_distributed_submitter")
    result = module._stage_result_failure(text)
    assert result is None if expected is None else expected in result


@pytest.mark.parametrize("windows", [False, True])
def test_settings_sharing_denial_stops_at_deadline_without_busy_loop(tmp_path, monkeypatch, windows):
    from types import SimpleNamespace
    module = importlib.import_module("agilab.dag.dag_distributed_submitter")
    path = tmp_path / "settings.toml"
    calls, delays = [], []
    clock = iter([0.0, 0.1, 0.6])
    original = Path.open
    def denied(target, *args, **kwargs):
        if target == path:
            calls.append(True)
            raise PermissionError("sharing denial")
        return original(target, *args, **kwargs)
    monkeypatch.setattr(Path, "open", denied)
    monkeypatch.setattr(module, "os", SimpleNamespace(name="nt" if windows else "posix"))
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda:next(clock), sleep=delays.append))
    assert module._read_settings_file_stdlib(path) == {}
    assert len(calls) == (2 if windows else 1)
    assert delays == ([0.01] if windows else [])


def _upstream_stage_case(tmp_path, monkeypatch):
    """A declared producer fixture; no worker, installation or science runs."""
    import hashlib

    module = dag_distributed_submitter
    _write_app(tmp_path, "src/agilab/apps/builtin", "uav_relay_queue_project")
    producer = tmp_path / "queue" / "metrics.json"
    producer.parent.mkdir()
    metrics = {"packets_generated": 3, "packets_delivered": 2, "packets_dropped": 1}
    producer.write_text(json.dumps(metrics), encoding="utf-8")
    row = {
        "id": " queue_metrics ",
        "producer": " queue_baseline ",
        "kind": "summary_metrics",
        "path": str(producer),
        "resolved_path": str(producer.resolve()),
        "size_bytes": producer.stat().st_size,
        "sha256": hashlib.sha256(producer.read_bytes()).hexdigest(),
    }
    run_root = tmp_path / "relay"
    config = module.DagDistributedStageConfig(
        scheduler="127.0.0.1:18786", workers={"127.0.0.1": 1},
        workers_data_path=str(tmp_path / "share"), mode=4,
    )
    monkeypatch.setattr(
        module, "_distributed_output_roots",
        lambda _config, root, _request: ([root], [root]),
    )
    artifact = {"artifact": "relay_metrics", "kind": "summary_metrics", "path": "relay.json"}
    unit = {
        "id": "relay_followup", "app": "uav_relay_queue_project",
        "produces": [artifact],
        "artifact_dependencies": [{"from": " queue_baseline ", "artifact": " queue_metrics "}],
    }
    contract = {
        "params": {"sim_seconds": 30.0, "packet_rate_pps": 14.0, "random_seed": 2026},
        "stages": [{"name": "on_map", "args": {}}],
        "data_in": "uav_relay_queue/scenarios", "data_out": "uav_relay_queue/results",
        "reset_target": False,
    }
    calls = []

    def runner(**kwargs):
        calls.append(kwargs)
        output = run_root / "relay.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text('{"packets_generated": 3, "packets_delivered": 2}', encoding="utf-8")
        receipts = []
        for item in kwargs["request_payload"].get("input_artifacts", []):
            receipts.append({
                **item, "summary_metrics": metrics, "role": "upstream_context",
                "read_scope": "child_orchestrator", "numerically_conditioned": False,
            })
        return {"summary_metrics_path": str(output), "consumed_artifacts": receipts}

    kwargs = dict(
        config=config, runner_fn=runner, repo_root=tmp_path, lab_dir=tmp_path / "lab",
        run_root=run_root, unit=unit, artifact=artifact, execution_contract=contract,
        timestamp="2026-10-15T00:00:00Z", idempotency_token="context-transport:relay",
        input_artifacts=[row],
    )
    return kwargs, calls, row, metrics


@pytest.mark.parametrize("check", ["source", "script", "receipt"])
def test_declared_upstream_context_reaches_distributed_child(tmp_path, monkeypatch, check):
    kwargs, calls, row, metrics = _upstream_stage_case(tmp_path, monkeypatch)
    result = dag_distributed_submitter.submit_distributed_stage(**kwargs)
    payload = calls[0]["request_payload"]
    if check == "source":
        item = payload["input_artifacts"][0]
        assert (item["artifact"], item["producer"]) == ("queue_metrics", "queue_baseline")
        assert (item["path"], item["sha256"]) == (row["path"], row["sha256"])
        assert payload["params"] == kwargs["execution_contract"]["params"]
        assert payload["data_in"] == "uav_relay_queue/scenarios"
        assert payload["reset_target"] is False
    elif check == "script":
        script = dag_distributed_submitter._stage_run_script(
            config=kwargs["config"], apps_path=tmp_path / "apps",
            app_name="uav_relay_queue_project", request_payload=payload,
        )
        assert script.index("_read_queue_context(") < script.index("await AGI.run(")
    else:
        receipt = result["consumed_artifacts"][0]
        assert receipt["summary_metrics"] == metrics
        assert receipt["sha256"] == row["sha256"]
        assert receipt["role"] == "upstream_context"
        assert receipt["read_scope"] == "child_orchestrator"
        assert receipt["numerically_conditioned"] is False
        evidence = json.loads(Path(result["submission_evidence_path"]).read_text())
        assert evidence["runner_result"]["consumed_artifacts"] == result["consumed_artifacts"]


@pytest.mark.parametrize("problem", ["missing", "wrong_producer", "ambiguous", "bad_identity"])
def test_distributed_context_rejects_unbound_inputs_before_runner(tmp_path, monkeypatch, problem):
    kwargs, calls, row, _ = _upstream_stage_case(tmp_path, monkeypatch)
    if problem == "missing":
        kwargs["input_artifacts"] = None
    elif problem == "wrong_producer":
        row["producer"] = "other_producer"
    elif problem == "ambiguous":
        kwargs["input_artifacts"] = [row, dict(row)]
    else:
        row["sha256"] = "invalid"

    original_open = Path.open

    def no_target_read(path, *args, **options):
        if path == Path(row["path"]):
            pytest.fail("Invalid producer metadata must fail before target reads")
        return original_open(path, *args, **options)

    monkeypatch.setattr(Path, "open", no_target_read)
    with pytest.raises(ValueError, match="upstream artifact"):
        dag_distributed_submitter.submit_distributed_stage(**kwargs)
    assert not calls


@pytest.mark.parametrize("change", ["bytes", "missing", "redirect"])
def test_distributed_context_rejects_changed_original_before_cached_result(tmp_path, monkeypatch, change):
    kwargs, calls, row, _ = _upstream_stage_case(tmp_path, monkeypatch)
    dag_distributed_submitter.submit_distributed_stage(**kwargs)
    producer = Path(row["path"])
    if change == "bytes":
        producer.write_text('{"packets_generated": 999, "packets_delivered": 0}')
    elif change == "missing":
        producer.unlink()
    else:
        original_dir = producer.parent
        target_dir = tmp_path / "redirected-producer"
        original_dir.rename(target_dir)
        original_dir.symlink_to(target_dir, target_is_directory=True)
        original_open = Path.open

        def no_redirect_read(path, *args, **options):
            if path.name == producer.name:
                pytest.fail("Redirected target was opened before location rejection")
            return original_open(path, *args, **options)

        monkeypatch.setattr(Path, "open", no_redirect_read)
    with pytest.raises(ValueError, match="produced artifact"):
        dag_distributed_submitter.submit_distributed_stage(**kwargs)
    assert len(calls) == 1


def test_distributed_context_cache_rejects_new_valid_producer_binding(tmp_path, monkeypatch):
    import hashlib

    kwargs, calls, row, _ = _upstream_stage_case(tmp_path, monkeypatch)
    result = dag_distributed_submitter.submit_distributed_stage(**kwargs)
    assert dag_distributed_submitter.submit_distributed_stage(**kwargs) == result
    replacement = tmp_path / "replacement.json"
    replacement.write_bytes(Path(row["path"]).read_bytes())
    row.update(
        path=str(replacement), resolved_path=str(replacement.resolve()),
        sha256=hashlib.sha256(replacement.read_bytes()).hexdigest(),
        size_bytes=replacement.stat().st_size,
    )
    with pytest.raises(ValueError, match="original upstream inputs"):
        dag_distributed_submitter.submit_distributed_stage(**kwargs)
    assert len(calls) == 1


@pytest.mark.parametrize("receipt_change", ["missing", "identity", "context"])
def test_distributed_runner_must_return_actual_context_receipt(tmp_path, monkeypatch, receipt_change):
    kwargs, calls, _, _ = _upstream_stage_case(tmp_path, monkeypatch)
    runner = kwargs["runner_fn"]

    def endpoint(**arguments):
        result = runner(**arguments)
        if receipt_change == "missing":
            result.pop("consumed_artifacts")
        elif receipt_change == "identity":
            result["consumed_artifacts"][0]["sha256"] = "0" * 64
        else:
            result["consumed_artifacts"][0].pop("summary_metrics")
        return result

    kwargs["runner_fn"] = endpoint
    with pytest.raises(RuntimeError, match="receipt"):
        dag_distributed_submitter.submit_distributed_stage(**kwargs)
    assert len(calls) == 1
    assert not list(kwargs["run_root"].glob("distributed_submission_evidence/*.json"))


def _execute_fake_distributed_child(monkeypatch, kwargs, inputs, *, result=None, fail=False):
    """Execute generated orchestrator with fake SDK endpoints and the real JSON reader."""
    import asyncio
    import importlib
    from types import ModuleType

    module = dag_distributed_submitter
    context_module = importlib.import_module(
        "agilab.global_pipeline.global_pipeline_app_dispatch_smoke"
    )
    real_read = context_module._read_queue_context
    events = []
    captured = {}

    def read_context(reference):
        receipt = real_read(reference)
        events.append(("context_read", receipt))
        return receipt

    class Request:
        def __init__(self, **values):
            self.__dict__.update(values)

    class FakeAGI:
        @staticmethod
        async def install(*args, **options):
            events.append(("fake_install", None))

        @staticmethod
        async def run(*args, request, **options):
            events.append(("fake_run", request))
            captured["request"] = request
            if fail:
                raise RuntimeError("fake SDK failure")
            return result

        @staticmethod
        def load_worker(*args, **options):
            pytest.fail("No real worker loading is permitted in transport tests")

    fake_sdk = ModuleType("agi_cluster.agi_distributor")
    fake_sdk.AGI = FakeAGI
    fake_sdk.RunRequest = Request
    fake_sdk.StageRequest = Request
    monkeypatch.setitem(sys.modules, "agi_cluster.agi_distributor", fake_sdk)
    fake_env = ModuleType("agi_env")
    fake_env.AgiEnv = lambda **options: SimpleNamespace(**options)
    monkeypatch.setitem(sys.modules, "agi_env", fake_env)
    monkeypatch.setattr(context_module, "_read_queue_context", read_context)
    monkeypatch.setattr(
        module.subprocess, "run",
        lambda *args, **options: pytest.fail("No subprocess/science launch is permitted"),
    )
    payload = module.request_payload_from_execution_contract(kwargs["execution_contract"])
    payload.update(input_artifacts=inputs, idempotency_token=kwargs["idempotency_token"])
    script = module._stage_run_script(
        config=kwargs["config"], apps_path=kwargs["repo_root"] / "apps",
        app_name=kwargs["unit"]["app"], request_payload=payload,
    )
    namespace = {"__name__": "agilab_fake_child"}
    exec(compile(script, "fake-distributed-orchestrator.py", "exec"), namespace)
    return lambda: asyncio.run(namespace["main"]()), events, captured


def test_generated_child_reads_actual_queue_context_before_sdk_and_preserves_authorship(
    tmp_path, monkeypatch, capsys,
):
    kwargs, _, row, metrics = _upstream_stage_case(tmp_path, monkeypatch)
    inputs = dag_distributed_submitter.validate_distributed_stage_inputs(
        kwargs["unit"], kwargs["input_artifacts"],
    )
    run_child, events, captured = _execute_fake_distributed_child(
        monkeypatch, kwargs, inputs, result={"status": "ok", "packets_generated": 3},
    )
    run_child()
    assert [event[0] for event in events] == ["context_read", "fake_install", "fake_run"]
    assert events[0][1]["summary_metrics"] == metrics
    assert events[0][1]["sha256"] == row["sha256"]
    request = captured["request"]
    assert request.params == kwargs["execution_contract"]["params"]
    assert request.data_in == "uav_relay_queue/scenarios"
    assert request.data_out == "uav_relay_queue/results"
    assert request.reset_target is False
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["consumed_artifacts"][0]["summary_metrics"] == metrics
    assert result["consumed_artifacts"][0]["read_scope"] == "child_orchestrator"


@pytest.mark.parametrize("result,raises", [(None, False), ({"status": "error"}, False), (None, True)])
def test_generated_child_failed_run_emits_no_success_consumption_receipt(
    tmp_path, monkeypatch, capsys, result, raises,
):
    kwargs, _, _, _ = _upstream_stage_case(tmp_path, monkeypatch)
    inputs = dag_distributed_submitter.validate_distributed_stage_inputs(
        kwargs["unit"], kwargs["input_artifacts"],
    )
    run_child, events, _ = _execute_fake_distributed_child(
        monkeypatch, kwargs, inputs, result=result, fail=raises,
    )
    with pytest.raises(RuntimeError if raises else SystemExit):
        run_child()
    stdout = capsys.readouterr().out
    assert "consumed_artifacts" not in stdout
    assert [event[0] for event in events] == ["context_read", "fake_install", "fake_run"]


def test_generated_child_rechecks_identity_before_any_sdk_call(tmp_path, monkeypatch):
    kwargs, _, row, _ = _upstream_stage_case(tmp_path, monkeypatch)
    inputs = dag_distributed_submitter.validate_distributed_stage_inputs(
        kwargs["unit"], kwargs["input_artifacts"],
    )
    run_child, events, _ = _execute_fake_distributed_child(
        monkeypatch, kwargs, inputs, result={"status": "ok"},
    )
    Path(row["path"]).write_text('{"packets_generated": 8, "packets_delivered": 2}')
    with pytest.raises(ValueError, match="completed producer bytes"):
        run_child()
    assert not events


def test_generated_child_preserves_non_json_dataset_reference(tmp_path, monkeypatch, capsys):
    import hashlib

    kwargs, _, row, _ = _upstream_stage_case(tmp_path, monkeypatch)
    Path(row["path"]).write_bytes(b"\x00\xffnon-json-dataset")
    row.update(
        id="input_dataset", kind="dataset", producer="dataset_source",
        size_bytes=Path(row["path"]).stat().st_size,
        sha256=hashlib.sha256(Path(row["path"]).read_bytes()).hexdigest(),
    )
    kwargs["unit"]["artifact_dependencies"] = [
        {"from": "dataset_source", "artifact": "input_dataset"}
    ]
    inputs = dag_distributed_submitter.validate_distributed_stage_inputs(
        kwargs["unit"], kwargs["input_artifacts"],
    )
    run_child, events, captured = _execute_fake_distributed_child(
        monkeypatch, kwargs, inputs, result={"status": "ok"},
    )
    run_child()
    assert [event[0] for event in events] == ["fake_install", "fake_run"]
    receipt = json.loads(capsys.readouterr().out)["result"]["consumed_artifacts"][0]
    assert receipt["role"] == "declared_input_reference"
    assert "summary_metrics" not in receipt
    assert receipt["path"] == row["path"]
    assert captured["request"].data_in == "uav_relay_queue/scenarios"


def test_configured_submitter_forwards_original_input_bindings(tmp_path, monkeypatch):
    kwargs, calls, _, metrics = _upstream_stage_case(tmp_path, monkeypatch)
    monkeypatch.setattr(
        dag_distributed_submitter, "dag_distributed_stage_config_from_settings",
        lambda *args, **options: kwargs["config"],
    )
    submit = dag_distributed_submitter.build_multi_app_dag_distributed_stage_submitter(
        env=SimpleNamespace(), runner_fn=kwargs.pop("runner_fn"),
    )
    kwargs.pop("config")
    result = submit(**kwargs)
    assert calls[0]["request_payload"]["input_artifacts"][0]["artifact"] == "queue_metrics"
    assert result["consumed_artifacts"][0]["summary_metrics"] == metrics


def test_distributed_input_receipts_preserve_only_no_input_legacy_cache_compatibility(
    tmp_path, monkeypatch,
):
    module = dag_distributed_submitter
    module.require_distributed_input_receipts({"legacy": True}, [], app_name="anything")
    kwargs, _, _, _ = _upstream_stage_case(tmp_path, monkeypatch)
    inputs = module.validate_distributed_stage_inputs(kwargs["unit"], kwargs["input_artifacts"])
    with pytest.raises(ValueError, match="missing original upstream inputs"):
        module.require_distributed_input_receipts(
            {"legacy": True}, inputs, app_name=kwargs["unit"]["app"],
        )
    with pytest.raises(ValueError, match="different or missing original upstream inputs"):
        module.require_distributed_input_receipts(
            {"input_artifact_fingerprint": module._input_artifact_fingerprint(inputs)},
            [], app_name=kwargs["unit"]["app"],
        )


@pytest.mark.parametrize("metadata", [
    {"identity_kind": "directory", "entry_count": True},
    {"identity_kind": "directory", "entry_count": 1},
    {"identity_kind": "unsupported"},
    {"entry_count": 1},
])
def test_distributed_directory_metadata_fails_before_target_read(tmp_path, monkeypatch, metadata):
    kwargs, calls, row, _ = _upstream_stage_case(tmp_path, monkeypatch)
    row.update(metadata)
    original_open = Path.open

    def no_target_read(path, *args, **options):
        if path == Path(row["path"]):
            pytest.fail("Malformed directory identity must fail before target reads")
        return original_open(path, *args, **options)

    monkeypatch.setattr(Path, "open", no_target_read)
    with pytest.raises(ValueError, match="identity"):
        dag_distributed_submitter.submit_distributed_stage(**kwargs)
    assert not calls


def test_stage_subprocess_preserves_verified_child_consumption_receipt(
    tmp_path, monkeypatch,
):
    module = dag_distributed_submitter
    kwargs, _, _, metrics = _upstream_stage_case(tmp_path, monkeypatch)
    inputs = module.validate_distributed_stage_inputs(kwargs["unit"], kwargs["input_artifacts"])
    receipt = {
        **inputs[0], "summary_metrics": metrics, "role": "upstream_context",
        "read_scope": "child_orchestrator", "numerically_conditioned": False,
    }

    def fake_run(command, **options):
        options["stdout"].write(json.dumps({"result": {
            "status": "ok", "consumed_artifacts": [receipt],
        }}) + "\n")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    payload = module.request_payload_from_execution_contract(kwargs["execution_contract"])
    payload["input_artifacts"] = inputs
    call = dict(
        config=kwargs["config"], repo_root=tmp_path, run_root=kwargs["run_root"],
        apps_path=tmp_path / "apps", app_name=kwargs["unit"]["app"],
        request_payload=payload, timestamp=kwargs["timestamp"],
        idempotency_token=kwargs["idempotency_token"],
    )
    result = module.run_agilab_stage_subprocess(**call)
    assert result["consumed_artifacts"] == [receipt]
    assert module.run_agilab_stage_subprocess(**call) == result


def _worker_summary_collection_case(tmp_path):
    module = dag_distributed_submitter
    repo_root = tmp_path / "repo"
    _write_app(repo_root, "src/agilab/apps/builtin", "uav_queue_project")
    run_root = tmp_path / "run"
    share = tmp_path / "worker-share"
    output_root = share / "uav_queue/results"
    config = module.DagDistributedStageConfig(
        scheduler="127.0.0.1:18786", workers={"127.0.0.1": 1},
        workers_data_path=str(share), mode=4,
    )
    artifact = {
        "artifact": "queue_metrics", "kind": "summary_metrics",
        "path": "queue_analysis/uav_queue_summary_metrics.json",
    }
    metrics = {
        "artifact_stem": "scenario_shortest_path_seed2026",
        "sim_time_s": 30.0, "source_rate_pps": 14.0,
        "sampling_interval_s": 0.5, "queue_weight": 2.5,
        "random_seed": 2026, "routing_policy": "shortest_path",
        "packets_generated": 420, "packets_delivered": 400, "packets_dropped": 20,
    }
    source = output_root / metrics["artifact_stem"] / (
        metrics["artifact_stem"] + "_summary_metrics.json"
    )
    kwargs = dict(
        config=config, repo_root=repo_root, lab_dir=tmp_path / "lab",
        run_root=run_root, unit={
            "id": "queue_baseline", "app": "uav_queue_project",
            "produces": [artifact],
        },
        artifact=artifact,
        execution_contract={"data_out": "uav_queue/results", "params": metrics},
        timestamp="2026-10-15T10:00:00Z", idempotency_token="worker-output:queue",
    )
    return module, kwargs, source, metrics


def test_worker_summary_collection_preserves_real_runtime_string_output_bytes(
    tmp_path, monkeypatch,
):
    import hashlib

    module, kwargs, source, metrics = _worker_summary_collection_case(tmp_path)
    raw = (json.dumps(metrics, indent=2) + "\n").encode()

    def fake_subprocess(command, **run_kwargs):
        source.parent.mkdir(parents=True)
        source.write_bytes(raw)
        run_kwargs["stdout"].write(json.dumps({"result": "distributed Python 1.2s"}) + "\n")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(module.subprocess, "run", fake_subprocess)
    result = module.submit_distributed_stage(
        **kwargs, runner_fn=module.run_agilab_stage_subprocess,
    )
    alias = kwargs["run_root"] / kwargs["artifact"]["path"]
    assert alias.read_bytes() == raw
    assert result["summary_metrics_path"] == str(alias)
    assert all(result["summary_metrics"][key] == value for key, value in metrics.items())
    receipt = result["worker_output_collection"][0]
    assert receipt["artifact"] == "queue_metrics"
    assert receipt["source_path"] == str(source)
    assert receipt["path"] == str(alias)
    assert receipt["source_identity"] == {
        "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
    }
    assert receipt["copied_sha256"] == hashlib.sha256(raw).hexdigest()
    evidence = json.loads(Path(result["submission_evidence_path"]).read_text())
    assert evidence["worker_output_collection"] == [receipt]
    assert result["produced_artifacts"][0]["sha256"] == receipt["copied_sha256"]


@pytest.mark.parametrize("pollution", [
    "stale", "ambiguous", "source_symlink", "directory_symlink",
    "outside_data_out", "receipt", "invalid_json", "nonfinite", "operational_only",
    "failed_run", "null_run", "escape_alias", "linked_alias_parent",
    "reported_missing_path",
])
def test_worker_summary_collection_rejects_unqualified_outputs(
    tmp_path, monkeypatch, pollution,
):
    module, kwargs, source, metrics = _worker_summary_collection_case(tmp_path)
    raw = json.dumps(metrics).encode()
    source.parent.mkdir(parents=True)
    if pollution == "stale":
        source.write_bytes(raw)
    alias = kwargs["run_root"] / kwargs["artifact"]["path"]
    if pollution == "escape_alias":
        kwargs["artifact"]["path"] = "../escaped_summary_metrics.json"
    if pollution == "linked_alias_parent":
        outside = tmp_path / "outside-alias"
        outside.mkdir()
        kwargs["run_root"].mkdir()
        alias.parent.symlink_to(outside, target_is_directory=True)

    def fake_subprocess(command, **run_kwargs):
        if pollution not in {"stale", "outside_data_out", "directory_symlink"}:
            if pollution == "source_symlink":
                target = tmp_path / "outside_summary_metrics.json"
                target.write_bytes(raw)
                source.symlink_to(target)
            elif pollution == "receipt":
                source.write_text(json.dumps({
                    "schema": "agilab.distributed_dag_stage_submission.v1",
                    "summary_metrics": metrics,
                }))
            elif pollution == "invalid_json":
                source.write_text("{")
            elif pollution == "nonfinite":
                source.write_text('{"sim_time_s": NaN}')
            elif pollution == "operational_only":
                source.write_text('{"stage_completed": 1, "distributed_submissions": 1}')
            else:
                source.write_bytes(raw)
        if pollution == "ambiguous":
            (source.parent / "other_summary_metrics.json").write_bytes(raw)
        if pollution == "directory_symlink":
            target = tmp_path / "outside-worker"
            target.mkdir()
            (target / "outside_summary_metrics.json").write_bytes(raw)
            (source.parent.parent / "linked").symlink_to(target, target_is_directory=True)
        if pollution == "outside_data_out":
            (source.parents[2] / "unrelated_summary_metrics.json").write_bytes(raw)
        stage_result = (
            {"status": "error", "message": "failed worker"}
            if pollution == "failed_run" else
            None if pollution == "null_run" else
            {"summary_metrics_path": "missing_summary_metrics.json"}
            if pollution == "reported_missing_path" else
            "distributed Python 1.2s"
        )
        run_kwargs["stdout"].write(json.dumps({"result": stage_result}) + "\n")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(module.subprocess, "run", fake_subprocess)
    with pytest.raises((RuntimeError, ValueError)):
        module.submit_distributed_stage(
            **kwargs, runner_fn=module.run_agilab_stage_subprocess,
        )
    assert not alias.is_file()
    assert not (tmp_path / "escaped_summary_metrics.json").exists()


def test_worker_summary_collection_replaces_stale_alias_only_from_fresh_source(
    tmp_path, monkeypatch,
):
    module, kwargs, source, metrics = _worker_summary_collection_case(tmp_path)
    alias = kwargs["run_root"] / kwargs["artifact"]["path"]
    alias.parent.mkdir(parents=True)
    alias.write_text('{"sim_time_s": 1}')
    raw = json.dumps(metrics).encode()

    def fake_subprocess(command, **run_kwargs):
        source.parent.mkdir(parents=True)
        source.write_bytes(raw)
        run_kwargs["stdout"].write(json.dumps({"result": "distributed Python 1.2s"}) + "\n")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(module.subprocess, "run", fake_subprocess)
    result = module.submit_distributed_stage(
        **kwargs, runner_fn=module.run_agilab_stage_subprocess,
    )
    assert alias.read_bytes() == raw
    assert result["summary_metrics"]["sim_time_s"] == 30.0


def _write_worker_runtime_summary(module, monkeypatch, source, metrics):
    def fake_subprocess(command, **run_kwargs):
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(json.dumps(metrics))
        run_kwargs["stdout"].write(json.dumps({"result": "distributed Python 1.2s"}) + "\n")
        return subprocess.CompletedProcess(command, 0)
    monkeypatch.setattr(module.subprocess, "run", fake_subprocess)


def test_worker_summary_collection_uses_effective_cluster_share_with_workflow_subdir(
    tmp_path, monkeypatch,
):
    from dataclasses import replace

    module, kwargs, source, metrics = _worker_summary_collection_case(tmp_path)
    share = source.parents[3]
    monkeypatch.setenv("AGI_CLUSTER_SHARE", str(share))
    kwargs["config"] = replace(kwargs["config"], workers_data_path=str(share / "workflows"))
    _write_worker_runtime_summary(module, monkeypatch, source, metrics)
    result = module.submit_distributed_stage(
        **kwargs, runner_fn=module.run_agilab_stage_subprocess,
    )
    assert result["worker_output_collection"][0]["source_path"] == str(source)
    assert result["summary_metrics"]["packets_generated"] == 420


def test_worker_summary_collection_rejects_oversize_before_file_identity(
    tmp_path, monkeypatch,
):
    module, kwargs, source, metrics = _worker_summary_collection_case(tmp_path)
    def fake_subprocess(command, **run_kwargs):
        source.parent.mkdir(parents=True)
        source.write_bytes(b"x" * (1024 * 1024 + 1))
        run_kwargs["stdout"].write(json.dumps({"result": "distributed Python 1.2s"}) + "\n")
        return subprocess.CompletedProcess(command, 0)
    original_identity = module.artifact_file_identity
    def guarded_identity(path):
        assert path != source, "Oversized source must be rejected before hashing."
        return original_identity(path)
    monkeypatch.setattr(module.subprocess, "run", fake_subprocess)
    monkeypatch.setattr(module, "artifact_file_identity", guarded_identity)
    with pytest.raises(RuntimeError, match="bounded collection size"):
        module.submit_distributed_stage(
            **kwargs, runner_fn=module.run_agilab_stage_subprocess,
        )


def test_worker_summary_collection_rejects_source_parent_replaced_during_read(
    tmp_path, monkeypatch,
):
    module, kwargs, source, metrics = _worker_summary_collection_case(tmp_path)
    _write_worker_runtime_summary(module, monkeypatch, source, metrics)
    original_open = Path.open
    replaced = []
    def replaced_parent(path, *args, **open_kwargs):
        stream = original_open(path, *args, **open_kwargs)
        if path == source and args and args[0] == "rb" and not replaced:
            moved = source.parent.with_name("moved-scenario")
            source.parent.rename(moved)
            source.parent.symlink_to(moved, target_is_directory=True)
            replaced.append(True)
        return stream
    monkeypatch.setattr(Path, "open", replaced_parent)
    with pytest.raises(RuntimeError, match="symlink or junction") as caught:
        module.submit_distributed_stage(
            **kwargs, runner_fn=module.run_agilab_stage_subprocess,
        )
    assert isinstance(caught.value.__cause__, ValueError)
    assert not (kwargs["run_root"] / kwargs["artifact"]["path"]).exists()


def test_worker_summary_collection_propagates_inventory_permission_failure(
    tmp_path, monkeypatch,
):
    module, kwargs, source, metrics = _worker_summary_collection_case(tmp_path)
    _write_worker_runtime_summary(module, monkeypatch, source, metrics)
    output_root = source.parent.parent
    original_walk = module.os.walk
    def denied_walk(top, *args, **walk_kwargs):
        if Path(top) == output_root and source.exists():
            callback = walk_kwargs.get("onerror")
            if callback:
                callback(PermissionError("unreadable newly produced output subtree"))
            return
        yield from original_walk(top, *args, **walk_kwargs)
    monkeypatch.setattr(module.os, "walk", denied_walk)
    with pytest.raises(RuntimeError, match="unreadable newly produced") as caught:
        module.submit_distributed_stage(
            **kwargs, runner_fn=module.run_agilab_stage_subprocess,
        )
    assert isinstance(caught.value.__cause__, PermissionError)


def test_worker_summary_collection_missing_output_names_searched_data_roots(
    tmp_path, monkeypatch,
):
    module, kwargs, source, metrics = _worker_summary_collection_case(tmp_path)
    def fake_subprocess(command, **run_kwargs):
        run_kwargs["stdout"].write(json.dumps({"result": "distributed Python 1.2s"}) + "\n")
        return subprocess.CompletedProcess(command, 0)
    monkeypatch.setattr(module.subprocess, "run", fake_subprocess)
    with pytest.raises(RuntimeError) as caught:
        module.submit_distributed_stage(
            **kwargs, runner_fn=module.run_agilab_stage_subprocess,
        )
    assert "missing" in str(caught.value)
    assert "searched data_out roots" in str(caught.value)
    assert str(source.parent.parent) in str(caught.value)


def test_worker_summary_collection_ignores_unrelated_cluster_share_pollution(
    tmp_path, monkeypatch,
):
    module, kwargs, source, metrics = _worker_summary_collection_case(tmp_path)
    unrelated = tmp_path / "unrelated-cluster-share"
    monkeypatch.setenv("AGI_CLUSTER_SHARE", str(unrelated))
    foreign = unrelated / "uav_queue/results/scenario/unrelated_summary_metrics.json"
    _write_worker_runtime_summary(module, monkeypatch, foreign, metrics)
    with pytest.raises(RuntimeError, match="missing"):
        module.submit_distributed_stage(
            **kwargs, runner_fn=module.run_agilab_stage_subprocess,
        )
    assert not (kwargs["run_root"] / kwargs["artifact"]["path"]).exists()


def test_worker_summary_collection_rejects_different_open_file_descriptor(
    tmp_path, monkeypatch,
):
    module, kwargs, source, metrics = _worker_summary_collection_case(tmp_path)
    _write_worker_runtime_summary(module, monkeypatch, source, metrics)
    foreign = tmp_path / "foreign_same_bytes_summary_metrics.json"
    foreign.write_text(json.dumps(metrics))
    original_open = Path.open
    def redirected_open(path, *args, **open_kwargs):
        if path == source and args and args[0] == "rb":
            return original_open(foreign, *args, **open_kwargs)
        return original_open(path, *args, **open_kwargs)
    monkeypatch.setattr(Path, "open", redirected_open)
    with pytest.raises(RuntimeError, match="different file generation"):
        module.submit_distributed_stage(
            **kwargs, runner_fn=module.run_agilab_stage_subprocess,
        )
    assert not (kwargs["run_root"] / kwargs["artifact"]["path"]).exists()
