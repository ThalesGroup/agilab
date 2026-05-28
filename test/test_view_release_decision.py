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
    (project_dir / "src" / "weather_forecast").mkdir(parents=True)
    (project_dir / "pyproject.toml").write_text("[project]\nname='weather-forecast-project'\n", encoding="utf-8")
    (project_dir / "src" / "app_settings.toml").write_text(
        "\n".join(
            [
                "[args]",
                "",
                "[pages.view_release_decision]",
                'metrics_glob = "**/forecast_metrics.json"',
                'required_patterns = ["forecast_metrics.json", "forecast_predictions.csv"]',
                "",
            ]
        ),
        encoding="utf-8",
    )
    (project_dir / "src" / "weather_forecast" / "__init__.py").write_text("", encoding="utf-8")
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
    manifest_path = runtime_root / "log" / "execute" / "flight_telemetry" / "run_manifest.json"
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
                "reducer": "flight_telemetry.trajectory-metrics.v1",
                "partial_count": 1,
                "partial_ids": ["flight_telemetry_worker_0"],
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
    export_root = tmp_path / "export" / "weather_forecast"
    baseline_root = export_root / "run_2026_04_16"
    candidate_root = export_root / "run_2026_04_17"
    _write_bundle(baseline_root, mae=0.91, rmse=1.01, mape=5.80)
    _write_bundle(candidate_root, mae=0.81, rmse=0.97, mape=5.42)
    manifest_path = _write_first_proof_manifest(tmp_path)

    at = _run_release_page(tmp_path, monkeypatch, project_dir)

    assert not at.exception
    assert any(title.value == "Evidence cockpit" for title in at.title)
    assert any(header.value == "Run review cockpit" for header in at.subheader)
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
    assert payload["evidence_cockpit_summary"]["status_label"] == "Ready to export"
    assert payload["evidence_cockpit_summary"]["export_ready"] is True
    assert payload["evidence_cockpit_summary"]["explicit_blocking_gate_count"] == 0
    assert payload["evidence_cockpit_summary"]["candidate_bundle_root"] == str(candidate_root)
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
    export_root = tmp_path / "export" / "weather_forecast"
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
    export_root = tmp_path / "export" / "weather_forecast"
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
    export_root = tmp_path / "export" / "weather_forecast"
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
    export_root = tmp_path / "export" / "weather_forecast"
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

    fake_agilab_tuple_package = ModuleType("agilab")
    fake_agilab_tuple_package.__path__ = ()
    monkeypatch.setitem(module.sys.modules, "agilab", fake_agilab_tuple_package)
    module._ensure_repo_on_path()
    assert fake_agilab_tuple_package.__path__ == [str(src_root / "agilab")]

    run_manifest_path = src_root / "agilab" / "run_manifest.py"
    run_manifest_path.write_text("RUN_MANIFEST_FILENAME = 'run_manifest.json'\n", encoding="utf-8")
    monkeypatch.setattr(
        module.importlib.util,
        "spec_from_file_location",
        lambda *_args, **_kwargs: SimpleNamespace(loader=None),
    )
    with pytest.raises(ModuleNotFoundError):
        module._load_run_manifest_module()

    registry_paths: list[str] = []

    class _Registry:
        def path(self, name: str) -> Path:
            registry_paths.append(name)
            return tmp_path / name

    monkeypatch.setattr(module, "_connector_path_registry", lambda _env: _Registry())
    assert module._default_artifact_root(SimpleNamespace(target="demo", app="demo")) == tmp_path / "artifact_root"
    assert registry_paths == ["artifact_root"]
    fake_st = SimpleNamespace(
        session_state={
            "release_decision_app_scope": "old:/old",
            "release_decision_datadir": "/old/artifacts",
            "release_decision_metrics_glob": "*.json",
            "release_decision_required_patterns": "*.json",
            "release_decision_run_manifest_path": "/old/run_manifest.json",
        }
    )
    env = SimpleNamespace(app="weather_forecast_project", active_app=tmp_path / "weather_forecast_project")
    module._reset_app_scoped_session_defaults(fake_st, env)
    assert fake_st.session_state == {
        "release_decision_app_scope": f"weather_forecast_project:{tmp_path / 'weather_forecast_project'}",
    }
    settings_root = tmp_path / "weather_forecast_project"
    (settings_root / "src").mkdir(parents=True)
    (settings_root / "src" / "app_settings.toml").write_text(
        "\n".join(
            [
                "[pages.view_release_decision]",
                'metrics_glob = "**/forecast_metrics.json"',
                'required_patterns = ["forecast_metrics.json", "forecast_predictions.csv"]',
                "",
            ]
        ),
        encoding="utf-8",
    )
    normalized_env = SimpleNamespace(
        app="weather_forecast",
        target="weather_forecast",
        active_app=settings_root,
    )
    assert module._default_metrics_glob(normalized_env) == "**/forecast_metrics.json"
    assert module._default_required_patterns(normalized_env) == [
        "forecast_metrics.json",
        "forecast_predictions.csv",
    ]
    generic_env = SimpleNamespace(app="demo", target="demo", active_app=tmp_path / "missing_project")
    assert module._default_metrics_glob(generic_env) == "**/*metrics*.json"
    assert module._default_required_patterns(generic_env) == ["*.json"]

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

    cockpit_summary = module._build_evidence_cockpit_summary(
        decision_status=manifest_status,
        decision_summary=manifest_summary,
        artifact_root=tmp_path / "artifact_root",
        baseline_path=tmp_path / "artifact_root" / "run_a" / "metrics.json",
        candidate_path=tmp_path / "artifact_root" / "run_b" / "metrics.json",
        metrics_files=[
            tmp_path / "artifact_root" / "run_a" / "metrics.json",
            tmp_path / "artifact_root" / "run_b" / "metrics.json",
        ],
        artifact_rows=[{"status": "pass"}],
        metric_rows=[{"status": "pass"}],
        run_manifest_rows=bad_rows,
        run_manifest_summary=bad_summary,
        imported_manifest_summary={"loaded_manifest_count": 0, "validated_manifest_count": 0},
        ci_artifact_harvest_summary={"gate_status": "not_configured"},
        manifest_index_summary={"release_count": 0, "manifest_count": 0},
        evidence_bundle_comparison_summary={"blocking_count": 0},
        reduce_artifact_rows=[{"status": "pass"}],
    )
    assert cockpit_summary["schema"] == "agilab.evidence_cockpit_summary.v1"
    assert cockpit_summary["status_label"] == "Blocked"
    assert cockpit_summary["explicit_blocking_gate_count"] == 1
    assert cockpit_summary["export_ready"] is False
    assert "Fix failing" in cockpit_summary["next_action"]

    comparison_status, comparison_summary = module._decision_status(
        baseline_path=Path("/tmp/baseline.json"),
        candidate_path=Path("/tmp/candidate.json"),
        artifact_rows=[{"status": "pass"}],
        metric_rows=[{"status": "pass"}],
        manifest_rows=[],
        evidence_bundle_comparison_summary={"blocking_count": 2},
    )
    assert comparison_status == "blocked"
    assert "Cross-run evidence comparison" in comparison_summary
    comparison_cockpit_summary = module._build_evidence_cockpit_summary(
        decision_status="promotable",
        decision_summary="All explicit gates passed against the selected baseline.",
        artifact_root=tmp_path / "artifact_root",
        baseline_path=tmp_path / "artifact_root" / "run_a" / "metrics.json",
        candidate_path=tmp_path / "artifact_root" / "run_b" / "metrics.json",
        metrics_files=[
            tmp_path / "artifact_root" / "run_a" / "metrics.json",
            tmp_path / "artifact_root" / "run_b" / "metrics.json",
        ],
        artifact_rows=[{"status": "pass"}],
        metric_rows=[{"status": "pass"}],
        run_manifest_rows=[],
        run_manifest_summary={"loaded": True, "path": str(bad_manifest)},
        imported_manifest_summary={"loaded_manifest_count": 0, "validated_manifest_count": 0},
        ci_artifact_harvest_summary={"gate_status": "not_configured"},
        manifest_index_summary={"release_count": 0, "manifest_count": 0},
        evidence_bundle_comparison_summary={"blocking_count": 2},
        reduce_artifact_rows=[{"status": "pass"}],
    )
    assert comparison_cockpit_summary["status_label"] == "Blocked"
    assert comparison_cockpit_summary["comparison_blocking_count"] == 2
    assert comparison_cockpit_summary["export_ready"] is False

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


