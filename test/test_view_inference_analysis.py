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
