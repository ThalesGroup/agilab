from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from streamlit.testing.v1 import AppTest


def _make_env(tmp_path: Path, *, app_name: str, data_out: str) -> SimpleNamespace:
    settings_root = tmp_path / app_name
    settings_root.mkdir(parents=True, exist_ok=True)
    settings_file = settings_root / "app_settings.toml"
    settings_file.write_text(
        "[args]\n"
        "data_in = \"execution_playground/dataset\"\n"
        f"data_out = \"{data_out}\"\n"
        "files = \"*.csv\"\n"
        "nfile = 16\n"
        "n_partitions = 16\n"
        "rows_per_file = 100000\n"
        "n_groups = 32\n"
        "compute_passes = 32\n"
        "kernel_mode = \"typed_numeric\"\n"
        "output_format = \"csv\"\n"
        "seed = 42\n"
        "reset_target = false\n",
        encoding="utf-8",
    )
    return SimpleNamespace(
        app_settings_file=str(settings_file),
        humanize_validation_errors=lambda exc: [str(item) for item in exc.errors()],
    )


def test_execution_pandas_form_renders_and_persists_args(tmp_path: Path) -> None:
    env = _make_env(tmp_path, app_name="execution_pandas_project", data_out="execution_pandas/results")
    at = AppTest.from_file("src/agilab/apps/builtin/execution_pandas_project/src/app_args_form.py", default_timeout=20)
    at.session_state["env"] = env
    at.session_state["app_settings"] = {"args": {}, "cluster": {}}

    at.run()

    assert not at.exception
    assert at.text_input(key="execution_pandas_project:app_args_form:data_in").value == "execution_playground/dataset"
    assert at.text_input(key="execution_pandas_project:app_args_form:data_out").value == "execution_pandas/results"
    assert at.selectbox(key="execution_pandas_project:app_args_form:kernel_mode").value == "typed_numeric"

    at.number_input(key="execution_pandas_project:app_args_form:nfile").set_value(8)
    at.number_input(key="execution_pandas_project:app_args_form:rows_per_file").set_value(50000)
    at.selectbox(key="execution_pandas_project:app_args_form:kernel_mode").set_value("dataframe")
    at.selectbox(key="execution_pandas_project:app_args_form:output_format").set_value("parquet")
    at.run()

    assert not at.exception
    assert any("Saved to" in msg.value for msg in at.success)
    assert at.session_state["app_settings"]["args"]["nfile"] == 8
    assert at.session_state["app_settings"]["args"]["rows_per_file"] == 50000
    assert at.session_state["app_settings"]["args"]["kernel_mode"] == "dataframe"
    assert at.session_state["app_settings"]["args"]["output_format"] == "parquet"


def test_execution_polars_form_renders_and_persists_args(tmp_path: Path) -> None:
    env = _make_env(tmp_path, app_name="execution_polars_project", data_out="execution_polars/results")
    at = AppTest.from_file("src/agilab/apps/builtin/execution_polars_project/src/app_args_form.py", default_timeout=20)
    at.session_state["env"] = env
    at.session_state["app_settings"] = {"args": {}, "cluster": {}}

    at.run()

    assert not at.exception
    assert at.text_input(key="execution_polars_project:app_args_form:data_in").value == "execution_playground/dataset"
    assert at.text_input(key="execution_polars_project:app_args_form:data_out").value == "execution_polars/results"

    at.number_input(key="execution_polars_project:app_args_form:compute_passes").set_value(12)
    at.number_input(key="execution_polars_project:app_args_form:n_groups").set_value(9)
    at.checkbox(key="execution_polars_project:app_args_form:reset_target").set_value(True)
    at.run()

    assert not at.exception
    assert any("Saved to" in msg.value for msg in at.success)
    assert at.session_state["app_settings"]["args"]["compute_passes"] == 12
    assert at.session_state["app_settings"]["args"]["n_groups"] == 9
    assert at.session_state["app_settings"]["args"]["reset_target"] is True
