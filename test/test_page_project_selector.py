from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src/agilab/page_project_selector.py"


def _load_module():
    module_name = "agilab.page_project_selector"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_unique_project_names_sorts_and_deduplicates_case_insensitively() -> None:
    module = _load_module()

    assert module._unique_project_names(
        ["zeta_project", " Alpha_project ", "", "beta_project", "zeta_project"]
    ) == ["Alpha_project", "beta_project", "zeta_project"]


def test_render_project_selector_keeps_missing_current_in_sorted_options() -> None:
    module = _load_module()
    calls: list[Any] = []

    class _Host:
        def selectbox(self, _label, options, *, index=0, **_kwargs):
            calls.append(list(options))
            assert options == ["Alpha_project", "current_project", "zeta_project"]
            assert index == 1
            return options[index]

    streamlit = SimpleNamespace(
        session_state={},
        sidebar=SimpleNamespace(
            info=lambda *_args, **_kwargs: None,
            columns=lambda *_args, **_kwargs: (_Host(), SimpleNamespace(button=lambda *_a, **_k: False)),
        ),
        query_params={},
        switch_page=lambda *_args, **_kwargs: None,
    )

    selection = module.render_project_selector(
        streamlit,
        ["zeta_project", "Alpha_project"],
        "current_project",
        on_change=lambda selected: calls.append(f"changed:{selected}"),
    )

    assert selection == "current_project"
    assert calls == [["Alpha_project", "current_project", "zeta_project"]]


def test_render_project_selector_can_hide_edit_button_and_keep_valid_state() -> None:
    module = _load_module()
    events: list[str] = []

    class Sidebar:
        def selectbox(self, _label, options, *, index=0, **_kwargs):
            assert options == ["alpha_project"]
            assert index == 0
            return options[index]

    streamlit = SimpleNamespace(
        session_state={"project:selectbox": "alpha_project"},
        sidebar=Sidebar(),
        query_params={},
        switch_page=lambda *_args, **_kwargs: events.append("switch"),
    )

    selection = module.render_project_selector(
        streamlit,
        ["alpha_project"],
        "alpha_project",
        on_change=events.append,
        show_edit_button=False,
    )

    assert selection == "alpha_project"
    assert streamlit.session_state["project:selectbox"] == "alpha_project"
    assert events == []


def test_project_selector_handles_refresh_failure_and_empty_projects() -> None:
    module = _load_module()
    events: list[Any] = []

    class BrokenEnv:
        apps_path = "/apps"
        builtin_apps_path = "/apps/builtin"

        def get_projects(self, *_args):
            raise RuntimeError("project scan failed")

    streamlit = SimpleNamespace(
        session_state={"env": BrokenEnv(), "project_filter": "old"},
        sidebar=SimpleNamespace(info=lambda message: events.append(("info", message))),
    )

    assert module.render_project_selector(streamlit, [], None, on_change=events.append) is None
    assert ("info", "No projects available.") in events
    assert "project_filter" not in streamlit.session_state


def test_project_selector_refreshes_names_from_environment() -> None:
    module = _load_module()

    class Env:
        apps_path = "/apps"
        builtin_apps_path = "/apps/builtin"
        projects = []

        def get_projects(self, apps_path, builtin_apps_path):
            assert apps_path == self.apps_path
            assert builtin_apps_path == self.builtin_apps_path
            return ["beta_project", "alpha_project"]

    env = Env()
    streamlit = SimpleNamespace(session_state={"env": env})

    assert module._refresh_project_names(streamlit, ["fallback_project"]) == ["alpha_project", "beta_project"]
    assert env.projects == ["beta_project", "alpha_project"]


def test_project_selector_edit_button_is_disabled_without_registered_route(monkeypatch) -> None:
    module = _load_module()
    switched: list[Path] = []
    changed: list[str] = []
    button_kwargs: dict[str, object] = {}

    class SelectorHost:
        @staticmethod
        def selectbox(_label, options, *, index=0, **_kwargs):
            assert options == ["alpha_project", "beta_project"]
            assert index == 0
            return options[index]

    class EditHost:
        @staticmethod
        def button(_label, **_kwargs):
            button_kwargs.update(_kwargs)
            return True

    streamlit = SimpleNamespace(
        session_state={"project:selectbox": "stale_project"},
        sidebar=SimpleNamespace(
            info=lambda *_args, **_kwargs: None,
            columns=lambda *_args, **_kwargs: (SelectorHost(), EditHost()),
        ),
        query_params={},
        switch_page=switched.append,
    )
    monkeypatch.delattr(sys.modules["__main__"], "_NAVIGATION_PAGE_ROUTES", raising=False)
    monkeypatch.setitem(sys.modules, "agilab.main_page", SimpleNamespace(_NAVIGATION_PAGE_ROUTES={}))

    selection = module.render_project_selector(
        streamlit,
        ["alpha_project", "beta_project"],
        "alpha_project",
        on_change=changed.append,
    )

    # Stale session value is replaced by the real current project pre-widget.
    assert streamlit.session_state["project:selectbox"] == "alpha_project"
    assert selection == "alpha_project"
    assert button_kwargs.get("disabled") is True
    # Without a registered route the edit button must not hard-code a page path.
    assert switched == []
    assert "active_app" not in streamlit.query_params
    # Selection changes fire only through the widget's own on_change callback.
    assert changed == []


