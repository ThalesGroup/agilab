from __future__ import annotations

from pathlib import Path
import shutil
import sys
from types import SimpleNamespace
import tomllib

import pytest
from streamlit.testing.v1 import AppTest


APP_ARGS_FORM_ROOT = Path("src/agilab")
APP_ARGS_FORM_PATTERNS = (
    "apps/builtin/*_project/src/app_args_form.py",
    "apps/templates/*_template/src/app_args_form.py",
    "lib/agi-app-*/src/*/project/*_project/src/app_args_form.py",
)

PACKAGED_FORM_PAIRS = (
    (
        Path("src/agilab/apps/builtin/flight_telemetry_project/src/app_args_form.py"),
        Path(
            "src/agilab/lib/agi-app-flight-telemetry/src/agi_app_flight_telemetry/"
            "project/flight_telemetry_project/src/app_args_form.py"
        ),
    ),
    (
        Path("src/agilab/apps/builtin/mission_decision_project/src/app_args_form.py"),
        Path(
            "src/agilab/lib/agi-app-mission-decision/src/agi_app_mission_decision/"
            "project/mission_decision_project/src/app_args_form.py"
        ),
    ),
    (
        Path("src/agilab/apps/builtin/pytorch_playground_project/src/app_args_form.py"),
        Path(
            "src/agilab/lib/agi-app-pytorch-playground/src/agi_app_pytorch_playground/"
            "project/pytorch_playground_project/src/app_args_form.py"
        ),
    ),
    (
        Path("src/agilab/apps/builtin/uav_relay_queue_project/src/app_args_form.py"),
        Path(
            "src/agilab/lib/agi-app-uav-relay-queue/src/agi_app_uav_relay_queue/"
            "project/uav_relay_queue_project/src/app_args_form.py"
        ),
    ),
    (
        Path("src/agilab/apps/builtin/weather_forecast_project/src/app_args_form.py"),
        Path(
            "src/agilab/lib/agi-app-weather-forecast/src/agi_app_weather_forecast/"
            "project/weather_forecast_project/src/app_args_form.py"
        ),
    ),
)


class _BuiltinFormEnv(SimpleNamespace):
    def share_root_path(self):
        return self.share_root

    def resolve_share_path(self, value):
        path = Path(value)
        if path.is_absolute():
            return path
        return self.share_root / path

    @staticmethod
    def humanize_validation_errors(exc):
        return [str(item) for item in exc.errors()]


def _app_args_forms() -> list[Path]:
    paths: set[Path] = set()
    for pattern in APP_ARGS_FORM_PATTERNS:
        paths.update(APP_ARGS_FORM_ROOT.glob(pattern))
    return sorted(paths)


def _builtin_app_args_forms() -> list[Path]:
    return sorted(Path("src/agilab/apps/builtin").glob("*_project/src/app_args_form.py"))


def _app_name_from_form(form_path: Path) -> str:
    return form_path.parent.parent.name


def _seed_settings_for_form(form_path: Path, tmp_path: Path) -> Path:
    app_name = _app_name_from_form(form_path)
    settings_root = tmp_path / app_name
    settings_root.mkdir(parents=True, exist_ok=True)
    settings_file = settings_root / "app_settings.toml"
    source_settings = form_path.parent / "app_settings.toml"
    if source_settings.is_file():
        shutil.copyfile(source_settings, settings_file)
    else:
        settings_file.write_text("[args]\n", encoding="utf-8")
    return settings_file


def _clear_form_package_modules(form_path: Path) -> None:
    form_source = str(form_path.parent.resolve())
    sys.path[:] = [
        item
        for item in sys.path
        if str(Path(item or ".").resolve()) != form_source
    ]
    sys.path.insert(0, form_source)
    package_names = [
        path.name
        for path in sorted(form_path.parent.iterdir(), key=lambda item: item.name)
        if path.is_dir() and (path / "__init__.py").is_file()
    ]
    for package_name in package_names:
        for module_name in list(sys.modules):
            if module_name == package_name or module_name.startswith(f"{package_name}."):
                sys.modules.pop(module_name, None)


def test_all_app_args_form_files_are_non_empty() -> None:
    empty_forms = [str(path) for path in _app_args_forms() if not path.read_text(encoding="utf-8").strip()]
    assert empty_forms == []


