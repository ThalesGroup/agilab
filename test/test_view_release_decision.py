from __future__ import annotations

import hashlib
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
    project_dir = apps_dir / "weather_forecast_project"
    (project_dir / "src" / "meteo_forecast").mkdir(parents=True)
    (project_dir / "pyproject.toml").write_text("[project]\nname='weather-forecast-project'\n", encoding="utf-8")
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
    run_id: str = "first-proof-test",
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
                "run_id": run_id,
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
                    "active_app": str(runtime_root / "flight_telemetry_project"),
                    "app_name": "flight_telemetry_project",
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


def _write_ci_artifact_harvest(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    source_machine = "github-actions:macos-14-arm64"
    artifacts = [
        {
            "id": "first_proof_run_manifest",
            "kind": "run_manifest",
            "path": "ci/source-checkout-first-proof/run_manifest.json",
            "payload_status": "validated",
            "content_sha256": "sha-run-manifest",
            "calculated_sha256": "sha-run-manifest",
            "sha256_verified": True,
            "source_machine": source_machine,
            "workflow": "public-evidence.yml",
            "run_id": "ci-sample-20260425",
            "run_attempt": "1",
            "attachment_status": "provenance_tagged",
        },
        {
            "id": "public_kpi_evidence_bundle",
            "kind": "kpi_evidence_bundle",
            "path": "ci/evidence/kpi_evidence_bundle.json",
            "payload_status": "validated",
            "content_sha256": "sha-kpi",
            "calculated_sha256": "sha-kpi",
            "sha256_verified": True,
            "source_machine": source_machine,
            "workflow": "public-evidence.yml",
            "run_id": "ci-sample-20260425",
            "run_attempt": "1",
            "attachment_status": "provenance_tagged",
        },
        {
            "id": "compatibility_matrix_report",
            "kind": "compatibility_report",
            "path": "ci/evidence/compatibility_report.json",
            "payload_status": "validated",
            "content_sha256": "sha-compat",
            "calculated_sha256": "sha-compat",
            "sha256_verified": True,
            "source_machine": source_machine,
            "workflow": "public-evidence.yml",
            "run_id": "ci-sample-20260425",
            "run_attempt": "1",
            "attachment_status": "provenance_tagged",
        },
        {
            "id": "promotion_decision_export",
            "kind": "promotion_decision",
            "path": "ci/release/promotion_decision.json",
            "payload_status": "validated",
            "content_sha256": "sha-decision",
            "calculated_sha256": "sha-decision",
            "sha256_verified": True,
            "source_machine": source_machine,
            "workflow": "public-evidence.yml",
            "run_id": "ci-sample-20260425",
            "run_attempt": "1",
            "attachment_status": "provenance_tagged",
        },
    ]
    path.write_text(
        json.dumps(
            {
                "schema": "agilab.ci_artifact_harvest.v1",
                "run_id": "ci-artifact-harvest-proof",
                "run_status": "harvest_ready",
                "execution_mode": "ci_artifact_contract_only",
                "release": {
                    "release_id": "run_2026_04_17",
                    "public_status": "validated",
                    "artifact_statuses": {
                        "run_manifest": "validated",
                        "kpi_evidence_bundle": "validated",
                        "compatibility_report": "validated",
                        "promotion_decision": "validated",
                    },
                    "source_machines": [source_machine],
                },
                "summary": {
                    "release_status": "validated",
                    "artifact_count": 4,
                    "checksum_mismatch_count": 0,
                    "provenance_tagged_count": 4,
                    "external_machine_evidence_count": 4,
                    "live_ci_query_count": 0,
                    "network_probe_count": 0,
                    "command_execution_count": 0,
                },
                "artifacts": artifacts,
                "provenance": {
                    "queries_ci_provider": False,
                    "executes_network_probe": False,
                    "executes_commands": False,
                },
            }
        ),
        encoding="utf-8",
    )
    return path


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
                "name": "weather_forecast_reduce_summary",
                "reducer": "weather_forecast.forecast-metrics.v1",
                "partial_count": 1,
                "partial_ids": ["weather_forecast_worker_0"],
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
                "metadata": {"app": "weather_forecast_project"},
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
                "metadata": {"app": "flight_telemetry_project"},
            }
        ),
        encoding="utf-8",
    )


