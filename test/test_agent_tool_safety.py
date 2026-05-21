from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SECRET_MODULE_PATH = ROOT / "src" / "agilab" / "secret_uri.py"
MODULE_PATH = ROOT / "src" / "agilab" / "agent_tool_safety.py"


def _load_secret_module() -> object:
    spec = importlib.util.spec_from_file_location("agilab.secret_uri", SECRET_MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_module():
    previous_package = sys.modules.get("agilab")
    previous_secret = sys.modules.get("agilab.secret_uri")
    sys.modules.pop("agilab.agent_tool_safety", None)
    package = types.ModuleType("agilab")
    package.__path__ = [str(ROOT / "src" / "agilab")]  # type: ignore[attr-defined]
    package.__file__ = str(ROOT / "src" / "agilab" / "__init__.py")
    package.__package__ = "agilab"
    sys.modules["agilab"] = package
    _load_secret_module()
    spec = importlib.util.spec_from_file_location("agilab.agent_tool_safety", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        if previous_secret is None:
            sys.modules.pop("agilab.secret_uri", None)
        else:
            sys.modules["agilab.secret_uri"] = previous_secret
        if previous_package is None:
            sys.modules.pop("agilab", None)
        else:
            sys.modules["agilab"] = previous_package
    return module


def test_safe_agent_tool_invocation_is_allowed_without_confirmation() -> None:
    module = _load_module()
    decision = module.evaluate_tool_invocation("inspect_project", {"project": "flight_telemetry_project"})

    assert decision.allowed is True
    assert decision.risk == "safe"
    assert decision.confirmation_token is None


def test_metadata_can_mark_tool_invocation_as_destructive() -> None:
    module = _load_module()

    explicit = module.evaluate_tool_invocation("archive_project", metadata={"destructive": True})
    by_kind = module.evaluate_tool_invocation("archive_project", metadata={"kind": "destructive"})

    assert explicit.allowed is False
    assert explicit.risk == "destructive"
    assert explicit.confirmation_token == module.confirmation_token("archive_project")
    assert by_kind.allowed is False
    assert by_kind.risk == "destructive"


def test_destructive_agent_tool_invocation_requires_stable_confirmation() -> None:
    module = _load_module()
    args = {"path": "/tmp/output"}
    decision = module.evaluate_tool_invocation("delete_output", args)
    expected = module.confirmation_token("delete_output", args)

    assert decision.allowed is False
    assert decision.risk == "destructive"
    assert decision.confirmation_token == expected

    confirmed = module.evaluate_tool_invocation("delete_output", args, confirmation=expected)
    assert confirmed.allowed is True
    assert confirmed.reason == "destructive action confirmed by operator token"


def test_permission_tiers_classify_and_gate_agent_actions() -> None:
    module = _load_module()

    readonly = module.evaluate_tool_permission("inspect_project", level="readonly")
    safe_denied = module.evaluate_tool_permission("write_report", level="readonly")
    standard_denied = module.evaluate_tool_permission("run_tests", level="safe")
    operator_denied = module.evaluate_tool_permission("delete_output", {"path": "/tmp/out"}, level="standard")
    token = module.confirmation_token("delete_output", {"path": "/tmp/out"})
    operator_allowed = module.evaluate_tool_permission(
        "delete_output",
        {"path": "/tmp/out"},
        level="standard",
        confirmation=token,
    )

    assert readonly.allowed is True
    assert readonly.tier == "readonly"
    assert safe_denied.allowed is False
    assert safe_denied.tier == "safe"
    assert standard_denied.allowed is False
    assert standard_denied.tier == "standard"
    assert operator_denied.allowed is False
    assert operator_denied.tier == "operator"
    assert operator_denied.confirmation_token == token
    assert operator_allowed.allowed is True
    assert operator_allowed.reason == "operator action confirmed by explicit token"
    assert module.normalize_permission_level("yolo") == "operator"


def test_permission_tiers_honor_explicit_metadata() -> None:
    module = _load_module()

    decision = module.evaluate_tool_permission(
        "archive_project",
        level="safe",
        metadata={"permission_tier": "standard"},
    )

    assert decision.allowed is False
    assert decision.tier == "standard"
    assert module.classify_tool_permission("summarize_context") == "safe"
    assert module.classify_tool_permission("archive_project", {"permission_level": "yolo"}) == "operator"


def test_tool_hook_set_can_skip_and_rewrite_tool_results() -> None:
    module = _load_module()
    hooks = module.ToolHookSet()
    calls: list[str] = []

    @hooks.before_tool
    def before(ctx):
        calls.append(f"before:{ctx.action}")
        if ctx.action == "blocked":
            return module.ToolHookResult(output="blocked", status="denied", is_error=True)
        return None

    @hooks.after_tool
    def after(ctx, result):
        calls.append(f"after:{ctx.action}:{result.status}")
        if result.status == "pass":
            return module.ToolHookResult(
                output=f"{result.output} audited",
                status=result.status,
                metadata={"audited": True},
            )
        return None

    def runner(ctx):
        calls.append(f"run:{ctx.action}")
        return module.ToolHookResult(output="ok")

    allowed = hooks.execute(module.ToolHookContext("inspect", {}, {}, run_id="run"), runner)
    blocked = hooks.execute(module.ToolHookContext("blocked", {}, {}, run_id="run"), runner)

    assert allowed.output == "ok audited"
    assert allowed.metadata == {"audited": True}
    assert blocked.output == "blocked"
    assert blocked.is_error is True
    assert calls == [
        "before:inspect",
        "run:inspect",
        "after:inspect:pass",
        "before:blocked",
        "after:blocked:denied",
    ]


def test_require_tool_invocation_allowed_raises_for_unconfirmed_destructive_action() -> None:
    module = _load_module()
    with pytest.raises(module.ToolConfirmationRequired, match="requires explicit operator confirmation"):
        module.require_tool_invocation_allowed("reset_cluster", {"scheduler": "127.0.0.1"})


def test_require_tool_invocation_allowed_returns_confirmed_decision() -> None:
    module = _load_module()
    args = {"path": "/tmp/output"}
    token = module.confirmation_token("delete_output", args)

    decision = module.require_tool_invocation_allowed("delete_output", args, confirmation=token)

    assert decision.allowed is True
    assert decision.confirmation_token == token


def test_progress_recorder_writes_append_only_redacted_ndjson(tmp_path) -> None:
    module = _load_module()
    log_path = tmp_path / "progress.ndjson"
    recorder = module.ProgressRecorder(log_path, run_id="agent-run")

    event = recorder.emit(
        "tool_start",
        message="Using OPENAI_API_KEY=sk-real-secret and env://OPENAI_API_KEY",
        metadata={
            "OPENAI_API_KEY": "sk-real-secret",
            "config": {"token_ref": "env://OPENAI_API_KEY"},
            "safe": "visible",
        },
    )
    recorder.emit("tool_end", status="pass", message="done")

    raw = log_path.read_text(encoding="utf-8")
    rows = [json.loads(line) for line in raw.splitlines()]
    loaded = module.load_progress_events(log_path)

    assert event.schema == "agilab.agent_tool_safety.v1"
    assert len(rows) == 2
    assert loaded == rows
    assert rows[0]["message"] == "Using OPENAI_API_KEY=<redacted> and <secret-ref>"
    assert rows[0]["metadata"]["OPENAI_API_KEY"] == "<redacted>"
    assert rows[0]["metadata"]["config"]["token_ref"] == "<redacted>"
    assert rows[0]["metadata"]["safe"] == "visible"
    assert "sk-real-secret" not in raw
    assert "env://OPENAI_API_KEY" not in raw


def test_load_progress_events_returns_empty_list_for_missing_path(tmp_path) -> None:
    module = _load_module()

    assert module.load_progress_events(tmp_path / "missing.ndjson") == []
