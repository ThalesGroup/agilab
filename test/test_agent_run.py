from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path


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
    assert stdout_path.read_text(encoding="utf-8").strip() == "ok"
    assert stderr_path.read_text(encoding="utf-8").strip() == "warn"
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["run_id"] == "agent-success"


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
    )

    def timeout_runner(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=["aider"], timeout=1, output="partial", stderr="slow")

    result = module.run_agent_command(config, runner=timeout_runner, perf_counter=iter([1.0, 3.0]).__next__)

    assert result.returncode == 124
    assert result.manifest["status"] == "timeout"
    assert result.manifest["timing"]["duration_seconds"] == 2.0
    assert "Timed out after 1s" in (tmp_path / "stderr.txt").read_text(encoding="utf-8")
