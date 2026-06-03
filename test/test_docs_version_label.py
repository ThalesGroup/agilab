from __future__ import annotations

import importlib.util
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONF_PATH = ROOT / "docs/source/conf.py"
RELEASE_PROOF = ROOT / "docs/source/data/release_proof.toml"
LAYOUT_TEMPLATE = ROOT / "docs/source/_templates/layout.html"


def _load_conf_module():
    sys.modules.pop("agilab_docs_conf_test_module", None)
    spec = importlib.util.spec_from_file_location("agilab_docs_conf_test_module", CONF_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_docs_visible_release_uses_github_release_tag() -> None:
    release_proof = tomllib.loads(RELEASE_PROOF.read_text(encoding="utf-8"))
    release_tag = release_proof["release"]["github_release_tag"]

    conf = _load_conf_module()

    assert release_tag.startswith("v")
    assert conf.release == release_tag
    assert conf.version == release_tag
    assert conf.html_context["docs_version"] == release_tag


def test_docs_template_keeps_release_and_build_revision_separate() -> None:
    template = LAYOUT_TEMPLATE.read_text(encoding="utf-8")

    assert "Current release {{ docs_version }}" in template
    assert "Docs build {{ docs_build_revision }}" in template


def test_docs_conf_skips_generated_root_project_workspaces() -> None:
    conf = _load_conf_module()

    assert conf._is_generated_root_project_src(ROOT / "temporary_demo_project" / "src") is True
    assert (
        conf._is_generated_root_project_src(
            ROOT / "src" / "agilab" / "apps" / "builtin" / "flight_telemetry_project" / "src"
        )
        is False
    )
