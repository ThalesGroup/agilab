from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace


MODULE_PATH = Path("tools/dag_distributed_stage_smoke.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("dag_distributed_stage_smoke_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_distributed_stage_smoke_dry_run_writes_two_node_request_preview(tmp_path: Path) -> None:
    module = _load_module()
    output = tmp_path / "dag-smoke.json"

    report = module.build_smoke_report(
        repo_root=Path.cwd(),
        dag_path=Path("src/agilab/apps/builtin/flight_telemetry_project/dag_templates/flight_to_weather.json"),
        output_path=output,
        settings={
            "cluster": {
                "cluster_enabled": True,
                "scheduler": "192.168.20.111:8786",
                "workers": {"192.168.20.111": 1, "192.168.20.15": 1},
                "workers_data_path": "clustershare/agi",
                "pool": True,
                "cython": True,
                "rapids": True,
            }
        },
        execute=False,
        require_two_nodes=True,
        verbose=1,
    )

    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved == report
    assert report["schema"] == "agilab.distributed_dag_stage_smoke.v1"
    assert report["status"] == "pass"
    assert report["mode"] == "dry_run"
    assert report["two_node_ready"] is True
    assert report["cluster"]["worker_nodes"] == 2
    assert [row["Stage"] for row in report["distributed_request_preview"]] == [
        "flight_context",
        "weather_forecast_review",
    ]
    first_request = json.loads(report["distributed_request_preview"][0]["Request"])
    assert first_request["params"]["output_format"] == "parquet"
    assert first_request["data_in"] == "flight/dataset"
    assert first_request["stages"] == []


def test_distributed_stage_smoke_execute_requires_complete_cluster_settings(tmp_path: Path) -> None:
    module = _load_module()
    output = tmp_path / "dag-smoke.json"

    report = module.build_smoke_report(
        repo_root=Path.cwd(),
        dag_path=Path("src/agilab/apps/builtin/flight_telemetry_project/dag_templates/flight_to_weather.json"),
        output_path=output,
        settings={},
        execute=True,
        require_two_nodes=True,
    )

    assert report["status"] == "fail"
    assert report["cluster_ready"] is False
    assert "requires enabled cluster settings" in report["message"]


def test_distributed_stage_smoke_execute_requires_two_nodes_by_default(tmp_path: Path) -> None:
    module = _load_module()

    report = module.build_smoke_report(
        repo_root=Path.cwd(),
        dag_path=Path("src/agilab/apps/builtin/flight_telemetry_project/dag_templates/flight_to_weather.json"),
        output_path=tmp_path / "dag-smoke.json",
        settings={
            "cluster": {
                "cluster_enabled": True,
                "scheduler": "192.168.20.111:8786",
                "workers": {"192.168.20.111": 1},
                "workers_data_path": "clustershare/agi",
            }
        },
        execute=True,
        require_two_nodes=True,
    )

    assert report["status"] == "fail"
    assert report["cluster_ready"] is True
    assert report["two_node_ready"] is False
    assert report["required_nodes"] == 2
    assert "requires at least two configured worker nodes" in report["message"]


def test_distributed_stage_smoke_execute_can_use_single_node_when_allowed(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()

    def _fake_execute(_engine, _state, *, config):
        return {
            "executed_unit_ids": ["flight_context"],
            "failed_unit_ids": [],
            "message": f"executed on {config.worker_nodes} node",
            "final_state": {"summary": {"completed_count": 1, "unit_count": 1}},
        }

    monkeypatch.setattr(module, "_execute_ready_stage_waves", _fake_execute)

    report = module.build_smoke_report(
        repo_root=Path.cwd(),
        dag_path=Path("src/agilab/apps/builtin/flight_telemetry_project/dag_templates/flight_to_weather.json"),
        output_path=tmp_path / "dag-smoke.json",
        settings={
            "cluster": {
                "cluster_enabled": True,
                "scheduler": "192.168.20.111:8786",
                "workers": {"192.168.20.111": 1},
                "workers_data_path": "clustershare/agi",
            }
        },
        execute=True,
        require_two_nodes=False,
    )

    assert report["status"] == "pass"
    assert report["required_nodes"] == 1
    assert report["executed_unit_ids"] == ["flight_context"]
    assert report["message"] == "executed on 1 node"


def test_distributed_stage_smoke_loads_settings_files_and_cli_payloads(tmp_path: Path) -> None:
    module = _load_module()
    json_settings = tmp_path / "settings.json"
    json_settings.write_text(
        json.dumps(
            {
                "cluster": {
                    "cluster_enabled": True,
                    "scheduler": "192.168.20.111:8786",
                    "workers": {"192.168.20.111": 1, "192.168.20.15": 1},
                    "workers_data_path": "clustershare/agi",
                }
            }
        ),
        encoding="utf-8",
    )
    toml_settings = tmp_path / "settings.toml"
    toml_settings.write_text(
        """
[cluster]
cluster_enabled = true
scheduler = "192.168.20.111:8786"
workers_data_path = "clustershare/agi"

[cluster.workers]
"192.168.20.111" = 1
""".strip()
        + "\n",
        encoding="utf-8",
    )

    assert module._load_settings(settings=None, settings_file=None) == {}
    assert module._load_settings(settings={"cluster": {"cluster_enabled": False}}, settings_file=json_settings) == {
        "cluster": {"cluster_enabled": False}
    }
    assert module._load_settings(settings=None, settings_file=json_settings) == {}
    assert module._load_toml(toml_settings)["cluster"]["scheduler"] == "192.168.20.111:8786"

    args = SimpleNamespace(
        scheduler="192.168.20.111:8786",
        workers="192.168.20.111=1,192.168.20.15=2",
        workers_data_path="clustershare/agi",
        pool=True,
        cython=False,
        rapids=True,
    )
    settings = module._settings_from_cli(args)
    assert settings["cluster"]["workers"] == {"192.168.20.111": 1, "192.168.20.15": 2}
    assert settings["cluster"]["cython"] is False
    assert module._settings_from_cli(
        SimpleNamespace(scheduler="", workers="", workers_data_path="", pool=True, cython=True, rapids=False)
    ) is None

    assert module._parse_workers('{"a": 1, "b": 0}') == {"a": 1}
    assert module._parse_workers("{'a': 2}") == {"a": 2}
    assert module._parse_workers("a,b=3,,c=1") == {"a": 1, "b": 3, "c": 1}
    assert module._parse_workers("") == {}


def test_distributed_stage_smoke_main_supports_settings_json_and_files(tmp_path: Path, capsys) -> None:
    module = _load_module()
    output = tmp_path / "dag-smoke.json"
    settings = {
        "cluster": {
            "cluster_enabled": True,
            "scheduler": "192.168.20.111:8786",
            "workers": {"192.168.20.111": 1, "192.168.20.15": 1},
            "workers_data_path": "clustershare/agi",
        }
    }

    rc = module.main(
        [
            "--repo-root",
            str(Path.cwd()),
            "--dag",
            "src/agilab/apps/builtin/flight_telemetry_project/dag_templates/flight_to_weather.json",
            "--output",
            str(output),
            "--settings-json",
            json.dumps(settings),
            "--compact",
        ]
    )

    assert rc == 0
    stdout = capsys.readouterr().out
    assert '"status":"pass"' in stdout
    assert json.loads(output.read_text(encoding="utf-8"))["cluster"]["worker_nodes"] == 2

    json_settings = tmp_path / "settings.json"
    json_settings.write_text(json.dumps(settings), encoding="utf-8")
    rc = module.main(
        [
            "--repo-root",
            str(Path.cwd()),
            "--dag",
            "src/agilab/apps/builtin/flight_telemetry_project/dag_templates/flight_to_weather.json",
            "--output",
            str(tmp_path / "dag-smoke-from-file.json"),
            "--settings-file",
            str(json_settings),
        ]
    )

    assert rc == 0


def test_execute_ready_stage_waves_stops_after_failure(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()

    class FakeExecutionEngine:
        def __init__(self, **kwargs):
            self.repo_root = kwargs["repo_root"]
            self.lab_dir = kwargs["lab_dir"]
            self.dag_path = kwargs["dag_path"]
            self.state_filename = kwargs["state_filename"]
            self.now_fn = kwargs["now_fn"]
            self.written_states: list[dict[str, object]] = []

        def run_ready_controlled_stages(self, state, *, execution_backend):
            assert execution_backend == module.GLOBAL_DAG_STAGE_BACKEND_DISTRIBUTED
            return SimpleNamespace(
                message="failed wave",
                state={**state, "summary": {"completed_count": 0, "unit_count": 1}},
                executed_unit_ids=[],
                failed_unit_ids=["flight_context"],
            )

        def write_state(self, state):
            self.written_states.append(dict(state))

    monkeypatch.setattr(module, "DagRunEngine", FakeExecutionEngine)
    engine = SimpleNamespace(
        repo_root=tmp_path,
        lab_dir=tmp_path / "lab",
        dag_path=tmp_path / "dag.json",
        state_filename="state.json",
        now_fn=lambda: "now",
    )
    config = module.DagDistributedStageConfig(
        scheduler="192.168.20.111:8786",
        workers={"192.168.20.111": 1},
        workers_data_path="clustershare/agi",
        mode=7,
    )

    report = module._execute_ready_stage_waves(
        engine,
        {"units": [{"id": "flight_context"}]},
        config=config,
    )

    assert report["executed_unit_ids"] == []
    assert report["failed_unit_ids"] == ["flight_context"]
    assert report["message"] == "failed wave"
