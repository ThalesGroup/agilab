from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src/agilab/page_project_selector.py"


def _load_module():
    module_name = "agilab_page_project_selector_test_module"
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


def test_project_selector_edit_button_updates_query_and_switches_page() -> None:
    module = _load_module()
    switched: list[Path] = []
    changed: list[str] = []

    class SelectorHost:
        @staticmethod
        def selectbox(_label, options, *, index=0, **_kwargs):
            assert options == ["alpha_project", "beta_project"]
            assert index == 0
            return "beta_project"

    class EditHost:
        @staticmethod
        def button(_label, **_kwargs):
            return True

    streamlit = SimpleNamespace(
        session_state={"project_selectbox": "stale_project"},
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
        on_change=changed.append,
    )

    assert selection == "beta_project"
    assert streamlit.query_params["active_app"] == "beta_project"
    assert switched == [Path("pages/1_PROJECT.py")]
    assert changed == ["beta_project"]
