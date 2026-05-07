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


def test_build_connector_registry_resolves_roots_children_and_labels(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AGI_EXPORT_DIR", "process-export")
    env = SimpleNamespace(
        home_abs=tmp_path,
        envars={"AGI_EXPORT_DIR": "configured-export", "AGI_LOG_DIR": "configured-log"},
        target="ignored_when_explicit_target_is_passed",
        AGILAB_PAGES_ABS="pages",
    )

    registry = build_connector_path_registry(
        env,
        target=" demo_project ",
        first_proof_target="proof_project",
        run_manifest_filename="proof_manifest.json",
        ensure_roots=True,
    )

    assert registry.path("export_root") == (tmp_path / "configured-export").resolve()
    assert registry.path("log_root") == (tmp_path / "configured-log").resolve()
    assert registry.path("artifact_root") == (
        tmp_path / "configured-export" / "demo_project"
    ).resolve()
    assert registry.path("execute_log_root") == (
        tmp_path / "configured-log" / "execute" / "demo_project"
    ).resolve()
    assert registry.path("execute_log_root").is_dir()
    assert registry.path("first_proof_log_root") == (
        tmp_path / "configured-log" / "execute" / "proof_project"
    ).resolve()
    assert registry.path("first_proof_log_root").is_dir()
    assert registry.path("first_proof_manifest") == (
        tmp_path / "configured-log" / "execute" / "proof_project" / "proof_manifest.json"
    ).resolve()
    assert registry.path("pages_root") == (tmp_path / "pages").resolve()

    assert registry.portable_label(registry.path("pages_root")) == "pages_root://."
    assert (
        registry.portable_label(registry.path("execute_log_root") / "run.log")
        == "execute_log_root://run.log"
    )

    rows = {row["connector_id"]: row for row in registry.as_rows()}
    assert rows["export_root"]["source"] == "envars:AGI_EXPORT_DIR"
    assert rows["export_root"]["env_key"] == "AGI_EXPORT_DIR"
    assert rows["first_proof_manifest"]["kind"] == "manifest"
    assert rows["pages_root"]["portable_path"] == "pages_root://."

    summary = registry.summary()
    assert summary["connector_count"] == len(registry.paths)
    assert summary["paths"]["execute_log_root"].endswith("/execute/demo_project")
    assert "first_proof_manifest" in summary["missing_connector_ids"]


def test_connector_root_covers_get_only_slots_process_env_and_explicit_home(
    tmp_path, monkeypatch
) -> None:
    class GetOnly:
        def get(self, key: str):
            return {"AGI_EXPORT_DIR": "getter-export"}.get(key)

    class SlotsEnv:
        __slots__ = ("AGILAB_LOG_ABS", "envars", "home_abs")

        def __init__(self) -> None:
            self.AGILAB_LOG_ABS = tmp_path / "slot-log"
            self.envars = {}
            self.home_abs = tmp_path

    assert connector_registry._env_home(SimpleNamespace(), home_path=tmp_path) == tmp_path
    assert connector_registry._clean_value(Path("relative")) == "relative"
    assert connector_registry._clean_value("  value  ") == "value"
    assert connector_registry._clean_value("   ") is None

    getter_connector = resolve_connector_root(
        SimpleNamespace(home_abs=tmp_path, envars=GetOnly()),
        connector_id="export_root",
        label="Export root",
        attr_name="AGILAB_EXPORT_ABS",
        env_key="AGI_EXPORT_DIR",
        default_child="export",
    )
    assert getter_connector.path == (tmp_path / "getter-export").resolve()
    assert getter_connector.source == "envars:AGI_EXPORT_DIR"

    slot_connector = resolve_connector_root(
        SlotsEnv(),
        connector_id="log_root",
        label="Log root",
        attr_name="AGILAB_LOG_ABS",
        env_key="AGI_LOG_DIR",
        default_child="log",
    )
    assert slot_connector.path == tmp_path / "slot-log"
    assert slot_connector.source == "attr:AGILAB_LOG_ABS"

    monkeypatch.setenv("AGI_LOG_DIR", "process-log")
    process_connector = resolve_connector_root(
        SimpleNamespace(home_abs=tmp_path, envars={"AGI_LOG_DIR": "  "}),
        connector_id="log_root",
        label="Log root",
        attr_name="AGILAB_LOG_ABS",
        env_key="AGI_LOG_DIR",
        default_child="log",
        ensure=True,
    )
    assert process_connector.path == (tmp_path / "process-log").resolve()
    assert process_connector.path.is_dir()
    assert process_connector.source == "os.environ:AGI_LOG_DIR"


def test_connector_registry_handles_missing_unportable_and_broken_paths(
    tmp_path, monkeypatch
) -> None:
    root = ConnectorPath(
        id="root",
        label="Root",
        path=tmp_path / "root",
        kind="root",
        source="test",
    )
    child = ConnectorPath(
        id="child",
        label="Child",
        path=tmp_path / "root" / "child",
        kind="artifact_root",
        source="derived:root",
    )
    registry = ConnectorPathRegistry((root, child))

    assert registry.get("missing") is None
    with pytest.raises(KeyError, match="Unknown connector path id: missing"):
        registry.require("missing")
    assert registry.portable_label(tmp_path / "root" / "child" / "artifact.csv") == (
        "child://artifact.csv"
    )
    assert registry.path("root") == tmp_path / "root"

    def broken_relative_check(self: Path, other: Path) -> bool:
        raise RuntimeError("simulated relative-path failure")

    monkeypatch.setattr(Path, "is_relative_to", broken_relative_check)
    outside = tmp_path / "outside" / "artifact.csv"
    assert registry.portable_label(outside) == str(outside)

    class BrokenPath:
        def exists(self) -> bool:
            raise OSError("simulated filesystem failure")

        def __str__(self) -> str:
            return str(tmp_path / "broken")

    broken = ConnectorPath(
        id="broken",
        label="Broken",
        path=BrokenPath(),  # type: ignore[arg-type]
        kind="root",
        source="test",
    )
    assert broken.exists is False
    assert broken.as_row()["exists"] is False


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
