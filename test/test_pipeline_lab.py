from __future__ import annotations

import importlib
import importlib.util
import json
import os
from datetime import datetime
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agi_env.snippet_contract import snippet_contract_block


def _ensure_agilab_package_path() -> None:
    package_root = Path("src/agilab").resolve()
    package = sys.modules.get("agilab")
    package_spec = importlib.util.spec_from_file_location(
        "agilab",
        package_root / "__init__.py",
        submodule_search_locations=[str(package_root)],
    )
    if package is None:
        assert package_spec is not None and package_spec.loader is not None
        package = importlib.util.module_from_spec(package_spec)
        sys.modules["agilab"] = package
        package_spec.loader.exec_module(package)
        return

    package_paths = list(getattr(package, "__path__", []) or [])
    package_root_text = str(package_root)
    if package_root_text not in package_paths:
        package.__path__ = [package_root_text, *package_paths]
    package.__spec__ = package_spec
    package.__file__ = str(package_root / "__init__.py")
    package.__package__ = "agilab"


def _load_module(module_name: str, relative_path: str):
    _ensure_agilab_package_path()
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


class _FakeColumnConfig:
    @staticmethod
    def SelectboxColumn(label, **kwargs):
        return {"type": "selectbox", "label": label, **kwargs}


class _FakeStreamlit:
    def __init__(
        self,
        session_state=None,
        *,
        buttons=None,
        selectboxes=None,
        multiselects=None,
        checkboxes=None,
        data_editors=None,
    ):
        self.session_state = _State(session_state or {})
        self._buttons = buttons or {}
        self._selectboxes = selectboxes or {}
        self._multiselects = multiselects or {}
        self._checkboxes = checkboxes or {}
        self._data_editors = data_editors or {}
        self.messages: list[tuple[str, str]] = []
        self.button_calls: list[tuple[str, dict[str, object]]] = []
        self.data_editor_calls: list[tuple[str, dict[str, object]]] = []
        self.graphviz_sources: list[str] = []
        self.multiselect_calls: list[tuple[str, list[object], str | None]] = []
        self.text_area_labels: list[str] = []
        self.column_config = _FakeColumnConfig()

    def fragment(self, func):
        return func

    def info(self, message):
        self.messages.append(("info", str(message)))

    def warning(self, message):
        self.messages.append(("warning", str(message)))

    def caption(self, message):
        self.messages.append(("caption", str(message)))

    def markdown(self, message, **_kwargs):
        self.messages.append(("markdown", str(message)))

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
        self.multiselect_calls.append((str(_label), list(options), key))
        value = self._multiselects.get(key, self.session_state.get(key, list(options)))
        self.session_state[key] = list(value)
        return list(value)

    def graphviz_chart(self, chart, width=None):
        self.graphviz_sources.append(str(chart))
        self.messages.append(("graphviz", str(bool(chart))))

    def metric(self, label, value, delta=None, help=None):
        self.messages.append(("metric", f"{label}={value}"))

    def dataframe(self, data, **_kwargs):
        self.messages.append(("dataframe", str(len(data) if hasattr(data, "__len__") else "unknown")))

    def divider(self):
        self.messages.append(("divider", "called"))

    def empty(self):
        return _Ctx(self)

    def selectbox(self, _label, options, key=None, help=None, **_kwargs):
        value = self._selectboxes.get(key, self.session_state.get(key, options[0]))
        self.session_state[key] = value
        return value

    def text_area(self, _label, key=None, placeholder=None, label_visibility=None, on_change=None, **_kwargs):
        self.text_area_labels.append(str(_label))
        self.session_state.setdefault(key, "")
        return self.session_state[key]

    def text_input(self, _label, value="", disabled=False, key=None, **_kwargs):
        self.session_state.setdefault(key, value)
        return self.session_state[key]

    def checkbox(self, _label, value=False, key=None, **_kwargs):
        lookup_key = key or _label
        checked = self._checkboxes.get(lookup_key, self.session_state.get(lookup_key, value))
        self.session_state[lookup_key] = bool(checked)
        return bool(checked)

    def data_editor(self, data, key=None, **_kwargs):
        self.data_editor_calls.append((str(key), dict(_kwargs)))
        if key in self._data_editors:
            value = self._data_editors[key]
        else:
            value = self.session_state.get(key, data)
        self.session_state[key] = value
        length = len(value) if hasattr(value, "__len__") else "unknown"
        self.messages.append(("data_editor", f"{key}={length}"))
        return value

    def button(self, _label, key=None, **_kwargs):
        self.button_calls.append((str(key or _label), dict(_kwargs)))
        return bool(self._buttons.get(key or _label, False))

    def download_button(self, _label, *, key=None, **_kwargs):
        self.messages.append(("download_button", str(key or _label)))
        return False


def _load_pipeline_lab_with_missing(*missing_modules: str):
    module_name = f"agilab.pipeline_lab_fallback_{len(missing_modules)}_{abs(hash(missing_modules))}"
    original_import = __import__
    original_import_module = importlib.import_module

    def _patched_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in missing_modules:
            exc = ModuleNotFoundError(name)
            exc.name = name
            raise exc
        return original_import(name, globals, locals, fromlist, level)

    def _patched_import_module(name, package=None):
        if name in missing_modules:
            exc = ModuleNotFoundError(name)
            exc.name = name
            raise exc
        return original_import_module(name, package)

    with (
        patch("builtins.__import__", _patched_import),
        patch("importlib.import_module", _patched_import_module),
    ):
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
        configure_assistant_engine=lambda *_args, **_kwargs: None,
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


def test_valid_runtime_path_rejects_non_runtime_roots(monkeypatch):
    monkeypatch.setattr(pipeline_lab, "normalize_runtime_path", lambda raw: str(raw).strip() if raw else "")
    monkeypatch.setattr(pipeline_lab, "_is_valid_runtime_root", lambda raw: str(raw) == "/valid/runtime")

    assert pipeline_lab._valid_runtime_path(" /valid/runtime ") == "/valid/runtime"
    assert pipeline_lab._valid_runtime_path("/tmp/exported_notebooks/demo.ipynb") == ""
    assert pipeline_lab._valid_runtime_path("") == ""


def test_valid_runtime_choices_filters_invalid_and_deduplicates(monkeypatch):
    valid_paths = {"/valid/runtime_a", "/valid/runtime_b"}
    monkeypatch.setattr(pipeline_lab, "normalize_runtime_path", lambda raw: str(raw).strip() if raw else "")
    monkeypatch.setattr(pipeline_lab, "_is_valid_runtime_root", lambda raw: str(raw) in valid_paths)

    assert pipeline_lab._valid_runtime_choices(
        [
            "/valid/runtime_a",
            "/tmp/exported_notebooks/demo.ipynb",
            "/valid/runtime_a",
            None,
            " /valid/runtime_b ",
        ]
    ) == ["/valid/runtime_a", "/valid/runtime_b"]


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
    settings_time = datetime(2026, 4, 1, 11, 0, 0).timestamp()
    new_time = datetime(2026, 4, 1, 12, 0, 0).timestamp()
    os.utime(app_settings, (settings_time, settings_time))
    os.utime(runenv_snippet, (new_time, new_time))

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


def test_get_existing_snippets_warns_and_filters_stale_agi_api_snippets(monkeypatch, tmp_path):
    steps_file = tmp_path / "lab_steps.toml"
    steps_file.write_text("", encoding="utf-8")
    runenv_dir = tmp_path / "runenv"
    runenv_dir.mkdir()

    stale_snippet = runenv_dir / "AGI_install_flight.py"
    stale_snippet.write_text(
        "from agi_cluster.agi_distributor import AGI\n"
        "async def main():\n"
        "    await AGI.install(None)\n",
        encoding="utf-8",
    )
    current_snippet = runenv_dir / "AGI_run_flight.py"
    current_snippet.write_text(
        "from agi_cluster.agi_distributor import AGI\n"
        "from agi_env import AgiEnv\n"
        f"{snippet_contract_block(app='flight')}\n"
        "async def main():\n"
        "    await AGI.run(AgiEnv(apps_path='/tmp/apps', app='flight'))\n",
        encoding="utf-8",
    )

    app_settings = tmp_path / "app_settings.toml"
    app_settings.write_text("x=1\n", encoding="utf-8")
    settings_time = datetime(2026, 4, 1, 11, 0, 0).timestamp()
    new_time = datetime(2026, 4, 1, 12, 0, 0).timestamp()
    os.utime(app_settings, (settings_time, settings_time))
    os.utime(stale_snippet, (new_time, new_time))
    os.utime(current_snippet, (new_time, new_time))

    fake_st = _FakeStreamlit()
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    env = SimpleNamespace(runenv=runenv_dir, app_settings_file=app_settings, app="flight")
    deps = SimpleNamespace(
        ensure_safe_service_template=lambda *_args, **_kwargs: None,
        safe_service_template_filename="unused.py",
        safe_service_template_marker="marker",
    )

    option_map = pipeline_lab.get_existing_snippets(env, steps_file, deps)

    assert option_map == {"AGI_run_flight.py": current_snippet}
    warning_messages = [message for kind, message in fake_st.messages if kind == "warning"]
    assert warning_messages
    assert "AGILAB core snippet API changed" in warning_messages[0]
    assert str(stale_snippet) in warning_messages[0]


def test_get_existing_snippets_cleanup_button_deletes_stale_generated_snippets(monkeypatch, tmp_path):
    steps_file = tmp_path / "lab_steps.toml"
    steps_file.write_text("", encoding="utf-8")
    runenv_dir = tmp_path / "runenv"
    runenv_dir.mkdir()
    stale_snippet = runenv_dir / "AGI_run_flight.py"
    stale_snippet.write_text(
        "from agi_cluster.agi_distributor import AGI\n"
        "async def main():\n"
        "    await AGI.run(None)\n",
        encoding="utf-8",
    )
    app_settings = tmp_path / "app_settings.toml"
    app_settings.write_text("x=1\n", encoding="utf-8")
    settings_time = datetime(2026, 4, 1, 11, 0, 0).timestamp()
    new_time = datetime(2026, 4, 1, 12, 0, 0).timestamp()
    os.utime(app_settings, (settings_time, settings_time))
    os.utime(stale_snippet, (new_time, new_time))

    fake_st = _FakeStreamlit(
        {"clean_stale_snippets_flight__armed": True},
        buttons={"clean_stale_snippets_flight__confirm": True},
    )
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    env = SimpleNamespace(runenv=runenv_dir, app_settings_file=app_settings, app="flight")
    deps = SimpleNamespace(
        ensure_safe_service_template=lambda *_args, **_kwargs: None,
        safe_service_template_filename="unused.py",
        safe_service_template_marker="marker",
    )

    option_map = pipeline_lab.get_existing_snippets(env, steps_file, deps)

    assert option_map == {}
    assert not stale_snippet.exists()
    assert any(kind == "success" and "Deleted 1 stale" in message for kind, message in fake_st.messages)


def test_get_existing_snippets_handles_candidate_path_edge_cases(monkeypatch, tmp_path):
    steps_file = tmp_path / "lab_steps.toml"
    steps_file.write_text("", encoding="utf-8")

    snippet_dir = tmp_path / "snippets"
    snippet_dir.mkdir()

    class _BrokenCandidate:
        suffix = ".py"

        def __init__(self, path: Path):
            self._path = path
            self.name = path.name
            self.parent = path.parent

        def expanduser(self):
            raise RuntimeError("boom")

        def exists(self):
            return True

        def is_file(self):
            return True

        def resolve(self):
            raise OSError("resolve failed")

        def __str__(self):
            return str(self._path)

    snippet = snippet_dir / "AGI_run.py"
    snippet.write_text("print('ok')\n", encoding="utf-8")
    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(pipeline_lab, "st", fake_st)

    env = SimpleNamespace(runenv=None, app_settings_file=tmp_path / "missing.toml", app="flight")
    deps = SimpleNamespace(
        ensure_safe_service_template=lambda *_args, **_kwargs: _BrokenCandidate(snippet),
        safe_service_template_filename="unused.py",
        safe_service_template_marker="marker",
    )

    option_map = pipeline_lab.get_existing_snippets(env, steps_file, deps)

    assert list(option_map.keys()) == ["AGI_run.py"]
    assert str(option_map["AGI_run.py"]) == str(snippet)


def test_get_existing_snippets_disambiguates_multiple_duplicate_labels(monkeypatch, tmp_path):
    steps_file = tmp_path / "lab_steps.toml"
    steps_file.write_text("", encoding="utf-8")
    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(pipeline_lab, "st", fake_st)

    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_c = tmp_path / "c"
    root_a.mkdir()
    root_b.mkdir()
    root_c.mkdir()
    for root in (root_a, root_b, root_c):
        (root / "AGI_run.py").write_text(f"print('{root.name}')\n", encoding="utf-8")

    env = SimpleNamespace(runenv=None, app_settings_file=tmp_path / "missing.toml", app="flight")
    safe_templates = iter([root_b / "AGI_run.py"])
    deps = SimpleNamespace(
        ensure_safe_service_template=lambda *_args, **_kwargs: next(safe_templates),
        safe_service_template_filename="unused.py",
        safe_service_template_marker="marker",
    )

    monkeypatch.setitem(fake_st.session_state, "snippet_file", str(root_c / "AGI_run.py"))
    option_map = pipeline_lab.get_existing_snippets(env, root_a / "lab_steps.toml", deps)

    assert list(option_map.keys()) == [
        "AGI_run.py",
        "AGI_run.py (b)",
        "AGI_run.py (c)",
    ]


