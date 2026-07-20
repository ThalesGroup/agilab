from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from agi_pages import runtime


def test_agi_pages_runtime_resolves_active_app_and_reports_missing(tmp_path: Path) -> None:
    app = tmp_path / "demo_project"
    app.mkdir()

    assert runtime.resolve_active_app_path(["--active-app", str(app)]) == app.resolve()

    errors: list[str] = []
    stops = 0

    def stop() -> None:
        nonlocal stops
        stops += 1

    with pytest.raises(FileNotFoundError, match="Provided --active-app path not found"):
        runtime.resolve_active_app_path(
            ["--active-app", str(tmp_path / "missing")],
            error_fn=errors.append,
            stop_fn=stop,
        )

    assert stops == 1
    assert errors and "Provided --active-app path not found" in errors[0]

    errors.clear()
    stops = 0
    with pytest.raises(ValueError, match="Missing --active-app argument"):
        runtime.resolve_active_app_path(
            [],
            error_fn=errors.append,
            stop_fn=stop,
        )
    assert stops == 1
    assert errors == ["Missing --active-app argument."]

    with pytest.raises(FileNotFoundError, match="Provided --active-app path not found"):
        runtime.resolve_active_app_path(["--active-app", str(tmp_path / "missing_without_callbacks")])


def test_agi_pages_runtime_resolves_query_param_and_custom_missing_reporter(
    monkeypatch, tmp_path: Path
) -> None:
    app = tmp_path / "query_project"
    app.mkdir()
    monkeypatch.setenv("AGILAB_ACTIVE_APP", str(tmp_path / "environment_project"))

    assert runtime.resolve_active_app_path(
        [],
        use_environment=False,
        query_params={"project": [str(app)]},
        query_param_keys=("active_app", "project"),
    ) == app.resolve()

    notices: list[str] = []
    with pytest.raises(ValueError, match="Open from ANALYSIS"):
        runtime.resolve_active_app_path(
            [],
            use_environment=False,
            query_params={},
            query_param_keys=("active_app",),
            missing_message="Open from ANALYSIS.",
            missing_fn=notices.append,
        )
    assert notices == ["Open from ANALYSIS."]


def test_agi_pages_runtime_renders_shared_app_context(tmp_path: Path) -> None:
    events: list[tuple[str, object]] = []

    class _Context:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class _Streamlit:
        def columns(self, count: int):
            assert count == 2
            return [_Context(), _Context()]

        def caption(self, value: str):
            events.append(("caption", value))

        def link_button(self, label: str, url: str, **kwargs):
            events.append(("link", (label, url, kwargs)))

        def expander(self, label: str, **kwargs):
            events.append(("expander", (label, kwargs)))
            return _Context()

        def code(self, value: str, **kwargs):
            events.append(("code", (value, kwargs)))

    active_app = tmp_path / "demo project"
    runtime.render_app_page_context(_Streamlit(), "demo project", active_app)

    assert runtime.analysis_return_url("demo project") == "/ANALYSIS?active_app=demo+project"
    assert ("caption", "`demo project`") in events
    assert (
        "link",
        (
            "Back to ANALYSIS",
            "/ANALYSIS?active_app=demo+project",
            {"type": "secondary", "width": "content"},
        ),
    ) in events
    assert ("code", (str(active_app), {"language": "text"})) in events


def test_agi_pages_runtime_loads_workspace_app_settings_once(tmp_path: Path) -> None:
    settings_path = tmp_path / "app_settings.toml"
    settings_path.write_text("[pages.view_demo]\npattern='*.json'\n", encoding="utf-8")
    state: dict[str, object] = {}
    env = SimpleNamespace(app_settings_file=settings_path)

    loaded = runtime.ensure_app_settings_loaded(state, env)

    assert loaded == {"pages": {"view_demo": {"pattern": "*.json"}}}
    settings_path.write_text("[broken\n", encoding="utf-8")
    assert runtime.ensure_app_settings_loaded(state, env) is loaded

    fresh_state: dict[str, object] = {}
    assert runtime.ensure_app_settings_loaded(fresh_state, env) == {}
    assert runtime.ensure_app_settings_loaded({}, SimpleNamespace()) == {}


def test_agi_pages_runtime_scope_helpers_cover_env_fallbacks(tmp_path: Path) -> None:
    app_path = tmp_path / "apps" / "demo_project"
    app_path.mkdir(parents=True)

    assert runtime.env_app_scope_value(SimpleNamespace(app_path=app_path)) == str(app_path.resolve())
    assert runtime.env_app_scope_value(SimpleNamespace(active_app=app_path)) == str(app_path.resolve())
    assert runtime.env_app_scope_value(SimpleNamespace(apps_path=app_path.parent, app=app_path.name)) == str(app_path.resolve())
    assert runtime.env_app_scope_value(SimpleNamespace()) is None


