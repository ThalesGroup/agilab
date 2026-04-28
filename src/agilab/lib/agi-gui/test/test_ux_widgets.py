from __future__ import annotations

import builtins
from contextlib import contextmanager
import sys
from types import SimpleNamespace

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


def test_session_state_handles_streamlit_like_object_when_native_import_fails() -> None:
    class StreamlitLike:
        __module__ = "streamlit.delta_generator"

        def __setattr__(self, name, value):
            if name == "session_state":
                raise TypeError(name)
            super().__setattr__(name, value)

    original_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "streamlit":
            raise RuntimeError("streamlit unavailable")
        return original_import(name, globals, locals, fromlist, level)

    builtins.__import__ = _fake_import
    try:
        assert ux_widgets._session_state(StreamlitLike()) == {}
    finally:
        builtins.__import__ = original_import


def test_state_pop_attribute_fallback_returns_default_for_missing_key() -> None:
    assert ux_widgets._state_pop(SimpleNamespace(), "missing", "fallback") == "fallback"


def test_toast_uses_native_streamlit_toast_when_available() -> None:
    calls = []

    class NativeToast(_FakeStreamlit):
        def toast(self, message, icon=None):
            calls.append((message, icon))

    fake = NativeToast()

    ux_widgets.toast(fake, "saved", icon="ok", state="success")

    assert calls == [("saved", "ok")]
    assert fake.events == []


def test_toast_retries_legacy_native_toast_signature() -> None:
    calls = []

    class LegacyToast(_FakeStreamlit):
        def toast(self, message, **kwargs):
            if kwargs:
                raise TypeError("legacy signature")
            calls.append(message)

    fake = LegacyToast()

    ux_widgets.toast(fake, "saved", icon="ok", state="success")

    assert calls == ["saved"]


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


def test_status_container_retries_legacy_native_status_signature() -> None:
    calls = []

    class LegacyStatus(_FakeStreamlit):
        def status(self, label, **kwargs):
            if kwargs:
                raise TypeError("legacy signature")
            @contextmanager
            def _ctx():
                calls.append(("status", label))
                yield self

            return _ctx()

    fake = LegacyStatus()

    with ux_widgets.status_container(fake, "Running"):
        pass

    assert calls == [("status", "Running")]


def test_status_container_uses_spinner_and_ignores_bad_spinner_signature() -> None:
    calls = []

    class SpinnerOnly(_FakeStreamlit):
        @contextmanager
        def spinner(self, label):
            calls.append(("spinner", label))
            yield self

    fake = SpinnerOnly()
    with ux_widgets.status_container(fake, "Running"):
        pass

    assert calls == [("spinner", "Running")]

    class BadSpinner(_FakeStreamlit):
        def spinner(self, _label):
            raise TypeError("bad spinner")

    fallback = BadSpinner()
    with ux_widgets.status_container(fallback, "Running"):
        pass

    assert fallback.events == [("info", "Running")]


def test_status_container_falls_back_to_messages() -> None:
    fake = _FakeStreamlit()

    with ux_widgets.status_container(fake, "Running", state="running") as status:
        status.update(label="Done", state="complete", expanded=False)

    assert fake.events == [("info", "Running"), ("success", "Done")]


def test_status_container_update_without_label_only_updates_state() -> None:
    fake = _FakeStreamlit()

    with ux_widgets.status_container(fake, "Running") as status:
        status.update(state="complete")

    assert status.state == "complete"
    assert fake.events == [("info", "Running")]


def test_compact_choice_uses_native_segmented_control() -> None:
    calls = []

    class NativeSegmented(_FakeStreamlit):
        def segmented_control(self, label, options, **kwargs):
            calls.append((label, list(options), kwargs))
            return options[1]

    fake = NativeSegmented()

    result = ux_widgets.compact_choice(fake, "Mode", ["Run", "Edit"], key="mode", default="Run")

    assert result == "Edit"
    assert calls[0][0] == "Mode"
    assert calls[0][1] == ["Run", "Edit"]
    assert calls[0][2]["default"] == "Run"
    assert calls[0][2]["key"] == "mode"


def test_compact_choice_returns_none_for_empty_options() -> None:
    assert ux_widgets.compact_choice(_FakeStreamlit(), "Mode", []) is None


