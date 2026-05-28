from __future__ import annotations

import importlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agilab import agent_run, bridge_cli, run_manifest
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


def test_quarto_render_runner_and_empty_manifest_edges(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["artifacts"] = []
    payload["validations"] = []
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    calls: list[list[str]] = []

    def fake_runner(argv, **_kwargs):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 7, stdout="ok", stderr="render failed")

    report = bridge_cli.export_quarto_report(
        manifest_path,
        tmp_path / "rendered.qmd",
        render=True,
        runner=fake_runner,
        which=lambda _name: "/usr/bin/quarto",
    )

    assert calls == [["quarto", "render", str(tmp_path / "rendered.qmd")]]
    assert report["render"]["status"] == "fail"
    text = (tmp_path / "rendered.qmd").read_text(encoding="utf-8")
    assert "No validation rows recorded" in text
    assert "No artifacts recorded" in text


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


def test_hf_space_export_edges_and_secret_scan(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        bridge_cli.export_hf_space(tmp_path / "missing-project", tmp_path / "hf")

    project = tmp_path / "project"
    project.mkdir()
    (project / "README.md").write_text("# Project\n", encoding="utf-8")
    (project / "binary.env").write_bytes(b"\xff\xfe")
    (project / "notes.txt").write_text("secret://vault/path\n", encoding="utf-8")
    findings = bridge_cli._secret_findings(project)
    assert findings == [{"path": str(project / "notes.txt"), "reason": "secret reference URI"}]
    (project / "notes.txt").write_text("OPENAI_API_KEY=example\n", encoding="utf-8")

    output = tmp_path / "hf-existing"
    output.mkdir()
    (output / "old.txt").write_text("old\n", encoding="utf-8")
    with pytest.raises(FileExistsError):
        bridge_cli.export_hf_space(project, output)

    evidence_file = tmp_path / "evidence.txt"
    evidence_file.write_text("evidence\n", encoding="utf-8")
    payload = bridge_cli.export_hf_space(project, output, evidence_path=evidence_file, force=True)
    assert payload["status"] == "pass"
    assert (output / "evidence" / "evidence.txt").is_file()


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


def _write_minimal_notebook(path: Path, source: str = "print('hello')") -> Path:
    path.write_text(
        json.dumps(
            {
                "cells": [
                    {
                        "cell_type": "code",
                        "execution_count": None,
                        "metadata": {},
                        "outputs": [],
                        "source": source,
                    }
                ],
                "metadata": {
                    "kernelspec": {
                        "display_name": "Python 3",
                        "language": "python",
                        "name": "python3",
                    }
                },
                "nbformat": 4,
                "nbformat_minor": 5,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_notebook_sandbox_evidence_runner(tmp_path: Path) -> None:
    secret = "sk-notebook-secret-0000000000"
    notebook = _write_minimal_notebook(tmp_path / "demo.ipynb")
    params = tmp_path / "params.json"
    params.write_text(
        json.dumps({"threshold": 3, "OPENAI_API_KEY": secret}),
        encoding="utf-8",
    )

    def fake_executor(
        prepared,
        executed,
        _work_dir,
        artifact_dir,
        payload,
        timeout_seconds,
        kernel_name,
        allow_errors,
    ):
        assert payload["threshold"] == 3
        assert timeout_seconds == 5
        assert kernel_name == "python3"
        assert allow_errors is True
        prepared_payload = json.loads(prepared.read_text(encoding="utf-8"))
        assert prepared_payload["cells"][0]["metadata"]["tags"] == ["agilab-parameters"]
        assert prepared_payload["cells"][0]["id"].startswith("agilab-cell-")
        assert prepared_payload["cells"][1]["id"].startswith("agilab-cell-")
        assert "AGILAB_PARAMS" in prepared_payload["cells"][0]["source"]
        (artifact_dir / "result.txt").write_text("done", encoding="utf-8")
        prepared_payload["cells"].append(
            {
                "cell_type": "code",
                "execution_count": 2,
                "metadata": {},
                "outputs": [
                    {
                        "output_type": "stream",
                        "name": "stdout",
                        "text": f"ok OPENAI_API_KEY={secret}\n",
                    },
                    {
                        "output_type": "stream",
                        "name": "stderr",
                        "text": "warning\n",
                    },
                ],
                "source": "print('ok')",
            }
        )
        executed.write_text(json.dumps(prepared_payload), encoding="utf-8")
        return {"status": "pass", "stdout": f"runner {secret}\n"}

    payload = bridge_cli.run_notebook_sandbox(
        notebook,
        tmp_path / "notebook-run",
        params_path=params,
        timeout_seconds=5,
        kernel_name="python3",
        allow_errors=True,
        executor=fake_executor,
    )

    assert payload["status"] == "pass"
    assert payload["schema"] == "agilab.bridge.notebook_sandbox.v1"
    assert payload["params"]["OPENAI_API_KEY"] == "<redacted>"
    assert payload["artifacts"][0]["relative_path"] == "result.txt"
    assert secret not in Path(payload["stdout_log"]).read_text(encoding="utf-8")
    assert secret not in Path(payload["stderr_log"]).read_text(encoding="utf-8")
    assert secret not in Path(payload["executed_notebook_path"]).read_text(
        encoding="utf-8"
    )
    assert secret not in (
        tmp_path / "notebook-run" / "notebook_sandbox_evidence.json"
    ).read_text(encoding="utf-8")
    manifest = run_manifest.load_run_manifest(
        tmp_path / "notebook-run" / "run_manifest.json"
    )
    assert manifest.path_id == "notebook-sandbox"
    assert manifest.status == "pass"
    assert any(artifact.name == "executed-notebook" for artifact in manifest.artifacts)


def test_notebook_sandbox_failure_is_evidence(tmp_path: Path) -> None:
    secret = "sk-notebook-secret-0000000000"
    notebook = _write_minimal_notebook(
        tmp_path / "demo.ipynb",
        source=f"OPENAI_API_KEY='{secret}'\nraise RuntimeError('boom')",
    )

    def failing_executor(*_args):
        raise RuntimeError(f"OPENAI_API_KEY={secret} failed")

    payload = bridge_cli.run_notebook_sandbox(
        notebook,
        tmp_path / "notebook-fail",
        executor=failing_executor,
    )

    assert payload["status"] == "fail"
    assert secret not in payload["execution"]["error"]
    assert "<redacted>" in payload["execution"]["error"]
    assert secret not in Path(payload["stderr_log"]).read_text(encoding="utf-8")
    assert secret not in Path(payload["prepared_notebook_path"]).read_text(
        encoding="utf-8"
    )
    assert secret not in Path(payload["executed_notebook_path"]).read_text(
        encoding="utf-8"
    )
    manifest = run_manifest.load_run_manifest(
        tmp_path / "notebook-fail" / "run_manifest.json"
    )
    assert manifest.status == "fail"
    assert manifest.validations[0].status == "fail"


def test_notebook_sandbox_missing_params_is_evidence(tmp_path: Path) -> None:
    notebook = _write_minimal_notebook(tmp_path / "demo.ipynb")

    payload = bridge_cli.run_notebook_sandbox(
        notebook,
        tmp_path / "notebook-missing-params",
        params_path=tmp_path / "missing.json",
    )

    assert payload["status"] == "fail"
    assert "FileNotFoundError" in payload["execution"]["error"]
    assert Path(payload["stderr_log"]).is_file()
    manifest = run_manifest.load_run_manifest(
        tmp_path / "notebook-missing-params" / "run_manifest.json"
    )
    assert manifest.status == "fail"


def test_notebook_bridge_helper_edges(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert bridge_cli._text_from_notebook_value(["a", 1, None]) == "a1None"
    assert bridge_cli._extract_notebook_streams(tmp_path / "missing.ipynb") == {
        "stdout": "",
        "stderr": "",
    }
    invalid = tmp_path / "invalid.ipynb"
    invalid.write_text("{bad json", encoding="utf-8")
    assert bridge_cli._extract_notebook_streams(invalid) == {"stdout": "", "stderr": ""}

    executed = tmp_path / "executed.ipynb"
    executed.write_text(
        json.dumps(
            {
                "cells": [
                    "not-a-cell",
                    {"outputs": "not-a-list"},
                    {
                        "outputs": [
                            "not-a-mapping",
                            {"output_type": "stream", "name": "stdout", "text": ["hello", "\n"]},
                            {"output_type": "stream", "name": "stderr", "text": "warn\n"},
                            {"output_type": "error", "traceback": ["line1", "line2"]},
                            {"output_type": "error", "evalue": "boom"},
                        ]
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    streams = bridge_cli._extract_notebook_streams(executed)
    assert streams["stdout"] == "hello\n"
    assert "line1\nline2" in streams["stderr"]
    assert "boom" in streams["stderr"]

    artifact_dir = tmp_path / "artifacts"
    assert bridge_cli._notebook_artifact_rows(artifact_dir) == []
    artifact_dir.mkdir()
    (artifact_dir / "subdir").mkdir()
    (artifact_dir / "result.txt").write_text("done", encoding="utf-8")
    assert bridge_cli._notebook_artifact_rows(artifact_dir)[0]["relative_path"] == "result.txt"

    secret = "sk-redact-me-000000000"
    redaction_target = tmp_path / "redact.ipynb"
    redaction_target.write_text(
        json.dumps(
            {
                "cells": [
                    "skip",
                    {
                        "source": f"OPENAI_API_KEY={secret}",
                        "outputs": [
                            {
                                "text": f"{secret}\n",
                                "evalue": secret,
                                "traceback": [secret],
                                "data": {"text/plain": secret},
                            },
                            "skip",
                        ],
                    },
                    {"outputs": "skip"},
                ]
            }
        ),
        encoding="utf-8",
    )
    bridge_cli._redact_notebook_text_fields(redaction_target)
    assert secret not in redaction_target.read_text(encoding="utf-8")

    fake_nbformat = ModuleType("nbformat")
    fake_nbformat.read = lambda path, as_version: {"path": str(path), "as_version": as_version}
    writes: list[tuple[object, Path]] = []
    fake_nbformat.write = lambda notebook, path: writes.append((notebook, path))

    class FakeNotebookClient:
        def __init__(self, notebook, **kwargs):
            self.notebook = notebook
            self.kwargs = kwargs

        def execute(self):
            self.notebook["executed"] = True

    fake_nbclient = ModuleType("nbclient")
    fake_nbclient.NotebookClient = FakeNotebookClient
    monkeypatch.setitem(sys.modules, "nbformat", fake_nbformat)
    monkeypatch.setitem(sys.modules, "nbclient", fake_nbclient)

    status = bridge_cli._execute_notebook_with_nbclient(
        tmp_path / "prepared.ipynb",
        tmp_path / "executed-out.ipynb",
        tmp_path,
        artifact_dir,
        {},
        9,
        "python3",
        True,
    )
    assert status == {"status": "pass"}
    assert writes and writes[0][0]["executed"] is True


def test_notebook_sandbox_cli_route(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(notebook, output, **kwargs):
        calls.append({"notebook": notebook, "output": output, **kwargs})
        return {"schema": "agilab.bridge.notebook_sandbox.v1", "status": "pass"}

    monkeypatch.setattr(bridge_cli, "run_notebook_sandbox", fake_run)

    rc = bridge_cli.main(
        [
            "run",
            "notebook",
            "--notebook",
            "demo.ipynb",
            "--params",
            "params.json",
            "--output",
            "out",
            "--timeout",
            "5",
            "--kernel-name",
            "python3",
            "--allow-errors",
            "--json",
        ]
    )

    assert rc == 0
    assert json.loads(capsys.readouterr().out)["schema"] == (
        "agilab.bridge.notebook_sandbox.v1"
    )
    assert calls == [
        {
            "notebook": Path("demo.ipynb"),
            "output": Path("out"),
            "params_path": Path("params.json"),
            "timeout_seconds": 5,
            "kernel_name": "python3",
            "allow_errors": True,
        }
    ]


def test_mcp_tools_and_jsonrpc(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path)
    apps_root = tmp_path / "apps"
    (apps_root / "alpha_project").mkdir(parents=True)
    agent_root = tmp_path / "agents"
    agent_dir = agent_root / "codex-run"
    agent_run.trace_agent_run(
        [sys.executable, "-c", "print('agent ok')"],
        agent="codex",
        label="Review current diff",
        cwd=ROOT,
        output_dir=agent_dir,
        run_id="agent-codex",
        permission_level="standard",
        tags=("review",),
        metadata={"branch": "main"},
        protocol_adapters=("mcp",),
        capabilities=("evidence-review",),
    )

    assert (
        manifest_tools.list_projects(apps_root)["projects"][0]["name"]
        == "alpha_project"
    )
    assert manifest_tools.list_runs(tmp_path)["runs"]
    agent_runs = manifest_tools.list_agent_runs(
        agent_root,
        agent="codex",
        tag="review",
        metadata={"branch": "main"},
        protocol_adapter="mcp",
        capability="evidence-review",
    )["runs"]
    assert agent_runs[0]["run_id"] == "agent-codex"
    assert agent_runs[0]["tags"] == ["review"]
    assert agent_runs[0]["metadata"] == {"branch": "main"}
    assert (
        manifest_tools.summarize_agent_run(agent_dir)["summary"]["status"]
        == "pass"
    )
    read_agent_payload = manifest_tools.read_agent_run(agent_dir)
    assert read_agent_payload["manifest"]["kind"] == agent_run.TRACE_KIND
    assert "agent ok" not in json.dumps(read_agent_payload)
    handoff_payload = manifest_tools.agent_handoff(agent_dir)
    assert handoff_payload["handoff"]["run"]["run_id"] == "agent-codex"
    assert "agent ok" not in json.dumps(handoff_payload)
    next_payload = manifest_tools.agent_next_actions(agent_dir)
    assert next_payload["next_actions"]["run"]["run_id"] == "agent-codex"
    assert next_payload["next_actions"]["next_actions"][0]["priority"] == "P1"
    assert "agent ok" not in json.dumps(next_payload)
    context_payload = manifest_tools.agent_context(
        agent_root,
        agent="codex",
        tag="review",
        metadata={"branch": "main"},
        protocol_adapter="mcp",
        capability="evidence-review",
    )
    assert context_payload["context"]["match_count"] == 1
    assert context_payload["context"]["latest"]["handoff"]["run"]["run_id"] == "agent-codex"
    assert "agent ok" not in json.dumps(context_payload)
    lineage_payload = manifest_tools.agent_lineage(agent_root, run_id="agent-codex")
    assert lineage_payload["lineage"]["found"] is True
    assert lineage_payload["lineage"]["target"]["run_id"] == "agent-codex"
    agent_comparison = manifest_tools.compare_agent_runs(agent_dir, agent_dir)
    assert agent_comparison["comparison"]["status_changed"] is False
    assert agent_comparison["comparison"]["left"]["run_id"] == "agent-codex"
    agent_validation = manifest_tools.validate_agent_run(agent_dir)
    assert agent_validation["validation"]["ok"] is True
    assert "agent ok" not in json.dumps(agent_validation)
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
    agent_call_response = mcp_server.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "list_agent_runs",
                "arguments": {
                    "log_root": str(agent_root),
                    "agent": "codex",
                    "tag": "review",
                    "metadata": {"branch": "main"},
                },
            },
        }
    )
    assert agent_call_response
    assert (
        "agent-codex"
        in agent_call_response["result"]["content"][0]["text"]
    )
    handoff_call_response = mcp_server.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "agent_handoff",
                "arguments": {"manifest_path": str(agent_dir)},
            },
        }
    )
    assert handoff_call_response
    assert (
        "Continue from AGILAB agent-run evidence"
        in handoff_call_response["result"]["content"][0]["text"]
    )
    next_call_response = mcp_server.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "agent_next_actions",
                "arguments": {"manifest_path": str(agent_dir)},
            },
        }
    )
    assert next_call_response
    assert (
        "agilab.agent_next_actions.v1"
        in next_call_response["result"]["content"][0]["text"]
    )
    context_call_response = mcp_server.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {
                "name": "agent_context",
                "arguments": {
                    "log_root": str(agent_root),
                    "agent": "codex",
                    "tag": "review",
                },
            },
        }
    )
    assert context_call_response
    assert (
        "agilab.agent_context.v1"
        in context_call_response["result"]["content"][0]["text"]
    )
    lineage_call_response = mcp_server.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "agent_lineage",
                "arguments": {
                    "log_root": str(agent_root),
                    "run_id": "agent-codex",
                },
            },
        }
    )
    assert lineage_call_response
    assert (
        "agilab.agent_lineage.v1"
        in lineage_call_response["result"]["content"][0]["text"]
    )
    compare_agent_call_response = mcp_server.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {
                "name": "compare_agent_runs",
                "arguments": {
                    "left_manifest": str(agent_dir),
                    "right_manifest": str(agent_dir),
                },
            },
        }
    )
    assert compare_agent_call_response
    assert (
        "agilab.agent_compare.v1"
        in compare_agent_call_response["result"]["content"][0]["text"]
    )
    validate_agent_call_response = mcp_server.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {
                "name": "validate_agent_run",
                "arguments": {"manifest_path": str(agent_dir)},
            },
        }
    )
    assert validate_agent_call_response
    assert (
        "agilab.agent_run_validation.v1"
        in validate_agent_call_response["result"]["content"][0]["text"]
    )
    assert mcp_server.server_manifest()["policy"]["read_only"] is True


def test_lab_run_routes_bridge_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    from agilab import lab_run

    calls: list[list[str]] = []
    monkeypatch.setattr(lab_run, "_run_bridge", lambda argv: calls.append(argv) or 0)

    assert lab_run.main(["export", "quarto", "--help"]) == 0
    assert lab_run.main(["run", "notebook", "--help"]) == 0
    assert calls == [
        ["export", "quarto", "--help"],
        ["run", "notebook", "--help"],
    ]


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


def test_mcp_stdio_reports_parse_errors_without_crashing():
    import io
    import json

    from agilab_mcp.server import serve_stdio

    stdout = io.StringIO()
    assert serve_stdio(stdin=io.StringIO("{bad json}\n"), stdout=stdout) == 0
    response = json.loads(stdout.getvalue())
    assert response["id"] is None
    assert response["error"]["code"] == -32700


def test_mcp_jsonrpc_notifications_are_silent():
    from agilab_mcp.server import handle_jsonrpc

    assert handle_jsonrpc(
        {"jsonrpc": "2.0", "method": "unsupported/notification"}
    ) is None
