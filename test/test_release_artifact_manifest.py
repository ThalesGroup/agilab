from __future__ import annotations

import importlib.util
import json
import sys
import zipfile
from pathlib import Path

import pytest


MODULE_PATH = Path("tools/release_artifact_manifest.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("release_artifact_manifest_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_wheel(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("agilab-2026.5.12.post4.dist-info/METADATA", "Name: agilab\n")


def test_build_manifest_requires_wheel_and_sdist_for_release_packages(tmp_path: Path) -> None:
    module = _load_module()
    dist = tmp_path / "dist"
    dist.mkdir()
    _write_wheel(dist / "agilab-2026.5.12.post4-py3-none-any.whl")
    (dist / "agilab-2026.5.12.post4.tar.gz").write_bytes(b"sdist")

    artifacts = module.build_manifest(dist, package="agilab", artifact_policy="wheel+sdist")

    assert {artifact.kind for artifact in artifacts} == {"wheel", "sdist"}
    assert {artifact.name for artifact in artifacts} == {"agilab"}
    assert all(artifact.sha256 for artifact in artifacts)


def test_build_manifest_rejects_missing_sdist_for_wheel_sdist_policy(tmp_path: Path) -> None:
    module = _load_module()
    dist = tmp_path / "dist"
    dist.mkdir()
    _write_wheel(dist / "agilab-2026.5.12.post4-py3-none-any.whl")

    with pytest.raises(module.ReleaseArtifactManifestError, match="missing sdist"):
        module.build_manifest(dist, package="agilab", artifact_policy="wheel+sdist")


def test_write_manifests_records_hashes(tmp_path: Path) -> None:
    module = _load_module()
    dist = tmp_path / "dist"
    dist.mkdir()
    _write_wheel(dist / "agilab-2026.5.12.post4-py3-none-any.whl")
    (dist / "agilab-2026.5.12.post4.tar.gz").write_bytes(b"sdist")
    artifacts = module.build_manifest(dist, package="agilab", artifact_policy="wheel+sdist")

    json_path, sums_path = module.write_manifests(
        artifacts,
        output_dir=tmp_path / "evidence",
        output_prefix="agilab",
    )

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "agilab.release_artifact_manifest.v1"
    assert {row["kind"] for row in payload["artifacts"]} == {"wheel", "sdist"}
    sums = sums_path.read_text(encoding="utf-8")
    assert "agilab-2026.5.12.post4-py3-none-any.whl" in sums
    assert "agilab-2026.5.12.post4.tar.gz" in sums