def test_view_release_decision_helper_error_edges(tmp_path, monkeypatch) -> None:
    module = _load_release_helpers()

    broken_manifest_args = "--manifest 'unterminated"
    manifest_paths, manifest_dirs, parse_errors = module._parse_manifest_import_args(broken_manifest_args)
    assert manifest_paths == []
    assert manifest_dirs == []
    assert parse_errors[0]["source"] == "import args"
    missing_dir_rows, missing_dir_summary = module._build_manifest_import_rows(
        "--manifest-dir " + str(tmp_path / "missing-manifests")
    )
    assert missing_dir_rows[0]["evidence_status"] == "invalid"
    assert missing_dir_summary["invalid_manifest_count"] == 1
    equals_manifest, equals_dirs, equals_errors = module._parse_manifest_import_args(
        f"--manifest={tmp_path / 'a.json'} --manifest-dir={tmp_path}"
    )
    assert equals_manifest == [tmp_path / "a.json"]
    assert equals_dirs == [tmp_path]
    assert equals_errors == []

    bad_manifest = tmp_path / "bad" / "run_manifest.json"
    bad_manifest.parent.mkdir()
    bad_manifest.write_text("{broken", encoding="utf-8")
    invalid_rows, invalid_summary = module._build_manifest_import_rows(
        "--manifest " + str(bad_manifest)
    )
    assert invalid_rows[0]["evidence_status"] == "invalid"
    assert "Unable to load run manifest" in invalid_rows[0]["detail"]
    assert invalid_summary["attached_manifest_count"] == 1
    file_dir_rows, _file_dir_summary = module._build_manifest_import_rows(
        "--manifest-dir " + str(bad_manifest)
    )
    assert file_dir_rows[0]["provenance"].startswith("--manifest-dir")

    harvest_path = tmp_path / "ci_artifact_harvest.json"
    harvest_path.write_text(
        json.dumps(
            {
                "schema": "other",
                "run_status": "failed",
                "release": "not-a-dict",
                "summary": "not-a-dict",
                "artifacts": "not-a-list",
            }
        ),
        encoding="utf-8",
    )
    deduped_harvest_paths, harvest_parse_errors = module._parse_ci_artifact_harvest_import_args(
        f"--ci-artifact-harvest {harvest_path} --ci-artifact-harvest={harvest_path}"
    )
    assert deduped_harvest_paths == [harvest_path]
    assert harvest_parse_errors == []
    harvest_rows, harvest_summary = module._build_ci_artifact_harvest_rows(
        f"--ci-artifact-harvest {harvest_path}"
    )
    assert harvest_rows[0]["detail"] == "loaded without artifact rows"
    assert harvest_summary["loaded_harvest_count"] == 1
    assert module._ci_artifact_harvest_summary_counts(
        [{"loaded": True, "source": "x", "release_status": ""}],
        requested_count=1,
        parse_error_count=0,
    )["release_status_counts"] == {}

    comparison_rows = module._build_manifest_index_comparison_rows(
        {
            "releases": {
                "bad": "not-a-dict",
                "same": {"candidate_bundle_root": "bundle", "manifests": [{"path": "a"}]},
                "prior": {"candidate_bundle_root": "old", "manifests": ["not-a-dict"]},
            }
        },
        {"release_id": "current", "candidate_bundle_root": "bundle", "manifests": [{"path": "a"}]},
    )
    assert comparison_rows[0]["comparison_status"] == "new_evidence_not_validated"

    class _BrokenPath:
        def __init__(self, _value: object) -> None:
            pass

        def expanduser(self):
            return self

        def is_relative_to(self, _bundle_root: Path) -> bool:
            raise ValueError("bad path")

    with monkeypatch.context() as reduce_monkeypatch:
        reduce_monkeypatch.setattr(module, "Path", _BrokenPath)
        assert module._reduce_rows_for_bundle([{"path": "broken"}], tmp_path) == []

    signed_manifest = _write_first_proof_manifest(tmp_path / "signed")
    signature_path = Path(str(signed_manifest) + ".sig")
    signature_path.write_text("signature", encoding="utf-8")
    signed_rows, signed_summary = module._build_manifest_import_rows(
        "--manifest " + str(signed_manifest)
    )
    assert signed_rows[0]["attachment_status"] == "signed"
    assert signed_rows[0]["attachment_signature_path"] == str(signature_path)
    assert signed_summary["signed_attachment_count"] == 1
    assert module._manifest_attachment_status({"attachment": {"sha256": "abc"}}) == "provenance_tagged"

    original_file_metadata = module._file_metadata

    def fail_signature_metadata(path: Path):
        if path == signature_path:
            raise OSError("signature denied")
        return original_file_metadata(path)

    monkeypatch.setattr(module, "_file_metadata", fail_signature_metadata)
    assert module._manifest_signature_sidecar(signed_manifest) is None

    def fail_all_metadata(_path: Path):
        raise OSError("file denied")

    monkeypatch.setattr(module, "_file_metadata", fail_all_metadata)
    assert module._manifest_attachment_metadata(signed_manifest, "manual")["verification_status"] == "unverifiable"
    assert module._ci_artifact_harvest_attachment_metadata(signed_manifest, "manual")["verification_status"] == (
        "unverifiable"
    )
    monkeypatch.setattr(module, "_file_metadata", original_file_metadata)

    streamlit = SimpleNamespace(
        session_state={
            "release_decision_app_scope": "app-a:/tmp/app-a",
            **{key: "stale" for key in module.APP_SCOPED_SESSION_DEFAULT_KEYS},
        }
    )
    module._reset_app_scoped_session_defaults(
        streamlit,
        SimpleNamespace(app="app-b", active_app="/tmp/app-b"),
    )
    for key in module.APP_SCOPED_SESSION_DEFAULT_KEYS:
        assert key not in streamlit.session_state
    assert streamlit.session_state["release_decision_app_scope"] == "app-b:/tmp/app-b"

    ci_paths, ci_errors = module._parse_ci_artifact_harvest_import_args(
        "--ci-artifact-harvest --harvest=/tmp/ci_artifact_harvest.json ci_artifact_harvest.json"
    )
    assert ci_errors == [
        {"source": "--ci-artifact-harvest", "detail": "--ci-artifact-harvest requires a path value"}
    ]
    assert [path.name for path in ci_paths] == ["ci_artifact_harvest.json", "ci_artifact_harvest.json"]
    assert module._parse_ci_artifact_harvest_import_args("--harvest 'unterminated")[1][0]["source"] == (
        "import args"
    )
    ci_bad = tmp_path / "ci_artifact_harvest.json"
    ci_bad.write_text("[]", encoding="utf-8")
    ci_rows, ci_summary = module._build_ci_artifact_harvest_rows(
        "--ci-artifact-harvest " + str(ci_bad)
    )
    assert ci_rows[0]["harvest_status"] == "invalid"
    assert "must be a JSON object" in ci_rows[0]["detail"]
    assert ci_summary["gate_status"] == "fail"

    ci_empty = tmp_path / "ci-empty.json"
    ci_empty.write_text(
        json.dumps(
            {
                "schema": module.CI_ARTIFACT_HARVEST_SCHEMA,
                "run_status": "harvest_ready",
                "release": "bad",
                "summary": "bad",
                "artifacts": ["bad"],
            }
        ),
        encoding="utf-8",
    )
    empty_rows, empty_summary = module._build_ci_artifact_harvest_rows(
        "--harvest " + str(ci_empty)
    )
    assert empty_rows == []
    assert empty_summary["gate_status"] == "fail"

    invalid_index_path = tmp_path / "manifest_index.json"
    for payload, expected in (
        ("[]", "manifest index must be a JSON object"),
        (json.dumps({"schema": "wrong"}), "unsupported manifest index schema"),
        (json.dumps({"schema": module.MANIFEST_INDEX_SCHEMA, "releases": []}), "manifest index releases must be an object"),
    ):
        invalid_index_path.write_text(payload, encoding="utf-8")
        _index, summary = module._load_manifest_index(invalid_index_path)
        assert expected in summary["error"]

    mixed_index = {
        "schema": module.MANIFEST_INDEX_SCHEMA,
        "releases": {
            "bad": "not-a-release",
            "release-a": {"candidate_bundle_root": "bundle-a", "manifests": ["bad"]},
        },
    }
    assert module._manifest_index_rows(mixed_index) == []
    assert module._manifest_evidence_rank(None) == -1
    assert module._manifest_duration(None) is None
    assert module._best_manifest_record([]) is None

    assert module._classify_manifest_comparison(None, {"evidence_status": "validated"})[0] == (
        "missing_current_evidence"
    )
    assert module._classify_manifest_comparison({"evidence_status": "validated"}, None)[0] == (
        "newly_validated"
    )
    assert module._classify_manifest_comparison({"evidence_status": "failed"}, None)[0] == "failed"
    assert module._classify_manifest_comparison({"evidence_status": "invalid"}, None)[0] == (
        "new_evidence_not_validated"
    )
    assert module._classify_manifest_comparison(
        {"evidence_status": "invalid", "run_id": "new"},
        {"evidence_status": "validated", "run_id": "old"},
    )[0] == "regressed"
    assert module._classify_manifest_comparison(
        {"evidence_status": "failed", "run_id": "new"},
        {"evidence_status": "validated", "run_id": "old"},
    )[0] == "failed"
    assert module._classify_manifest_comparison(
        {"evidence_status": "validated", "run_id": "new"},
        {"evidence_status": "failed", "run_id": "old"},
    )[0] == "improved"
    assert module._classify_manifest_comparison(
        {"evidence_status": "validated", "run_id": "new", "duration_seconds": 3.0},
        {"evidence_status": "validated", "run_id": "old", "duration_seconds": 5.0},
    )[0] == "better"
    assert module._classify_manifest_comparison(
        {"evidence_status": "validated", "run_id": "new", "duration_seconds": 7.0},
        {"evidence_status": "validated", "run_id": "old", "duration_seconds": 5.0},
    )[0] == "slower"
    assert module._classify_manifest_comparison(
        {"evidence_status": "validated", "run_id": "new"},
        {"evidence_status": "validated", "run_id": "old"},
    )[0] == "stable"
    assert module._manifest_is_same_evidence(
        {"run_id": "same-run"},
        {"run_id": "same-run"},
    ) is True

    assert module._manifest_evidence_from_summary(
        {"loaded": True, "status": "pass", "error": "missing"},
        "missing.json",
    )["evidence_status"] == "missing"
    assert module._manifest_evidence_from_summary(
        {"loaded": False, "status": "pass", "error": "parse"},
        "bad.json",
    )["evidence_status"] == "invalid"
    assert module._selected_release_manifest_evidence(
        {"selected_run_manifest_summary": {"loaded": True, "status": "pass"}, "selected_run_manifest_path": "run.json"}
    )["evidence_status"] == "validated"
    assert module._selected_release_manifest_evidence({}) is None

    outside_row = {"path": object(), "status": "pass"}
    assert module._reduce_rows_for_bundle([{}, outside_row], tmp_path) == []
    inside_row = {"path": str(tmp_path / "bundle" / "reduce_summary_worker_0.json"), "status": "pass"}
    assert module._reduce_rows_for_bundle([inside_row], tmp_path / "bundle") == [inside_row]
    current_invalid = {"invalid_count": 1, "valid_count": 0, "reducers": []}
    target_valid = {"invalid_count": 0, "valid_count": 1, "reducers": ["a"]}
    assert module._compare_reduce_summaries(current_invalid, target_valid)[0] == "invalid_current"
    assert module._compare_reduce_summaries({"invalid_count": 0, "valid_count": 0, "reducers": []}, target_valid)[0] == (
        "missing_current"
    )
    assert module._compare_reduce_summaries({"invalid_count": 0, "valid_count": 2, "reducers": ["a"]}, target_valid)[0] == (
        "expanded"
    )
    assert module._compare_reduce_summaries({"invalid_count": 0, "valid_count": 1, "reducers": []}, {"invalid_count": 0, "valid_count": 2, "reducers": []})[0] == (
        "reduced"
    )
    assert module._compare_reduce_summaries({"invalid_count": 0, "valid_count": 1, "reducers": ["b"]}, target_valid)[0] == (
        "changed"
    )
    assert module._compare_reduce_summaries({"invalid_count": 0, "valid_count": 0, "reducers": []}, {"invalid_count": 0, "valid_count": 0, "reducers": []})[0] == (
        "not_available"
    )

    metrics_file = tmp_path / "metrics.json"
    metrics_file.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="Metrics payload"):
        module._load_metrics(metrics_file)
    assert module._relative_display_path(Path("/not/under/root"), tmp_path) == "/not/under/root"
    assert module._comma_joined(None) == ""
    assert module._comma_joined(["a", "b"]) == "a, b"
    assert module._comma_joined("x") == "x"
    assert module._metadata_subset({"a": "x", "b": True, "c": 1}) == {"a": "x", "c": 1}
    higher_rows = module._build_metric_rows({"accuracy": 0.8, "neutral": 1.0}, {"accuracy": 0.7, "neutral": 1.5}, 0)
    assert {row["metric"]: row["status"] for row in higher_rows} == {
        "accuracy": "fail",
        "neutral": "review",
    }
    artifact_rows = module._build_artifact_rows(tmp_path / "baseline", tmp_path / "candidate", ["*.csv"])
    assert artifact_rows[0]["status"] == "fail"
    invalid_manifest_file = tmp_path / "invalid-run-manifest.json"
    invalid_manifest_file.write_text("{broken", encoding="utf-8")
    invalid_gate_rows, invalid_gate_summary = module._build_run_manifest_gate_rows(invalid_manifest_file)
    assert invalid_gate_rows[0]["gate"] == "run_manifest_valid"
    assert invalid_gate_summary["error"]
    assert module._decision_status(
        baseline_path=tmp_path / "base.json",
        candidate_path=tmp_path / "candidate.json",
        artifact_rows=[],
        metric_rows=[{"status": "fail"}],
    )[0] == "blocked"
    assert module._decision_status(
        baseline_path=tmp_path / "base.json",
        candidate_path=tmp_path / "candidate.json",
        artifact_rows=[],
        metric_rows=[],
    )[0] == "needs_review"

    blocked_status, blocked_summary = module._decision_status(
        baseline_path=tmp_path / "base.json",
        candidate_path=tmp_path / "candidate.json",
        artifact_rows=[],
        metric_rows=[],
        ci_artifact_harvest_summary={"gate_status": "fail"},
    )
    assert blocked_status == "blocked"
    assert "CI artifact harvest" in blocked_summary

    missing_target_rows = module._evidence_target_rows(
        target_kind="baseline",
        target_release_id="base",
        target_bundle=tmp_path / "base",
        target_metrics_path=None,
        target_metrics_payload=None,
        target_manifest=None,
        candidate_bundle=tmp_path / "candidate",
        candidate_metrics_payload={},
        current_manifest={"evidence_status": "validated", "path_id": "first-proof"},
        required_patterns=[],
        reduce_artifact_rows=[],
        tolerance_pct=0,
    )
    assert any(row["status"] == "missing_target" for row in missing_target_rows)

    baseline_metrics = tmp_path / "baseline" / "metrics.json"
    candidate_metrics = tmp_path / "candidate" / "metrics.json"
    prior_bad_metrics = tmp_path / "prior" / "metrics.json"
    baseline_metrics.parent.mkdir()
    candidate_metrics.parent.mkdir()
    prior_bad_metrics.parent.mkdir()
    baseline_metrics.write_text('{"mae": 1.0}', encoding="utf-8")
    candidate_metrics.write_text('{"mae": 0.9}', encoding="utf-8")
    prior_bad_metrics.write_text("[]", encoding="utf-8")
    comparison_rows = module._build_evidence_bundle_comparison_rows(
        existing_index={
            "releases": {
                "same-current": {"candidate_bundle_root": str(candidate_metrics.parent)},
                "prior": {
                    "release_id": "prior",
                    "candidate_bundle_root": str(prior_bad_metrics.parent),
                    "candidate_metrics_file": str(prior_bad_metrics),
                },
            }
        },
        baseline_path=baseline_metrics,
        candidate_path=candidate_metrics,
        candidate_payload={"mae": 0.9},
        run_manifest_path=tmp_path / "run.json",
        run_manifest_summary={"loaded": True, "status": "pass"},
        current_release={
            "release_id": "current",
            "candidate_bundle_root": str(candidate_metrics.parent),
            "selected_run_manifest_summary": {"loaded": True, "status": "pass"},
            "selected_run_manifest_path": str(tmp_path / "run.json"),
        },
        required_patterns=[],
        reduce_artifact_rows=[],
        tolerance_pct=0,
    )
    assert any(row["target_kind"] == "prior_indexed" and row["status"] == "missing_target" for row in comparison_rows)

    class BrokenStatPath:
        def stat(self):
            raise OSError("stat denied")

        def as_posix(self):
            return "broken"

    assert module._sort_key_with_mtime(BrokenStatPath()) == (0, "broken")

    def raise_preview(_repo_root=None):
        raise RuntimeError("preview failed")

    monkeypatch.setattr(module, "_build_release_decision_connector_preview_state", raise_preview)
    captions: list[str] = []
    fallback = module._render_release_decision_connector_live_ui(SimpleNamespace(caption=captions.append))
    assert fallback["run_status"] == "unavailable"
    assert "preview failed" in captions[0]


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
    flight = next(row for row in rows if row["reducer"] == "flight_telemetry.trajectory-metrics.v1")
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
    export_root = tmp_path / "export" / "weather_forecast"
    baseline_root = export_root / "run_a"
    candidate_root = export_root / "run_b"
    _write_bundle(baseline_root, mae=1.1, rmse=1.2, mape=6.2)
    _write_bundle(candidate_root, mae=0.9, rmse=1.0, mape=5.9)
    _write_first_proof_manifest(tmp_path)

    env = SimpleNamespace(
        app="weather_forecast_project",
        target="weather_forecast",
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
