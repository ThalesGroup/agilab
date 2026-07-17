from pathlib import Path

import pytest

import agi_env.project.app_settings_schema as schema_module
from agi_env.project.app_settings_schema import (
    AppSettingsValidation,
    log_app_settings_validation,
    validate_app_settings,
    validate_app_settings_file,
)

REPO_ROOT = Path(__file__).resolve().parents[5]
SWEEP_EXCLUDED_PARTS = {".venv", "build", "dist", "__pycache__", ".git", "node_modules"}


def test_empty_payload_is_valid() -> None:
    validation = validate_app_settings({})
    assert validation.ok
    assert validation.warnings == ()


def test_non_table_payload_is_refused() -> None:
    validation = validate_app_settings(["not", "a", "table"])
    assert not validation.ok
    assert "must be a TOML table" in validation.errors[0]


@pytest.mark.parametrize(
    "section", ["__meta__", "args", "cluster", "pages", "app_surface"]
)
def test_non_table_core_sections_are_refused(section: str) -> None:
    validation = validate_app_settings({section: "oops"})
    assert [error for error in validation.errors if error.startswith(f"{section}:")]


def test_meta_version_contract_is_enforced() -> None:
    assert validate_app_settings({"__meta__": {"version": 1}}).ok
    assert validate_app_settings({"__meta__": {"version": "1"}}).ok
    assert validate_app_settings({"__meta__": {"owner": "app"}}).ok
    too_new = validate_app_settings({"__meta__": {"version": 2}})
    assert not too_new.ok
    not_numeric = validate_app_settings({"__meta__": {"version": "next"}})
    assert not not_numeric.ok


def test_args_stages_conflict_is_refused_and_legacy_key_warns() -> None:
    conflict = validate_app_settings({"args": {"args": [], "stages": []}})
    assert not conflict.ok
    assert "args.stages" in conflict.errors[0]

    legacy = validate_app_settings({"args": {"args": [{"name": "stage"}]}})
    assert legacy.ok
    assert any("legacy" in warning for warning in legacy.warnings)

    assert validate_app_settings({"args": {}}).ok


def test_cluster_verbose_shapes_warn_but_never_error() -> None:
    as_bool = validate_app_settings({"cluster": {"verbose": True}})
    assert as_bool.ok
    assert any("cluster.verbose" in warning for warning in as_bool.warnings)

    out_of_range = validate_app_settings({"cluster": {"verbose": 9}})
    assert out_of_range.ok
    assert any("outside 0-3" in warning for warning in out_of_range.warnings)

    assert validate_app_settings({"cluster": {"verbose": 2}}).warnings == ()


def test_cluster_flag_and_scheduler_types_warn() -> None:
    validation = validate_app_settings(
        {"cluster": {"cluster_enabled": "yes", "scheduler": 8786}}
    )
    assert validation.ok
    assert any("cluster.cluster_enabled" in warning for warning in validation.warnings)
    assert any("cluster.scheduler" in warning for warning in validation.warnings)


def test_cluster_strict_int_flags_error_on_non_numeric_strings() -> None:
    validation = validate_app_settings(
        {"cluster": {"pool": "true", "cython": "yes", "rapids": False}}
    )
    assert not validation.ok
    assert len(validation.errors) == 2
    assert any("cluster.pool" in error for error in validation.errors)
    assert any("cluster.cython" in error for error in validation.errors)

    numeric_string = validate_app_settings({"cluster": {"pool": "1"}})
    assert numeric_string.ok
    assert any("cluster.pool" in warning for warning in numeric_string.warnings)

    assert validate_app_settings({"cluster": {"pool": True, "cython": 0}}).ok
    assert validate_app_settings({"cluster": {"pool": 1}}).warnings == ()


