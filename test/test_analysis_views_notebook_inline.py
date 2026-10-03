from __future__ import annotations

import builtins
import hashlib
import importlib.util
import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from IPython.display import Markdown

from agilab.notebooks.notebook_export_support import build_notebook_export_context
from agilab.notebooks.notebook_helper_cell import _helper_cell

PAGES_ROOT = Path("src/agilab/apps-pages").resolve()
PAGES = (
    "view_maps",
    "view_forecast_analysis",
    "view_scenario_cockpit",
    "view_release_decision",
    "view_data_io_decision",
    "view_queue_resilience",
    "view_relay_resilience",
)


def _module(page: str):
    path = PAGES_ROOT / page / "src" / page / "notebook_inline.py"
    assert path.is_file(), f"{page} still needs an inline notebook renderer"
    spec = importlib.util.spec_from_file_location(f"notebook_test_{page}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _seed(page: str, root: Path) -> None:
    root.mkdir()
    if page == "view_maps":
        pd.DataFrame(
            [
                {"plane_id": "001", "latitude": 48.0, "longitude": 2.0},
                {"plane_id": "002", "latitude": 49.0, "longitude": 3.0},
            ]
        ).to_csv(root / "trajectory.csv", index=False)
    elif page == "view_forecast_analysis":
        _json(root / "run_a" / "forecast_metrics.json", {"run_id": "001", "mae": 1.0})
        pd.DataFrame(
            {
                "ds": ["2026-10-01", "2026-10-02"],
                "y_true": [10, 12],
                "y_pred": [11, 13],
                "run_id": ["001", "001"],
            }
        ).to_csv(root / "run_a" / "forecast_predictions.csv", index=False)
    elif page == "view_release_decision":
        _json(root / "forecast_metrics.json", {"mae": 1.0, "rmse": 1.4})
        _json(
            root / "run_manifest.json",
            {"schema": "agilab.run_manifest.v1", "status": "failed"},
        )
    elif page == "view_data_io_decision":
        _json(
            root / "run_summary_metrics.json",
            {"selected_strategy": "replan", "latency_ms_selected": 12},
        )
        _json(root / "run_generated_pipeline.json", {"stages": [{"name": "route"}]})
        _json(
            root / "run_mission_decision.json",
            {"applied_events": [{"event": "link_failure"}]},
        )
        pd.DataFrame({"strategy": ["replan"], "score": [0.9]}).to_csv(
            root / "run_candidate_routes.csv", index=False
        )
        pd.DataFrame({"time_s": [0, 1], "decision": ["initial", "replan"]}).to_csv(
            root / "run_decision_timeline.csv", index=False
        )
    else:
        for name, pdr in (("a", 0.8), ("b", 0.9)):
            _json(
                root / f"{name}_summary_metrics.json",
                {
                    "scenario": name,
                    "pdr": pdr,
                    "mean_e2e_delay_ms": 20,
                    "mean_queue_wait_ms": 5,
                    "max_queue_depth_pkts": 3,
                },
            )
            pd.DataFrame(
                {"time_s": [0, 1], "relay": ["r1", "r1"], "queue_depth_pkts": [1, 3]}
            ).to_csv(root / f"{name}_queue_timeseries.csv", index=False)
            pd.DataFrame({"status": ["delivered"], "delay_ms": [20]}).to_csv(
                root / f"{name}_packet_events.csv", index=False
            )
            pd.DataFrame(
                {"time_s": [0], "node": ["r1"], "role": ["relay"], "x": [1], "y": [2]}
            ).to_csv(root / f"{name}_node_positions.csv", index=False)
            pd.DataFrame({"relay": ["r1"], "delivered": [1]}).to_csv(
                root / f"{name}_routing_summary.csv", index=False
            )


@pytest.mark.parametrize("page", PAGES)
def test_export_discovers_and_renders_common_views_without_streamlit(
    page, tmp_path, monkeypatch
):
    artifact_dir = tmp_path / "export"
    _seed(page, artifact_dir)
    settings = tmp_path / "app_settings.toml"
    settings.write_text(f'[pages]\nview_module = ["{page}"]\n', encoding="utf-8")
    env = SimpleNamespace(
        app_settings_file=settings, AGILAB_PAGES_ABS=PAGES_ROOT, active_app=""
    )
    context = build_notebook_export_context(
        env, "demo", artifact_dir / "lab_stages.toml"
    )
    assert len(context.related_pages) == 1
    record = context.related_pages[0]
    renderer_path = PAGES_ROOT / page / "src" / page / "notebook_inline.py"
    assert record.inline_renderer == f"{renderer_path}:render_inline"
    assert (
        record.inline_renderer_sha256
        == hashlib.sha256(renderer_path.read_bytes()).hexdigest()
    )

    namespace = {}
    exec(
        _helper_cell(
            {
                "schema": "agilab.notebook_export.v1",
                "version": 1,
                "project_name": "demo",
                "module_path": "demo",
                "artifact_dir": str(artifact_dir),
                "stages": [],
                "pages_root": str(PAGES_ROOT),
                "related_pages": [asdict(record)],
            }
        ),
        namespace,
    )
    displayed = []
    monkeypatch.setattr("IPython.display.display", displayed.append)

    def forbidden(*args, **kwargs):
        raise AssertionError("Rendering a notebook view must not launch Streamlit")

    namespace["launch_analysis_page"] = forbidden
    original_import = builtins.__import__

    def import_without_streamlit(name, *args, **kwargs):
        if name == "streamlit" or name.startswith("streamlit."):
            raise AssertionError("Notebook rendering imported Streamlit")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_streamlit)
    result = namespace["render_analysis_page"](page)
    assert result
    assert displayed
    assert any(isinstance(item, pd.DataFrame) for item in result)


