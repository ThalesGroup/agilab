from __future__ import annotations

import importlib
import importlib.util
import os
from datetime import datetime
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch


def _load_module(module_name: str, relative_path: str):
    module_path = Path(relative_path)
    importlib.invalidate_caches()
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


pipeline_lab = _load_module("agilab.pipeline_lab", "src/agilab/pipeline_lab.py")


class _State(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


class _Ctx:
    def __init__(self, owner=None):
        self._owner = owner

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def __getattr__(self, name):
        if self._owner is None:
            raise AttributeError(name)
        return getattr(self._owner, name)


class _FakeStreamlit:
    def __init__(self, session_state=None, *, buttons=None, selectboxes=None, multiselects=None):
        self.session_state = _State(session_state or {})
        self._buttons = buttons or {}
        self._selectboxes = selectboxes or {}
        self._multiselects = multiselects or {}
        self.messages: list[tuple[str, str]] = []

    def fragment(self, func):
        return func

    def info(self, message):
        self.messages.append(("info", str(message)))

    def warning(self, message):
        self.messages.append(("warning", str(message)))

    def caption(self, message):
        self.messages.append(("caption", str(message)))

    def code(self, message, language=None):
        self.messages.append(("code", str(message)))

    def error(self, message):
        self.messages.append(("error", str(message)))

    def success(self, message):
        self.messages.append(("success", str(message)))

    def rerun(self):
        self.messages.append(("rerun", "called"))

    def expander(self, _label, expanded=False):
        self.messages.append(("expander", str(expanded)))
        return _Ctx(self)

    def columns(self, specs, gap=None):
        count = len(specs) if isinstance(specs, (list, tuple)) else int(specs)
        return [_Ctx(self) for _ in range(count)]

    def multiselect(self, _label, options, key=None, format_func=None, help=None):
        value = self._multiselects.get(key, self.session_state.get(key, list(options)))
        self.session_state[key] = list(value)
        return list(value)

    def graphviz_chart(self, chart, width=None):
        self.messages.append(("graphviz", str(bool(chart))))

    def divider(self):
        self.messages.append(("divider", "called"))

    def empty(self):
        return _Ctx(self)

    def selectbox(self, _label, options, key=None, help=None, **_kwargs):
        value = self._selectboxes.get(key, self.session_state.get(key, options[0]))
        self.session_state[key] = value
        return value

    def text_area(self, _label, key=None, placeholder=None, label_visibility=None, on_change=None, **_kwargs):
        self.session_state.setdefault(key, "")
        return self.session_state[key]

    def text_input(self, _label, value="", disabled=False, key=None, **_kwargs):
        self.session_state.setdefault(key, value)
        return self.session_state[key]

    def button(self, _label, key=None, **_kwargs):
        return bool(self._buttons.get(key or _label, False))


def _load_pipeline_lab_with_missing(*missing_modules: str):
    module_name = f"agilab.pipeline_lab_fallback_{len(missing_modules)}_{abs(hash(missing_modules))}"
    original_import = __import__

    def _patched_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in missing_modules:
            raise ModuleNotFoundError(name)
        return original_import(name, globals, locals, fromlist, level)

    with patch("builtins.__import__", _patched_import):
        return _load_module(module_name, "src/agilab/pipeline_lab.py")


def _make_lab_deps(**overrides):
    defaults = dict(
        load_all_steps=lambda *_args, **_kwargs: [],
        save_step=lambda *_args, **_kwargs: None,
        remove_step=lambda *_args, **_kwargs: None,
        force_persist_step=lambda *_args, **_kwargs: None,
        capture_pipeline_snapshot=lambda *_args, **_kwargs: {},
        restore_pipeline_snapshot=lambda *_args, **_kwargs: None,
        run_all_steps=lambda *_args, **_kwargs: None,
        prepare_run_log_file=lambda *_args, **_kwargs: None,
        get_run_placeholder=lambda *_args, **_kwargs: None,
        push_run_log=lambda *_args, **_kwargs: None,
        rerun_fragment_or_app=lambda *_args, **_kwargs: None,
        bump_history_revision=lambda *_args, **_kwargs: None,
        ask_gpt=lambda *_args, **_kwargs: ["", "generated question", "model", "print('ok')"],
        maybe_autofix_generated_code=lambda *_args, **_kwargs: None,
        load_df_cached=lambda *_args, **_kwargs: None,
        ensure_safe_service_template=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
        refresh_pipeline_run_lock=lambda *_args, **_kwargs: None,
        acquire_pipeline_run_lock=lambda *_args, **_kwargs: None,
        release_pipeline_run_lock=lambda *_args, **_kwargs: None,
        label_for_step_runtime=lambda *_args, **_kwargs: "",
        python_for_step=lambda *_args, **_kwargs: "python",
        python_for_venv=lambda *_args, **_kwargs: "python",
        stream_run_command=lambda *_args, **_kwargs: None,
        run_locked_step=lambda *_args, **_kwargs: None,
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: None,
        render_pipeline_view=lambda *_args, **_kwargs: None,
        default_df="",
        safe_service_template_filename="AGI_serve_safe_start_template.py",
        safe_service_template_marker="# marker",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_get_existing_snippets_deduplicates_and_disambiguates_labels(monkeypatch, tmp_path):
    steps_file = tmp_path / "lab_steps.toml"
    steps_file.write_text("", encoding="utf-8")

    snippet_dir = tmp_path / "snippets"
    snippet_dir.mkdir()
    explicit_snippet = snippet_dir / "AGI_run.py"
    explicit_snippet.write_text("print('explicit')\n", encoding="utf-8")

    safe_template = tmp_path / "templates" / "AGI_run.py"
    safe_template.parent.mkdir(parents=True)
    safe_template.write_text("print('safe')\n", encoding="utf-8")

    runenv_dir = tmp_path / "runenv"
    runenv_dir.mkdir()
    runenv_snippet = runenv_dir / "AGI_run_flight.py"
    runenv_snippet.write_text("print('runenv')\n", encoding="utf-8")

    app_settings = tmp_path / "app_settings.toml"
    app_settings.write_text("x=1\n", encoding="utf-8")
    os.utime(runenv_snippet, None)

    fake_st = SimpleNamespace(session_state={"snippet_file": str(explicit_snippet)})
    monkeypatch.setattr(pipeline_lab, "st", fake_st)

    env = SimpleNamespace(
        runenv=runenv_dir,
        app_settings_file=app_settings,
        app="flight",
    )
    deps = SimpleNamespace(
        ensure_safe_service_template=lambda *_args, **_kwargs: safe_template,
        safe_service_template_filename="unused.py",
        safe_service_template_marker="marker",
    )

    option_map = pipeline_lab.get_existing_snippets(env, steps_file, deps)

    labels = list(option_map.keys())
    assert "AGI_run.py" in labels
    assert "AGI_run.py (templates)" in labels
    assert "AGI_run_flight.py" in labels
    assert len(option_map) == 3


def test_get_existing_snippets_filters_stale_and_wrong_app_runenv_snippets(monkeypatch, tmp_path):
    steps_file = tmp_path / "lab_steps.toml"
    steps_file.write_text("", encoding="utf-8")

    runenv_dir = tmp_path / "runenv"
    runenv_dir.mkdir()

    stale_install = runenv_dir / "AGI_install_flight.py"
    stale_install.write_text("print('stale')\n", encoding="utf-8")

    fresh_run = runenv_dir / "AGI_run_flight.py"
    fresh_run.write_text("print('fresh')\n", encoding="utf-8")

    wrong_app_run = runenv_dir / "AGI_run_other.py"
    wrong_app_run.write_text("print('other')\n", encoding="utf-8")

    app_settings = tmp_path / "app_settings.toml"
    app_settings.write_text("x=1\n", encoding="utf-8")

    old_time = datetime(2026, 4, 1, 10, 0, 0).timestamp()
    new_time = datetime(2026, 4, 1, 12, 0, 0).timestamp()
    os.utime(stale_install, (old_time, old_time))
    os.utime(app_settings, (new_time, new_time))
    os.utime(fresh_run, (new_time + 60, new_time + 60))

    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(pipeline_lab, "st", fake_st)

    env = SimpleNamespace(
        runenv=runenv_dir,
        app_settings_file=app_settings,
        app="flight",
    )
    deps = SimpleNamespace(
        ensure_safe_service_template=lambda *_args, **_kwargs: None,
        safe_service_template_filename="unused.py",
        safe_service_template_marker="marker",
    )

    option_map = pipeline_lab.get_existing_snippets(env, steps_file, deps)

    assert option_map == {"AGI_run_flight.py": fresh_run}


def test_pipeline_lab_import_falls_back_when_pipeline_modules_are_unavailable():
    fallback = _load_pipeline_lab_with_missing("agilab.pipeline_steps", "agilab.pipeline_runtime")

    assert callable(fallback.get_existing_snippets)
    assert callable(fallback.display_lab_tab)
    assert fallback.ORCHESTRATE_LOCKED_STEP_KEY == pipeline_lab.ORCHESTRATE_LOCKED_STEP_KEY


def test_display_lab_tab_empty_pipeline_renders_generator_form(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit({"demo": [0, "", "", "", "", "", 0]})
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    monkeypatch.setattr(pipeline_lab, "get_available_virtualenvs", lambda _env: [])
    monkeypatch.setattr(pipeline_lab, "normalize_runtime_path", lambda raw: str(raw) if raw else "")

    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")
    deps = _make_lab_deps()

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert ("info", "No steps recorded yet. Generate your first step below.") in fake_st.messages
    assert fake_st.session_state["demo"][0] == 0
    assert fake_st.session_state["demo"][-1] == 0
    assert fake_st.session_state["demo_new_q"] == ""


def test_display_lab_tab_empty_pipeline_warns_when_prompt_missing(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit(
        {"demo": [0, "", "", "", "", "", 0], "demo_new_q": ""},
        buttons={"demo_add_first_step_btn": True},
    )
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    monkeypatch.setattr(pipeline_lab, "get_available_virtualenvs", lambda _env: [])
    monkeypatch.setattr(pipeline_lab, "normalize_runtime_path", lambda raw: str(raw) if raw else "")

    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")
    deps = _make_lab_deps()

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert ("warning", "Enter a prompt before generating code.") in fake_st.messages


def test_display_lab_tab_empty_pipeline_generates_first_step_with_runtime(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime_a"
    runtime_root.mkdir()
    saved: dict[str, object] = {}

    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo_new_q": "build topology",
        },
        buttons={"demo_add_first_step_btn": True},
        selectboxes={"demo_new_venv": str(runtime_root)},
    )
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    monkeypatch.setattr(pipeline_lab, "get_available_virtualenvs", lambda _env: [runtime_root])
    monkeypatch.setattr(pipeline_lab, "normalize_runtime_path", lambda raw: str(raw) if raw else "")

    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={"OPENAI_MODEL": "demo"}, app="flight_project")
    deps = _make_lab_deps(
        save_step=lambda module_path, answer, current_step, nsteps, steps_file, venv_map=None, engine_map=None: saved.update(
            answer=answer,
            venv_map=venv_map,
            engine_map=engine_map,
        ),
        bump_history_revision=lambda: saved.setdefault("bumped", True),
    )

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert saved["venv_map"] == {0: str(runtime_root)}
    assert saved["engine_map"] == {0: "agi.run"}
    assert saved["bumped"] is True
    assert ("rerun", "called") in fake_st.messages


def test_display_lab_tab_empty_pipeline_imports_first_snippet(monkeypatch, tmp_path):
    snippet_path = tmp_path / "AGI_run_demo.py"
    snippet_path.write_text("print('snippet')\n", encoding="utf-8")
    saved: dict[str, object] = {}

    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo_new_step_source": snippet_path.name,
        },
        buttons={"demo_add_first_snippet_btn": True},
        selectboxes={"demo_new_step_source": snippet_path.name},
    )
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    monkeypatch.setattr(pipeline_lab, "get_available_virtualenvs", lambda _env: [])
    monkeypatch.setattr(pipeline_lab, "normalize_runtime_path", lambda raw: str(raw) if raw else "")
    monkeypatch.setattr(
        pipeline_lab,
        "_normalize_imported_orchestrate_snippet",
        lambda code, default_runtime="": ("normalized", "agi.run", default_runtime),
    )

    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")
    deps = _make_lab_deps(
        ensure_safe_service_template=lambda *_args, **_kwargs: snippet_path,
        save_step=lambda module_path, answer, current_step, nsteps, steps_file, venv_map=None, engine_map=None, extra_fields=None: saved.update(
            answer=answer,
            venv_map=venv_map,
            engine_map=engine_map,
            extra_fields=extra_fields,
        ),
        bump_history_revision=lambda: saved.setdefault("bumped", True),
    )

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert saved["engine_map"] == {0: "agi.run"}
    assert saved["extra_fields"][pipeline_lab.ORCHESTRATE_LOCKED_STEP_KEY] is True
    assert saved["extra_fields"][pipeline_lab.ORCHESTRATE_LOCKED_SOURCE_KEY] == str(snippet_path)
    assert fake_st.session_state["demo__details"][0] == f"Imported from {snippet_path}"


