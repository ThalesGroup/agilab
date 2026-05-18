from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import tomllib

MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "agilab" / "runtime_diagnostics.py"
SPEC = importlib.util.spec_from_file_location("agilab_runtime_diagnostics_test", MODULE_PATH)
assert SPEC and SPEC.loader
runtime_diagnostics = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime_diagnostics)

FAILURE_MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "agilab" / "runtime_failure_diagnostics.py"
FAILURE_SPEC = importlib.util.spec_from_file_location(
    "agilab_runtime_failure_diagnostics_test",
    FAILURE_MODULE_PATH,
)
assert FAILURE_SPEC and FAILURE_SPEC.loader
runtime_failure_diagnostics = importlib.util.module_from_spec(FAILURE_SPEC)
sys.modules[FAILURE_SPEC.name] = runtime_failure_diagnostics
FAILURE_SPEC.loader.exec_module(runtime_failure_diagnostics)


def test_diagnostics_verbose_mapping_is_user_facing_and_bounded() -> None:
    assert runtime_diagnostics.diagnostics_verbose("Quiet") == 0
    assert runtime_diagnostics.diagnostics_verbose("Standard") == 1
    assert runtime_diagnostics.diagnostics_verbose("Detailed") == 2
    assert runtime_diagnostics.diagnostics_verbose("Debug") == 3
    assert runtime_diagnostics.diagnostics_label("2") == "Detailed"
    assert runtime_diagnostics.coerce_diagnostics_verbose(True) == 1
    assert runtime_diagnostics.coerce_diagnostics_verbose(99) == 1
    assert runtime_diagnostics.coerce_diagnostics_verbose("bad", default=0) == 0
    assert runtime_diagnostics.diagnostics_verbose("unknown", default=3) == 3
    assert runtime_diagnostics.diagnostics_widget_key("flight project/demo") == (
        "runtime_diagnostics_level__flight_telemetry_project_demo"
    )
    assert runtime_diagnostics.diagnostics_widget_key("   ") == "runtime_diagnostics_level__default"


def test_global_diagnostics_verbose_prefers_project_agnostic_env() -> None:
    assert runtime_diagnostics.global_diagnostics_verbose(
        session_state={runtime_diagnostics.GLOBAL_DIAGNOSTICS_ENV_KEY: "3"},
        envars={runtime_diagnostics.GLOBAL_DIAGNOSTICS_ENV_KEY: "2"},
        environ={runtime_diagnostics.GLOBAL_DIAGNOSTICS_ENV_KEY: "1"},
        settings={"cluster": {"verbose": 0}},
    ) == 3
    assert runtime_diagnostics.global_diagnostics_verbose(
        envars={runtime_diagnostics.GLOBAL_DIAGNOSTICS_ENV_KEY: "2"},
        settings={"cluster": {"verbose": 0}},
    ) == 2
    assert runtime_diagnostics.global_diagnostics_verbose(
        session_state=SimpleNamespace(**{runtime_diagnostics.GLOBAL_DIAGNOSTICS_ENV_KEY: "1"}),
        settings={"cluster": {"verbose": 0}},
    ) == 1
    assert runtime_diagnostics.global_diagnostics_verbose(settings={"cluster": {"verbose": 0}}) == 0
    assert runtime_diagnostics.global_diagnostics_verbose(settings={"cluster": "bad"}, default=2) == 2


def test_update_settings_diagnostics_replaces_invalid_cluster_section() -> None:
    settings = {"cluster": "not-a-table"}

    selected = runtime_diagnostics.update_settings_diagnostics(settings, "Debug")

    assert selected == 3
    assert settings == {"cluster": {"verbose": 3}}


def test_render_runtime_diagnostics_control_reuses_cross_page_state() -> None:
    fake_st = SimpleNamespace(session_state={"runtime_diagnostics_level__flight_telemetry_project": "Debug"})
    settings = {"cluster": {"verbose": 1}}
    calls: list[dict[str, object]] = []

    def _choice(container, label, options, **kwargs):
        calls.append(
            {
                "container": container,
                "label": label,
                "options": tuple(options),
                "key": kwargs.get("key"),
                "default": kwargs.get("default"),
            }
        )
        return fake_st.session_state[kwargs["key"]]

    selected = runtime_diagnostics.render_runtime_diagnostics_control(
        fake_st,
        object(),
        settings,
        app_name="flight_telemetry_project",
        compact_choice_fn=_choice,
    )

    assert selected == 3
    assert settings["cluster"]["verbose"] == 3
    assert calls[0]["label"] == "Diagnostics level"
    assert calls[0]["default"] == "Standard"
    assert calls[0]["key"] == "runtime_diagnostics_level__flight_telemetry_project"


def test_render_runtime_diagnostics_control_clears_invalid_state_and_repairs_settings() -> None:
    fake_st = SimpleNamespace(session_state=SimpleNamespace(runtime_diagnostics_level__bad_app="Invalid"))
    settings = {"cluster": "not-a-table"}
    calls: list[dict[str, object]] = []

    def _choice(_container, _label, _options, **kwargs):
        calls.append({"default": kwargs["default"], "key": kwargs["key"], "help": kwargs["help"]})
        return "Quiet"

    selected = runtime_diagnostics.render_runtime_diagnostics_control(
        fake_st,
        object(),
        settings,
        app_name="bad app",
        compact_choice_fn=_choice,
    )

    assert selected == 0
    assert not hasattr(fake_st.session_state, "runtime_diagnostics_level__bad_app")
    assert settings["cluster"]["verbose"] == 0
    assert calls == [
        {
            "default": "Standard",
            "key": "runtime_diagnostics_level__bad_app",
            "help": runtime_diagnostics.RUNTIME_DIAGNOSTICS_HELP,
        }
    ]


