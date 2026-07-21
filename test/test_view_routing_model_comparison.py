from __future__ import annotations

import importlib.util
import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import math

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT
    / "src/agilab/apps-pages/view_routing_model_comparison/src/view_routing_model_comparison/view_routing_model_comparison.py"
)


def _load_module():
    src_path = str((ROOT / "src").resolve())
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    spec = importlib.util.spec_from_file_location(
        "view_routing_model_comparison_test_module",
        MODULE_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _StopStreamlit(Exception):
    pass


class _Context:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _MetricColumn:
    def __init__(self, calls: list[tuple[str, tuple[object, ...]]]) -> None:
        self._calls = calls

    def metric(self, *args: object) -> None:
        self._calls.append(("metric", args))


class _Sidebar:
    def __init__(
        self,
        *,
        pipeline_text: str | None = None,
        selected_models: list[str] | None = None,
        failure_rows: int = 100,
    ) -> None:
        self.pipeline_text = pipeline_text
        self.selected_models = selected_models
        self.failure_rows = failure_rows

    def text_input(self, _label: str, *, value: str, key: str) -> str:
        return value if self.pipeline_text is None else self.pipeline_text

    def multiselect(
        self,
        _label: str,
        *,
        options: list[str],
        default: list[str],
        key: str,
    ) -> list[str]:
        return default if self.selected_models is None else self.selected_models

    def number_input(self, *args: object, **kwargs: object) -> int:
        return self.failure_rows


class _StreamlitStub:
    def __init__(
        self,
        *,
        pipeline_text: str | None = None,
        selected_models: list[str] | None = None,
    ) -> None:
        self.session_state: dict[str, object] = {}
        self.sidebar = _Sidebar(
            pipeline_text=pipeline_text,
            selected_models=selected_models,
        )
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def error(self, *args: object) -> None:
        self.calls.append(("error", args))

    def stop(self) -> None:
        raise _StopStreamlit

    def info(self, *args: object) -> None:
        self.calls.append(("info", args))

    def warning(self, *args: object) -> None:
        self.calls.append(("warning", args))

    def expander(self, *args: object, **kwargs: object) -> _Context:
        self.calls.append(("expander", args))
        return _Context()

    def write(self, *args: object) -> None:
        self.calls.append(("write", args))

    def columns(self, count: int) -> list[_MetricColumn]:
        return [_MetricColumn(self.calls) for _ in range(count)]

    def tabs(self, labels: list[str]) -> list[_Context]:
        self.calls.append(("tabs", tuple(labels)))
        return [_Context() for _ in labels]

    def subheader(self, *args: object) -> None:
        self.calls.append(("subheader", args))

    def dataframe(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("dataframe", args))

    def caption(self, *args: object) -> None:
        self.calls.append(("caption", args))

    def plotly_chart(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("plotly_chart", args))


def _write_allocations(path: Path, allocations: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([{"time_index": 0, "allocations": allocations}]),
        encoding="utf-8",
    )


def test_routing_model_comparison_parses_allocation_helpers() -> None:
    module = _load_module()

    assert module.safe_bool("yes") is True
    assert module.safe_bool("0") is False
    assert module.safe_bool(None) is None
    assert math.isnan(module.safe_float(None))
    assert module.parse_list_value("[(1, 2), (2, 3)]") == [(1, 2), (2, 3)]
    assert module.parse_list_value("not a literal") == ["not a literal"]
    assert module.is_edge_list_path([(1, 2), (2, 3)])

    routed = {
        "path": "[(1, 2)]",
        "delivered_bandwidth": 5.0,
        "bandwidth": 10.0,
        "bearers": "['SATCOM', 'ivdl']",
    }
    assert module.has_path(routed)
    assert module.is_routed(routed)
    assert module.get_satisfaction(routed) == 0.5
    assert module.hop_count(routed) == 1
    assert module.normalize_bearer("satcom") == "SAT"
    assert module.normalize_bearer("ivdl") == "IVDL"
    assert module.demand_outcome(False, 1.0) == "unrouted"
    assert module.demand_outcome(True, 1.0) == "fulfilled"
    assert module.demand_outcome(True, 0.5) == "partial"


def test_routing_model_comparison_covers_fallback_helper_branches(
    tmp_path: Path,
) -> None:
    module = _load_module()
    active_app = tmp_path / "active_app"

    module.resolve_active_app_path = lambda **kwargs: active_app
    assert module._resolve_active_app() == active_app

    assert module.safe_bool("maybe") is True
    assert math.isnan(module.safe_float(True))
    assert math.isnan(module.safe_float(object()))
    assert module.parse_list_value("") == []
    assert module.parse_list_value("('A', 'B')") == ["A", "B"]
    assert module.parse_list_value("{'not': 'a list'}") == []
    assert module.parse_list_value(("A", "B")) == ["A", "B"]
    assert module.is_edge_list_path([]) is False
    assert module.has_path({"path_labels": "['A', 'B']"}) is True
    assert module.has_path({"routed": "yes"}) is True
    assert module.has_path({"delivered_bandwidth": 0.5}) is True
    assert module.has_path({"delivered_bandwidth": 0.0}) is False
    assert (
        module.is_routed({"path_labels": ["A", "B"], "served_fraction": 0.25}) is True
    )
    assert module.is_routed({"path_labels": ["A", "B"], "served_fraction": 0}) is False
    assert math.isnan(
        module.get_satisfaction({"bandwidth": 0, "delivered_bandwidth": 1})
    )
    assert module.get_latency_ms({"latency": "42"}) == 42.0
    assert math.isnan(module.get_latency_ms({}))
    assert module.get_latency_target_ms({"latency_target": "20"}) == 20.0
    assert module.get_latency_target_ms({"max_latency": 25}) == 25.0
    assert math.isnan(module.get_latency_target_ms({}))
    assert module.hop_count({"path": ["A", "B", "C"]}) == 2
    assert module.hop_count({"path_labels": ["A", "B"]}) == 1
    assert module.hop_count({}) == 0
    assert module.normalize_bearer("") == "UNKNOWN"
    assert module.demand_outcome(True, math.nan) == "unknown"
    assert module.step_time_s({"time_s": "12.5"}) == 12.5
    assert module.step_time_s({"t_now_s": "18"}) == 18.0
    assert module.step_time_s({"time_index": 2}) == 120.0

    missing_app = tmp_path / "missing_app"
    assert module._load_app_settings(missing_app) == {}
    app = tmp_path / "app"
    settings_file = app / "src" / "app_settings.toml"
    settings_file.parent.mkdir(parents=True)
    settings_file.write_text(
        "[pages.view_routing_model_comparison]\n"
        "dataset_custom_base = '/tmp/agilab-routing'\n",
        encoding="utf-8",
    )
    settings = module._load_app_settings(app)
    assert (
        module._page_defaults(settings)["dataset_custom_base"] == "/tmp/agilab-routing"
    )
    settings_file.write_text("[pages\n", encoding="utf-8")
    assert module._load_app_settings(app) == {}
    assert module._page_defaults({}) == {}
    assert module._page_defaults({"pages": []}) == {}
    assert module._page_defaults({"pages": {module.PAGE_KEY: "bad"}}) == {}

    env = type("Env", (), {"agi_share_path_abs": str(tmp_path / "share")})()
    assert (
        module._default_pipeline_root(env, {})
        == tmp_path / "share" / "sb3_trainer/pipeline"
    )
    custom_root = module._default_pipeline_root(
        env,
        {"dataset_custom_base": str(tmp_path), "dataset_subpath": "pipeline"},
    )
    assert custom_root == tmp_path / "pipeline"
    empty_env = type("Env", (), {"agi_share_path_abs": ""})()
    assert module._default_pipeline_root(empty_env, {}) is None


def test_decision_timing_is_deduplicated_and_converted_to_milliseconds() -> None:
    module = _load_module()
    allocations = pd.DataFrame(
        [
            {
                "model": "ILP",
                "time_index": 0,
                "time_s": 0.0,
                "active_demands": 2,
                "active": True,
                "decision_preparation_time_ns": 100_000_000,
                "decision_core_time_ns": 20_000_000,
                "decision_realization_time_ns": 5_000_000,
                "decision_time_ns": 125_000_000,
            },
            # The exporter repeats step timing on every allocation row.
            {
                "model": "ILP",
                "time_index": 0,
                "time_s": 0.0,
                "active_demands": 2,
                "active": True,
                "decision_preparation_time_ns": 100_000_000,
                "decision_core_time_ns": 20_000_000,
                "decision_realization_time_ns": 5_000_000,
                "decision_time_ns": 125_000_000,
            },
            {
                "model": "Path-AC",
                "time_index": 1,
                "time_s": 60.0,
                "active_demands": 3,
                "active": True,
                "decision_preparation_time_ns": 200_000_000,
                "decision_core_time_ns": 10_000_000,
                "decision_realization_time_ns": 10_000_000,
                "decision_time_ns": 220_000_000,
            },
        ]
    )
    timing = module.build_decision_timing_data(allocations)
    assert len(timing) == 2
    assert timing.loc[timing["model"] == "ILP", "decision_time_ms"].iloc[0] == 125.0

    summary = module.build_decision_timing_summary(timing).set_index("model")
    assert summary.loc["ILP", "decision_count"] == 1
    assert summary.loc["ILP", "core_median_ms"] == 20.0
    assert summary.loc["Path-AC", "total_time_s"] == 0.22

    distribution = module.build_decision_timing_distribution_figure(
        timing, ["ILP", "Path-AC"]
    )
    over_time = module.build_decision_timing_over_time_figure(
        timing, ["ILP", "Path-AC"]
    )
    scaling = module.build_decision_timing_scaling_figure(
        timing, ["ILP", "Path-AC"]
    )
    assert len(distribution.data) == 4
    assert len(over_time.data) == 2
    assert len(scaling.data) == 2


def test_decision_timing_summary_handles_legacy_exports() -> None:
    module = _load_module()
    timing = module.build_decision_timing_data(
        pd.DataFrame([{"model": "PPO-GNN", "time_index": 0, "time_s": 0.0}])
    )
    summary = module.build_decision_timing_summary(timing)
    assert summary.loc[0, "decision_count"] == 0
    assert math.isnan(summary.loc[0, "total_median_ms"])


def test_routing_model_comparison_scoped_env_reuses_or_initializes(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_module()
    app_path = tmp_path / "apps" / "routing_app"
    app_path.mkdir(parents=True)
    streamlit = _StreamlitStub()
    reused_env = SimpleNamespace(apps_path=app_path.parent, app=app_path.name)
    streamlit.session_state["env"] = reused_env
    resets: list[tuple[dict[str, object], Path]] = []

    monkeypatch.setattr(module, "st", streamlit)
    monkeypatch.setattr(module, "_resolve_active_app", lambda: app_path)
    monkeypatch.setattr(
        module,
        "reset_scoped_session_state",
        lambda state, scope_key, active, prefixes: (
            resets.append((state, active)) or False
        ),
    )

    assert module._ensure_app_scoped_env() is reused_env
    assert resets == [(streamlit.session_state, app_path)]

    stale_env = SimpleNamespace(
        apps_path=app_path.parent,
        app="other_routing_app",
    )
    streamlit.session_state["env"] = stale_env
    created: list[dict[str, object]] = []

    class FakeAgiEnv:
        @staticmethod
        def session_for_app(**kwargs):
            env = type("Env", (), {})()
            created.append(kwargs)
            return env

    monkeypatch.setattr(module, "AgiEnv", FakeAgiEnv)
    monkeypatch.setattr(
        module, "reset_scoped_session_state", lambda *_args, **_kwargs: False
    )

    env = module._ensure_app_scoped_env()

    assert created == [
        {"apps_path": app_path.parent, "app": app_path.name, "verbose": 0}
    ]
    assert env is not stale_env
    assert getattr(env, "init_done") is True
    assert streamlit.session_state["env"] is env


def test_routing_model_comparison_loads_and_summarizes_allocations(
    tmp_path: Path,
) -> None:
    module = _load_module()
    base = tmp_path / "pipeline"
    ilp_path = base / "trainer_fcas_routing_ilp" / "allocations_steps.json"
    ppo_path = base / "trainer_fcas_routing_ppo_gnn" / "allocations_steps.json"
    ilp_path.parent.mkdir(parents=True)
    ppo_path.parent.mkdir(parents=True)
    ilp_path.write_text(
        json.dumps(
            [
                {
                    "time_index": 0,
                    "allocations": [
                        ["ignored", "non-dict"],
                        {
                            "source_label": "A",
                            "destination_label": "B",
                            "bandwidth": 10.0,
                            "delivered_bandwidth": 10.0,
                            "served_fraction": 1.0,
                            "latency_ms": 20.0,
                            "latency_target_ms": 30.0,
                            "routed": True,
                            "bearers": ["SAT", "IVDL"],
                            "path": [[1, 2], [2, 3]],
                        },
                        {
                            "source": "C",
                            "destination": "D",
                            "bandwidth": 4.0,
                            "delivered_bandwidth": 0.0,
                            "path_found": False,
                        },
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )
    ppo_path.write_text(
        json.dumps(
            [
                {
                    "time_index": 0,
                    "allocations": [
                        {
                            "source_label": "A",
                            "destination_label": "B",
                            "bandwidth": 10.0,
                            "delivered_bandwidth": 5.0,
                            "latency_ms": 45.0,
                            "latency_target_ms": 30.0,
                            "routed": True,
                            "bearers": ["SAT"],
                            "path_labels": ["A", "relay", "B"],
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    signatures = module.available_file_signatures(base)
    alloc_df = module.load_allocations(signatures)
    alloc_df = module.add_latency_targets(alloc_df)
    summary = module.build_summary(alloc_df)
    demand_matrix = module.build_demand_matrix_data(alloc_df)
    failures = module.build_failure_table(alloc_df)

    assert set(alloc_df["model"]) == {"ILP", "PPO-GNN"}
    assert alloc_df["outcome"].tolist().count("fulfilled") == 1
    assert alloc_df["outcome"].tolist().count("unrouted") == 1
    assert alloc_df["outcome"].tolist().count("partial") == 1
    assert summary.set_index("model").loc["ILP", "routed_count"] == 1
    assert summary.set_index("model").loc["PPO-GNN", "latency_violation_rate"] == 1.0
    demand_by_pair = demand_matrix.set_index(
        ["model", "source_label", "destination_label"]
    )
    assert demand_by_pair.loc[("ILP", "A", "B"), "served_bandwidth_ratio"] == 1.0
    assert demand_by_pair.loc[("ILP", "C", "D"), "unmet_bandwidth_ratio"] == 1.0
    assert demand_by_pair.loc[("ILP", "C", "D"), "unrouted_rate"] == 1.0
    assert demand_by_pair.loc[("PPO-GNN", "A", "B"), "mean_latency_ms"] == 45.0
    assert len(failures) == 2
    assert "latency_over_target_ms" in failures.columns


def test_routing_model_comparison_filters_to_active_demand_schedule(
    tmp_path: Path,
) -> None:
    module = _load_module()
    base = tmp_path / "pipeline"
    _write_allocations(
        base / "trainer_fcas_routing_ilp" / "allocations_steps.json",
        [
            {
                "source_label": "active-source",
                "destination_label": "active-destination",
                "bandwidth": 10.0,
                "delivered_bandwidth": 10.0,
                "active": True,
            },
            {
                "source_label": "inactive-source",
                "destination_label": "inactive-destination",
                "bandwidth": 20.0,
                "delivered_bandwidth": 0.0,
                "active": False,
            },
            {
                "source_label": "active-unrouted-source",
                "destination_label": "active-unrouted-destination",
                "bandwidth": 5.0,
                "delivered_bandwidth": 0.0,
                "routed": False,
                "active": True,
            },
        ],
    )
    _write_allocations(
        base / "trainer_fcas_routing_ppo_gnn" / "allocations_steps.json",
        [
            {
                "source_label": "active-source",
                "destination_label": "active-destination",
                "bandwidth": 10.0,
                "delivered_bandwidth": 5.0,
            },
            {
                "source_label": "inactive-source",
                "destination_label": "inactive-destination",
                "bandwidth": 20.0,
                "delivered_bandwidth": 0.0,
            },
            {
                "source_label": "unknown-source",
                "destination_label": "unknown-destination",
                "bandwidth": 30.0,
                "delivered_bandwidth": 30.0,
            },
        ],
    )

    alloc_df = module.load_allocations(module.available_file_signatures(base))
    failures = module.build_failure_table(module.add_latency_targets(alloc_df.copy()))

    assert len(alloc_df) == 4
    assert set(alloc_df["model"]) == {"ILP", "PPO-GNN"}
    assert set(alloc_df["source_label"]) == {
        "active-source",
        "active-unrouted-source",
        "unknown-source",
    }
    assert alloc_df["requested_mbps"].sum() == 55.0
    assert alloc_df.loc[alloc_df["source_label"] == "active-source", "active"].all()
    assert "active-unrouted-source" in set(failures["source_label"])
    assert "inactive-source" not in set(failures["source_label"])


def test_routing_model_comparison_retains_legacy_rows_without_active_evidence(
    tmp_path: Path,
) -> None:
    module = _load_module()
    base = tmp_path / "pipeline"
    _write_allocations(
        base / "trainer_fcas_routing_ilp" / "allocations_steps.json",
        [
            {
                "source_label": "legacy-source",
                "destination_label": "legacy-destination",
                "bandwidth": 10.0,
                "delivered_bandwidth": 10.0,
            }
        ],
    )

    alloc_df = module.load_allocations(module.available_file_signatures(base))

    assert len(alloc_df) == 1
    assert alloc_df.iloc[0]["source_label"] == "legacy-source"
    assert alloc_df["active"].isna().all()


def test_routing_model_comparison_matches_duplicate_demands_by_occurrence(
    tmp_path: Path,
) -> None:
    module = _load_module()
    base = tmp_path / "pipeline"
    ilp_path = base / "trainer_fcas_routing_ilp" / "allocations_steps.json"
    ppo_path = base / "trainer_fcas_routing_ppo_gnn" / "allocations_steps.json"
    ilp_path.parent.mkdir(parents=True)
    ppo_path.parent.mkdir(parents=True)
    common_pair = {
        "source_label": "duplicate-source",
        "destination_label": "duplicate-destination",
    }
    ilp_path.write_text(
        json.dumps(
            [
                {
                    "time_index": 0,
                    "allocations": [
                        {**common_pair, "bandwidth": 1.0, "active": True},
                        {**common_pair, "bandwidth": 2.0, "active": False},
                    ],
                },
                {
                    "time_index": 1,
                    "allocations": [
                        {**common_pair, "bandwidth": 1.0, "active": False},
                        {**common_pair, "bandwidth": 2.0, "active": True},
                    ],
                },
            ]
        ),
        encoding="utf-8",
    )
    ppo_path.write_text(
        json.dumps(
            [
                {
                    "time_index": time_index,
                    "allocations": [
                        {**common_pair, "bandwidth": 1.0},
                        {**common_pair, "bandwidth": 2.0},
                    ],
                }
                for time_index in (0, 1)
            ]
        ),
        encoding="utf-8",
    )

    alloc_df = module.load_allocations(module.available_file_signatures(base))
    bandwidths_by_model_and_time = {
        key: values.tolist()
        for key, values in alloc_df.groupby(["model", "time_index"], observed=False)[
            "requested_mbps"
        ]
    }

    assert bandwidths_by_model_and_time == {
        ("ILP", 0): [1.0],
        ("ILP", 1): [2.0],
        ("PPO-GNN", 0): [1.0],
        ("PPO-GNN", 1): [2.0],
    }


def test_routing_model_comparison_excludes_conflicting_active_evidence(
    tmp_path: Path,
) -> None:
    module = _load_module()
    base = tmp_path / "pipeline"
    conflicting = {
        "source_label": "conflict-source",
        "destination_label": "conflict-destination",
        "bandwidth": 10.0,
    }
    _write_allocations(
        base / "trainer_fcas_routing_ilp" / "allocations_steps.json",
        [{**conflicting, "active": False}],
    )
    _write_allocations(
        base / "trainer_fcas_routing_path_ac" / "allocations_steps.json",
        [{**conflicting, "active": True}],
    )
    _write_allocations(
        base / "trainer_fcas_routing_ppo_gnn" / "allocations_steps.json",
        [
            conflicting,
            {
                "source_label": "legacy-source",
                "destination_label": "legacy-destination",
                "bandwidth": 5.0,
            },
        ],
    )

    alloc_df = module.load_allocations(module.available_file_signatures(base))

    assert alloc_df["source_label"].tolist() == ["legacy-source"]
    assert alloc_df.attrs[module.ACTIVE_DEMAND_CONFLICT_ATTR] == 1


def test_routing_model_comparison_figures_handle_empty_and_visible_models() -> None:
    module = _load_module()
    alloc_df = pd.DataFrame(
        [
            {
                "model": "ILP",
                "time_index": 0,
                "source_label": "A",
                "destination_label": "B",
                "requested_mbps": 10.0,
                "satisfaction_ratio": 1.0,
                "delivered_mbps": 10.0,
                "latency_ms": 20.0,
                "latency_violation": False,
                "routed": True,
                "outcome": "fulfilled",
                "hop_count": 2,
                "sat_edge_count": 1,
                "ivdl_edge_count": 1,
            },
            {
                "model": "PPO-GNN",
                "time_index": 0,
                "source_label": "A",
                "destination_label": "B",
                "requested_mbps": 10.0,
                "satisfaction_ratio": 0.5,
                "delivered_mbps": 5.0,
                "latency_ms": 45.0,
                "latency_violation": True,
                "routed": True,
                "outcome": "partial",
                "hop_count": 2,
                "sat_edge_count": 1,
                "ivdl_edge_count": 0,
            },
        ]
    )
    summary = pd.DataFrame(
        [
            {
                "model": "ILP",
                "served_bandwidth_ratio": 1.0,
                "mean_latency_ms": 20.0,
                "latency_violation_rate": 0.0,
                "routed_count": 1,
            },
            {
                "model": "PPO-GNN",
                "served_bandwidth_ratio": 0.5,
                "mean_latency_ms": 45.0,
                "latency_violation_rate": 1.0,
                "routed_count": 1,
            },
        ]
    )
    models = ["ILP", "PPO-GNN"]

    assert len(module.build_overview_figure(alloc_df, summary, models).data) >= 4
    time_figure = module.build_time_figure(alloc_df, models)
    assert len(time_figure.data) == 4
    assert time_figure.data[0].name == "Requested bandwidth"
    assert time_figure.data[1].name == "ILP delivered bandwidth"
    assert time_figure.data[2].name == "Requested bandwidth"
    assert time_figure.data[3].name == "PPO-GNN delivered bandwidth"
    assert time_figure.data[0].showlegend is True
    assert time_figure.data[2].showlegend is False
    assert [
        annotation.text for annotation in time_figure.layout.annotations
    ] == [
        "ILP: requested vs delivered bandwidth",
        "PPO-GNN: requested vs delivered bandwidth",
    ]
    satisfaction_figure = module.build_demand_satisfaction_heatmap_figure(
        alloc_df, models
    )
    assert len(satisfaction_figure.data) == 2
    assert satisfaction_figure.data[0].mode == "markers"
    assert satisfaction_figure.data[0].marker.symbol == "square"
    assert satisfaction_figure.data[0].marker.size == 5
    assert satisfaction_figure.data[0].marker.cmin == 0.0
    assert satisfaction_figure.data[0].marker.cmax == 1.0
    assert satisfaction_figure.data[0].marker.showscale is True
    assert satisfaction_figure.data[0].marker.line.width == 0.5
    assert satisfaction_figure.data[1].marker.showscale is True
    assert satisfaction_figure.data[1].marker.colorbar.title.text == "Satisfaction ratio"
    assert satisfaction_figure.layout.height == 840
    assert satisfaction_figure.layout.yaxis.tickmode == "array"
    assert satisfaction_figure.layout.yaxis.showticklabels is True
    assert satisfaction_figure.layout.yaxis2.showticklabels is True
    assert satisfaction_figure.layout.plot_bgcolor is None
    assert satisfaction_figure.layout.paper_bgcolor is None
    assert [
        annotation.text for annotation in satisfaction_figure.layout.annotations
    ] == [
        "ILP: raw active demand satisfaction over time",
        "PPO-GNN: raw active demand satisfaction over time",
    ]
    assert satisfaction_figure.layout.xaxis.showgrid is True
    assert satisfaction_figure.layout.xaxis.title.text == "Time index"
    assert satisfaction_figure.layout.xaxis2.title.text == "Time index"
    assert satisfaction_figure.layout.xaxis.showticklabels is True
    assert satisfaction_figure.layout.xaxis2.showticklabels is True
    assert satisfaction_figure.layout.yaxis.showgrid is True
    demand_figure = module.build_demand_matrix_figure(alloc_df, models)
    assert len(demand_figure.data) == 8
    ratio_traces = [
        trace for index, trace in enumerate(demand_figure.data) if index % 4 != 3
    ]
    assert {trace.zmin for trace in ratio_traces} == {0.0}
    assert {trace.zmax for trace in ratio_traces} == {1.0}
    latency_traces = demand_figure.data[3::4]
    assert {trace.zmin for trace in latency_traces} == {0.0}
    assert {trace.zmax for trace in latency_traces} == {45.0}
    assert len(module.build_path_figure(alloc_df, models).data) >= 2
    no_routed = alloc_df.assign(routed=False)
    assert len(module.build_path_figure(no_routed, models).data) == 2
    assert module._format_summary(summary).columns.tolist() == models
    assert module.build_demand_matrix_data(pd.DataFrame()).empty
    assert len(module.build_demand_matrix_figure(pd.DataFrame(), models).data) == 0


def test_demand_matrix_caps_delivery_and_preserves_full_node_identity() -> None:
    module = _load_module()
    alloc_df = pd.DataFrame(
        [
            {
                "model": "ILP",
                "source_label": "A-S1",
                "destination_label": "destination",
                "requested_mbps": 10.0,
                "delivered_mbps": 20.0,
                "routed": True,
                "latency_ms": 10.0,
            },
            {
                "model": "ILP",
                "source_label": "A-S1",
                "destination_label": "destination",
                "requested_mbps": 10.0,
                "delivered_mbps": 0.0,
                "routed": False,
                "latency_ms": math.nan,
            },
            {
                "model": "ILP",
                "source_label": "A-S1",
                "destination_label": "destination",
                "requested_mbps": math.nan,
                "delivered_mbps": 100.0,
                "routed": True,
                "latency_ms": 12.0,
            },
            {
                "model": "ILP",
                "source_label": "B-S1",
                "destination_label": "destination",
                "requested_mbps": 5.0,
                "delivered_mbps": 5.0,
                "routed": True,
                "latency_ms": 8.0,
            },
        ]
    )

    matrix = module.build_demand_matrix_data(alloc_df).set_index("source_label")
    figure = module.build_demand_matrix_figure(alloc_df, ["ILP"])

    assert matrix.loc["A-S1", "served_bandwidth_ratio"] == 0.5
    assert matrix.loc["A-S1", "unmet_bandwidth_ratio"] == 0.5
    assert list(figure.data[0].x) == ["A-S1", "B-S1"]
    assert all(trace.showscale is False for trace in figure.data)
    assert figure.layout.xaxis3.domain == figure.layout.xaxis.domain
    assert figure.layout.yaxis3.domain != figure.layout.yaxis.domain


def test_routing_model_comparison_empty_helpers_and_metrics(monkeypatch) -> None:
    module = _load_module()

    empty = pd.DataFrame()
    assert module.add_latency_targets(empty) is empty
    empty_allocations = pd.DataFrame(columns=["model"])
    assert module.build_summary(empty_allocations).empty
    failures = module.build_failure_table(
        pd.DataFrame(
            [
                {
                    "model": "ILP",
                    "time_index": 0,
                    "source_label": "A",
                    "destination_label": "B",
                    "outcome": "fulfilled",
                    "requested_mbps": 1.0,
                    "delivered_mbps": 1.0,
                    "satisfaction_ratio": 1.0,
                    "latency_ms": 10.0,
                    "latency_target_used_ms": 20.0,
                    "latency_violation": False,
                    "hop_count": 1,
                    "bearers": "SAT",
                    "path": "A -> B",
                }
            ]
        )
    )
    assert failures.empty

    streamlit = _StreamlitStub()
    monkeypatch.setattr(module, "st", streamlit)
    module.render_metric_row(pd.DataFrame())
    assert streamlit.calls == []

    sparse_summary = pd.DataFrame(
        [
            {
                "model": "ILP",
                "served_bandwidth_ratio": 1.0,
                "mean_latency_ms": math.nan,
                "latency_violation_rate": math.nan,
                "routed_count": 1,
            }
        ]
    )
    module.render_metric_row(sparse_summary)
    assert [name for name, _args in streamlit.calls].count("metric") == 2


def test_routing_model_comparison_package_bundle_root() -> None:
    package_src = str(ROOT / "src/agilab/apps-pages/view_routing_model_comparison/src")
    if package_src not in sys.path:
        sys.path.insert(0, package_src)

    package = importlib.import_module("view_routing_model_comparison")

    assert package.bundle_root().name == "view_routing_model_comparison"


def test_routing_model_comparison_main_renders_pipeline(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_module()
    pipeline_dir = tmp_path / "pipeline"
    app = tmp_path / "apps" / "routing_app"
    settings_path = app / "src" / "app_settings.toml"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(
        "[pages.view_routing_model_comparison]\n"
        f"dataset_custom_base = {json.dumps(str(tmp_path))}\n"
        "dataset_subpath = 'pipeline'\n",
        encoding="utf-8",
    )
    _write_allocations(
        pipeline_dir / "trainer_fcas_routing_ilp" / "allocations_steps.json",
        [
            {
                "source_label": "A",
                "destination_label": "B",
                "bandwidth": 10.0,
                "delivered_bandwidth": 10.0,
                "served_fraction": 1.0,
                "latency_ms": 20.0,
                "latency_target_ms": 30.0,
                "routed": True,
                "bearers": ["SAT", "IVDL"],
                "path": [[1, 2]],
            }
        ],
    )
    streamlit = _StreamlitStub()
    env = type("Env", (), {"agi_share_path_abs": ""})()

    monkeypatch.setattr(module, "st", streamlit)
    monkeypatch.setattr(
        module, "configure_streamlit_page", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        module, "render_streamlit_page_header", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(module, "_ensure_app_scoped_env", lambda: env)
    monkeypatch.setattr(module, "_resolve_active_app", lambda: app)

    module.main()

    call_names = [name for name, _args in streamlit.calls]
    assert "expander" in call_names
    assert call_names.count("plotly_chart") == 5
    assert "dataframe" in call_names
    assert any(
        name == "subheader" and args[0] == "Demand Satisfaction Over Time"
        for name, args in streamlit.calls
    )
    assert any(
        name == "tabs" and "Demand Matrix" in args for name, args in streamlit.calls
    )
    assert any(
        name == "caption" and "Loaded 1 allocation" in args[0]
        for name, args in streamlit.calls
    )


def test_routing_model_comparison_main_requests_wide_layout(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_module()
    app = tmp_path / "apps" / "routing_app"
    app.mkdir(parents=True)
    streamlit = _StreamlitStub(pipeline_text="")
    env = type("Env", (), {"agi_share_path_abs": ""})()
    page_configs: list[dict[str, object]] = []

    monkeypatch.setattr(module, "st", streamlit)
    monkeypatch.setattr(
        module,
        "configure_streamlit_page",
        lambda _streamlit, **kwargs: page_configs.append(kwargs),
    )
    monkeypatch.setattr(
        module, "render_streamlit_page_header", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(module, "_ensure_app_scoped_env", lambda: env)
    monkeypatch.setattr(module, "_resolve_active_app", lambda: app)

    module.main()

    assert page_configs == [
        {
            "title": "Routing Model Comparison",
            "layout": "wide",
        }
    ]


def test_routing_model_comparison_main_renders_without_missing_files_or_model_filter(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    pipeline_dir = tmp_path / "pipeline"
    app = tmp_path / "apps" / "routing_app"
    app.mkdir(parents=True)
    for model, rel_path in module.MODEL_FILES.items():
        _write_allocations(
            pipeline_dir / rel_path,
            [
                {
                    "source_label": f"{model}-A",
                    "destination_label": f"{model}-B",
                    "bandwidth": 10.0,
                    "delivered_bandwidth": 10.0,
                    "served_fraction": 1.0,
                    "latency_ms": 20.0,
                    "latency_target_ms": 30.0,
                    "routed": True,
                }
            ],
        )
    streamlit = _StreamlitStub(
        pipeline_text=str(pipeline_dir),
        selected_models=[],
    )
    env = type("Env", (), {"agi_share_path_abs": ""})()

    monkeypatch.setattr(module, "st", streamlit)
    monkeypatch.setattr(
        module, "configure_streamlit_page", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        module, "render_streamlit_page_header", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(module, "_ensure_app_scoped_env", lambda: env)
    monkeypatch.setattr(module, "_resolve_active_app", lambda: app)

    module.main()

    assert all(name != "expander" for name, _args in streamlit.calls)
    assert any(
        name == "caption" and "Loaded 3 allocation" in args[0]
        for name, args in streamlit.calls
    )


def test_routing_model_comparison_main_stops_when_loaded_data_is_empty(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_module()
    pipeline_dir = tmp_path / "pipeline"
    app = tmp_path / "apps" / "routing_app"
    app.mkdir(parents=True)
    _write_allocations(
        pipeline_dir / "trainer_fcas_routing_ilp" / "allocations_steps.json",
        [],
    )
    streamlit = _StreamlitStub(pipeline_text=str(pipeline_dir))
    env = type("Env", (), {"agi_share_path_abs": ""})()

    monkeypatch.setattr(module, "st", streamlit)
    monkeypatch.setattr(
        module, "configure_streamlit_page", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        module, "render_streamlit_page_header", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(module, "_ensure_app_scoped_env", lambda: env)
    monkeypatch.setattr(module, "_resolve_active_app", lambda: app)

    with pytest.raises(_StopStreamlit):
        module.main()

    assert any(
        name == "warning" and "No active-demand allocation data was loaded" in args[0]
        for name, args in streamlit.calls
    )


def test_routing_model_comparison_main_warns_when_filter_removes_rows(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_module()
    pipeline_dir = tmp_path / "pipeline"
    app = tmp_path / "apps" / "routing_app"
    app.mkdir(parents=True)
    _write_allocations(
        pipeline_dir / "trainer_fcas_routing_ilp" / "allocations_steps.json",
        [
            {
                "source_label": "A",
                "destination_label": "B",
                "bandwidth": 10.0,
                "delivered_bandwidth": 10.0,
                "served_fraction": 1.0,
                "routed": True,
            }
        ],
    )
    streamlit = _StreamlitStub(
        pipeline_text=str(pipeline_dir),
        selected_models=["PPO-GNN"],
    )
    env = type("Env", (), {"agi_share_path_abs": ""})()

    monkeypatch.setattr(module, "st", streamlit)
    monkeypatch.setattr(
        module, "configure_streamlit_page", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        module, "render_streamlit_page_header", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(module, "_ensure_app_scoped_env", lambda: env)
    monkeypatch.setattr(module, "_resolve_active_app", lambda: app)

    with pytest.raises(_StopStreamlit):
        module.main()

    assert any(
        name == "warning" and "No allocation rows match" in args[0]
        for name, args in streamlit.calls
    )


def test_routing_model_comparison_main_returns_without_pipeline(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_module()
    app = tmp_path / "apps" / "routing_app"
    app.mkdir(parents=True)
    streamlit = _StreamlitStub(pipeline_text="")
    env = type("Env", (), {"agi_share_path_abs": ""})()

    monkeypatch.setattr(module, "st", streamlit)
    monkeypatch.setattr(
        module, "configure_streamlit_page", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        module, "render_streamlit_page_header", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(module, "_ensure_app_scoped_env", lambda: env)
    monkeypatch.setattr(module, "_resolve_active_app", lambda: app)

    module.main()

    assert any(
        name == "info" and "Data directory not configured" in args[0]
        for name, args in streamlit.calls
    )


def test_routing_model_comparison_app_test_renders_demand_matrix(
    tmp_path: Path,
    monkeypatch,
) -> None:
    pipeline_dir = tmp_path / "pipeline"
    app = tmp_path / "apps" / "routing_app"
    settings_path = app / "src" / "app_settings.toml"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(
        "[pages.view_routing_model_comparison]\n"
        f"dataset_custom_base = {json.dumps(str(tmp_path))}\n"
        "dataset_subpath = 'pipeline'\n",
        encoding="utf-8",
    )
    _write_allocations(
        pipeline_dir / "trainer_fcas_routing_ilp" / "allocations_steps.json",
        [
            {
                "source_label": "flight-000-S001",
                "destination_label": "flight-001-S002",
                "bandwidth": 10.0,
                "delivered_bandwidth": 7.5,
                "latency_ms": 22.0,
                "latency_target_ms": 30.0,
                "routed": True,
            }
        ],
    )

    argv = [MODULE_PATH.name, "--active-app", str(app)]
    with patch.object(sys, "argv", argv):
        monkeypatch.setenv("AGI_EXPORT_DIR", str(tmp_path / "export"))
        monkeypatch.setenv("AGI_LOCAL_SHARE", str(tmp_path / "localshare"))
        monkeypatch.setenv("AGI_CLUSTER_SHARE", str(tmp_path / "clustershare"))
        monkeypatch.setenv("IS_SOURCE_ENV", "1")
        at = AppTest.from_file(str(MODULE_PATH), default_timeout=30)
        at.session_state["env"] = SimpleNamespace(
            apps_path=app.parent,
            app=app.name,
            agi_share_path_abs="",
            st_resources=tmp_path / "resources",
        )
        at.run()

    assert not at.exception
    assert any(
        "Compare served and unmet bandwidth" in caption.value for caption in at.caption
    )