def test_agi_pages_runtime_ensures_app_scoped_env_reuses_matching_cache(
    tmp_path: Path,
) -> None:
    app = tmp_path / "apps" / "demo_project"
    app.mkdir(parents=True)
    env = SimpleNamespace(apps_path=app.parent, app=app.name)
    state = {"scope": str(app.resolve()), "env": env, "page:choice": "kept"}
    created: list[Path] = []

    resolved = runtime.ensure_app_scoped_env(
        state,
        app,
        scope_key="scope",
        env_factory=lambda active: created.append(active),
        prefixes=("page:",),
    )

    assert resolved is env
    assert created == []
    assert state["page:choice"] == "kept"


def test_agi_pages_runtime_ensures_app_scoped_env_rebuilds_stale_cache(
    tmp_path: Path,
) -> None:
    old_app = tmp_path / "apps" / "old_project"
    new_app = tmp_path / "apps" / "new_project"
    old_app.mkdir(parents=True)
    new_app.mkdir()
    stale_env = SimpleNamespace(apps_path=old_app.parent, app=old_app.name)
    new_env = SimpleNamespace(apps_path=new_app.parent, app=new_app.name)
    state = {
        "scope": str(old_app.resolve()),
        "env": stale_env,
        "app_settings": {"stale": True},
        "page:choice": "stale",
        "global": "kept",
    }
    created: list[Path] = []

    resolved = runtime.ensure_app_scoped_env(
        state,
        new_app,
        scope_key="scope",
        env_factory=lambda active: created.append(active) or new_env,
        keys=("app_settings",),
        prefixes=("page:",),
    )

    assert resolved is new_env
    assert created == [new_app.resolve()]
    assert state == {
        "scope": str(new_app.resolve()),
        "env": new_env,
        "global": "kept",
    }


def test_agi_pages_runtime_ensures_app_scoped_env_rebuilds_unknown_unscoped_cache(
    tmp_path: Path,
) -> None:
    app = tmp_path / "apps" / "demo_project"
    app.mkdir(parents=True)
    unknown_env = SimpleNamespace()
    new_env = SimpleNamespace(apps_path=app.parent, app=app.name)
    state = {"env": unknown_env}

    resolved = runtime.ensure_app_scoped_env(
        state,
        app,
        scope_key="scope",
        env_factory=lambda _active: new_env,
    )

    assert resolved is new_env
    assert state["env"] is new_env
    assert state["scope"] == str(app.resolve())


