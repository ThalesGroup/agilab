from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
from agi_node.pandas_worker import PandasWorker


APP_ROOT = Path("src/agilab/apps/builtin/mission_decision_project").resolve()
SRC_ROOT = APP_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from data_io_2026 import DataIo2026, DataIo2026Args, build_decision_artifacts
from data_io_2026.fred_support import (
    FRED_FIXTURE_SERIES_ID,
    fetch_fred_csv_rows,
    fred_csv_url,
    fred_fixture_rows,
    parse_fred_csv,
)
from data_io_2026_worker import DataIo2026Worker
from data_io_2026_worker.data_io_2026_worker import _args_with_defaults


def _make_env(tmp_path: Path) -> SimpleNamespace:
    share_root = tmp_path / "share"
    share_root.mkdir(parents=True, exist_ok=True)
    export_root = tmp_path / "export"
    export_root.mkdir(parents=True, exist_ok=True)

    def _resolve_share_path(path):
        candidate = Path(path)
        return candidate if candidate.is_absolute() else share_root / candidate

    return SimpleNamespace(
        verbose=0,
        resolve_share_path=_resolve_share_path,
        home_abs=tmp_path,
        _is_managed_pc=False,
        AGI_LOCAL_SHARE=str(share_root),
        AGILAB_EXPORT_ABS=export_root,
        target="data_io_2026",
    )


def test_data_io_2026_manager_seeds_public_scenario_and_distribution(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    manager = DataIo2026(env, args=DataIo2026Args())

    files = sorted(manager.args.data_in.glob("*.json"))
    assert len(files) == 1
    assert files[0].name == "mission_decision_demo.json"
    assert manager.analysis_artifact_dir == env.AGILAB_EXPORT_ABS / "data_io_2026" / "data_io_decision"

    work_plan, metadata, partition_key, weights_key, unit = manager.build_distribution({"127.0.0.1": 1})

    assert len(work_plan) == 1
    assert len(work_plan[0][0]) == 1
    assert metadata[0][0]["scenario"] == "mission_decision_demo.json"
    assert partition_key == "scenario"
    assert weights_key == "size_kb"
    assert unit == "KB"


def test_data_io_2026_decision_artifacts_replan_after_bandwidth_drop() -> None:
    scenario_path = SRC_ROOT / "data_io_2026" / "sample_data" / "mission_decision_demo.json"
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))

    artifacts = build_decision_artifacts(scenario, DataIo2026Args())
    summary = artifacts["summary"]
    feature_rows = artifacts["feature_table"]

    assert summary["initial_strategy"] == "direct_satcom"
    assert summary["selected_strategy"] == "relay_mesh"
    assert summary["latency_delta_pct_vs_no_replan"] < 0
    assert summary["cost_delta_pct_vs_no_replan"] < 0
    assert summary["reliability_delta_pct_vs_no_replan"] > 0
    assert summary["pipeline_stage_count"] == len(artifacts["generated_pipeline"]["stages"])
    assert {row["phase"] for row in artifacts["candidate_routes"]} == {"baseline", "post_failure"}
    assert len(artifacts["decision_timeline"]) == 6
    assert {
        ("public_macro_fixture_series", "fred_fixture"),
        ("public_macro_fixture_value", "fred_fixture"),
        ("public_macro_fixture_date", "fred_fixture"),
    } <= {(row["feature"], row["source"]) for row in feature_rows}


def test_data_io_2026_fred_fixture_and_parser_are_deterministic() -> None:
    rows = fred_fixture_rows()

    assert [row["date"] for row in rows] == ["2026-01-01", "2026-02-01", "2026-03-01"]
    assert {row["series_id"] for row in rows} == {FRED_FIXTURE_SERIES_ID}
    assert rows[-1]["value"] == 3.9
    assert rows[-1]["source"] == "fred_fixture"

    parsed = parse_fred_csv(
        "DATE,UNRATE\n2026-01-01,4.1\n2026-02-01,.\n2026-03-01,not-a-number\n",
        series_id="UNRATE",
    )
    assert parsed == [
        {
            "date": "2026-01-01",
            "series_id": "UNRATE",
            "value": 4.1,
            "source": "fred",
        }
    ]