def test_cluster_workers_counts_are_validated() -> None:
    assert validate_app_settings({"cluster": {"workers": {}}}).ok
    assert validate_app_settings({"cluster": {"workers": {"127.0.0.1": 2}}}).ok

    bad_counts = validate_app_settings(
        {"cluster": {"workers": {"a-host": -1, "b-host": True, "c-host": "2"}}}
    )
    assert len(bad_counts.errors) == 3

    not_table = validate_app_settings({"cluster": {"workers": "many"}})
    assert not not_table.ok


def test_cluster_workers_fractional_counts_warn_not_error() -> None:
    validation = validate_app_settings({"cluster": {"workers": {"127.0.0.1": 2.5}}})
    assert validation.ok
    assert any(
        "truncated to 2" in warning for warning in validation.warnings
    )


def test_cluster_service_health_must_be_table() -> None:
    assert validate_app_settings({"cluster": {"service_health": {}}}).ok
    assert not validate_app_settings({"cluster": {"service_health": True}}).ok


def test_pages_view_module_shapes() -> None:
    assert validate_app_settings({"pages": {"view_module": []}}).ok
    assert validate_app_settings({"pages": {"view_module": ["app_ui"]}}).ok

    as_string = validate_app_settings({"pages": {"view_module": "view_maps"}})
    assert not as_string.ok
    assert "silently ignored" in as_string.errors[0]

    bad_item = validate_app_settings({"pages": {"view_module": ["view_maps", 3]}})
    assert not bad_item.ok

    blank_item = validate_app_settings({"pages": {"view_module": ["view_maps", " "]}})
    assert blank_item.ok
    assert any("blank" in warning for warning in blank_item.warnings)


def test_pages_default_view_must_be_string() -> None:
    assert validate_app_settings({"pages": {"default_view": "view_maps"}}).ok
    assert not validate_app_settings({"pages": {"default_view": 1}}).ok


def test_app_surface_dual_default_convention_is_accepted() -> None:
    payload = {
        "app_surface": {
            "title": "Cockpit",
            "entrypoint": "app/app_surface.py",
            "default": "streamlit",
            "backends": {
                "streamlit": {
                    "entrypoint": "app/app_surface.py",
                    "default": True,
                }
            },
        }
    }
    validation = validate_app_settings(payload)
    assert validation.ok
    assert validation.warnings == ()


def test_app_surface_misused_defaults_warn() -> None:
    validation = validate_app_settings(
        {
            "app_surface": {
                "entrypoint": "app/app_surface.py",
                "default": True,
                "backends": {
                    "streamlit": {
                        "entrypoint": "app/app_surface.py",
                        "default": "true",
                    }
                },
            }
        }
    )
    assert validation.ok
    assert any("app_surface.default" in warning for warning in validation.warnings)
    assert any(
        "app_surface.backends.streamlit.default" in warning
        for warning in validation.warnings
    )


def test_app_surface_without_any_target_warns() -> None:
    validation = validate_app_settings({"app_surface": {"title": "Cockpit"}})
    assert validation.ok
    assert any("dropped" in warning for warning in validation.warnings)

    backend_only = validate_app_settings(
        {
            "app_surface": {
                "backends": {"streamlit": {"title": "Cockpit"}},
            }
        }
    )
    assert backend_only.ok
    assert any("skipped" in warning for warning in backend_only.warnings)


def test_app_surface_backend_shapes_are_refused_when_not_tables() -> None:
    assert not validate_app_settings({"app_surface": {"backends": "streamlit"}}).ok
    assert not validate_app_settings(
        {"app_surface": {"backends": {"streamlit": "app.py"}}}
    ).ok


def test_app_owned_territory_is_never_rejected() -> None:
    payload = {
        "args": {"custom": {"nested": [1, 2, 3]}, "stages": [{"name": "run"}]},
        "pages": {
            "view_module": ["view_maps_network"],
            "view_maps_network": {"anything": True},
        },
        "view_maps_network": {"widget_state": ["a", "b"]},
        "connector_refs": {"weather": "connector-1"},
        "page_connector_refs": {"release_decision": {"role": "id"}},
        "app_surface": {
            "entrypoint": "app/app_surface.py",
            "policies": [{"label": "L", "directory": "d", "role": "r"}],
            "sidebar_controls": {"free": "form"},
        },
    }
    validation = validate_app_settings(payload)
    assert validation.ok
    assert validation.warnings == ()


