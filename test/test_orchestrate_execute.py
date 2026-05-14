from __future__ import annotations

import importlib
import importlib.util
import json
import os
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


def _load_orchestrate_execute_with_missing(module_suffix: str, *missing_modules: str):
    module_name = f"agilab.orchestrate_execute_missing_{module_suffix}"
    module_path = Path("src/agilab/orchestrate_execute.py")
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    original_import = __import__

    def _patched_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in missing_modules:
            raise ModuleNotFoundError(name)
        return original_import(name, globals, locals, fromlist, level)

    import builtins

    previous = builtins.__import__
    builtins.__import__ = _patched_import
    try:
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    finally:
        builtins.__import__ = previous
    return module


def _load_orchestrate_execute_with_missing_matplotlib():
    return _load_orchestrate_execute_with_missing("matplotlib", "matplotlib", "matplotlib.pyplot")


def _load_orchestrate_execute_with_missing_networkx():
    return _load_orchestrate_execute_with_missing("networkx", "networkx", "networkx.readwrite")


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


def test_orchestrate_execute_import_records_missing_matplotlib():
    fallback = _load_orchestrate_execute_with_missing_matplotlib()

    assert fallback.plt is None
    assert isinstance(fallback._MATPLOTLIB_IMPORT_ERROR, ModuleNotFoundError)


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


def test_collect_candidate_roots_resolves_app_args_with_share_path(tmp_path):
    share_root = tmp_path / "clustershare"

    def _resolve_share_path(raw_path: Path | str) -> Path:
        return share_root / Path(raw_path)

    env = SimpleNamespace(
        dataframe_path=None,
        app_data_rel=None,
        resolve_share_path=_resolve_share_path,
    )
    roots = orchestrate_execute.collect_candidate_roots(
        env,
        {
            "data_in": "flight/dataset",
            "data_out": "flight/dataframe",
        },
    )

    assert roots == [
        share_root / "flight/dataframe",
        share_root / "flight/dataset",
    ]


def test_collect_candidate_roots_falls_back_to_home_when_share_resolution_fails(tmp_path, monkeypatch):
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setattr(
        orchestrate_execute.Path,
        "home",
        classmethod(lambda cls: home_dir),
    )

    def _resolve_share_path(*_args, **_kwargs):
        raise OSError("share unavailable")

    env = SimpleNamespace(
        dataframe_path=Path("relative/data"),
        app_data_rel=None,
        resolve_share_path=_resolve_share_path,
    )
    roots = orchestrate_execute.collect_candidate_roots(
        env,
        {
            "data_out": "flight/output",
            "data_in": "flight/input",
        },
    )

    assert roots == [home_dir / "relative/data", home_dir / "flight/output"]
    assert str(home_dir / "relative/data") in [str(roots[0]), str(roots[1])]


def test_collect_candidate_roots_skips_data_in_when_share_unavailable(monkeypatch, tmp_path):
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setattr(
        orchestrate_execute.Path,
        "home",
        classmethod(lambda cls: home_dir),
    )

    def _resolve_share_path(*_args, **_kwargs):
        raise TypeError("share not configured")

    env = SimpleNamespace(
        dataframe_path="dataframe",
        app_data_rel=None,
        resolve_share_path=_resolve_share_path,
    )
    roots = orchestrate_execute.collect_candidate_roots(
        env,
        {
            "data_out": "flight/output",
            "data_in": "flight/input",
        },
    )

    assert roots == [home_dir / "dataframe", home_dir / "flight/output"]
    assert all("flight/input" not in str(root) for root in roots)


def test_collect_candidate_roots_keeps_absolute_data_in_without_share(monkeypatch, tmp_path):
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setattr(
        orchestrate_execute.Path,
        "home",
        classmethod(lambda cls: home_dir),
    )
    absolute_data_in = tmp_path / "shared" / "forced" / "input"

    def _resolve_share_path(*_args, **_kwargs):
        raise ValueError("share path cannot be resolved")

    env = SimpleNamespace(
        dataframe_path="local/data",
        app_data_rel=None,
        resolve_share_path=_resolve_share_path,
    )
    roots = orchestrate_execute.collect_candidate_roots(
        env,
        {
            "data_in": str(absolute_data_in),
            "data_out": "flight/output",
        },
    )

    assert absolute_data_in in roots
    assert absolute_data_in == roots[1] or roots[-1] == absolute_data_in
    assert home_dir / "local/data" in roots


def test_is_preview_metadata_file_detects_metadata_names():
    assert orchestrate_execute._is_preview_metadata_file(orchestrate_execute.Path("run_manifest.json"))
    assert orchestrate_execute._is_preview_metadata_file(orchestrate_execute.Path("reduce_summary_worker_0.json"))
    assert orchestrate_execute._is_preview_metadata_file(orchestrate_execute.Path("._cache.csv"))
    assert not orchestrate_execute._is_preview_metadata_file(orchestrate_execute.Path("dataset.csv"))