def test_get_existing_snippets_skips_exact_duplicate_paths(monkeypatch, tmp_path):
    steps_file = tmp_path / "lab_steps.toml"
    steps_file.write_text("", encoding="utf-8")
    snippet = tmp_path / "AGI_run.py"
    snippet.write_text("print('same')\n", encoding="utf-8")

    fake_st = SimpleNamespace(session_state={"snippet_file": str(snippet)})
    monkeypatch.setattr(pipeline_lab, "st", fake_st)

    env = SimpleNamespace(runenv=None, app_settings_file=tmp_path / "missing.toml", app="flight")
    deps = SimpleNamespace(
        ensure_safe_service_template=lambda *_args, **_kwargs: snippet,
        safe_service_template_filename="unused.py",
        safe_service_template_marker="marker",
    )

    option_map = pipeline_lab.get_existing_snippets(env, steps_file, deps)

    assert option_map == {"AGI_run.py": snippet}


def test_get_existing_snippets_uses_incremented_label_for_same_parent_names(monkeypatch, tmp_path):
    steps_file = tmp_path / "lab_steps.toml"
    steps_file.write_text("", encoding="utf-8")

    shared_left = tmp_path / "left" / "common"
    shared_right = tmp_path / "right" / "common"
    shared_left.mkdir(parents=True)
    shared_right.mkdir(parents=True)
    (shared_left / "AGI_run.py").write_text("print('left')\n", encoding="utf-8")
    (shared_right / "AGI_run.py").write_text("print('right')\n", encoding="utf-8")
    run_script = tmp_path / "AGI_run.py"
    run_script.write_text("print('root')\n", encoding="utf-8")

    fake_st = SimpleNamespace(session_state={"snippet_file": str(shared_left / "AGI_run.py")})
    monkeypatch.setattr(pipeline_lab, "st", fake_st)

    env = SimpleNamespace(runenv=None, app_settings_file=tmp_path / "missing.toml", app="flight")
    deps = SimpleNamespace(
        ensure_safe_service_template=lambda *_args, **_kwargs: shared_right / "AGI_run.py",
        safe_service_template_filename="unused.py",
        safe_service_template_marker="marker",
    )

    option_map = pipeline_lab.get_existing_snippets(env, steps_file, deps)

    assert list(option_map.keys()) == [
        "AGI_run.py",
        "AGI_run.py (common)",
        "AGI_run.py (common #2)",
    ]


def test_get_existing_snippets_skips_runenv_files_with_unstatable_mtime(monkeypatch, tmp_path):
    steps_file = tmp_path / "lab_steps.toml"
    steps_file.write_text("", encoding="utf-8")
    runenv_dir = tmp_path / "runenv"
    runenv_dir.mkdir()
    bad_run = runenv_dir / "AGI_run_flight.py"
    bad_run.write_text("print('bad')\n", encoding="utf-8")

    app_settings = tmp_path / "app_settings.toml"
    app_settings.write_text("x=1\n", encoding="utf-8")
    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(pipeline_lab, "st", fake_st)

    original_stat = Path.stat

    def _patched_stat(self, *args, **kwargs):
        if self == bad_run:
            raise OSError("stat failed")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", _patched_stat)

    env = SimpleNamespace(runenv=runenv_dir, app_settings_file=app_settings, app="flight")
    deps = SimpleNamespace(
        ensure_safe_service_template=lambda *_args, **_kwargs: None,
        safe_service_template_filename="unused.py",
        safe_service_template_marker="marker",
    )

    assert pipeline_lab.get_existing_snippets(env, steps_file, deps) == {}


def test_get_existing_snippets_ignores_runenv_glob_errors(monkeypatch, tmp_path):
    steps_file = tmp_path / "lab_steps.toml"
    steps_file.write_text("", encoding="utf-8")
    runenv_dir = tmp_path / "runenv"
    runenv_dir.mkdir()
    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(pipeline_lab, "st", fake_st)

    original_glob = Path.glob

    def _patched_glob(self, pattern, *args, **kwargs):
        if self == runenv_dir:
            raise OSError("glob failed")
        return original_glob(self, pattern, *args, **kwargs)

    monkeypatch.setattr(Path, "glob", _patched_glob)

    env = SimpleNamespace(runenv=runenv_dir, app_settings_file=tmp_path / "missing.toml", app="flight")
    deps = SimpleNamespace(
        ensure_safe_service_template=lambda *_args, **_kwargs: None,
        safe_service_template_filename="unused.py",
        safe_service_template_marker="marker",
    )

    assert pipeline_lab.get_existing_snippets(env, steps_file, deps) == {}


def test_pipeline_lab_import_falls_back_when_pipeline_modules_are_unavailable():
    fallback = _load_pipeline_lab_with_missing("agilab.pipeline_steps", "agilab.pipeline_runtime")

    assert callable(fallback.get_existing_snippets)
    assert callable(fallback.display_lab_tab)
    assert fallback.ORCHESTRATE_LOCKED_STEP_KEY == pipeline_lab.ORCHESTRATE_LOCKED_STEP_KEY


def test_pipeline_lab_import_falls_back_when_code_editor_support_is_unavailable():
    fallback = _load_pipeline_lab_with_missing("agilab.code_editor_support")

    assert fallback.normalize_custom_buttons([{"name": "Run"}]) == [{"name": "Run"}]
    assert fallback.normalize_custom_buttons({"buttons": [{"name": "Run"}]}) == [{"name": "Run"}]


def test_pipeline_lab_import_fallback_raises_when_code_editor_support_local_spec_is_missing(monkeypatch):
    original_spec = importlib.util.spec_from_file_location

    def _fake_spec(name, location, *args, **kwargs):
        if name == "agilab_code_editor_support_fallback":
            return None
        return original_spec(name, location, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "spec_from_file_location", _fake_spec)

    with pytest.raises(ModuleNotFoundError, match="code_editor_support"):
        _load_pipeline_lab_with_missing("agilab.code_editor_support")


def test_pipeline_lab_import_fallback_raises_when_pipeline_steps_local_spec_is_missing(monkeypatch):
    original_spec = importlib.util.spec_from_file_location

    def _fake_spec(name, location, *args, **kwargs):
        if name == "agilab_pipeline_steps_fallback":
            return None
        return original_spec(name, location, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "spec_from_file_location", _fake_spec)

    with pytest.raises(ModuleNotFoundError, match="pipeline_steps"):
        _load_pipeline_lab_with_missing("agilab.pipeline_steps", "agilab.pipeline_runtime")


def test_pipeline_lab_import_fallback_raises_when_pipeline_runtime_local_spec_is_missing(monkeypatch):
    original_spec = importlib.util.spec_from_file_location

    def _fake_spec(name, location, *args, **kwargs):
        if name == "agilab_pipeline_runtime_fallback":
            return None
        return original_spec(name, location, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "spec_from_file_location", _fake_spec)

    with pytest.raises(ModuleNotFoundError, match="pipeline_runtime"):
        _load_pipeline_lab_with_missing("agilab.pipeline_steps", "agilab.pipeline_runtime")


def test_pipeline_lab_helper_functions_cover_editor_text_and_engine_defaults():
    assert pipeline_lab._normalize_editor_text(None) == ""
    assert pipeline_lab._normalize_editor_text("   ") == ""
    assert pipeline_lab._normalize_editor_text("print('ok')") == "print('ok')"

    assert pipeline_lab._resolve_step_engine("", "", "") == "runpy"
    assert pipeline_lab._resolve_step_engine("", "", "/tmp/runtime") == "agi.run"
    assert pipeline_lab._resolve_step_engine("agi.run", "runpy", "") == "agi.run"
    assert pipeline_lab._resolve_step_engine("", "runpy", "") == "runpy"


