from __future__ import annotations

import builtins
import importlib.util
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest


MODULE_PATH = Path(
    "src/agilab/apps-pages/view_training_analysis/src/view_training_analysis/view_training_analysis.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("view_training_analysis_test_module", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _StopCalled(RuntimeError):
    pass


def _stop() -> None:
    raise _StopCalled()


def test_view_training_analysis_discovers_trainers_and_runs(tmp_path: Path) -> None:
    module = _load_module()

    trainer_a = tmp_path / "pipeline" / "trainer_a" / "tensorboard" / "run_1"
    trainer_a.mkdir(parents=True)
    (trainer_a / "events.out.tfevents.1").write_text("", encoding="utf-8")

    trainer_b_root = tmp_path / "pipeline" / "trainer_b" / "tensorboard"
    trainer_b_root.mkdir(parents=True)
    (trainer_b_root / "events.out.tfevents.2").write_text("", encoding="utf-8")
    trainer_b_run = trainer_b_root / "run_2"
    trainer_b_run.mkdir()
    (trainer_b_run / "events.out.tfevents.3").write_text("", encoding="utf-8")

    trainer_roots = module._discover_tensorboard_roots(tmp_path / "pipeline")
    assert trainer_roots == sorted(
        [tmp_path / "pipeline" / "trainer_a", tmp_path / "pipeline" / "trainer_b"],
        key=lambda path: path.as_posix(),
    )

    run_dirs = module._discover_run_directories(trainer_b_root)
    assert run_dirs == [trainer_b_root.resolve(), trainer_b_run.resolve()]


def test_view_training_analysis_grid_shape_scales_with_selection_count() -> None:
    module = _load_module()

    assert module._grid_shape(1) == (1, 1)
    assert module._grid_shape(4) == (2, 3)
    assert module._grid_shape(5) == (2, 3)
    assert module._grid_shape(10) == (4, 3)


def test_view_training_analysis_builds_one_trace_per_run_and_metric() -> None:
    module = _load_module()

    scalar_df = pd.DataFrame(
        [
            {"tag": "rollout/ep_rew_mean", "step": 1, "value": 1.0, "run_label": "routing_2"},
            {"tag": "rollout/ep_rew_mean", "step": 2, "value": 2.0, "run_label": "routing_2"},
            {"tag": "rollout/ep_rew_mean", "step": 1, "value": 1.5, "run_label": "routing_12"},
            {"tag": "rollout/ep_rew_mean", "step": 2, "value": 2.5, "run_label": "routing_12"},
            {"tag": "rollout/ep_rew_mean", "step": 1, "value": 0.8, "run_label": "routing_20"},
            {"tag": "rollout/ep_rew_mean", "step": 2, "value": 1.9, "run_label": "routing_20"},
            {"tag": "train/approx_kl", "step": 1, "value": 0.1, "run_label": "routing_2"},
            {"tag": "train/approx_kl", "step": 2, "value": 0.05, "run_label": "routing_2"},
            {"tag": "train/approx_kl", "step": 1, "value": 0.08, "run_label": "routing_12"},
            {"tag": "train/approx_kl", "step": 2, "value": 0.03, "run_label": "routing_12"},
            {"tag": "train/approx_kl", "step": 1, "value": 0.12, "run_label": "routing_20"},
            {"tag": "train/approx_kl", "step": 2, "value": 0.06, "run_label": "routing_20"},
        ]
    )
    scalar_df["wall_time"] = scalar_df["step"].astype(float)
    scalar_df["relative_time_s"] = scalar_df["step"].astype(float)
    scalar_df["timestamp"] = pd.to_datetime(scalar_df["step"], unit="s")

    fig = module._build_scalar_figure(
        scalar_df,
        ["rollout/ep_rew_mean", "train/approx_kl"],
        "step",
    )

    assert len(fig.data) == 6
    assert Counter(trace.name for trace in fig.data) == {
        "routing_2": 2,
        "routing_12": 2,
        "routing_20": 2,
    }
    colors_by_run = {}
    for trace in fig.data:
        colors_by_run.setdefault(trace.name, set()).add(trace.line.color)
    assert len(colors_by_run["routing_2"]) == 1
    assert len(colors_by_run["routing_12"]) == 1
    assert len(colors_by_run["routing_20"]) == 1
    assert colors_by_run["routing_2"] != colors_by_run["routing_12"]
    assert colors_by_run["routing_2"] != colors_by_run["routing_20"]
    assert colors_by_run["routing_12"] != colors_by_run["routing_20"]


def test_view_training_analysis_normalizes_page_settings_and_paths(tmp_path: Path) -> None:
    module = _load_module()

    assert module._coerce_str_list(" a; b\n a , c ") == ["a", "b", "c"]
    assert module._get_first_nonempty_setting(
        [{"unused": " "}, {"primary": "  "}, {"secondary": " chosen "}],
        "primary",
        "secondary",
    ) == "chosen"

    share_dir = tmp_path / "share"
    export_dir = tmp_path / "export"
    env = SimpleNamespace(share_root_path=lambda: str(share_dir), AGILAB_EXPORT_ABS=str(export_dir))
    assert module._resolve_base_path(env, "AGI_SHARE_DIR", "").resolve() == share_dir.resolve()
    assert module._resolve_base_path(env, "AGILAB_EXPORT", "").resolve() == export_dir.resolve()
    assert module._resolve_base_path(env, "CUSTOM", "~/custom-root") == Path("~/custom-root").expanduser()

    assert module._relative_label(tmp_path / "base" / "child", tmp_path / "base") == "child"
    assert module._relative_label(tmp_path / "outside", tmp_path / "base") == "outside"
    assert module._default_selected_tags(["a", "b", "c"], ["x", "b"]) == ["b"]
    assert module._default_selected_tags(["a", "b", "c", "d", "e"], []) == ["a", "b", "c", "d"]


def test_view_training_analysis_loads_and_persists_app_settings(tmp_path: Path) -> None:
    module = _load_module()
    settings_path = tmp_path / "app_settings.toml"
    env = SimpleNamespace(app_settings_file=settings_path)

    module.st = SimpleNamespace(session_state={})
    module._ensure_app_settings_loaded(env)
    assert module.st.session_state["app_settings"] == {}

    settings_path.write_text("[view_training_analysis]\ntrainer = \"alpha\"\n", encoding="utf-8")
    module.st = SimpleNamespace(session_state={})
    module._ensure_app_settings_loaded(env)
    assert module.st.session_state["app_settings"]["view_training_analysis"]["trainer"] == "alpha"

    module.st.session_state["app_settings"] = {"view_training_analysis": {"trainer": "beta"}}
    module._persist_app_settings(env)
    assert "view_training_analysis" in settings_path.read_text(encoding="utf-8")

    module.st = SimpleNamespace(session_state={})
    page_state = module._get_page_state()
    page_state["trainer"] = "gamma"
    assert module.st.session_state["app_settings"][module.PAGE_KEY]["trainer"] == "gamma"

    module.st = SimpleNamespace(session_state={"app_settings": {"pages": {module.PAGE_KEY: {"tags": ["x"]}}}})
    assert module._get_page_defaults() == {"tags": ["x"]}


def test_view_training_analysis_repo_path_and_setting_helpers(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    repo_root = tmp_path / "repo"
    src_root = repo_root / "src"
    app_root = src_root / "agilab" / "apps-pages" / "view_training_analysis" / "src" / "view_training_analysis"
    app_root.mkdir(parents=True)
    module_path = app_root / "view_training_analysis.py"
    module_path.write_text("# stub\n", encoding="utf-8")

    monkeypatch.setattr(module, "__file__", str(module_path))
    monkeypatch.setattr(module.sys, "path", [])
    module._ensure_repo_on_path()

    assert str(src_root) in module.sys.path
    assert str(repo_root) in module.sys.path

    module.st = SimpleNamespace(session_state={"app_settings": {"kept": True}})
    module._ensure_app_settings_loaded(SimpleNamespace(app_settings_file=tmp_path / "missing.toml"))
    assert module.st.session_state["app_settings"] == {"kept": True}

    assert module._get_first_nonempty_setting(["bad", {"primary": " "}, {"secondary": "ok"}], "primary", "secondary") == "ok"


def test_view_training_analysis_handles_tensorboard_helper_edge_cases(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    tensorboard_root = tmp_path / "tensorboard"
    tensorboard_root.mkdir()
    (tensorboard_root / "events.out.tfevents.1").write_text("", encoding="utf-8")
    assert module._discover_tensorboard_roots(tensorboard_root) == [tmp_path.resolve()]
    assert module._discover_run_directories(tmp_path / "missing") == []

    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "tensorboard.backend.event_processing.event_accumulator":
            raise ModuleNotFoundError("tensorboard missing")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError, match="TensorBoard support is not installed"):
        module._load_event_accumulator()

    class _EmptyAccumulator:
        def __init__(self, run_dir_str):
            self.run_dir_str = run_dir_str

        def Reload(self):
            return None

        def Tags(self):
            return {"scalars": []}

    monkeypatch.setattr(module, "_load_event_accumulator", lambda: _EmptyAccumulator)
    module._load_scalar_frame.clear()
    assert module._load_scalar_frame(str(tmp_path)).empty


def test_view_training_analysis_event_helpers_and_scalar_frame(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()

    events_root = tmp_path / "events"
    nested = events_root / "trainer" / "tensorboard" / "run_1"
    nested.mkdir(parents=True)
    event_b = nested / "events.out.tfevents.2"
    event_a = nested / "events.out.tfevents.1"
    event_a.write_text("", encoding="utf-8")
    event_b.write_text("", encoding="utf-8")
    assert module._event_files(events_root) == [event_a.resolve(), event_b.resolve()]

    class _Event:
        def __init__(self, step, wall_time, value):
            self.step = step
            self.wall_time = wall_time
            self.value = value

    class _Accumulator:
        def __init__(self, run_dir_str):
            self.run_dir_str = run_dir_str

        def Reload(self):
            return None

        def Tags(self):
            return {"scalars": ["metric/b", "metric/a"]}

        def Scalars(self, tag):
            if tag == "metric/a":
                return [_Event(2, 12.0, 0.2), _Event(1, 10.0, 0.1)]
            return [_Event(1, 11.0, 1.1)]

    monkeypatch.setattr(module, "_load_event_accumulator", lambda: _Accumulator)
    module._load_scalar_frame.clear()
    df = module._load_scalar_frame(str(events_root))

    assert df[["tag", "step", "value"]].to_dict("records") == [
        {"tag": "metric/a", "step": 1, "value": 0.1},
        {"tag": "metric/a", "step": 2, "value": 0.2},
        {"tag": "metric/b", "step": 1, "value": 1.1},
    ]
    assert df["relative_time_s"].tolist() == [0.0, 2.0, 1.0]
    assert str(df["timestamp"].iloc[0]) == "1970-01-01 00:00:10"


def test_view_training_analysis_resolve_active_app(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    active_app = tmp_path / "apps" / "demo_project"
    active_app.mkdir(parents=True)

    with patch("sys.argv", [MODULE_PATH.name, "--active-app", str(active_app)]):
        assert module._resolve_active_app() == active_app.resolve()


def test_view_training_analysis_main_warns_when_data_root_missing(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    settings_path = tmp_path / "app_settings.toml"
    env = SimpleNamespace(
        app_settings_file=settings_path,
        share_root_path=lambda: str(tmp_path / "share"),
        AGILAB_EXPORT_ABS=str(tmp_path / "export"),
    )
    warnings_seen: list[str] = []
    captions: list[str] = []

    sidebar = SimpleNamespace(
        radio=lambda *args, **kwargs: "Custom",
        text_input=lambda *args, **kwargs: str(tmp_path / "missing-root"),
        caption=lambda value: captions.append(value),
    )
    module.st = SimpleNamespace(
        session_state={
            "env": env,
            "base_dir_choice": "Custom",
            "input_datadir": str(tmp_path / "missing-root"),
            "datadir_rel": "",
        },
        sidebar=sidebar,
        set_page_config=lambda **kwargs: None,
        title=lambda *args, **kwargs: None,
        caption=lambda value: captions.append(value),
        warning=warnings_seen.append,
        stop=_stop,
    )
    monkeypatch.setattr(module, "render_logo", lambda *args, **kwargs: None)

    with pytest.raises(_StopCalled):
        module.main()

    assert any("Data root does not exist yet" in message for message in warnings_seen)
    written = settings_path.read_text(encoding="utf-8")
    assert "base_dir_choice = \"Custom\"" in written
    assert "view_training_analysis" in written


def test_view_training_analysis_main_bootstraps_env_when_missing(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    export_root = tmp_path / "export"
    export_root.mkdir()
    settings_path = tmp_path / "app_settings.toml"
    active_app = tmp_path / "apps" / "trainer_project"
    active_app.mkdir(parents=True)
    warnings_seen: list[str] = []

    class FakeEnv:
        def __init__(self, apps_path, app, verbose):
            self.apps_path = apps_path
            self.app = app
            self.verbose = verbose
            self.app_settings_file = settings_path
            self.share_root_path = lambda: str(tmp_path / "share")
            self.AGILAB_EXPORT_ABS = str(export_root)
            self.init_done = False

    module.st = SimpleNamespace(
        session_state={},
        sidebar=SimpleNamespace(
            radio=lambda *args, **kwargs: "AGILAB_EXPORT",
            text_input=lambda *args, **kwargs: "",
            caption=lambda *args, **kwargs: None,
            selectbox=lambda label, options, index=0, key=None, format_func=None: "step" if label == "X axis" else options[0],
            multiselect=lambda *args, **kwargs: [],
        ),
        set_page_config=lambda **kwargs: None,
        title=lambda *args, **kwargs: None,
        caption=lambda *args, **kwargs: None,
        warning=warnings_seen.append,
        info=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
        subheader=lambda *args, **kwargs: None,
        plotly_chart=lambda *args, **kwargs: None,
        stop=_stop,
    )
    monkeypatch.setattr(module, "render_logo", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "_resolve_active_app", lambda: active_app)
    monkeypatch.setattr(module, "AgiEnv", FakeEnv)
    monkeypatch.setattr(module, "_discover_tensorboard_roots", lambda root: [])

    with pytest.raises(_StopCalled):
        module.main()

    assert module.st.session_state["env"].app == "trainer_project"
    assert module.st.session_state["base_dir_choice"] == "AGI_SHARE_DIR"
    assert module.st.session_state["input_datadir"] == ""
    assert module.st.session_state["datadir_rel"] == ""
    assert module.st.session_state[module.X_AXIS_KEY] == "step"
    assert any("No TensorBoard trainers found" in message for message in warnings_seen)


def test_view_training_analysis_main_plots_selected_metrics(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    export_root = tmp_path / "export"
    export_root.mkdir()
    data_root = export_root / "trainer_data"
    data_root.mkdir()
    settings_path = tmp_path / "app_settings.toml"
    env = SimpleNamespace(
        app_settings_file=settings_path,
        share_root_path=lambda: str(tmp_path / "share"),
        AGILAB_EXPORT_ABS=str(export_root),
    )
    trainer_dir = data_root / "trainer_a"
    run_a = trainer_dir / "tensorboard" / "run_a"
    run_b = trainer_dir / "tensorboard" / "run_b"
    plotted: list[tuple[object, str]] = []
    subheaders: list[str] = []

    def sidebar_selectbox(label, options, index=0, key=None, format_func=None):
        if label == "Trainer output":
            return options[0]
        if label == "X axis":
            return "step"
        return options[index]

    def sidebar_multiselect(label, options, default=None, key=None):
        if label == "TensorBoard run folders":
            return list(options)
        if label == "TensorBoard variables":
            return ["metric/a"]
        return list(default or [])

    module.st = SimpleNamespace(
        session_state={
            "env": env,
            "base_dir_choice": "AGILAB_EXPORT",
            "datadir_rel": "trainer_data",
            "input_datadir": "",
        },
        sidebar=SimpleNamespace(
            radio=lambda *args, **kwargs: "AGILAB_EXPORT",
            text_input=lambda *args, **kwargs: "trainer_data",
            caption=lambda *args, **kwargs: None,
            selectbox=sidebar_selectbox,
            multiselect=sidebar_multiselect,
        ),
        set_page_config=lambda **kwargs: None,
        title=lambda *args, **kwargs: None,
        caption=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        info=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
        subheader=subheaders.append,
        plotly_chart=lambda fig, width=None: plotted.append((fig, width)),
        stop=_stop,
    )
    monkeypatch.setattr(module, "render_logo", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "_discover_tensorboard_roots", lambda root: [trainer_dir])
    monkeypatch.setattr(module, "_discover_run_directories", lambda root: [run_a, run_b])

    def fake_load_scalar_frame(run_dir_str: str) -> pd.DataFrame:
        run_label = Path(run_dir_str).name
        return pd.DataFrame(
            {
                "tag": ["metric/a", "metric/b"],
                "step": [1, 2],
                "wall_time": [10.0, 11.0],
                "relative_time_s": [0.0, 1.0],
                "timestamp": pd.to_datetime([10.0, 11.0], unit="s"),
                "value": [1.0, 2.0],
                "run_label": [run_label, run_label],
            }
        )

    monkeypatch.setattr(module, "_load_scalar_frame", fake_load_scalar_frame)
    monkeypatch.setattr(module, "_build_scalar_figure", lambda df, tags, axis: {"tags": tags, "axis": axis, "rows": len(df)})

    module.main()

    assert subheaders == ["Scalar plots"]
    assert plotted == [({"tags": ["metric/a"], "axis": "step", "rows": 4}, "stretch")]
    written = settings_path.read_text(encoding="utf-8")
    assert "trainer_rel = \"trainer_a\"" in written
    assert "selected_tags = [" in written
    assert "\"metric/a\"" in written


def test_view_training_analysis_handles_active_app_and_settings_error_paths(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    errors: list[str] = []
    settings_path = tmp_path / "invalid.toml"
    settings_path.write_text("[broken", encoding="utf-8")

    module.st = SimpleNamespace(error=errors.append, stop=_stop, session_state={})
    with patch("sys.argv", [MODULE_PATH.name, "--active-app", str(tmp_path / "missing-app")]):
        with pytest.raises(_StopCalled):
            module._resolve_active_app()

    assert any("Provided --active-app path not found" in message for message in errors)

    module.st = SimpleNamespace(session_state={})
    module._ensure_app_settings_loaded(SimpleNamespace(app_settings_file=settings_path))
    assert module.st.session_state["app_settings"] == {}

    module.st = SimpleNamespace(session_state={"app_settings": "bad"})
    module._persist_app_settings(SimpleNamespace(app_settings_file=tmp_path / "persist.toml"))
    assert not (tmp_path / "persist.toml").exists()

    module.st = SimpleNamespace(session_state={"app_settings": {"view_training_analysis": {}}})
    monkeypatch.setattr(
        module,
        "_dump_toml",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("dump failed")),
    )
    module._persist_app_settings(SimpleNamespace(app_settings_file=tmp_path / "persist.toml"))

    assert module._coerce_str_list(None) == []
    assert module._coerce_str_list(("a", "b", "a")) == ["a", "b"]
    assert module._coerce_str_list(3) == ["3"]


def test_view_training_analysis_main_warns_when_no_trainers_or_runs(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    export_root = tmp_path / "export"
    export_root.mkdir()
    data_root = export_root / "trainer_data"
    data_root.mkdir()
    settings_path = tmp_path / "app_settings.toml"
    env = SimpleNamespace(
        app_settings_file=settings_path,
        share_root_path=lambda: str(tmp_path / "share"),
        AGILAB_EXPORT_ABS=str(export_root),
    )
    warnings_seen: list[str] = []

    def _base_st() -> SimpleNamespace:
        def sidebar_selectbox(label, options, index=0, key=None, format_func=None):
            if label == "Trainer output":
                return options[0]
            if label == "X axis":
                return "step"
            return options[index]

        return SimpleNamespace(
            session_state={
                "env": env,
                "base_dir_choice": "AGILAB_EXPORT",
                "datadir_rel": "trainer_data",
                "input_datadir": "",
            },
            sidebar=SimpleNamespace(
                radio=lambda *args, **kwargs: "AGILAB_EXPORT",
                text_input=lambda *args, **kwargs: "trainer_data",
                caption=lambda *args, **kwargs: None,
                selectbox=sidebar_selectbox,
                multiselect=lambda *args, **kwargs: [],
            ),
            set_page_config=lambda **kwargs: None,
            title=lambda *args, **kwargs: None,
            caption=lambda *args, **kwargs: None,
            warning=warnings_seen.append,
            info=lambda *args, **kwargs: None,
            error=lambda *args, **kwargs: None,
            subheader=lambda *args, **kwargs: None,
            plotly_chart=lambda *args, **kwargs: None,
            stop=_stop,
        )

    monkeypatch.setattr(module, "render_logo", lambda *args, **kwargs: None)

    module.st = _base_st()
    monkeypatch.setattr(module, "_discover_tensorboard_roots", lambda root: [])
    with pytest.raises(_StopCalled):
        module.main()
    assert any("No TensorBoard trainers found" in message for message in warnings_seen)

    warnings_seen.clear()
    trainer_dir = data_root / "trainer_a"
    trainer_dir.mkdir()
    module.st = _base_st()
    monkeypatch.setattr(module, "_discover_tensorboard_roots", lambda root: [trainer_dir])
    monkeypatch.setattr(module, "_discover_run_directories", lambda root: [])
    with pytest.raises(_StopCalled):
        module.main()
    assert any("No TensorBoard run folders found" in message for message in warnings_seen)


def test_view_training_analysis_main_handles_selection_and_metric_edge_cases(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    export_root = tmp_path / "export"
    export_root.mkdir()
    data_root = export_root / "trainer_data"
    data_root.mkdir()
    settings_path = tmp_path / "app_settings.toml"
    env = SimpleNamespace(
        app_settings_file=settings_path,
        share_root_path=lambda: str(tmp_path / "share"),
        AGILAB_EXPORT_ABS=str(export_root),
    )
    trainer_dir = data_root / "trainer_a"
    run_a = trainer_dir / "tensorboard" / "run_a"
    run_b = trainer_dir / "tensorboard" / "run_b"
    infos: list[str] = []
    errors: list[str] = []
    warnings_seen: list[str] = []

    def _base_st(run_selection, tag_selection) -> SimpleNamespace:
        def sidebar_selectbox(label, options, index=0, key=None, format_func=None):
            if label == "Trainer output":
                return options[0]
            if label == "X axis":
                return "step"
            return options[index]

        def sidebar_multiselect(label, options, default=None, key=None):
            if label == "TensorBoard run folders":
                return run_selection
            if label == "TensorBoard variables":
                return tag_selection
            return list(default or [])

        return SimpleNamespace(
            session_state={
                "env": env,
                "base_dir_choice": "AGILAB_EXPORT",
                "datadir_rel": "trainer_data",
                "input_datadir": "",
            },
            sidebar=SimpleNamespace(
                radio=lambda *args, **kwargs: "AGILAB_EXPORT",
                text_input=lambda *args, **kwargs: "trainer_data",
                caption=lambda *args, **kwargs: None,
                selectbox=sidebar_selectbox,
                multiselect=sidebar_multiselect,
            ),
            set_page_config=lambda **kwargs: None,
            title=lambda *args, **kwargs: None,
            caption=lambda *args, **kwargs: None,
            warning=warnings_seen.append,
            info=infos.append,
            error=errors.append,
            subheader=lambda *args, **kwargs: None,
            plotly_chart=lambda *args, **kwargs: None,
            stop=_stop,
        )

    monkeypatch.setattr(module, "render_logo", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "_discover_tensorboard_roots", lambda root: [trainer_dir])
    monkeypatch.setattr(module, "_discover_run_directories", lambda root: [run_a, run_b])

    module.st = _base_st([], [])
    with pytest.raises(_StopCalled):
        module.main()
    assert any("Select at least one TensorBoard run folder" in message for message in infos)

    infos.clear()
    warnings_seen.clear()
    module.st = _base_st(["run_a"], [])
    monkeypatch.setattr(module, "_load_scalar_frame", lambda *_args, **_kwargs: pd.DataFrame())
    with pytest.raises(_StopCalled):
        module.main()
    assert any("No scalar metrics were found" in message for message in warnings_seen)

    infos.clear()
    scalar_df = pd.DataFrame(
        {
            "tag": ["metric/a"],
            "step": [1],
            "wall_time": [10.0],
            "relative_time_s": [0.0],
            "timestamp": pd.to_datetime([10.0], unit="s"),
            "value": [1.0],
        }
    )
    module.st = _base_st(["run_a"], [])
    monkeypatch.setattr(module, "_load_scalar_frame", lambda *_args, **_kwargs: scalar_df.copy())
    module.main()
    assert any("Select at least one TensorBoard variable" in message for message in infos)

    infos.clear()
    errors.clear()
    module.st = _base_st(["run_a"], ["metric/a"])
    monkeypatch.setattr(module, "_load_scalar_frame", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("tensorboard missing")))
    with pytest.raises(_StopCalled):
        module.main()
    assert errors == ["tensorboard missing"]