def test_agi_pages_runtime_file_helpers_are_deterministic(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    (root / "b").mkdir(parents=True)
    (root / "a").mkdir()
    b_file = root / "b" / "metrics.json"
    a_file = root / "a" / "metrics.json"
    b_file.write_text('{"run": "b"}', encoding="utf-8")
    a_file.write_text('{"run": "a"}', encoding="utf-8")
    list_file = root / "list.json"
    malformed_file = root / "malformed.json"
    list_file.write_text("[1, 2]", encoding="utf-8")
    malformed_file.write_text("{", encoding="utf-8")

    class BrokenBase:
        def glob(self, _pattern: str):
            raise OSError("glob unavailable")

    assert runtime.artifact_root(
        SimpleNamespace(AGILAB_EXPORT_ABS=tmp_path / "export", target="demo"),
        "forecast",
    ) == tmp_path / "export" / "demo" / "forecast"
    assert runtime.discover_files(root, "**/metrics.json") == [a_file, b_file]
    assert runtime.discover_files(root / "missing", "[") == []
    assert runtime.discover_files(BrokenBase(), "*.json") == []
    assert runtime.load_json_object(a_file) == {"run": "a"}
    assert runtime.load_json_object(None) == {}
    assert runtime.load_json_object(tmp_path / "missing.json") == {}
    assert runtime.load_json_object(list_file) == {}
    assert runtime.load_json_object(malformed_file) == {}
    assert runtime.relative_label(a_file, root) == "a/metrics.json"
    assert runtime.relative_label(tmp_path / "outside.json", root) == "outside.json"
    assert runtime.safe_float("1.25") == 1.25
    assert runtime.safe_float(float("nan")) is None
    assert runtime.safe_float(float("inf")) is None
    assert runtime.safe_float(object()) is None
    assert runtime.safe_metric("bad") == "n/a"
    assert runtime.safe_metric(1.23456, digits=2) == "1.23"


def test_agi_pages_runtime_configures_and_renders_streamlit_page_header() -> None:
    events: list[tuple[str, object]] = []
    fake_st = SimpleNamespace(
        set_page_config=lambda **kwargs: events.append(("config", kwargs)),
        title=lambda value: events.append(("title", value)),
        caption=lambda value: events.append(("caption", value)),
    )

    runtime.configure_streamlit_page(
        fake_st,
        title="Evidence cockpit",
        initial_sidebar_state="collapsed",
    )
    runtime.render_streamlit_page_header(
        fake_st,
        title="Evidence cockpit",
        logo_title="Evidence Cockpit",
        caption="Review baseline versus candidate evidence.",
        render_logo_fn=lambda *args: events.append(("logo", args)),
    )

    assert events == [
        (
            "config",
            {
                "page_title": "Evidence cockpit",
                "layout": "wide",
                "initial_sidebar_state": "collapsed",
            },
        ),
        ("logo", ("Evidence Cockpit",)),
        ("title", "Evidence cockpit"),
        ("caption", "Review baseline versus candidate evidence."),
    ]

    events.clear()
    runtime.render_streamlit_page_header(
        fake_st,
        title="Logo without label",
        logo_title=None,
        show_title=False,
        render_logo_fn=lambda *args: events.append(("logo", args)),
    )
    assert events == [("logo", ())]


def test_agi_pages_runtime_header_can_skip_logo_and_caption() -> None:
    events: list[tuple[str, object]] = []
    fake_st = SimpleNamespace(
        title=lambda value: events.append(("title", value)),
        caption=lambda value: events.append(("caption", value)),
    )

    runtime.render_streamlit_page_header(
        fake_st,
        title="Embedded training analysis",
        show_logo=False,
    )

    assert events == [("title", "Embedded training analysis")]


def test_agi_pages_runtime_header_can_render_logo_without_title() -> None:
    events: list[tuple[str, object]] = []
    fake_st = SimpleNamespace(
        title=lambda value: events.append(("title", value)),
        caption=lambda value: events.append(("caption", value)),
    )

    runtime.render_streamlit_page_header(
        fake_st,
        title="3D maps",
        logo_title="3D Maps",
        show_title=False,
        render_logo_fn=lambda *args: events.append(("logo", args)),
    )

    assert events == [("logo", ("3D Maps",))]


def test_agi_pages_runtime_resets_app_scoped_session_state(tmp_path: Path) -> None:
    first_app = tmp_path / "first"
    second_app = tmp_path / "second"
    first_app.mkdir()
    second_app.mkdir()
    state = {
        "scope": str(first_app.resolve()),
        "keep": "global",
        "exact": "stale",
        "page:widget": "stale",
        "other:widget": "global",
    }

    assert (
        runtime.reset_scoped_session_state(
            state,
            "scope",
            second_app,
            keys=("exact",),
            prefixes=("page:",),
        )
        is True
    )

    assert state == {
        "scope": str(second_app.resolve()),
        "keep": "global",
        "other:widget": "global",
    }
    assert (
        runtime.reset_scoped_session_state(
            state,
            "scope",
            second_app,
            keys=("exact",),
            prefixes=("page:",),
        )
        is False
    )


def test_agi_pages_runtime_resets_can_preserve_first_scope(tmp_path: Path) -> None:
    app = tmp_path / "app"
    app.mkdir()
    state = {"page:value": "warm-start"}

    changed = runtime.reset_scoped_session_state(
        state,
        "scope",
        app,
        prefixes=("page:",),
        clear_on_first_scope=False,
    )

    assert changed is True
    assert state == {"page:value": "warm-start", "scope": str(app.resolve())}


def test_agi_pages_runtime_infers_env_app_scope(tmp_path: Path) -> None:
    app = tmp_path / "apps" / "demo"
    app.mkdir(parents=True)

    assert runtime.env_app_scope_value(SimpleNamespace(app_path=app)) == str(app.resolve())
    assert runtime.env_app_scope_value(SimpleNamespace(active_app=app)) == str(app.resolve())
    assert runtime.env_app_scope_value(SimpleNamespace(apps_path=app.parent, app=app.name)) == str(app.resolve())
    assert runtime.env_app_scope_value(SimpleNamespace()) is None


def test_agi_pages_runtime_ensure_repo_on_path(monkeypatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    src_root = repo_root / "src"
    page_file = src_root / "agilab" / "apps-pages" / "view_demo" / "src" / "view_demo" / "view_demo.py"
    page_file.parent.mkdir(parents=True)
    page_file.write_text("# page\n", encoding="utf-8")

    monkeypatch.setattr(sys, "path", [])
    runtime.ensure_repo_on_path(page_file)

    assert str(src_root) in sys.path
    assert str(repo_root) in sys.path
    first_path = list(sys.path)

    runtime.ensure_repo_on_path(page_file)

    assert sys.path == first_path


def test_agi_pages_runtime_ensure_repo_on_path_ignores_unmatched_anchor(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "path", [])

    runtime.ensure_repo_on_path(tmp_path / "outside.py")

    assert sys.path == []
