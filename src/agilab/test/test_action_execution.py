from __future__ import annotations

from pathlib import Path
import sys

import pytest


SRC_ROOT = Path(__file__).resolve().parents[2]
SRC_PACKAGE = SRC_ROOT / "agilab"
sys.path.insert(0, str(SRC_ROOT))

import agilab as _agilab_package

if str(SRC_PACKAGE) not in _agilab_package.__path__:
    _agilab_package.__path__.insert(0, str(SRC_PACKAGE))

from agilab.action_execution import (
    ActionResult,
    ActionSpec,
    render_action_result,
    run_streamlit_action,
)


class _FakeSpinner:
    def __init__(self, streamlit: "_FakeStreamlit", message: str) -> None:
        self._streamlit = streamlit
        self._message = message

    def __enter__(self) -> None:
        self._streamlit.events.append(("spinner.enter", self._message))

    def __exit__(self, exc_type, exc, traceback) -> None:
        self._streamlit.events.append(("spinner.exit", self._message))


class _FakeStreamlit:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def spinner(self, message: str) -> _FakeSpinner:
        return _FakeSpinner(self, message)

    def success(self, message: str) -> None:
        self.events.append(("success", message))

    def warning(self, message: str) -> None:
        self.events.append(("warning", message))

    def error(self, message: str) -> None:
        self.events.append(("error", message))

    def info(self, message: str) -> None:
        self.events.append(("info", message))


@pytest.mark.parametrize(
    ("factory_name", "expected_status"),
    [
        ("success", "success"),
        ("warning", "warning"),
        ("error", "error"),
        ("info", "info"),
    ],
)
def test_action_result_factories_normalize_optional_data(factory_name, expected_status) -> None:
    factory = getattr(ActionResult, factory_name)

    result = factory(
        "Action title",
        detail="detail text",
        next_action="retry later",
        data={"job": "demo"},
    )

    assert result.status == expected_status
    assert result.title == "Action title"
    assert result.detail == "detail text"
    assert result.next_action == "retry later"
    assert result.data == {"job": "demo"}
    assert factory("Minimal").data == {}


def test_render_action_result_emits_status_detail_and_next_action() -> None:
    streamlit = _FakeStreamlit()

    render_action_result(
        streamlit,
        ActionResult.warning(
            "Partial result",
            detail="Worker skipped optional step.",
            next_action="Inspect logs",
        ),
    )

    assert streamlit.events == [
        ("warning", "Partial result"),
        ("info", "Worker skipped optional step."),
        ("info", "Next: Inspect logs"),
    ]


def test_run_streamlit_action_calls_success_callback_after_rendering() -> None:
    streamlit = _FakeStreamlit()
    successes: list[ActionResult] = []

    result = run_streamlit_action(
        streamlit,
        ActionSpec(name="Install", start_message="Installing app..."),
        lambda: ActionResult.success("Installed", data={"app": "flight_telemetry_project"}),
        on_success=successes.append,
    )

    assert result.status == "success"
    assert result.data == {"app": "flight_telemetry_project"}
    assert successes == [result]
    assert streamlit.events == [
        ("spinner.enter", "Installing app..."),
        ("spinner.exit", "Installing app..."),
        ("success", "Installed"),
    ]


def test_run_streamlit_action_turns_exceptions_into_action_errors() -> None:
    streamlit = _FakeStreamlit()
    successes: list[ActionResult] = []

    def failing_action() -> ActionResult:
        raise ValueError("invalid worker configuration")

    result = run_streamlit_action(
        streamlit,
        ActionSpec(
            name="Install",
            start_message="Installing app...",
            failure_title="Cluster installation failed.",
            failure_next_action="Fix the worker environment and retry.",
        ),
        failing_action,
        on_success=successes.append,
    )

    assert result == ActionResult.error(
        "Cluster installation failed.",
        detail="invalid worker configuration",
        next_action="Fix the worker environment and retry.",
    )
    assert successes == []
    assert streamlit.events == [
        ("spinner.enter", "Installing app..."),
        ("spinner.exit", "Installing app..."),
        ("error", "Cluster installation failed."),
        ("info", "invalid worker configuration"),
        ("info", "Next: Fix the worker environment and retry."),
    ]