def test_display_lab_tab_empty_pipeline_clears_stale_sequence_preferences(monkeypatch, tmp_path):
    persisted = []
    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo__run_sequence": [1, 2],
        }
    )
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    monkeypatch.setattr(pipeline_lab, "get_available_virtualenvs", lambda _env: [])
    monkeypatch.setattr(pipeline_lab, "normalize_runtime_path", lambda raw: str(raw) if raw else "")
    monkeypatch.setattr(
        pipeline_lab,
        "_persist_sequence_preferences",
        lambda _module_path, _steps_file, seq: persisted.append(list(seq)),
    )

    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")
    deps = _make_lab_deps()

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert fake_st.session_state["demo__run_sequence"] == []
    assert persisted == [[]]


def test_display_lab_tab_existing_steps_updates_sequence_and_runtime_selection(monkeypatch, tmp_path):
    persisted_sequences = []
    render_calls = []
    runtime_root = tmp_path / "runtime_a"
    runtime_root.mkdir()
    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo_total_steps": 1,
            "demo__run_sequence": [0],
            "demo__venv_map": {0: ""},
            "demo_run_sequence_widget": [1],
        },
        multiselects={"demo_run_sequence_widget": [1]},
    )
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    monkeypatch.setattr(pipeline_lab, "code_editor", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline_lab, "get_custom_buttons", lambda: [])
    monkeypatch.setattr(pipeline_lab, "get_info_bar", lambda: {})
    monkeypatch.setattr(pipeline_lab, "get_css_text", lambda: {})
    monkeypatch.setattr(pipeline_lab, "get_available_virtualenvs", lambda _env: [runtime_root])
    monkeypatch.setattr(pipeline_lab, "normalize_runtime_path", lambda raw: str(raw) if raw else "")
    monkeypatch.setattr(pipeline_lab, "_is_valid_runtime_root", lambda raw: bool(raw))
    monkeypatch.setattr(
        pipeline_lab,
        "_persist_sequence_preferences",
        lambda _module_path, _steps_file, seq: persisted_sequences.append(list(seq)),
    )
    monkeypatch.setattr(pipeline_lab, "get_existing_snippets", lambda *_args, **_kwargs: {})

    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")
    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [
            {"D": "", "Q": "alpha", "M": "m", "C": "print('a')", "E": ""},
            {"D": "", "Q": "beta", "M": "m", "C": "print('b')", "E": str(runtime_root)},
        ],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *args, **kwargs: render_calls.append((args, kwargs)),
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
    )

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert fake_st.session_state["demo__run_sequence"] == [1]
    assert fake_st.session_state["demo__venv_map"][1] == str(runtime_root)
    assert persisted_sequences[0] == [0, 1]
    assert persisted_sequences[-1] == [1]
    assert render_calls


