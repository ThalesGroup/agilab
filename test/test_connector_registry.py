from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from agi_env.connector_registry import build_connector_path_registry, resolve_connector_root


def test_connector_registry_resolves_relative_roots_and_portable_labels(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AGI_EXPORT_DIR", "process-export")
    env = SimpleNamespace(
        home_abs=tmp_path,
        envars={"AGI_EXPORT_DIR": "configured-export", "AGI_LOG_DIR": "configured-log"},
        target="meteo_forecast",
        AGILAB_PAGES_ABS=tmp_path / "pages",
    )

    registry = build_connector_path_registry(env, ensure_roots=True)

    assert registry.path("export_root") == (tmp_path / "configured-export").resolve()
    assert registry.path("log_root") == (tmp_path / "configured-log").resolve()
    assert registry.path("artifact_root") == (
        tmp_path / "configured-export" / "meteo_forecast"
    ).resolve()
    assert registry.path("first_proof_manifest") == (
        tmp_path / "configured-log" / "execute" / "flight" / "run_manifest.json"
    ).resolve()
    assert registry.path("export_root").is_dir()
    assert registry.path("log_root").is_dir()
    assert registry.portable_label(
        registry.path("artifact_root") / "run_a" / "forecast_metrics.json"
    ) == "artifact_root://run_a/forecast_metrics.json"

    rows = registry.as_rows()
    row_by_id = {row["connector_id"]: row for row in rows}
    assert row_by_id["export_root"]["source"] == "envars:AGI_EXPORT_DIR"
    assert row_by_id["pages_root"]["portable_path"] == "pages_root://."
    assert registry.summary()["connector_count"] == len(rows)


def test_connector_root_prefers_resolved_attr_over_process_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AGI_LOG_DIR", "process-log")
    env = SimpleNamespace(
        home_abs=tmp_path,
        envars={"AGI_LOG_DIR": "configured-log"},
        AGILAB_LOG_ABS=tmp_path / "resolved-log",
    )

    connector = resolve_connector_root(
        env,
        connector_id="log_root",
        label="Log root",
        attr_name="AGILAB_LOG_ABS",
        env_key="AGI_LOG_DIR",
        default_child="log",
    )

    assert connector.path == tmp_path / "resolved-log"
    assert connector.source == "attr:AGILAB_LOG_ABS"


def test_connector_root_ignores_delegated_stale_attr_during_init(tmp_path) -> None:
    class DelegatingEnv:
        def __init__(self) -> None:
            self.home_abs = tmp_path
            self.envars = {}

        def __getattr__(self, name: str):
            if name == "AGILAB_LOG_ABS":
                return tmp_path / "stale-singleton-log"
            raise AttributeError(name)

    connector = resolve_connector_root(
        DelegatingEnv(),
        connector_id="log_root",
        label="Log root",
        attr_name="AGILAB_LOG_ABS",
        env_key="AGI_LOG_DIR",
        default_child="log",
        prefer_attr=False,
    )

    assert connector.path == tmp_path / "log"
    assert connector.source == "default:~/log"
