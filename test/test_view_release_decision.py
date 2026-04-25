from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest


PAGE_PATH = (
    "src/agilab/apps-pages/view_release_decision/src/view_release_decision/view_release_decision.py"
)


def _create_forecast_project(tmp_path: Path) -> Path:
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir()
    project_dir = apps_dir / "meteo_forecast_project"
    (project_dir / "src" / "meteo_forecast").mkdir(parents=True)
    (project_dir / "pyproject.toml").write_text("[project]\nname='meteo-forecast-project'\n", encoding="utf-8")
    (project_dir / "src" / "app_settings.toml").write_text("[args]\n", encoding="utf-8")
    (project_dir / "src" / "meteo_forecast" / "__init__.py").write_text("", encoding="utf-8")
    return project_dir


def _write_bundle(root: Path, *, mae: float, rmse: float, mape: float, with_predictions: bool = True) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "forecast_metrics.json").write_text(
        json.dumps(
            {
                "scenario": "French daily weather forecasting pilot",
                "station": "Paris-Montsouris",
                "target": "tmax_c",
                "model_name": "ForecasterRecursive(RandomForestRegressor)",
                "mae": mae,
                "rmse": rmse,
                "mape": mape,
            }
        ),
        encoding="utf-8",
    )
    if with_predictions:
        (root / "forecast_predictions.csv").write_text(
            "ds,y_true,y_pred\n2025-04-01,16.1,15.7\n",
            encoding="utf-8",
        )


def _write_first_proof_manifest(
    runtime_root: Path,
    *,
    status: str = "pass",
    path_id: str = "source-checkout-first-proof",
    duration_seconds: float = 5.0,
    target_seconds: float = 600.0,
    validation_status: str = "pass",
) -> Path:
    manifest_path = runtime_root / "log" / "execute" / "flight" / "run_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    validations = [
        {
            "label": label,
            "status": validation_status,
            "summary": f"{label} {validation_status}",
            "details": {},
        }
        for label in ("proof_steps", "target_seconds", "recommended_project")
    ]
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "agilab.run_manifest",
                "run_id": "first-proof-test",
                "path_id": path_id,
                "label": "Source checkout first proof",
                "status": status,
                "command": {
                    "label": "newcomer first proof",
                    "argv": ["tools/newcomer_first_proof.py", "--json"],
                    "cwd": str(runtime_root),
                    "env_overrides": {},
                },
                "environment": {
                    "python_version": "3.13.0",
                    "python_executable": sys.executable,
                    "platform": "test",
                    "repo_root": str(runtime_root),
                    "active_app": str(runtime_root / "flight_project"),
                    "app_name": "flight_project",
                },
                "timing": {
                    "started_at": "2026-04-25T00:00:00Z",
                    "finished_at": "2026-04-25T00:00:05Z",
                    "duration_seconds": duration_seconds,
                    "target_seconds": target_seconds,
                },
                "artifacts": [],
                "validations": validations,
                "created_at": "2026-04-25T00:00:05Z",
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


def _write_reduce_artifact(path: Path, *, engine: str = "pandas") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": f"execution_{engine}_reduce_summary",
                "reducer": f"execution_{engine}.weighted-score.v1",
                "partial_count": 1,
                "partial_ids": [f"execution_{engine}_worker_0"],
                "payload": {
                    "row_count": 48,
                    "result_rows": 24,
                    "source_file_count": 2,
                    "engines": [engine],
                    "execution_models": ["process" if engine == "pandas" else "threads"],
                },
                "metadata": {"app": f"execution_{engine}_project"},
            }
        ),
        encoding="utf-8",
    )


def _write_uav_reduce_artifact(
    path: Path,
    *,
    name: str = "uav_queue_reduce_summary",
    reducer: str = "uav_queue.queue-metrics.v1",
    app: str = "uav_queue_project",
    scenario: str = "uav_queue_hotspot",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": name,
                "reducer": reducer,
                "partial_count": 1,
                "partial_ids": ["uav_queue_worker_0_hotspot_seed2026"],
                "payload": {
                    "scenario_count": 1,
                    "scenarios": [scenario],
                    "packets_generated": 25,
                    "packets_delivered": 20,
                    "packets_dropped": 5,
                    "pdr": 0.8,
                    "mean_e2e_delay_ms": 12.4,
                    "mean_queue_wait_ms": 1.7,
                    "max_queue_depth_pkts": 6,
                },
                "metadata": {"app": app},
            }
        ),
        encoding="utf-8",
    )