def test_global_runner_panel_uses_flight_two_app_dag_and_persists_state(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit()
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    env = SimpleNamespace(app="flight_project", target="flight_project")

    pipeline_lab._render_global_runner_state_panel(env, tmp_path, "demo")

    state_path = tmp_path / ".agilab" / "runner_state.json"
    assert state_path.is_file()
    state = pipeline_lab.load_runner_state(state_path)
    assert state["source"]["dag_path"] == "docs/source/data/multi_app_dag_flight_sample.json"
    assert state["summary"]["runnable_unit_ids"] == ["flight_context"]
    assert state["summary"]["blocked_unit_ids"] == ["meteo_forecast_review"]
    assert ("expander", "True") in fake_st.messages
    assert ("metric", "Stages=2") in fake_st.messages
    assert ("metric", "Dependencies=1") in fake_st.messages
    assert (
        "caption",
        "Next action: Dispatch `flight_context`.",
    ) in fake_st.messages
    assert ("dataframe", "2") in fake_st.messages


def test_global_runner_readiness_summary_prioritizes_running_and_scope():
    summary = pipeline_lab._global_dag_readiness_summary(
        {
            "summary": {
                "unit_count": 3,
                "runnable_unit_ids": ["beta"],
                "blocked_unit_ids": ["gamma"],
                "running_unit_ids": ["alpha"],
                "completed_unit_ids": [],
                "failed_unit_ids": [],
            },
            "provenance": {"real_app_execution": True},
            "units": [
                {
                    "id": "gamma",
                    "dispatch_status": "blocked",
                    "artifact_dependencies": [{"artifact": "alpha_metrics"}],
                    "operator_ui": {"blocked_by_artifacts": ["alpha_metrics"]},
                }
            ],
        }
    )

    assert summary["stage_count"] == 3
    assert summary["dependency_count"] == 1
    assert summary["next_action"] == "Monitor running stage `alpha`."
    assert summary["execution_scope"] == "live app execution"


def test_global_runner_readiness_summary_describes_blocked_artifact():
    summary = pipeline_lab._global_dag_readiness_summary(
        {
            "summary": {
                "unit_count": 1,
                "runnable_unit_ids": [],
                "blocked_unit_ids": ["consumer"],
                "running_unit_ids": [],
                "completed_unit_ids": [],
                "failed_unit_ids": [],
            },
            "units": [
                {
                    "id": "consumer",
                    "dispatch_status": "blocked",
                    "artifact_dependencies": [{"artifact": "producer_metrics"}],
                    "operator_ui": {"blocked_by_artifacts": ["producer_metrics"]},
                }
            ],
        }
    )

    assert summary["next_action"] == "Wait for `consumer` until `producer_metrics` is available."
    assert summary["execution_scope"] == "preview dispatch, no app execution claimed"


def test_global_runner_panel_dispatch_button_marks_next_unit_running(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit(buttons={"demo_global_runner_dispatch_next": True})
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    env = SimpleNamespace(app="flight_project", target="flight_project")

    pipeline_lab._render_global_runner_state_panel(env, tmp_path, "demo")

    state = pipeline_lab.load_runner_state(tmp_path / ".agilab" / "runner_state.json")
    assert state["run_status"] == "running"
    assert state["summary"]["running_unit_ids"] == ["flight_context"]
    assert state["summary"]["blocked_unit_ids"] == ["meteo_forecast_review"]
    assert any(kind == "success" and "flight_context" in message for kind, message in fake_st.messages)
    assert ("rerun", "called") in fake_st.messages


def test_global_runner_panel_real_run_executes_controlled_queue_stage(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit(buttons={"demo_global_runner_run_next_stage": True})
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    calls: list[Path] = []

    def _fake_queue_run(*, repo_root: Path, run_root: Path) -> dict[str, object]:
        calls.append(run_root)
        run_root.mkdir(parents=True, exist_ok=True)
        return {
            "summary_metrics_path": "queue/summary.json",
            "reduce_artifact_path": "queue/reduce.json",
            "summary_metrics": {"packets_generated": 8, "packets_delivered": 7},
        }

    monkeypatch.setattr(pipeline_lab, "run_global_dag_queue_baseline_app", _fake_queue_run)
    env = SimpleNamespace(app="uav_queue_project", target="uav_queue_project")

    pipeline_lab._render_global_runner_state_panel(env, tmp_path, "demo")

    state = pipeline_lab.load_runner_state(tmp_path / ".agilab" / "runner_state.json")
    assert calls == [tmp_path / ".agilab" / "global_dag_real_runs" / "queue_baseline"]
    assert state["summary"]["completed_unit_ids"] == ["queue_baseline"]
    assert state["summary"]["runnable_unit_ids"] == ["relay_followup"]
    assert state["summary"]["available_artifact_ids"] == ["queue_metrics", "queue_reduce_summary"]
    assert state["summary"]["real_executed_unit_ids"] == ["queue_baseline"]
    assert state["provenance"]["real_app_execution"] is True
    assert state["provenance"]["real_execution_scope"] == "controlled_uav_queue_to_relay_stage"
    queue = next(unit for unit in state["units"] if unit["id"] == "queue_baseline")
    relay = next(unit for unit in state["units"] if unit["id"] == "relay_followup")
    assert queue["dispatch_status"] == "completed"
    assert queue["execution_mode"] == "real_app_entry"
    assert queue["real_execution"]["summary_metrics"]["packets_delivered"] == 7
    assert queue["produces"] == [
        {"artifact": "queue_metrics", "kind": "summary_metrics", "path": "queue/summary.json"}
    ]
    assert relay["dispatch_status"] == "runnable"
    assert relay["unblocked_by"] == ["queue_metrics"]
    assert any(kind == "success" and "queue_baseline" in message for kind, message in fake_st.messages)
    assert ("rerun", "called") in fake_st.messages


def test_global_runner_panel_real_run_executes_controlled_relay_stage(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit(buttons={"demo_global_runner_run_next_stage": True})
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    state_path = tmp_path / ".agilab" / "runner_state.json"
    proof = pipeline_lab.persist_runner_state(
        repo_root=Path.cwd(),
        output_path=state_path,
        dag_path=Path("docs/source/data/multi_app_dag_sample.json"),
    )
    state = pipeline_lab._run_next_controlled_global_dag_stage(
        proof.runner_state,
        repo_root=Path.cwd(),
        dag_path=Path.cwd() / "docs/source/data/multi_app_dag_sample.json",
        lab_dir=tmp_path,
        run_queue_fn=lambda **_kwargs: {
            "summary_metrics_path": "queue/summary.json",
            "reduce_artifact_path": "queue/reduce.json",
            "summary_metrics": {"packets_generated": 8, "packets_delivered": 7},
        },
        now_fn=lambda: "2026-05-07T00:00:00Z",
    ).state
    pipeline_lab.write_runner_state(state_path, state)
    relay_calls: list[dict[str, object]] = []

    def _fake_relay_run(*, repo_root: Path, run_root: Path, queue_result: dict[str, object]) -> dict[str, object]:
        relay_calls.append({"run_root": run_root, "queue_result": queue_result})
        return {
            "summary_metrics_path": "relay/summary.json",
            "reduce_artifact_path": "relay/reduce.json",
            "summary_metrics": {"packets_generated": 5, "packets_delivered": 5},
            "consumed_artifacts": [
                {
                    "artifact": "queue_metrics",
                    "path": str(queue_result.get("summary_metrics_path", "")),
                    "producer": "queue_baseline",
                }
            ],
        }

    monkeypatch.setattr(pipeline_lab, "run_global_dag_relay_followup_app", _fake_relay_run)
    env = SimpleNamespace(app="uav_queue_project", target="uav_queue_project")

    pipeline_lab._render_global_runner_state_panel(env, tmp_path, "demo")

    state = pipeline_lab.load_runner_state(state_path)
    assert relay_calls == [
        {
            "run_root": tmp_path / ".agilab" / "global_dag_real_runs" / "relay_followup",
            "queue_result": state["units"][0]["real_execution"],
        }
    ]
    assert state["run_status"] == "completed"
    assert state["summary"]["completed_unit_ids"] == ["queue_baseline", "relay_followup"]
    assert state["summary"]["real_executed_unit_ids"] == ["queue_baseline", "relay_followup"]
    assert set(state["summary"]["available_artifact_ids"]) == {
        "queue_metrics",
        "queue_reduce_summary",
        "relay_metrics",
        "relay_reduce_summary",
    }
    relay = next(unit for unit in state["units"] if unit["id"] == "relay_followup")
    assert relay["dispatch_status"] == "completed"
    assert relay["real_execution"]["consumed_artifacts"][0]["path"] == "queue/summary.json"


def test_global_runner_panel_keeps_unsupported_dag_preview_only(monkeypatch, tmp_path):
    selected = "docs/source/data/multi_app_dag_flight_sample.json"
    fake_st = _FakeStreamlit({"demo_global_runner_library": selected})
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    env = SimpleNamespace(app="flight_project", target="flight_project")

    pipeline_lab._render_global_runner_state_panel(env, tmp_path, "demo")

    assert all(call[0] != "demo_global_runner_run_next_stage" for call in fake_st.button_calls)
    assert any("other DAGs stay preview-only" in message for kind, message in fake_st.messages if kind == "caption")


def test_global_runner_panel_selects_workspace_draft_as_preview_only(monkeypatch, tmp_path):
    draft_dir = tmp_path / ".agilab" / "global_dags"
    draft_dir.mkdir(parents=True)
    draft_path = draft_dir / "workspace-dag.json"
    sample_text = Path("docs/source/data/multi_app_dag_sample.json").read_text(encoding="utf-8")
    draft_path.write_text(sample_text, encoding="utf-8")
    fake_st = _FakeStreamlit(
        selectboxes={
            "demo_global_runner_source": pipeline_lab.GLOBAL_DAG_SOURCE_WORKSPACE,
            "demo_global_runner_workspace_dag": str(draft_path),
        }
    )
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    env = SimpleNamespace(app="uav_queue_project", target="uav_queue_project")

    pipeline_lab._render_global_runner_state_panel(env, tmp_path, "demo")

    assert fake_st.session_state["demo_global_runner_source"] == pipeline_lab.GLOBAL_DAG_SOURCE_WORKSPACE
    assert fake_st.session_state["demo_global_runner_workspace_dag"] == str(draft_path)
    assert all(call[0] != "demo_global_runner_run_next_stage" for call in fake_st.button_calls)
    assert any("other DAGs stay preview-only" in message for kind, message in fake_st.messages if kind == "caption")


def test_global_dag_execution_history_rows_skip_planning_and_sort_latest_first():
    rows = pipeline_lab._global_dag_execution_history_rows(
        {
            "events": [
                {
                    "timestamp": "2026-05-07T00:00:00Z",
                    "kind": "run_planned",
                    "unit_id": "",
                    "from_status": "",
                    "to_status": "planned",
                    "detail": "created",
                },
                {
                    "timestamp": "2026-05-07T00:01:00Z",
                    "kind": "unit_dispatched",
                    "unit_id": "queue_baseline",
                    "from_status": "runnable",
                    "to_status": "running",
                    "detail": "preview",
                },
                {
                    "timestamp": "2026-05-07T00:02:00Z",
                    "kind": "unit_completed",
                    "unit_id": "queue_baseline",
                    "from_status": "running",
                    "to_status": "completed",
                    "detail": "real run",
                },
            ]
        }
    )

    assert [row["Event"] for row in rows] == ["unit completed", "unit dispatched"]
    assert rows[0]["Stage"] == "queue_baseline"
    assert rows[0]["Status"] == "running -> completed"


def test_global_runner_panel_recreates_state_when_selected_dag_changes(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit(
        {
            "demo_global_runner_dag_path": "docs/source/data/multi_app_dag_sample.json",
        },
        selectboxes={"demo_global_runner_source": pipeline_lab.GLOBAL_DAG_SOURCE_CUSTOM},
    )
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    env = SimpleNamespace(app="flight_project", target="flight_project")

    state_path = tmp_path / ".agilab" / "runner_state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "source": {"dag_path": "docs/source/data/multi_app_dag_flight_sample.json"},
                "summary": {},
                "units": [],
            }
        ),
        encoding="utf-8",
    )

    pipeline_lab._render_global_runner_state_panel(env, tmp_path, "demo")

    state = pipeline_lab.load_runner_state(state_path)
    assert state["source"]["dag_path"] == "docs/source/data/multi_app_dag_sample.json"
    assert state["summary"]["runnable_unit_ids"] == ["queue_baseline"]
    assert state["summary"]["blocked_unit_ids"] == ["relay_followup"]
    assert fake_st.graphviz_sources
    assert "queue_baseline" in fake_st.graphviz_sources[-1]
    assert "artifact:queue_metrics" in fake_st.graphviz_sources[-1]


def test_global_runner_panel_reset_rebuilds_matching_runner_state(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit(buttons={"demo_global_runner_reset": True})
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    env = SimpleNamespace(app="flight_project", target="flight_project")

    state_path = tmp_path / ".agilab" / "runner_state.json"
    proof = pipeline_lab.persist_runner_state(
        repo_root=Path.cwd(),
        output_path=state_path,
        dag_path=Path("docs/source/data/multi_app_dag_flight_sample.json"),
    )
    dispatched = pipeline_lab.dispatch_next_runnable(proof.runner_state)
    pipeline_lab.write_runner_state(state_path, dispatched.state)

    pipeline_lab._render_global_runner_state_panel(env, tmp_path, "demo")

    state = pipeline_lab.load_runner_state(state_path)
    assert state["run_status"] == "planned"
    assert state["summary"]["runnable_unit_ids"] == ["flight_context"]
    assert state["summary"]["running_unit_ids"] == []


def test_global_runner_panel_saves_visual_editor_as_workspace_draft(monkeypatch, tmp_path):
    selected = "docs/source/data/multi_app_dag_flight_sample.json"
    token = pipeline_lab._global_dag_source_token(selected)
    fake_st = _FakeStreamlit(
        {
            "demo_global_runner_library": selected,
            "demo_global_runner_dag_path": "",
            f"demo_global_runner_dag_id_{token}": "flight-dag-edited",
            f"demo_global_runner_label_{token}": "Edited flight DAG",
        },
        buttons={"demo_global_runner_save_draft": True},
    )
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    env = SimpleNamespace(app="flight_project", target="flight_project")

    pipeline_lab._render_global_runner_state_panel(env, tmp_path, "demo")

    draft_path = tmp_path / ".agilab" / "global_dags" / "flight-dag-edited.json"
    assert draft_path.is_file()
    state = pipeline_lab.load_runner_state(tmp_path / ".agilab" / "runner_state.json")
    assert state["source"]["dag_path"] == str(draft_path)
    assert state["summary"]["runnable_unit_ids"] == ["flight_context"]
    assert any(kind == "success" and "Saved DAG draft" in message for kind, message in fake_st.messages)
    assert "Edit DAG JSON draft" not in fake_st.text_area_labels
    assert any(label == "Stages" for label, _options, _key in fake_st.multiselect_calls)
    assert any(
        label == "Produced artifacts" and key == f"demo_global_runner_produces_{token}"
        for label, _options, key in fake_st.multiselect_calls
    )
    assert any(
        label == "Stage connections" and key == f"demo_global_runner_edges_{token}"
        for label, _options, key in fake_st.multiselect_calls
    )
    assert not fake_st.data_editor_calls


def test_global_runner_panel_reports_invalid_visual_editor_as_code(monkeypatch, tmp_path):
    selected = "docs/source/data/multi_app_dag_flight_sample.json"
    token = pipeline_lab._global_dag_source_token(selected)
    fake_st = _FakeStreamlit(
        {
            "demo_global_runner_library": selected,
            "demo_global_runner_dag_path": "",
            f"demo_global_runner_dag_id_{token}": "",
        },
        buttons={"demo_global_runner_validate": True},
    )
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    env = SimpleNamespace(app="flight_project", target="flight_project")

    pipeline_lab._render_global_runner_state_panel(env, tmp_path, "demo")

    assert ("error", "DAG draft is not valid.") in fake_st.messages
    assert ("caption", "Validation details") in fake_st.messages
    assert any(kind == "code" and "dag_id is required" in message for kind, message in fake_st.messages)
    assert not (tmp_path / ".agilab" / "global_dags").exists()
    assert "Edit DAG JSON draft" not in fake_st.text_area_labels


def test_global_runner_artifact_handoffs_mark_available_and_missing():
    rows = pipeline_lab._artifact_handoffs_for_display(
        {
            "artifacts": [{"artifact": "ready_metrics", "status": "available"}],
            "units": [
                {
                    "id": "consumer",
                    "app": "downstream_project",
                    "artifact_dependencies": [
                        {
                            "artifact": "ready_metrics",
                            "from": "producer",
                            "from_app": "upstream_project",
                            "source_path": "analysis/ready.json",
                            "handoff": "Use validated metrics.",
                        },
                        {
                            "artifact": "missing_metrics",
                            "from": "producer",
                            "from_app": "upstream_project",
                            "source_path": "analysis/missing.json",
                            "handoff": "Use later metrics.",
                        },
                    ],
                }
            ],
        }
    )

    assert [row["status"] for row in rows] == ["available", "missing"]
    assert rows[0]["from_app"] == "upstream_project"
    assert rows[1]["to"] == "consumer"


def test_global_runner_error_diagnostic_renders_as_code(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit()
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    monkeypatch.setattr(
        pipeline_lab,
        "_load_or_create_global_runner_state",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad dag\nline 2")),
    )
    env = SimpleNamespace(app="flight_project", target="flight_project")

    pipeline_lab._render_global_runner_state_panel(env, tmp_path, "demo")

    assert ("error", "Multi-app DAG orchestration preview is unavailable.") in fake_st.messages
    assert ("caption", "Full diagnostic") in fake_st.messages
    assert ("code", "bad dag\nline 2") in fake_st.messages


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


def test_display_lab_tab_recovers_steps_from_toml_when_loader_returns_empty(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo_run_sequence_widget": [0],
        },
        multiselects={"demo_run_sequence_widget": [0]},
    )
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    monkeypatch.setattr(
        pipeline_lab,
        "code_editor",
        lambda body, **_kwargs: fake_st.messages.append(("code", str(body))),
    )
    monkeypatch.setattr(pipeline_lab, "get_custom_buttons", lambda: [])
    monkeypatch.setattr(pipeline_lab, "get_info_bar", lambda: {})
    monkeypatch.setattr(pipeline_lab, "get_css_text", lambda: {})
    monkeypatch.setattr(pipeline_lab, "get_available_virtualenvs", lambda _env: [])
    monkeypatch.setattr(pipeline_lab, "normalize_runtime_path", lambda raw: str(raw) if raw else "")
    monkeypatch.setattr(pipeline_lab, "_is_valid_runtime_root", lambda raw: bool(raw))
    monkeypatch.setattr(pipeline_lab, "get_existing_snippets", lambda *_args, **_kwargs: {})

    module_path = tmp_path / "flight_project"
    module_key = pipeline_lab._module_keys(module_path)[0]
    steps_file = tmp_path / "lab_steps.toml"
    steps_file.write_text(
        f'"{module_key}" = [{{Q = "fallback", M = "demo", C = "print(\\"ok\\")", D = "", E = ""}}]\n',
        encoding="utf-8",
    )

    env = SimpleNamespace(active_app=module_path, envars={}, app="flight_project")
    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
    )

    pipeline_lab.display_lab_tab(tmp_path, "demo", steps_file, module_path, env, deps)

    assert fake_st.session_state["demo"][-1] == 1
    assert fake_st.session_state["demo__run_sequence"] == [0]


def test_display_lab_tab_empty_pipeline_warns_when_first_snippet_cannot_be_read(monkeypatch, tmp_path):
    snippet_path = tmp_path / "AGI_run_demo.py"
    snippet_path.write_text("print('snippet')\n", encoding="utf-8")

    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo_new_step_source": snippet_path.name,
        },
        selectboxes={"demo_new_step_source": snippet_path.name},
    )
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    monkeypatch.setattr(pipeline_lab, "get_available_virtualenvs", lambda _env: [])
    monkeypatch.setattr(pipeline_lab, "normalize_runtime_path", lambda raw: str(raw) if raw else "")

    original_read_text = Path.read_text

    def _patched_read_text(self, *args, **kwargs):
        if self == snippet_path:
            raise OSError("cannot read")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _patched_read_text)

    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")
    deps = _make_lab_deps(
        ensure_safe_service_template=lambda *_args, **_kwargs: snippet_path,
    )

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert any(
        level == "warning" and "Unable to read snippet" in message
        for level, message in fake_st.messages
    )


