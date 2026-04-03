from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
import sys
import types


def _import_agilab_module(module_name: str):
    src_root = Path(__file__).resolve().parents[1] / "src"
    package_root = src_root / "agilab"
    src_root_str = str(src_root)
    package_root_str = str(package_root)
    if src_root_str not in sys.path:
        sys.path.insert(0, src_root_str)
    pkg = sys.modules.get("agilab")
    if pkg is None or not hasattr(pkg, "__path__"):
        pkg = types.ModuleType("agilab")
        pkg.__path__ = [package_root_str]
        sys.modules["agilab"] = pkg
    else:
        package_path = list(pkg.__path__)
        if package_root_str not in package_path:
            pkg.__path__ = [package_root_str, *package_path]
    importlib.invalidate_caches()
    return importlib.import_module(module_name)


orchestrate_execute = _import_agilab_module("agilab.orchestrate_execute")


def test_collect_candidate_roots_deduplicates_paths(tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir()

    env = SimpleNamespace(
        dataframe_path=shared,
        app_data_rel=shared,
    )
    roots = orchestrate_execute.collect_candidate_roots(
        env,
        {
            "data_in": str(shared),
            "data_out": str(shared / "out"),
        },
    )

    assert roots == [shared, shared / "out"]


def test_collect_candidate_roots_expands_relative_paths_from_home(monkeypatch, tmp_path):
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    relative_data = Path("relative/input")
    relative_out = Path("relative/output")

    monkeypatch.setattr(
        orchestrate_execute.Path,
        "home",
        classmethod(lambda cls: home_dir),
    )

    env = SimpleNamespace(
        dataframe_path=relative_data,
        app_data_rel=None,
    )
    roots = orchestrate_execute.collect_candidate_roots(
        env,
        {
            "data_in": str(relative_data),
            "data_out": str(relative_out),
        },
    )

    assert roots == [
        home_dir / relative_data,
        home_dir / relative_out,
    ]


def test_find_preview_target_ignores_empty_and_metadata_files(tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    empty_csv = output_dir / "empty.csv"
    empty_csv.write_text("")

    metadata_csv = output_dir / "._artifact.csv"
    metadata_csv.write_text("metadata")

    valid_csv = output_dir / "artifact.csv"
    valid_csv.write_text("a,b\n1,2\n")

    target, files = orchestrate_execute.find_preview_target([output_dir])

    assert target == valid_csv
    assert files == [valid_csv]


def test_find_preview_target_returns_none_when_latest_file_disappears(tmp_path, monkeypatch):
    older_csv = tmp_path / "older.csv"
    older_csv.write_text("a,b\n1,2\n", encoding="utf-8")

    newest_csv = tmp_path / "newest.csv"
    newest_csv.write_text("a,b\n3,4\n", encoding="utf-8")

    original_stat = orchestrate_execute.Path.stat
    newest_calls = {"count": 0}

    def flaky_stat(self: Path, *args, **kwargs):
        if self == newest_csv:
            newest_calls["count"] += 1
            if newest_calls["count"] >= 5:
                raise FileNotFoundError("simulated race")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(orchestrate_execute.Path, "stat", flaky_stat)

    target, files = orchestrate_execute.find_preview_target([older_csv, newest_csv])

    assert target is None
    assert files == [older_csv, newest_csv]


def test_pending_execute_action_round_trip():
    session_state = {}

    assert orchestrate_execute.consume_pending_execute_action(session_state) is None

    orchestrate_execute.queue_pending_execute_action(session_state, "run")
    assert session_state[orchestrate_execute.PENDING_EXECUTE_ACTION_KEY] == "run"
    assert orchestrate_execute.consume_pending_execute_action(session_state) == "run"
    assert orchestrate_execute.consume_pending_execute_action(session_state) is None


def test_render_graph_preview_draws_and_labels_source(monkeypatch):
    calls: list[tuple[str, object]] = []

    fake_st = SimpleNamespace(
        caption=lambda message: calls.append(("caption", message)),
        pyplot=lambda fig, width=None: calls.append(("pyplot", (fig, width))),
    )
    fake_ax = SimpleNamespace(axis=lambda mode: calls.append(("axis", mode)))
    fake_fig = object()
    fake_plt = SimpleNamespace(
        subplots=lambda figsize=None: (fake_fig, fake_ax),
        close=lambda fig: calls.append(("close", fig)),
    )

    monkeypatch.setattr(orchestrate_execute, "st", fake_st)
    monkeypatch.setattr(orchestrate_execute, "plt", fake_plt)
    monkeypatch.setattr(orchestrate_execute.nx, "spring_layout", lambda graph_preview, seed=None: {"n1": (0.0, 0.0)})
    monkeypatch.setattr(orchestrate_execute.nx, "draw_networkx_nodes", lambda *args, **kwargs: calls.append(("nodes", kwargs.get("node_color"))))
    monkeypatch.setattr(orchestrate_execute.nx, "draw_networkx_edges", lambda *args, **kwargs: calls.append(("edges", kwargs.get("alpha"))))
    monkeypatch.setattr(orchestrate_execute.nx, "draw_networkx_labels", lambda *args, **kwargs: calls.append(("labels", kwargs.get("font_size"))))

    graph = orchestrate_execute.nx.Graph()
    graph.add_node("n1")

    orchestrate_execute._render_graph_preview(graph, "preview.json")

    assert ("caption", "Graph preview generated from JSON output") in calls
    assert ("caption", "Source: preview.json") in calls
    assert ("nodes", "skyblue") in calls
    assert ("edges", 0.5) in calls
    assert ("labels", 9) in calls
    assert ("axis", "off") in calls
    assert ("pyplot", (fake_fig, "stretch")) in calls
    assert ("close", fake_fig) in calls


def test_render_graph_preview_requires_matplotlib(monkeypatch):
    monkeypatch.setattr(orchestrate_execute, "plt", None)
    monkeypatch.setattr(orchestrate_execute, "_MATPLOTLIB_IMPORT_ERROR", ModuleNotFoundError("matplotlib"))

    graph = orchestrate_execute.nx.Graph()

    with pytest.raises(RuntimeError, match="matplotlib unavailable"):
        orchestrate_execute._render_graph_preview(graph, None)


class _State(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


class _Ctx:
    def __init__(self, api=None):
        self._api = api

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def button(self, *args, **kwargs):
        if self._api is None:
            raise AttributeError("button")
        return self._api.button(*args, **kwargs)


class _Placeholder:
    def __init__(self, messages: list[tuple[str, str]]):
        self._messages = messages

    def empty(self):
        self._messages.append(("placeholder", "empty"))

    def caption(self, message):
        self._messages.append(("caption", str(message)))

    def code(self, message, language=None):
        self._messages.append(("code", str(message)))


class _FakeStreamlit:
    def __init__(self, session_state: dict[str, object] | None = None, *, buttons: dict[str, bool] | None = None):
        self.session_state = _State(session_state or {})
        self._buttons = buttons or {}
        self.messages: list[tuple[str, str]] = []

    def fragment(self, func):
        return func

    def caption(self, message):
        self.messages.append(("caption", str(message)))

    def pyplot(self, _fig, width=None):
        self.messages.append(("pyplot", str(width)))

    def container(self):
        return _Ctx()

    def expander(self, _label, expanded=False):
        self.messages.append(("expander", str(expanded)))
        return _Ctx()

    def empty(self):
        return _Placeholder(self.messages)

    def columns(self, spec, gap=None):
        count = spec if isinstance(spec, int) else len(spec)
        return [_Ctx(self) for _ in range(count)]

    def checkbox(self, _label, key=None, on_change=None, args=(), value=False, **_kwargs):
        if key is not None:
            self.session_state.setdefault(key, value)
        if on_change and self._buttons.get(f"__checkbox__::{key}", False):
            on_change(*args)
        return bool(self.session_state.get(key, value))

    def text_input(self, _label, value="", key=None, **_kwargs):
        if key is None:
            return value
        self.session_state.setdefault(key, value)
        return str(self.session_state.get(key, value))

    def button(self, _label, key=None, **_kwargs):
        button_key = key or _label
        return bool(self._buttons.get(button_key, False))

    def spinner(self, _label):
        return _Ctx()

    def rerun(self):
        self.messages.append(("rerun", "called"))

    def warning(self, message):
        self.messages.append(("warning", str(message)))

    def info(self, message):
        self.messages.append(("info", str(message)))

    def success(self, message):
        self.messages.append(("success", str(message)))

    def error(self, message):
        self.messages.append(("error", str(message)))

    def code(self, message, language=None):
        self.messages.append(("code", str(message)))


def _make_execute_deps(message_log: list[tuple[str, str]], state: _State):
    def _update_log(_placeholder, message):
        message_log.append(("update_log", str(message)))
        state["log_text"] = state.get("log_text", "") + str(message)

    return orchestrate_execute.OrchestrateExecuteDeps(
        clear_log=lambda: state.__setitem__("log_text", ""),
        update_log=_update_log,
        strip_ansi=lambda text: text,
        reset_traceback_skip=lambda: None,
        append_log_lines=lambda lines, line: lines.append(line),
        display_log=lambda text, stderr: message_log.append(("display_log", f"{text}|{stderr}")),
        rerun_fragment_or_app=lambda: message_log.append(("rerun_fragment_or_app", "called")),
        update_delete_confirm_state=lambda *_args, **_kwargs: False,
        capture_dataframe_preview_state=lambda: {"loaded_df": state.get("loaded_df"), "loaded_graph": state.get("loaded_graph")},
        restore_dataframe_preview_state=lambda payload: state.update(payload),
        generate_profile_report=lambda _df: SimpleNamespace(to_file=lambda path, silent=False: Path(path).write_text("profile")),
        log_display_max_lines=50,
        live_log_min_height=200,
        install_log_height=200,
    )


@pytest.mark.asyncio
async def test_render_execute_section_loads_csv_preview_and_exports(monkeypatch, tmp_path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    first = data_root / "part1.csv"
    second = data_root / "part2.csv"
    first.write_text("value\n1\n", encoding="utf-8")
    second.write_text("value\n2\n", encoding="utf-8")

    fake_st = _FakeStreamlit(
        {
            "app_settings": {"args": {}},
            "df_export_file": str(tmp_path / "export.csv"),
            "profile_report_file": tmp_path / "profile.html",
        },
        buttons={"load_data_main": True, "export_df_main": True},
    )
    monkeypatch.setattr(orchestrate_execute, "st", fake_st)

    class _Loader:
        def __call__(self, path, with_index=False, nrows=0):
            return pd.read_csv(path)

        def clear(self):
            fake_st.messages.append(("clear", "cached_load_df"))

    class _Finder:
        def clear(self):
            fake_st.messages.append(("clear", "find_files"))

    monkeypatch.setattr(orchestrate_execute, "cached_load_df", _Loader())
    monkeypatch.setattr(orchestrate_execute, "find_files", _Finder())
    monkeypatch.setattr(
        orchestrate_execute,
        "render_dataframe_preview",
        lambda df, truncation_label=None: fake_st.messages.append(("preview", f"{len(df)} rows")),
    )
    monkeypatch.setattr(
        orchestrate_execute,
        "save_csv",
        lambda df, target: Path(target).write_text(df.to_csv(index=False), encoding="utf-8") or True,
    )

    env = SimpleNamespace(
        dataframe_path=data_root,
        app_data_rel=None,
        runenv=tmp_path / "runenv",
        app="flight_project",
        wenv_abs=tmp_path / "wenv",
    )
    deps = _make_execute_deps(fake_st.messages, fake_st.session_state)

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="print('run')",
        deps=deps,
    )

    exported = Path(fake_st.session_state["df_export_file"])
    assert exported.exists()
    assert "__source__" in fake_st.session_state["loaded_df"].columns
    assert any(kind == "success" and "Loaded dataframe preview from 2 files" in msg for kind, msg in fake_st.messages)
    assert any(kind == "success" and "Dataframe exported successfully" in msg for kind, msg in fake_st.messages)
    assert any(kind == "preview" for kind, _ in fake_st.messages)


@pytest.mark.asyncio
async def test_render_execute_section_delete_and_undo_restores_file(monkeypatch, tmp_path):
    source_file = tmp_path / "result.csv"
    source_file.write_text("value\n1\n", encoding="utf-8")

    fake_st = _FakeStreamlit(
        {
            "app_settings": {"args": {}},
            "delete_data_main_confirm": True,
            "loaded_df": pd.DataFrame({"value": [1]}),
            "loaded_source_path": str(source_file),
            "df_export_file": str(tmp_path / "export.csv"),
            "profile_report_file": tmp_path / "profile.html",
        },
        buttons={"delete_data_main_confirm_btn": True},
    )
    monkeypatch.setattr(orchestrate_execute, "st", fake_st)
    monkeypatch.setattr(
        orchestrate_execute,
        "cached_load_df",
        SimpleNamespace(clear=lambda: fake_st.messages.append(("clear", "cached_load_df"))),
    )
    monkeypatch.setattr(
        orchestrate_execute,
        "find_files",
        SimpleNamespace(clear=lambda: fake_st.messages.append(("clear", "find_files"))),
    )

    env = SimpleNamespace(
        dataframe_path=tmp_path,
        app_data_rel=None,
        runenv=tmp_path / "runenv",
        app="flight_project",
        wenv_abs=tmp_path / "wenv",
    )
    deps = _make_execute_deps(fake_st.messages, fake_st.session_state)

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="print('run')",
        deps=deps,
    )

    assert not source_file.exists()
    backup_path = Path(fake_st.session_state["delete_data_main_undo_payload"]["backup_file"])
    assert backup_path.exists()
    assert fake_st.session_state["loaded_df"] is None

    fake_st._buttons["delete_data_main_undo_btn"] = True
    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_project",
        controls_visible=True,
        show_run_panel=True,
        cmd=None,
        deps=deps,
    )

    assert source_file.exists()
    assert "delete_data_main_undo_payload" not in fake_st.session_state
    assert isinstance(fake_st.session_state["loaded_df"], pd.DataFrame)
    assert any(kind == "success" and "restore" in msg.lower() for kind, msg in fake_st.messages)


@pytest.mark.asyncio
async def test_render_execute_section_run_requires_installed_venvs(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit(
        {
            "app_settings": {"args": {}},
            "df_export_file": str(tmp_path / "export.csv"),
            "profile_report_file": tmp_path / "profile.html",
        },
        buttons={"run_btn": True},
    )
    monkeypatch.setattr(orchestrate_execute, "st", fake_st)

    env = SimpleNamespace(
        dataframe_path=tmp_path,
        app_data_rel=None,
        runenv=tmp_path / "runenv",
        app="flight_project",
        wenv_abs=tmp_path / "wenv",
    )
    deps = _make_execute_deps(fake_st.messages, fake_st.session_state)

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="print('run')",
        deps=deps,
    )

    assert any(kind == "error" and "installation is incomplete" in msg for kind, msg in fake_st.messages)


@pytest.mark.asyncio
async def test_render_execute_section_loads_json_graph_payload(monkeypatch, tmp_path):
    graph_file = tmp_path / "graph.json"
    graph_file.write_text(
        json.dumps(
            {
                "directed": True,
                "multigraph": False,
                "graph": {},
                "nodes": [{"id": "a"}, {"id": "b"}],
                "links": [{"source": "a", "target": "b"}],
                "edges": [{"source": "a", "target": "b"}],
            }
        ),
        encoding="utf-8",
    )

    fake_st = _FakeStreamlit(
        {
            "app_settings": {"args": {}},
            "df_export_file": str(tmp_path / "export.csv"),
            "profile_report_file": tmp_path / "profile.html",
        },
        buttons={"load_data_main": True},
    )
    monkeypatch.setattr(orchestrate_execute, "st", fake_st)
    monkeypatch.setattr(orchestrate_execute, "_render_graph_preview", lambda graph, source: fake_st.messages.append(("graph", source or "")))

    env = SimpleNamespace(
        dataframe_path=graph_file,
        app_data_rel=None,
        runenv=tmp_path / "runenv",
        app="flight_project",
        wenv_abs=tmp_path / "wenv",
    )
    deps = _make_execute_deps(fake_st.messages, fake_st.session_state)

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="print('run')",
        deps=deps,
    )

    assert fake_st.session_state.get("loaded_df") is None
    assert fake_st.session_state["loaded_graph"].number_of_edges() == 1
    assert any(kind == "success" and "Loaded network graph" in msg for kind, msg in fake_st.messages)
    assert ("graph", "graph.json") in fake_st.messages