@pytest.mark.parametrize("page", PAGES)
def test_missing_and_invalid_artifacts_stay_inside_the_notebook(page, tmp_path):
    module = _module(page)
    for payload in (
        {},
        {"artifact_dir": str(tmp_path / "absent")},
        {"artifact_dir": str(tmp_path)},
    ):
        outputs = module.render_inline(
            page=page, record={"label": "Analysis"}, export_payload=payload
        )
        assert outputs
        assert any(
            "No " in item.data or "Missing " in item.data
            for item in outputs
            if hasattr(item, "data")
        )
    for name in (
        "forecast_metrics.json",
        "bad_summary_metrics.json",
        "run_manifest.json",
    ):
        (tmp_path / name).write_text("[invalid", encoding="utf-8")
    (tmp_path / "bad.csv").write_text("latitude,longitude\nbad,bad\n", encoding="utf-8")
    outputs = module.render_inline(
        page=page, record={}, export_payload={"artifact_dir": str(tmp_path)}
    )
    assert outputs
    assert any(
        "Unable " in item.data or "No " in item.data
        for item in outputs
        if hasattr(item, "data")
    )


def test_forecast_keeps_run_pairing_and_validates_predictions(tmp_path):
    module = _module("view_forecast_analysis")
    root = tmp_path / "export"
    _seed("view_forecast_analysis", root)
    _json(root / "run_b" / "forecast_metrics.json", {"run_id": "002", "mae": 99})
    outputs = module.render_inline(
        page="view_forecast_analysis",
        record={},
        export_payload={"artifact_dir": str(root)},
    )
    assert any(
        "Missing " in item.data and "run_b" in item.data
        for item in outputs
        if hasattr(item, "data")
    )
    figures = [item for item in outputs if hasattr(item, "to_plotly_json")]
    assert len(figures) == 1
    assert list(figures[0].data[0].y) == [10, 12]
    assert list(figures[0].data[1].y) == [11, 13]
    predictions = root / "run_a" / "forecast_predictions.csv"
    frame = pd.read_csv(predictions)
    frame["run_id"] = "wrong"
    frame.to_csv(predictions, index=False)
    outputs = module.render_inline(
        page="view_forecast_analysis",
        record={},
        export_payload={"artifact_dir": str(root)},
    )
    assert not any(hasattr(item, "to_plotly_json") for item in outputs)
    assert any("run_id" in item.data for item in outputs if hasattr(item, "data"))


def test_map_coordinates_and_invalid_rows_are_explicit(tmp_path):
    module = _module("view_maps")
    root = tmp_path / "export"
    _seed("view_maps", root)
    frame = pd.read_csv(root / "trajectory.csv")
    frame.loc[2] = ["bad", 100, 200]
    frame.to_csv(root / "trajectory.csv", index=False)
    outputs = module.render_inline(
        page="view_maps", record={}, export_payload={"artifact_dir": str(root)}
    )
    figure = next(item for item in outputs if hasattr(item, "to_plotly_json"))
    assert list(figure.data[0].x) == [2.0, 3.0]
    assert list(figure.data[0].y) == [48.0, 49.0]
    assert any("1 invalid" in item.data for item in outputs if hasattr(item, "data"))


