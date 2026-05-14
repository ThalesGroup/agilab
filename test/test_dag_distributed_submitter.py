from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
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


def test_build_global_submitter_runs_configured_runner(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _write_app(repo_root, "src/agilab/apps/builtin", "flight_telemetry_project")
    env = SimpleNamespace(app_settings_file=None)
    calls: list[dict[str, object]] = []

    def _runner(**kwargs):
        calls.append(kwargs)
        return {"summary_metrics": {"factory_runner": 1}}

    submitter = dag_distributed_submitter.build_global_dag_distributed_stage_submitter(
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
        artifact={"artifact": "stage_result"},
        execution_contract={"params": {}, "stages": []},
        timestamp="2026-05-07T00:00:00Z",
    )

    assert calls[0]["config"].verbose == 3
    assert result["summary_metrics"]["factory_runner"] == 1


def test_build_global_submitter_returns_none_without_cluster() -> None:
    submitter = dag_distributed_submitter.build_global_dag_distributed_stage_submitter(
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
        return {"summary_metrics": {"runner_confirmed": 1}}

    result = dag_distributed_submitter.submit_distributed_stage(
        config=config,
        runner_fn=_runner,
        repo_root=repo_root,
        lab_dir=tmp_path / "lab",
        run_root=tmp_path / "lab/.agilab/global_dag_real_runs/flight_context",
        unit={"id": "flight_context", "app": "flight_telemetry_project"},
        artifact={"artifact": "flight_reduce_summary", "kind": "reduce_summary", "path": "flight/reduce.json"},
        execution_contract={
            "entrypoint": "flight_telemetry_project.flight_context",
            "params": {"scenario": "demo"},
            "stages": [{"name": "prepare", "args": {"n": 2}}],
        },
        timestamp="2026-05-07T00:00:00Z",
    )

    assert len(calls) == 1
    assert calls[0]["apps_path"] == repo_root / "src/agilab/apps/builtin"
    assert calls[0]["app_name"] == "flight_telemetry_project"
    assert calls[0]["request_payload"]["params"] == {"scenario": "demo"}
    assert calls[0]["request_payload"]["stages"] == [{"name": "prepare", "args": {"n": 2}}]
    evidence_path = Path(result["submission_evidence_path"])
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["schema"] == "agilab.distributed_dag_stage_submission.v1"
    assert evidence["app"] == "flight_telemetry_project"
    assert evidence["cluster"]["worker_nodes"] == 2
    assert result["reduce_artifact_path"] == str(evidence_path)
    assert result["summary_metrics"]["worker_slots"] == 3
    assert result["summary_metrics"]["runner_confirmed"] == 1

    non_mapping_result = dag_distributed_submitter.submit_distributed_stage(
        config=config,
        runner_fn=lambda **_kwargs: {"summary_metrics": ["ignored"]},
        repo_root=repo_root,
        lab_dir=tmp_path / "lab",
        run_root=tmp_path / "lab/.agilab/global_dag_real_runs/default_metrics",
        unit={"id": "flight_context", "app": "flight_telemetry_project"},
        artifact={"artifact": "default_metrics"},
        execution_contract={},
        timestamp="2026-05-07T00:00:01Z",
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
                        "data_in": "flight/dataset",
                        "data_out": "flight/dataframe",
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
                '{"benchmark_best_single_node":false,"data_in":"flight/dataset",'
                '"data_out":"flight/dataframe","params":{"scenario":"demo"},'
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
    assert dag_distributed_submitter._distributed_evidence_path(run_root, {"artifact": "safe", "path": "safe/out.json"}) == (
        run_root / "safe/out.json"
    )
    assert dag_distributed_submitter._distributed_evidence_path(run_root, {"id": "fallback", "path": "../unsafe"}) == (
        run_root / "fallback.json"
    )
    assert dag_distributed_submitter._distributed_evidence_path(run_root, {"path": str(tmp_path / "absolute")}) == (
        run_root / "stage_result.json"
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

    def _fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        kwargs["stdout"].write('{"result": null}\n')
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
    )

    script = (tmp_path / "run/run_distributed_stage.py").read_text(encoding="utf-8")
    assert "await AGI.install(" in script
    assert "modes_enabled=7" in script
    assert "await AGI.run(app_env, request=request)" in script
    assert "workers_data_path='clustershare/agi'" in script
    assert captured["command"][0] == sys.executable
    assert captured["kwargs"]["stdout"] is not subprocess.PIPE
    assert captured["kwargs"]["stderr"] is not subprocess.PIPE
    assert "capture_output" not in captured["kwargs"]
    assert result["returncode"] == 0
    assert result["stdout_tail"] == '{"result": null}\n'
    assert result["stdout_log"].endswith("distributed_stage.stdout.log")
    assert result["stderr_log"].endswith("distributed_stage.stderr.log")


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
        )

    message = str(err.value)
    assert "Distributed DAG stage `flight_telemetry_project` failed" in message
    assert len(message) < 4100