@pytest.mark.asyncio
async def test_render_execute_section_run_executes_and_records_logs(monkeypatch, tmp_path):
    manager_venv = tmp_path / "project" / ".venv"
    worker_venv = tmp_path / "wenv" / ".venv"
    manager_venv.mkdir(parents=True)
    worker_venv.mkdir(parents=True)

    fake_st = _FakeStreamlit(
        {
            "app_settings": {"args": {}},
            "benchmark": True,
            "df_export_file": str(tmp_path / "export.csv"),
            "profile_report_file": tmp_path / "profile.html",
        },
        buttons={"run_btn": True},
    )
    monkeypatch.setattr(orchestrate_execute, "st", fake_st)

    async def _run_agi(cmd, log_callback=None, venv=None):
        log_callback("first line")
        log_callback("\u001b[31msecond line\u001b[0m")
        return "", "stderr text"

    env = SimpleNamespace(
        dataframe_path=tmp_path,
        app_data_rel=None,
        runenv=tmp_path / "runenv",
        app="flight_project",
        wenv_abs=tmp_path / "wenv",
        snippet_tail="pass",
        run_agi=_run_agi,
    )
    deps = _make_execute_deps(fake_st.messages, fake_st.session_state)

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="asyncio.run(main())",
        deps=deps,
    )

    log_path = Path(fake_st.session_state["last_run_log_path"])
    assert log_path.exists()
    assert "first line" in log_path.read_text(encoding="utf-8")
    assert fake_st.session_state["run_log_cache"]
    assert fake_st.session_state["_benchmark_expand"] is True
    assert any(kind == "display_log" and "stderr text" in msg for kind, msg in fake_st.messages)
    assert ("rerun", "called") in fake_st.messages


