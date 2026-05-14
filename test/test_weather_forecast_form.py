from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from streamlit.testing.v1 import AppTest


APP_FORM = "src/agilab/apps/builtin/weather_forecast_project/src/app_args_form.py"


def _make_env(tmp_path: Path) -> SimpleNamespace:
    share_root = tmp_path / "share"
    share_root.mkdir(parents=True, exist_ok=True)
    export_root = tmp_path / "export"
    export_root.mkdir(parents=True, exist_ok=True)
    settings_root = tmp_path / "app"
    settings_root.mkdir(parents=True, exist_ok=True)
    settings_file = settings_root / "app_settings.toml"
    settings_file.write_text(
        "[args]\n"
        "data_in = \"weather_forecast/dataset\"\n"
        "data_out = \"weather_forecast/results\"\n"
        "files = \"*.csv\"\n"
        "nfile = 1\n"
        "station = \"Paris-Montsouris\"\n"
        "target_column = \"tmax_c\"\n"
        "lags = 7\n"
        "horizon_days = 7\n"
        "validation_days = 9\n"
        "n_estimators = 100\n"
        "random_state = 42\n"
        "reset_target = false\n",
        encoding="utf-8",
    )

    def _resolve_share_path(path):
        candidate = Path(path)
        return candidate if candidate.is_absolute() else share_root / candidate

    return SimpleNamespace(
        app_settings_file=str(settings_file),
        resolve_share_path=_resolve_share_path,
        share_root_path=lambda: share_root,
        AGILAB_EXPORT_ABS=export_root,
        target="meteo_forecast",
        humanize_validation_errors=lambda exc: [str(item) for item in exc.errors()],
    )


def test_meteo_forecast_form_renders_and_persists_args(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    at = AppTest.from_file(APP_FORM, default_timeout=20)
    at.session_state["env"] = env
    at.session_state["app_settings"] = {"args": {}, "cluster": {}, "pages": {}}

    at.run()

    assert not at.exception
    captions = [element.value for element in at.caption]
    assert any(
        "This app turns the notebook migration pilot into a reproducible AGILAB workflow."
        in value
        for value in captions
    )
    assert at.text_input(key="weather_forecast_project:app_args_form:station").value == "Paris-Montsouris"
    assert at.selectbox(key="weather_forecast_project:app_args_form:target_column").value == "tmax_c"

    at.text_input(key="weather_forecast_project:app_args_form:station").set_value("Paris-Montsouris")
    at.number_input(key="weather_forecast_project:app_args_form:lags").set_value(8)
    at.run()

    assert not at.exception
    success_messages = [msg.value for msg in at.success]
    assert any("Saved to" in message for message in success_messages)