def test_app_args_form_environment_wording_is_normalized() -> None:
    offenders = [
        str(path)
        for path in _app_args_forms()
        if "AGILab environment" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_template_forms_accept_public_and_private_env_session_keys() -> None:
    template_forms = sorted(Path("src/agilab/apps/templates").glob("*_template/src/app_args_form.py"))
    assert template_forms
    for path in template_forms:
        source = path.read_text(encoding="utf-8")
        assert 'st.session_state.get("env") or st.session_state.get("_env")' in source


def test_packaged_app_args_forms_match_builtin_sources() -> None:
    for source_path, packaged_path in PACKAGED_FORM_PAIRS:
        assert source_path.read_text(encoding="utf-8") == packaged_path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "form_path",
    _builtin_app_args_forms(),
    ids=lambda path: _app_name_from_form(path),
)
def test_builtin_app_args_form_renders_without_streamlit_exception(
    form_path: Path,
    tmp_path: Path,
) -> None:
    app_name = _app_name_from_form(form_path)
    settings_file = _seed_settings_for_form(form_path, tmp_path)
    env = _BuiltinFormEnv(
        AGILAB_EXPORT_ABS=str(tmp_path / "export"),
        active_app=str(form_path.parent.parent),
        app=app_name,
        app_settings_file=str(settings_file),
        apps_path=str(form_path.parents[2]),
        envars={},
        share_root=tmp_path / "share",
        target=app_name,
    )

    _clear_form_package_modules(form_path)
    at = AppTest.from_file(str(form_path), default_timeout=30)
    at.session_state["env"] = env
    at.session_state["_env"] = env
    at.session_state["app_settings"] = {"args": {}, "cluster": {}}

    at.run()

    assert not at.exception


def test_flight_app_args_form_repairs_foreign_workspace_args(tmp_path: Path) -> None:
    form_path = Path("src/agilab/apps/builtin/flight_telemetry_project/src/app_args_form.py")
    settings_file = tmp_path / "flight_telemetry_project" / "app_settings.toml"
    settings_file.parent.mkdir(parents=True)
    settings_file.write_text(
        "\n".join(
            (
                "[cluster]",
                "cluster_enabled = true",
                "",
                "[args]",
                'data_out = "pytorch_playground/evidence"',
                'dataset = "circles"',
                "sample_count = 320",
                "noise = 0.08",
                'hidden_layers = "12,12"',
                "learning_rate = 0.035",
                "epochs = 90",
            )
        ),
        encoding="utf-8",
    )
    env = _BuiltinFormEnv(
        AGILAB_EXPORT_ABS=str(tmp_path / "export"),
        active_app=str(form_path.parent.parent),
        app="flight_telemetry_project",
        app_settings_file=str(settings_file),
        apps_path=str(form_path.parents[2]),
        envars={},
        share_root=tmp_path / "share",
        target="flight_telemetry_project",
    )

    _clear_form_package_modules(form_path)
    at = AppTest.from_file(str(form_path), default_timeout=30)
    at.session_state["env"] = env
    at.session_state["_env"] = env
    at.session_state["app_settings"] = {"args": {}, "cluster": {}}

    at.run()

    assert not at.exception
    warning_text = "\n".join(str(message.value) for message in at.warning)
    assert "Unable to load Flight args" not in warning_text
    assert any("Reset incompatible Flight args" in str(message.value) for message in at.info)
    with settings_file.open("rb") as stream:
        persisted = tomllib.load(stream)
    assert persisted["cluster"]["cluster_enabled"] is True
    assert persisted["args"]["data_source"] == "file"
    assert persisted["args"]["data_in"] == "flight_telemetry/dataset"
    assert persisted["args"]["data_out"] == "flight_telemetry/dataframe"
    assert "dataset" not in persisted["args"]
    assert "hidden_layers" not in persisted["args"]


def _make_builtin_env(form_path: Path, settings_file: Path, tmp_path: Path) -> _BuiltinFormEnv:
    app_name = _app_name_from_form(form_path)
    return _BuiltinFormEnv(
        AGILAB_EXPORT_ABS=str(tmp_path / "export"),
        active_app=str(form_path.parent.parent),
        app=app_name,
        app_settings_file=str(settings_file),
        apps_path=str(form_path.parents[2]),
        envars={},
        share_root=tmp_path / "share",
        target=app_name,
    )