def test_data_io_2026_fred_live_fetch_is_optional_and_injectable() -> None:
    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        @staticmethod
        def read() -> bytes:
            return b"DATE,FEDFUNDS\n2026-04-01,3.8\n"

    calls: list[tuple[str, float]] = []

    def _opener(url: str, *, timeout: float):
        calls.append((url, timeout))
        return _Response()

    rows = fetch_fred_csv_rows(opener=_opener, timeout=1.5)

    assert rows == [
        {
            "date": "2026-04-01",
            "series_id": "FEDFUNDS",
            "value": 3.8,
            "source": "fred",
        }
    ]
    assert calls == [(fred_csv_url("FEDFUNDS"), 1.5)]


def test_mission_decision_worker_exports_analysis_artifacts(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    manager = DataIo2026(env, args=DataIo2026Args(reset_target=True))
    source = sorted(manager.args.data_in.glob("*.json"))[0]

    worker = DataIo2026Worker()
    worker.env = env
    worker.args = manager.args.model_dump(mode="json")
    worker._worker_id = 0
    worker.worker_id = 0
    worker.verbose = 0
    worker.start()

    result = worker.work_pool(str(source))
    worker.work_done(result)

    for root in (
        Path(worker.data_out) / "mission_decision_demo",
        env.AGILAB_EXPORT_ABS / env.target / "data_io_decision" / "mission_decision_demo",
    ):
        summary_path = root / "mission_decision_demo_summary_metrics.json"
        assert summary_path.is_file()
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        assert summary["selected_strategy"] == "relay_mesh"
        assert summary["initial_strategy"] == "direct_satcom"
        assert summary["worker_id"] == 0

        pipeline_path = root / "mission_decision_demo_generated_pipeline.json"
        decision_path = root / "mission_decision_demo_mission_decision.json"
        reduce_path = root / "reduce_summary_worker_0.json"
        assert pipeline_path.is_file()
        assert decision_path.is_file()
        assert reduce_path.is_file()

        reduce_artifact = json.loads(reduce_path.read_text(encoding="utf-8"))
        assert reduce_artifact["name"] == "mission_decision_reduce_summary"
        assert reduce_artifact["reducer"] == "mission_decision.mission-decision.v1"
        assert reduce_artifact["payload"]["selected_strategies"] == ["relay_mesh"]

        routes_df = pd.read_csv(root / "mission_decision_demo_candidate_routes.csv")
        timeline_df = pd.read_csv(root / "mission_decision_demo_decision_timeline.csv")
        sensor_df = pd.read_csv(root / "mission_decision_demo_sensor_stream.csv")
        feature_df = pd.read_csv(root / "mission_decision_demo_feature_table.csv")

        assert {"phase", "route_id", "latency_ms", "score"} <= set(routes_df.columns)
        assert {"step", "phase", "decision", "selected_strategy"} <= set(timeline_df.columns)
        assert {"source_id", "kind", "quality", "event"} <= set(sensor_df.columns)
        assert {"feature", "value", "unit", "source"} <= set(feature_df.columns)


def test_mission_decision_worker_args_fill_missing_defaults() -> None:
    args = _args_with_defaults({"data_in": "custom/in"})

    assert args.data_in == "custom/in"
    assert args.data_out == "mission_decision/results"
    assert args.files == "*.json"
    assert args.failure_kind == "bandwidth_drop"


def test_data_io_2026_public_analysis_config_and_wording() -> None:
    settings = tomllib.loads((SRC_ROOT / "app_settings.toml").read_text(encoding="utf-8"))

    assert settings["pages"]["default_view"] == "view_data_io_decision"
    assert settings["pages"]["view_module"] == ["view_data_io_decision"]

    public_files = [
        APP_ROOT / "README.md",
        APP_ROOT / "lab_stages.toml",
        APP_ROOT / "pipeline_view.dot",
        SRC_ROOT / "pre_prompt.json",
        Path("src/agilab/apps-pages/view_data_io_decision/README.md"),
    ]
    public_text = "\n".join(path.read_text(encoding="utf-8") for path in public_files).lower()
    assert "fred" in public_text
    assert "fredapi" in public_text
    assert "obsolete" not in public_text
    assert "private project" not in public_text

    dependencies = " ".join(
        tomllib.loads((APP_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
    ).lower()
    assert "fredapi" not in dependencies


def test_mission_decision_worker_is_installable_supported_worker() -> None:
    assert issubclass(DataIo2026Worker, PandasWorker)