def test_find_preview_target_ignores_empty_and_metadata_files(tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    empty_csv = output_dir / "empty.csv"
    empty_csv.write_text("")

    metadata_csv = output_dir / "._artifact.csv"
    metadata_csv.write_text("metadata")

    reduce_summary = output_dir / "reduce_summary_worker_0.json"
    reduce_summary.write_text('{"name": "flight_reduce_summary"}', encoding="utf-8")

    valid_csv = output_dir / "artifact.csv"
    valid_csv.write_text("a,b\n1,2\n")
    os.utime(reduce_summary, (valid_csv.stat().st_mtime + 5, valid_csv.stat().st_mtime + 5))

    target, files = orchestrate_execute.find_preview_target([output_dir])

    assert target == valid_csv
    assert files == [valid_csv]


def test_find_preview_target_prefers_flight_dataframe_over_newer_reduce_summary(tmp_path):
    output_dir = tmp_path / "flight" / "dataframe"
    output_dir.mkdir(parents=True)

    plane_60 = output_dir / "60.parquet"
    plane_60.write_text("parquet placeholder for plane 60", encoding="utf-8")
    plane_61 = output_dir / "61.parquet"
    plane_61.write_text("parquet placeholder for plane 61", encoding="utf-8")
    reduce_summary = output_dir / "reduce_summary_worker_0.json"
    reduce_summary.write_text('{"name": "flight_reduce_summary"}', encoding="utf-8")
    run_manifest = output_dir / "run_manifest.json"
    run_manifest.write_text('{"kind": "agilab.run_manifest"}', encoding="utf-8")

    base_mtime = plane_60.stat().st_mtime
    os.utime(plane_60, (base_mtime, base_mtime))
    os.utime(plane_61, (base_mtime + 1, base_mtime + 1))
    os.utime(reduce_summary, (base_mtime + 10, base_mtime + 10))
    os.utime(run_manifest, (base_mtime + 11, base_mtime + 11))

    target, files = orchestrate_execute.find_preview_target([output_dir])

    assert target == plane_61
    assert files == [plane_60, plane_61]


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
            if newest_calls["count"] >= 4:
                raise FileNotFoundError("simulated race")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(orchestrate_execute.Path, "stat", flaky_stat)

    target, files = orchestrate_execute.find_preview_target([older_csv, newest_csv])

    assert target is None
    assert files == [older_csv, newest_csv]


def test_find_preview_target_returns_none_when_only_hidden_or_empty_files_exist(tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "._artifact.csv").write_text("hidden", encoding="utf-8")
    (output_dir / "empty.csv").write_text("", encoding="utf-8")

    target, files = orchestrate_execute.find_preview_target([output_dir])

    assert target is None
    assert files == []


def test_find_preview_target_caps_candidate_search(tmp_path, monkeypatch):
    files = []
    for index in range(3):
        file_path = tmp_path / f"artifact_{index}.csv"
        file_path.write_text("a,b\n1,2\n", encoding="utf-8")
        files.append(file_path)

    monkeypatch.setattr(orchestrate_execute, "PREVIEW_MAX_SEARCH_FILES", 2)

    target, found_files = orchestrate_execute.find_preview_target(files)

    assert target in files[:2]
    assert found_files == files[:2]


def test_preview_candidate_paths_are_sorted_before_search_cap(tmp_path, monkeypatch):
    root = tmp_path / "output"
    root.mkdir()
    first = root / "a.csv"
    second = root / "b.csv"
    first.write_text("a,b\n1,2\n", encoding="utf-8")
    second.write_text("a,b\n3,4\n", encoding="utf-8")

    def fake_rglob(self, pattern):
        if self == root and pattern == "*.csv":
            return [second, first]
        return []

    monkeypatch.setattr(orchestrate_execute.Path, "rglob", fake_rglob)
    monkeypatch.setattr(orchestrate_execute, "PREVIEW_MAX_SEARCH_FILES", 1)

    assert orchestrate_execute._preview_candidate_paths([root]) == [first]


def test_preview_candidate_paths_removes_duplicates_across_roots(tmp_path):
    root = tmp_path / "output"
    root.mkdir()
    first = root / "a.csv"
    second = root / "b.csv"
    first.write_text("a,b\n1,2\n", encoding="utf-8")
    second.write_text("a,b\n3,4\n", encoding="utf-8")

    candidates = orchestrate_execute._preview_candidate_paths([root, root])

    assert candidates == [first, second]


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        (None, False),
        ("", False),
        ("  ", False),
        ("all good", False),
        ("Command failed with exit code 2", True),
        ("RuntimeError: crash", True),
        ("Process exited with non-zero exit status 127", True),
        ("Traceback (most recent call last):", True),
        ("No virtual environment found", True),
    ],
)
def test_run_stderr_indicates_failure(stderr, expected):
    assert orchestrate_execute._run_stderr_indicates_failure(stderr) is expected


def test_render_execute_notice_unknown_kind_uses_info():
    fake_st = _FakeStreamlit()
    fake_st.session_state[orchestrate_execute.EXECUTE_NOTICE_KEY] = {
        "kind": "not-a-kind",
        "message": "Fallback visible",
    }

    orchestrate_execute.render_execute_notice(fake_st, fake_st.session_state)

    assert ("info", "Fallback visible") in fake_st.messages
    assert orchestrate_execute.EXECUTE_NOTICE_KEY not in fake_st.session_state


def test_find_preview_target_skips_oversized_files(tmp_path, monkeypatch):
    small_csv = tmp_path / "small.csv"
    small_csv.write_text("a,b\n1,2\n", encoding="utf-8")
    large_csv = tmp_path / "large.csv"
    large_csv.write_text("a,b\n" + ("x" * 50), encoding="utf-8")

    monkeypatch.setattr(orchestrate_execute, "PREVIEW_MAX_FILE_BYTES", 12)

    target, found_files = orchestrate_execute.find_preview_target([large_csv, small_csv])

    assert target == small_csv
    assert found_files == [small_csv]


def test_pending_execute_action_round_trip():
    session_state = {}

    assert orchestrate_execute.consume_pending_execute_action(session_state) is None

    orchestrate_execute.queue_pending_execute_action(session_state, "run")
    assert session_state[orchestrate_execute.PENDING_EXECUTE_ACTION_KEY] == "run"
    assert orchestrate_execute.consume_pending_execute_action(session_state) == "run"
    assert orchestrate_execute.consume_pending_execute_action(session_state) is None


def test_execute_notice_round_trip_renders_and_clears():
    fake_st = _FakeStreamlit()
    orchestrate_execute.queue_execute_notice(fake_st.session_state, kind="success", message="Loaded output.")

    orchestrate_execute.render_execute_notice(fake_st, fake_st.session_state)

    assert ("success", "Loaded output.") in fake_st.messages
    assert orchestrate_execute.EXECUTE_NOTICE_KEY not in fake_st.session_state


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


def test_orchestrate_execute_import_survives_missing_networkx():
    module = _load_orchestrate_execute_with_missing_networkx()

    assert module.nx is None
    assert module.json_graph is None
    assert isinstance(module._NETWORKX_IMPORT_ERROR, ModuleNotFoundError)
    assert module._is_networkx_graph(object()) is False
    with pytest.raises(RuntimeError, match=r"agilab\[ui\]"):
        module._render_graph_preview(object(), None)


