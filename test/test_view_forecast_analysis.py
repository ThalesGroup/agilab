from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


PAGE_PATH = (
    "src/agilab/apps-pages/view_forecast_analysis/src/view_forecast_analysis/view_forecast_analysis.py"
)


def test_view_forecast_analysis_renders_exported_artifacts(tmp_path, monkeypatch) -> None:
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir()
    project_dir = apps_dir / "meteo_forecast_project"
    (project_dir / "src" / "meteo_forecast").mkdir(parents=True)
    (project_dir / "pyproject.toml").write_text("[project]\nname='meteo-forecast-project'\n", encoding="utf-8")
    (project_dir / "src" / "app_settings.toml").write_text("[args]\n", encoding="utf-8")
    (project_dir / "src" / "meteo_forecast" / "__init__.py").write_text("", encoding="utf-8")

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
            }
        ),
        encoding="utf-8",
    )
    (artifact_dir / "forecast_predictions.csv").write_text(
        "date,y_true,y_pred,split\n"
        "2025-04-01,16.1,15.7,backtest\n"
        "2025-04-02,14.8,15.3,backtest\n",
        encoding="utf-8",
    )

    argv = [Path(PAGE_PATH).name, "--active-app", str(project_dir)]
    with patch.object(sys, "argv", argv):
        monkeypatch.setenv("AGI_EXPORT_DIR", str(tmp_path / "export"))
        monkeypatch.setenv("AGI_LOCAL_SHARE", str(tmp_path / "localshare"))
        monkeypatch.setenv("AGI_CLUSTER_SHARE", str(tmp_path / "clustershare"))
        monkeypatch.setenv("OPENAI_API_KEY", "dummy")
        monkeypatch.setenv("IS_SOURCE_ENV", "1")
        at = AppTest.from_file(PAGE_PATH, default_timeout=20)
        at.run()

    assert not at.exception
    assert any(title.value == "Forecast analysis" for title in at.title)
    assert any(metric.label == "MAE" for metric in at.metric)
    assert len(at.dataframe) == 1
