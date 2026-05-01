from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


def _import_agilab_module(module_name: str):
    module_path = Path(__file__).resolve().parents[1] / "src" / "agilab" / f"{module_name.rsplit('.', 1)[-1]}.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


workflow_ui = _import_agilab_module("agilab.workflow_ui")


class _FakeContainer:
    def __init__(self, streamlit):
        self._streamlit = streamlit

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def caption(self, body: object):
        self._streamlit.events.append(("caption", str(body)))

    def button(self, label: str, key: str | None = None, **kwargs):
        return self._streamlit.button(label, key=key, **kwargs)

    def download_button(self, label: str, key: str | None = None, **kwargs):
        return self._streamlit.download_button(label, key=key, **kwargs)


class _FakeSidebar:
    def __init__(self, streamlit):
        self._streamlit = streamlit

    def expander(self, title: str, expanded: bool = False):
        self._streamlit.events.append(("sidebar.expander", f"{title}:{expanded}"))
        return _FakeContainer(self._streamlit)


class _FakeStreamlit:
    def __init__(self, *, buttons: dict[str, bool] | None = None):
        self.events: list[tuple[str, str]] = []
        self.buttons = buttons or {}
        self.sidebar = _FakeSidebar(self)

    def expander(self, title: str, expanded: bool = False):
        self.events.append(("expander", f"{title}:{expanded}"))
        return _FakeContainer(self)

    def columns(self, specs):
        count = len(specs) if isinstance(specs, (list, tuple)) else int(specs)
        return [_FakeContainer(self) for _ in range(count)]

    def caption(self, body: object):
        self.events.append(("caption", str(body)))

    def button(self, label: str, key: str | None = None, **kwargs):
        self.events.append(("button", f"{key or label}:{kwargs.get('disabled', False)}"))
        if kwargs.get("disabled"):
            return False
        return bool(self.buttons.get(str(key or label), False))

    def download_button(self, label: str, key: str | None = None, **kwargs):
        self.events.append(("download", f"{key or label}:{kwargs.get('disabled', False)}"))
        return False


def test_render_page_context_shows_page_and_project() -> None:
    fake_st = _FakeStreamlit()
    env = SimpleNamespace(app="flight_project", target="flight_worker", mode="Run now")

    workflow_ui.render_page_context(fake_st, page_label="ORCHESTRATE", env=env)

    assert ("sidebar.expander", "Context:False") in fake_st.events
    assert ("caption", "Page: ORCHESTRATE") in fake_st.events
    assert ("caption", "Project: flight_project") in fake_st.events
    assert ("caption", "Target: flight_worker") in fake_st.events


def test_render_log_actions_can_download_and_clear() -> None:
    fake_st = _FakeStreamlit(buttons={"clear": True})

    assert workflow_ui.render_log_actions(
        fake_st,
        body="line 1",
        download_key="download",
        file_name="run.log",
        clear_key="clear",
    )

    assert ("download", "download:False") in fake_st.events
    assert ("button", "clear:False") in fake_st.events


def test_render_log_actions_disables_empty_actions() -> None:
    fake_st = _FakeStreamlit(buttons={"clear": True})

    assert not workflow_ui.render_log_actions(
        fake_st,
        body="",
        download_key="download",
        file_name="run.log",
        clear_key="clear",
    )

    assert ("download", "download:True") in fake_st.events
    assert ("button", "clear:True") in fake_st.events


def test_render_latest_outputs_summarizes_dataframe_and_downloads(tmp_path) -> None:
    fake_st = _FakeStreamlit()
    output = tmp_path / "output.csv"
    output.write_text("a\n1\n", encoding="utf-8")

    workflow_ui.render_latest_outputs(
        fake_st,
        source_path=output,
        dataframe=pd.DataFrame({"a": [1]}),
        key_prefix="demo",
    )

    assert ("expander", "Latest outputs:False") in fake_st.events
    assert ("caption", "Dataframe: 1 row(s), 1 column(s)") in fake_st.events
    assert ("caption", f"Source: {output}") in fake_st.events
    assert ("download", "demo:download_output:False") in fake_st.events
