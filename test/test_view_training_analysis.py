from __future__ import annotations

import importlib.util
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


MODULE_PATH = Path(
    "src/agilab/apps-pages/view_training_analysis/src/view_training_analysis/view_training_analysis.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("view_training_analysis_test_module", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