def test_display_lab_tab_empty_pipeline_hides_stale_hf_snippet_runtime(monkeypatch, tmp_path):
    stale_runtime = "/app/src/agilab/apps/builtin/flight_project"
    snippet_path = tmp_path / "AGI_run_demo.py"
    snippet_path.write_text("print('snippet')\n", encoding="utf-8")

    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo_new_step_source": snippet_path.name,
        },
        selectboxes={"demo_new_step_source": snippet_path.name},
    )
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    monkeypatch.setattr(pipeline_lab, "get_available_virtualenvs", lambda _env: [stale_runtime])
    monkeypatch.setattr(pipeline_lab, "normalize_runtime_path", lambda raw: str(raw) if raw else "")
    monkeypatch.setattr(
        pipeline_lab,
        "_is_valid_runtime_root",
        lambda raw: bool(raw) and not str(raw).startswith("/app/"),
    )
    monkeypatch.setattr(pipeline_lab, "get_existing_snippets", lambda *_args, **_kwargs: {snippet_path.name: snippet_path})

    env = SimpleNamespace(active_app=stale_runtime, envars={}, app="flight_project")
    deps = _make_lab_deps()

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert fake_st.session_state["demo_first_snippet_venv_ro"] == "Use AGILAB environment"


def test_display_lab_tab_existing_step_prunes_invalid_runtime_selection(monkeypatch, tmp_path):
    valid_runtime = tmp_path / "flight_project"
    valid_runtime.mkdir()
    invalid_runtime = tmp_path / "exported_notebooks" / "lab_steps.ipynb"
    invalid_runtime.parent.mkdir()
    invalid_runtime.write_text("{}", encoding="utf-8")
    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo__run_sequence": [0],
            "demo__venv_map": {0: str(invalid_runtime)},
            "demo_venv_0": str(invalid_runtime),
            "demo_step_init_0": True,
        },
        multiselects={"demo_run_sequence_widget": [0]},
    )
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    monkeypatch.setattr(pipeline_lab, "code_editor", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline_lab, "get_custom_buttons", lambda: [])
    monkeypatch.setattr(pipeline_lab, "get_info_bar", lambda: {})
    monkeypatch.setattr(pipeline_lab, "get_css_text", lambda: {})
    monkeypatch.setattr(pipeline_lab, "get_available_virtualenvs", lambda _env: [valid_runtime, invalid_runtime])
    monkeypatch.setattr(pipeline_lab, "normalize_runtime_path", lambda raw: str(raw) if raw else "")
    monkeypatch.setattr(pipeline_lab, "_is_valid_runtime_root", lambda raw: str(raw) == str(valid_runtime))
    monkeypatch.setattr(pipeline_lab, "get_existing_snippets", lambda *_args, **_kwargs: {})

    env = SimpleNamespace(active_app=valid_runtime, envars={}, app="flight_project")
    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [
            {"D": "", "Q": "q", "M": "m", "C": "print('seed')", "E": str(invalid_runtime)}
        ],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
    )

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", valid_runtime, env, deps)

    assert fake_st.session_state["demo__venv_map"] == {}
    assert fake_st.session_state["demo_venv_0"] == "Use AGILAB environment"


def test_display_lab_tab_empty_pipeline_warns_when_first_snippet_is_empty(monkeypatch, tmp_path):
    snippet_path = tmp_path / "AGI_run_demo.py"
    snippet_path.write_text("", encoding="utf-8")

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

    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")
    deps = _make_lab_deps(
        ensure_safe_service_template=lambda *_args, **_kwargs: snippet_path,
    )

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert ("warning", "Selected snippet is empty.") in fake_st.messages


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


def test_display_lab_tab_renders_assistant_engine_next_to_first_prompt(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit({"demo": [0, "", "", "", "", "", 0]})
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    monkeypatch.setattr(pipeline_lab, "get_available_virtualenvs", lambda _env: [])
    monkeypatch.setattr(pipeline_lab, "normalize_runtime_path", lambda raw: str(raw) if raw else "")

    calls: list[object] = []
    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")
    deps = _make_lab_deps(
        configure_assistant_engine=lambda _env, *, container=None: calls.append(container),
    )

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert calls == [fake_st]
    assert "Ask code generator:" in fake_st.text_area_labels


def test_display_lab_tab_empty_pipeline_generates_first_step_with_runtime(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime_a"
    (runtime_root / ".venv").mkdir(parents=True)
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
    monkeypatch.setattr(pipeline_lab, "_is_valid_runtime_root", lambda raw: str(raw) == str(runtime_root))

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


def test_display_lab_tab_existing_step_defaults_to_runpy_without_runtime(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo__run_sequence": [0],
        },
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
    monkeypatch.setattr(pipeline_lab, "get_existing_snippets", lambda *_args, **_kwargs: {})

    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")
    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [
            {"D": "", "Q": "alpha", "M": "m", "C": "print('a')", "E": "", "R": ""}
        ],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
    )

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert fake_st.session_state["demo__engine_map"][0] == "runpy"


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
    (runtime_root / ".venv").mkdir(parents=True)
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


def test_display_lab_tab_existing_steps_drops_stale_hf_runtime_selection(monkeypatch, tmp_path):
    stale_runtime = "/app/src/agilab/apps/builtin/flight_project"
    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo__run_sequence": [0],
            "demo__venv_map": {0: stale_runtime},
            "demo_venv_0": stale_runtime,
        },
        multiselects={"demo_run_sequence_widget": [0]},
    )
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    monkeypatch.setattr(pipeline_lab, "code_editor", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline_lab, "get_custom_buttons", lambda: [])
    monkeypatch.setattr(pipeline_lab, "get_info_bar", lambda: {})
    monkeypatch.setattr(pipeline_lab, "get_css_text", lambda: {})
    monkeypatch.setattr(pipeline_lab, "get_available_virtualenvs", lambda _env: [stale_runtime])
    monkeypatch.setattr(pipeline_lab, "normalize_runtime_path", lambda raw: str(raw) if raw else "")
    monkeypatch.setattr(
        pipeline_lab,
        "_is_valid_runtime_root",
        lambda raw: bool(raw) and not str(raw).startswith("/app/"),
    )
    monkeypatch.setattr(pipeline_lab, "get_existing_snippets", lambda *_args, **_kwargs: {})

    env = SimpleNamespace(active_app=stale_runtime, envars={}, app="flight_project")
    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [
            {"D": "", "Q": "alpha", "M": "m", "C": "print('a')", "E": stale_runtime, "R": "agi.run"},
        ],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
    )

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert fake_st.session_state["demo__venv_map"] == {}
    assert fake_st.session_state["demo_venv_0"] == "Use AGILAB environment"


def test_display_lab_tab_renders_from_page_state_visible_steps(monkeypatch, tmp_path):
    render_calls = []
    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo__run_sequence": [0, 1],
        }
    )
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    monkeypatch.setattr(pipeline_lab, "code_editor", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline_lab, "get_custom_buttons", lambda: [])
    monkeypatch.setattr(pipeline_lab, "get_info_bar", lambda: {})
    monkeypatch.setattr(pipeline_lab, "get_css_text", lambda: {})
    monkeypatch.setattr(pipeline_lab, "get_available_virtualenvs", lambda _env: [])
    monkeypatch.setattr(pipeline_lab, "normalize_runtime_path", lambda raw: str(raw) if raw else "")
    monkeypatch.setattr(pipeline_lab, "_is_valid_runtime_root", lambda raw: bool(raw))
    monkeypatch.setattr(pipeline_lab, "get_existing_snippets", lambda *_args, **_kwargs: {})

    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")
    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [
            {"D": "", "Q": "", "M": "", "C": "", "E": ""},
            {"D": "", "Q": "visible", "M": "m", "C": "print('visible')", "E": ""},
        ],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *args, **kwargs: render_calls.append((args, kwargs)),
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
    )

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    rendered_steps = render_calls[-1][0][0]
    assert [step["Q"] for step in rendered_steps] == ["visible"]
    assert fake_st.session_state["demo__run_sequence"] == [1]
    assert fake_st.session_state["demo_run_sequence_widget"] == [1]
    assert 1 in fake_st.session_state["demo__engine_map"]
    assert 0 not in fake_st.session_state["demo__engine_map"]


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
    finish_calls = []
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

    def _finish_pipeline_run_command(*, session_state, index_page, succeeded, message=None):
        finish_calls.append((index_page, succeeded, message))
        session_state[f"{index_page}__last_run_status"] = "complete" if succeeded else "failed"
        return pipeline_lab._pipeline_page_state_module.PipelineCommandResult(
            status=(
                pipeline_lab._pipeline_page_state_module.PipelineCommandStatus.SUCCESS
                if succeeded
                else pipeline_lab._pipeline_page_state_module.PipelineCommandStatus.FAILED
            ),
            message=message or "finished",
        )

    monkeypatch.setattr(pipeline_lab, "finish_pipeline_run_command", _finish_pipeline_run_command)

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
    assert finish_calls == [("demo", True, "Pipeline run finished. Inspect Run logs.")]
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


def test_display_lab_tab_refuses_run_when_page_state_detects_legacy_snippet(monkeypatch, tmp_path):
    run_calls = []
    legacy_code = (
        "from agi_cluster.agi_distributor import AGI\n"
        "async def main(app_env):\n"
        "    await AGI.run(app_env, mode=0)\n"
    )
    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 1],
            "demo__run_sequence": [0],
        },
        buttons={"demo_run_all": True},
        multiselects={"demo_run_sequence_widget": [0]},
    )
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    monkeypatch.setattr(
        pipeline_lab,
        "code_editor",
        lambda body, **_kwargs: fake_st.messages.append(("code", str(body))),
    )
    monkeypatch.setattr(pipeline_lab, "get_available_virtualenvs", lambda _env: [])
    monkeypatch.setattr(pipeline_lab, "normalize_runtime_path", lambda raw: str(raw) if raw else "")
    monkeypatch.setattr(pipeline_lab, "_is_valid_runtime_root", lambda raw: bool(raw))
    monkeypatch.setattr(pipeline_lab, "get_existing_snippets", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(pipeline_lab, "get_custom_buttons", lambda: [])
    monkeypatch.setattr(pipeline_lab, "get_info_bar", lambda: {})
    monkeypatch.setattr(pipeline_lab, "get_css_text", lambda: {})

    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [
            {"D": "", "Q": "legacy run", "M": "m", "C": legacy_code, "E": "", "R": "agi.run"}
        ],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
        run_all_steps=lambda *args, **kwargs: run_calls.append((args, kwargs)),
    )
    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert run_calls == []
    assert any(
        kind == "warning" and "stale AGI.run snippets" in message
        for kind, message in fake_st.messages
    )


