from __future__ import annotations

import importlib
from pathlib import Path
import sys
from types import SimpleNamespace

from streamlit.testing.v1 import AppTest


APP_SRC = Path("src/agilab/apps/builtin/multi_app_dag_project/src").resolve()
APP_FORM = APP_SRC / "app_args_form.py"
CORE_SRC = Path("src/agilab").resolve()


def _make_env(tmp_path: Path) -> SimpleNamespace:
    settings_file = tmp_path / "app_settings.toml"
    settings_file.write_text(
        "[args]\n"
        'dag_path = "dag_templates/flight_to_weather_legacy_multi_app_dag.json"\n'
        'output_path = "~/log/execute/multi_app_dag/runner_state.json"\n'
        "reset_target = false\n",
        encoding="utf-8",
    )
    return SimpleNamespace(
        app_settings_file=str(settings_file),
        humanize_validation_errors=lambda exc: [str(item) for item in exc.errors()],
    )


def _clear_multi_app_dag_modules() -> None:
    for name in list(sys.modules):
        if name == "multi_app_dag" or name.startswith("multi_app_dag."):
            sys.modules.pop(name, None)


def test_app_args_form_prefers_project_src_when_package_dir_shadows_imports(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _clear_multi_app_dag_modules()
    monkeypatch.setattr(sys, "path", [str(CORE_SRC), str(APP_SRC), *sys.path])
    try:
        shadow = importlib.import_module("multi_app_dag")
        assert not getattr(shadow, "__path__", None)

        at = AppTest.from_file(str(APP_FORM), default_timeout=20)
        at.session_state["env"] = _make_env(tmp_path)
        at.session_state["app_settings"] = {"args": {}, "cluster": {}, "pages": {}}

        at.run()

        assert not at.exception
        assert at.text_input(key="multi_app_dag_project:app_args_form:dag_path").value == (
            "dag_templates/flight_to_weather_legacy_multi_app_dag.json"
        )
    finally:
        _clear_multi_app_dag_modules()
