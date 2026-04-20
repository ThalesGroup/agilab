from __future__ import annotations

import importlib.util
from pathlib import Path

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


def test_view_inference_analysis_adds_missing_bearer_legend_traces() -> None:
    module = _load_module()

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

    module._add_missing_bearer_legend_traces(fig, ["SAT", "OPT", "not routed"])

    names = [trace.name for trace in fig.data]
    assert names == ["SAT", "OPT", "not routed"]


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