def _run_release_page(
    tmp_path: Path,
    monkeypatch,
    project_dir: Path,
    *,
    manifest_import_args: str = "",
    ci_artifact_harvest_args: str = "",
) -> AppTest:
    argv = [Path(PAGE_PATH).name, "--active-app", str(project_dir)]
    with patch.object(sys, "argv", argv):
        monkeypatch.setenv("AGI_EXPORT_DIR", str(tmp_path / "export"))
        monkeypatch.setenv("AGI_LOCAL_SHARE", str(tmp_path / "localshare"))
        monkeypatch.setenv("AGI_CLUSTER_SHARE", str(tmp_path / "clustershare"))
        monkeypatch.setenv("AGI_LOG_DIR", str(tmp_path / "log"))
        monkeypatch.setenv("OPENAI_API_KEY", "dummy")
        monkeypatch.setenv("IS_SOURCE_ENV", "1")
        at = AppTest.from_file(PAGE_PATH, default_timeout=20)
        if manifest_import_args:
            at.session_state["release_decision_manifest_import_args"] = manifest_import_args
        if ci_artifact_harvest_args:
            at.session_state["release_decision_ci_artifact_harvest_args"] = ci_artifact_harvest_args
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
    assert any(header.value == "Connector path registry" for header in at.subheader)
    connector_live_ui = at.session_state["release_decision_connector_live_ui"]
    assert connector_live_ui["run_status"] == "ready_for_live_ui"
    assert connector_live_ui["summary"]["connector_card_count"] == 5
    assert connector_live_ui["summary"]["page_binding_count"] == 2
    assert connector_live_ui["summary"]["network_probe_count"] == 0

    export_button = next(button for button in at.button if button.label == "Export promotion decision")
    export_button.click().run()

    assert not at.exception
    decision_path = candidate_root / "promotion_decision.json"
    assert decision_path.is_file()
    payload = json.loads(decision_path.read_text(encoding="utf-8"))
    assert payload["status"] == "promotable"
    assert payload["candidate_bundle_root"] == str(candidate_root)
    assert payload["connector_registry_summary"]["paths"]["artifact_root"] == str(export_root)
    assert {
        row["connector_id"]
        for row in payload["connector_registry_paths"]
    } >= {"export_root", "log_root", "artifact_root", "first_proof_manifest"}
    assert payload["run_manifest_path"] == str(manifest_path)
    assert payload["run_manifest_summary"]["path_id"] == "source-checkout-first-proof"
    assert payload["run_manifest_summary"]["status"] == "pass"
    assert {row["gate"]: row["status"] for row in payload["run_manifest_gates"]} == {
        "run_manifest_status": "pass",
        "run_manifest_path_id": "pass",
        "run_manifest_validations": "pass",
        "run_manifest_target_seconds": "pass",
    }