@pytest.mark.parametrize(
    ("app_state_name", "env_app", "target", "base_worker_cls", "expected"),
    [
        ("workflow_project", "workflow_project", "workflow", "DagWorker", True),
        ("sb3_trainer_project", "sb3_trainer_project", "sb3_trainer", "Sb3TrainerWorker", True),
        ("custom_project", "custom_project", "custom", "CustomDagWorker", True),
        ("global_dag_project", "global_dag_project", "global_dag", "PolarsWorker", True),
        ("custom_dag_project", "custom_dag_project", "custom_dag", None, True),
        ("dag_app_template", "your_dag_project", "dag_app", None, True),
        ("flight_telemetry_project", "flight_telemetry_project", "flight", "PolarsWorker", False),
        ("tescia_diagnostic_project", "tescia_diagnostic_project", "tescia_diagnostic", "PandasWorker", False),
    ],
)
def test_is_dag_based_app_detects_env_worker_base_first(app_state_name, env_app, target, base_worker_cls, expected):
    env = SimpleNamespace(app=env_app, target=target, base_worker_cls=base_worker_cls)

    assert orchestrate_execute._is_dag_based_app(env, app_state_name) is expected


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
        self.button_calls: list[tuple[str, dict[str, object]]] = []

    def fragment(self, func):
        return func

    def caption(self, message):
        self.messages.append(("caption", str(message)))

    def markdown(self, message):
        self.messages.append(("markdown", str(message)))

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
        self.button_calls.append((str(key or _label), dict(_kwargs)))
        if _kwargs.get("disabled"):
            return False
        button_key = key or _label
        return bool(self._buttons.get(button_key, False))

    def download_button(self, _label, *, key=None, **_kwargs):
        self.messages.append(("download_button", str(key or _label)))
        return False

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
        app="flight_telemetry_project",
        wenv_abs=tmp_path / "wenv",
    )
    deps = _make_execute_deps(fake_st.messages, fake_st.session_state)

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_telemetry_project",
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
    assert fake_st.session_state[orchestrate_execute.EXECUTE_NOTICE_KEY]["kind"] == "success"
    assert ("rerun_fragment_or_app", "called") in fake_st.messages
    assert ("markdown", "#### 5. Execute and inspect outputs") in fake_st.messages
    assert any(kind == "preview" for kind, _ in fake_st.messages)

    fake_st.button_calls.clear()
    fake_st._buttons = {}
    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_telemetry_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="print('run')",
        deps=deps,
    )
    delete_call = next(kwargs for key, kwargs in fake_st.button_calls if key == "delete_data_main")
    assert delete_call["disabled"] is False


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
        app="flight_telemetry_project",
        wenv_abs=tmp_path / "wenv",
    )
    deps = _make_execute_deps(fake_st.messages, fake_st.session_state)

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_telemetry_project",
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
        app_state_name="flight_telemetry_project",
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
        app="flight_telemetry_project",
        wenv_abs=tmp_path / "wenv",
    )
    deps = _make_execute_deps(fake_st.messages, fake_st.session_state)

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_telemetry_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="print('run')",
        deps=deps,
    )

    run_call = next(kwargs for key, kwargs in fake_st.button_calls if key == "run_btn")
    assert run_call["disabled"] is True
    assert "installation is incomplete" in str(run_call["help"])
    assert not any(kind == "error" and "installation is incomplete" in msg for kind, msg in fake_st.messages)


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
        app="flight_telemetry_project",
        wenv_abs=tmp_path / "wenv",
    )
    deps = _make_execute_deps(fake_st.messages, fake_st.session_state)

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_telemetry_project",
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
        app="flight_telemetry_project",
        wenv_abs=tmp_path / "wenv",
        snippet_tail="pass",
        run_agi=_run_agi,
    )
    deps = _make_execute_deps(fake_st.messages, fake_st.session_state)

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_telemetry_project",
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
async def test_render_execute_section_run_failure_keeps_logs_visible(monkeypatch, tmp_path):
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

    async def _run_agi(_cmd, log_callback=None, venv=None):
        if log_callback:
            log_callback("ConnectionError: scheduler host is invalid")
        raise RuntimeError("Command failed (exit 1)")

    env = SimpleNamespace(
        dataframe_path=tmp_path,
        app_data_rel=None,
        runenv=tmp_path / "runenv",
        app="flight_telemetry_project",
        wenv_abs=tmp_path / "wenv",
        snippet_tail="pass",
        run_agi=_run_agi,
    )
    deps = _make_execute_deps(fake_st.messages, fake_st.session_state)

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_telemetry_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="asyncio.run(main())",
        deps=deps,
    )

    assert fake_st.session_state["_last_execute_failed"] is True
    assert "ConnectionError: scheduler host is invalid" in fake_st.session_state["run_log_cache"]
    assert any(kind == "error" and msg == "AGI execution failed." for kind, msg in fake_st.messages)
    assert any(kind == "code" and "ConnectionError: scheduler host is invalid" in msg for kind, msg in fake_st.messages)
    assert fake_st.session_state.get("_benchmark_expand") is not True


@pytest.mark.asyncio
async def test_render_execute_section_can_pin_existing_run_logs(monkeypatch, tmp_path):
    manager_venv = tmp_path / "project" / ".venv"
    worker_venv = tmp_path / "wenv" / ".venv"
    manager_venv.mkdir(parents=True)
    worker_venv.mkdir(parents=True)

    editor_calls: list[dict[str, object]] = []

    def _code_editor(body, **kwargs):
        editor_calls.append({"body": body, **kwargs})
        return {"type": "pin_to_sidebar", "text": body}

    fake_st = _FakeStreamlit(
        {
            "app_settings": {"args": {}},
            "df_export_file": str(tmp_path / "export.csv"),
            "profile_report_file": tmp_path / "profile.html",
            "run_log_cache": "existing log",
            "last_run_log_path": str(tmp_path / "run.log"),
        }
    )
    monkeypatch.setattr(orchestrate_execute, "st", fake_st)
    monkeypatch.setattr(orchestrate_execute, "code_editor", _code_editor)

    env = SimpleNamespace(
        dataframe_path=tmp_path,
        app_data_rel=None,
        runenv=tmp_path / "runenv",
        app="flight_telemetry_project",
        wenv_abs=tmp_path / "wenv",
        snippet_tail="pass",
    )
    deps = _make_execute_deps(fake_st.messages, fake_st.session_state)

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_telemetry_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="asyncio.run(main())",
        deps=deps,
    )

    panels = fake_st.session_state["agilab:pinned_expanders"]
    buttons = editor_calls[-1]["buttons"]
    assert isinstance(buttons, list)
    assert [button["name"] for button in buttons[:2]] == ["Copy", "Pin"]
    assert editor_calls[-1]["theme"] == "dark"
    assert panels["orchestrate_run_logs"]["title"] == "Run logs: flight_telemetry_project"
    assert panels["orchestrate_run_logs"]["body"] == "existing log"
    assert panels["orchestrate_run_logs"]["source"] == f"ORCHESTRATE {tmp_path / 'run.log'}"
    assert ("rerun", "called") in fake_st.messages


@pytest.mark.asyncio
async def test_render_execute_section_skips_log_pin_editor_without_run_logs(monkeypatch, tmp_path):
    manager_venv = tmp_path / "project" / ".venv"
    worker_venv = tmp_path / "wenv" / ".venv"
    manager_venv.mkdir(parents=True)
    worker_venv.mkdir(parents=True)

    fake_st = _FakeStreamlit(
        {
            "app_settings": {"args": {}},
            "df_export_file": str(tmp_path / "export.csv"),
            "profile_report_file": tmp_path / "profile.html",
        },
    )
    monkeypatch.setattr(orchestrate_execute, "st", fake_st)
    monkeypatch.setattr(
        orchestrate_execute,
        "code_editor",
        lambda *_args, **_kwargs: pytest.fail("empty logs should not render code editor"),
    )

    env = SimpleNamespace(
        dataframe_path=tmp_path,
        app_data_rel=None,
        runenv=tmp_path / "runenv",
        app="flight_telemetry_project",
        wenv_abs=tmp_path / "wenv",
        snippet_tail="pass",
    )
    deps = _make_execute_deps(fake_st.messages, fake_st.session_state)

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_telemetry_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="asyncio.run(main())",
        deps=deps,
    )

    assert all(
        key != "pinned_expander:toggle:orchestrate_run_logs"
        for key, _kwargs in fake_st.button_calls
    )
    assert ("caption", "No run logs yet.") in fake_st.messages