def test_display_lab_tab_existing_steps_generates_new_step(monkeypatch, tmp_path):
    saved = []
    runtime_root = tmp_path / "runtime_b"
    (runtime_root / ".venv").mkdir(parents=True)
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


def test_display_lab_tab_overlay_save_persists_editor_payload(monkeypatch, tmp_path):
    saved = []
    forced = []
    reruns = []
    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo__run_sequence": [0],
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
    monkeypatch.setattr(
        pipeline_lab,
        "code_editor",
        lambda *_args, **_kwargs: {"text": "print('overlay save')", "type": "save"},
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
    assert fake_st.session_state["demo_pending_c_0"] == "print('overlay save')"
    assert reruns == ["fragment"]


def test_display_lab_tab_overlay_run_streams_step_and_logs_artifacts(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime"
    (runtime_root / ".venv").mkdir(parents=True)
    pushed_logs = []
    stream_calls = []
    artifact_calls = []

    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo__run_sequence": [0],
            "snippet_file": str(tmp_path / "snippet.py"),
            "df_file_out": str(tmp_path / "export.csv"),
        },
        multiselects={"demo_run_sequence_widget": [0]},
    )
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    monkeypatch.setattr(pipeline_lab, "get_available_virtualenvs", lambda _env: [runtime_root])
    monkeypatch.setattr(pipeline_lab, "normalize_runtime_path", lambda raw: str(raw) if raw else "")
    monkeypatch.setattr(pipeline_lab, "_is_valid_runtime_root", lambda raw: bool(raw))
    monkeypatch.setattr(pipeline_lab, "get_existing_snippets", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(pipeline_lab, "get_custom_buttons", lambda: [])
    monkeypatch.setattr(pipeline_lab, "get_info_bar", lambda: {})
    monkeypatch.setattr(pipeline_lab, "get_css_text", lambda: {})
    monkeypatch.setattr(
        pipeline_lab,
        "code_editor",
        lambda *_args, **_kwargs: {"text": "print('overlay run')", "type": "run"},
    )
    monkeypatch.setattr(pipeline_lab, "wrap_code_with_mlflow_resume", lambda code: f"# wrapped\n{code}")
    monkeypatch.setattr(pipeline_lab, "build_mlflow_process_env", lambda env, run_id=None: {"MLFLOW_RUN_ID": run_id or ""})
    monkeypatch.setattr(
        pipeline_lab,
        "start_mlflow_run",
        lambda *args, **kwargs: _Ctx(
            SimpleNamespace(
                __enter__=lambda self=None: {"run": SimpleNamespace(info=SimpleNamespace(run_id="run-123"))},
                __exit__=lambda self, exc_type, exc, tb: False,
            )
        ),
    )

    class _RunContext:
        def __enter__(self):
            return {"run": SimpleNamespace(info=SimpleNamespace(run_id="run-123"))}

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(pipeline_lab, "start_mlflow_run", lambda *args, **kwargs: _RunContext())
    monkeypatch.setattr(
        pipeline_lab,
        "log_mlflow_artifacts",
        lambda *args, **kwargs: artifact_calls.append((args, kwargs)),
    )

    entry = {"D": "desc", "Q": "question", "M": "model", "C": "print('old')", "E": str(runtime_root), "R": "agi.run"}
    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [entry],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
        prepare_run_log_file=lambda *_args, **_kwargs: (tmp_path / "step.log", None),
        push_run_log=lambda *_args, **kwargs: pushed_logs.append(kwargs.get("message") if "message" in kwargs else _args[1]),
        get_run_placeholder=lambda *_args, **_kwargs: None,
        python_for_step=lambda *_args, **_kwargs: "python-run",
        label_for_step_runtime=lambda *_args, **_kwargs: "runtime",
        stream_run_command=lambda *args, **kwargs: stream_calls.append((args, kwargs)) or "No such file or directory: missing.csv",
        rerun_fragment_or_app=lambda: pushed_logs.append("rerun"),
    )
    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert stream_calls
    assert artifact_calls
    assert any("Run step 1 started" in str(message) for message in pushed_logs)
    assert any("Hint: for AGI app steps" in str(message) for message in pushed_logs)


def test_display_lab_tab_existing_step_run_button_generates_and_autofixes(monkeypatch, tmp_path):
    saved = []
    pushed_logs = []
    reruns = []
    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo__run_sequence": [0],
            "demo_q_step_0": "new prompt",
            "demo_code_step_0": "print('old')",
        },
        buttons={"demo_run_0": True},
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

    entry = {"D": "desc", "Q": "question", "M": "model", "C": "print('old')", "E": ""}
    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [entry],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
        ask_gpt=lambda *_args, **_kwargs: ["", "generated question", "model-x", "print('generated')", "detail"],
        maybe_autofix_generated_code=lambda **_kwargs: ("print('fixed')", "fixed-model", "fixed-detail"),
        save_step=lambda *args, **kwargs: saved.append((args, kwargs)),
        push_run_log=lambda *_args, **kwargs: pushed_logs.append(kwargs.get("message") if "message" in kwargs else _args[1]),
        get_run_placeholder=lambda *_args, **_kwargs: None,
        rerun_fragment_or_app=lambda: reruns.append("fragment"),
    )
    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert saved
    assert fake_st.session_state["demo_pending_q_0"] == "generated question"
    assert fake_st.session_state["demo_pending_c_0"] == "print('fixed')"
    assert fake_st.session_state["demo__details"][0] == "fixed-detail"
    assert reruns == ["fragment"]
    assert any("Step 1:" in str(message) for message in pushed_logs)


def test_display_lab_tab_existing_steps_imports_additional_snippet(monkeypatch, tmp_path):
    saved = []
    snippet_path = tmp_path / "AGI_run_demo.py"
    snippet_path.write_text("print('snippet')\n", encoding="utf-8")
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
    monkeypatch.setattr(pipeline_lab, "get_available_virtualenvs", lambda _env: [])
    monkeypatch.setattr(pipeline_lab, "normalize_runtime_path", lambda raw: str(raw) if raw else "")
    monkeypatch.setattr(pipeline_lab, "_is_valid_runtime_root", lambda raw: bool(raw))
    monkeypatch.setattr(pipeline_lab, "get_existing_snippets", lambda *_args, **_kwargs: {snippet_path.name: snippet_path})
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
        save_step=lambda *args, **kwargs: saved.append((args, kwargs)),
    )
    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert saved
    args, kwargs = saved[-1]
    assert args[2] == 1
    assert kwargs["engine_map"][1] == "runpy"
    assert fake_st.session_state["demo__details"][1].startswith("Imported from")


def test_display_lab_tab_overlay_run_covers_fallback_runtime_and_missing_snippet(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime"
    (runtime_root / ".venv").mkdir(parents=True)
    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo__run_sequence": [0],
            "lab_selected_venv": str(runtime_root),
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
    monkeypatch.setattr(
        pipeline_lab,
        "code_editor",
        lambda *_args, **_kwargs: {"text": "print('overlay run')", "type": "run"},
    )

    entry = {"D": "desc", "Q": "question", "M": "model", "C": "print('old')", "E": "", "R": ""}
    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [entry],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
        get_run_placeholder=lambda *_args, **_kwargs: None,
    )
    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert fake_st.session_state["lab_selected_venv"] == str(runtime_root)
    assert fake_st.session_state["demo_venv_0"] == str(runtime_root)
    assert any(kind == "error" and "Snippet file is not configured" in message for kind, message in fake_st.messages)


def test_display_lab_tab_applies_pending_updates_and_reruns_fragment(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo__run_sequence": [0],
            "demo_q_step_0": "stale prompt",
            "demo_code_step_0": "print('stale')",
            "demo_pending_q_0": "fresh prompt",
            "demo_pending_c_0": "print('fresh')",
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
    monkeypatch.setattr(pipeline_lab, "code_editor", lambda *_args, **_kwargs: None)

    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [{"D": "", "Q": "q", "M": "m", "C": "print('old')", "E": ""}],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
        rerun_fragment_or_app=lambda: fake_st.messages.append(("rerun-fragment", "called")),
    )
    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert fake_st.session_state["demo_q_step_0"] == "fresh prompt"
    assert fake_st.session_state["demo_code_step_0"] == "print('fresh')"
    assert any(kind == "rerun-fragment" for kind, _ in fake_st.messages)


def test_display_lab_tab_sequence_lock_cancel_and_undo_paths(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo__run_sequence": [],
            "demo_run_sequence_widget": [],
            "demo_confirm_force_run": True,
            "demo_confirm_delete_all": True,
            "demo__undo_delete_snapshot": {"steps": [{"Q": "q"}], "label": "latest delete"},
        },
        buttons={
            "demo_force_run_cancel": True,
            "demo_delete_all_cancel": True,
            "demo_undo_delete": True,
        },
        multiselects={"demo_run_sequence_widget": []},
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
        load_all_steps=lambda *_args, **_kwargs: [{"D": "", "Q": "q", "M": "m", "C": "print('a')", "E": ""}],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: {
            "owner_text": "owner-1",
            "stale_reason": "missing heartbeat",
            "is_stale": False,
        },
        restore_pipeline_snapshot=lambda *_args, **_kwargs: "restore boom",
    )
    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert fake_st.session_state["demo__run_sequence"] == [0]
    assert "demo_confirm_force_run" not in fake_st.session_state
    assert "demo_confirm_delete_all" not in fake_st.session_state
    assert any(kind == "info" and "looks stale" in message for kind, message in fake_st.messages)
    assert any(kind == "error" and "Undo failed: restore boom" in message for kind, message in fake_st.messages)


def test_display_lab_tab_step_delete_and_undo_success_paths(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo__run_sequence": [0],
            "demo__undo_delete_snapshot": {"steps": [{"Q": "q"}], "label": "latest delete"},
        },
        buttons={
            "demo_delete_0": True,
            "demo_undo_delete": True,
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
    monkeypatch.setattr(pipeline_lab, "code_editor", lambda *_args, **_kwargs: None)

    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [{"D": "", "Q": "q", "M": "m", "C": "print('a')", "E": ""}],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
        capture_pipeline_snapshot=lambda *_args, **_kwargs: {"steps": [{"Q": "q"}]},
        restore_pipeline_snapshot=lambda *_args, **_kwargs: None,
    )
    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert fake_st.session_state["demo_confirm_delete_0"] is True
    assert any(kind == "success" and "Deleted steps restored." in message for kind, message in fake_st.messages)
    assert any(kind == "rerun" and message == "called" for kind, message in fake_st.messages)


def test_display_lab_tab_overlay_run_uses_active_app_when_agi_engine_has_no_runtime(monkeypatch, tmp_path):
    active_app = tmp_path / "flight_project"
    active_app.mkdir()
    pushed_logs = []
    stream_calls = []

    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo__run_sequence": [0],
            "snippet_file": str(tmp_path / "snippet.py"),
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
    monkeypatch.setattr(
        pipeline_lab,
        "code_editor",
        lambda *_args, **_kwargs: {"text": "print('overlay run')", "type": "run"},
    )
    monkeypatch.setattr(pipeline_lab, "wrap_code_with_mlflow_resume", lambda code: code)
    monkeypatch.setattr(pipeline_lab, "build_mlflow_process_env", lambda env, run_id=None: {})

    class _RunContext:
        def __enter__(self):
            return {"run": SimpleNamespace(info=SimpleNamespace(run_id="run-123"))}

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(pipeline_lab, "start_mlflow_run", lambda *args, **kwargs: _RunContext())
    monkeypatch.setattr(pipeline_lab, "log_mlflow_artifacts", lambda *args, **kwargs: None)

    entry = {"D": "desc", "Q": "question", "M": "model", "C": "print('old')", "E": "", "R": "agi.run"}
    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [entry],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
        prepare_run_log_file=lambda *_args, **_kwargs: (tmp_path / "step.log", None),
        push_run_log=lambda *_args, **kwargs: pushed_logs.append(kwargs.get("message") if "message" in kwargs else _args[1]),
        get_run_placeholder=lambda *_args, **_kwargs: None,
        python_for_step=lambda *_args, **_kwargs: "python-run",
        label_for_step_runtime=lambda *_args, **_kwargs: "runtime",
        stream_run_command=lambda *args, **kwargs: stream_calls.append((args, kwargs)) or "",
        rerun_fragment_or_app=lambda: pushed_logs.append("rerun"),
    )
    env = SimpleNamespace(active_app=active_app, envars={}, app="flight_project")

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", active_app, env, deps)

    assert fake_st.session_state["lab_selected_venv"] == str(active_app)
    assert stream_calls