def test_project_selector_widget_callback_fires_on_change(monkeypatch) -> None:
    module = _load_module()
    changed: list[str] = []

    class SelectorHost:
        def __init__(self, streamlit_holder):
            self._holder = streamlit_holder

        def selectbox(self, _label, options, *, index=0, key=None, on_change=None, **_kwargs):
            # Simulate a real user pick: widget state mutates, callback fires.
            self._holder["st"].session_state[key] = "beta_project"
            on_change()
            return "beta_project"

    holder: dict[str, SimpleNamespace] = {}
    streamlit = SimpleNamespace(
        session_state={},
        sidebar=SimpleNamespace(
            info=lambda *_args, **_kwargs: None,
            columns=lambda *_args, **_kwargs: (
                SelectorHost(holder),
                SimpleNamespace(button=lambda *_a, **_k: False),
            ),
        ),
        query_params={},
        switch_page=lambda *_args, **_kwargs: None,
    )
    holder["st"] = streamlit
    monkeypatch.delattr(sys.modules["__main__"], "_NAVIGATION_PAGE_ROUTES", raising=False)
    monkeypatch.setitem(sys.modules, "agilab.main_page", SimpleNamespace(_NAVIGATION_PAGE_ROUTES={}))

    selection = module.render_project_selector(
        streamlit,
        ["alpha_project", "beta_project"],
        "alpha_project",
        on_change=changed.append,
    )

    assert selection == "beta_project"
    assert changed == ["beta_project"]


def test_project_selector_edit_button_prefers_registered_navigation_page(monkeypatch) -> None:
    module = _load_module()
    route = object()
    switched: list[object] = []

    class SelectorHost:
        @staticmethod
        def selectbox(_label, options, *, index=0, **_kwargs):
            assert index == 0
            return options[index]

    class EditHost:
        @staticmethod
        def button(_label, **_kwargs):
            return True

    monkeypatch.setitem(
        sys.modules,
        "agilab.main_page",
        SimpleNamespace(_NAVIGATION_PAGE_ROUTES={module.PROJECT_ROUTE_ID: route}),
    )
    monkeypatch.delattr(sys.modules["__main__"], "_NAVIGATION_PAGE_ROUTES", raising=False)

    streamlit = SimpleNamespace(
        session_state={},
        sidebar=SimpleNamespace(
            info=lambda *_args, **_kwargs: None,
            columns=lambda *_args, **_kwargs: (SelectorHost(), EditHost()),
        ),
        query_params={},
        switch_page=switched.append,
    )

    selection = module.render_project_selector(
        streamlit,
        ["alpha_project", "beta_project"],
        "alpha_project",
        on_change=lambda _selected: None,
    )

    assert selection == "alpha_project"
    assert streamlit.query_params["active_app"] == "alpha_project"
    assert switched == [route]


def test_registered_navigation_page_prefers_main_module_route(monkeypatch) -> None:
    module = _load_module()
    main_route = object()
    fallback_route = object()

    monkeypatch.setattr(
        sys.modules["__main__"],
        "_NAVIGATION_PAGE_ROUTES",
        {module.PROJECT_ROUTE_ID: main_route},
        raising=False,
    )
    monkeypatch.setitem(
        sys.modules,
        "agilab.main_page",
        SimpleNamespace(_NAVIGATION_PAGE_ROUTES={module.PROJECT_ROUTE_ID: fallback_route}),
    )

    assert module._registered_navigation_page(module.PROJECT_ROUTE_ID) is main_route


def test_registered_navigation_page_ignores_missing_or_invalid_routes(monkeypatch) -> None:
    module = _load_module()

    monkeypatch.setattr(sys.modules["__main__"], "_NAVIGATION_PAGE_ROUTES", [module.PROJECT_ROUTE_ID], raising=False)
    monkeypatch.setitem(
        sys.modules,
        "agilab.main_page",
        SimpleNamespace(_NAVIGATION_PAGE_ROUTES={module.PROJECT_ROUTE_ID: None, "analysis": object()}),
    )

    assert module._registered_navigation_page(module.PROJECT_ROUTE_ID) is None


def test_switch_to_project_page_handles_missing_switch_page_without_side_effects() -> None:
    module = _load_module()
    streamlit = SimpleNamespace(query_params={})

    assert module.switch_to_project_page(streamlit, active_app="alpha_project") is False
    assert streamlit.query_params == {}


def test_switch_to_project_page_requires_registered_route(monkeypatch) -> None:
    module = _load_module()
    switched: list[Path] = []
    streamlit = SimpleNamespace(query_params={"keep": "value"}, switch_page=switched.append)

    monkeypatch.delattr(sys.modules["__main__"], "_NAVIGATION_PAGE_ROUTES", raising=False)
    monkeypatch.setitem(sys.modules, "agilab.main_page", SimpleNamespace(_NAVIGATION_PAGE_ROUTES={}))

    assert module.switch_to_project_page(streamlit, active_app="alpha_project") is False
    assert streamlit.query_params == {"keep": "value"}
    assert switched == []