def test_compact_choice_uses_index_when_default_is_missing() -> None:
    calls = []

    class SelectboxOnly(_FakeStreamlit):
        def selectbox(self, label, options, **kwargs):
            calls.append((label, list(options), kwargs))
            return options[1]

    fake = SelectboxOnly()

    result = ux_widgets.compact_choice(
        fake,
        "Mode",
        ["Run", "Edit"],
        default="missing",
        index=1,
        inline_limit=0,
    )

    assert result == "Edit"
    assert calls[0][2]["index"] == 1


def test_compact_choice_uses_zero_index_when_default_and_index_are_invalid() -> None:
    calls = []

    class SelectboxOnly(_FakeStreamlit):
        def selectbox(self, label, options, **kwargs):
            calls.append((label, list(options), kwargs))
            return options[0]

    fake = SelectboxOnly()

    result = ux_widgets.compact_choice(
        fake,
        "Mode",
        ["Run", "Edit"],
        default="missing",
        index=99,
        inline_limit=0,
    )

    assert result == "Run"
    assert calls[0][2]["index"] == 0


def test_compact_choice_omits_native_default_when_keyed_state_exists() -> None:
    calls = []

    class NativeSegmented(_FakeStreamlit):
        def segmented_control(self, label, options, **kwargs):
            calls.append((label, list(options), kwargs))
            return self.session_state["mode"]

    fake = NativeSegmented()
    fake.session_state["mode"] = "Edit"

    result = ux_widgets.compact_choice(fake, "Mode", ["Run", "Edit"], key="mode", default="Run")

    assert result == "Edit"
    assert "default" not in calls[0][2]
    assert calls[0][2]["key"] == "mode"


def test_compact_choice_uses_global_streamlit_state_for_streamlit_containers(monkeypatch) -> None:
    calls = []
    native_state = _State({"mode": "Edit"})

    class SidebarLike:
        __module__ = "streamlit.delta_generator"

        def segmented_control(self, label, options, **kwargs):
            calls.append((label, list(options), kwargs))
            return native_state["mode"]

    monkeypatch.setitem(sys.modules, "streamlit", SimpleNamespace(session_state=native_state))

    result = ux_widgets.compact_choice(SidebarLike(), "Mode", ["Run", "Edit"], key="mode", default="Run")

    assert result == "Edit"
    assert "default" not in calls[0][2]
    assert calls[0][2]["key"] == "mode"


def test_compact_choice_ignores_callable_container_session_state(monkeypatch) -> None:
    calls = []
    native_state = _State({"mode": "Edit"})

    class SidebarLike:
        __module__ = "streamlit.delta_generator"

        def session_state(self):
            return None

        def segmented_control(self, label, options, **kwargs):
            calls.append((label, list(options), kwargs))
            return native_state["mode"]

    monkeypatch.setitem(sys.modules, "streamlit", SimpleNamespace(session_state=native_state))

    result = ux_widgets.compact_choice(SidebarLike(), "Mode", ["Run", "Edit"], key="mode", default="Run")

    assert result == "Edit"
    assert "default" not in calls[0][2]
    assert calls[0][2]["key"] == "mode"


def test_compact_choice_detects_keyed_attribute_state() -> None:
    calls = []

    class NativeSegmented:
        def __init__(self):
            self.session_state = SimpleNamespace(mode="Edit")

        def segmented_control(self, label, options, **kwargs):
            calls.append((label, list(options), kwargs))
            return self.session_state.mode

    fake = NativeSegmented()

    result = ux_widgets.compact_choice(fake, "Mode", ["Run", "Edit"], key="mode", default="Run")

    assert result == "Edit"
    assert "default" not in calls[0][2]


def test_compact_choice_creates_missing_session_state() -> None:
    calls = []

    class NoState:
        def selectbox(self, label, options, **kwargs):
            calls.append((label, list(options), kwargs))
            return options[0]

    fake = NoState()

    result = ux_widgets.compact_choice(fake, "Mode", ["Run"], key="mode", inline_limit=0)

    assert result == "Run"
    assert calls[0][2]["index"] == 0