def _write_forecast_reduce_artifact(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "meteo_forecast_reduce_summary",
                "reducer": "meteo_forecast.forecast-metrics.v1",
                "partial_count": 1,
                "partial_ids": ["meteo_forecast_worker_0"],
                "payload": {
                    "forecast_run_count": 1,
                    "stations": ["Paris-Montsouris"],
                    "targets": ["tmax_c"],
                    "model_names": ["ForecasterRecursive(RandomForestRegressor)"],
                    "source_files": ["meteo_fr_daily_sample.csv"],
                    "source_file_count": 1,
                    "horizon_days": ["7"],
                    "validation_days": ["21"],
                    "lags": ["7"],
                    "prediction_rows": 28,
                    "backtest_rows": 21,
                    "forecast_rows": 7,
                    "mae": 0.81,
                    "rmse": 0.97,
                    "mape": 5.42,
                },
                "metadata": {"app": "meteo_forecast_project"},
            }
        ),
        encoding="utf-8",
    )


def _write_flight_reduce_artifact(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "flight_reduce_summary",
                "reducer": "flight.trajectory-metrics.v1",
                "partial_count": 1,
                "partial_ids": ["flight_worker_0"],
                "payload": {
                    "flight_run_count": 1,
                    "row_count": 3,
                    "source_file_count": 1,
                    "source_files": ["01_track.csv"],
                    "aircraft_count": 1,
                    "aircraft": ["A1"],
                    "output_file_count": 1,
                    "output_files": ["A1.parquet"],
                    "output_formats": ["parquet"],
                    "speed_count": 3,
                    "mean_speed_m": 42.5,
                    "max_speed_m": 90.0,
                    "time_start": "2021-01-01T00:00:00",
                    "time_end": "2021-01-01T00:02:00",
                },
                "metadata": {"app": "flight_project"},
            }
        ),
        encoding="utf-8",
    )


def _run_release_page(tmp_path: Path, monkeypatch, project_dir: Path) -> AppTest:
    argv = [Path(PAGE_PATH).name, "--active-app", str(project_dir)]
    with patch.object(sys, "argv", argv):
        monkeypatch.setenv("AGI_EXPORT_DIR", str(tmp_path / "export"))
        monkeypatch.setenv("AGI_LOCAL_SHARE", str(tmp_path / "localshare"))
        monkeypatch.setenv("AGI_CLUSTER_SHARE", str(tmp_path / "clustershare"))
        monkeypatch.setenv("AGI_LOG_DIR", str(tmp_path / "log"))
        monkeypatch.setenv("OPENAI_API_KEY", "dummy")
        monkeypatch.setenv("IS_SOURCE_ENV", "1")
        at = AppTest.from_file(PAGE_PATH, default_timeout=20)
        at.run()
    return at


def _load_release_helpers() -> ModuleType:
    source = Path(PAGE_PATH).read_text(encoding="utf-8")
    prefix = source.split('\nst.set_page_config(layout="wide")\n', 1)[0]
    module = ModuleType("view_release_decision_test_module")
    module.__file__ = str(Path(PAGE_PATH).resolve())
    module.__package__ = None
    exec(compile(prefix, str(Path(PAGE_PATH)), "exec"), module.__dict__)
    return module


def test_view_release_decision_renders_promotable_candidate_and_exports_json(tmp_path, monkeypatch) -> None:
    project_dir = _create_forecast_project(tmp_path)
    export_root = tmp_path / "export" / "meteo_forecast"
    baseline_root = export_root / "run_2026_04_16"
    candidate_root = export_root / "run_2026_04_17"
    _write_bundle(baseline_root, mae=0.91, rmse=1.01, mape=5.80)
    _write_bundle(candidate_root, mae=0.81, rmse=0.97, mape=5.42)
    manifest_path = _write_first_proof_manifest(tmp_path)

    at = _run_release_page(tmp_path, monkeypatch, project_dir)

    assert not at.exception
    assert any(title.value == "Release decision" for title in at.title)
    assert any("Promotable" in message.value for message in at.success)

    export_button = next(button for button in at.button if button.label == "Export promotion decision")
    export_button.click().run()

    assert not at.exception
    decision_path = candidate_root / "promotion_decision.json"
    assert decision_path.is_file()
    payload = json.loads(decision_path.read_text(encoding="utf-8"))
    assert payload["status"] == "promotable"
    assert payload["candidate_bundle_root"] == str(candidate_root)
    assert payload["run_manifest_path"] == str(manifest_path)
    assert payload["run_manifest_summary"]["path_id"] == "source-checkout-first-proof"
    assert payload["run_manifest_summary"]["status"] == "pass"
    assert {row["gate"]: row["status"] for row in payload["run_manifest_gates"]} == {
        "run_manifest_status": "pass",
        "run_manifest_path_id": "pass",
        "run_manifest_validations": "pass",
        "run_manifest_target_seconds": "pass",
    }


