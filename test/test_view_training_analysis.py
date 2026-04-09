from __future__ import annotations

import importlib.util
from pathlib import Path
from collections import Counter

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
