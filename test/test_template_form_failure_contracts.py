"""Template forms report validation/path failures without persisting invalid values."""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1] / "src/agilab/apps/templates"


@pytest.fixture(params=("pandas", "polars", "fireducks", "dag", "simple"))
def form(request, monkeypatch):
    package = request.param + "_app"
    src = ROOT / (package + "_template") / "src"
    monkeypatch.syspath_prepend(str(src))
    original_names = set(sys.modules)
    for name in tuple(sys.modules):
        if name == package or name.startswith(package + "."):
            monkeypatch.delitem(sys.modules, name)
    spec = importlib.util.spec_from_file_location(
        "template_form_" + package, src / "app_args_form.py"
    )
    module = importlib.util.module_from_spec(spec)
    import streamlit as st

    # Import invokes render; an uninitialized session must not mutate settings.
    monkeypatch.setattr(st, "session_state", {})
    spec.loader.exec_module(module)
    events = []
    state = {
        "env": SimpleNamespace(
            humanize_validation_errors=lambda exc: ["Invalid app argument"]
        ),
        "is_args_from_ui": True,
    }
    ui = SimpleNamespace(
        session_state=state,
        caption=lambda value: None,
        warning=lambda value: events.append(("warning", value)),
        error=lambda value: events.append(("error", value)),
        success=lambda value: events.append(("success", value)),
    )
    monkeypatch.setattr(module, "st", ui)
    defaults = module.ArgsModel()
    monkeypatch.setattr(
        module,
        "load_args_state",
        lambda *a, **k: (
            defaults,
            defaults.model_dump(mode="json"),
            Path("settings.toml"),
        ),
    )
    yield request.param, module, state, events
    for name in tuple(sys.modules):
        if (
            name == package or name.startswith(package + ".")
        ) and name not in original_names:
            monkeypatch.delitem(sys.modules, name)


def test_template_form_invalid_model_clears_ui_origin_without_persisting(
    form, monkeypatch
):
    kind, module, state, events = form
    path_key = "data_out" if kind == "simple" else "data_in"
    monkeypatch.setattr(module, "render_form", lambda model: {path_key: []})
    monkeypatch.setattr(
        module, "persist_args", lambda *a, **k: pytest.fail("invalid form persisted")
    )
    module.render()
    assert events == [("warning", "Invalid app argument")]
    assert "is_args_from_ui" not in state


def test_template_form_confined_path_failure_reports_error_without_persisting(
    form, monkeypatch
):
    _, module, _, events = form
    monkeypatch.setattr(
        module, "render_form", lambda model: model.model_dump(mode="json")
    )

    def refuse_path(env, parsed):
        raise ValueError("data path escapes workflow root")

    monkeypatch.setattr(module, "resolve_app_args_share_paths", refuse_path)
    monkeypatch.setattr(
        module, "persist_args", lambda *a, **k: pytest.fail("unsafe path persisted")
    )
    module.render()
    assert events == [("error", "data path escapes workflow root")]
