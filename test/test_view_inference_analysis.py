from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest


MODULE_PATH = Path(
    "src/agilab/apps-pages/view_inference_analysis/src/view_inference_analysis/view_inference_analysis.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("view_inference_analysis_test_module", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeStop(RuntimeError):
    pass


class _FakeStreamlit:
    def __init__(self, *, query_params: dict[str, object] | None = None) -> None:
        self.query_params = query_params or {}
        self.session_state: dict[str, object] = {}
        self.sidebar = _FakeContext()
        self.writes: list[object] = []
        self.infos: list[str] = []
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.headers: list[str] = []
        self.titles: list[str] = []
        self.captions: list[str] = []
        self.dataframes: list[dict[str, object]] = []
        self.plot_calls: list[dict[str, object]] = []

    def set_page_config(self, **_kwargs) -> None:
        return None

    def title(self, value: str) -> None:
        self.titles.append(value)

    def caption(self, value: str) -> None:
        self.captions.append(value)

    def header(self, value: str) -> None:
        self.headers.append(value)

    def write(self, value: object) -> None:
        self.writes.append(value)

    def info(self, value: str) -> None:
        self.infos.append(value)

    def error(self, value: str) -> None:
        self.errors.append(value)

    def warning(self, value: str) -> None:
        self.warnings.append(value)

    def stop(self) -> None:
        raise _FakeStop

    def selectbox(self, _label, options, *, key=None, **_kwargs):
        if key is not None and key not in self.session_state and options:
            self.session_state[key] = options[0]
        return self.session_state.get(key, options[0] if options else None)

    def text_input(self, _label, *, key=None, **_kwargs):
        return self.session_state.get(key, "")

    def text_area(self, _label, *, key=None, **_kwargs):
        return self.session_state.get(key, "")

    def multiselect(self, _label, *, key=None, **_kwargs):
        return self.session_state.get(key, [])

    def dataframe(self, data, **kwargs) -> None:
        self.dataframes.append({"data": data, **kwargs})

    def expander(self, *_args, **_kwargs):
        return _FakeContext()

    def markdown(self, *_args, **_kwargs) -> None:
        return None

    def subheader(self, value: str) -> None:
        self.headers.append(value)

    def plotly_chart(self, fig, *, width: str = "stretch", key: str | None = None) -> None:
        self.plot_calls.append({"fig": fig, "width": width, "key": key})

    def columns(self, spec):
        count = spec if isinstance(spec, int) else len(spec)
        return [_FakeContext() for _ in range(count)]


def test_view_inference_analysis_builds_routed_latency_percentiles() -> None:
    module = _load_module()

    frames = {
        "ppo": pd.DataFrame(
            {
                "time_index": [0, 0, 0, 1, 1],
                "latency": [10.0, 20.0, 999.0, 30.0, 40.0],
                "routed": [1, 1, 0, 1, 1],
            }
        )
    }

    percentile_df = module.build_latency_percentile_frame(frames, "time_index")

    assert set(percentile_df["percentile"]) == {"p50", "p90", "p95"}
    assert set(percentile_df["run_label"]) == {"ppo"}

    lookup = {
        (int(row.time_index), row.percentile): float(row.latency)
        for row in percentile_df.itertuples(index=False)
    }
    assert lookup[(0, "p50")] == pytest.approx(15.0)
    assert lookup[(0, "p90")] == pytest.approx(19.0)
    assert lookup[(0, "p95")] == pytest.approx(19.5)
    assert lookup[(1, "p50")] == pytest.approx(35.0)
    assert lookup[(1, "p90")] == pytest.approx(39.0)
    assert lookup[(1, "p95")] == pytest.approx(39.5)


def test_view_inference_analysis_normalizes_latency_and_delivery_aliases() -> None:
    module = _load_module()

    normalized = module._normalize_allocations_frame(
        pd.DataFrame(
            {
                "time_index": [0, 1],
                "source": [1, 1],
                "destination": [2, 2],
                "latency_ms": [12.0, 14.0],
                "delivered_mbps": [0.8, 0.9],
                "selected_path": [[1, 4, 2], [1, 5, 2]],
                "path_capacity": [1.0, 1.1],
            }
        )
    )

    assert normalized["latency"].tolist() == pytest.approx([12.0, 14.0])
    assert normalized["delivered_bandwidth"].tolist() == pytest.approx([0.8, 0.9])
    assert normalized["path"].tolist() == [[1, 4, 2], [1, 5, 2]]
    assert normalized["capacity_mbps"].tolist() == pytest.approx([1.0, 1.1])


def test_view_inference_analysis_normalizes_nested_allocation_aliases() -> None:
    module = _load_module()

    normalized = module._normalize_allocations_frame(
        pd.DataFrame(
            {
                "time_index": [0],
                "allocations": [[
                    {
                        "source": 1,
                        "destination": 2,
                        "bandwidth": 1.0,
                        "delivered_mbps": 0.8,
                        "latency_ms": 12.0,
                        "selected_path": [1, 4, 2],
                        "path_capacity": 1.1,
                    }
                ]],
            }
        )
    )

    assert normalized["latency"].tolist() == pytest.approx([12.0])
    assert normalized["delivered_bandwidth"].tolist() == pytest.approx([0.8])
    assert normalized["path"].tolist() == [[1, 4, 2]]
    assert normalized["capacity_mbps"].tolist() == pytest.approx([1.1])


def test_view_inference_analysis_attaches_latency_p90_when_available() -> None:
    module = _load_module()

    frames = {
        "ppo": pd.DataFrame(
            {
                "time_index": [0, 0, 1, 1],
                "latency": [10.0, 20.0, 30.0, 40.0],
                "routed": [1, 1, 1, 1],
                "bandwidth": [1.0, 1.0, 1.0, 1.0],
                "delivered_bandwidth": [1.0, 1.0, 1.0, 1.0],
            }
        )
    }
    step_kpi_df = module.build_step_kpi_frame(frames, "time_index")

    enriched = module.attach_latency_p90_frame(step_kpi_df, frames, "time_index")

    assert "p90_routed_latency" in enriched.columns
    values = enriched.sort_values(["run_label", "time_index"])["p90_routed_latency"].tolist()
    assert values == pytest.approx([19.0, 39.0])


def test_view_inference_analysis_keeps_empty_latency_p90_column_when_latency_missing() -> None:
    module = _load_module()

    frames = {
        "ppo": pd.DataFrame(
            {
                "time_index": [0, 0, 1, 1],
                "routed": [1, 1, 1, 1],
                "bandwidth": [1.0, 1.0, 1.0, 1.0],
                "delivered_bandwidth": [1.0, 1.0, 1.0, 1.0],
            }
        )
    }
    step_kpi_df = module.build_step_kpi_frame(frames, "time_index")

    enriched = module.attach_latency_p90_frame(step_kpi_df, frames, "time_index")

    assert "p90_routed_latency" in enriched.columns
    assert enriched["p90_routed_latency"].isna().all()


def test_view_inference_analysis_compare_style_schema_produces_latency_p90() -> None:
    module = _load_module()

    compare_like = module._normalize_allocations_frame(
        pd.DataFrame(
            {
                "time_index": [0, 0, 1, 1],
                "source": [1, 1, 1, 1],
                "destination": [2, 2, 2, 2],
                "bandwidth": [1.0, 1.0, 1.0, 1.0],
                "delivered_mbps": [1.0, 1.0, 1.0, 1.0],
                "latency_ms": [10.0, 20.0, 30.0, 40.0],
                "routed": [1, 1, 1, 1],
            }
        )
    )
    frames = {"edge_gnn": compare_like}
    step_kpi_df = module.build_step_kpi_frame(frames, "time_index")

    enriched = module.attach_latency_p90_frame(step_kpi_df, frames, "time_index")

    assert enriched.sort_values("time_index")["p90_routed_latency"].tolist() == pytest.approx([19.0, 39.0])


def test_view_inference_analysis_prefers_shared_time_index_for_mixed_time_axes() -> None:
    module = _load_module()

    frames = {
        "uav": pd.DataFrame(
            {
                "time_index": [0, 1],
                "t_now_s": [0.5, 1.5],
                "bandwidth": [1.0, 1.0],
                "delivered_bandwidth": [0.8, 0.9],
            }
        ),
        "fcas": pd.DataFrame(
            {
                "time_index": [0, 1],
                "bandwidth": [2.0, 2.0],
                "delivered_bandwidth": [1.5, 1.6],
            }
        ),
    }

    axis = module._choose_time_series_axis(frames)
    step_kpi_df = module.build_step_kpi_frame(frames, axis)

    assert axis == "time_index"
    assert module._axis_options_for_frames(frames) == ["time_index"]
    assert set(step_kpi_df["run_label"]) == {"uav", "fcas"}


def test_view_inference_analysis_prefers_seconds_when_all_runs_have_t_now_s() -> None:
    module = _load_module()

    frames = {
        "run_a": pd.DataFrame({"time_index": [0], "t_now_s": [0.5], "delivered_bandwidth": [1.0]}),
        "run_b": pd.DataFrame({"time_index": [0], "t_now_s": [1.0], "delivered_bandwidth": [2.0]}),
    }

    assert module._choose_time_series_axis(frames) == "t_now_s"
    assert module._axis_options_for_frames(frames) == ["time_index", "t_now_s"]


def test_view_inference_analysis_detects_when_requested_load_varies() -> None:
    module = _load_module()

    assert module._series_varies(pd.Series([10.0, 10.0, 10.0])) is False
    assert module._series_varies(pd.Series([10.0, 10.000000001, 10.0])) is False
    assert module._series_varies(pd.Series([10.0, 11.0, 10.0])) is True


def test_view_inference_analysis_preserves_explicit_empty_selection() -> None:
    module = _load_module()

    options = ["run_a", "run_b"]

    assert module._coerce_selection([], options, fallback=["run_a"]) == []
    assert module._coerce_selection(None, options, fallback=["run_a"]) == ["run_a"]
    assert module._coerce_selection(["missing"], options, fallback=["run_a"]) == ["run_a"]


def test_view_inference_analysis_loads_page_defaults_from_app_settings(tmp_path: Path) -> None:
    module = _load_module()
    settings_path = tmp_path / "app_settings.toml"
    settings_path.write_text(
        f"""
[pages.{module.PAGE_KEY}]
base_choice = "AGI_SHARE_DIR"
selected_files = ["allocations/run_a.csv"]
""",
        encoding="utf-8",
    )
    env = SimpleNamespace(app_settings_file=str(settings_path))

    payload = module._load_app_settings(env)
    defaults = module._get_page_defaults(env)

    assert payload["pages"][module.PAGE_KEY]["base_choice"] == "AGI_SHARE_DIR"
    assert defaults == {
        "base_choice": "AGI_SHARE_DIR",
        "selected_files": ["allocations/run_a.csv"],
    }

    env.app_settings_file = str(tmp_path / "missing.toml")
    assert module._load_app_settings(env) == {}
    assert module._get_page_defaults(env) == {}

    invalid_path = tmp_path / "invalid.toml"
    invalid_path.write_text("pages = [", encoding="utf-8")
    env.app_settings_file = str(invalid_path)
    assert module._load_app_settings(env) == {}


def test_view_inference_analysis_resolves_active_app_from_cli_and_query_params(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    active_app = tmp_path / "demo_project"
    active_app.mkdir()

    cli_streamlit = _FakeStreamlit()
    monkeypatch.setattr(module, "st", cli_streamlit)
    monkeypatch.setattr(module.sys, "argv", ["page.py", "--active-app", str(active_app)])
    assert module._resolve_active_app() == active_app.resolve()

    query_streamlit = _FakeStreamlit(query_params={"project": str(active_app)})
    monkeypatch.setattr(module, "st", query_streamlit)
    monkeypatch.setattr(module.sys, "argv", ["page.py"])
    assert module._resolve_active_app() == active_app.resolve()


def test_view_inference_analysis_resolve_active_app_stops_for_missing_inputs(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_module()

    no_app_streamlit = _FakeStreamlit()
    monkeypatch.setattr(module, "st", no_app_streamlit)
    monkeypatch.setattr(module.sys, "argv", ["page.py"])
    with pytest.raises(_FakeStop):
        module._resolve_active_app()
    assert no_app_streamlit.infos == [
        "Open this page from AGILAB Analysis so the active project is passed via --active-app."
    ]

    missing_path = tmp_path / "missing_project"
    missing_streamlit = _FakeStreamlit(query_params={"active-app": str(missing_path)})
    monkeypatch.setattr(module, "st", missing_streamlit)
    monkeypatch.setattr(module.sys, "argv", ["page.py"])
    with pytest.raises(_FakeStop):
        module._resolve_active_app()
    assert missing_streamlit.errors == [f"Provided --active-app path not found: {missing_path.resolve()}"]


def test_view_inference_analysis_coerces_string_lists_and_resolves_dataset_paths(tmp_path: Path) -> None:
    module = _load_module()
    share_root = tmp_path / "share"
    export_root = tmp_path / "export"
    custom_root = tmp_path / "custom"
    env = SimpleNamespace(
        target="flight",
        AGILAB_EXPORT_ABS=str(export_root),
        share_root_path=lambda: str(share_root),
    )

    assert module._coerce_str_list(" run_a,run_b;\nrun_b\n\n run_c ") == ["run_a", "run_b", "run_c"]
    assert module._coerce_str_list(("run_a", "run_b", "run_a")) == ["run_a", "run_b"]
    assert module._coerce_str_list(42) == ["42"]
    assert module._default_dataset_subpath(env, tmp_path / "demo_project") == "flight/pipeline"

    env.target = ""
    assert module._default_dataset_subpath(env, tmp_path / "demo_project") == "demo/pipeline"
    assert module._resolve_base_path(env, "AGI_SHARE_DIR", "") == share_root
    assert module._resolve_base_path(env, "AGILAB_EXPORT", "") == export_root
    assert export_root.exists()
    assert module._resolve_base_path(env, "custom", str(custom_root)) == custom_root
    assert module._resolve_base_path(env, "custom", "   ") is None
    assert module._resolve_dataset_root(None, "demo/pipeline") is None
    assert module._resolve_dataset_root(share_root, "demo/pipeline") == share_root / "demo" / "pipeline"
    assert module._resolve_dataset_root(share_root, "") == share_root


def test_view_inference_analysis_helper_edges_cover_paths_patterns_and_empty_frames(
    tmp_path: Path,
) -> None:
    module = _load_module()
    root = tmp_path / "dataset"
    root.mkdir()
    outside = tmp_path / "outside.csv"
    outside.write_text("time_index,latency\n0,1\n", encoding="utf-8")
    (root / "allocations_dir.csv").mkdir()
    nested = root / "nested"
    nested.mkdir()
    (nested / "allocations_real.csv").write_text("time_index,latency\n0,1\n", encoding="utf-8")

    class _BrokenRoot:
        def exists(self) -> bool:
            return True

        def glob(self, _pattern: str):
            raise ValueError("bad glob")

    assert module._coerce_str_list(None) == []
    assert module._default_dataset_subpath(SimpleNamespace(target=""), tmp_path / "demo") == "pipeline"
    assert module._relative_path_label(outside, root) == outside.as_posix()
    assert module._run_label(root / "allocations_steps.json", root) == "allocations_steps.json"
    assert module._discover_allocation_files(_BrokenRoot(), ["**/allocations*.csv"]) == []
    assert [path.relative_to(root).as_posix() for path in module._discover_allocation_files(root, ["**/allocations*.csv"])] == [
        "nested/allocations_real.csv"
    ]
    assert module._matches_any_pattern("   ", ["**/*.csv"]) is False
    assert module._matches_any_pattern("nested/file.csv", ["   ", "["]) is False
    assert module._parse_structured_value("   ") == "   "
    assert module._parse_allocations_cell(({"source": 1}, {"destination": 2}, "bad")) == [
        {"source": 1},
        {"destination": 2},
    ]
    assert module._apply_column_aliases(pd.DataFrame()).empty
    assert module._normalize_allocations_frame(pd.DataFrame()).empty
    assert module._coerce_time_index(pd.DataFrame({"step": ["bad", "worse"]}))["time_index"].tolist() == [0, 1]


def test_view_inference_analysis_normalizes_nested_allocations_with_row_index_and_time_fallback() -> None:
    module = _load_module()

    normalized = module._normalize_allocations_frame(
        pd.DataFrame(
            {
                "time_s": [1.5],
                "allocations": ['[{"source": 1, "destination": 2, "delivered_mbps": 0.7}]'],
            }
        )
    )

    assert normalized["time_index"].tolist() == [0]
    assert normalized["t_now_s"].tolist() == pytest.approx([1.5])
    assert normalized["source"].tolist() == [1]
    assert normalized["destination"].tolist() == [2]
    assert normalized["delivered_bandwidth"].tolist() == pytest.approx([0.7])


def test_view_inference_analysis_discovers_visible_allocation_files_and_labels_runs(tmp_path: Path) -> None:
    module = _load_module()
    root = tmp_path / "dataset"
    root.mkdir()
    (root / "allocations_root.csv").write_text("time_index,latency\n0,10\n", encoding="utf-8")
    (root / "nested").mkdir()
    (root / "nested" / "allocations_main.parquet").write_text("placeholder", encoding="utf-8")
    (root / ".hidden").mkdir()
    (root / ".hidden" / "allocations_secret.csv").write_text("time_index,latency\n0,20\n", encoding="utf-8")

    discovered = module._discover_allocation_files(
        root,
        ["**/allocations*.csv", "**/allocations*.parquet"],
    )

    assert [path.relative_to(root).as_posix() for path in discovered] == [
        "allocations_root.csv",
        "nested/allocations_main.parquet",
    ]
    assert module._is_hidden_relative(Path(".hidden/allocations_secret.csv")) is True
    assert module._relative_path_label(root / "nested" / "allocations_main.parquet", root) == (
        "nested/allocations_main.parquet"
    )
    assert module._run_label(root / "nested" / "allocations_main.parquet", root) == "nested"
    assert module._matches_any_pattern("nested/allocations_main.parquet", ["**/allocations*.parquet"]) is True
    assert module._matches_any_pattern("allocations_root.csv", ["allocations*.csv"]) is True
    assert module._matches_any_pattern("nested/ignored.txt", ["**/allocations*.csv"]) is False


def test_view_inference_analysis_parses_structured_cells_and_coerces_time_index() -> None:
    module = _load_module()

    assert module._parse_structured_value('{"source": 1}') == {"source": 1}
    assert module._parse_structured_value("[1, 2, 3]") == [1, 2, 3]
    assert module._parse_structured_value("not structured") == "not structured"
    assert module._parse_allocations_cell('{"source": 1, "destination": 2}') == [
        {"source": 1, "destination": 2}
    ]
    assert module._parse_allocations_cell('[{"source": 1}, "bad", {"destination": 2}]') == [
        {"source": 1},
        {"destination": 2},
    ]
    assert module._parse_allocations_cell("bad") == []
    assert module._is_scalar_like(None) is True
    assert module._is_scalar_like("42") is True
    assert module._is_scalar_like("[1, 2]") is False

    aliased = pd.DataFrame(
        {
            "SRC": [1, 3],
            "To": [2, 4],
            "delivered_mbps": [0.5, 0.7],
            "latency_ms": [12.0, 14.0],
            "selected_path": ["[1, 2]", "[3, 4]"],
            "path_capacity": [0.8, 0.9],
            "step": [2, "bad"],
            "time_s": [0.5, 1.5],
        }
    )

    normalized = module._coerce_time_index(module._apply_column_aliases(aliased.copy()))

    assert module._pick_ci_column(aliased, ("source", "src", "from")) == "SRC"
    assert normalized["source"].tolist() == [1, 3]
    assert normalized["destination"].tolist() == [2, 4]
    assert normalized["delivered_bandwidth"].tolist() == pytest.approx([0.5, 0.7])
    assert normalized["latency"].tolist() == pytest.approx([12.0, 14.0])
    assert normalized["path"].tolist() == ["[1, 2]", "[3, 4]"]
    assert normalized["capacity_mbps"].tolist() == pytest.approx([0.8, 0.9])
    assert normalized["time_index"].tolist() == [2, 1]
    assert normalized["t_now_s"].tolist() == pytest.approx([0.5, 1.5])

    fallback = module._coerce_time_index(pd.DataFrame({"latency": [10.0, 20.0]}))
    assert fallback["time_index"].tolist() == [0, 1]


def test_view_inference_analysis_loads_allocation_files_from_common_formats(tmp_path: Path) -> None:
    module = _load_module()
    csv_path = tmp_path / "allocations.csv"
    csv_path.write_text(
        "step,source,destination,delivered_mbps,latency_ms,selected_path,path_capacity,time_s\n"
        "0,1,2,0.5,12.0,\"[1, 2]\",0.8,1.5\n",
        encoding="utf-8",
    )
    jsonl_path = tmp_path / "allocations.jsonl"
    jsonl_path.write_text(
        '\n{"step": 1, "source": 2, "destination": 3, "delivered_mbps": 0.7, "latency_ms": 14.0}\n',
        encoding="utf-8",
    )
    json_path = tmp_path / "allocations.json"
    json_path.write_text(
        '{"allocations_steps": [{"step": 2, "source": 3, "destination": 4, "delivered_mbps": 0.9, "latency_ms": 16.0}]}',
        encoding="utf-8",
    )
    steps_path = tmp_path / "steps.json"
    steps_path.write_text(
        '{"steps": [{"step": 3, "source": 4, "destination": 5, "delivered_mbps": 1.1, "latency_ms": 18.0}]}',
        encoding="utf-8",
    )
    invalid_path = tmp_path / "broken.json"
    invalid_path.write_text("{broken", encoding="utf-8")

    csv_df = module.load_allocations(csv_path)
    jsonl_df = module.load_allocations(jsonl_path)
    json_df = module.load_allocations(json_path)
    steps_df = module._load_allocations_cached(str(steps_path), steps_path.stat().st_mtime_ns, 1)

    assert csv_df["time_index"].tolist() == [0]
    assert csv_df["source"].tolist() == [1]
    assert csv_df["destination"].tolist() == [2]
    assert csv_df["delivered_bandwidth"].tolist() == pytest.approx([0.5])
    assert csv_df["latency"].tolist() == pytest.approx([12.0])
    assert csv_df["path"].tolist() == ["[1, 2]"]
    assert csv_df["capacity_mbps"].tolist() == pytest.approx([0.8])
    assert csv_df["t_now_s"].tolist() == pytest.approx([1.5])
    assert jsonl_df["time_index"].tolist() == [1]
    assert json_df["time_index"].tolist() == [2]
    assert steps_df["time_index"].tolist() == [3]
    assert module.load_allocations(tmp_path / "missing.json").empty
    assert module.load_allocations(invalid_path).empty


@pytest.mark.parametrize(
    ("aggregation", "expected"),
    [
        ("mean", [2.0, 7.0]),
        ("sum", [4.0, 14.0]),
        ("median", [2.0, 7.0]),
        ("min", [1.0, 5.0]),
        ("max", [3.0, 9.0]),
        ("std", [pytest.approx(1.41421356237), pytest.approx(2.82842712475)]),
        ("count", [2.0, 2.0]),
    ],
)
def test_view_inference_analysis_discovers_metrics_and_builds_profiles(
    aggregation: str,
    expected: list[object],
) -> None:
    module = _load_module()
    frames = {
        "run_a": pd.DataFrame(
            {
                "time_index": [0, 0, 1, 1],
                "reward": [1.0, 3.0, 5.0, 9.0],
                "latency": [10.0, 11.0, 12.0, 13.0],
                "delivered_bandwidth": [0.2, 0.4, 0.6, 0.8],
                "routed": [True, False, True, True],
                "seed": [1, 1, 1, 1],
            }
        ),
        "run_b": pd.DataFrame(
            {
                "time_index": [0, 1],
                "custom_metric": [8.0, 9.0],
            }
        ),
    }

    metrics = module.discover_metric_columns(frames)
    profile = module.build_profile_frame(frames, "reward", aggregation, "time_index")
    color_map = module._run_color_map(["run_a", "run_b"])

    assert metrics[:4] == ["delivered_bandwidth", "reward", "latency", "routed"]
    assert metrics[-1] == "custom_metric"
    assert profile.index.tolist() == [0, 1]
    assert profile["run_a"].tolist() == pytest.approx(expected)
    assert list(color_map) == ["run_a", "run_b"]
    assert module._metric_series(frames["run_a"], "routed").tolist() == pytest.approx([1.0, 0.0, 1.0, 1.0])


def test_view_inference_analysis_metric_and_profile_helpers_handle_empty_inputs() -> None:
    module = _load_module()

    frames = {
        "empty": pd.DataFrame(),
        "excluded_only": pd.DataFrame({"time_index": [0], "seed": [1], "reward": ["bad"]}),
    }

    assert module.discover_metric_columns(frames) == []
    assert module.build_profile_frame(
        {"bad": pd.DataFrame({"time_index": ["bad"], "reward": ["nan"]})},
        "reward",
        "mean",
        "time_index",
    ).empty


def test_view_inference_analysis_profile_builder_rejects_unknown_aggregation() -> None:
    module = _load_module()
    frames = {"run_a": pd.DataFrame({"time_index": [0, 1], "reward": [1.0, 2.0]})}

    with pytest.raises(ValueError, match="Unsupported aggregation"):
        module.build_profile_frame(frames, "reward", "mode", "time_index")


def test_view_inference_analysis_builds_inventory_and_path_helpers(tmp_path: Path) -> None:
    module = _load_module()
    root = tmp_path / "dataset"
    root.mkdir()
    existing_path = root / "run_a" / "allocations.csv"
    existing_path.parent.mkdir()
    existing_path.write_text("time_index,latency\n0,1\n1,2\n", encoding="utf-8")
    missing_path = root / "run_b" / "allocations.csv"
    frames = {
        "run_a": pd.DataFrame({"time_index": [0, 1], "latency": [1.0, 2.0]}),
        "run_b": pd.DataFrame({"latency": [3.0]}),
    }

    inventory = module.build_inventory_frame(
        frames,
        {"run_b": missing_path, "run_a": existing_path},
        root,
    )

    assert inventory["run_label"].tolist() == ["run_a", "run_b"]
    assert inventory["relative_path"].tolist() == ["run_a/allocations.csv", "run_b/allocations.csv"]
    assert inventory["rows"].tolist() == [2, 1]
    assert inventory["steps"].tolist() == [2, 0]
    assert inventory["columns"].tolist() == [2, 1]
    assert inventory.loc[inventory["run_label"] == "run_a", "modified_utc"].item()
    assert inventory.loc[inventory["run_label"] == "run_b", "modified_utc"].item() == ""


def test_view_inference_analysis_handles_list_and_path_helper_edges() -> None:
    module = _load_module()

    assert module._parse_list_like("[1, 2, 3]") == [1, 2, 3]
    assert module._parse_list_like("(1, 2)") == [1, 2]
    assert module._parse_list_like("scalar") == []
    assert module._is_missing_value(pd.NA) is True
    assert module._is_missing_value([1, 2]) is False

    routed = module._routed_flag_series(pd.DataFrame({"routed": [1, None, 2, -1]}))
    delivered = module._routed_flag_series(pd.DataFrame({"delivered_bandwidth": [0.0, 0.1, None]}))
    defaulted = module._routed_flag_series(pd.DataFrame({"latency": [1.0, 2.0]}))

    assert routed.tolist() == pytest.approx([1.0, 0.0, 1.0, 0.0])
    assert delivered.tolist() == pytest.approx([0.0, 1.0, 0.0])
    assert defaulted.tolist() == pytest.approx([0.0, 0.0])

    assert module._coerce_path_sequence("[1, 2, null, 3]") == [1, 2, 3]
    assert module._coerce_path_sequence("[[1, 2, 3]]") == [1, 2, 3]
    assert module._coerce_path_sequence("[[1, 2], [2, 3], null]") == [[1, 2], [2, 3]]
    assert module._coerce_path_sequence("invalid") == []
    assert module._path_hop_count("[1, 2, 3, 4]") == 3
    assert module._path_hop_count("[[1, 2], [2, 3], [3, 4]]") == 3
    assert module._path_hop_count("[]") is None


def test_view_inference_analysis_distribution_helpers_return_empty_when_inputs_do_not_qualify() -> None:
    module = _load_module()

    assert module.build_step_kpi_frame(
        {
            "missing_axis": pd.DataFrame({"latency": [1.0]}),
            "nan_axis": pd.DataFrame({"time_index": ["bad"], "bandwidth": [1.0]}),
        },
        "time_index",
    ).empty
    assert module.build_latency_distribution_frame(
        {
            "missing_latency": pd.DataFrame({"delivered_bandwidth": [1.0]}),
            "unrouted_only": pd.DataFrame({"latency": [5.0], "routed": [0]}),
        }
    ).empty
    assert module.build_hop_count_distribution_frame(
        {
            "missing_path": pd.DataFrame({"latency": [1.0]}),
            "invalid_path": pd.DataFrame({"path": [None], "routed": [1]}),
        }
    ).empty
    assert module.build_latency_percentile_frame(
        {"missing_latency": pd.DataFrame({"time_index": [0], "routed": [1]})},
        "time_index",
    ).empty
    assert module.attach_latency_p90_frame(
        pd.DataFrame(),
        {"missing_latency": pd.DataFrame({"time_index": [0], "routed": [1]})},
        "time_index",
    ).empty


def test_view_inference_analysis_aligns_heatmap_frames_to_shared_axes() -> None:
    module = _load_module()

    matrices = {
        "run_a": pd.DataFrame(
            [[10.0, 20.0], [30.0, 40.0]],
            index=pd.Index([1, 3]),
            columns=pd.Index([1001, 2002]),
        ),
        "run_b": pd.DataFrame(
            [[50.0, 60.0], [70.0, 80.0]],
            index=pd.Index([3, 5]),
            columns=pd.Index([2002, 3003]),
        ),
    }

    aligned, rows, columns = module.align_heatmap_frames(matrices)

    assert rows.tolist() == [1, 3, 5]
    assert columns.tolist() == [1001, 2002, 3003]
    assert aligned["run_a"].index.tolist() == [1, 3, 5]
    assert aligned["run_a"].columns.tolist() == [1001, 2002, 3003]
    assert pd.isna(aligned["run_a"].loc[5, 3003])
    assert pd.isna(aligned["run_b"].loc[1, 1001])


def test_view_inference_analysis_can_align_heatmaps_to_one_square_node_axis() -> None:
    module = _load_module()

    matrices = {
        "run_a": pd.DataFrame(
            [[10.0, 20.0], [30.0, 40.0]],
            index=pd.Index([1, 3]),
            columns=pd.Index([1001, 2002]),
        ),
        "run_b": pd.DataFrame(
            [[50.0, 60.0], [70.0, 80.0]],
            index=pd.Index([3, 5]),
            columns=pd.Index([2002, 3003]),
        ),
    }
    node_axis = pd.Index([])
    for matrix in matrices.values():
        node_axis = node_axis.union(matrix.index).union(matrix.columns)

    aligned, rows, columns = module.align_heatmap_frames(
        matrices,
        row_index=node_axis,
        column_index=node_axis,
    )

    assert rows.tolist() == [1, 3, 5, 1001, 2002, 3003]
    assert columns.tolist() == [1, 3, 5, 1001, 2002, 3003]
    assert aligned["run_a"].shape == (6, 6)
    assert aligned["run_b"].shape == (6, 6)
    assert pd.isna(aligned["run_a"].loc[1, 1])
    assert pd.isna(aligned["run_b"].loc[1001, 3003])


def test_view_inference_analysis_formats_heatmap_text_without_applymap_dependency() -> None:
    module = _load_module()

    matrix = pd.DataFrame(
        [[12.345, None], [0.0, 99.99]],
        index=pd.Index([2, 3]),
        columns=pd.Index([10, 11]),
    )

    text = module._format_heatmap_text_frame(matrix)

    assert text.to_dict() == {
        10: {2: "12.3", 3: "0.0"},
        11: {2: "", 3: "100.0"},
    }


def test_view_inference_analysis_builds_uniform_matrix_heatmap_coordinates() -> None:
    module = _load_module()

    matrix = pd.DataFrame(
        [[10.0, None], [20.0, 30.0]],
        index=pd.Index([5, 900]),
        columns=pd.Index([1, 1001]),
    )

    fig = module._build_heatmap_figure(matrix, colorbar_title="Value")
    heatmap = fig.data[0]

    assert list(heatmap.x) == [0, 1]
    assert list(heatmap.y) == [0, 1]
    assert fig.layout.xaxis.title.text == "Source node"
    assert fig.layout.yaxis.title.text == "Destination node"
    assert list(fig.layout.xaxis.ticktext) == ["1", "1001"]
    assert list(fig.layout.yaxis.ticktext) == ["5", "900"]
    assert fig.layout.xaxis.tickangle == -45
    assert fig.layout.yaxis.scaleanchor == "x"
    assert fig.layout.yaxis.scaleratio == 1
    assert heatmap.xgap == 0
    assert heatmap.ygap == 0
    assert len(fig.layout.shapes) == 6
    vertical_boundaries = {
        float(shape.x0)
        for shape in fig.layout.shapes
        if shape.type == "line" and float(shape.x0) == float(shape.x1)
    }
    horizontal_boundaries = {
        float(shape.y0)
        for shape in fig.layout.shapes
        if shape.type == "line" and float(shape.y0) == float(shape.y1)
    }
    assert vertical_boundaries == {-0.5, 0.5, 1.5}
    assert horizontal_boundaries == {-0.5, 0.5, 1.5}
    assert all(shape.line.color == module.HEATMAP_GRID_COLOR for shape in fig.layout.shapes)
    assert heatmap.colorbar.len == pytest.approx(0.72)
    assert heatmap.colorbar.thickness == 14
    assert fig.layout.title.text is None
    assert heatmap.texttemplate is None
    assert heatmap.customdata[0][0] == ["5", "1"]
    assert heatmap.customdata[1][1] == ["900", "1001"]


def test_view_inference_analysis_can_hide_redundant_heatmap_colorbars() -> None:
    module = _load_module()

    matrix = pd.DataFrame(
        [[10.0, None], [20.0, 30.0]],
        index=pd.Index([5, 900]),
        columns=pd.Index([1, 1001]),
    )

    fig = module._build_heatmap_figure(matrix, colorbar_title="Value", show_colorbar=False)
    heatmap = fig.data[0]

    assert heatmap.showscale is False


def test_view_inference_analysis_builds_detached_heatmap_colorbar_figure() -> None:
    module = _load_module()

    fig = module._build_heatmap_colorbar_figure(colorbar_title="Value", zmax=100.0, height=420)
    scatter = fig.data[0]

    assert scatter.marker.showscale is True
    assert scatter.marker.colorbar.title.text == "Value"
    assert scatter.marker.colorbar.len == pytest.approx(0.66)
    assert scatter.marker.colorbar.x == pytest.approx(0.58)
    assert scatter.marker.colorbar.xanchor == "right"
    assert scatter.marker.colorbar.thickness == 10
    assert scatter.marker.colorbar.tickfont.size == 11
    assert fig.layout.height == 420
    assert fig.layout.margin.r == 28
    assert fig.layout.xaxis.visible is False
    assert fig.layout.yaxis.visible is False


def test_view_inference_analysis_can_build_detached_heatmap_colorbar_without_internal_title() -> None:
    module = _load_module()

    fig = module._build_heatmap_colorbar_figure(colorbar_title="", zmax=100.0, height=420)
    scatter = fig.data[0]

    assert scatter.marker.showscale is True
    assert scatter.marker.colorbar.title.text is None


def test_view_inference_analysis_formats_wrapped_heatmap_scale_labels() -> None:
    module = _load_module()

    assert module._format_heatmap_scale_label("Served bandwidth (%)") == "**Served bandwidth**  \n(%)"
    assert module._format_heatmap_scale_label("Rejected ratio (%)") == "**Rejected ratio**  \n(%)"
    assert module._format_heatmap_scale_label("Value") == "**Value**"
    assert module._format_heatmap_scale_label("   ") == ""


def test_view_inference_analysis_chunks_heatmap_labels_for_wrapped_matrix_grid() -> None:
    module = _load_module()

    rows = module._chunk_labels(["run_a", "run_b", "run_c"], max_columns=2)

    assert rows == [["run_a", "run_b"], ["run_c"]]


def test_view_inference_analysis_keeps_heatmap_grid_column_count_fixed_for_odd_rows() -> None:
    module = _load_module()

    assert module._resolve_heatmap_section_column_count(1) == 1
    assert module._resolve_heatmap_section_column_count(2) == 2
    assert module._resolve_heatmap_section_column_count(3) == 2


def test_view_inference_analysis_chunks_bearer_plots_with_three_max_per_row() -> None:
    module = _load_module()

    rows = module._chunk_labels(["run_a", "run_b", "run_c", "run_d"], max_columns=module.BEARER_MAX_COLUMNS)

    assert rows == [["run_a", "run_b", "run_c"], ["run_d"]]


def test_view_inference_analysis_collects_bearer_legend_items_across_runs() -> None:
    module = _load_module()

    legend_items = module._collect_bearer_legend_items(
        {
            "run_a": pd.DataFrame({"bearer": ["OPT", "not routed"]}),
            "run_b": pd.DataFrame({"bearer": ["SAT", "IVDL"]}),
            "run_c": pd.DataFrame(),
        }
    )

    assert legend_items == ["SAT", "OPT", "IVDL", "not routed"]


def test_view_inference_analysis_resolves_stable_colors_for_unknown_bearers() -> None:
    module = _load_module()

    color_map = module._resolve_bearer_color_map(["SAT", "OPT", "mesh", "lte"])

    assert color_map["SAT"] == module.BEARER_COLOR_MAP["SAT"]
    assert color_map["OPT"] == module.BEARER_COLOR_MAP["OPT"]
    assert color_map["mesh"] == module.BEARER_EXTRA_COLOR_SEQUENCE[0]
    assert color_map["lte"] == module.BEARER_EXTRA_COLOR_SEQUENCE[1]


def test_view_inference_analysis_adds_missing_bearer_legend_traces() -> None:
    module = _load_module()
    color_map = module._resolve_bearer_color_map(["SAT", "OPT", "not routed"])

    fig = module.go.Figure(
        data=[
            module.go.Scatter(
                x=[0, 1],
                y=[10, 20],
                mode="lines",
                name="SAT",
                showlegend=True,
            )
        ]
    )

    module._add_missing_bearer_legend_traces(fig, ["SAT", "OPT", "not routed"], color_map)

    names = [trace.name for trace in fig.data]
    assert names == ["SAT", "OPT", "not routed"]
    assert fig.data[1].line.color == module.BEARER_COLOR_MAP["OPT"]
    assert fig.data[2].line.color == module.BEARER_COLOR_MAP["not routed"]


def test_view_inference_analysis_builds_shared_bearer_legend_html() -> None:
    module = _load_module()
    color_map = module._resolve_bearer_color_map(["SAT", "mesh"])

    legend_html = module._build_bearer_legend_html(["SAT", "mesh"], color_map)

    assert "SAT" in legend_html
    assert "mesh" in legend_html
    assert module.BEARER_COLOR_MAP["SAT"] in legend_html
    assert module.BEARER_EXTRA_COLOR_SEQUENCE[0] in legend_html
    assert "display:flex" in legend_html


def test_view_inference_analysis_builds_bearer_figure_with_embedded_title() -> None:
    module = _load_module()
    color_map = module._resolve_bearer_color_map(["SAT", "OPT"])
    plot_df = pd.DataFrame(
        {
            "time_index": [0, 0, 1, 1],
            "bearer": ["SAT", "OPT", "SAT", "OPT"],
            "share_pct": [60.0, 40.0, 55.0, 45.0],
        }
    )

    fig = module._build_bearer_involvement_figure(
        plot_df,
        axis_name="time_index",
        run_label="ppo_run",
        bearer_color_map=color_map,
        bearer_legend_items=["SAT", "OPT"],
    )

    assert fig.layout.title.text == "ppo_run"
    assert fig.layout.title.x == pytest.approx(0.5)
    assert fig.layout.xaxis.title.text == "time_index"
    assert fig.layout.yaxis.title.text == "Bearer involvement (%)"
    assert fig.layout.showlegend is False
    assert fig.layout.margin.t == 52


def test_view_inference_analysis_latency_distribution_uses_only_routed_rows() -> None:
    module = _load_module()

    frames = {
        "ilp": pd.DataFrame(
            {
                "latency": [5.0, 7.5, 99.0],
                "routed": [1, 1, 0],
            }
        ),
        "ppo": pd.DataFrame(
            {
                "latency": [8.0, 10.0],
                "delivered_bandwidth": [1.0, 0.0],
            }
        ),
    }

    distribution_df = module.build_latency_distribution_frame(frames)

    assert distribution_df.sort_values(["run_label", "latency"]).reset_index(drop=True).to_dict("records") == [
        {"latency": 5.0, "run_label": "ilp"},
        {"latency": 7.5, "run_label": "ilp"},
        {"latency": 8.0, "run_label": "ppo"},
    ]


def test_view_inference_analysis_builds_routed_hop_count_distribution() -> None:
    module = _load_module()

    frames = {
        "ilp": pd.DataFrame(
            {
                "path": ["[1, 3, 2]", "[1, 4, 5, 2]", None],
                "delivered_bandwidth": [1.0, 1.0, 0.0],
            }
        ),
        "ppo": pd.DataFrame(
            {
                "path": [[1, 2], [1, 4, 2], [1, 7, 8, 2], []],
                "routed": [1, 1, 0, 1],
            }
        ),
    }

    hop_count_df = module.build_hop_count_distribution_frame(frames)

    records = hop_count_df.sort_values(["run_label", "hop_count"]).reset_index(drop=True).to_dict("records")
    assert records == [
        {"hop_count": 2, "count": 1, "run_label": "ilp", "share_pct": pytest.approx(50.0)},
        {"hop_count": 3, "count": 1, "run_label": "ilp", "share_pct": pytest.approx(50.0)},
        {"hop_count": 1, "count": 1, "run_label": "ppo", "share_pct": pytest.approx(50.0)},
        {"hop_count": 2, "count": 1, "run_label": "ppo", "share_pct": pytest.approx(50.0)},
    ]


def test_view_inference_analysis_handles_nested_path_values_for_hop_count() -> None:
    module = _load_module()

    frames = {
        "edge_mlp": pd.DataFrame(
            {
                "path": [[[1, 4, 2]], [[1, 5, 6, 2]], [None], "[[1, 9, 2]]"],
                "routed": [1, 1, 1, 1],
            }
        )
    }

    hop_count_df = module.build_hop_count_distribution_frame(frames)

    records = hop_count_df.sort_values(["run_label", "hop_count"]).reset_index(drop=True).to_dict("records")
    assert records == [
        {"hop_count": 2, "count": 2, "run_label": "edge_mlp", "share_pct": pytest.approx(66.66666666666666)},
        {"hop_count": 3, "count": 1, "run_label": "edge_mlp", "share_pct": pytest.approx(33.33333333333333)},
    ]


def test_view_inference_analysis_builds_bearer_mix_for_deduped_routed_and_unrouted_rows() -> None:
    module = _load_module()

    frame = pd.DataFrame(
        {
            "time_index": [0, 0, 1, 2, None],
            "bearers": ['["SAT", "SAT", "OPT"]', "[]", None, None, '["IVDL"]'],
            "routed": [1, 1, 1, 0, 1],
        }
    )

    mix_df = module.build_bearer_mix_frame(frame, "time_index")

    assert mix_df.to_dict("records") == [
        {"time_index": 0.0, "bearer": "OPT", "count": 1},
        {"time_index": 0.0, "bearer": "SAT", "count": 1},
        {"time_index": 0.0, "bearer": "routed/no bearer", "count": 1},
        {"time_index": 1.0, "bearer": "routed/no bearer", "count": 1},
        {"time_index": 2.0, "bearer": "not routed", "count": 1},
    ]
    assert module.build_bearer_mix_frame(frame, "missing_axis").empty
    assert module.build_bearer_mix_frame(pd.DataFrame({"time_index": [None], "bearers": ['["SAT"]']}), "time_index").empty


def test_view_inference_analysis_builds_flow_heatmaps_for_served_and_rejected_values() -> None:
    module = _load_module()

    frame = pd.DataFrame(
        {
            "source": [1, 1, 2, "bad"],
            "destination": [10, 10, 20, 30],
            "bandwidth": [10.0, 5.0, 8.0, 4.0],
            "delivered_bandwidth": [7.0, 0.0, 8.0, 4.0],
            "routed": [1, 0, 1, 1],
        }
    )

    served = module.build_flow_heatmap_frame(frame, value_kind="served_bandwidth_pct")
    rejected = module.build_flow_heatmap_frame(frame, value_kind="rejected_ratio_pct")

    assert served.index.tolist() == [10.0, 20.0]
    assert served.columns.tolist() == [1.0, 2.0]
    assert served.loc[10.0, 1.0] == pytest.approx((7.0 / 15.0) * 100.0)
    assert served.loc[20.0, 2.0] == pytest.approx(100.0)
    assert rejected.loc[10.0, 1.0] == pytest.approx(50.0)
    assert rejected.loc[20.0, 2.0] == pytest.approx(0.0)
    assert module.build_flow_heatmap_frame(pd.DataFrame({"latency": [1.0]}), value_kind="served_bandwidth_pct").empty
    assert module.build_flow_heatmap_frame(
        pd.DataFrame({"source": ["bad"], "destination": [None]}),
        value_kind="served_bandwidth_pct",
    ).empty

    with pytest.raises(ValueError, match="Unsupported heatmap value kind"):
        module.build_flow_heatmap_frame(frame, value_kind="mystery")


def test_view_inference_analysis_heatmap_helpers_cover_annotation_and_layout_edges() -> None:
    module = _load_module()
    matrix = pd.DataFrame(
        [[10.0, 20.0], [30.0, None]],
        index=pd.Index([5, 6]),
        columns=pd.Index([1, 2]),
    )

    fig = module._build_heatmap_figure(
        matrix,
        title="Run A",
        colorbar_title="Served bandwidth (%)",
        show_annotations=True,
    )
    heatmap = fig.data[0]

    assert heatmap.texttemplate == "%{text}"
    assert heatmap.colorbar.title.text == "Served bandwidth (%)"
    assert fig.layout.title.text == "Run A"
    assert fig.layout.height == 400
    assert module._resolve_heatmap_height(20) == 900
    assert module._build_heatmap_grid_shapes(0, 2) == []
    assert len(module._build_heatmap_grid_shapes(2, 3)) == 7

    with pytest.raises(ValueError, match="max_columns must be at least 1"):
        module._chunk_labels(["run_a"], max_columns=0)


def test_view_inference_analysis_formats_heatmap_text_frame_via_applymap_fallback() -> None:
    module = _load_module()

    class _LegacyMatrix:
        def applymap(self, formatter):
            return pd.DataFrame([[formatter(1.25), formatter(float("nan"))]])

    text = module._format_heatmap_text_frame(_LegacyMatrix())

    assert text.to_dict() == {0: {0: "1.2"}, 1: {0: ""}}


def test_view_inference_analysis_collects_empty_bearer_legend_and_builds_empty_html() -> None:
    module = _load_module()

    assert module._collect_bearer_legend_items({"run_a": pd.DataFrame(), "run_b": pd.DataFrame({"value": [1]})}) == []
    assert module._build_bearer_legend_html([], {}) == ""


def test_view_inference_analysis_render_heatmap_handles_empty_and_non_empty_matrices(monkeypatch) -> None:
    module = _load_module()
    fake_st = _FakeStreamlit()
    monkeypatch.setattr(module, "st", fake_st)

    module._render_heatmap(pd.DataFrame(), colorbar_title="Value")
    matrix = pd.DataFrame([[10.0]], index=pd.Index([5]), columns=pd.Index([1]))
    module._render_heatmap(matrix, title="Run A", colorbar_title="Value", chart_key="heatmap:run_a")

    assert fake_st.infos == ["No data available for this heatmap."]
    assert [call["key"] for call in fake_st.plot_calls] == ["heatmap:run_a"]
    assert fake_st.plot_calls[0]["width"] == "stretch"


def test_view_inference_analysis_render_heatmap_section_renders_charts_and_shared_scale(monkeypatch) -> None:
    module = _load_module()
    fake_st = _FakeStreamlit()
    monkeypatch.setattr(module, "st", fake_st)

    matrices = {
        "run_a": pd.DataFrame([[10.0]], index=pd.Index([5]), columns=pd.Index([1])),
        "run_b": pd.DataFrame(),
    }

    module._render_heatmap_section(
        "Served bandwidth matrix",
        matrices,
        colorbar_title="Served bandwidth (%)",
        zmax=100.0,
        chart_key_prefix="detail:served",
        show_annotations=True,
    )

    assert fake_st.writes == ["Served bandwidth matrix"]
    assert fake_st.infos == ["No data available for run_b."]
    assert [call["key"] for call in fake_st.plot_calls] == [
        "detail:served:run_a",
        "detail:served:scale:0",
    ]


def test_view_inference_analysis_align_heatmaps_keeps_explicit_empty_matrix_unchanged() -> None:
    module = _load_module()

    aligned, rows, columns = module.align_heatmap_frames(
        {
            "run_a": pd.DataFrame(),
            "run_b": pd.DataFrame([[10.0]], index=pd.Index([5]), columns=pd.Index([1])),
        }
    )

    assert aligned["run_a"].empty
    assert rows.tolist() == [5]
    assert columns.tolist() == [1]


def test_view_inference_analysis_main_stops_when_dataset_root_is_missing(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    fake_st = _FakeStreamlit()
    active_app = tmp_path / "demo_project"
    active_app.mkdir()

    class _FakeEnv:
        def __init__(self, **_kwargs):
            self.active_app = active_app
            self.target = ""
            self.AGILAB_EXPORT_ABS = str(tmp_path / "export")
            self.app_settings_file = str(tmp_path / "missing.toml")
            self.init_done = False

        def share_root_path(self) -> str:
            return str(tmp_path / "share")

    monkeypatch.setattr(module, "st", fake_st)
    monkeypatch.setattr(module, "_resolve_active_app", lambda: active_app)
    monkeypatch.setattr(module, "AgiEnv", _FakeEnv)
    monkeypatch.setattr(module, "render_logo", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "_resolve_base_path", lambda *_args, **_kwargs: tmp_path / "base")
    monkeypatch.setattr(module, "_resolve_dataset_root", lambda *_args, **_kwargs: tmp_path / "missing-root")

    with pytest.raises(_FakeStop):
        module.main()

    assert fake_st.titles == [module.PAGE_TITLE]
    assert fake_st.headers[0] == "Data source"
    assert fake_st.infos == [f"Resolved dataset root: `{tmp_path / 'missing-root'}`"]
    assert fake_st.warnings == [f"Dataset root does not exist yet: {tmp_path / 'missing-root'}"]
    assert module.ENV_KEY in fake_st.session_state


def test_view_inference_analysis_main_handles_no_selection_before_loading_frames(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    fake_st = _FakeStreamlit()
    active_app = tmp_path / "demo_project"
    active_app.mkdir()
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    allocations = dataset_root / "allocations_steps.json"
    allocations.write_text("[]", encoding="utf-8")

    class _FakeEnv:
        def __init__(self, **_kwargs):
            self.active_app = active_app
            self.target = ""
            self.AGILAB_EXPORT_ABS = str(tmp_path / "export")
            self.app_settings_file = str(tmp_path / "missing.toml")
            self.init_done = False

        def share_root_path(self) -> str:
            return str(tmp_path / "share")

    monkeypatch.setattr(module, "st", fake_st)
    monkeypatch.setattr(module, "_resolve_active_app", lambda: active_app)
    monkeypatch.setattr(module, "AgiEnv", _FakeEnv)
    monkeypatch.setattr(module, "render_logo", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "_resolve_base_path", lambda *_args, **_kwargs: tmp_path / "base")
    monkeypatch.setattr(module, "_resolve_dataset_root", lambda *_args, **_kwargs: dataset_root)
    monkeypatch.setattr(module, "_discover_allocation_files", lambda *_args, **_kwargs: [allocations])
    monkeypatch.setattr(module, "_coerce_selection", lambda saved, options, **_kwargs: [] if saved is not None else [])

    module.main()

    assert fake_st.infos[-1] == "No allocation file selected. Use the sidebar to choose one or more files."
    assert len(fake_st.dataframes) == 1
    inventory = fake_st.dataframes[0]["data"]
    assert inventory["run_label"].tolist() == ["allocations_steps.json"]


def test_view_inference_analysis_main_stops_when_selected_files_have_no_numeric_metrics(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    fake_st = _FakeStreamlit()
    active_app = tmp_path / "demo_project"
    active_app.mkdir()
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    allocations = dataset_root / "allocations_steps.json"
    allocations.write_text("[]", encoding="utf-8")

    class _FakeEnv:
        def __init__(self, **_kwargs):
            self.active_app = active_app
            self.target = ""
            self.AGILAB_EXPORT_ABS = str(tmp_path / "export")
            self.app_settings_file = str(tmp_path / "missing.toml")
            self.init_done = False

        def share_root_path(self) -> str:
            return str(tmp_path / "share")

    monkeypatch.setattr(module, "st", fake_st)
    monkeypatch.setattr(module, "_resolve_active_app", lambda: active_app)
    monkeypatch.setattr(module, "AgiEnv", _FakeEnv)
    monkeypatch.setattr(module, "render_logo", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "_resolve_base_path", lambda *_args, **_kwargs: tmp_path / "base")
    monkeypatch.setattr(module, "_resolve_dataset_root", lambda *_args, **_kwargs: dataset_root)
    monkeypatch.setattr(module, "_discover_allocation_files", lambda *_args, **_kwargs: [allocations])
    monkeypatch.setattr(
        module,
        "_coerce_selection",
        lambda saved, options, **_kwargs: [options[0]] if options else [],
    )
    monkeypatch.setattr(module, "_load_allocations_cached", lambda *_args, **_kwargs: pd.DataFrame({"seed": ["a"]}))
    monkeypatch.setattr(module, "discover_metric_columns", lambda _frames: [])

    with pytest.raises(_FakeStop):
        module.main()

    assert fake_st.warnings[-1] == "The selected files loaded successfully, but no numeric metric column was found."
    assert len(fake_st.dataframes) == 1


def test_view_inference_analysis_main_renders_time_series_requested_reference(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    fake_st = _FakeStreamlit()
    active_app = tmp_path / "demo_project"
    active_app.mkdir()
    dataset_root = tmp_path / "dataset"
    run_a_path = dataset_root / "run_a" / "allocations_steps.json"
    run_b_path = dataset_root / "run_b" / "allocations_steps.json"
    run_a_path.parent.mkdir(parents=True)
    run_b_path.parent.mkdir(parents=True)
    run_a_path.write_text("[]", encoding="utf-8")
    run_b_path.write_text("[]", encoding="utf-8")

    frames_by_path = {
        run_a_path: pd.DataFrame(
            {
                "time_index": [0, 1],
                "bandwidth": [10.0, 20.0],
                "delivered_bandwidth": [8.0, 18.0],
                "latency": [10.0, 20.0],
                "routed": [1, 1],
            }
        ),
        run_b_path: pd.DataFrame(
            {
                "time_index": [0, 1],
                "bandwidth": [5.0, 5.0],
                "delivered_bandwidth": [4.0, 4.5],
                "latency": [30.0, 40.0],
                "routed": [1, 1],
            }
        ),
    }

    class _FakeEnv:
        def __init__(self, **_kwargs):
            self.active_app = active_app
            self.target = ""
            self.AGILAB_EXPORT_ABS = str(tmp_path / "export")
            self.app_settings_file = str(tmp_path / "missing.toml")
            self.init_done = False

        def share_root_path(self) -> str:
            return str(tmp_path / "share")

    monkeypatch.setattr(module, "st", fake_st)
    monkeypatch.setattr(module, "_resolve_active_app", lambda: active_app)
    monkeypatch.setattr(module, "AgiEnv", _FakeEnv)
    monkeypatch.setattr(module, "render_logo", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "_resolve_base_path", lambda *_args, **_kwargs: tmp_path / "base")
    monkeypatch.setattr(module, "_resolve_dataset_root", lambda *_args, **_kwargs: dataset_root)
    monkeypatch.setattr(module, "_discover_allocation_files", lambda *_args, **_kwargs: [run_a_path, run_b_path])
    monkeypatch.setattr(
        module,
        "_load_allocations_cached",
        lambda path, *_args, **_kwargs: frames_by_path[Path(path)],
    )

    module.main()

    assert "Time-series diagnostics" in fake_st.headers
    time_series_fig = fake_st.plot_calls[0]["fig"]
    trace_names = [trace.name for trace in time_series_fig.data]
    requested_traces = [trace for trace in time_series_fig.data if str(trace.name).endswith(" requested")]

    assert trace_names[:2] == ["run_a requested", "run_a"]
    assert {trace.name for trace in requested_traces} == {"run_a requested", "run_b requested"}
    assert all(trace.line.dash == "dash" for trace in requested_traces)
    assert all(trace.line.width == 1 for trace in requested_traces)
    assert any(
        caption == "In the delivered bandwidth panel, thin dashed traces show requested bandwidth."
        for caption in fake_st.captions
    )