def test_display_lab_tab_renders_conceptual_view_when_available(monkeypatch, tmp_path):
    render_calls = []
    fake_st = _FakeStreamlit(
        {"demo": [0, "", "", "", "", "", 0], "demo__run_sequence": [0]},
        multiselects={"demo_run_sequence_widget": [0]},
    )
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    monkeypatch.setattr(pipeline_lab, "code_editor", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline_lab, "get_available_virtualenvs", lambda _env: [])
    monkeypatch.setattr(pipeline_lab, "normalize_runtime_path", lambda raw: str(raw) if raw else "")
    monkeypatch.setattr(pipeline_lab, "_is_valid_runtime_root", lambda raw: bool(raw))
    monkeypatch.setattr(pipeline_lab, "get_existing_snippets", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(pipeline_lab, "get_custom_buttons", lambda: [])
    monkeypatch.setattr(pipeline_lab, "get_info_bar", lambda: {})
    monkeypatch.setattr(pipeline_lab, "get_css_text", lambda: {})

    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [{"D": "", "Q": "q", "M": "m", "C": "print('a')", "E": ""}],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: ("pipeline_view.dot", "digraph { a -> b }"),
        render_pipeline_view=lambda *args, **kwargs: render_calls.append((args, kwargs)),
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
    )
    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert ("graphviz", "True") in fake_st.messages
    assert render_calls[-1][1]["title"] == "Execution view"


def test_display_lab_tab_existing_steps_warns_when_add_prompt_missing(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit(
        {"demo": [0, "", "", "", "", "", 0], "demo__run_sequence": [0], "demo_new_q": ""},
        buttons={"demo_add_step_btn": True},
        multiselects={"demo_run_sequence_widget": [0]},
    )
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    monkeypatch.setattr(pipeline_lab, "code_editor", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline_lab, "get_available_virtualenvs", lambda _env: [])
    monkeypatch.setattr(pipeline_lab, "normalize_runtime_path", lambda raw: str(raw) if raw else "")
    monkeypatch.setattr(pipeline_lab, "_is_valid_runtime_root", lambda raw: bool(raw))
    monkeypatch.setattr(pipeline_lab, "get_existing_snippets", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(pipeline_lab, "get_custom_buttons", lambda: [])
    monkeypatch.setattr(pipeline_lab, "get_info_bar", lambda: {})
    monkeypatch.setattr(pipeline_lab, "get_css_text", lambda: {})

    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [{"D": "", "Q": "q", "M": "m", "C": "print('a')", "E": ""}],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
    )
    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert ("warning", "Enter a prompt before generating code.") in fake_st.messages


def test_display_lab_tab_existing_steps_warns_when_add_snippet_cannot_be_read(monkeypatch, tmp_path):
    snippet_path = tmp_path / "AGI_run_demo.py"
    snippet_path.write_text("print('snippet')\n", encoding="utf-8")
    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo_new_step_source": snippet_path.name,
            "demo__run_sequence": [0],
        },
        selectboxes={"demo_new_step_source": snippet_path.name},
        multiselects={"demo_run_sequence_widget": [0]},
    )
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    monkeypatch.setattr(pipeline_lab, "code_editor", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline_lab, "get_available_virtualenvs", lambda _env: [])
    monkeypatch.setattr(pipeline_lab, "normalize_runtime_path", lambda raw: str(raw) if raw else "")
    monkeypatch.setattr(pipeline_lab, "_is_valid_runtime_root", lambda raw: bool(raw))
    monkeypatch.setattr(pipeline_lab, "get_existing_snippets", lambda *_args, **_kwargs: {snippet_path.name: snippet_path})
    monkeypatch.setattr(pipeline_lab, "get_custom_buttons", lambda: [])
    monkeypatch.setattr(pipeline_lab, "get_info_bar", lambda: {})
    monkeypatch.setattr(pipeline_lab, "get_css_text", lambda: {})

    original_read_text = Path.read_text

    def _patched_read_text(self, *args, **kwargs):
        if self == snippet_path:
            raise OSError("cannot read")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _patched_read_text)

    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [{"D": "", "Q": "q", "M": "m", "C": "print('a')", "E": ""}],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
    )
    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert any(kind == "warning" and "Unable to read snippet" in message for kind, message in fake_st.messages)


def test_display_lab_tab_arms_force_unlock_and_delete_all(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit(
        {"demo": [0, "", "", "", "", "", 0], "demo__run_sequence": [0]},
        buttons={"demo_force_run_arm": True, "demo_delete_all": True},
        multiselects={"demo_run_sequence_widget": [0]},
    )
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    monkeypatch.setattr(pipeline_lab, "code_editor", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline_lab, "get_available_virtualenvs", lambda _env: [])
    monkeypatch.setattr(pipeline_lab, "normalize_runtime_path", lambda raw: str(raw) if raw else "")
    monkeypatch.setattr(pipeline_lab, "_is_valid_runtime_root", lambda raw: bool(raw))
    monkeypatch.setattr(pipeline_lab, "get_existing_snippets", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(pipeline_lab, "get_custom_buttons", lambda: [])
    monkeypatch.setattr(pipeline_lab, "get_info_bar", lambda: {})
    monkeypatch.setattr(pipeline_lab, "get_css_text", lambda: {})

    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [{"D": "", "Q": "q", "M": "m", "C": "print('a')", "E": ""}],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: {"owner_text": "owner-1", "is_stale": False},
    )
    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert fake_st.session_state["demo_confirm_force_run"] is True
    assert fake_st.session_state["demo_confirm_delete_all"] is True
    assert fake_st.messages.count(("rerun", "called")) >= 2


def test_display_lab_tab_preview_and_logs_cover_clear_and_last_log(monkeypatch, tmp_path):
    preview_calls = []
    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo__run_sequence": [0],
            "demo__run_logs": ["line 1"],
            "demo__last_run_log_file": str(tmp_path / "pipeline.log"),
            "loaded_df": pipeline_lab.pd.DataFrame({"value": [1]}),
        },
        buttons={"demo__clear_logs_global": True},
        multiselects={"demo_run_sequence_widget": [0]},
    )
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    monkeypatch.setattr(pipeline_lab, "code_editor", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline_lab, "get_available_virtualenvs", lambda _env: [])
    monkeypatch.setattr(pipeline_lab, "normalize_runtime_path", lambda raw: str(raw) if raw else "")
    monkeypatch.setattr(pipeline_lab, "_is_valid_runtime_root", lambda raw: bool(raw))
    monkeypatch.setattr(pipeline_lab, "get_existing_snippets", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(pipeline_lab, "get_custom_buttons", lambda: [])
    monkeypatch.setattr(pipeline_lab, "get_info_bar", lambda: {})
    monkeypatch.setattr(pipeline_lab, "get_css_text", lambda: {})
    monkeypatch.setattr(
        pipeline_lab,
        "render_dataframe_preview",
        lambda df, truncation_label=None: preview_calls.append((len(df), truncation_label)),
    )

    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [{"D": "", "Q": "q", "M": "m", "C": "print('a')", "E": ""}],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
    )
    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert preview_calls == [(1, "PIPELINE preview limited")]
    assert fake_st.session_state["demo__run_logs"] == []
    assert any(kind == "caption" and "No runs recorded yet." in message for kind, message in fake_st.messages)
    assert any(kind == "caption" and "Most recent run log" in message for kind, message in fake_st.messages)
    assert all(
        key != "pinned_expander:toggle:pipeline_run_logs:demo"
        for key, _kwargs in fake_st.button_calls
    )


def test_display_lab_tab_can_pin_run_logs(monkeypatch, tmp_path):
    log_file = tmp_path / "pipeline.log"
    editor_calls: list[dict[str, object]] = []

    def _code_editor(body, **kwargs):
        editor_calls.append({"body": body, **kwargs})
        return {"type": "pin_to_sidebar", "text": body}

    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo__run_sequence": [0],
            "demo__run_logs": ["line 1", "line 2"],
            "demo__last_run_log_file": str(log_file),
            "loaded_df": pipeline_lab.pd.DataFrame({"value": [1]}),
        },
        multiselects={"demo_run_sequence_widget": [0]},
    )
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    monkeypatch.setattr(pipeline_lab, "code_editor", _code_editor)
    monkeypatch.setattr(pipeline_lab, "get_available_virtualenvs", lambda _env: [])
    monkeypatch.setattr(pipeline_lab, "normalize_runtime_path", lambda raw: str(raw) if raw else "")
    monkeypatch.setattr(pipeline_lab, "_is_valid_runtime_root", lambda raw: bool(raw))
    monkeypatch.setattr(pipeline_lab, "get_existing_snippets", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(pipeline_lab, "get_custom_buttons", lambda: [])
    monkeypatch.setattr(pipeline_lab, "get_info_bar", lambda: {})
    monkeypatch.setattr(pipeline_lab, "get_css_text", lambda: {})
    monkeypatch.setattr(pipeline_lab, "render_dataframe_preview", lambda *_args, **_kwargs: None)

    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [{"D": "", "Q": "q", "M": "m", "C": "print('a')", "E": ""}],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
    )
    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    panels = fake_st.session_state["agilab:pinned_expanders"]
    buttons = editor_calls[-1]["buttons"]
    assert isinstance(buttons, list)
    assert [button["name"] for button in buttons[:2]] == ["Copy", "Pin"]
    assert panels["pipeline_run_logs:demo"]["title"] == "Pipeline logs: flight_project"
    assert panels["pipeline_run_logs:demo"]["body"] == "line 1\nline 2"
    assert panels["pipeline_run_logs:demo"]["source"] == f"PIPELINE {log_file}"
    assert ("rerun", "called") in fake_st.messages


def test_display_lab_tab_locked_step_delete_paths(monkeypatch, tmp_path):
    removed: list[tuple[str, str, str, str]] = []
    entry = {
        "D": "",
        "Q": "q",
        "M": "m",
        "C": "print('a')",
        "E": "",
        pipeline_lab.ORCHESTRATE_LOCKED_STEP_KEY: True,
        pipeline_lab.ORCHESTRATE_LOCKED_SOURCE_KEY: str(tmp_path / "AGI_run.py"),
    }

    def _configure(fake_st):
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
        load_all_steps=lambda *_args, **_kwargs: [entry],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
        capture_pipeline_snapshot=lambda *_args, **_kwargs: {"steps": [entry.copy()]},
        remove_step=lambda *args, **_kwargs: removed.append(tuple(str(arg) for arg in args[:4])),
    )
    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")

    arm_st = _FakeStreamlit(
        {"demo": [0, "", "", "", "", "", 0], "demo__run_sequence": [0]},
        buttons={"demo_delete_0": True},
        multiselects={"demo_run_sequence_widget": [0]},
    )
    _configure(arm_st)
    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)
    assert arm_st.session_state["demo_confirm_delete_0"] is True

    cancel_st = _FakeStreamlit(
        {"demo": [0, "", "", "", "", "", 0], "demo__run_sequence": [0], "demo_confirm_delete_0": True},
        buttons={"demo_delete_cancel_0": True},
        multiselects={"demo_run_sequence_widget": [0]},
    )
    _configure(cancel_st)
    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)
    assert "demo_confirm_delete_0" not in cancel_st.session_state

    delete_st = _FakeStreamlit(
        {"demo": [0, "", "", "", "", "", 0], "demo__run_sequence": [0], "demo_confirm_delete_0": True},
        buttons={"demo_delete_confirm_0": True},
        multiselects={"demo_run_sequence_widget": [0]},
    )
    _configure(delete_st)
    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)
    assert removed
    assert isinstance(delete_st.session_state["demo__undo_delete_snapshot"], dict)
    assert any(kind == "rerun" and message == "called" for kind, message in delete_st.messages)


def test_display_lab_tab_overlay_run_covers_runpy_and_missing_log_path(monkeypatch, tmp_path):
    pushed_logs: list[str] = []
    run_lab_calls: list[tuple[tuple, dict]] = []
    placeholder_messages: list[str] = []
    placeholder = SimpleNamespace(caption=lambda message: placeholder_messages.append(str(message)))

    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo__run_sequence": [0],
            "snippet_file": str(tmp_path / "snippet.py"),
            "demo__run_placeholder": placeholder,
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
    monkeypatch.setattr(
        pipeline_lab,
        "code_editor",
        lambda *_args, **_kwargs: {"text": "print('overlay run')", "type": "run"},
    )
    monkeypatch.setattr(
        pipeline_lab,
        "run_lab",
        lambda *args, **kwargs: run_lab_calls.append((args, kwargs)) or "",
    )
    monkeypatch.setattr(pipeline_lab, "build_mlflow_process_env", lambda env, run_id=None: {})

    class _RunContext:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(pipeline_lab, "start_mlflow_run", lambda *args, **kwargs: _RunContext())
    monkeypatch.setattr(pipeline_lab, "log_mlflow_artifacts", lambda *args, **kwargs: None)

    entry = {"D": "desc", "Q": "question", "M": "model", "C": "print('old')", "E": "", "R": ""}
    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [entry],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
        prepare_run_log_file=lambda *_args, **_kwargs: (None, "no log"),
        push_run_log=lambda *_args, **kwargs: pushed_logs.append(kwargs.get("message") if "message" in kwargs else _args[1]),
        get_run_placeholder=lambda *_args, **_kwargs: placeholder,
        rerun_fragment_or_app=lambda: pushed_logs.append("rerun"),
    )
    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project", copilot_file=tmp_path / "copilot.py")

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert placeholder_messages == ["Starting overlay run…"]
    assert run_lab_calls
    assert any("unable to prepare log file: no log" in message for message in pushed_logs)
    assert any("runpy executed (no captured stdout)" in message for message in pushed_logs)


