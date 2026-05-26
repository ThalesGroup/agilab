from __future__ import annotations

import importlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from agilab import bridge_cli, run_manifest
from agilab_mcp import manifest_tools, server as mcp_server


def _write_manifest(
    tmp_path: Path, *, status: str = "pass", duration: float = 1.25
) -> Path:
    artifact = tmp_path / f"artifact-{duration}.txt"
    artifact.write_text("evidence\n", encoding="utf-8")
    manifest = run_manifest.build_run_manifest(
        path_id="audience-bridge-proof",
        label="Audience bridge proof",
        status=status,
        command=run_manifest.RunManifestCommand(
            label="demo",
            argv=("python", "demo.py"),
            cwd=str(tmp_path),
            env_overrides={},
        ),
        environment=run_manifest.RunManifestEnvironment(
            python_version="3.13",
            python_executable=sys.executable,
            platform="test",
            repo_root=str(tmp_path),
            active_app=str(tmp_path / "demo_project"),
            app_name="demo_project",
        ),
        timing=run_manifest.RunManifestTiming(
            started_at="2026-05-26T00:00:00Z",
            finished_at="2026-05-26T00:00:01Z",
            duration_seconds=duration,
            target_seconds=10.0,
        ),
        artifacts=[
            run_manifest.RunManifestArtifact.from_path(
                artifact,
                name="evidence",
                kind="text",
            )
        ],
        validations=[
            run_manifest.RunManifestValidation(
                label="schema",
                status=status,
                summary="manifest validates",
                details={"score": 1.0},
            )
        ],
    )
    return run_manifest.write_run_manifest(
        manifest, tmp_path / f"run-{duration}" / "run_manifest.json"
    )


def test_quarto_export_and_run_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest_path = _write_manifest(tmp_path)
    qmd = tmp_path / "report.qmd"

    payload = bridge_cli.export_quarto_report(
        manifest_path,
        qmd,
        render=True,
        which=lambda _name: None,
    )

    assert payload["status"] == "pass"
    assert payload["render"]["status"] == "skipped"
    report = qmd.read_text(encoding="utf-8")
    assert "AGILAB Run Report" in report
    assert "Audience bridge proof" in report
    assert "SHA-256" in report
    assert (tmp_path / "manifest.json").is_file()

    rc = bridge_cli.main(
        [
            "run",
            "quarto",
            "--run",
            str(manifest_path),
            "--output",
            str(tmp_path / "run-report.qmd"),
            "--no-render",
            "--json",
        ]
    )
    assert rc == 0
    emitted = json.loads(capsys.readouterr().out)
    assert emitted["schema"] == "agilab.bridge.quarto_export.v1"


