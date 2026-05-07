from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace


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


def test_submit_distributed_stage_runs_fake_runner_and_writes_evidence(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _write_app(repo_root, "src/agilab/apps/builtin", "flight_project")
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
        unit={"id": "flight_context", "app": "flight_project"},
        artifact={"artifact": "flight_reduce_summary", "kind": "reduce_summary", "path": "flight/reduce.json"},
        execution_contract={
            "entrypoint": "flight_project.flight_context",
            "params": {"scenario": "demo"},
            "steps": [{"name": "prepare", "args": {"n": 2}}],
        },
        timestamp="2026-05-07T00:00:00Z",
    )

    assert len(calls) == 1
    assert calls[0]["apps_path"] == repo_root / "src/agilab/apps/builtin"
    assert calls[0]["app_name"] == "flight_project"
    assert calls[0]["request_payload"]["params"] == {"scenario": "demo"}
    assert calls[0]["request_payload"]["steps"] == [{"name": "prepare", "args": {"n": 2}}]
    evidence_path = Path(result["submission_evidence_path"])
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["schema"] == "agilab.distributed_dag_stage_submission.v1"
    assert evidence["app"] == "flight_project"
    assert evidence["cluster"]["worker_nodes"] == 2
    assert result["reduce_artifact_path"] == str(evidence_path)
    assert result["summary_metrics"]["worker_slots"] == 3
    assert result["summary_metrics"]["runner_confirmed"] == 1


def test_resolve_stage_apps_path_supports_repository_apps(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _write_app(repo_root, "src/agilab/apps", "custom_project")

    assert dag_distributed_submitter.resolve_stage_apps_path(repo_root, "custom_project") == (
        repo_root / "src/agilab/apps"
    )


def test_stage_subprocess_runner_generates_isolated_agilab_run_script(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def _fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, stdout='{"result": null}\n', stderr="")

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
        app_name="flight_project",
        request_payload={"params": {}, "steps": []},
        timestamp="2026-05-07T00:00:00Z",
    )

    script = (tmp_path / "run/run_distributed_stage.py").read_text(encoding="utf-8")
    assert "await AGI.run(app_env, request=request)" in script
    assert "workers_data_path='clustershare/agi'" in script
    assert captured["command"][0] == sys.executable
    assert result["returncode"] == 0