@pytest.mark.asyncio
async def test_render_execute_section_source_env_uses_app_runtime(monkeypatch, tmp_path):
    manager_venv = tmp_path / "project" / ".venv"
    worker_venv = tmp_path / "wenv" / ".venv"
    controller_root = tmp_path / "controller"
    manager_venv.mkdir(parents=True)
    worker_venv.mkdir(parents=True)
    controller_root.mkdir()

    fake_st = _FakeStreamlit(
        {
            "app_settings": {"args": {}},
            "df_export_file": str(tmp_path / "export.csv"),
            "profile_report_file": tmp_path / "profile.html",
        },
        buttons={"run_btn": True},
    )
    monkeypatch.setattr(orchestrate_execute, "st", fake_st)

    captured: dict[str, object] = {}

    async def _run_agi(cmd, log_callback=None, venv=None):
        captured["cmd"] = cmd
        captured["venv"] = venv
        if log_callback:
            log_callback("source-env line")
        return "", ""

    env = SimpleNamespace(
        dataframe_path=tmp_path,
        app_data_rel=None,
        runenv=tmp_path / "runenv",
        app="flight_telemetry_project",
        wenv_abs=tmp_path / "wenv",
        snippet_tail="pass",
        run_agi=_run_agi,
        is_source_env=True,
        is_worker_env=False,
        agi_cluster=controller_root,
    )
    deps = _make_execute_deps(fake_st.messages, fake_st.session_state)

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_telemetry_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="asyncio.run(main())",
        deps=deps,
    )

    assert Path(captured["venv"]) == tmp_path / "project"


@pytest.mark.asyncio
async def test_render_execute_section_fatal_returned_stderr_blocks_combo_load(monkeypatch, tmp_path):
    manager_venv = tmp_path / "project" / ".venv"
    worker_venv = tmp_path / "wenv" / ".venv"
    manager_venv.mkdir(parents=True)
    worker_venv.mkdir(parents=True)

    fake_st = _FakeStreamlit(
        {
            "app_settings": {"args": {}},
            "df_export_file": str(tmp_path / "export.csv"),
            "profile_report_file": tmp_path / "profile.html",
        },
        buttons={"combo_exec_load_export": True},
    )
    monkeypatch.setattr(orchestrate_execute, "st", fake_st)

    async def _run_agi(_cmd, log_callback=None, venv=None):
        if log_callback:
            log_callback("No virtual environment found in /tmp/controller. Run INSTALL first.")
        return "", "No virtual environment found in /tmp/controller. Run INSTALL first."

    env = SimpleNamespace(
        dataframe_path=tmp_path,
        app_data_rel=None,
        runenv=tmp_path / "runenv",
        app="uav_relay_queue_project",
        wenv_abs=tmp_path / "wenv",
        snippet_tail="pass",
        run_agi=_run_agi,
    )

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="uav_relay_queue_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="asyncio.run(main())",
        deps=_make_execute_deps(fake_st.messages, fake_st.session_state),
    )

    assert fake_st.session_state["_last_execute_failed"] is True
    assert "_combo_load_trigger" not in fake_st.session_state
    assert "_combo_export_trigger" not in fake_st.session_state
    assert any(kind == "error" and msg == "AGI execution failed." for kind, msg in fake_st.messages)


@pytest.mark.asyncio
async def test_render_execute_section_load_after_failed_run_shows_failure_not_missing_output(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit(
        {
            "app_settings": {"args": {}},
            orchestrate_execute.PENDING_EXECUTE_ACTION_KEY: "load",
            "_last_execute_failed": True,
            "df_export_file": str(tmp_path / "export.csv"),
            "profile_report_file": tmp_path / "profile.html",
        }
    )
    monkeypatch.setattr(orchestrate_execute, "st", fake_st)
    monkeypatch.setattr(orchestrate_execute, "find_preview_target", lambda *_args, **_kwargs: (None, []))

    env = SimpleNamespace(
        dataframe_path=tmp_path,
        app_data_rel=None,
        runenv=tmp_path / "runenv",
        app="uav_relay_queue_project",
        wenv_abs=tmp_path / "wenv",
    )

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="uav_relay_queue_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="print('run')",
        deps=_make_execute_deps(fake_st.messages, fake_st.session_state),
    )

    assert any(kind == "info" and "Latest EXECUTE failed" in msg for kind, msg in fake_st.messages)
    assert not any(kind == "warning" and "No previewable output found yet" in msg for kind, msg in fake_st.messages)


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
        app="flight_telemetry_project",
        wenv_abs=tmp_path / "wenv",
    )
    deps = _make_execute_deps(fake_st.messages, fake_st.session_state)

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_telemetry_project",
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
        app_state_name="flight_telemetry_project",
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
            "export_tab_previous_project": "flight_telemetry_project",
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
        "code_editor",
        lambda body, **_kwargs: fake_st.messages.append(("code", str(body))),
    )
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
        app="flight_telemetry_project",
        wenv_abs=tmp_path / "wenv",
    )

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_telemetry_project",
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
        app_state_name="flight_telemetry_project",
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
        app="flight_telemetry_project",
        wenv_abs=tmp_path / "wenv",
    )

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_telemetry_project",
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
        app_state_name="flight_telemetry_project",
        controls_visible=True,
        show_run_panel=True,
        cmd=None,
        deps=_make_execute_deps(combo_st.messages, combo_st.session_state),
    )

    assert any(kind == "error" and "No EXECUTE command configured" in msg for kind, msg in combo_st.messages)
    assert "_combo_load_trigger" not in combo_st.session_state
    assert "_combo_export_trigger" not in combo_st.session_state


@pytest.mark.asyncio
async def test_render_execute_section_uses_artifact_state_for_load_and_delete_buttons(monkeypatch, tmp_path):
    deleted_st = _FakeStreamlit(
        {
            "app_settings": {"args": {}},
            "dataframe_deleted": True,
            "df_export_file": str(tmp_path / "export.csv"),
            "profile_report_file": tmp_path / "profile.html",
        },
        buttons={"load_data_main": True},
    )
    monkeypatch.setattr(orchestrate_execute, "st", deleted_st)

    env = SimpleNamespace(
        dataframe_path=tmp_path,
        app_data_rel=None,
        runenv=tmp_path / "runenv",
        app="flight_telemetry_project",
        wenv_abs=tmp_path / "wenv",
    )

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_telemetry_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="print('run')",
        deps=_make_execute_deps(deleted_st.messages, deleted_st.session_state),
    )

    load_call = next(kwargs for key, kwargs in deleted_st.button_calls if key == "load_data_main")
    delete_call = next(kwargs for key, kwargs in deleted_st.button_calls if key == "delete_data_main")
    assert load_call["disabled"] is True
    assert "Run EXECUTE again" in str(load_call["help"])
    assert delete_call["disabled"] is True

    loaded_st = _FakeStreamlit(
        {
            "app_settings": {"args": {}},
            "loaded_df": pd.DataFrame({"value": [1]}),
            "loaded_source_path": str(tmp_path / "result.csv"),
            "df_export_file": str(tmp_path / "export.csv"),
            "profile_report_file": tmp_path / "profile.html",
        },
    )
    monkeypatch.setattr(orchestrate_execute, "st", loaded_st)
    monkeypatch.setattr(orchestrate_execute, "render_dataframe_preview", lambda *_args, **_kwargs: None)

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_telemetry_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="print('run')",
        deps=_make_execute_deps(loaded_st.messages, loaded_st.session_state),
    )

    loaded_delete_call = next(kwargs for key, kwargs in loaded_st.button_calls if key == "delete_data_main")
    stats_call = next(kwargs for key, kwargs in loaded_st.button_calls if key == "stats_report_main")
    export_call = next(kwargs for key, kwargs in loaded_st.button_calls if key == "export_df_main")
    assert loaded_delete_call["disabled"] is False
    assert stats_call["disabled"] is False
    assert export_call["disabled"] is False