def test_view_release_decision_blocks_candidate_with_missing_artifact(tmp_path, monkeypatch) -> None:
    project_dir = _create_forecast_project(tmp_path)
    export_root = tmp_path / "export" / "meteo_forecast"
    baseline_root = export_root / "run_a"
    candidate_root = export_root / "run_b"
    _write_bundle(baseline_root, mae=0.91, rmse=1.01, mape=5.80)
    _write_bundle(candidate_root, mae=0.81, rmse=0.97, mape=5.42, with_predictions=False)
    _write_first_proof_manifest(tmp_path)

    at = _run_release_page(tmp_path, monkeypatch, project_dir)

    assert not at.exception
    assert any("Blocked" in message.value for message in at.error)


def test_view_release_decision_warns_when_artifact_directory_is_missing(tmp_path, monkeypatch) -> None:
    project_dir = _create_forecast_project(tmp_path)

    at = _run_release_page(tmp_path, monkeypatch, project_dir)

    assert not at.exception
    assert any("Artifact directory does not exist yet" in warning.value for warning in at.warning)


def test_view_release_decision_helper_branches(monkeypatch, tmp_path) -> None:
    module = _load_release_helpers()

    repo_root = tmp_path / "repo"
    src_root = repo_root / "src"
    module_path = (
        src_root
        / "agilab"
        / "apps-pages"
        / "view_release_decision"
        / "src"
        / "view_release_decision"
        / "view_release_decision.py"
    )
    module_path.parent.mkdir(parents=True)
    module_path.write_text("# stub\n", encoding="utf-8")
    monkeypatch.setattr(module, "__file__", str(module_path))
    monkeypatch.setattr(module.sys, "path", [])
    module._ensure_repo_on_path()
    assert str(src_root) in module.sys.path
    assert str(repo_root) in module.sys.path

    broken_base = SimpleNamespace(glob=lambda _pattern: (_ for _ in ()).throw(RuntimeError("broken glob")))
    assert module._discover_files(broken_base, "*.json") == []

    baseline_index, candidate_index = module._default_metric_file_selection([])
    assert (baseline_index, candidate_index) == (0, 0)

    nested_metrics = module._flatten_numeric_metrics({"outer": {"mae": 0.5}, "label": "ignored", "ok": True})
    assert nested_metrics == {"outer.mae": 0.5}

    assert module._metric_direction("mae") == "lower"
    assert module._metric_direction("accuracy") == "higher"
    assert module._metric_direction("custom_metric") == "unknown"

    same_status, same_summary = module._decision_status(
        baseline_path=Path("/tmp/a.json"),
        candidate_path=Path("/tmp/a.json"),
        artifact_rows=[],
        metric_rows=[],
    )
    assert same_status == "needs_review"
    assert "same metrics file" in same_summary

    missing_rows, missing_summary = module._build_run_manifest_gate_rows(tmp_path / "missing.json")
    assert missing_rows == [
        {
            "gate": "run_manifest_present",
            "status": "fail",
            "detail": f"Missing first-proof run manifest: {tmp_path / 'missing.json'}",
        }
    ]
    assert missing_summary["error"] == "missing"

    bad_manifest = _write_first_proof_manifest(
        tmp_path,
        status="pass",
        duration_seconds=601.0,
        target_seconds=600.0,
    )
    bad_rows, bad_summary = module._build_run_manifest_gate_rows(bad_manifest)
    assert bad_summary["loaded"] is True
    assert {row["gate"]: row["status"] for row in bad_rows} == {
        "run_manifest_status": "pass",
        "run_manifest_path_id": "pass",
        "run_manifest_validations": "pass",
        "run_manifest_target_seconds": "fail",
    }

    manifest_status, manifest_summary = module._decision_status(
        baseline_path=Path("/tmp/baseline.json"),
        candidate_path=Path("/tmp/candidate.json"),
        artifact_rows=[],
        metric_rows=[],
        manifest_rows=bad_rows,
    )
    assert manifest_status == "blocked"
    assert "manifest gate" in manifest_summary

    errors: list[str] = []

    def stop_now():
        raise RuntimeError("stop")

    module.st = SimpleNamespace(error=errors.append, stop=stop_now)
    monkeypatch.setattr(module.sys, "argv", [Path(PAGE_PATH).name, "--active-app", str(tmp_path / "missing_app")])
    with pytest.raises(RuntimeError, match="stop"):
        module._resolve_active_app()
    assert any("Provided --active-app path not found" in message for message in errors)


