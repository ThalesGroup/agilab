from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


def _import_agilab_module(module_name: str):
    module_path = Path(__file__).resolve().parents[1] / "src" / "agilab" / f"{module_name.rsplit('.', 1)[-1]}.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


pinned_expander = _import_agilab_module("agilab.pinned_expander")


class _State(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


class _FakeExpander:
    def __init__(self, streamlit, title: str):
        self._streamlit = streamlit
        self._title = title

    def __enter__(self):
        self._streamlit.events.append(("enter_expander", self._title))
        return self

    def __exit__(self, exc_type, exc, tb):
        self._streamlit.events.append(("exit_expander", self._title))
        return False

    def caption(self, body: object):
        self._streamlit.events.append(("caption", str(body)))

    def code(self, body: object, language: str | None = None):
        self._streamlit.events.append(("code", f"{language}:{body}"))

    def markdown(self, body: object):
        self._streamlit.events.append(("markdown", str(body)))

    def write(self, body: object):
        self._streamlit.events.append(("write", str(body)))

    def button(self, label: str, key: str | None = None, **kwargs):
        return self._streamlit.button(label, key=key, **kwargs)


class _FakeSidebar:
    def __init__(self, streamlit):
        self._streamlit = streamlit

    def divider(self):
        self._streamlit.events.append(("divider", ""))

    def markdown(self, body: object):
        self._streamlit.events.append(("sidebar.markdown", str(body)))

    def expander(self, title: str, expanded: bool = False):
        self._streamlit.events.append(("sidebar.expander", f"{title}:{expanded}"))
        return _FakeExpander(self._streamlit, title)


class _FakeStreamlit:
    def __init__(self, *, buttons: dict[str, bool] | None = None):
        self.session_state = _State()
        self.events: list[tuple[str, str]] = []
        self.button_kwargs: dict[str, dict[str, object]] = {}
        self.buttons = buttons or {}
        self.sidebar = _FakeSidebar(self)

    def button(self, label: str, key: str | None = None, **_kwargs):
        self.events.append(("button", str(key or label)))
        self.button_kwargs[str(key or label)] = dict(_kwargs)
        return bool(self.buttons.get(str(key or label), False))

    def caption(self, body: object):
        self.events.append(("caption", str(body)))

    def rerun(self):
        self.events.append(("rerun", "called"))


def test_render_pin_button_creates_and_refreshes_panel() -> None:
    fake_st = _FakeStreamlit(
        buttons={"pinned_expander:toggle:demo": True},
    )

    assert pinned_expander.render_pin_button(
        fake_st,
        "demo",
        title="Demo",
        body="first",
        language="text",
        source="ORCHESTRATE",
    )

    panel = fake_st.session_state[pinned_expander.PINNED_EXPANDERS_KEY]["demo"]
    assert panel["title"] == "Demo"
    assert panel["body"] == "first"
    assert panel["language"] == "text"
    assert panel["source"] == "ORCHESTRATE"
    assert ("rerun", "called") in fake_st.events

    pinned_expander.refresh_pinned_expander(
        fake_st.session_state,
        "demo",
        title="Demo",
        body="second",
    )

    panel = fake_st.session_state[pinned_expander.PINNED_EXPANDERS_KEY]["demo"]
    assert panel["body"] == "second"


def test_render_pinned_expanders_unpins_from_sidebar() -> None:
    fake_st = _FakeStreamlit(
        buttons={"pinned_expander:sidebar_unpin:demo": True},
    )
    pinned_expander.upsert_pinned_expander(
        fake_st.session_state,
        "demo",
        title="Demo",
        body="content",
        language="text",
        source="ORCHESTRATE",
    )

    pinned_expander.render_pinned_expanders(fake_st)

    assert ("sidebar.markdown", "#### Pinned panels") in fake_st.events
    assert ("sidebar.expander", "Demo:True") in fake_st.events
    assert ("caption", "ORCHESTRATE") in fake_st.events
    assert ("code", "text:content") in fake_st.events
    assert not pinned_expander.is_pinned_expander(fake_st.session_state, "demo")
    assert ("rerun", "called") in fake_st.events


def test_render_pin_button_is_visible_but_disabled_without_body() -> None:
    fake_st = _FakeStreamlit()

    assert not pinned_expander.render_pin_button(
        fake_st,
        "empty-demo",
        title="Empty demo",
        body="",
    )

    key = "pinned_expander:toggle:empty-demo"
    assert ("button", key) in fake_st.events
    assert fake_st.button_kwargs[key]["disabled"] is True
    assert "empty-demo" not in fake_st.session_state[pinned_expander.PINNED_EXPANDERS_KEY]


def test_render_pinnable_code_editor_uses_toolbar_pin() -> None:
    fake_st = _FakeStreamlit()
    editor_calls: list[dict[str, object]] = []

    def _code_editor(body: str, **kwargs):
        editor_calls.append({"body": body, **kwargs})
        return {"type": pinned_expander.CODE_EDITOR_PIN_RESPONSE, "text": body}

    pinned_expander.render_pinnable_code_editor(
        fake_st,
        _code_editor,
        "logs",
        title="Logs",
        body="line 1\nline 2",
        key="logs-editor",
        language="text",
        source="WORKFLOW",
    )

    buttons = editor_calls[-1]["buttons"]
    assert isinstance(buttons, list)
    assert [button["name"] for button in buttons[:2]] == ["Copy", "Pin"]
    panel = fake_st.session_state[pinned_expander.PINNED_EXPANDERS_KEY]["logs"]
    assert panel["title"] == "Logs"
    assert panel["body"] == "line 1\nline 2"
    assert panel["source"] == "WORKFLOW"
    assert ("rerun", "called") in fake_st.events


def test_render_pinned_expanders_is_noop_without_panels() -> None:
    fake_st = SimpleNamespace(session_state={}, sidebar=_FakeSidebar(SimpleNamespace(events=[])))

    pinned_expander.render_pinned_expanders(fake_st)

    assert fake_st.session_state[pinned_expander.PINNED_EXPANDERS_KEY] == {}


def test_panel_store_recovers_from_invalid_state_and_lists_sorted() -> None:
    state = _State({pinned_expander.PINNED_EXPANDERS_KEY: "broken"})

    assert not pinned_expander.is_pinned_expander(state, "missing")
    assert state[pinned_expander.PINNED_EXPANDERS_KEY] == {}

    pinned_expander.upsert_pinned_expander(state, "b", title="Beta", body="b")
    pinned_expander.upsert_pinned_expander(state, "a", title="Alpha", body="a")
    pinned_expander.upsert_pinned_expander(state, "c", title="Alpha", body="c")

    assert [panel["id"] for panel in pinned_expander.list_pinned_expanders(state)] == ["a", "c", "b"]
    assert not pinned_expander.remove_pinned_expander(state, "missing")
    assert pinned_expander._button_key("toggle", "demo panel") == "pinned_expander:toggle:demo_panel"


def test_code_editor_pin_buttons_preserves_base_and_uses_response_types() -> None:
    base = {"buttons": [{"name": "CopyCustom"}], "meta": {"x": 1}}

    unpin_buttons = pinned_expander.code_editor_pin_buttons(
        base,
        pinned=True,
        unpin_response="custom_unpin",
    )
    pin_buttons = pinned_expander.code_editor_pin_buttons(
        {"buttons": []},
        pinned=False,
        pin_response="custom_pin",
    )

    assert base == {"buttons": [{"name": "CopyCustom"}], "meta": {"x": 1}}
    assert isinstance(unpin_buttons, list)
    assert [button["name"] for button in unpin_buttons] == ["CopyCustom", "Unpin"]
    assert unpin_buttons[1]["commands"][1][1] == "custom_unpin"
    assert isinstance(pin_buttons, list)
    assert [button["name"] for button in pin_buttons] == ["Pin"]
    assert pin_buttons[0]["commands"][1][1] == "custom_pin"


def test_upsert_truncates_body_and_combines_caption() -> None:
    state = _State()

    panel = pinned_expander.upsert_pinned_expander(
        state,
        "long",
        title="Long",
        body="abcdef",
        caption="Log",
        max_body_chars=3,
    )

    assert panel["body"] == "def"
    assert panel["caption"] == "Log Showing last 3 characters."


def test_refresh_missing_panel_returns_false() -> None:
    assert not pinned_expander.refresh_pinned_expander(
        _State(),
        "missing",
        title="Missing",
        body="content",
    )


def test_render_pin_button_unpins_existing_panel() -> None:
    fake_st = _FakeStreamlit(buttons={"pinned_expander:toggle:demo": True})
    pinned_expander.upsert_pinned_expander(fake_st.session_state, "demo", title="Demo", body="old")

    assert not pinned_expander.render_pin_button(
        fake_st,
        "demo",
        title="Demo",
        body="fresh",
        language="text",
    )

    key = "pinned_expander:toggle:demo"
    assert not pinned_expander.is_pinned_expander(fake_st.session_state, "demo")
    assert fake_st.button_kwargs[key]["disabled"] is False
    assert fake_st.button_kwargs[key]["help"] == "Remove this pinned panel from the sidebar."
    assert ("rerun", "called") in fake_st.events


def test_render_pin_button_refreshes_existing_panel_when_not_clicked() -> None:
    fake_st = _FakeStreamlit()
    pinned_expander.upsert_pinned_expander(fake_st.session_state, "demo", title="Demo", body="old")

    assert pinned_expander.render_pin_button(
        fake_st,
        "demo",
        title="Demo",
        body="fresh",
        source="PROJECT",
    )

    panel = fake_st.session_state[pinned_expander.PINNED_EXPANDERS_KEY]["demo"]
    assert panel["body"] == "fresh"
    assert panel["source"] == "PROJECT"
    assert ("rerun", "called") not in fake_st.events


def test_render_pinnable_code_editor_handles_empty_and_non_dict_response() -> None:
    fake_st = _FakeStreamlit()

    assert (
        pinned_expander.render_pinnable_code_editor(
            fake_st,
            lambda body, **kwargs: {"type": "unused"},
            "empty",
            title="Empty",
            body="   ",
            key="empty-editor",
            empty_message="Nothing to show.",
        )
        is None
    )
    assert ("caption", "Nothing to show.") in fake_st.events

    no_caption_st = SimpleNamespace(session_state=_State())
    assert (
        pinned_expander.render_pinnable_code_editor(
            no_caption_st,
            lambda body, **kwargs: {"type": "unused"},
            "empty",
            title="Empty",
            body="",
            key="empty-editor",
        )
        is None
    )

    editor_calls: list[dict[str, object]] = []

    def _code_editor(body: str, **kwargs):
        editor_calls.append({"body": body, **kwargs})
        return "plain-response"

    assert (
        pinned_expander.render_pinnable_code_editor(
            fake_st,
            _code_editor,
            "logs",
            title="Logs",
            body="line",
            key="logs-editor",
            height=12,
        )
        == "plain-response"
    )
    assert editor_calls[-1]["height"] == 12


def test_render_pinnable_code_editor_unpins_existing_panel_from_toolbar() -> None:
    fake_st = _FakeStreamlit()
    pinned_expander.upsert_pinned_expander(fake_st.session_state, "logs", title="Logs", body="old")
    editor_calls: list[dict[str, object]] = []

    def _code_editor(body: str, **kwargs):
        editor_calls.append({"body": body, **kwargs})
        return {"type": pinned_expander.CODE_EDITOR_UNPIN_RESPONSE, "text": body}

    response = pinned_expander.render_pinnable_code_editor(
        fake_st,
        _code_editor,
        "logs",
        title="Logs",
        body="fresh",
        key="logs-editor",
        language="text",
    )

    buttons = editor_calls[-1]["buttons"]
    assert isinstance(buttons, list)
    assert response["type"] == pinned_expander.CODE_EDITOR_UNPIN_RESPONSE
    assert [button["name"] for button in buttons[:2]] == ["Copy", "Unpin"]
    assert not pinned_expander.is_pinned_expander(fake_st.session_state, "logs")
    assert ("rerun", "called") in fake_st.events


def test_render_pinned_expanders_renders_markdown_and_text_with_container() -> None:
    fake_st = _FakeStreamlit()
    container = _FakeSidebar(fake_st)
    pinned_expander.upsert_pinned_expander(
        fake_st.session_state,
        "markdown",
        title="Markdown",
        body="**ready**",
        body_format="markdown",
        caption="Markdown caption",
    )
    pinned_expander.upsert_pinned_expander(
        fake_st.session_state,
        "text",
        title="Text",
        body="plain text",
        body_format="text",
    )

    pinned_expander.render_pinned_expanders(
        fake_st,
        container=container,
        session_state=fake_st.session_state,
    )

    assert ("divider", "") in fake_st.events
    assert ("sidebar.markdown", "#### Pinned panels") in fake_st.events
    assert ("caption", "Markdown caption") in fake_st.events
    assert ("markdown", "**ready**") in fake_st.events
    assert ("write", "plain text") in fake_st.events


def test_request_rerun_ignores_missing_rerun() -> None:
    pinned_expander._request_rerun(SimpleNamespace())
