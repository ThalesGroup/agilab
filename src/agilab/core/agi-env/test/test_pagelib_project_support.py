from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from agi_env.pagelib_project_support import init_custom_ui, on_project_change


def test_init_custom_ui_support_clears_form_keys():
    state = {
        "toggle_edit_ui": True,
        "x:app_args_form:field": "value",
        "keep": "ok",
    }

    init_custom_ui(state)

    assert state["toggle_edit"] is False
    assert "x:app_args_form:field" not in state
    assert state["app_args_form_refresh_nonce"] == 1
    assert state["keep"] == "ok"


def test_on_project_change_support_updates_state_and_resets_sections(tmp_path):
    class _State(dict):
        def __getattr__(self, name):
            return self[name]

        def __setattr__(self, name, value):
            self[name] = value

    changed: list[Path] = []
    stored: list[Path] = []
    reset_calls: list[dict] = []
    env = SimpleNamespace(
        apps_path=tmp_path / "apps",
        AGILAB_EXPORT_ABS=tmp_path / "exports",
        active_app=tmp_path / "apps" / "demo_project",
        target="demo_project",
    )

    def _change_app(path):
        changed.append(path)
        env.active_app = path

    env.change_app = _change_app
    state = _State({"env": env, "toggle_edit": True})

    on_project_change(
        "demo_project",
        session_state=state,
        store_last_active_app_fn=lambda path: stored.append(path),
        clear_project_session_state_fn=lambda session: session.pop("toggle_edit", None),
        reset_project_sections_fn=lambda session: reset_calls.append(dict(session)),
        error_fn=lambda _message: None,
        switch_to_select=True,
    )

    assert changed == [env.apps_path / "demo_project"]
    assert stored == [env.active_app]
    assert state.module_rel == Path("demo_project")
    assert state.datadir == env.AGILAB_EXPORT_ABS / "demo_project"
    assert state.switch_to_select is True
    assert state.project_changed is True
    assert "toggle_edit" not in state
    assert reset_calls