def test_hf_space_export_and_secret_rejection(tmp_path: Path) -> None:
    project = tmp_path / "demo_project"
    project.mkdir()
    (project / "README.md").write_text("# Demo\n", encoding="utf-8")

    payload = bridge_cli.export_hf_space(project, tmp_path / "hf", force=True)

    assert payload["status"] == "pass"
    assert (tmp_path / "hf" / "Dockerfile").is_file()
    assert (tmp_path / "hf" / "app.py").is_file()
    assert (tmp_path / "hf" / "agilab_project" / "README.md").is_file()

    (project / ".env").write_text("OPENAI_API_KEY=sk-real-value\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="secret-like"):
        bridge_cli.export_hf_space(project, tmp_path / "hf-secret", force=True)


def test_mlflow_vscode_and_workflow_handoff_exports(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path)

    mlflow_payload = bridge_cli.export_mlflow_handoff(
        manifest_path,
        tmp_path / "mlflow_export.json",
    )
    assert mlflow_payload["params"]["agilab_app"] == "demo_project"
    assert mlflow_payload["metrics"]["duration_seconds"] == 1.25

    imported = bridge_cli.import_mlflow_handoff(
        "demo",
        tmp_path / "mlflow_import.json",
        input_path=tmp_path / "mlflow_export.json",
    )
    assert imported["imported_run_count"] == 1

    vscode = bridge_cli.init_vscode_bridge(tmp_path / "workspace", force=True)
    assert any(path.endswith(".vscode/tasks.json") for path in vscode["files"])
    assert (tmp_path / "workspace" / "AGILAB_QUICKSTART.md").is_file()

    airflow = bridge_cli.export_airflow_dag(
        manifest_path,
        tmp_path / "airflow" / "agilab_dag.py",
        dag_id="agilab_demo",
    )
    assert airflow["dag_id"] == "agilab_demo"
    assert "BashOperator" in (tmp_path / "airflow" / "agilab_dag.py").read_text(
        encoding="utf-8"
    )

    dagster = bridge_cli.export_dagster_job(
        manifest_path,
        tmp_path / "dagster" / "agilab_job.py",
        job_name="agilab_demo_job",
    )
    assert dagster["job_name"] == "agilab_demo_job"
    assert "@job" in (tmp_path / "dagster" / "agilab_job.py").read_text(
        encoding="utf-8"
    )


def test_duckdb_bridge_plan_and_optional_execution(tmp_path: Path) -> None:
    query = tmp_path / "query.sql"
    query.write_text("select 3 as total", encoding="utf-8")
    params = tmp_path / "params.json"
    params.write_text('{"threshold": 2}', encoding="utf-8")

    planned = bridge_cli.run_duckdb_query(
        query, tmp_path / "duckdb-plan", plan_only=True
    )
    assert planned["status"] == "planned"
    assert (tmp_path / "duckdb-plan" / "duckdb_manifest.json").is_file()

    class FakeConnection:
        description = [("total",)]
        calls: list[tuple[str, object]] = []

        def execute(self, query, params=None):
            self.calls.append((query, params))
            return self

        def fetchall(self):
            return [(3,)]

    fake_connection = FakeConnection()
    fake_duckdb = SimpleNamespace(connect=lambda database: fake_connection)
    executed = bridge_cli.run_duckdb_query(
        query,
        tmp_path / "duckdb-run",
        params_path=params,
        duckdb_module=fake_duckdb,
    )

    assert executed["status"] == "pass"
    assert executed["columns"] == ["total"]
    assert fake_connection.calls[-1] == ("select 3 as total", {"threshold": 2})
    assert json.loads(
        (tmp_path / "duckdb-run" / "result.json").read_text(encoding="utf-8")
    )["rows"] == [{"total": 3}]

    with pytest.raises(ValueError, match="Unsafe SQL identifier"):
        bridge_cli.run_duckdb_query(
            query,
            tmp_path / "duckdb-unsafe",
            input_path=tmp_path / "data.csv",
            table_name="input;drop",
            plan_only=True,
        )


def test_mcp_tools_and_jsonrpc(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path)
    apps_root = tmp_path / "apps"
    (apps_root / "alpha_project").mkdir(parents=True)

    assert (
        manifest_tools.list_projects(apps_root)["projects"][0]["name"]
        == "alpha_project"
    )
    assert manifest_tools.list_runs(tmp_path)["runs"]
    assert manifest_tools.summarize_run(manifest_path)["summary"]["status"] == "pass"
    assert (
        manifest_tools.list_artifacts(manifest_path)["artifacts"][0]["exists"] is True
    )
    assert (
        manifest_tools.export_quarto_report(manifest_path, tmp_path / "mcp.qmd")[
            "status"
        ]
        == "pass"
    )

    other_manifest = _write_manifest(tmp_path, status="fail", duration=2.0)
    comparison = manifest_tools.compare_runs(manifest_path, other_manifest)
    assert comparison["status_changed"] is True
    assert comparison["duration_delta_seconds"] == 0.75

    tools_response = mcp_server.handle_jsonrpc(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )
    assert tools_response and tools_response["result"]["tools"]

    call_response = mcp_server.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "summarize_run",
                "arguments": {"manifest_path": str(manifest_path)},
            },
        }
    )
    assert call_response and call_response["result"]["content"][0]["type"] == "text"
    assert mcp_server.server_manifest()["policy"]["read_only"] is True


def test_lab_run_routes_bridge_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    from agilab import lab_run

    calls: list[list[str]] = []
    monkeypatch.setattr(lab_run, "_run_bridge", lambda argv: calls.append(argv) or 0)

    assert lab_run.main(["export", "quarto", "--help"]) == 0
    assert calls == [["export", "quarto", "--help"]]


def test_tool_wrappers_forward_sys_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    quarto_tool = importlib.import_module("tools.agilab_quarto_export")
    hf_tool = importlib.import_module("tools.agilab_hf_space_export")
    calls: list[list[str]] = []

    monkeypatch.setattr(bridge_cli, "main", lambda argv: calls.append(list(argv)) or 0)
    monkeypatch.setattr(sys, "argv", ["tool", "--help"])

    assert quarto_tool.main() == 0
    assert hf_tool.main(["--project", "demo", "--output", "hf"]) == 0
    assert calls == [
        ["export", "quarto", "--help"],
        ["export", "hf-space", "--project", "demo", "--output", "hf"],
    ]