def test_display_lab_tab_existing_steps_warns_for_empty_add_snippet(monkeypatch, tmp_path):
    snippet_path = tmp_path / "AGI_run_empty.py"
    snippet_path.write_text("", encoding="utf-8")
    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo_new_step_source": snippet_path.name,
            "demo__run_sequence": [0],
        },
        buttons={"demo_add_step_snippet_btn": True},
        selectboxes={"demo_new_step_source": snippet_path.name},
        multiselects={"demo_run_sequence_widget": [0]},
    )
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    monkeypatch.setattr(pipeline_lab, "code_editor", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline_lab, "get_custom_buttons", lambda: [])
    monkeypatch.setattr(pipeline_lab, "get_info_bar", lambda: {})
    monkeypatch.setattr(pipeline_lab, "get_css_text", lambda: {})
    monkeypatch.setattr(pipeline_lab, "get_available_virtualenvs", lambda _env: [])
    monkeypatch.setattr(pipeline_lab, "normalize_runtime_path", lambda raw: str(raw) if raw else "")
    monkeypatch.setattr(pipeline_lab, "_is_valid_runtime_root", lambda raw: bool(raw))
    monkeypatch.setattr(pipeline_lab, "get_existing_snippets", lambda *_args, **_kwargs: {snippet_path.name: snippet_path})

    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")
    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [
            {"D": "", "Q": "alpha", "M": "m", "C": "print('a')", "E": ""}
        ],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
    )

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert ("warning", "Selected snippet is empty.") in fake_st.messages


