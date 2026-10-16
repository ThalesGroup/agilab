"""Authored TOML mappings survive SDK overlay and extras preparation."""

from __future__ import annotations

from pathlib import Path
import tomllib

import pytest

from agi_cluster.agi_distributor.deployment import deployment_local_support
from agi_cluster.agi_distributor.runtime import uv_source_support


REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize("app", ["uav_queue_project", "uav_relay_queue_project"])
def test_manager_overlay_preserves_actual_builtin_authored_sources(tmp_path, app):
    source = REPO_ROOT / "src/agilab/apps/builtin" / app / "pyproject.toml"
    original = source.read_bytes()
    authored = tomllib.loads(original.decode())
    local_core = tmp_path / "source-sdk" / "agi-core"
    local_core.mkdir(parents=True)

    overlay = deployment_local_support._write_manager_sync_overlay(
        source, tmp_path / "overlay", local_core_sources={"agi-core": str(local_core)}
    )

    data = tomllib.loads((overlay / "pyproject.toml").read_text())
    actual = data["tool"]["uv"]["sources"]
    expected = authored["tool"]["uv"]["sources"]
    assert set(expected) <= set(actual)
    for name, declaration in expected.items():
        normalized = dict(declaration)
        normalized["path"] = (source.parent / declaration["path"]).resolve().as_posix()
        assert actual[name] == normalized
    assert data["tool"]["setuptools"] == authored["tool"]["setuptools"]
    assert actual["agi-core"]["path"] == str(local_core)
    assert source.read_bytes() == original


def test_manager_overlay_preserves_interleaved_tool_metadata_and_comments(tmp_path):
    app = tmp_path / "authored-app"
    app.mkdir()
    local_env = tmp_path / "user-owned-sdk"
    local_env.mkdir()
    sentinel = local_env / "authored-source.txt"
    sentinel.write_text("preserve user source\n")
    source = app / "pyproject.toml"
    source.write_text(
        "# authored metadata must survive staging\n"
        '[project]\nname = "authored-app"\nversion = "1.0"\n'
        'dependencies = ["agi-env", "agi-web"]\n'
        "[tool.uv.sources]\n"
        'agi-env = { path = "../user-owned-sdk", editable = true } # keep source declaration\n'
        '[tool.authoring]\nsentinel = "keep authored tool settings"\n'
        '[build-system]\nrequires = ["setuptools"]\nbuild-backend = "setuptools.build_meta"\n'
        '[tool.uv.sources.agi-web]\npath = "./local-web"\neditable = true\n'
    )
    original = source.read_bytes()
    overlay = deployment_local_support._write_manager_sync_overlay(
        source,
        tmp_path / "overlay",
        local_core_sources={"agi-core": str(tmp_path / "core")},
    )
    output = (overlay / "pyproject.toml").read_text()
    data = tomllib.loads(output)
    assert data["tool"]["authoring"]["sentinel"] == "keep authored tool settings"
    assert data["tool"]["uv"]["sources"]["agi-env"] == {
        "path": local_env.resolve().as_posix(),
        "editable": True,
    }
    assert data["tool"]["uv"]["sources"]["agi-web"] == {
        "path": (app / "local-web").resolve().as_posix(),
        "editable": True,
    }
    assert "# authored metadata must survive staging" in output
    assert "# keep source declaration" in output
    assert source.read_bytes() == original
    assert sentinel.read_text() == "preserve user source\n"


def test_manager_overlay_creates_missing_tool_tables(tmp_path):
    source = tmp_path / "pyproject.toml"
    source.write_text('[project]\nname = "plain-app"\nversion = "1.0"\n')
    overlay = deployment_local_support._write_manager_sync_overlay(
        source,
        tmp_path / "overlay",
        local_core_sources={"agi-core": str(tmp_path / "core")},
    )
    data = tomllib.loads((overlay / "pyproject.toml").read_text())
    assert data["tool"]["uv"]["sources"]["agi-core"]["path"] == str(tmp_path / "core")


@pytest.mark.parametrize(
    "optional",
    [
        'optional-dependencies = { analysis = ["pandas>=2.3,<4"], test = ["pytest>=9,<10"] } # keep groups\n',
        '[project.optional-dependencies]\nanalysis = ["pandas>=2.3,<4"]\ntest = ["pytest>=9,<10"]\n',
    ],
    ids=["pep621-inline-table", "pep621-standard-table"],
)
def test_optional_extras_preserves_valid_pep621_groups(tmp_path, optional):
    source = tmp_path / "pyproject.toml"
    source.write_text('[project]\nname = "extras-app"\nversion = "1.0"\n' + optional)
    before = tomllib.loads(source.read_text())["project"]["optional-dependencies"]
    assert all(
        isinstance(value, list) and all(isinstance(item, str) for item in value)
        for value in before.values()
    )

    uv_source_support.ensure_optional_extras(source, {"new-extra"})

    output = source.read_text()
    after = tomllib.loads(output)["project"]["optional-dependencies"]
    assert {name: after[name] for name in before} == before
    assert after["new-extra"] == []
    if "# keep groups" in optional:
        assert "# keep groups" in output