def test_view_release_decision_imports_external_manifest_for_gate(tmp_path, monkeypatch) -> None:
    project_dir = _create_forecast_project(tmp_path)
    export_root = tmp_path / "export" / "meteo_forecast"
    baseline_root = export_root / "run_2026_04_16"
    candidate_root = export_root / "run_2026_04_17"
    _write_bundle(baseline_root, mae=0.91, rmse=1.01, mape=5.80)
    _write_bundle(candidate_root, mae=0.81, rmse=0.97, mape=5.42)
    imported_manifest_path = _write_first_proof_manifest(tmp_path / "external_machine")
    Path(f"{imported_manifest_path}.sig").write_text("test signature\n", encoding="utf-8")
    imported_manifest_sha256 = hashlib.sha256(imported_manifest_path.read_bytes()).hexdigest()

    at = _run_release_page(
        tmp_path,
        monkeypatch,
        project_dir,
        manifest_import_args=(
            "uv --preview-features extra-build-dependencies run python "
            f"tools/compatibility_report.py --manifest {imported_manifest_path} --compact"
        ),
    )

    assert not at.exception
    assert any("Promotable" in message.value for message in at.success)
    assert any(header.value == "Imported run manifest evidence" for header in at.subheader)
    assert any(header.value == "Cross-release manifest comparison" for header in at.subheader)
    assert any(header.value == "Cross-run evidence bundle comparison" for header in at.subheader)

    export_button = next(button for button in at.button if button.label == "Export promotion decision")
    export_button.click().run()

    decision_path = candidate_root / "promotion_decision.json"
    payload = json.loads(decision_path.read_text(encoding="utf-8"))
    assert payload["run_manifest_path"] == str(imported_manifest_path)
    assert payload["run_manifest_import_summary"]["loaded_manifest_count"] == 1
    assert payload["run_manifest_import_summary"]["validated_manifest_count"] == 1
    assert payload["manifest_index_path"] == str(export_root / "manifest_index.json")
    assert payload["manifest_index_summary"]["loaded"] is True
    assert payload["manifest_index_summary"]["existing_index_loaded"] is False
    assert payload["manifest_index_summary"]["existing_index_error"] == "missing"
    assert payload["manifest_index_summary"]["release_count"] == 1
    assert payload["manifest_index_summary"]["manifest_count"] == 1
    assert payload["manifest_index_comparison_summary"]["previous_release_count"] == 0
    assert payload["manifest_index_comparison_summary"]["compared_path_count"] == 1
    assert payload["manifest_index_comparison_summary"]["status_counts"] == {"newly_validated": 1}
    assert payload["manifest_index_comparison"][0]["comparison_status"] == "newly_validated"
    assert payload["evidence_bundle_comparison_summary"]["target_count"] == 1
    assert payload["evidence_bundle_comparison_summary"]["evidence_counts"] == {
        "artifact": 2,
        "kpi": 3,
        "manifest": 1,
        "reduce_artifact": 1,
    }
    assert payload["evidence_bundle_comparison_summary"]["blocking_count"] == 0
    assert payload["imported_run_manifest_evidence"][0]["source"] == str(imported_manifest_path)
    assert payload["imported_run_manifest_evidence"][0]["path_id"] == "source-checkout-first-proof"
    assert payload["imported_run_manifest_evidence"][0]["evidence_status"] == "validated"
    assert payload["imported_run_manifest_evidence"][0]["duration_seconds"] == 5.0
    assert payload["imported_run_manifest_evidence"][0]["target_seconds"] == 600.0
    assert "proof_steps=pass" in payload["imported_run_manifest_evidence"][0]["validation_statuses"]
    assert payload["imported_run_manifest_evidence"][0]["attachment_status"] == "signed"
    assert payload["imported_run_manifest_evidence"][0]["attachment_sha256"] == imported_manifest_sha256
    assert (
        payload["imported_run_manifest_evidence"][0]["attachment_signature_path"]
        == f"{imported_manifest_path}.sig"
    )
    manifest_index_path = export_root / "manifest_index.json"
    assert manifest_index_path.is_file()
    manifest_index = json.loads(manifest_index_path.read_text(encoding="utf-8"))
    assert manifest_index["schema"] == "agilab.manifest_index.v1"
    release = manifest_index["releases"][str(candidate_root)]
    assert release["release_id"] == "run_2026_04_17"
    assert release["candidate_bundle_root"] == str(candidate_root)
    assert release["baseline_bundle_root"] == str(baseline_root)
    assert release["selected_run_manifest_path"] == str(imported_manifest_path)
    assert release["import_summary"]["loaded_manifest_count"] == 1
    assert release["import_summary"]["signed_attachment_count"] == 1
    assert release["manifests"][0]["source"] == str(imported_manifest_path)
    assert release["manifests"][0]["evidence_status"] == "validated"
    assert release["manifests"][0]["attachment"]["verification_status"] == "signed"
    assert release["manifests"][0]["attachment"]["sha256"] == imported_manifest_sha256