def test_compact_choice_tolerates_unsettable_session_state() -> None:
    calls = []

    class NoWritableState:
        def __setattr__(self, name, value):
            if name == "session_state":
                raise AttributeError(name)
            super().__setattr__(name, value)

        def selectbox(self, label, options, **kwargs):
            calls.append((label, list(options), kwargs))
            return options[0]

    fake = NoWritableState()

    assert ux_widgets.compact_choice(fake, "Mode", ["Run"], inline_limit=0) == "Run"
    assert calls[0][2]["index"] == 0


def test_compact_choice_uses_pills_when_segmented_control_missing() -> None:
    calls = []

    class NativePills(_FakeStreamlit):
        def pills(self, label, options, **kwargs):
            calls.append((label, list(options), kwargs))
            return None

    fake = NativePills()

    result = ux_widgets.compact_choice(fake, "Mode", ["Run", "Edit"], default="Edit")

    assert result == "Edit"
    assert calls[0][0] == "Mode"
    assert calls[0][2]["default"] == "Edit"


def test_compact_choice_uses_legacy_inline_signature_after_type_error() -> None:
    calls = []

    class LegacySegmented(_FakeStreamlit):
        def segmented_control(self, label, options, **kwargs):
            calls.append((label, list(options), kwargs))
            if "disabled" in kwargs:
                raise TypeError("legacy signature")
            return None

    fake = LegacySegmented()

    result = ux_widgets.compact_choice(fake, "Mode", ["Run", "Edit"], default="Edit")

    assert result == "Edit"
    assert len(calls) == 2
    assert calls[-1][2] == {"key": None, "format_func": str, "default": "Edit"}


def test_compact_choice_skips_inline_methods_that_reject_all_signatures() -> None:
    calls = []

    class RejectInline(_FakeStreamlit):
        def segmented_control(self, *_args, **_kwargs):
            raise TypeError("no segmented")

        def pills(self, *_args, **_kwargs):
            raise TypeError("no pills")

        def selectbox(self, label, options, **kwargs):
            calls.append((label, list(options), kwargs))
            return options[0]

    fake = RejectInline()

    assert ux_widgets.compact_choice(fake, "Mode", ["Run", "Edit"]) == "Run"
    assert calls[0][0] == "Mode"


def test_compact_choice_falls_back_to_selectbox_for_long_option_lists() -> None:
    calls = []

    class SelectboxOnly(_FakeStreamlit):
        def segmented_control(self, *_args, **_kwargs):
            raise AssertionError("segmented control should be skipped for long lists")

        def selectbox(self, label, options, **kwargs):
            calls.append((label, list(options), kwargs))
            return options[2]

    fake = SelectboxOnly()

    result = ux_widgets.compact_choice(
        fake,
        "Step",
        ["a", "b", "c", "d"],
        default="b",
        inline_limit=3,
    )

    assert result == "c"
    assert calls[0][0] == "Step"
    assert calls[0][2]["index"] == 1


def test_compact_choice_uses_radio_fallback_and_legacy_radio_signature() -> None:
    calls = []

    class LegacyRadio(_FakeStreamlit):
        def radio(self, label, options, **kwargs):
            calls.append((label, list(options), kwargs))
            if "disabled" in kwargs:
                raise TypeError("legacy signature")
            return options[1]

    fake = LegacyRadio()

    result = ux_widgets.compact_choice(
        fake,
        "Execution panel",
        ["Run now", "Serve"],
        default="Serve",
        fallback="radio",
        inline_limit=0,
    )

    assert result == "Serve"
    assert len(calls) == 2
    assert calls[-1][2]["index"] == 1


def test_compact_choice_omits_fallback_index_when_keyed_state_exists() -> None:
    calls = []

    class RadioOnly(_FakeStreamlit):
        def radio(self, label, options, **kwargs):
            calls.append((label, list(options), kwargs))
            return self.session_state["execution"]

    fake = RadioOnly()
    fake.session_state["execution"] = "Serve"

    result = ux_widgets.compact_choice(
        fake,
        "Execution panel",
        ["Run now", "Serve"],
        key="execution",
        fallback="radio",
        inline_limit=0,
    )

    assert result == "Serve"
    assert "index" not in calls[0][2]
    assert calls[0][2]["key"] == "execution"