def test_persist_diagnostics_verbose_preserves_app_settings(tmp_path) -> None:
    settings_path = tmp_path / "app_settings.toml"
    settings_path.write_text(
        """
[cluster]
cluster_enabled = true
verbose = 1

[args]
data_in = "input"
""".strip(),
        encoding="utf-8",
    )

    runtime_diagnostics.persist_diagnostics_verbose(settings_path, "Detailed")

    payload = tomllib.loads(settings_path.read_text(encoding="utf-8"))
    assert payload["cluster"]["cluster_enabled"] is True
    assert payload["cluster"]["verbose"] == 2
    assert payload["args"]["data_in"] == "input"


def test_settings_file_helpers_handle_empty_missing_and_malformed_paths(tmp_path) -> None:
    assert runtime_diagnostics.load_settings_file(None) == {}
    assert runtime_diagnostics.load_settings_file("") == {}
    assert runtime_diagnostics.load_settings_file(tmp_path / "missing.toml") == {}

    malformed = tmp_path / "bad.toml"
    malformed.write_text("[cluster\n", encoding="utf-8")
    assert runtime_diagnostics.load_settings_file(malformed) == {}

    assert runtime_diagnostics.persist_diagnostics_verbose(None, "Debug") == {}
    assert runtime_diagnostics.persist_diagnostics_verbose("", "Debug") == {}

    new_settings = tmp_path / "nested" / "app_settings.toml"
    persisted = runtime_diagnostics.persist_diagnostics_verbose(new_settings, 0)

    assert persisted == {"cluster": {"verbose": 0}}
    assert tomllib.loads(new_settings.read_text(encoding="utf-8")) == persisted


def test_classify_runtime_failure_reports_invalid_dataset_archive() -> None:
    diagnostic = runtime_failure_diagnostics.classify_runtime_failure(
        "agilab.data_archive_support.unzip_data Failed to extract "
        "'/tmp/app/src/worker/dataset.7z': not a 7z file\n"
        "py7zr.exceptions.Bad7zFile: not a 7z file",
        phase="install",
    )

    assert diagnostic is not None
    assert diagnostic.category == "archive"
    assert diagnostic.title == "Dataset archive is invalid."
    assert "dataset.7z could not be extracted" in diagnostic.detail
    assert "rerun INSTALL" in diagnostic.next_action


def test_classify_runtime_failure_reports_dependency_and_scheduler() -> None:
    dependency = runtime_failure_diagnostics.classify_runtime_failure(
        "ModuleNotFoundError: No module named 'polars_worker'"
    )
    scheduler = runtime_failure_diagnostics.classify_runtime_failure(
        "ConnectionError: scheduler host is invalid",
        phase="execute",
    )

    assert dependency is not None
    assert dependency.category == "dependency"
    assert "`polars_worker`" in dependency.detail
    assert scheduler is not None
    assert scheduler.category == "scheduler"
    assert "execute action" in scheduler.detail


def test_classify_runtime_failure_handles_empty_sequence_and_object_payloads() -> None:
    class _Payload:
        def __str__(self) -> str:
            return 'ModuleNotFoundError: "custom_worker"'

    sequence_dependency = runtime_failure_diagnostics.classify_runtime_failure(
        ["worker startup", 'No module named "numpy"']
    )
    object_dependency = runtime_failure_diagnostics.classify_runtime_failure(_Payload())

    assert runtime_failure_diagnostics.classify_runtime_failure(None) is None
    assert runtime_failure_diagnostics.classify_runtime_failure("   ") is None
    assert sequence_dependency is not None
    assert sequence_dependency.category == "dependency"
    assert "`numpy`" in sequence_dependency.detail
    assert object_dependency is not None
    assert object_dependency.category == "dependency"
    assert "`custom_worker`" in object_dependency.detail


def test_classify_runtime_failure_reports_install_state_path_and_share_issues() -> None:
    cluster_share = runtime_failure_diagnostics.classify_runtime_failure(
        "cluster mode requires AGI_CLUSTER_SHARE",
        phase="install",
    )
    project_state = runtime_failure_diagnostics.classify_runtime_failure(
        "installation is incomplete because .venv is missing"
    )
    worker_copy = runtime_failure_diagnostics.classify_runtime_failure(
        "worker copy /tmp/wenv/demo_worker/pyproject.toml is unsatisfiable"
    )
    missing_path = runtime_failure_diagnostics.classify_runtime_failure(
        "project path /tmp/demo/input does not exist"
    )

    assert cluster_share is not None
    assert cluster_share.category == "cluster-share"
    assert "AGI_CLUSTER_SHARE" in cluster_share.detail
    assert project_state is not None
    assert project_state.category == "project-state"
    assert worker_copy is not None
    assert worker_copy.category == "worker-copy"
    assert missing_path is not None
    assert missing_path.category == "path"


def test_archive_display_name_falls_back_to_generic_dataset_name() -> None:
    assert runtime_failure_diagnostics._archive_display_name("bad archive marker") == "dataset.7z"


def test_classify_runtime_failure_returns_none_for_unknown_text() -> None:
    assert runtime_failure_diagnostics.classify_runtime_failure("Command failed with exit code 1") is None