@pytest.mark.asyncio
async def test_render_execute_section_handles_json_table_and_invalid_json(monkeypatch, tmp_path):
    tabular_json = tmp_path / "table.json"
    tabular_json.write_text(json.dumps({"rows": [{"value": 1}, {"value": 2}]}), encoding="utf-8")

    fake_st = _FakeStreamlit(
        {
            "app_settings": {"args": {}},
            "df_export_file": str(tmp_path / "export.csv"),
            "profile_report_file": tmp_path / "profile.html",
        },
        buttons={"load_data_main": True},
    )
    monkeypatch.setattr(orchestrate_execute, "st", fake_st)

    env = SimpleNamespace(
        dataframe_path=tabular_json,
        app_data_rel=None,
        runenv=tmp_path / "runenv",
        app="flight_project",
        wenv_abs=tmp_path / "wenv",
    )
    deps = _make_execute_deps(fake_st.messages, fake_st.session_state)

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="print('run')",
        deps=deps,
    )

    assert isinstance(fake_st.session_state["loaded_df"], pd.DataFrame)
    assert any(kind == "info" and "Parsed JSON payload as tabular data" in msg for kind, msg in fake_st.messages)

    broken_json = tmp_path / "broken.json"
    broken_json.write_text("{not-json", encoding="utf-8")
    fake_st = _FakeStreamlit(
        {
            "app_settings": {"args": {}},
            "df_export_file": str(tmp_path / "export.csv"),
            "profile_report_file": tmp_path / "profile.html",
        },
        buttons={"load_data_main": True},
    )
    monkeypatch.setattr(orchestrate_execute, "st", fake_st)
    env.dataframe_path = broken_json

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="print('run')",
        deps=_make_execute_deps(fake_st.messages, fake_st.session_state),
    )

    assert any(kind == "error" and "Failed to decode JSON" in msg for kind, msg in fake_st.messages)


