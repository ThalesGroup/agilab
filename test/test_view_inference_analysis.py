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
