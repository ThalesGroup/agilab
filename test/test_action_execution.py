from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest


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


def test_action_result_factories_normalize_optional_data():
    for factory_name in ("success", "warning", "error", "info"):
        factory = getattr(action_execution.ActionResult, factory_name)

        result = factory(
            "Action title",
            detail="detail text",
            next_action="retry later",
            data={"job": "demo"},
        )

        assert result.status == factory_name
        assert result.title == "Action title"
        assert result.detail == "detail text"
        assert result.next_action == "retry later"
        assert result.data == {"job": "demo"}
        assert factory("Minimal").data == {}


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


class _FakeStatus:
    def __init__(self, label, *, expanded):
        self.label = label
        self.expanded = expanded
        self.state = "running"
        self.phases = []

    def __enter__(self):
        return self

    def __exit__(self, *exception):
        return False

    def update(self, **kwargs):
        for name, value in kwargs.items():
            setattr(self, name, value)

    def write(self, message):
        self.phases.append(message)


class _FakeProgressStreamlit(_FakeStreamlit):
    def __init__(self):
        super().__init__()
        self.status_blocks = []

    def status(self, label, *, expanded):
        block = _FakeStatus(label, expanded=expanded)
        self.status_blocks.append(block)
        return block


def test_progress_action_publishes_start_and_phases_before_returning():
    ui = _FakeProgressStreamlit()
    callbacks = []

    def export(report):
        block = ui.status_blocks[0]
        assert block.state == "running" and block.label == "Preparing export..."
        report("Checking project files")
        assert block.label == "Checking project files"
        assert block.phases == ["Checking project files"]
        report("Writing archive")
        return action_execution.ActionResult.success("Archive ready", next_action="Download the archive.")

    result = action_execution.run_streamlit_action(
        ui,
        action_execution.ActionSpec(name="Export project", start_message="Preparing export..."),
        action_with_progress=export,
        on_success=lambda result: callbacks.append(result.title),
    )

    block = ui.status_blocks[0]
    assert block.state == "complete" and block.label == "Export project"
    assert block.expanded is False
    assert block.phases == ["Checking project files", "Writing archive"]
    assert result.status == "success" and callbacks == ["Archive ready"]
    assert ui.messages == [("success", "Archive ready"), ("info", "Next: Download the archive.")]
    assert not ui.spinner_messages


def test_progress_action_failure_finishes_status_and_skips_success_callback():
    ui = _FakeProgressStreamlit()
    callbacks = []

    def import_archive(report):
        report("Checking archive")
        raise OSError("Permission denied when reading the archive")

    result = action_execution.run_streamlit_action(
        ui,
        action_execution.ActionSpec(
            name="Import project", start_message="Preparing import...",
            failure_title="Project import failed.", failure_next_action="Check archive permissions.",
        ),
        action_with_progress=import_archive,
        on_success=callbacks.append,
    )

    assert result.status == "error" and not callbacks
    block = ui.status_blocks[0]
    assert block.state == "error" and block.expanded is True
    assert block.phases == ["Checking archive"]
    assert ("error", "Project import failed.") in ui.messages
    assert ("info", "Next: Check archive permissions.") in ui.messages


def test_progress_action_warning_preserves_terminal_guidance_without_success_callback():
    ui = _FakeProgressStreamlit()
    callbacks = []
    result = action_execution.run_streamlit_action(
        ui,
        action_execution.ActionSpec(name="Import project", start_message="Preparing import..."),
        action_with_progress=lambda report: action_execution.ActionResult.warning(
            "Existing project preserved", next_action="Choose another project name.",
        ),
        on_success=callbacks.append,
    )
    assert result.status == "warning" and not callbacks
    assert ui.status_blocks[0].state == "complete"
    assert ("warning", "Existing project preserved") in ui.messages
    assert ("info", "Next: Choose another project name.") in ui.messages


@pytest.mark.parametrize("with_legacy_action,with_progress_action", [(False, False), (True, True)])
def test_action_requires_exactly_one_execution_callable(with_legacy_action, with_progress_action):
    ui = _FakeProgressStreamlit()
    legacy = (lambda: action_execution.ActionResult.success("done")) if with_legacy_action else None
    phased = (lambda report: action_execution.ActionResult.success("done")) if with_progress_action else None
    with pytest.raises(ValueError, match="exactly one"):
        action_execution.run_streamlit_action(
            ui, action_execution.ActionSpec(name="Export project", start_message="Starting..."),
            legacy, action_with_progress=phased,
        )
    assert not ui.status_blocks and not ui.spinner_messages and not ui.messages


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


def test_run_streamlit_action_classifies_archive_exceptions():
    fake_st = _FakeStreamlit()

    def _raise():
        raise RuntimeError("Failed to extract '/tmp/dataset.7z': not a 7z file")

    result = action_execution.run_streamlit_action(
        fake_st,
        action_execution.ActionSpec(
            name="Import project",
            start_message="Importing...",
            failure_title="Project import failed.",
        ),
        _raise,
    )

    assert result.status == "error"
    assert result.title == "Project import failed."
    assert result.detail == (
        "dataset.7z could not be extracted. The archive is missing, truncated, "
        "or not a valid .7z dataset archive."
    )
    assert result.next_action is not None
    assert result.data == {"failure_category": "archive"}
    assert fake_st.messages[0] == ("error", "Project import failed.")
    assert "not a 7z file" not in str(fake_st.messages)


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


def test_render_action_result_supports_info_without_optional_messages():
    fake_st = _FakeStreamlit()

    result = action_execution.ActionResult.info("Nothing to do.")

    action_execution.render_action_result(fake_st, result)

    assert result.status == "info"
    assert result.data == {}
    assert fake_st.messages == [("info", "Nothing to do.")]