@pytest.mark.asyncio
async def test_render_execute_section_combo_button_queues_action(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit(
        {
            "app_settings": {"args": {}},
            "df_export_file": str(tmp_path / "export.csv"),
            "profile_report_file": tmp_path / "profile.html",
        },
        buttons={"combo_exec_load_export": True},
    )
    monkeypatch.setattr(orchestrate_execute, "st", fake_st)

    env = SimpleNamespace(
        dataframe_path=tmp_path,
        app_data_rel=None,
        runenv=tmp_path / "runenv",
        app="flight_telemetry_project",
        wenv_abs=tmp_path / "wenv",
    )

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_telemetry_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="print('run')",
        deps=_make_execute_deps(fake_st.messages, fake_st.session_state),
    )

    combo_call = next(kwargs for key, kwargs in fake_st.button_calls if key == "combo_exec_load_export")
    assert combo_call["disabled"] is True
    assert "installation is incomplete" in str(combo_call["help"])
    assert not any(kind == "rerun" and msg == "called" for kind, msg in fake_st.messages)
    assert "_combo_load_trigger" not in fake_st.session_state
    assert "_combo_export_trigger" not in fake_st.session_state


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("app_state_name", "env_app", "target"),
    [
        ("global_dag_project", "global_dag_project", "global_dag"),
        ("custom_dag_project", "custom_dag_project", "custom_dag"),
        ("workflow_project", "workflow_project", "workflow"),
    ],
)
async def test_render_execute_section_dag_based_project_uses_run_only_controls(
    monkeypatch,
    tmp_path,
    app_state_name,
    env_app,
    target,
):
    fake_st = _FakeStreamlit(
        {
            "app_settings": {"args": {}},
            orchestrate_execute.PENDING_EXECUTE_ACTION_KEY: "combo",
            "_combo_load_trigger": True,
            "_combo_export_trigger": True,
            "df_export_file": str(tmp_path / "export.csv"),
            "profile_report_file": tmp_path / "profile.html",
            "loaded_df": pd.DataFrame({"stage": ["done"]}),
            "loaded_source_path": tmp_path / "stale.csv",
        },
        buttons={"combo_exec_load_export": True, "load_data_main": True},
    )
    monkeypatch.setattr(orchestrate_execute, "st", fake_st)

    env = SimpleNamespace(
        dataframe_path=tmp_path,
        app_data_rel=None,
        runenv=tmp_path / "runenv",
        app=env_app,
        target=target,
        base_worker_cls="DagWorker" if app_state_name == "workflow_project" else None,
        wenv_abs=tmp_path / "wenv",
    )

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name=app_state_name,
        controls_visible=True,
        show_run_panel=True,
        cmd="print('run')",
        deps=_make_execute_deps(fake_st.messages, fake_st.session_state),
    )

    button_keys = {key for key, _kwargs in fake_st.button_calls}
    assert "run_btn" in button_keys
    assert "combo_exec_load_export" not in button_keys
    assert "load_data_main" not in button_keys
    assert "delete_data_main" not in button_keys
    assert "export_df_main" not in button_keys
    assert "stats_report_main" not in button_keys
    assert "_combo_load_trigger" not in fake_st.session_state
    assert "_combo_export_trigger" not in fake_st.session_state
    assert not any("LOAD dataframe" in msg for kind, msg in fake_st.messages if kind == "info")
    assert any("Run the selected DAG workflow" in msg for kind, msg in fake_st.messages if kind == "caption")


@pytest.mark.asyncio
async def test_render_execute_section_load_warns_when_no_preview_or_empty_batch(monkeypatch, tmp_path):
    no_target_st = _FakeStreamlit(
        {
            "app_settings": {"args": {}},
            orchestrate_execute.PENDING_EXECUTE_ACTION_KEY: "load",
            "df_export_file": str(tmp_path / "export.csv"),
            "profile_report_file": tmp_path / "profile.html",
        }
    )
    monkeypatch.setattr(orchestrate_execute, "st", no_target_st)
    monkeypatch.setattr(orchestrate_execute, "collect_candidate_roots", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(orchestrate_execute, "find_preview_target", lambda *_args, **_kwargs: (None, []))

    env = SimpleNamespace(
        dataframe_path=tmp_path,
        app_data_rel=None,
        runenv=tmp_path / "runenv",
        app="flight_telemetry_project",
        wenv_abs=tmp_path / "wenv",
    )

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_telemetry_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="print('run')",
        deps=_make_execute_deps(no_target_st.messages, no_target_st.session_state),
    )

    assert any(kind == "warning" and "No previewable output found yet" in msg for kind, msg in no_target_st.messages)

    empty_csv = tmp_path / "empty.csv"
    empty_csv.write_text("value\n", encoding="utf-8")
    empty_batch_st = _FakeStreamlit(
        {
            "app_settings": {"args": {}},
            orchestrate_execute.PENDING_EXECUTE_ACTION_KEY: "load",
            "export_batch_window_seconds": "bad-window",
            "df_export_file": str(tmp_path / "export.csv"),
            "profile_report_file": tmp_path / "profile.html",
        }
    )
    monkeypatch.setattr(orchestrate_execute, "st", empty_batch_st)
    monkeypatch.setattr(orchestrate_execute, "find_preview_target", lambda *_args, **_kwargs: (empty_csv, [empty_csv]))
    monkeypatch.setattr(
        orchestrate_execute,
        "cached_load_df",
        SimpleNamespace(__call__=lambda self, *_args, **_kwargs: pd.DataFrame(), clear=lambda: None),
        raising=False,
    )

    class _Loader:
        def __call__(self, *_args, **_kwargs):
            return pd.DataFrame()

        def clear(self):
            return None

    monkeypatch.setattr(orchestrate_execute, "cached_load_df", _Loader())

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_telemetry_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="print('run')",
        deps=_make_execute_deps(empty_batch_st.messages, empty_batch_st.session_state),
    )

    assert any(kind == "warning" and "is empty; nothing to preview" in msg for kind, msg in empty_batch_st.messages)