def test_passthrough_path_types_warn_only() -> None:
    validation = validate_app_settings(
        {
            "connector_catalog": {"path": 5},
            "legacy_paths": {"data_in": 5, "data_out": "ok"},
        }
    )
    assert validation.ok
    assert len(validation.warnings) == 2


def test_missing_file_is_a_valid_app_marker(tmp_path: Path) -> None:
    validation = validate_app_settings_file(tmp_path / "app_settings.toml")
    assert validation == AppSettingsValidation()


def test_invalid_toml_file_is_refused(tmp_path: Path) -> None:
    settings = tmp_path / "app_settings.toml"
    settings.write_text("[pages\n", encoding="utf-8")
    validation = validate_app_settings_file(settings)
    assert not validation.ok
    assert "not valid TOML" in validation.errors[0]


class _RecordingLogger:
    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []

    def warning(self, message: str) -> None:
        self.records.append(("warning", message))

    def info(self, message: str) -> None:
        self.records.append(("info", message))

    def debug(self, message: str) -> None:
        self.records.append(("debug", message))


def test_log_app_settings_validation_reports_by_severity(tmp_path: Path) -> None:
    settings = tmp_path / "app_settings.toml"
    settings.write_text(
        'pages = "oops"\n\n[cluster]\nverbose = true\n', encoding="utf-8"
    )
    logger = _RecordingLogger()

    validation = log_app_settings_validation(settings, logger=logger)

    assert not validation.ok
    levels = [level for level, _message in logger.records]
    assert "warning" in levels
    assert "info" in levels


def test_log_app_settings_validation_never_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _explode(_path: object) -> AppSettingsValidation:
        raise RuntimeError("boom")

    monkeypatch.setattr(schema_module, "validate_app_settings_file", _explode)
    logger = _RecordingLogger()

    validation = log_app_settings_validation(
        tmp_path / "app_settings.toml", logger=logger
    )

    assert validation == AppSettingsValidation()
    assert logger.records and logger.records[0][0] == "debug"


def test_log_app_settings_validation_tolerates_none_logger(tmp_path: Path) -> None:
    settings = tmp_path / "app_settings.toml"
    settings.write_text("[cluster]\nverbose = true\n", encoding="utf-8")

    validation = log_app_settings_validation(settings, logger=None)

    assert validation.ok
    assert any("cluster.verbose" in warning for warning in validation.warnings)


class _BrokenLogger:
    def warning(self, _message: str) -> None:
        raise RuntimeError("logger unavailable")

    def info(self, _message: str) -> None:
        raise RuntimeError("logger unavailable")

    def debug(self, _message: str) -> None:
        raise RuntimeError("logger unavailable")


def test_log_app_settings_validation_survives_broken_logger(tmp_path: Path) -> None:
    settings = tmp_path / "app_settings.toml"
    settings.write_text("[cluster]\nverbose = true\n", encoding="utf-8")

    validation = log_app_settings_validation(settings, logger=_BrokenLogger())

    assert validation == AppSettingsValidation()


def test_every_tracked_app_settings_file_passes_without_errors() -> None:
    candidates = [
        path
        for path in (REPO_ROOT / "src").rglob("app_settings.toml")
        if not SWEEP_EXCLUDED_PARTS.intersection(path.parts)
    ]
    assert len(candidates) >= 10, "sweep found suspiciously few app_settings files"

    failures = {}
    for path in candidates:
        validation = validate_app_settings_file(path)
        if validation.errors:
            failures[str(path)] = validation.errors
    assert failures == {}