def test_display_lab_tab_locked_step_run_and_remove_confirm(monkeypatch, tmp_path):
    run_calls = []
    remove_calls = []
    snapshots = []
    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo__run_sequence": [0],
            "demo_confirm_delete_0": True,
        },
        buttons={
            "demo_run_locked_0": True,
            "demo_delete_confirm_0": True,
        },
        multiselects={"demo_run_sequence_widget": [0]},
    )
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    monkeypatch.setattr(pipeline_lab, "get_available_virtualenvs", lambda _env: [])
    monkeypatch.setattr(pipeline_lab, "normalize_runtime_path", lambda raw: str(raw) if raw else "")
    monkeypatch.setattr(pipeline_lab, "_is_valid_runtime_root", lambda raw: bool(raw))
    monkeypatch.setattr(pipeline_lab, "get_existing_snippets", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(pipeline_lab, "get_custom_buttons", lambda: [])
    monkeypatch.setattr(pipeline_lab, "get_info_bar", lambda: {})
    monkeypatch.setattr(pipeline_lab, "get_css_text", lambda: {})

    entry = {
        "D": "",
        "Q": "locked",
        "M": "m",
        "C": "print('locked')",
        pipeline_lab.ORCHESTRATE_LOCKED_STEP_KEY: True,
        pipeline_lab.ORCHESTRATE_LOCKED_SOURCE_KEY: str(tmp_path / "AGI_run_demo.py"),
    }
    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [entry],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
        run_locked_step=lambda *args, **kwargs: run_calls.append((args, kwargs)),
        capture_pipeline_snapshot=lambda *_args, **_kwargs: {"steps": 1},
        remove_step=lambda *args, **kwargs: remove_calls.append((args, kwargs)),
    )
    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert run_calls
    assert remove_calls
    snapshot = fake_st.session_state["demo__undo_delete_snapshot"]
    assert snapshot["label"] == "remove step 1"
    assert "timestamp" in snapshot


