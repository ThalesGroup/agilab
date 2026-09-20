"""Standalone exports must retain both Iris builds and reject either tampered bundle."""
import importlib.util
from pathlib import Path
import shutil

import pytest

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "hf_notebook_export", ROOT / "tools/demos/hf_notebook_demo_export.py"
)
exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exporter)


def test_standalone_export_includes_both_verified_iris_bundles(tmp_path):
    exporter.export(tmp_path / "space")
    for resource in exporter.RESOURCE_PATHS:
        for name in exporter.VERIFIED_FILES | {"LICENSE", "result.json"}:
            assert (tmp_path / "space" / resource / name).read_bytes() == (
                ROOT / resource / name
            ).read_bytes()
        assert resource in (tmp_path / "space/Dockerfile").read_text()


@pytest.mark.parametrize("resource", exporter.RESOURCE_PATHS)
def test_standalone_export_rejects_tampering_in_either_iris_bundle(tmp_path, resource):
    source = tmp_path / "source"
    for name in exporter.SOURCE_FILES:
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    (source / resource / "app.py").write_text("raise AssertionError('tampered')")
    with pytest.raises(ValueError, match="Demo artifact changed"):
        exporter.export(tmp_path / "space", source_root=source)
    assert not (tmp_path / "space").exists()