def test_view_release_decision_discovers_reduce_artifacts_and_invalid_payloads(tmp_path) -> None:
    module = _load_release_helpers()
    artifact_root = tmp_path / "artifacts"
    valid_path = artifact_root / "run_a" / "reduce_summary_worker_0.json"
    uav_path = artifact_root / "run_uav" / "reduce_summary_worker_0.json"
    relay_path = artifact_root / "run_uav_relay" / "reduce_summary_worker_0.json"
    forecast_path = artifact_root / "run_forecast" / "reduce_summary_worker_0.json"
    flight_path = artifact_root / "run_flight" / "reduce_summary_worker_0.json"
    invalid_path = artifact_root / "run_b" / "reduce_summary_worker_1.json"
    _write_reduce_artifact(valid_path, engine="polars")
    _write_uav_reduce_artifact(uav_path)
    _write_uav_reduce_artifact(
        relay_path,
        name="uav_relay_queue_reduce_summary",
        reducer="uav_relay_queue.queue-metrics.v1",
        app="uav_relay_queue_project",
        scenario="uav_relay_queue_hotspot",
    )
    _write_forecast_reduce_artifact(forecast_path)
    _write_flight_reduce_artifact(flight_path)
    invalid_path.parent.mkdir(parents=True, exist_ok=True)
    invalid_path.write_text("{broken", encoding="utf-8")

    rows = module._build_reduce_artifact_rows(artifact_root)

    valid = next(row for row in rows if row["status"] == "pass")
    uav = next(row for row in rows if row["reducer"] == "uav_queue.queue-metrics.v1")
    relay = next(row for row in rows if row["reducer"] == "uav_relay_queue.queue-metrics.v1")
    forecast = next(row for row in rows if row["reducer"] == "meteo_forecast.forecast-metrics.v1")
    flight = next(row for row in rows if row["reducer"] == "flight.trajectory-metrics.v1")
    invalid = next(row for row in rows if row["status"] == "invalid")
    assert valid["artifact"] == "run_a/reduce_summary_worker_0.json"
    assert valid["reducer"] == "execution_polars.weighted-score.v1"
    assert valid["partial_count"] == 1
    assert valid["source_file_count"] == 2
    assert valid["row_count"] == 48
    assert valid["engines"] == "polars"
    assert valid["execution_models"] == "threads"
    assert uav["artifact"] == "run_uav/reduce_summary_worker_0.json"
    assert uav["scenario_count"] == 1
    assert uav["scenarios"] == "uav_queue_hotspot"
    assert uav["packets_generated"] == 25
    assert uav["packets_delivered"] == 20
    assert uav["packets_dropped"] == 5
    assert uav["pdr"] == 0.8
    assert uav["mean_e2e_delay_ms"] == 12.4
    assert uav["mean_queue_wait_ms"] == 1.7
    assert uav["max_queue_depth_pkts"] == 6
    assert relay["artifact"] == "run_uav_relay/reduce_summary_worker_0.json"
    assert relay["scenario_count"] == 1
    assert relay["scenarios"] == "uav_relay_queue_hotspot"
    assert relay["packets_generated"] == 25
    assert relay["packets_delivered"] == 20
    assert relay["packets_dropped"] == 5
    assert relay["pdr"] == 0.8
    assert forecast["artifact"] == "run_forecast/reduce_summary_worker_0.json"
    assert forecast["forecast_run_count"] == 1
    assert forecast["stations"] == "Paris-Montsouris"
    assert forecast["targets"] == "tmax_c"
    assert forecast["model_names"] == "ForecasterRecursive(RandomForestRegressor)"
    assert forecast["source_file_count"] == 1
    assert forecast["prediction_rows"] == 28
    assert forecast["backtest_rows"] == 21
    assert forecast["forecast_rows"] == 7
    assert forecast["mae"] == 0.81
    assert forecast["rmse"] == 0.97
    assert forecast["mape"] == 5.42
    assert forecast["horizon_days"] == "7"
    assert forecast["validation_days"] == "21"
    assert forecast["lags"] == "7"
    assert flight["artifact"] == "run_flight/reduce_summary_worker_0.json"
    assert flight["flight_run_count"] == 1
    assert flight["row_count"] == 3
    assert flight["source_file_count"] == 1
    assert flight["aircraft_count"] == 1
    assert flight["aircraft"] == "A1"
    assert flight["output_file_count"] == 1
    assert flight["output_files"] == "A1.parquet"
    assert flight["output_formats"] == "parquet"
    assert flight["speed_count"] == 3
    assert flight["mean_speed_m"] == 42.5
    assert flight["max_speed_m"] == 90.0
    assert flight["time_start"] == "2021-01-01T00:00:00"
    assert flight["time_end"] == "2021-01-01T00:02:00"
    assert invalid["artifact"] == "run_b/reduce_summary_worker_1.json"
    assert "Expecting property name" in invalid["detail"]