def test_display_lab_tab_nonlocked_save_persists_editor_changes(monkeypatch, tmp_path):
    saved = []
    forced = []
    reruns = []
    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo__run_sequence": [0],
        },
        buttons={"demo_save_0": True},
        multiselects={"demo_run_sequence_widget": [0]},
    )
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    monkeypatch.setattr(pipeline_lab, "get_available_virtualenvs", lambda _env: [])
    monkeypatch.setattr(pipeline_lab, "normalize_runtime_path", lambda raw: str(raw) if raw else "")
    monkeypatch.setattr(pipeline_lab, "_is_valid_runtime_root", lambda raw: bool(raw))
    monkeypatch.setattr(pipeline_lab, "get_existing_snippets", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(pipeline_lab, "get_custom_buttons", lambda: [])
    monkeypatch.setattr(pipeline_lab, "get_info_bar", lambda: {})
    monkeypatch.setattr(pipeline_lab, "get_css_text", lambda: {})
    monkeypatch.setattr(
        pipeline_lab,
        "code_editor",
        lambda *_args, **_kwargs: {"text": "print('edited')", "type": None},
    )

    entry = {"D": "desc", "Q": "question", "M": "model", "C": "print('old')", "E": ""}
    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [entry],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
        save_step=lambda *args, **kwargs: saved.append((args, kwargs)),
        force_persist_step=lambda *args, **kwargs: forced.append((args, kwargs)),
        rerun_fragment_or_app=lambda: reruns.append("fragment"),
    )
    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert saved
    assert forced
    assert reruns == ["fragment"]
    assert fake_st.session_state["demo_pending_c_0"] == "print('edited')"