def test_scenario_comparison_reuses_existing_metrics(tmp_path):
    module = _module("view_scenario_cockpit")
    root = tmp_path / "export"
    _seed("view_scenario_cockpit", root)
    outputs = module.render_inline(
        page="view_scenario_cockpit",
        record={},
        export_payload={"artifact_dir": str(root)},
    )
    frame = next(item for item in outputs if isinstance(item, pd.DataFrame))
    assert list(frame["pdr"]) == [0.8, 0.9]
    assert list(frame["scenario"]) == ["a", "b"]
    assert "delta_pdr_vs_baseline" not in frame


def test_release_reports_recorded_failure_without_inventing_readiness(tmp_path):
    module = _module("view_release_decision")
    root = tmp_path / "export"
    _seed("view_release_decision", root)
    outputs = module.render_inline(
        page="view_release_decision",
        record={},
        export_payload={"artifact_dir": str(root)},
    )
    frames = [item for item in outputs if isinstance(item, pd.DataFrame)]
    assert any(
        "status" in frame and "failed" in frame["status"].values for frame in frames
    )
    assert not any("promotable" in getattr(item, "data", "") for item in outputs)


@pytest.mark.parametrize("page", PAGES)
def test_export_helper_displays_bad_artifacts_without_launching_a_server(
    page, tmp_path, monkeypatch
):
    for name in (
        "forecast_metrics.json",
        "bad_summary_metrics.json",
        "run_manifest.json",
    ):
        (tmp_path / name).write_text("[invalid", encoding="utf-8")
    (tmp_path / "bad.csv").write_text("latitude,longitude\nbad,bad\n", encoding="utf-8")
    renderer = PAGES_ROOT / page / "src" / page / "notebook_inline.py"
    namespace = {}
    exec(
        _helper_cell(
            {
                "schema": "agilab.notebook_export.v1",
                "version": 1,
                "project_name": "demo",
                "module_path": "demo",
                "artifact_dir": str(tmp_path),
                "stages": [],
                "related_pages": [
                    {"module": page, "inline_renderer": f"{renderer}:render_inline"}
                ],
            }
        ),
        namespace,
    )
    monkeypatch.setattr("IPython.display.display", lambda *args, **kwargs: None)

    def forbidden(*args, **kwargs):
        raise AssertionError("Bad artifacts must produce notebook diagnostics")

    namespace["launch_analysis_page"] = forbidden
    assert namespace["render_analysis_page"](page)


@pytest.mark.parametrize("page", PAGES)
def test_notebook_rendering_uses_recorded_artifacts_in_a_polluted_environment(
    page, tmp_path, monkeypatch
):
    root = tmp_path / "export"
    _seed(page, root)
    unrelated = tmp_path / "other-app"
    unrelated.mkdir()
    monkeypatch.setenv("HOME", str(unrelated))
    monkeypatch.setenv("AGILAB_EXPORT_ABS", str(unrelated))
    monkeypatch.setenv("AGILAB_ACTIVE_APP", str(unrelated))
    monkeypatch.chdir(unrelated)
    outputs = _module(page).render_inline(
        page=page, record={}, export_payload={"artifact_dir": str(root)}
    )
    assert any(isinstance(item, pd.DataFrame) for item in outputs)


@pytest.mark.parametrize(
    "page",
    [
        name
        for name in PAGES
        if name not in ("view_release_decision", "view_data_io_decision")
    ],
)
def test_missing_plotly_keeps_native_tables(page, tmp_path, monkeypatch):
    root = tmp_path / "export"
    _seed(page, root)
    original_import = builtins.__import__

    def without_plotly(name, *args, **kwargs):
        if name == "plotly" or name.startswith("plotly."):
            raise ModuleNotFoundError("Plotly is not installed")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_plotly)
    outputs = _module(page).render_inline(
        page=page, record={}, export_payload={"artifact_dir": str(root)}
    )
    assert any(isinstance(item, pd.DataFrame) for item in outputs)
    assert any(
        "install Plotly" in item.data for item in outputs if isinstance(item, Markdown)
    )


def test_map_json_export_renders_without_csv_or_parquet(tmp_path):
    root = tmp_path / "export"
    _seed("view_maps", root)
    frame = pd.read_csv(root / "trajectory.csv", dtype={"plane_id": str})
    frame.to_json(root / "export.json", orient="records")
    (root / "trajectory.csv").unlink()
    outputs = _module("view_maps").render_inline(
        page="view_maps", record={}, export_payload={"artifact_dir": str(root)}
    )
    figure = next(item for item in outputs if hasattr(item, "to_plotly_json"))
    assert list(figure.data[0].x) == [2.0, 3.0]
    assert list(figure.data[0].y) == [48.0, 49.0]
