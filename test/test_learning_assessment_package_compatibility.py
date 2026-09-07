"""The old package installs one canonical app and keeps legacy lookups usable."""

from __future__ import annotations

import importlib
import tomllib
from pathlib import Path

from packaging.requirements import Requirement


ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "src/agilab/lib"


def test_compatibility_package_depends_on_the_canonical_release(monkeypatch):
    canonical = LIB / "agi-app-learning-assessment"
    legacy = LIB / "agi-app-tescia-diagnostic"
    new = tomllib.loads((canonical / "pyproject.toml").read_text())
    old = tomllib.loads((legacy / "pyproject.toml").read_text())
    dependency, = map(Requirement, old["project"]["dependencies"])
    assert dependency.name == "agi-app-learning-assessment"
    assert new["project"]["version"] in dependency.specifier
    assert "2026.12.1" in dependency.specifier
    assert "2027.0" not in dependency.specifier
    assert "entry-points" not in old["project"]
    assert not (legacy / "setup.py").exists()

    monkeypatch.syspath_prepend(str(canonical / "src"))
    monkeypatch.syspath_prepend(str(legacy / "src"))
    current = importlib.import_module("agi_app_learning_assessment")
    bridge = importlib.import_module("agi_app_tescia_diagnostic")
    assert bridge.project_root() == current.project_root()
    assert bridge.metadata() == current.metadata()
    assert current.project_root().name == "learning_assessment_project"


def test_legacy_entry_points_use_the_canonical_runtime(monkeypatch):
    from importlib.metadata import EntryPoint

    from agi_env.project.app_provider_registry import resolve_app_runtime_target

    package = LIB / "agi-app-learning-assessment"
    manifest = tomllib.loads((package / "pyproject.toml").read_text())
    entry_points = manifest["project"]["entry-points"]["agilab.apps"]
    monkeypatch.syspath_prepend(str(package / "src"))
    roots = set()
    for name in (
        "learning_assessment", "learning_assessment_project",
        "tescia_diagnostic", "tescia_diagnostic_project",
    ):
        provider = EntryPoint(name=name, value=entry_points[name], group="agilab.apps").load()
        root = provider()
        roots.add(root)
        assert resolve_app_runtime_target(root, name) == "learning_assessment"
        settings = tomllib.loads((root / "src/app_settings.toml").read_text())
        assert settings["app_surface"]["title"] == "Learning & Assessment"
    assert len(roots) == 1