def test_view_release_decision_imports_ci_artifact_harvest_for_export(tmp_path, monkeypatch) -> None:
    project_dir = _create_forecast_project(tmp_path)
    export_root = tmp_path / "export" / "meteo_forecast"
    baseline_root = export_root / "run_2026_04_16"
    candidate_root = export_root / "run_2026_04_17"
    _write_bundle(baseline_root, mae=0.91, rmse=1.01, mape=5.80)
    _write_bundle(candidate_root, mae=0.81, rmse=0.97, mape=5.42)
    _write_first_proof_manifest(tmp_path)
    harvest_path = _write_ci_artifact_harvest(
        tmp_path / "external_ci" / "ci_artifact_harvest.json"
    )

    at = _run_release_page(
        tmp_path,
        monkeypatch,
        project_dir,
        ci_artifact_harvest_args=f"--ci-artifact-harvest {harvest_path}",
    )

    assert not at.exception
    assert any("Promotable" in message.value for message in at.success)
    assert any(header.value == "CI artifact harvest evidence" for header in at.subheader)

    export_button = next(button for button in at.button if button.label == "Export promotion decision")
    export_button.click().run()

    decision_path = candidate_root / "promotion_decision.json"
    payload = json.loads(decision_path.read_text(encoding="utf-8"))
    summary = payload["ci_artifact_harvest_summary"]
    rows = payload["ci_artifact_harvest_evidence"]
    assert summary["gate_status"] == "pass"
    assert summary["requested_harvest_count"] == 1
    assert summary["loaded_harvest_count"] == 1
    assert summary["validated_harvest_count"] == 1
    assert summary["artifact_count"] == 4
    assert summary["checksum_mismatch_count"] == 0
    assert summary["provenance_tagged_count"] == 4
    assert summary["external_machine_evidence_count"] == 4
    assert rows[0]["source"] == str(harvest_path)
    assert {row["artifact_kind"] for row in rows} == {
        "compatibility_report",
        "kpi_evidence_bundle",
        "promotion_decision",
        "run_manifest",
    }
    assert {row["harvest_status"] for row in rows} == {"validated"}
    assert {row["release_status"] for row in rows} == {"validated"}
    assert all(row["sha256_verified"] is True for row in rows)
    assert {row["source_machine"] for row in rows} == {
        "github-actions:macos-14-arm64"
    }