def test_display_lab_tab_overlay_run_logs_missing_file_hint(monkeypatch, tmp_path):
    pushed_logs: list[str] = []

    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo__run_sequence": [0],
            "snippet_file": str(tmp_path / "snippet.py"),
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
    monkeypatch.setattr(
        pipeline_lab,
        "code_editor",
        lambda *_args, **_kwargs: {"text": "print('overlay run')", "type": "run"},
    )
    monkeypatch.setattr(pipeline_lab, "wrap_code_with_mlflow_resume", lambda code: code)
    monkeypatch.setattr(pipeline_lab, "build_mlflow_process_env", lambda env, run_id=None: {})

    class _RunContext:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(pipeline_lab, "start_mlflow_run", lambda *args, **kwargs: _RunContext())
    monkeypatch.setattr(pipeline_lab, "log_mlflow_artifacts", lambda *args, **kwargs: None)

    runtime_root = tmp_path / "runtime"
    (runtime_root / ".venv").mkdir(parents=True)
    entry = {"D": "desc", "Q": "question", "M": "model", "C": "print('old')", "E": str(runtime_root), "R": ""}
    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [entry],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
        prepare_run_log_file=lambda *_args, **_kwargs: (tmp_path / "step.log", None),
        push_run_log=lambda *_args, **kwargs: pushed_logs.append(kwargs.get("message") if "message" in kwargs else _args[1]),
        get_run_placeholder=lambda *_args, **_kwargs: None,
        python_for_step=lambda *_args, **_kwargs: "python-run",
        label_for_step_runtime=lambda *_args, **_kwargs: "runtime",
        stream_run_command=lambda *_args, **_kwargs: "No such file or directory",
    )
    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert any("Output (step 1):" in message for message in pushed_logs)
    assert any("Check whether the upstream step created the expected file" in message for message in pushed_logs)


def test_display_lab_tab_import_snippet_without_runtime_resets_sequence(monkeypatch, tmp_path):
    snippet_path = tmp_path / "AGI_run_demo.py"
    snippet_path.write_text("print('snippet')\n", encoding="utf-8")
    save_calls: list[tuple[tuple, dict]] = []

    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo_new_step_source": snippet_path.name,
            "demo__run_sequence": [],
            "demo_run_sequence_widget": [],
        },
        buttons={"demo_add_step_snippet_btn": True},
        selectboxes={"demo_new_step_source": snippet_path.name},
        multiselects={"demo_run_sequence_widget": []},
    )
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    monkeypatch.setattr(pipeline_lab, "code_editor", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline_lab, "get_available_virtualenvs", lambda _env: [])
    monkeypatch.setattr(pipeline_lab, "normalize_runtime_path", lambda raw: str(raw) if raw else "")
    monkeypatch.setattr(pipeline_lab, "_is_valid_runtime_root", lambda raw: bool(raw))
    monkeypatch.setattr(pipeline_lab, "get_existing_snippets", lambda *_args, **_kwargs: {snippet_path.name: snippet_path})
    monkeypatch.setattr(pipeline_lab, "get_custom_buttons", lambda: [])
    monkeypatch.setattr(pipeline_lab, "get_info_bar", lambda: {})
    monkeypatch.setattr(pipeline_lab, "get_css_text", lambda: {})
    monkeypatch.setattr(
        pipeline_lab,
        "_normalize_imported_orchestrate_snippet",
        lambda code, default_runtime="": (code, "runpy", ""),
    )

    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [{"D": "", "Q": "q", "M": "m", "C": "print('a')", "E": ""}],
        save_step=lambda *args, **kwargs: save_calls.append((args, kwargs)),
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
    )
    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert fake_st.session_state["demo__run_sequence"] == [0]
    assert save_calls[-1][1]["venv_map"] == {}


def test_display_lab_tab_stale_lock_run_logs_without_file(monkeypatch, tmp_path):
    pushed_logs: list[str] = []
    run_all_calls: list[tuple[tuple, dict]] = []
    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo__run_sequence": [0],
            "demo__run_logs": ["existing log"],
        },
        buttons={"demo_force_run_stale": True},
        multiselects={"demo_run_sequence_widget": [0]},
    )
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    monkeypatch.setattr(
        pipeline_lab,
        "code_editor",
        lambda body, **_kwargs: fake_st.messages.append(("code", str(body))),
    )
    monkeypatch.setattr(pipeline_lab, "get_available_virtualenvs", lambda _env: [])
    monkeypatch.setattr(pipeline_lab, "normalize_runtime_path", lambda raw: str(raw) if raw else "")
    monkeypatch.setattr(pipeline_lab, "_is_valid_runtime_root", lambda raw: bool(raw))
    monkeypatch.setattr(pipeline_lab, "get_existing_snippets", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(pipeline_lab, "get_custom_buttons", lambda: [])
    monkeypatch.setattr(pipeline_lab, "get_info_bar", lambda: {})
    monkeypatch.setattr(pipeline_lab, "get_css_text", lambda: {})

    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [{"D": "", "Q": "q", "M": "m", "C": "print('a')", "E": ""}],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: {"owner_text": "owner-1", "is_stale": True},
        prepare_run_log_file=lambda *_args, **_kwargs: (None, "no log"),
        push_run_log=lambda *_args, **kwargs: pushed_logs.append(kwargs.get("message") if "message" in kwargs else _args[1]),
        get_run_placeholder=lambda *_args, **_kwargs: None,
        run_all_steps=lambda *args, **kwargs: run_all_calls.append((args, kwargs)),
    )
    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert run_all_calls and run_all_calls[-1][1]["force_lock_clear"] is True
    assert any("unable to prepare log file: no log" in message for message in pushed_logs)
    assert any(kind == "code" and "existing log" in message for kind, message in fake_st.messages)


def test_display_lab_tab_add_step_without_selected_runtime_uses_runpy(monkeypatch, tmp_path):
    save_calls: list[tuple[tuple, dict]] = []
    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo__run_sequence": [0],
            "demo_new_q": "generate code",
        },
        buttons={"demo_add_step_btn": True},
        multiselects={"demo_run_sequence_widget": [0]},
    )
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    monkeypatch.setattr(pipeline_lab, "code_editor", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline_lab, "get_available_virtualenvs", lambda _env: [])
    monkeypatch.setattr(pipeline_lab, "normalize_runtime_path", lambda raw: str(raw) if raw else "")
    monkeypatch.setattr(pipeline_lab, "_is_valid_runtime_root", lambda raw: bool(raw))
    monkeypatch.setattr(pipeline_lab, "get_existing_snippets", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(pipeline_lab, "get_custom_buttons", lambda: [])
    monkeypatch.setattr(pipeline_lab, "get_info_bar", lambda: {})
    monkeypatch.setattr(pipeline_lab, "get_css_text", lambda: {})

    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [{"D": "", "Q": "q", "M": "m", "C": "print('a')", "E": ""}],
        save_step=lambda *args, **kwargs: save_calls.append((args, kwargs)),
        ask_gpt=lambda *_args, **_kwargs: [Path("df.csv"), "new question", "model", "print('new')", "detail"],
        maybe_autofix_generated_code=lambda **kwargs: (kwargs["merged_code"], kwargs["model_label"], kwargs["detail"]),
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
        bump_history_revision=lambda *_args, **_kwargs: None,
    )
    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert save_calls[-1][1]["engine_map"][1] == "runpy"


def test_display_lab_tab_dirty_locked_source_and_experiment_reload_paths(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo__run_sequence": [0],
            "demo_q_step_0_dirty": True,
            "_experiment_reload_required": True,
            "loaded_df": pipeline_lab.pd.DataFrame({"value": [1]}),
        },
        multiselects={"demo_run_sequence_widget": [0]},
    )
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    monkeypatch.setattr(pipeline_lab, "code_editor", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline_lab, "get_available_virtualenvs", lambda _env: [])
    monkeypatch.setattr(pipeline_lab, "normalize_runtime_path", lambda raw: str(raw) if raw else "")
    monkeypatch.setattr(pipeline_lab, "_is_valid_runtime_root", lambda raw: bool(raw))
    monkeypatch.setattr(pipeline_lab, "get_existing_snippets", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(pipeline_lab, "get_custom_buttons", lambda: [])
    monkeypatch.setattr(pipeline_lab, "get_info_bar", lambda: {})
    monkeypatch.setattr(pipeline_lab, "get_css_text", lambda: {})

    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [
            {
                "D": "",
                "Q": "q",
                "M": "m",
                "C": "print('a')",
                "E": "",
                pipeline_lab.ORCHESTRATE_LOCKED_STEP_KEY: True,
            }
        ],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
        rerun_fragment_or_app=lambda: fake_st.messages.append(("rerun-fragment", "called")),
    )
    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert any(kind == "caption" and "Imported from ORCHESTRATE." in message for kind, message in fake_st.messages)
    assert any(kind == "rerun-fragment" for kind, _ in fake_st.messages)
    assert any(kind == "rerun" and message == "called" for kind, message in fake_st.messages)


def test_display_lab_tab_overlay_duplicate_guards_skip_repeat_save_and_run(monkeypatch, tmp_path):
    save_calls: list[tuple[tuple, dict]] = []
    stream_calls: list[tuple[tuple, dict]] = []

    def _configure(fake_st):
        monkeypatch.setattr(pipeline_lab, "st", fake_st)
        monkeypatch.setattr(pipeline_lab, "get_available_virtualenvs", lambda _env: [])
        monkeypatch.setattr(pipeline_lab, "normalize_runtime_path", lambda raw: str(raw) if raw else "")
        monkeypatch.setattr(pipeline_lab, "_is_valid_runtime_root", lambda raw: bool(raw))
        monkeypatch.setattr(pipeline_lab, "get_existing_snippets", lambda *_args, **_kwargs: {})
        monkeypatch.setattr(pipeline_lab, "get_custom_buttons", lambda: [])
        monkeypatch.setattr(pipeline_lab, "get_info_bar", lambda: {})
        monkeypatch.setattr(pipeline_lab, "get_css_text", lambda: {})

    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [{"D": "", "Q": "q", "M": "m", "C": "print('a')", "E": ""}],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
        save_step=lambda *args, **kwargs: save_calls.append((args, kwargs)),
        stream_run_command=lambda *args, **kwargs: stream_calls.append((args, kwargs)) or "",
    )
    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")

    save_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo__run_sequence": [0],
            "demo_overlay_done_0": True,
        },
        multiselects={"demo_run_sequence_widget": [0]},
    )
    _configure(save_st)
    monkeypatch.setattr(
        pipeline_lab,
        "code_editor",
        lambda *_args, **_kwargs: {"text": "print('overlay save')", "type": "save"},
    )
    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)
    assert "demo_overlay_done_0" not in save_st.session_state
    assert save_calls == []

    run_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo__run_sequence": [0],
            "demo_overlay_done_0": True,
            "snippet_file": str(tmp_path / "snippet.py"),
        },
        multiselects={"demo_run_sequence_widget": [0]},
    )
    _configure(run_st)
    monkeypatch.setattr(
        pipeline_lab,
        "code_editor",
        lambda *_args, **_kwargs: {"text": "print('overlay run')", "type": "run"},
    )
    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)
    assert "demo_overlay_done_0" not in run_st.session_state
    assert stream_calls == []


def test_display_lab_tab_run_button_reuses_existing_code_when_generation_returns_blank(monkeypatch, tmp_path):
    save_calls: list[tuple[tuple, dict]] = []
    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo__run_sequence": [0],
            "demo_q_step_0": "new prompt",
            "demo_code_step_0": "print('existing')",
        },
        buttons={"demo_run_0": True},
        multiselects={"demo_run_sequence_widget": [0]},
    )
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    monkeypatch.setattr(pipeline_lab, "code_editor", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline_lab, "get_available_virtualenvs", lambda _env: [])
    monkeypatch.setattr(pipeline_lab, "normalize_runtime_path", lambda raw: str(raw) if raw else "")
    monkeypatch.setattr(pipeline_lab, "_is_valid_runtime_root", lambda raw: bool(raw))
    monkeypatch.setattr(pipeline_lab, "get_existing_snippets", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(pipeline_lab, "get_custom_buttons", lambda: [])
    monkeypatch.setattr(pipeline_lab, "get_info_bar", lambda: {})
    monkeypatch.setattr(pipeline_lab, "get_css_text", lambda: {})

    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [{"D": "", "Q": "q", "M": "m", "C": "print('existing')", "E": ""}],
        save_step=lambda *args, **kwargs: save_calls.append((args, kwargs)),
        ask_gpt=lambda *_args, **_kwargs: [Path("df.csv"), "generated question", "model", "", "detail"],
        maybe_autofix_generated_code=lambda **kwargs: (kwargs["merged_code"], kwargs["model_label"], kwargs["detail"]),
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
        bump_history_revision=lambda *_args, **_kwargs: None,
    )
    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    saved_answer = save_calls[-1][0][1]
    assert saved_answer[3] == "print('existing')"