def test_compact_choice_legacy_selectbox_signature() -> None:
    calls = []

    class LegacySelectbox(_FakeStreamlit):
        def selectbox(self, label, options, **kwargs):
            calls.append((label, list(options), kwargs))
            if "disabled" in kwargs:
                raise TypeError("legacy signature")
            return options[0]

    fake = LegacySelectbox()

    result = ux_widgets.compact_choice(fake, "Mode", ["Run", "Edit"], inline_limit=0)

    assert result == "Run"
    assert len(calls) == 2
    assert calls[-1][2]["index"] == 0


def test_compact_choice_forwards_disabled_to_fallback_selectbox() -> None:
    calls = []

    class SelectboxOnly(_FakeStreamlit):
        def selectbox(self, label, options, **kwargs):
            calls.append((label, list(options), kwargs))
            return options[0]

    fake = SelectboxOnly()

    result = ux_widgets.compact_choice(
        fake,
        "Runtime",
        ["default", "custom"],
        disabled=True,
        inline_limit=0,
    )

    assert result == "default"
    assert calls[0][2]["disabled"] is True


def test_compact_choice_returns_default_when_no_widget_is_available() -> None:
    assert ux_widgets.compact_choice(SimpleNamespace(), "Mode", ["Run", "Edit"], default="Edit") == "Edit"


def test_confirm_button_fallback_requires_second_confirm_click() -> None:
    fake = _FakeStreamlit(buttons={"clean": True})

    assert ux_widgets.confirm_button(fake, "Clean", key="clean", message="Delete?") is False
    assert fake.session_state["clean__armed"] is True

    fake.buttons = {"clean__confirm": True}
    assert ux_widgets.confirm_button(fake, "Clean", key="clean", message="Delete?") is True
    assert "clean__armed" not in fake.session_state


def test_confirm_button_dialog_confirm_sets_confirmed_and_reruns() -> None:
    calls = []

    class DialogStreamlit(_FakeStreamlit):
        def dialog(self, title):
            calls.append(("dialog", title))

            def _decorator(func):
                func()
                return func

            return _decorator

    fake = DialogStreamlit(buttons={"clean": True, "clean__confirm": True})

    assert ux_widgets.confirm_button(fake, "Clean", key="clean", message="Delete?") is True
    assert ("dialog", "Clean") in calls
    assert ("rerun", "called") in fake.events
    assert "clean__dialog_open" not in fake.session_state


def test_confirm_button_dialog_cancel_clears_open_state() -> None:
    class DialogStreamlit(_FakeStreamlit):
        def dialog(self, _title):
            def _decorator(func):
                func()
                return func

            return _decorator

    fake = DialogStreamlit(buttons={"clean__cancel": True})
    fake.session_state["clean__dialog_open"] = True

    assert ux_widgets.confirm_button(fake, "Clean", key="clean", message="Delete?") is False
    assert "clean__dialog_open" not in fake.session_state
    assert ("rerun", "called") in fake.events


def test_confirm_button_attribute_session_state_fallback() -> None:
    class AttributeStateStreamlit(_FakeStreamlit):
        def __init__(self):
            super().__init__(buttons={"clean": True})
            self.session_state = SimpleNamespace()

    fake = AttributeStateStreamlit()

    assert ux_widgets.confirm_button(fake, "Clean", key="clean", message="Delete?", use_dialog=False) is False
    assert fake.session_state.clean__armed is True


def test_confirm_button_attribute_state_confirm_pops_armed_state() -> None:
    class AttributeStateStreamlit(_FakeStreamlit):
        def __init__(self):
            super().__init__(buttons={"clean__confirm": True})
            self.session_state = SimpleNamespace(clean__armed=True)

    fake = AttributeStateStreamlit()

    assert ux_widgets.confirm_button(fake, "Clean", key="clean", message="Delete?", use_dialog=False) is True
    assert not hasattr(fake.session_state, "clean__armed")


def test_confirm_button_fallback_cancel_clears_armed_state() -> None:
    fake = _FakeStreamlit(buttons={"clean__cancel": True})
    fake.session_state["clean__armed"] = True

    assert ux_widgets.confirm_button(fake, "Clean", key="clean", message="Delete?") is False

    assert "clean__armed" not in fake.session_state
    assert ("rerun", "called") in fake.events
