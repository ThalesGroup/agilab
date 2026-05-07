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
