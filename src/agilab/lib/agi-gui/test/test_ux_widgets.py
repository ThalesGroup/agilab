from __future__ import annotations

from contextlib import contextmanager

from agi_gui import ux_widgets


class _State(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


class _FakeStreamlit:
    def __init__(self, *, buttons=None):
        self.session_state = _State()
        self.buttons = buttons or {}
        self.events: list[tuple[str, str]] = []

    def button(self, label, key=None, **_kwargs):
        self.events.append(("button", str(key or label)))
        return bool(self.buttons.get(key or label, False))

    def info(self, message):
        self.events.append(("info", str(message)))

    def success(self, message):
        self.events.append(("success", str(message)))

    def warning(self, message):
        self.events.append(("warning", str(message)))

    def error(self, message):
        self.events.append(("error", str(message)))

    def rerun(self):
        self.events.append(("rerun", "called"))


def test_toast_uses_native_streamlit_toast_when_available() -> None:
    calls = []

    class NativeToast(_FakeStreamlit):
        def toast(self, message, icon=None):
            calls.append((message, icon))

    fake = NativeToast()

    ux_widgets.toast(fake, "saved", icon="ok", state="success")

    assert calls == [("saved", "ok")]
    assert fake.events == []


def test_toast_falls_back_to_message_method() -> None:
    fake = _FakeStreamlit()

    ux_widgets.toast(fake, "saved", state="success")

    assert fake.events == [("success", "saved")]


def test_status_container_uses_native_status_when_available() -> None:
    calls = []

    class NativeStatus(_FakeStreamlit):
        @contextmanager
        def status(self, label, state="running", expanded=True):
            calls.append(("status", label, state, expanded))
            yield self

        def update(self, *, label=None, state=None, expanded=None):
            calls.append(("update", label, state, expanded))

    fake = NativeStatus()

    with ux_widgets.status_container(fake, "Running", state="running") as status:
        status.update(label="Done", state="complete", expanded=False)

    assert calls == [
        ("status", "Running", "running", True),
        ("update", "Done", "complete", False),
    ]


def test_status_container_falls_back_to_messages() -> None:
    fake = _FakeStreamlit()

    with ux_widgets.status_container(fake, "Running", state="running") as status:
        status.update(label="Done", state="complete", expanded=False)

    assert fake.events == [("info", "Running"), ("success", "Done")]


def test_confirm_button_fallback_requires_second_confirm_click() -> None:
    fake = _FakeStreamlit(buttons={"clean": True})

    assert ux_widgets.confirm_button(fake, "Clean", key="clean", message="Delete?") is False
    assert fake.session_state["clean__armed"] is True

    fake.buttons = {"clean__confirm": True}
    assert ux_widgets.confirm_button(fake, "Clean", key="clean", message="Delete?") is True
    assert "clean__armed" not in fake.session_state


def test_confirm_button_fallback_cancel_clears_armed_state() -> None:
    fake = _FakeStreamlit(buttons={"clean__cancel": True})
    fake.session_state["clean__armed"] = True

    assert ux_widgets.confirm_button(fake, "Clean", key="clean", message="Delete?") is False

    assert "clean__armed" not in fake.session_state
    assert ("rerun", "called") in fake.events
