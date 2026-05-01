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
        source="PIPELINE",
    )

    buttons = editor_calls[-1]["buttons"]["buttons"]
    assert [button["name"] for button in buttons[:2]] == ["Copy", "Pin"]
    panel = fake_st.session_state[pinned_expander.PINNED_EXPANDERS_KEY]["logs"]
    assert panel["title"] == "Logs"
    assert panel["body"] == "line 1\nline 2"
    assert panel["source"] == "PIPELINE"
    assert ("rerun", "called") in fake_st.events


def test_render_pinned_expanders_is_noop_without_panels() -> None:
    fake_st = SimpleNamespace(session_state={}, sidebar=_FakeSidebar(SimpleNamespace(events=[])))

    pinned_expander.render_pinned_expanders(fake_st)

    assert fake_st.session_state[pinned_expander.PINNED_EXPANDERS_KEY] == {}