@pytest.mark.asyncio
async def test_render_execute_section_handles_gml_and_unsupported_previews(monkeypatch, tmp_path):
    env = SimpleNamespace(
        dataframe_path=tmp_path,
        app_data_rel=None,
        runenv=tmp_path / "runenv",
        app="flight_telemetry_project",
        wenv_abs=tmp_path / "wenv",
    )
    monkeypatch.setattr(orchestrate_execute, "collect_candidate_roots", lambda *_args, **_kwargs: [])

    gml_file = tmp_path / "graph.gml"
    gml_file.write_text("graph", encoding="utf-8")
    edge_graph = orchestrate_execute.nx.Graph()
    edge_graph.add_edge("a", "b")
    edge_st = _FakeStreamlit(
        {
            "app_settings": {"args": {}},
            orchestrate_execute.PENDING_EXECUTE_ACTION_KEY: "load",
            "df_export_file": str(tmp_path / "export.csv"),
            "profile_report_file": tmp_path / "profile.html",
        }
    )
    monkeypatch.setattr(orchestrate_execute, "st", edge_st)
    monkeypatch.setattr(orchestrate_execute, "find_preview_target", lambda *_args, **_kwargs: (gml_file, [gml_file]))
    monkeypatch.setattr(orchestrate_execute.nx, "read_gml", lambda *_args, **_kwargs: edge_graph)

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_telemetry_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="print('run')",
        deps=_make_execute_deps(edge_st.messages, edge_st.session_state),
    )

    assert any(kind == "success" and "Loaded topology edges" in msg for kind, msg in edge_st.messages)

    node_graph = orchestrate_execute.nx.Graph()
    node_graph.add_node("solo", role="worker")
    node_st = _FakeStreamlit(
        {
            "app_settings": {"args": {}},
            orchestrate_execute.PENDING_EXECUTE_ACTION_KEY: "load",
            "df_export_file": str(tmp_path / "export.csv"),
            "profile_report_file": tmp_path / "profile.html",
        }
    )
    monkeypatch.setattr(orchestrate_execute, "st", node_st)
    monkeypatch.setattr(orchestrate_execute.nx, "read_gml", lambda *_args, **_kwargs: node_graph)

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_telemetry_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="print('run')",
        deps=_make_execute_deps(node_st.messages, node_st.session_state),
    )

    assert any(kind == "info" and "Showing node metadata" in msg for kind, msg in node_st.messages)

    empty_graph = orchestrate_execute.nx.Graph()
    empty_st = _FakeStreamlit(
        {
            "app_settings": {"args": {}},
            orchestrate_execute.PENDING_EXECUTE_ACTION_KEY: "load",
            "df_export_file": str(tmp_path / "export.csv"),
            "profile_report_file": tmp_path / "profile.html",
        }
    )
    monkeypatch.setattr(orchestrate_execute, "st", empty_st)
    monkeypatch.setattr(orchestrate_execute.nx, "read_gml", lambda *_args, **_kwargs: empty_graph)

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_telemetry_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="print('run')",
        deps=_make_execute_deps(empty_st.messages, empty_st.session_state),
    )

    assert any(kind == "warning" and "did not contain edges or node attributes" in msg for kind, msg in empty_st.messages)

    txt_file = tmp_path / "preview.txt"
    txt_file.write_text("plain text", encoding="utf-8")
    txt_st = _FakeStreamlit(
        {
            "app_settings": {"args": {}},
            orchestrate_execute.PENDING_EXECUTE_ACTION_KEY: "load",
            "df_export_file": str(tmp_path / "export.csv"),
            "profile_report_file": tmp_path / "profile.html",
        }
    )
    monkeypatch.setattr(orchestrate_execute, "st", txt_st)
    monkeypatch.setattr(orchestrate_execute, "find_preview_target", lambda *_args, **_kwargs: (txt_file, [txt_file]))

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_telemetry_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="print('run')",
        deps=_make_execute_deps(txt_st.messages, txt_st.session_state),
    )

    assert any(kind == "warning" and "Unsupported file format" in msg for kind, msg in txt_st.messages)


@pytest.mark.asyncio
async def test_render_execute_section_handles_delete_and_undo_edge_cases(monkeypatch, tmp_path):
    source_file = tmp_path / "result.csv"
    source_file.write_text("value\n1\n", encoding="utf-8")

    class _BrokenClear:
        def clear(self):
            raise RuntimeError("clear failed")

    delete_st = _FakeStreamlit(
        {
            "app_settings": {"args": {}},
            orchestrate_execute.PENDING_EXECUTE_ACTION_KEY: "delete",
            "loaded_df": pd.DataFrame({"value": [1]}),
            "loaded_source_path": str(source_file),
            "df_export_file": str(tmp_path / "export.csv"),
            "profile_report_file": tmp_path / "profile.html",
        }
    )
    monkeypatch.setattr(orchestrate_execute, "st", delete_st)
    monkeypatch.setattr(orchestrate_execute, "cached_load_df", _BrokenClear())
    monkeypatch.setattr(orchestrate_execute, "find_files", _BrokenClear())

    env = SimpleNamespace(
        dataframe_path=tmp_path,
        app_data_rel=None,
        runenv=tmp_path / "runenv",
        app="flight_telemetry_project",
        wenv_abs=tmp_path / "wenv",
    )

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_telemetry_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="print('run')",
        deps=_make_execute_deps(delete_st.messages, delete_st.session_state),
    )

    assert any(kind == "success" and "Deleted result.csv from disk." in msg for kind, msg in delete_st.messages)

    missing_backup_st = _FakeStreamlit(
        {
            "app_settings": {"args": {}},
            "delete_data_main_undo_payload": {
                "backup_file": str(tmp_path / "missing-backup.csv"),
                "source_file": str(tmp_path / "missing-source.csv"),
                "loaded_df": pd.DataFrame({"value": [1]}),
            },
            "df_export_file": str(tmp_path / "export.csv"),
            "profile_report_file": tmp_path / "profile.html",
        },
        buttons={"delete_data_main_undo_btn": True},
    )
    monkeypatch.setattr(orchestrate_execute, "st", missing_backup_st)
    monkeypatch.setattr(orchestrate_execute, "cached_load_df", _BrokenClear())
    monkeypatch.setattr(orchestrate_execute, "find_files", _BrokenClear())

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_telemetry_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="print('run')",
        deps=_make_execute_deps(missing_backup_st.messages, missing_backup_st.session_state),
    )

    assert any(kind == "warning" and "backup not found" in msg for kind, msg in missing_backup_st.messages)
    assert any(kind == "success" and "preview restore completed" in msg.lower() for kind, msg in missing_backup_st.messages)

    restore_error_st = _FakeStreamlit(
        {
            "app_settings": {"args": {}},
            "delete_data_main_undo_payload": {
                "backup_file": str(tmp_path / "backup.csv"),
                "source_file": str(tmp_path / "restore.csv"),
                "loaded_df": pd.DataFrame({"value": [1]}),
            },
            "df_export_file": str(tmp_path / "export.csv"),
            "profile_report_file": tmp_path / "profile.html",
        },
        buttons={"delete_data_main_undo_btn": True},
    )
    monkeypatch.setattr(orchestrate_execute, "st", restore_error_st)
    Path(restore_error_st.session_state["delete_data_main_undo_payload"]["backup_file"]).write_text("value\n1\n", encoding="utf-8")
    monkeypatch.setattr(orchestrate_execute.shutil, "move", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("restore boom")))

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_telemetry_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="print('run')",
        deps=_make_execute_deps(restore_error_st.messages, restore_error_st.session_state),
    )

    assert any(kind == "error" and "Failed to restore deleted file" in msg for kind, msg in restore_error_st.messages)