def test_display_lab_tab_nonlocked_delete_confirm_and_cancel_paths(monkeypatch, tmp_path):
    removed: list[tuple[str, str, str, str]] = []

    def _configure(fake_st):
        monkeypatch.setattr(pipeline_lab, "st", fake_st)
        monkeypatch.setattr(pipeline_lab, "code_editor", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(pipeline_lab, "get_available_virtualenvs", lambda _env: [])
        monkeypatch.setattr(pipeline_lab, "normalize_runtime_path", lambda raw: str(raw) if raw else "")
        monkeypatch.setattr(pipeline_lab, "_is_valid_runtime_root", lambda raw: bool(raw))
        monkeypatch.setattr(pipeline_lab, "get_existing_snippets", lambda *_args, **_kwargs: {})
        monkeypatch.setattr(pipeline_lab, "get_custom_buttons", lambda: [])
        monkeypatch.setattr(pipeline_lab, "get_info_bar", lambda: {})
        monkeypatch.setattr(pipeline_lab, "get_css_text", lambda: {})

    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [{"D": "", "Q": "q", "M": "m", "C": "print('a')", "E": ""}],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
        capture_pipeline_snapshot=lambda *_args, **_kwargs: {"steps": [{"Q": "q"}]},
        remove_step=lambda *args, **_kwargs: removed.append(tuple(str(arg) for arg in args[:4])),
    )
    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")

    cancel_st = _FakeStreamlit(
        {"demo": [0, "", "", "", "", "", 0], "demo__run_sequence": [0], "demo_confirm_delete_0": True},
        buttons={"demo_delete_cancel_0": True},
        multiselects={"demo_run_sequence_widget": [0]},
    )
    _configure(cancel_st)
    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)
    assert "demo_confirm_delete_0" not in cancel_st.session_state

    delete_st = _FakeStreamlit(
        {"demo": [0, "", "", "", "", "", 0], "demo__run_sequence": [0], "demo_confirm_delete_0": True},
        buttons={"demo_delete_confirm_0": True},
        multiselects={"demo_run_sequence_widget": [0]},
    )
    _configure(delete_st)
    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)
    assert removed
    assert any(kind == "rerun" and message == "called" for kind, message in delete_st.messages)


def test_display_lab_tab_overlay_paths_cover_same_sig_none_text_and_entry_runtime(monkeypatch, tmp_path):
    save_calls: list[tuple[tuple, dict]] = []

    def _configure(fake_st):
        monkeypatch.setattr(pipeline_lab, "st", fake_st)
        monkeypatch.setattr(pipeline_lab, "get_available_virtualenvs", lambda _env: [])
        monkeypatch.setattr(pipeline_lab, "normalize_runtime_path", lambda raw: str(raw) if raw else "")
        monkeypatch.setattr(pipeline_lab, "_is_valid_runtime_root", lambda raw: bool(raw))
        monkeypatch.setattr(pipeline_lab, "get_existing_snippets", lambda *_args, **_kwargs: {})
        monkeypatch.setattr(pipeline_lab, "get_custom_buttons", lambda: [])
        monkeypatch.setattr(pipeline_lab, "get_info_bar", lambda: {})
        monkeypatch.setattr(pipeline_lab, "get_css_text", lambda: {})

    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [{"D": "", "Q": "q", "M": "m", "C": "print('seed')", "E": "", "R": ""}],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
        save_step=lambda *args, **kwargs: save_calls.append((args, kwargs)),
        force_persist_step=lambda *_args, **_kwargs: None,
        bump_history_revision=lambda *_args, **_kwargs: None,
    )
    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")

    repeat_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo__run_sequence": [0],
            "demo_overlay_sig_0": ("save", "print('repeat')"),
        },
        multiselects={"demo_run_sequence_widget": [0]},
    )
    _configure(repeat_st)
    monkeypatch.setattr(
        pipeline_lab,
        "code_editor",
        lambda *_args, **_kwargs: {"text": "print('repeat')", "type": "save"},
    )
    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)
    assert save_calls == []

    none_text_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo__run_sequence": [0],
        },
        multiselects={"demo_run_sequence_widget": [0]},
    )
    _configure(none_text_st)
    monkeypatch.setattr(
        pipeline_lab,
        "code_editor",
        lambda *_args, **_kwargs: {"text": None, "type": "save"},
    )
    none_text_deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [{"D": "", "Q": "q", "M": "m", "C": "print('fallback')", "E": "", "R": ""}],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
        save_step=lambda *args, **kwargs: save_calls.append((args, kwargs)),
        force_persist_step=lambda *_args, **_kwargs: None,
        bump_history_revision=lambda *_args, **_kwargs: None,
    )
    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, none_text_deps)
    assert save_calls[-1][0][1][3] == "print('fallback')"

    runtime_root = tmp_path / "runtime"
    (runtime_root / ".venv").mkdir(parents=True)
    run_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo__run_sequence": [0],
        },
        multiselects={"demo_run_sequence_widget": [0]},
    )
    _configure(run_st)
    monkeypatch.setattr(
        pipeline_lab,
        "code_editor",
        lambda *_args, **_kwargs: {"text": "print('overlay run')", "type": "run"},
    )
    run_deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [{"D": "", "Q": "q", "M": "m", "C": "print('seed')", "E": str(runtime_root), "R": "custom.engine"}],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
        get_run_placeholder=lambda *_args, **_kwargs: None,
    )
    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, run_deps)
    assert run_st.session_state["demo__venv_map"][0] == str(runtime_root)
    assert run_st.session_state["demo__engine_map"][0] == "agi.run"


def test_display_lab_tab_ignores_invalid_steps_file_toml(monkeypatch, tmp_path):
    steps_file = tmp_path / "lab_steps.toml"
    steps_file.write_text("not = [valid", encoding="utf-8")
    fake_st = _FakeStreamlit({"demo": [0, "", "", "", "", "", 0]})
    monkeypatch.setattr(pipeline_lab, "st", fake_st)
    monkeypatch.setattr(pipeline_lab, "get_available_virtualenvs", lambda _env: [])
    monkeypatch.setattr(pipeline_lab, "normalize_runtime_path", lambda raw: str(raw) if raw else "")
    monkeypatch.setattr(pipeline_lab, "_is_valid_runtime_root", lambda raw: bool(raw))
    monkeypatch.setattr(pipeline_lab, "get_existing_snippets", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(pipeline_lab, "get_custom_buttons", lambda: [])
    monkeypatch.setattr(pipeline_lab, "get_info_bar", lambda: {})
    monkeypatch.setattr(pipeline_lab, "get_css_text", lambda: {})

    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
    )
    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")

    pipeline_lab.display_lab_tab(tmp_path, "demo", steps_file, tmp_path / "flight_project", env, deps)

    assert fake_st.session_state["demo"][-1] == 0
    assert any(kind == "info" and "No steps recorded yet" in message for kind, message in fake_st.messages)


def test_display_lab_tab_reseeds_missing_or_blank_editor_state(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo__run_sequence": [0],
            "demo_step_init_0": True,
            "demo_code_step_0": "",
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
    monkeypatch.setattr(pipeline_lab, "code_editor", lambda *_args, **_kwargs: None)

    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [{"D": "", "Q": "fresh q", "M": "m", "C": "print('seed')", "E": ""}],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
    )
    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert fake_st.session_state["demo_q_step_0"] == "fresh q"
    assert fake_st.session_state["demo_code_step_0"] == "print('seed')"
    assert fake_st.session_state["demo_ignore_blank_editor_0"] is True


def test_display_lab_tab_reapplies_pending_code_over_existing_editor_state(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo__run_sequence": [0],
            "demo_step_init_0": True,
            "demo_code_step_0": "print('old')",
            "demo_code_step_0_apply_pending": "print('new')",
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
    monkeypatch.setattr(pipeline_lab, "code_editor", lambda *_args, **_kwargs: None)

    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [{"D": "", "Q": "q", "M": "m", "C": "print('seed')", "E": ""}],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
    )
    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert fake_st.session_state["demo_code_step_0"] == "print('new')"
    assert fake_st.session_state["demo_editor_resync_sig_0"] == "print('new')"


def test_display_lab_tab_overlay_blank_editor_keeps_existing_code(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo__run_sequence": [0],
            "demo_step_init_0": True,
            "demo_code_step_0": "print('keep')",
            "demo_ignore_blank_editor_0": True,
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
    monkeypatch.setattr(
        pipeline_lab,
        "code_editor",
        lambda *_args, **_kwargs: {"text": "", "type": None},
    )

    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [{"D": "", "Q": "q", "M": "m", "C": "print('keep')", "E": ""}],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
    )
    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert fake_st.session_state["demo_code_step_0"] == "print('keep')"
    assert "demo_ignore_blank_editor_0" not in fake_st.session_state


def test_display_lab_tab_overlay_run_uses_entry_runtime_and_default_engine(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime"
    (runtime_root / ".venv").mkdir(parents=True)
    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo__run_sequence": [0],
        },
        selectboxes={"demo_venv_0": "Use AGILAB environment"},
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
        lambda *_args, **_kwargs: {"text": "print('overlay run')", "type": "run"},
    )

    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [{"D": "", "Q": "q", "M": "m", "C": "print('seed')", "E": str(runtime_root), "R": ""}],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
        get_run_placeholder=lambda *_args, **_kwargs: None,
    )
    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert fake_st.session_state["demo__venv_map"][0] == str(runtime_root)
    assert fake_st.session_state["demo__engine_map"][0] == "agi.run"


def test_display_lab_tab_overlay_run_uses_active_app_for_agi_engine(monkeypatch, tmp_path):
    active_runtime = tmp_path / "active_runtime"
    (active_runtime / ".venv").mkdir(parents=True)
    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo__run_sequence": [0],
        },
        selectboxes={"demo_venv_0": "Use AGILAB environment"},
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
        lambda *_args, **_kwargs: {"text": "print('overlay run')", "type": "run"},
    )

    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [{"D": "", "Q": "q", "M": "m", "C": "print('seed')", "E": "", "R": "agi.custom"}],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
        get_run_placeholder=lambda *_args, **_kwargs: None,
    )
    env = SimpleNamespace(active_app=active_runtime, envars={}, app="flight_project")

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert fake_st.session_state["lab_selected_venv"] == str(active_runtime)
    assert fake_st.session_state["demo__engine_map"][0] == "agi.custom"


def test_display_lab_tab_sequence_defaults_and_formats_labels(monkeypatch, tmp_path):
    class _FormattingStreamlit(_FakeStreamlit):
        def multiselect(self, _label, options, key=None, format_func=None, help=None):
            if format_func is not None:
                self.messages.extend(("formatted", str(format_func(option))) for option in options)
            return super().multiselect(_label, options, key=key, format_func=format_func, help=help)

    fake_st = _FormattingStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo__run_sequence": [],
            "demo_run_sequence_widget": [99],
        },
        multiselects={"demo_run_sequence_widget": []},
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
        load_all_steps=lambda *_args, **_kwargs: [{"D": "", "Q": "q", "M": "m", "C": "print('seed')", "E": ""}],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
    )
    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert fake_st.session_state["demo__run_sequence"] == [0]
    assert any(kind == "formatted" and message.startswith("Step 1") for kind, message in fake_st.messages)


def test_display_lab_tab_appends_custom_initial_runtime_label(monkeypatch, tmp_path):
    custom_runtime = str(tmp_path / "custom-runtime")
    fake_st = _FakeStreamlit(
        {
            "demo": [0, "", "", "", "", "", 0],
            "demo__run_sequence": [0],
            "demo_step_init_0": True,
            "demo_venv_0": custom_runtime,
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
    monkeypatch.setattr(pipeline_lab, "code_editor", lambda *_args, **_kwargs: None)

    deps = _make_lab_deps(
        load_all_steps=lambda *_args, **_kwargs: [{"D": "", "Q": "q", "M": "m", "C": "print('seed')", "E": ""}],
        load_pipeline_conceptual_dot=lambda *_args, **_kwargs: (None, None),
        render_pipeline_view=lambda *_args, **_kwargs: None,
        inspect_pipeline_run_lock=lambda *_args, **_kwargs: None,
    )
    env = SimpleNamespace(active_app=tmp_path / "flight_project", envars={}, app="flight_project")

    pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_steps.toml", tmp_path / "flight_project", env, deps)

    assert fake_st.session_state["demo_venv_0"] == custom_runtime