def test_display_lab_tab_revert_restores_previous_snapshot(monkeypatch, tmp_path):
    saved = []
    reruns = []
    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo__run_sequence": [0],
            "demo_step_init_0": True,
            "demo_q_step_0": "latest question",
            "demo_code_step_0": "print('latest')",
            "demo_undo_0": [("initial question", "print('initial')"), ("latest question", "print('latest')")],
        },
        buttons={"demo_revert_0": True},
        multiselects={"demo_run_sequence_widget": [0]},
    )
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    monkeypatch.setattr(pipeline_lab, "get_available_virtualenvs", lambda _env: [])
    monkeypatch.setattr(pipeline_lab, "normalize_runtime_path", lambda raw: str(raw) if raw else "")
    monkeypatch.setattr(pipeline_lab, "_is_valid_runtime_root", lambda raw: bool(raw))
    monkeypatch.setattr(pipeline_lab, "get_existing_snippets", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(pipeline_lab, "get_custom_buttons", lambda: [])
    monkeypatch.setattr(pipeline_lab, "get_info_bar", lambda: {})
    monkeypatch.setattr(pipeline_lab, "get_css_text", lambda: {})
    monkeypatch.setattr(pipeline_lab, "code_editor", lambda *_args, **_kwargs: None)

    entry = {"D": "desc", "Q": "initial question", "M": "model", "C": "print('initial')", "E": ""}
    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [entry],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
        save_step=lambda *args, **kwargs: saved.append((args, kwargs)),
        rerun_fragment_or_app=lambda: reruns.append("fragment"),
    )
    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert saved
    args, kwargs = saved[-1]
    assert args[1][1] == "initial question"
    assert args[1][3] == "print('initial')"
    assert fake_st.session_state["demo_pending_q_0"] == "initial question"
    assert fake_st.session_state["demo_pending_c_0"] == "print('initial')"
    assert fake_st.session_state["demo_editor_rev_0"] == 1
    assert reruns == ["fragment"]