def test_flight_app_args_form_reports_invalid_date_range_without_saving(tmp_path: Path) -> None:
    import datetime as _dt

    form_path = Path("src/agilab/apps/builtin/flight_telemetry_project/src/app_args_form.py")
    settings_file = _seed_settings_for_form(form_path, tmp_path)
    env = _make_builtin_env(form_path, settings_file, tmp_path)

    _clear_form_package_modules(form_path)
    at = AppTest.from_file(str(form_path), default_timeout=30)
    at.session_state["env"] = env
    at.session_state["_env"] = env
    at.session_state["app_settings"] = {"args": {}, "cluster": {}}
    at.run()
    assert not at.exception

    before = settings_file.read_bytes()
    at.date_input(key="flight_telemetry_project:app_args_form:datemin").set_value(_dt.date(2021, 6, 1))
    at.date_input(key="flight_telemetry_project:app_args_form:datemax").set_value(_dt.date(2020, 6, 1))
    at.run()

    assert not at.exception
    errors = "\n".join(str(message.value) for message in at.error)
    assert "must be on or before" in errors
    assert settings_file.read_bytes() == before
    assert not any("Saved to" in str(message.value) for message in at.success)


def test_flight_app_args_form_reseeds_widgets_after_external_settings_change(tmp_path: Path) -> None:
    form_path = Path("src/agilab/apps/builtin/flight_telemetry_project/src/app_args_form.py")
    settings_file = _seed_settings_for_form(form_path, tmp_path)
    env = _make_builtin_env(form_path, settings_file, tmp_path)

    _clear_form_package_modules(form_path)
    at = AppTest.from_file(str(form_path), default_timeout=30)
    at.session_state["env"] = env
    at.session_state["_env"] = env
    at.session_state["app_settings"] = {"args": {}, "cluster": {}}
    at.run()
    assert not at.exception

    # A user edit followed by a rerun keeps the widget value (no spurious reseed).
    at.text_input(key="flight_telemetry_project:app_args_form:files").set_value("*.parquet")
    at.run()
    assert not at.exception
    at.run()
    assert at.text_input(key="flight_telemetry_project:app_args_form:files").value == "*.parquet"

    # An external [args] edit (project switch, generic editor) reseeds widget state.
    content = settings_file.read_text(encoding="utf-8")
    settings_file.write_text(content.replace('files = "*.parquet"', 'files = "*.csv"'), encoding="utf-8")
    at.run()
    assert not at.exception
    assert at.text_input(key="flight_telemetry_project:app_args_form:files").value == "*.csv"


def test_tescia_app_args_form_reseeds_widgets_after_external_settings_change(tmp_path: Path) -> None:
    form_path = Path("src/agilab/apps/builtin/tescia_diagnostic_project/src/app_args_form.py")
    settings_file = _seed_settings_for_form(form_path, tmp_path)
    env = _make_builtin_env(form_path, settings_file, tmp_path)

    _clear_form_package_modules(form_path)
    at = AppTest.from_file(str(form_path), default_timeout=30)
    at.session_state["env"] = env
    at.session_state["_env"] = env
    at.session_state["app_settings"] = {"args": {}, "cluster": {}}
    at.run()
    assert not at.exception
    assert at.text_input(key="tescia_diagnostic_project:app_args_form:files").value == "*.json"

    content = settings_file.read_text(encoding="utf-8")
    settings_file.write_text(content.replace('files = "*.json"', 'files = "case_*.json"'), encoding="utf-8")
    at.run()
    assert not at.exception
    assert at.text_input(key="tescia_diagnostic_project:app_args_form:files").value == "case_*.json"


def test_pytorch_playground_form_reseeds_widgets_after_external_settings_change(tmp_path: Path) -> None:
    form_path = Path("src/agilab/apps/builtin/pytorch_playground_project/src/app_args_form.py")
    settings_file = _seed_settings_for_form(form_path, tmp_path)
    env = _make_builtin_env(form_path, settings_file, tmp_path)
    dataset_key = f"pytorch_playground_args:{env.active_app}:dataset"

    _clear_form_package_modules(form_path)
    at = AppTest.from_file(str(form_path), default_timeout=30)
    at.session_state["env"] = env
    at.session_state["_env"] = env
    at.session_state["app_settings"] = {"args": {}, "cluster": {}}
    at.run()
    assert not at.exception
    assert at.selectbox(key=dataset_key).value == "circles"

    # Simulate a project switch back: the page reloads app_settings from disk.
    content = settings_file.read_text(encoding="utf-8")
    settings_file.write_text(content.replace('dataset = "circles"', 'dataset = "spiral"'), encoding="utf-8")
    at.session_state["app_settings"] = None
    at.session_state["is_args_from_ui"] = False
    at.run()
    assert not at.exception
    assert at.selectbox(key=dataset_key).value == "spiral"


