from __future__ import annotations

from types import SimpleNamespace

import tomllib

from agilab import runtime_diagnostics


def test_diagnostics_verbose_mapping_is_user_facing_and_bounded() -> None:
    assert runtime_diagnostics.diagnostics_verbose("Quiet") == 0
    assert runtime_diagnostics.diagnostics_verbose("Standard") == 1
    assert runtime_diagnostics.diagnostics_verbose("Detailed") == 2
    assert runtime_diagnostics.diagnostics_verbose("Debug") == 3
    assert runtime_diagnostics.diagnostics_label("2") == "Detailed"
    assert runtime_diagnostics.coerce_diagnostics_verbose(True) == 1
    assert runtime_diagnostics.coerce_diagnostics_verbose(99) == 1


def test_render_runtime_diagnostics_control_reuses_cross_page_state() -> None:
    fake_st = SimpleNamespace(session_state={"runtime_diagnostics_level__flight_project": "Debug"})
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
        app_name="flight_project",
        compact_choice_fn=_choice,
    )

    assert selected == 3
    assert settings["cluster"]["verbose"] == 3
    assert calls[0]["label"] == "Diagnostics level"
    assert calls[0]["default"] == "Standard"
    assert calls[0]["key"] == "runtime_diagnostics_level__flight_project"


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