def test_view_release_decision_surfaces_reduce_artifacts_without_metrics(tmp_path, monkeypatch) -> None:
    artifact_root = tmp_path / "export" / "execution_pandas_project"
    _write_reduce_artifact(artifact_root / "results" / "reduce_summary_worker_0.json")
    project_dir = tmp_path / "apps" / "execution_pandas_project"
    project_dir.mkdir(parents=True)

    env = SimpleNamespace(
        app="execution_pandas_project",
        target="execution_pandas_project",
        AGILAB_EXPORT_ABS=str(tmp_path / "export"),
        st_resources=tmp_path,
    )
    argv = [Path(PAGE_PATH).name, "--active-app", str(project_dir)]
    with patch.object(sys, "argv", argv):
        monkeypatch.setenv("AGI_EXPORT_DIR", str(tmp_path / "export"))
        monkeypatch.setenv("AGI_LOCAL_SHARE", str(tmp_path / "localshare"))
        monkeypatch.setenv("AGI_CLUSTER_SHARE", str(tmp_path / "clustershare"))
        monkeypatch.setenv("AGI_LOG_DIR", str(tmp_path / "log"))
        monkeypatch.setenv("OPENAI_API_KEY", "dummy")
        monkeypatch.setenv("IS_SOURCE_ENV", "1")
        at = AppTest.from_file(PAGE_PATH, default_timeout=20)
        at.session_state["env"] = env
        at.run()

    assert not at.exception
    assert any(header.value == "Reduce artifacts" for header in at.subheader)
    assert any("No metrics file found" in warning.value for warning in at.warning)


def test_view_release_decision_reuses_existing_session_env(tmp_path, monkeypatch) -> None:
    project_dir = _create_forecast_project(tmp_path)
    export_root = tmp_path / "export" / "meteo_forecast"
    baseline_root = export_root / "run_a"
    candidate_root = export_root / "run_b"
    _write_bundle(baseline_root, mae=1.1, rmse=1.2, mape=6.2)
    _write_bundle(candidate_root, mae=0.9, rmse=1.0, mape=5.9)
    _write_first_proof_manifest(tmp_path)

    env = SimpleNamespace(
        app="meteo_forecast_project",
        target="meteo_forecast",
        AGILAB_EXPORT_ABS=str(tmp_path / "export"),
        AGILAB_LOG_ABS=tmp_path / "log",
        st_resources=tmp_path,
    )
    argv = [Path(PAGE_PATH).name, "--active-app", str(project_dir)]
    with patch.object(sys, "argv", argv):
        monkeypatch.setenv("AGI_EXPORT_DIR", str(tmp_path / "export"))
        monkeypatch.setenv("AGI_LOCAL_SHARE", str(tmp_path / "localshare"))
        monkeypatch.setenv("AGI_CLUSTER_SHARE", str(tmp_path / "clustershare"))
        monkeypatch.setenv("AGI_LOG_DIR", str(tmp_path / "log"))
        monkeypatch.setenv("OPENAI_API_KEY", "dummy")
        monkeypatch.setenv("IS_SOURCE_ENV", "1")
        at = AppTest.from_file(PAGE_PATH, default_timeout=20)
        at.session_state["env"] = env
        at.run()

    assert not at.exception
