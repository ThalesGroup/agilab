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


def _run_release_page(tmp_path: Path, monkeypatch, project_dir: Path) -> AppTest:
    argv = [Path(PAGE_PATH).name, "--active-app", str(project_dir)]
    with patch.object(sys, "argv", argv):
        monkeypatch.setenv("AGI_EXPORT_DIR", str(tmp_path / "export"))
        monkeypatch.setenv("AGI_LOCAL_SHARE", str(tmp_path / "localshare"))
        monkeypatch.setenv("AGI_CLUSTER_SHARE", str(tmp_path / "clustershare"))
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


def test_view_release_decision_blocks_candidate_with_missing_artifact(tmp_path, monkeypatch) -> None:
    project_dir = _create_forecast_project(tmp_path)
    export_root = tmp_path / "export" / "meteo_forecast"
    baseline_root = export_root / "run_a"
    candidate_root = export_root / "run_b"
    _write_bundle(baseline_root, mae=0.91, rmse=1.01, mape=5.80)
    _write_bundle(candidate_root, mae=0.81, rmse=0.97, mape=5.42, with_predictions=False)

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
    invalid_path = artifact_root / "run_b" / "reduce_summary_worker_1.json"
    _write_reduce_artifact(valid_path, engine="polars")
    invalid_path.parent.mkdir(parents=True, exist_ok=True)
    invalid_path.write_text("{broken", encoding="utf-8")

    rows = module._build_reduce_artifact_rows(artifact_root)

    valid = next(row for row in rows if row["status"] == "pass")
    invalid = next(row for row in rows if row["status"] == "invalid")
    assert valid["artifact"] == "run_a/reduce_summary_worker_0.json"
    assert valid["reducer"] == "execution_polars.weighted-score.v1"
    assert valid["partial_count"] == 1
    assert valid["source_file_count"] == 2
    assert valid["row_count"] == 48
    assert valid["engines"] == "polars"
    assert valid["execution_models"] == "threads"
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

    env = SimpleNamespace(
        app="meteo_forecast_project",
        target="meteo_forecast",
        AGILAB_EXPORT_ABS=str(tmp_path / "export"),
        st_resources=tmp_path,
    )
    argv = [Path(PAGE_PATH).name, "--active-app", str(project_dir)]
    with patch.object(sys, "argv", argv):
        monkeypatch.setenv("AGI_EXPORT_DIR", str(tmp_path / "export"))
        monkeypatch.setenv("AGI_LOCAL_SHARE", str(tmp_path / "localshare"))
        monkeypatch.setenv("AGI_CLUSTER_SHARE", str(tmp_path / "clustershare"))
        monkeypatch.setenv("OPENAI_API_KEY", "dummy")
        monkeypatch.setenv("IS_SOURCE_ENV", "1")
        at = AppTest.from_file(PAGE_PATH, default_timeout=20)
        at.session_state["env"] = env
        at.run()

    assert not at.exception