@pytest.mark.asyncio
async def test_render_execute_section_handles_combo_install_gaps_and_export_reset(monkeypatch, tmp_path):
    combo_st = _FakeStreamlit(
        {
            "app_settings": {"args": {}},
            orchestrate_execute.PENDING_EXECUTE_ACTION_KEY: "combo",
            "df_export_file": str(tmp_path / "export.csv"),
            "profile_report_file": tmp_path / "profile.html",
        }
    )
    monkeypatch.setattr(orchestrate_execute, "st", combo_st)

    env = SimpleNamespace(
        dataframe_path=tmp_path,
        app_data_rel=None,
        runenv=tmp_path / "runenv",
        app="flight_telemetry_project",
        wenv_abs=tmp_path / "wenv",
    )

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_telemetry_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="print('run')",
        deps=_make_execute_deps(combo_st.messages, combo_st.session_state),
    )

    assert any(kind == "error" and "installation is incomplete" in msg for kind, msg in combo_st.messages)

    reset_st = _FakeStreamlit(
        {
            "app_settings": {"args": {}},
            "loaded_df": pd.DataFrame({"a": [1], "b": [2]}),
            "df_export_file": str(tmp_path / "export.csv"),
            "profile_report_file": tmp_path / "profile.html",
            "_reset_export_checkboxes": True,
            "export_tab_previous_project": "flight_telemetry_project",
            "df_cols": ["a", "b"],
            "selected_cols": [],
            "check_all": True,
            "export_col_0": False,
            "export_col_1": False,
        },
        buttons={"__checkbox__::check_all": True},
    )
    monkeypatch.setattr(orchestrate_execute, "st", reset_st)
    monkeypatch.setattr(orchestrate_execute, "render_dataframe_preview", lambda *_args, **_kwargs: None)

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_telemetry_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="print('run')",
        deps=_make_execute_deps(reset_st.messages, reset_st.session_state),
    )

    assert reset_st.session_state["selected_cols"] == ["a", "b"]
    assert reset_st.session_state["export_col_0"] is True
    assert reset_st.session_state["export_col_1"] is True


@pytest.mark.asyncio
async def test_render_execute_section_load_and_delete_cover_generic_error_paths(monkeypatch, tmp_path):
    preview_file = tmp_path / "preview.csv"
    preview_file.write_text("value\n1\n", encoding="utf-8")

    class _BrokenLoader:
        def __call__(self, *_args, **_kwargs):
            raise RuntimeError("read boom")

        def clear(self):
            return None

    load_st = _FakeStreamlit(
        {
            "app_settings": {"args": {}},
            orchestrate_execute.PENDING_EXECUTE_ACTION_KEY: "load",
            "df_export_file": str(tmp_path / "export.csv"),
            "profile_report_file": tmp_path / "profile.html",
        }
    )
    monkeypatch.setattr(orchestrate_execute, "st", load_st)
    monkeypatch.setattr(orchestrate_execute, "cached_load_df", _BrokenLoader())
    monkeypatch.setattr(orchestrate_execute, "find_preview_target", lambda *_args, **_kwargs: (preview_file, [preview_file]))

    env = SimpleNamespace(
        dataframe_path=tmp_path,
        app_data_rel=None,
        runenv=tmp_path / "runenv",
        app="flight_telemetry_project",
        wenv_abs=tmp_path / "wenv",
    )

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_telemetry_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="print('run')",
        deps=_make_execute_deps(load_st.messages, load_st.session_state),
    )

    assert any(kind == "error" and "Unable to load preview.csv: read boom" in msg for kind, msg in load_st.messages)

    delete_st = _FakeStreamlit(
        {
            "app_settings": {"args": {}},
            orchestrate_execute.PENDING_EXECUTE_ACTION_KEY: "delete",
            "loaded_df": pd.DataFrame({"value": [1]}),
            "loaded_source_path": str(tmp_path / "missing.csv"),
            "df_export_file": str(tmp_path / "export.csv"),
            "profile_report_file": tmp_path / "profile.html",
        }
    )
    monkeypatch.setattr(orchestrate_execute, "st", delete_st)

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_telemetry_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="print('run')",
        deps=_make_execute_deps(delete_st.messages, delete_st.session_state),
    )

    assert any(kind == "info" and "already removed from disk" in msg for kind, msg in delete_st.messages)
    assert any(kind == "info" and "preview cleared" in msg.lower() for kind, msg in delete_st.messages)


@pytest.mark.asyncio
async def test_render_execute_section_export_warns_for_missing_selection_and_filename(monkeypatch, tmp_path):
    env = SimpleNamespace(
        dataframe_path=tmp_path,
        app_data_rel=None,
        runenv=tmp_path / "runenv",
        app="flight_telemetry_project",
        wenv_abs=tmp_path / "wenv",
    )
    monkeypatch.setattr(orchestrate_execute, "render_dataframe_preview", lambda *_args, **_kwargs: None)

    no_columns_st = _FakeStreamlit(
        {
            "app_settings": {"args": {}},
            "loaded_df": pd.DataFrame({"a": [1]}),
            "df_export_file": str(tmp_path / "export.csv"),
            "profile_report_file": tmp_path / "profile.html",
            "export_tab_previous_project": "flight_telemetry_project",
            "df_cols": ["a"],
            "selected_cols": [],
            "check_all": False,
        },
        buttons={"export_df_main": True},
    )
    monkeypatch.setattr(orchestrate_execute, "st", no_columns_st)

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_telemetry_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="print('run')",
        deps=_make_execute_deps(no_columns_st.messages, no_columns_st.session_state),
    )

    assert any(kind == "warning" and "No columns selected for export." in msg for kind, msg in no_columns_st.messages)

    no_filename_st = _FakeStreamlit(
        {
            "app_settings": {"args": {}},
            "loaded_df": pd.DataFrame({"a": [1]}),
            "df_export_file": "",
            "input_df_export_file_main": "",
            "profile_report_file": tmp_path / "profile.html",
            "export_tab_previous_project": "flight_telemetry_project",
            "df_cols": ["a"],
            "selected_cols": ["a"],
            "check_all": True,
            "export_col_0": True,
        },
        buttons={"export_df_main": True},
    )
    monkeypatch.setattr(orchestrate_execute, "st", no_filename_st)

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_telemetry_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="print('run')",
        deps=_make_execute_deps(no_filename_st.messages, no_filename_st.session_state),
    )

    assert any(kind == "warning" and "Please provide a filename for the export." in msg for kind, msg in no_filename_st.messages)


