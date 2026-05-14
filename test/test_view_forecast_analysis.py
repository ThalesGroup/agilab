from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest


PAGE_PATH = (
    "src/agilab/apps-pages/view_forecast_analysis/src/view_forecast_analysis/view_forecast_analysis.py"
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


def _run_forecast_page(
    tmp_path: Path,
    monkeypatch,
    project_dir: Path,
    *,
    default_timeout: int = 20,
) -> AppTest:
    argv = [Path(PAGE_PATH).name, "--active-app", str(project_dir)]
    with patch.object(sys, "argv", argv):
        monkeypatch.setenv("AGI_EXPORT_DIR", str(tmp_path / "export"))
        monkeypatch.setenv("AGI_LOCAL_SHARE", str(tmp_path / "localshare"))
        monkeypatch.setenv("AGI_CLUSTER_SHARE", str(tmp_path / "clustershare"))
        monkeypatch.setenv("OPENAI_API_KEY", "dummy")
        monkeypatch.setenv("IS_SOURCE_ENV", "1")
        at = AppTest.from_file(PAGE_PATH, default_timeout=default_timeout)
        at.run()
    return at


def _load_forecast_helpers() -> ModuleType:
    source = Path(PAGE_PATH).read_text(encoding="utf-8")
    prefix = source.split('\nst.set_page_config(layout="wide")\n', 1)[0]
    module = ModuleType("view_forecast_analysis_test_module")
    module.__file__ = str(Path(PAGE_PATH).resolve())
    module.__package__ = None
    exec(compile(prefix, str(Path(PAGE_PATH)), "exec"), module.__dict__)
    return module


def test_view_forecast_analysis_renders_exported_artifacts(tmp_path, monkeypatch) -> None:
    project_dir = _create_forecast_project(tmp_path)

    artifact_dir = tmp_path / "export" / "meteo_forecast" / "forecast_analysis"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "forecast_metrics.json").write_text(
        json.dumps(
            {
                "scenario": "French daily weather forecasting pilot",
                "station": "Paris-Montsouris",
                "target": "tmax_c",
                "model_name": "ForecasterRecursive(RandomForestRegressor)",
                "horizon_days": 7,
                "mae": 0.81,
                "rmse": 0.97,
                "mape": 5.42,
                "notes": "Recursive forecasting stays reproducible through exported artifacts.",
            }
        ),
        encoding="utf-8",
    )
    (artifact_dir / "forecast_predictions.csv").write_text(
        "ds,y_true,y_pred,split\n"
        "2025-04-01,16.1,15.7,backtest\n"
        "2025-04-02,14.8,15.3,backtest\n",
        encoding="utf-8",
    )

    at = _run_forecast_page(tmp_path, monkeypatch, project_dir, default_timeout=60)

    assert not at.exception
    assert any(title.value == "Forecast analysis" for title in at.title)
    assert any(metric.label == "MAE" for metric in at.metric)
    assert len(at.dataframe) == 1
    assert any(subheader.value == "Notes" for subheader in at.subheader)


def test_view_forecast_analysis_warns_when_artifact_directory_is_missing(tmp_path, monkeypatch) -> None:
    project_dir = _create_forecast_project(tmp_path)

    at = _run_forecast_page(tmp_path, monkeypatch, project_dir)

    assert not at.exception
    assert any("Artifact directory does not exist yet" in warning.value for warning in at.warning)


def test_view_forecast_analysis_warns_when_predictions_are_missing(tmp_path, monkeypatch) -> None:
    project_dir = _create_forecast_project(tmp_path)
    artifact_dir = tmp_path / "export" / "meteo_forecast" / "forecast_analysis"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "forecast_metrics.json").write_text(
        json.dumps({"scenario": "pilot", "mae": 0.5}),
        encoding="utf-8",
    )

    at = _run_forecast_page(tmp_path, monkeypatch, project_dir)

    assert not at.exception
    assert any("No predictions file found" in warning.value for warning in at.warning)


def test_view_forecast_analysis_helper_branches(monkeypatch, tmp_path) -> None:
    module = _load_forecast_helpers()

    repo_root = tmp_path / "repo"
    src_root = repo_root / "src"
    module_path = src_root / "agilab" / "apps-pages" / "view_forecast_analysis" / "src" / "view_forecast_analysis" / "view_forecast_analysis.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text("# stub\n", encoding="utf-8")
    monkeypatch.setattr(module, "__file__", str(module_path))
    monkeypatch.setattr(module.sys, "path", [])
    module._ensure_repo_on_path()
    assert str(src_root) in module.sys.path
    assert str(repo_root) in module.sys.path

    errors: list[str] = []
    def stop_now():
        raise RuntimeError("stop")
    module.st = SimpleNamespace(error=errors.append, stop=stop_now)
    monkeypatch.setattr(module.sys, "argv", [Path(PAGE_PATH).name, "--active-app", str(tmp_path / "missing_app")])
    with pytest.raises(RuntimeError, match="stop"):
        module._resolve_active_app()
    assert any("Provided --active-app path not found" in message for message in errors)

    assert module._discover_files(tmp_path / "missing", "[") == []
    assert module._safe_float(object()) is None

    predictions_path = tmp_path / "predictions.csv"
    predictions_path.write_text("ds,y_true,y_pred\n2025-01-01,1.0,1.1\n", encoding="utf-8")
    loaded = module._load_predictions(predictions_path)
    assert "date" in loaded.columns


def test_view_forecast_analysis_covers_discover_exception_and_existing_env(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_forecast_helpers()
    broken_base = SimpleNamespace(glob=lambda _pattern: (_ for _ in ()).throw(RuntimeError("broken glob")))
    assert module._discover_files(broken_base, "*.json") == []

    project_dir = _create_forecast_project(tmp_path)
    env = SimpleNamespace(
        app="weather_forecast_project",
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


def test_view_forecast_analysis_warns_when_metrics_are_missing(tmp_path, monkeypatch) -> None:
    project_dir = _create_forecast_project(tmp_path)
    artifact_dir = tmp_path / "export" / "meteo_forecast" / "forecast_analysis"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "forecast_predictions.csv").write_text(
        "date,y_true,y_pred\n2025-01-01,1.0,1.1\n",
        encoding="utf-8",
    )

    at = _run_forecast_page(tmp_path, monkeypatch, project_dir)

    assert not at.exception
    assert any("No metrics file found" in warning.value for warning in at.warning)
