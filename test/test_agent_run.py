from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "agilab" / "agent_run.py"


def _load_module():
    previous_package = sys.modules.get("agilab")
    sys.modules.pop("agilab.agent_run", None)
    package = types.ModuleType("agilab")
    package.__path__ = [str(ROOT / "src" / "agilab")]  # type: ignore[attr-defined]
    package.__file__ = str(ROOT / "src" / "agilab" / "__init__.py")
    package.__package__ = "agilab"
    sys.modules["agilab"] = package
    spec = importlib.util.spec_from_file_location("agilab.agent_run", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        if previous_package is None:
            sys.modules.pop("agilab", None)
        else:
            sys.modules["agilab"] = previous_package
    return module


def test_agent_run_print_only_json_is_redacted(tmp_path: Path, capsys) -> None:
    module = _load_module()

    exit_code = module.main(
        [
            "--agent",
            "codex",
            "--label",
            "Review current diff",
            "--run-id",
            "agent-test",
            "--output-dir",
            str(tmp_path),
            "--env",
            "OPENAI_API_KEY=sk-secret",
            "--protocol-adapter",
            "AG-UI",
            "--protocol-adapter",
            "ag ui",
            "--capability",
            "app as tool",
            "--json",
            "--print-only",
            "--",
            "codex",
            "review",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["kind"] == module.TRACE_KIND
    assert payload["status"] == "planned"
    assert payload["agent"] == "codex"
    assert payload["command"]["argv"] == ["codex", "<1 argument(s) redacted>"]
    assert payload["command"]["argv_redacted"] is True
    assert payload["command"]["argv_count"] == 2
    assert len(payload["command"]["argv_sha256"]) == 64
    assert payload["command"]["env_overrides"]["keys"] == ["OPENAI_API_KEY"]
    assert payload["command"]["env_overrides"]["value_redacted"]["OPENAI_API_KEY"] is True
    assert payload["command"]["env_overrides"]["secret_like"]["OPENAI_API_KEY"] is True
    assert payload["protocols"]["adapters"] == ["ag-ui"]
    assert payload["protocols"]["capabilities"] == ["app-as-tool"]
    assert payload["protocols"]["mode"] == "metadata-only"
    assert payload["permission"]["allowed"] is False
    assert payload["permission"]["tier"] == "standard"
    assert payload["permission"]["level"] == "safe"
    assert payload["events"][0]["type"] == "agent.run.planned"
    assert payload["events"][0]["protocol_adapters"] == ["ag-ui"]
    assert payload["events"][0]["capabilities"] == ["app-as-tool"]
    assert payload["artifacts"]["agent_trace"]["events"] == str(tmp_path / "agent_events.ndjson")
    assert payload["artifacts"]["agent_trace"]["exists"] is False
    assert "sk-secret" not in json.dumps(payload)
    assert "review" not in json.dumps(payload)


def test_agent_run_can_include_full_command_args_when_requested(tmp_path: Path, capsys) -> None:
    module = _load_module()

    exit_code = module.main(
        [
            "--agent",
            "codex",
            "--run-id",
            "agent-full-argv",
            "--output-dir",
            str(tmp_path),
            "--include-command-args",
            "--json",
            "--print-only",
            "--",
            "codex",
            "review",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"]["argv"] == ["codex", "review"]
    assert payload["command"]["argv_redacted"] is False


def test_agent_run_manifest_context_supports_tags_and_metadata(tmp_path: Path, capsys) -> None:
    module = _load_module()

    exit_code = module.main(
        [
            "--agent",
            "codex",
            "--run-id",
            "agent-context",
            "--output-dir",
            str(tmp_path),
            "--tag",
            "review",
            "--tag",
            "Review",
            "--tag",
            "release candidate",
            "--metadata",
            "issue=123",
            "--metadata",
            "note=using env://OPENAI_API_KEY",
            "--metadata",
            "OPENAI_API_KEY=sk-secret",
            "--json",
            "--print-only",
            "--",
            "codex",
            "review",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["context"]["tags"] == ["review", "release-candidate"]
    assert payload["context"]["metadata"]["issue"] == "123"
    assert payload["context"]["metadata"]["note"] == "using <secret-ref>"
    assert payload["context"]["metadata"]["OPENAI_API_KEY"] == "<redacted>"
    assert payload["context"]["metadata_redacted"]["issue"] is False
    assert payload["context"]["metadata_redacted"]["note"] is True
    assert payload["context"]["metadata_redacted"]["OPENAI_API_KEY"] is True
    assert "sk-secret" not in json.dumps(payload)
    assert "env://OPENAI_API_KEY" not in json.dumps(payload)


def test_agent_run_public_python_api_uses_cli_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    monkeypatch.setenv("AGILAB_LOG_ABS", str(tmp_path / "logs"))
    monkeypatch.setenv("AGILAB_AGENT_HOME", str(tmp_path / "agent-home"))

    config = module.create_agent_run_config(
        [sys.executable, "-c", "print('api')"],
        agent="Codex Agent",
        label="Python API smoke",
        cwd=ROOT,
        run_id="api run",
        env_overrides={"OPENAI_API_KEY": "sk-secret"},
        tags=("review", "Review", "api smoke"),
        metadata={"branch": "main", "token": "hidden"},
        protocol_adapters=("mcp", "MCP"),
        capabilities=("evidence review",),
    )

    assert config.run_id == "api-run"
    assert config.output_dir == tmp_path / "logs" / "agents" / "Codex-Agent" / "api-run"
    assert config.cwd == ROOT
    assert config.tags == ("review", "api-smoke")
    assert config.metadata == {"branch": "main", "token": "hidden"}
    assert config.protocol_adapters == ("mcp",)
    assert config.capabilities == ("evidence-review",)
    assert config.permission_level == "safe"
    assert config.trace_enabled is True
    assert config.provider == ""
    assert config.model == ""


def test_trace_agent_run_public_python_api_executes_and_redacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    monkeypatch.setenv("AGILAB_AGENT_HOME", str(tmp_path / "agent-home"))

    result = module.trace_agent_run(
        [sys.executable, "-c", "print('api ok')"],
        agent="codex",
        label="Python API trace",
        cwd=ROOT,
        output_dir=tmp_path,
        run_id="api-trace",
        env_overrides={"OPENAI_API_KEY": "sk-secret"},
        metadata={"note": "using env://OPENAI_API_KEY"},
        tags=("api",),
        protocol_adapters=("mcp",),
        capabilities=("agent-as-tool",),
        permission_level="standard",
    )

    assert result.returncode == 0
    assert result.manifest["status"] == "pass"
    assert result.manifest["run_id"] == "api-trace"
    assert result.manifest["command"]["argv"] == [sys.executable, "<2 argument(s) redacted>"]
    assert result.manifest["command"]["env_overrides"]["keys"] == ["OPENAI_API_KEY"]
    assert result.manifest["context"]["metadata"]["note"] == "using <secret-ref>"
    assert result.manifest["protocols"]["adapters"] == ["mcp"]
    assert result.manifest["protocols"]["capabilities"] == ["agent-as-tool"]
    assert [event["type"] for event in result.manifest["events"]] == [
        "agent.run.started",
        "agent.command.completed",
        "agent.artifacts.written",
    ]
    assert "sk-secret" not in json.dumps(result.manifest)
    assert (tmp_path / module.STDOUT_FILENAME).read_text(encoding="utf-8").strip() == "api ok"
    summary = module.summarize_agent_run(tmp_path)
    assert summary.run_id == "api-trace"
    assert summary.tags == ("api",)
    assert summary.trace_events_path == tmp_path / "agent_events.ndjson"
    events = (tmp_path / "agent_events.ndjson").read_text(encoding="utf-8")
    assert "session_start" in events
    assert "command_done" in events
    assert "sk-secret" not in events


def test_agent_run_stamps_provider_config_and_permission_level(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    agent_home = tmp_path / "agent-home"
    agent_home.mkdir()
    monkeypatch.setenv("AGILAB_AGENT_HOME", str(agent_home))
    (agent_home / "agents.json").write_text(
        json.dumps(
            {
                "default": {"provider": "local-code"},
                "permission": {"level": "standard"},
                "providers": {
                    "local-code": {
                        "type": "ollama",
                        "model": "qwen2.5-coder:latest",
                        "capability": {"context_window": 32768},
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    payload = module.build_planned_manifest(
        module.create_agent_run_config(
            [sys.executable, "-c", "print('ok')"],
            cwd=ROOT,
            output_dir=tmp_path / "run",
            run_id="configured",
        )
    )

    assert payload["context"]["agent_config"]["permission_level"] == "standard"
    assert payload["context"]["agent_config"]["config_paths"] == [str(agent_home / "agents.json")]
    assert payload["context"]["provider"]["provider"] == "ollama"
    assert payload["context"]["provider"]["model"] == "qwen2.5-coder:latest"
    assert payload["context"]["provider"]["capability"]["context_window"] == 32768
    assert payload["permission"]["allowed"] is True
    assert payload["permission"]["level"] == "standard"


def test_agent_run_executes_command_and_writes_local_artifacts(tmp_path: Path, capsys) -> None:
    module = _load_module()

    exit_code = module.main(
        [
            "--agent",
            "codex",
            "--label",
            "Tiny smoke",
            "--run-id",
            "agent-success",
            "--output-dir",
            str(tmp_path),
            "--permission-level",
            "standard",
            "--json",
            "--",
            sys.executable,
            "-c",
            "import sys; print('ok'); print('warn', file=sys.stderr)",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    manifest_path = tmp_path / "agent_run_manifest.json"
    stdout_path = tmp_path / "stdout.txt"
    stderr_path = tmp_path / "stderr.txt"
    assert payload["status"] == "pass"
    assert payload["returncode"] == 0
    assert payload["artifacts"]["manifest"] == str(manifest_path)
    assert payload["artifacts"]["stdout"]["line_count"] == 1
    assert payload["artifacts"]["stderr"]["line_count"] == 1
    assert payload["protocols"]["mode"] == "none"
    assert [event["type"] for event in payload["events"]] == [
        "agent.run.started",
        "agent.command.completed",
        "agent.artifacts.written",
    ]
    assert payload["events"][1]["returncode"] == 0
    assert payload["permission"]["allowed"] is True
    assert payload["artifacts"]["agent_trace"]["event_count"] == 6
    assert payload["artifacts"]["agent_trace"]["event_types"] == [
        "session_start",
        "command_start",
        "permission_request",
        "permission_resolved",
        "command_done",
        "session_end",
    ]
    assert stdout_path.read_text(encoding="utf-8").strip() == "ok"
    assert stderr_path.read_text(encoding="utf-8").strip() == "warn"
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["run_id"] == "agent-success"
    assert "command finished with returncode 0" in (tmp_path / "agent_events.ndjson").read_text(encoding="utf-8")


def test_agent_run_denies_execution_below_permission_level(tmp_path: Path, capsys) -> None:
    module = _load_module()

    exit_code = module.main(
        [
            "--agent",
            "codex",
            "--run-id",
            "agent-denied",
            "--output-dir",
            str(tmp_path),
            "--json",
            "--",
            sys.executable,
            "-c",
            "print('should not run')",
        ]
    )

    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 126
    assert payload["status"] == "denied"
    assert payload["permission"]["allowed"] is False
    assert payload["permission"]["tier"] == "standard"
    assert payload["permission"]["level"] == "safe"
    assert [event["type"] for event in payload["events"]] == [
        "agent.run.started",
        "agent.permission.denied",
        "agent.artifacts.written",
    ]
    assert (tmp_path / "stdout.txt").read_text(encoding="utf-8") == ""
    assert "standard action exceeds safe permission level" in (tmp_path / "stderr.txt").read_text(encoding="utf-8")


def test_agent_run_operator_gates_destructive_command_content(tmp_path: Path, capsys) -> None:
    module = _load_module()

    exit_code = module.main(
        [
            "--agent",
            "codex",
            "--run-id",
            "agent-destructive-shell",
            "--output-dir",
            str(tmp_path),
            "--permission-level",
            "standard",
            "--json",
            "--",
            "bash",
            "-c",
            "rm -rf /tmp/agilab-agent-run-test",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    stderr = (tmp_path / "stderr.txt").read_text(encoding="utf-8")

    assert exit_code == 126
    assert payload["status"] == "denied"
    assert payload["permission"]["allowed"] is False
    assert payload["permission"]["tier"] == "operator"
    assert payload["permission"]["level"] == "standard"
    assert payload["permission"]["command_policy"] == "operator-gated"
    assert payload["permission"]["confirmation_token"]
    assert "operator action exceeds standard permission level" in stderr
    assert "confirmation_token=" in stderr
    assert (tmp_path / "stdout.txt").read_text(encoding="utf-8") == ""

    git_config = module.create_agent_run_config(
        ["git", "reset", "--hard"],
        cwd=ROOT,
        output_dir=tmp_path / "git-reset",
        permission_level="standard",
    )
    planned = module.build_planned_manifest(git_config)
    assert planned["permission"]["tier"] == "operator"
    assert planned["permission"]["command_policy"] == "operator-gated"


def test_agent_run_redacts_output_artifacts_by_default(tmp_path: Path, capsys) -> None:
    module = _load_module()

    exit_code = module.main(
        [
            "--agent",
            "codex",
            "--run-id",
            "agent-redacted-output",
            "--output-dir",
            str(tmp_path),
            "--permission-level",
            "standard",
            "--json",
            "--",
            sys.executable,
            "-c",
            "print('OPENAI_API_KEY=sk-secret'); print('Bearer sk-proj-abcdefghijklmnopqrstuvwxyz1234567890')",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    raw_manifest = json.dumps(payload)
    stdout = (tmp_path / "stdout.txt").read_text(encoding="utf-8")

    assert exit_code == 0
    assert payload["status"] == "pass"
    assert "OPENAI_API_KEY=<redacted>" in stdout
    assert "Bearer <redacted>" in stdout
    assert "sk-secret" not in stdout
    assert "sk-proj-" not in stdout
    assert "sk-secret" not in raw_manifest


def test_agent_run_read_side_helpers_and_list_command(tmp_path: Path, capsys) -> None:
    module = _load_module()
    run_root = tmp_path / "runs"
    codex_dir = run_root / "codex-run"
    aider_dir = run_root / "aider-run"

    assert module.main(
        [
            "--agent",
            "codex",
            "--label",
            "Codex run",
            "--run-id",
            "agent-codex",
            "--output-dir",
            str(codex_dir),
            "--tag",
            "review",
            "--metadata",
            "branch=main",
            "--protocol-adapter",
            "mcp",
            "--capability",
            "evidence review",
            "--permission-level",
            "standard",
            "--",
            sys.executable,
            "-c",
            "print('ok')",
        ]
    ) == 0
    assert module.main(
        [
            "--agent",
            "aider",
            "--label",
            "Aider run",
            "--run-id",
            "agent-aider",
            "--output-dir",
            str(aider_dir),
            "--allow-failure",
            "--permission-level",
            "standard",
            "--",
            sys.executable,
            "-c",
            "raise SystemExit(4)",
        ]
    ) == 0
    capsys.readouterr()

    manifest = module.load_agent_run_manifest(codex_dir)
    summary = module.summarize_agent_run(manifest)

    assert summary.run_id == "agent-codex"
    assert summary.agent == "codex"
    assert summary.status == "pass"
    assert summary.returncode == 0
    assert summary.manifest_path == codex_dir / module.MANIFEST_FILENAME
    assert summary.stdout_path == codex_dir / module.STDOUT_FILENAME
    assert summary.stderr_path == codex_dir / module.STDERR_FILENAME
    assert summary.trace_events_path == codex_dir / "agent_events.ndjson"
    assert summary.tags == ("review",)
    assert summary.metadata == {"branch": "main"}

    assert [path.parent.name for path in module.find_agent_run_manifests(run_root, status="fail")] == ["aider-run"]
    assert [item.run_id for item in module.list_agent_runs(run_root, agent="codex")] == ["agent-codex"]
    assert [
        item.run_id
        for item in module.list_agent_runs(
            run_root,
            tags=("review",),
            metadata={"branch": "main"},
            protocol_adapters=("MCP",),
            capabilities=("evidence review",),
        )
    ] == ["agent-codex"]
    assert module.list_agent_runs(run_root, metadata={"branch": "other"}) == []

    assert module.main(
        [
            "list",
            "--root",
            str(run_root),
            "--agent",
            "codex",
            "--tag",
            "review",
            "--metadata",
            "branch=main",
            "--protocol-adapter",
            "mcp",
            "--capability",
            "evidence-review",
            "--json",
        ]
    ) == 0
    listed = json.loads(capsys.readouterr().out)
    assert [item["run_id"] for item in listed] == ["agent-codex"]
    assert listed[0]["metadata"] == {"branch": "main"}
    assert listed[0]["trace_events"] == str(codex_dir / "agent_events.ndjson")


def test_agent_run_failure_returns_command_status_and_manifest(tmp_path: Path, capsys) -> None:
    module = _load_module()

    exit_code = module.main(
        [
            "--agent",
            "opencode",
            "--run-id",
            "agent-fail",
            "--output-dir",
            str(tmp_path),
            "--permission-level",
            "standard",
            "--json",
            "--",
            sys.executable,
            "-c",
            "import sys; print('bad', file=sys.stderr); raise SystemExit(7)",
        ]
    )

    assert exit_code == 7
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "fail"
    assert payload["returncode"] == 7
    assert (tmp_path / "stderr.txt").read_text(encoding="utf-8").strip() == "bad"


def test_agent_run_handoff_card_does_not_embed_output(tmp_path: Path, capsys) -> None:
    module = _load_module()

    assert module.main(
        [
            "--agent",
            "codex",
            "--label",
            "Handoff smoke",
            "--run-id",
            "agent-handoff",
            "--output-dir",
            str(tmp_path),
            "--tag",
            "review",
            "--metadata",
            "branch=main",
            "--protocol-adapter",
            "mcp",
            "--capability",
            "evidence-review",
            "--permission-level",
            "standard",
            "--",
            sys.executable,
            "-c",
            "print('private output should stay in stdout artifact')",
        ]
    ) == 0
    capsys.readouterr()

    payload = module.agent_handoff_payload(tmp_path)
    assert payload["schema"] == "agilab.agent_handoff.v1"
    assert payload["run"]["run_id"] == "agent-handoff"
    assert payload["run"]["tags"] == ["review"]
    assert payload["protocols"]["adapters"] == ["mcp"]
    assert payload["protocols"]["capabilities"] == ["evidence-review"]
    assert payload["trace"]["event_count"] == 6
    assert "private output" not in json.dumps(payload)
    assert "Continue from AGILAB agent-run evidence" in payload["handoff"]["continue_prompt"]

    assert module.main(["handoff", str(tmp_path), "--json"]) == 0
    cli_payload = json.loads(capsys.readouterr().out)
    assert cli_payload["run"]["run_id"] == "agent-handoff"
    assert "private output" not in json.dumps(cli_payload)

    assert module.main(["handoff", str(tmp_path)]) == 0
    markdown = capsys.readouterr().out
    assert "# AGILAB agent handoff" in markdown
    assert "agent-handoff" in markdown
    assert "private output" not in markdown


def test_agent_run_next_actions_are_status_aware(tmp_path: Path, capsys) -> None:
    module = _load_module()
    fail_dir = tmp_path / "fail"
    denied_dir = tmp_path / "denied"

    assert module.main(
        [
            "--agent",
            "codex",
            "--label",
            "Failing smoke",
            "--run-id",
            "agent-fail-next",
            "--output-dir",
            str(fail_dir),
            "--tag",
            "debug",
            "--metadata",
            "branch=main",
            "--allow-failure",
            "--permission-level",
            "standard",
            "--",
            sys.executable,
            "-c",
            "raise SystemExit(7)",
        ]
    ) == 0
    assert module.main(
        [
            "--agent",
            "codex",
            "--label",
            "Denied smoke",
            "--run-id",
            "agent-denied-next",
            "--output-dir",
            str(denied_dir),
            "--",
            sys.executable,
            "-c",
            "print('should not run')",
        ]
    ) == 126
    capsys.readouterr()

    fail_payload = module.agent_next_actions_payload(fail_dir)
    assert fail_payload["schema"] == "agilab.agent_next_actions.v1"
    assert fail_payload["run"]["status"] == "fail"
    assert fail_payload["followup_context"]["metadata"]["followup_of"] == "agent-fail-next"
    assert fail_payload["next_actions"][0]["priority"] == "P0"
    assert "stderr" in fail_payload["next_actions"][0]["action"]

    denied_payload = module.agent_next_actions_payload(denied_dir)
    assert denied_payload["run"]["status"] == "denied"
    assert denied_payload["permission"]["allowed"] is False
    assert "permission" in denied_payload["next_actions"][0]["action"]

    assert module.main(["next", str(fail_dir), "--json"]) == 0
    cli_payload = json.loads(capsys.readouterr().out)
    assert cli_payload["run"]["run_id"] == "agent-fail-next"

    assert module.main(["next-actions", str(denied_dir)]) == 0
    markdown = capsys.readouterr().out
    assert "# AGILAB agent next actions" in markdown
    assert "agent-denied-next" in markdown


def test_agent_run_context_pack_summarizes_matching_runs(tmp_path: Path, capsys) -> None:
    module = _load_module()
    run_root = tmp_path / "runs"
    first_dir = run_root / "first"
    second_dir = run_root / "second"

    assert module.main(
        [
            "--agent",
            "codex",
            "--label",
            "First pass",
            "--run-id",
            "agent-context-pass",
            "--output-dir",
            str(first_dir),
            "--tag",
            "review",
            "--metadata",
            "branch=main",
            "--protocol-adapter",
            "mcp",
            "--capability",
            "evidence-review",
            "--permission-level",
            "standard",
            "--",
            sys.executable,
            "-c",
            "print('context private output')",
        ]
    ) == 0
    assert module.main(
        [
            "--agent",
            "codex",
            "--label",
            "Second fail",
            "--run-id",
            "agent-context-fail",
            "--output-dir",
            str(second_dir),
            "--tag",
            "review",
            "--metadata",
            "branch=main",
            "--protocol-adapter",
            "mcp",
            "--capability",
            "evidence-review",
            "--allow-failure",
            "--permission-level",
            "standard",
            "--",
            sys.executable,
            "-c",
            "raise SystemExit(3)",
        ]
    ) == 0
    capsys.readouterr()

    payload = module.agent_context_payload(
        run_root,
        agent="codex",
        tags=("review",),
        metadata={"branch": "main"},
        protocol_adapters=("mcp",),
        capabilities=("evidence-review",),
    )
    assert payload["schema"] == "agilab.agent_context.v1"
    assert payload["match_count"] == 2
    assert payload["status_counts"] == {"fail": 1, "pass": 1}
    assert [item["run_id"] for item in payload["runs"]] == [
        "agent-context-fail",
        "agent-context-pass",
    ]
    assert payload["latest"]["handoff"]["run"]["run_id"] == "agent-context-fail"
    assert payload["latest"]["next_actions"]["run"]["status"] == "fail"
    assert "context private output" not in json.dumps(payload)

    assert module.main(
        [
            "context",
            "--root",
            str(run_root),
            "--agent",
            "codex",
            "--tag",
            "review",
            "--metadata",
            "branch=main",
            "--protocol-adapter",
            "mcp",
            "--capability",
            "evidence-review",
            "--json",
        ]
    ) == 0
    cli_payload = json.loads(capsys.readouterr().out)
    assert cli_payload["match_count"] == 2
    assert "context private output" not in json.dumps(cli_payload)

    assert module.main(["context", "--root", str(run_root)]) == 0
    markdown = capsys.readouterr().out
    assert "# AGILAB agent context pack" in markdown
    assert "agent-context-fail" in markdown


def test_agent_run_lineage_links_followups(tmp_path: Path, capsys) -> None:
    module = _load_module()
    run_root = tmp_path / "lineage"
    root_dir = run_root / "root"
    child_dir = run_root / "child"
    grandchild_dir = run_root / "grandchild"

    assert module.main(
        [
            "--agent",
            "codex",
            "--label",
            "Root review",
            "--run-id",
            "agent-root",
            "--output-dir",
            str(root_dir),
            "--tag",
            "review",
            "--permission-level",
            "standard",
            "--",
            sys.executable,
            "-c",
            "print('lineage private root output')",
        ]
    ) == 0
    assert module.main(
        [
            "--agent",
            "codex",
            "--label",
            "Child fix",
            "--run-id",
            "agent-child",
            "--output-dir",
            str(child_dir),
            "--metadata",
            "followup_of=agent-root",
            "--permission-level",
            "standard",
            "--",
            sys.executable,
            "-c",
            "print('child')",
        ]
    ) == 0
    assert module.main(
        [
            "--agent",
            "codex",
            "--label",
            "Grandchild verify",
            "--run-id",
            "agent-grandchild",
            "--output-dir",
            str(grandchild_dir),
            "--metadata",
            "followup_of=agent-child",
            "--permission-level",
            "standard",
            "--",
            sys.executable,
            "-c",
            "print('grandchild')",
        ]
    ) == 0
    capsys.readouterr()

    root_payload = module.agent_lineage_payload(run_root, run_id="agent-root")
    assert root_payload["schema"] == "agilab.agent_lineage.v1"
    assert root_payload["found"] is True
    assert [item["run_id"] for item in root_payload["descendants"]] == [
        "agent-child",
        "agent-grandchild",
    ]
    assert [item["run_id"] for item in root_payload["chain"]] == [
        "agent-root",
        "agent-child",
        "agent-grandchild",
    ]
    assert {"from": "agent-root", "to": "agent-child"} in root_payload["edges"]
    assert "lineage private root output" not in json.dumps(root_payload)

    grandchild_payload = module.agent_lineage_payload(run_root, run_id="agent-grandchild")
    assert [item["run_id"] for item in grandchild_payload["ancestors"]] == [
        "agent-root",
        "agent-child",
    ]
    assert [item["run_id"] for item in grandchild_payload["chain"]] == [
        "agent-root",
        "agent-child",
        "agent-grandchild",
    ]

    assert module.main(["lineage", "agent-grandchild", "--root", str(run_root), "--json"]) == 0
    cli_payload = json.loads(capsys.readouterr().out)
    assert cli_payload["target"]["run_id"] == "agent-grandchild"

    assert module.main(["lineage", "agent-root", "--root", str(run_root)]) == 0
    markdown = capsys.readouterr().out
    assert "# AGILAB agent lineage" in markdown
    assert "agent-root -> agent-child" in markdown


def test_agent_run_timeout_records_timeout_status(tmp_path: Path) -> None:
    module = _load_module()
    config = module.AgentRunConfig(
        agent="aider",
        label="timeout",
        command=("aider", "--version"),
        cwd=ROOT,
        output_dir=tmp_path,
        run_id="agent-timeout",
        timeout_seconds=1.0,
        permission_level="standard",
    )

    def timeout_runner(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=["aider"], timeout=1, output="partial", stderr="slow")

    result = module.run_agent_command(config, runner=timeout_runner, perf_counter=iter([1.0, 3.0]).__next__)

    assert result.returncode == 124
    assert result.manifest["status"] == "timeout"
    assert result.manifest["timing"]["duration_seconds"] == 2.0
    assert [event["type"] for event in result.manifest["events"]] == [
        "agent.run.started",
        "agent.command.timeout",
        "agent.artifacts.written",
    ]
    assert result.manifest["events"][1]["returncode"] == 124
    assert "Timed out after 1s" in (tmp_path / "stderr.txt").read_text(encoding="utf-8")


def test_agent_run_defaults_and_helper_error_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    monkeypatch.setenv("AGILAB_LOG_ABS", str(tmp_path / "logs"))

    run_id = module._new_run_id("Codex Agent")
    assert run_id.startswith("agent-Codex-Agent-")
    assert module._default_log_root() == tmp_path / "logs"
    assert module._default_output_dir("Codex Agent", "run-1") == tmp_path / "logs" / "agents" / "Codex-Agent" / "run-1"

    repo_root = tmp_path / "repo"
    (repo_root / "src" / "agilab").mkdir(parents=True)
    (repo_root / "pyproject.toml").write_text("[project]\nname='agilab'\n", encoding="utf-8")
    assert module._detect_repo_root(repo_root / "src" / "agilab") == repo_root
    assert module._detect_repo_root(tmp_path / "outside") is None

    with pytest.raises(ValueError, match="expected KEY=VALUE"):
        module._parse_env_overrides(["BROKEN"])
    with pytest.raises(ValueError, match="KEY cannot be empty"):
        module._parse_env_overrides([" =value"])
    with pytest.raises(ValueError, match="command cannot be empty"):
        module.create_agent_run_config([], cwd=ROOT)
    with pytest.raises(ValueError, match="argv sequence"):
        module.create_agent_run_config("codex review", cwd=ROOT)
    with pytest.raises(ValueError, match="timeout_seconds must be > 0"):
        module.create_agent_run_config([sys.executable], cwd=ROOT, timeout_seconds=0)
    with pytest.raises(ValueError, match="cwd is not a directory"):
        module.create_agent_run_config([sys.executable], cwd=tmp_path / "missing")

    missing_payload = module._file_payload(tmp_path / "missing.txt")
    assert missing_payload == {
        "path": str(tmp_path / "missing.txt"),
        "exists": False,
        "size_bytes": 0,
        "line_count": 0,
    }


def test_agent_run_parser_validation_errors(tmp_path: Path) -> None:
    module = _load_module()

    with pytest.raises(SystemExit):
        module.parse_args(["--"])
    with pytest.raises(SystemExit):
        module.parse_args(["--timeout", "0", "--", sys.executable])
    with pytest.raises(SystemExit):
        module.parse_args(["--cwd", str(tmp_path / "missing"), "--", sys.executable])


def test_agent_run_human_rendering_and_allow_failure(tmp_path: Path, capsys) -> None:
    module = _load_module()

    without_manifest = module.render_human(
        {"agent": "codex", "run_id": "agent-human", "status": "planned", "artifacts": "not-a-dict"}
    )
    assert "status: planned" in without_manifest
    assert "manifest:" not in without_manifest

    exit_code = module.main(
        [
            "--agent",
            "codex",
            "--run-id",
            "agent-allowed-fail",
            "--output-dir",
            str(tmp_path),
            "--allow-failure",
            "--permission-level",
            "standard",
            "--",
            sys.executable,
            "-c",
            "raise SystemExit(3)",
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "status: fail" in output
    assert f"manifest: {tmp_path / 'agent_run_manifest.json'}" in output
