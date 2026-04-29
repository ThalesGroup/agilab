from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import agi_env.connector_registry as connector_registry
from agi_env.connector_registry import (
    ConnectorPath,
    ConnectorPathRegistry,
    build_connector_path_registry,
    resolve_connector_root,
)


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


def test_connector_root_supports_get_only_envars(tmp_path) -> None:
    class GetOnly:
        def get(self, key: str):
            return {"AGI_EXPORT_DIR": "getter-export"}.get(key)

    env = SimpleNamespace(home_abs=tmp_path, envars=GetOnly())

    connector = resolve_connector_root(
        env,
        connector_id="export_root",
        label="Export root",
        attr_name="AGILAB_EXPORT_ABS",
        env_key="AGI_EXPORT_DIR",
        default_child="export",
    )

    assert connector.path == (tmp_path / "getter-export").resolve()
    assert connector.source == "envars:AGI_EXPORT_DIR"


def test_connector_root_ignores_non_callable_get_envars(tmp_path) -> None:
    class NonCallableGet:
        get = "not-callable"

    env = SimpleNamespace(home_abs=tmp_path, envars=NonCallableGet())

    connector = resolve_connector_root(
        env,
        connector_id="export_root",
        label="Export root",
        attr_name="AGILAB_EXPORT_ABS",
        env_key="AGI_EXPORT_DIR",
        default_child="export",
    )

    assert connector.path == tmp_path / "export"
    assert connector.source == "default:~/export"


def test_connector_root_falls_back_to_getattr_for_slots_env(tmp_path) -> None:
    class SlotsEnv:
        __slots__ = ("AGILAB_LOG_ABS", "envars", "home_abs")

        def __init__(self) -> None:
            self.AGILAB_LOG_ABS = tmp_path / "slot-log"
            self.envars = {}
            self.home_abs = tmp_path

    connector = resolve_connector_root(
        SlotsEnv(),
        connector_id="log_root",
        label="Log root",
        attr_name="AGILAB_LOG_ABS",
        env_key="AGI_LOG_DIR",
        default_child="log",
    )

    assert connector.path == tmp_path / "slot-log"
    assert connector.source == "attr:AGILAB_LOG_ABS"


def test_connector_root_uses_process_env_when_config_is_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AGI_LOG_DIR", "process-log")
    env = SimpleNamespace(home_abs=tmp_path, envars={"AGI_LOG_DIR": "   "})

    connector = resolve_connector_root(
        env,
        connector_id="log_root",
        label="Log root",
        attr_name="AGILAB_LOG_ABS",
        env_key="AGI_LOG_DIR",
        default_child="log",
    )

    assert connector.path == (tmp_path / "process-log").resolve()
    assert connector.source == "os.environ:AGI_LOG_DIR"


def test_connector_exists_handles_unreadable_paths(tmp_path) -> None:
    class BrokenPath:
        def exists(self) -> bool:
            raise OSError("simulated filesystem failure")

        def __str__(self) -> str:
            return str(tmp_path / "broken")

    connector = ConnectorPath(
        id="broken",
        label="Broken path",
        path=BrokenPath(),  # type: ignore[arg-type]
        kind="root",
        source="test",
    )

    assert connector.exists is False
    assert connector.as_row()["exists"] is False


def test_connector_registry_missing_and_unportable_paths(tmp_path, monkeypatch) -> None:
    root = ConnectorPath(
        id="root",
        label="Root",
        path=tmp_path / "root",
        kind="root",
        source="test",
    )
    registry = ConnectorPathRegistry((root,))

    with pytest.raises(KeyError, match="Unknown connector path id: missing"):
        registry.require("missing")

    def broken_relative_check(self: Path, other: Path) -> bool:
        raise RuntimeError("simulated relative path failure")

    monkeypatch.setattr(Path, "is_relative_to", broken_relative_check)

    outside = tmp_path / "outside" / "artifact.txt"
    assert registry.portable_label(outside) == str(outside)


def test_connector_registry_can_build_without_target_or_pages_root(tmp_path) -> None:
    env = SimpleNamespace(home_abs=tmp_path, envars={})

    registry = build_connector_path_registry(env, ensure_roots=True)

    assert registry.get("artifact_root") is None
    assert registry.get("execute_log_root") is None
    assert registry.get("pages_root") is None
    assert registry.path("export_root") == tmp_path / "export"
    assert registry.path("log_root") == tmp_path / "log"
    assert registry.path("first_proof_log_root").is_dir()


def test_connector_root_reports_unresolvable_candidates(monkeypatch, tmp_path) -> None:
    env = SimpleNamespace(home_abs=tmp_path, envars={})
    monkeypatch.setattr(connector_registry, "_clean_value", lambda _value: None)

    with pytest.raises(RuntimeError, match="Unable to resolve connector root 'export_root'"):
        resolve_connector_root(
            env,
            connector_id="export_root",
            label="Export root",
            attr_name="AGILAB_EXPORT_ABS",
            env_key="AGI_EXPORT_DIR",
            default_child="export",
        )