@pytest.mark.asyncio
async def test_render_execute_section_reruns_when_delete_confirm_state_changes(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit(
        {
            "app_settings": {"args": {}},
            "df_export_file": str(tmp_path / "export.csv"),
            "profile_report_file": tmp_path / "profile.html",
        }
    )
    monkeypatch.setattr(orchestrate_execute, "st", fake_st)

    env = SimpleNamespace(
        dataframe_path=tmp_path,
        app_data_rel=None,
        runenv=tmp_path / "runenv",
        app="flight_telemetry_project",
        wenv_abs=tmp_path / "wenv",
    )
    deps = _make_execute_deps(fake_st.messages, fake_st.session_state)
    deps = deps.__replace__(update_delete_confirm_state=lambda *_args, **_kwargs: True)

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_telemetry_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="print('run')",
        deps=deps,
    )

    assert any(kind == "rerun_fragment_or_app" and message == "called" for kind, message in fake_st.messages)


@pytest.mark.asyncio
async def test_render_execute_section_loads_single_file_and_combo_install_gap(monkeypatch, tmp_path):
    preview_file = tmp_path / "preview.csv"
    preview_file.write_text("value\n1\n", encoding="utf-8")

    class _Loader:
        def __call__(self, *_args, **_kwargs):
            return pd.DataFrame({"value": [1]})

        def clear(self):
            return None

    single_file_st = _FakeStreamlit(
        {
            "app_settings": {"args": {}},
            orchestrate_execute.PENDING_EXECUTE_ACTION_KEY: "load",
            "df_export_file": str(tmp_path / "export.csv"),
            "profile_report_file": tmp_path / "profile.html",
        }
    )
    monkeypatch.setattr(orchestrate_execute, "st", single_file_st)
    monkeypatch.setattr(orchestrate_execute, "cached_load_df", _Loader())
    monkeypatch.setattr(orchestrate_execute, "find_preview_target", lambda *_args, **_kwargs: (preview_file, [preview_file]))

    env = SimpleNamespace(
        dataframe_path=tmp_path,
        app_data_rel=None,
        runenv=tmp_path / "runenv",
        app="flight_telemetry_project",
        wenv_abs=tmp_path / "wenv",
    )

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_telemetry_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="print('run')",
        deps=_make_execute_deps(single_file_st.messages, single_file_st.session_state),
    )

    assert any(kind == "success" and "Loaded dataframe preview from preview.csv." in msg for kind, msg in single_file_st.messages)

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
        app_state_name="flight_telemetry_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="print('run')",
        deps=_make_execute_deps(combo_st.messages, combo_st.session_state),
    )

    assert any(kind == "error" and "installation is incomplete" in msg for kind, msg in combo_st.messages)


@pytest.mark.asyncio
async def test_render_execute_section_combo_runs_when_installation_exists(monkeypatch, tmp_path):
    project_path = tmp_path / "project"
    manager_venv = project_path / ".venv"
    worker_venv = (tmp_path / "wenv") / ".venv"
    manager_venv.mkdir(parents=True)
    worker_venv.mkdir(parents=True)

    async def _run_agi(_cmd, log_callback=None, venv=None):
        if log_callback is not None:
            log_callback("combo run log")
        return "", ""

    combo_st = _FakeStreamlit(
        {
            "app_settings": {"args": {}},
            orchestrate_execute.PENDING_EXECUTE_ACTION_KEY: "combo",
            "df_export_file": str(tmp_path / "export.csv"),
            "profile_report_file": tmp_path / "profile.html",
        }
    )
    monkeypatch.setattr(orchestrate_execute, "st", combo_st)

    env = SimpleNamespace(
        dataframe_path=tmp_path,
        app_data_rel=None,
        runenv=tmp_path / "runenv",
        app="flight_telemetry_project",
        wenv_abs=tmp_path / "wenv",
        run_agi=_run_agi,
        snippet_tail="pass",
    )

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=project_path,
        app_state_name="flight_telemetry_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="asyncio.run(main())",
        deps=_make_execute_deps(combo_st.messages, combo_st.session_state),
    )

    assert any(kind == "caption" and "Logs saved to" in msg for kind, msg in combo_st.messages)
    assert combo_st.session_state["_combo_load_trigger"] is True
    assert combo_st.session_state["_combo_export_trigger"] is True


@pytest.mark.asyncio
async def test_render_execute_section_export_checkbox_callbacks_update_selection(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit(
        {
            "app_settings": {"args": {}},
            "loaded_df": pd.DataFrame({"a": [1], "b": [2]}),
            "selected_cols": ["b"],
            "check_all": False,
            "export_col_0": True,
            "export_col_1": False,
            "df_export_file": str(tmp_path / "export.csv"),
            "profile_report_file": tmp_path / "profile.html",
        },
        buttons={
            "__checkbox__::export_col_0": True,
            "__checkbox__::export_col_1": True,
        },
    )
    monkeypatch.setattr(orchestrate_execute, "st", fake_st)

    env = SimpleNamespace(
        dataframe_path=tmp_path,
        app_data_rel=None,
        runenv=tmp_path / "runenv",
        app="flight_telemetry_project",
        wenv_abs=tmp_path / "wenv",
    )

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_telemetry_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="print('run')",
        deps=_make_execute_deps(fake_st.messages, fake_st.session_state),
    )

    assert fake_st.session_state["selected_cols"] == ["a"]
    assert fake_st.session_state["check_all"] is False
    assert fake_st.session_state["_force_export_open"] is True


@pytest.mark.asyncio
async def test_render_execute_section_delete_reports_disk_failure(monkeypatch, tmp_path):
    source_file = tmp_path / "result.csv"
    source_file.write_text("value\n1\n", encoding="utf-8")

    delete_st = _FakeStreamlit(
        {
            "app_settings": {"args": {}},
            orchestrate_execute.PENDING_EXECUTE_ACTION_KEY: "delete",
            "loaded_df": pd.DataFrame({"value": [1]}),
            "loaded_source_path": str(source_file),
            "df_export_file": str(tmp_path / "export.csv"),
            "profile_report_file": tmp_path / "profile.html",
        }
    )
    monkeypatch.setattr(orchestrate_execute, "st", delete_st)
    monkeypatch.setattr(
        orchestrate_execute.shutil,
        "move",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("delete boom")),
    )

    env = SimpleNamespace(
        dataframe_path=tmp_path,
        app_data_rel=None,
        runenv=tmp_path / "runenv",
        app="flight_telemetry_project",
        wenv_abs=tmp_path / "wenv",
    )

    await orchestrate_execute.render_execute_section(
        env=env,
        project_path=tmp_path / "project",
        app_state_name="flight_telemetry_project",
        controls_visible=True,
        show_run_panel=True,
        cmd="print('run')",
        deps=_make_execute_deps(delete_st.messages, delete_st.session_state),
    )

    assert any(kind == "error" and "Failed to delete" in msg for kind, msg in delete_st.messages)