def test_minimal_app_app_args_form_renders_and_persists_args(tmp_path: Path) -> None:
    settings_file = tmp_path / "minimal_app_project" / "app_settings.toml"
    settings_file.parent.mkdir()
    settings_file.write_text("[args]\n", encoding="utf-8")
    env = _BuiltinFormEnv(
        app_settings_file=str(settings_file),
        share_root=tmp_path / "share",
    )

    at = AppTest.from_file(
        "src/agilab/apps/builtin/minimal_app_project/src/app_args_form.py",
        default_timeout=20,
    )
    at.session_state["env"] = env
    at.session_state["app_settings"] = {"args": {}, "cluster": {}}

    at.run()

    assert not at.exception
    assert at.text_input(key="minimal_app_project:app_args_form:data_in").value == "minimal_app/dataset"
    assert at.text_input(key="minimal_app_project:app_args_form:data_out").value == "minimal_app/dataframe"
    assert at.text_input(key="minimal_app_project:app_args_form:files").value == "*"

    at.text_input(key="minimal_app_project:app_args_form:files").set_value("*.csv")
    at.number_input(key="minimal_app_project:app_args_form:nfile").set_value(3)
    at.number_input(key="minimal_app_project:app_args_form:nskip").set_value(2)
    at.checkbox(key="minimal_app_project:app_args_form:reset_target").set_value(True)
    at.run()

    assert not at.exception
    assert any("Saved to" in message.value for message in at.success)
    with settings_file.open("rb") as stream:
        persisted = tomllib.load(stream)
    assert persisted["args"]["files"] == "*.csv"
    assert persisted["args"]["nfile"] == 3
    assert persisted["args"]["nskip"] == 2
    assert persisted["args"]["reset_target"] is True
    assert at.session_state["app_settings"]["args"]["files"] == "*.csv"


def test_minimal_app_form_reseeds_widgets_when_settings_change_on_disk(tmp_path: Path) -> None:
    settings_file = tmp_path / "minimal_app_project" / "app_settings.toml"
    settings_file.parent.mkdir()
    settings_file.write_text('[args]\nfiles = "*.csv"\nnfile = 2\n', encoding="utf-8")
    env = _BuiltinFormEnv(
        app_settings_file=str(settings_file),
        share_root=tmp_path / "share",
    )

    at = AppTest.from_file(
        "src/agilab/apps/builtin/minimal_app_project/src/app_args_form.py",
        default_timeout=20,
    )
    at.session_state["env"] = env
    at.session_state["app_settings"] = {"args": {}, "cluster": {}}

    at.run()
    assert not at.exception
    assert at.text_input(key="minimal_app_project:app_args_form:files").value == "*.csv"
    assert at.number_input(key="minimal_app_project:app_args_form:nfile").value == 2

    # Simulate an external edit (generic ORCHESTRATE editor / manual TOML change).
    settings_file.write_text('[args]\nfiles = "*.parquet"\nnfile = 5\n', encoding="utf-8")
    at.run()

    assert not at.exception
    assert at.text_input(key="minimal_app_project:app_args_form:files").value == "*.parquet"
    assert at.number_input(key="minimal_app_project:app_args_form:nfile").value == 5


def test_r_runtime_bridge_form_reports_actionable_x_parse_error(tmp_path: Path) -> None:
    form_path = Path("src/agilab/apps/builtin/r_runtime_bridge_project/src/app_args_form.py")
    settings_file = _seed_settings_for_form(form_path, tmp_path)
    env = _BuiltinFormEnv(
        AGILAB_EXPORT_ABS=str(tmp_path / "export"),
        app="r_runtime_bridge_project",
        app_settings_file=str(settings_file),
        envars={},
        share_root=tmp_path / "share",
        target="r_runtime_bridge_project",
    )

    _clear_form_package_modules(form_path)
    at = AppTest.from_file(str(form_path), default_timeout=30)
    at.session_state["env"] = env
    at.session_state["_env"] = env
    at.session_state["app_settings"] = {"args": {}, "cluster": {}}

    at.run()
    assert not at.exception

    at.text_input(key="r_runtime_bridge_project:app_args_form:x").set_value("1, oops, 3")
    at.run()

    assert not at.exception
    assert any("Invalid R Runtime Bridge parameters" in str(item.value) for item in at.error)
    markdown_text = "\n".join(str(item.value) for item in at.markdown)
    assert "comma-separated list of numbers" in markdown_text