@pytest.mark.asyncio
async def test_render_execute_section_handles_existing_logs_graph_errors_and_stats(monkeypatch, tmp_path):
    profile_path = tmp_path / "profile.html"
    fake_st = _FakeStreamlit(
        {
            "app_settings": {"args": {}},
            "run_log_cache": "cached log",
            "loaded_df": pd.DataFrame({"": [1], "value": [2]}),
            "loaded_graph": orchestrate_execute.nx.Graph(),
            "loaded_source_path": object(),
            "df_export_file": "",
            "profile_report_file": profile_path,
            "selected_cols": [],
            "df_cols": ["", "value"],
            "export_tab_previous_project": "flight_project",
            "check_all": False,
            "export_col_0": False,
            "export_col_1": False,
        },
        buttons={"stats_report_main": True, "export_df_main": True},
    )
    fake_st.session_state["loaded_graph"].add_node("n1")
    monkeypatch.setattr(orchestrate_execute, "st", fake_st)
    monkeypatch.setattr(
        orchestrate_execute,
        "render_dataframe_preview",
        lambda df, truncation_label=None: fake_st.messages.append(("preview", ",".join(df.columns))),
    )
    monkeypatch.setattr(
        orchestrate_execute,
        "_render_graph_preview",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("graph boom")),
    )
    opened: list[str] = []
    monkeypatch.setattr(orchestrate_execute, "open_new_tab", lambda uri: opened.append(uri))

    class _Profile:
        def to_file(self, path, silent=False):
            Path(path).write_text("profile", encoding="utf-8")

    env = SimpleNamespace(
        dataframe_path=tmp_path,
        app_data_rel=None,
        runenv=tmp_path / "runenv",
        app="flight_project",
        wenv_abs=tmp_path / "wenv",
    )

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="print('run')",
        deps=_make_execute_deps(fake_st.messages, fake_st.session_state),
    )

    assert any(kind == "code" and "cached log" in msg for kind, msg in fake_st.messages)
    assert any(kind == "preview" and ",value" in msg for kind, msg in fake_st.messages)
    assert any(kind == "warning" and "Please provide a filename for the export." in msg for kind, msg in fake_st.messages)
    assert opened and opened[0].startswith("file:")
    assert not profile_path.exists()

    graph_only_st = _FakeStreamlit(
        {
            "app_settings": {"args": {}},
            "loaded_graph": orchestrate_execute.nx.Graph(),
            "loaded_source_path": object(),
            "df_export_file": str(tmp_path / "export.csv"),
            "profile_report_file": tmp_path / "other_profile.html",
        }
    )
    graph_only_st.session_state["loaded_graph"].add_node("n1")
    monkeypatch.setattr(orchestrate_execute, "st", graph_only_st)

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_project",
        controls_visible=True,
        show_run_panel=False,
        cmd=None,
        deps=_make_execute_deps(graph_only_st.messages, graph_only_st.session_state),
    )

    assert any(kind == "error" and "Unable to render graph preview" in msg for kind, msg in graph_only_st.messages)


