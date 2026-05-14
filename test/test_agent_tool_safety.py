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


def test_require_tool_invocation_allowed_raises_for_unconfirmed_destructive_action() -> None:
    module = _load_module()
    with pytest.raises(module.ToolConfirmationRequired, match="requires explicit operator confirmation"):
        module.require_tool_invocation_allowed("reset_cluster", {"scheduler": "127.0.0.1"})


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