def test_display_lab_tab_run_pipeline_and_delete_all(monkeypatch, tmp_path):
    run_calls = []
    remove_calls = []
    bumped = []
    pushed_logs = []
    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 2],
            "demo__run_sequence": [0, 1],
            "demo_confirm_delete_all": True,
            "demo__details": {0: "a", 1: "b"},
            "demo__venv_map": {0: "runtime-a"},
        },
        buttons={"demo_run_all": True, "demo_delete_all_confirm": True},
        multiselects={"demo_run_sequence_widget": [0, 1]},
    )
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    monkeypatch.setattr(pipeline_lab, "get_available_virtualenvs", lambda _env: [])
    monkeypatch.setattr(pipeline_lab, "normalize_runtime_path", lambda raw: str(raw) if raw else "")
    monkeypatch.setattr(pipeline_lab, "_is_valid_runtime_root", lambda raw: bool(raw))
    monkeypatch.setattr(pipeline_lab, "get_existing_snippets", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(pipeline_lab, "get_custom_buttons", lambda: [])
    monkeypatch.setattr(pipeline_lab, "get_info_bar", lambda: {})
    monkeypatch.setattr(pipeline_lab, "get_css_text", lambda: {})
    monkeypatch.setattr(pipeline_lab, "code_editor", lambda *_args, **_kwargs: None)

    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [
            {"D": "", "Q": "alpha", "M": "m1", "C": "print('a')", "E": ""},
            {"D": "", "Q": "beta", "M": "m2", "C": "print('b')", "E": ""},
        ],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
        prepare_run_log_file=lambda *_args, **_kwargs: (tmp_path / "pipeline.log", None),
        push_run_log=lambda *_args, **kwargs: pushed_logs.append(kwargs.get("message") if "message" in kwargs else _args[1]),
        get_run_placeholder=lambda *_args, **_kwargs: None,
        run_all_steps=lambda *args, **kwargs: run_calls.append((args, kwargs)),
        capture_pipeline_snapshot=lambda *_args, **_kwargs: {"steps": ["alpha", "beta"]},
        remove_step=lambda *args, **kwargs: remove_calls.append((args, kwargs)),
        bump_history_revision=lambda: bumped.append(True),
    )
    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")

    steps_file = tmp_path / "lab_steps.toml"
    module_path = tmp_path / "flight_project"
    pipeline_lab.display_lab_tab(tmp_path, "demo", steps_file, module_path, env, deps)

    assert run_calls
    assert run_calls[-1][1]["force_lock_clear"] is False
    assert remove_calls
    assert [call[0][1] for call in remove_calls] == ["1", "0"]
    assert fake_st.session_state["demo"] == [0, "", "", "", "", "", 0]
    assert fake_st.session_state["demo__run_sequence"] == []
    assert fake_st.session_state["demo__details"] == {}
    assert fake_st.session_state["demo__venv_map"] == {}
    assert fake_st.session_state["lab_selected_venv"] == ""
    assert fake_st.session_state["demo__undo_delete_snapshot"]["label"] == "delete pipeline"
    assert bumped
    assert any("Run pipeline started" in str(message) for message in pushed_logs)
    assert fake_st.messages.count(("rerun", "called")) >= 2


def test_display_lab_tab_existing_steps_generates_new_step(monkeypatch, tmp_path):
    saved = []
    runtime_root = tmp_path / "runtime_b"
    runtime_root.mkdir()
    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo__run_sequence": [0],
            "demo_new_q": "new generated step",
        },
        buttons={"demo_add_step_btn": True},
        selectboxes={"demo_new_venv": str(runtime_root)},
        multiselects={"demo_run_sequence_widget": [0]},
    )
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    monkeypatch.setattr(pipeline_lab, "code_editor", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline_lab, "get_available_virtualenvs", lambda _env: [runtime_root])
    monkeypatch.setattr(pipeline_lab, "normalize_runtime_path", lambda raw: str(raw) if raw else "")
    monkeypatch.setattr(pipeline_lab, "_is_valid_runtime_root", lambda raw: bool(raw))
    monkeypatch.setattr(pipeline_lab, "get_existing_snippets", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(pipeline_lab, "get_custom_buttons", lambda: [])
    monkeypatch.setattr(pipeline_lab, "get_info_bar", lambda: {})
    monkeypatch.setattr(pipeline_lab, "get_css_text", lambda: {})

    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [
            {"D": "", "Q": "alpha", "M": "m", "C": "print('a')", "E": ""}
        ],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
        ask_gpt=lambda *_args, **_kwargs: ["", "new generated step", "model", "print('new')", "detail"],
        maybe_autofix_generated_code=lambda **_kwargs: ("print('fixed')", "fixed-model", "fixed-detail"),
        save_step=lambda *args, **kwargs: saved.append((args, kwargs)),
    )
    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert saved
    args, kwargs = saved[-1]
    assert args[2] == 1
    assert kwargs["venv_map"][1] == str(runtime_root)
    assert kwargs["engine_map"][1] == "agi.run"
    assert ("rerun", "called") in fake_st.messages