@pytest.mark.asyncio
async def test_render_execute_section_load_deleted_and_combo_without_cmd(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit(
        {
            "app_settings": {"args": {}},
            "dataframe_deleted": True,
            orchestrate_execute.PENDING_EXECUTE_ACTION_KEY: "load",
            "df_export_file": str(tmp_path / "export.csv"),
            "profile_report_file": tmp_path / "profile.html",
        }
    )
    monkeypatch.setattr(orchestrate_execute, "st", fake_st)

    env = SimpleNamespace(
        dataframe_path=tmp_path / "missing",
        app_data_rel=None,
        runenv=tmp_path / "runenv",
        app="flight_project",
        wenv_abs=tmp_path / "wenv",
    )

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="print('run')",
        deps=_make_execute_deps(fake_st.messages, fake_st.session_state),
    )

    assert any(kind == "info" and "Run EXECUTE again" in msg for kind, msg in fake_st.messages)

    combo_st = _FakeStreamlit(
        {
            "app_settings": {"args": {}},
            orchestrate_execute.PENDING_EXECUTE_ACTION_KEY: "combo",
            "df_export_file": str(tmp_path / "export.csv"),
            "profile_report_file": tmp_path / "profile.html",
        }
    )
    monkeypatch.setattr(orchestrate_execute, "st", combo_st)

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_project",
        controls_visible=True,
        show_run_panel=True,
        cmd=None,
        deps=_make_execute_deps(combo_st.messages, combo_st.session_state),
    )

    assert any(kind == "error" and "No EXECUTE command configured" in msg for kind, msg in combo_st.messages)
    assert combo_st.session_state["_combo_load_trigger"] is True
    assert combo_st.session_state["_combo_export_trigger"] is True