def test_view_release_decision_compares_manifest_index_history(tmp_path, monkeypatch) -> None:
    project_dir = _create_forecast_project(tmp_path)
    export_root = tmp_path / "export" / "meteo_forecast"
    baseline_root = export_root / "run_2026_04_16"
    candidate_root = export_root / "run_2026_04_17"
    prior_root = export_root / "run_2026_04_15"
    _write_bundle(prior_root, mae=0.86, rmse=0.99, mape=5.50)
    _write_bundle(baseline_root, mae=0.91, rmse=1.01, mape=5.80)
    _write_bundle(candidate_root, mae=0.81, rmse=0.97, mape=5.42)
    _write_forecast_reduce_artifact(prior_root / "reduce_summary_worker_0.json")
    _write_forecast_reduce_artifact(candidate_root / "reduce_summary_worker_0.json")
    current_manifest_path = _write_first_proof_manifest(
        tmp_path / "current_external_machine",
        run_id="current-first-proof",
        duration_seconds=5.0,
    )
    failed_manifest_path = _write_first_proof_manifest(
        tmp_path / "current_ci_machine",
        run_id="current-ci-proof",
        status="fail",
        path_id="ci-fresh-proof",
        duration_seconds=700.0,
        validation_status="fail",
    )
    (export_root / "manifest_index.json").write_text(
        json.dumps(
            {
                "schema": "agilab.manifest_index.v1",
                "generated_at": "2026-04-24T00:00:00Z",
                "artifact_root": str(export_root),
                "releases": {
                    str(prior_root): {
                        "release_id": "run_2026_04_15",
                        "artifact_root": str(export_root),
                        "candidate_bundle_root": str(prior_root),
                        "baseline_bundle_root": str(baseline_root),
                        "candidate_metrics_file": str(prior_root / "forecast_metrics.json"),
                        "baseline_metrics_file": str(baseline_root / "forecast_metrics.json"),
                        "selected_run_manifest_path": "/external/prior/run_manifest.json",
                        "selected_run_manifest_summary": {"loaded": True, "status": "pass"},
                        "import_summary": {"loaded_manifest_count": 2},
                        "manifests": [
                            {
                                "source": "/external/prior/run_manifest.json",
                                "provenance": "--manifest",
                                "path_id": "source-checkout-first-proof",
                                "run_id": "prior-first-proof",
                                "manifest_status": "pass",
                                "evidence_status": "validated",
                                "duration_seconds": 8.0,
                                "target_seconds": 600.0,
                                "validation_statuses": "proof_steps=pass",
                                "loaded": True,
                                "detail": "loaded",
                            },
                            {
                                "source": "/external/prior/legacy_manifest.json",
                                "provenance": "--manifest",
                                "path_id": "legacy-only-proof",
                                "run_id": "prior-legacy-proof",
                                "manifest_status": "pass",
                                "evidence_status": "validated",
                                "duration_seconds": 9.0,
                                "target_seconds": 600.0,
                                "validation_statuses": "proof_steps=pass",
                                "loaded": True,
                                "detail": "loaded",
                            },
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    at = _run_release_page(
        tmp_path,
        monkeypatch,
        project_dir,
        manifest_import_args=f"--manifest {current_manifest_path} --manifest {failed_manifest_path}",
    )

    assert not at.exception
    assert any(header.value == "Cross-release manifest comparison" for header in at.subheader)
    assert any(header.value == "Cross-run evidence bundle comparison" for header in at.subheader)

    export_button = next(button for button in at.button if button.label == "Export promotion decision")
    export_button.click().run()

    decision_path = candidate_root / "promotion_decision.json"
    payload = json.loads(decision_path.read_text(encoding="utf-8"))
    comparison_by_key = {
        row["comparison_key"]: row
        for row in payload["manifest_index_comparison"]
    }
    assert payload["manifest_index_summary"]["release_count"] == 2
    assert payload["manifest_index_comparison_summary"]["previous_release_count"] == 1
    assert payload["manifest_index_comparison_summary"]["status_counts"] == {
        "better": 1,
        "failed": 1,
        "missing_current_evidence": 1,
    }
    assert payload["manifest_index_comparison_summary"]["blocking_count"] == 2
    assert comparison_by_key["source-checkout-first-proof"]["comparison_status"] == "better"
    assert comparison_by_key["source-checkout-first-proof"]["prior_duration_seconds"] == 8.0
    assert comparison_by_key["source-checkout-first-proof"]["current_duration_seconds"] == 5.0
    assert comparison_by_key["ci-fresh-proof"]["comparison_status"] == "failed"
    assert comparison_by_key["legacy-only-proof"]["comparison_status"] == "missing_current_evidence"
    bundle_rows = payload["evidence_bundle_comparison"]
    prior_reduce = next(
        row
        for row in bundle_rows
        if row["target_kind"] == "prior_indexed" and row["evidence"] == "reduce_artifact"
    )
    baseline_reduce = next(
        row
        for row in bundle_rows
        if row["target_kind"] == "baseline" and row["evidence"] == "reduce_artifact"
    )
    assert payload["evidence_bundle_comparison_summary"]["target_count"] == 2
    assert payload["evidence_bundle_comparison_summary"]["evidence_counts"] == {
        "artifact": 4,
        "kpi": 6,
        "manifest": 2,
        "reduce_artifact": 2,
    }
    assert payload["evidence_bundle_comparison_summary"]["blocking_count"] == 0
    assert prior_reduce["status"] == "stable"
    assert baseline_reduce["status"] == "expanded"


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
    fake_agilab_package = ModuleType("agilab")
    fake_agilab_package.__path__ = []
    monkeypatch.setitem(module.sys.modules, "agilab", fake_agilab_package)
    module._ensure_repo_on_path()
    assert str(src_root) in module.sys.path
    assert str(repo_root) in module.sys.path
    assert str(src_root / "agilab") in fake_agilab_package.__path__

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

    import_args = (
        f"uv run python tools/compatibility_report.py --manifest {bad_manifest} "
        f"--manifest-dir {bad_manifest.parent.parent.parent}"
    )
    manifest_paths, manifest_dirs, parse_errors = module._parse_manifest_import_args(import_args)
    assert manifest_paths == [bad_manifest]
    assert manifest_dirs == [bad_manifest.parent.parent.parent]
    assert parse_errors == []

    import_rows, import_summary = module._build_manifest_import_rows(import_args)
    assert import_summary["discovered_manifest_count"] == 1
    assert import_summary["loaded_manifest_count"] == 1
    assert import_rows[0]["source"] == str(bad_manifest)
    assert import_rows[0]["provenance"].startswith("--manifest")
    assert import_rows[0]["path_id"] == "source-checkout-first-proof"
    assert import_rows[0]["evidence_status"] == "validated"
    assert import_rows[0]["duration_seconds"] == 601.0
    assert import_rows[0]["attachment_status"] == "provenance_tagged"
    assert import_rows[0]["attachment_sha256"] == hashlib.sha256(bad_manifest.read_bytes()).hexdigest()
    assert import_summary["attached_manifest_count"] == 1
    assert import_summary["provenance_tagged_attachment_count"] == 1
    assert "target_seconds=pass" in import_rows[0]["validation_statuses"]
    assert module._select_run_manifest_gate_path(tmp_path / "missing.json", import_rows) == bad_manifest
    connector_preview = module._build_release_decision_connector_preview_state()
    connector_live_ui = module._render_release_decision_connector_live_ui(
        module.render_connector_live_ui.__globals__["StreamlitCallRecorder"]()
    )
    assert connector_preview["run_status"] == "ready_for_ui_preview"
    assert connector_live_ui["run_status"] == "ready_for_live_ui"
    assert connector_live_ui["summary"]["network_probe_count"] == 0

    manifest_index_path = tmp_path / "artifact_root" / "manifest_index.json"
    empty_index, empty_summary = module._load_manifest_index(manifest_index_path)
    assert empty_summary["loaded"] is False
    assert empty_summary["error"] == "missing"
    release = module._build_manifest_index_release(
        artifact_root=manifest_index_path.parent,
        baseline_path=tmp_path / "artifact_root" / "run_a" / "metrics.json",
        candidate_path=tmp_path / "artifact_root" / "run_b" / "metrics.json",
        run_manifest_path=bad_manifest,
        run_manifest_summary=bad_summary,
        imported_manifest_rows=import_rows,
        imported_manifest_summary=import_summary,
    )
    merged_index = module._merge_manifest_index(
        empty_index,
        artifact_root=manifest_index_path.parent,
        release=release,
    )
    merged_summary = module._manifest_index_summary(
        merged_index,
        path=manifest_index_path,
        loaded=empty_summary["loaded"],
        error=empty_summary["error"],
    )
    assert merged_summary["release_count"] == 1
    assert merged_summary["manifest_count"] == 1
    assert merged_summary["loaded"] is True
    assert merged_summary["existing_index_loaded"] is False
    assert merged_summary["validated_manifest_count"] == 1
    assert merged_summary["attached_manifest_count"] == 1
    assert merged_summary["provenance_tagged_attachment_count"] == 1
    index_rows = module._manifest_index_rows(merged_index)
    assert index_rows[0]["release"] == "run_b"
    assert index_rows[0]["source"] == str(bad_manifest)
    assert index_rows[0]["attachment_status"] == "provenance_tagged"
    written_index = module._write_manifest_index(manifest_index_path, merged_index)
    assert written_index == manifest_index_path
    loaded_index, loaded_summary = module._load_manifest_index(manifest_index_path)
    assert loaded_summary["loaded"] is True
    assert loaded_summary["release_count"] == 1
    loaded_release = loaded_index["releases"][str(tmp_path / "artifact_root" / "run_b")]
    assert loaded_release["manifests"][0]["source"] == str(bad_manifest)
    stale_release = module._build_manifest_index_release(
        artifact_root=manifest_index_path.parent,
        baseline_path=tmp_path / "artifact_root" / "run_b" / "metrics.json",
        candidate_path=tmp_path / "artifact_root" / "run_c" / "metrics.json",
        run_manifest_path=bad_manifest,
        run_manifest_summary=bad_summary,
        imported_manifest_rows=import_rows,
        imported_manifest_summary=import_summary,
    )
    comparison_rows = module._build_manifest_index_comparison_rows(loaded_index, stale_release)
    assert comparison_rows[0]["comparison_status"] == "stale"
    assert comparison_rows[0]["attachment_match"] is True
    assert comparison_rows[0]["current_attachment_status"] == "provenance_tagged"
    comparison_summary = module._manifest_index_comparison_summary(
        comparison_rows,
        loaded_index,
        stale_release,
    )
    assert comparison_summary["previous_release_count"] == 1
    assert comparison_summary["stale_count"] == 1

    missing_paths, missing_dirs, missing_errors = module._parse_manifest_import_args("--manifest-dir")
    assert missing_paths == []
    assert missing_dirs == []
    assert missing_errors == [{"source": "--manifest-dir", "detail": "--manifest-dir requires a path value"}]

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
    forecast = next(row for row in rows if row["reducer"] == "weather_forecast.forecast-metrics.v1")
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
        app="weather_forecast_project",
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
