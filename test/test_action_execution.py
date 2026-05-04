from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
package_root = str(SRC_ROOT / "agilab")
pkg = sys.modules.get("agilab")
if pkg is not None and hasattr(pkg, "__path__"):
    package_path = list(pkg.__path__)
    if package_root not in package_path:
        pkg.__path__ = [package_root, *package_path]
importlib.invalidate_caches()

action_execution = importlib.import_module("agilab.action_execution")


class _FakeStreamlit:
    def __init__(self):
        self.messages: list[tuple[str, str]] = []
        self.spinner_messages: list[str] = []

    @contextmanager
    def spinner(self, message: str):
        self.spinner_messages.append(message)
        yield

    def success(self, message: str):
        self.messages.append(("success", message))

    def warning(self, message: str):
        self.messages.append(("warning", message))

    def error(self, message: str):
        self.messages.append(("error", message))

    def info(self, message: str):
        self.messages.append(("info", message))


def test_run_streamlit_action_renders_success_and_calls_callback():
    fake_st = _FakeStreamlit()
    callbacks: list[str] = []

    result = action_execution.run_streamlit_action(
        fake_st,
        action_execution.ActionSpec(name="Demo", start_message="Working..."),
        lambda: action_execution.ActionResult.success(
            "Created.",
            detail="Details",
            next_action="Open it",
            data={"name": "demo"},
        ),
        on_success=lambda action_result: callbacks.append(action_result.data["name"]),
    )

    assert result.status == "success"
    assert fake_st.spinner_messages == ["Working..."]
    assert fake_st.messages == [
        ("success", "Created."),
        ("info", "Details"),
        ("info", "Next: Open it"),
    ]
    assert callbacks == ["demo"]


def test_run_streamlit_action_converts_exceptions_to_action_errors():
    fake_st = _FakeStreamlit()
    callbacks: list[str] = []

    def _raise():
        raise RuntimeError("boom")

    result = action_execution.run_streamlit_action(
        fake_st,
        action_execution.ActionSpec(
            name="Demo",
            start_message="Working...",
            failure_title="Demo failed.",
            failure_next_action="Retry later.",
        ),
        _raise,
        on_success=lambda action_result: callbacks.append(action_result.title),
    )

    assert result.status == "error"
    assert result.title == "Demo failed."
    assert fake_st.messages == [
        ("error", "Demo failed."),
        ("info", "boom"),
        ("info", "Next: Retry later."),
    ]
    assert callbacks == []


def test_render_action_result_supports_warning_outcomes():
    fake_st = _FakeStreamlit()

    action_execution.render_action_result(
        fake_st,
        action_execution.ActionResult.warning(
            "Already exists.",
            next_action="Pick another name.",
        ),
    )

    assert fake_st.messages == [
        ("warning", "Already exists."),
        ("info", "Next: Pick another name."),
    ]
