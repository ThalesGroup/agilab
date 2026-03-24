from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


def _load_module():
    module_path = Path("src/agilab/orchestrate_execute.py")
    spec = importlib.util.spec_from_file_location("agilab_orchestrate_execute_tests", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_collect_candidate_roots_deduplicates_paths(tmp_path):
    module = _load_module()
    shared = tmp_path / "shared"
    shared.mkdir()

    env = SimpleNamespace(
        dataframe_path=shared,
        app_data_rel=shared,
    )
    roots = module.collect_candidate_roots(
        env,
        {
            "data_in": str(shared),
            "data_out": str(shared / "out"),
        },
    )

    assert roots == [shared, shared / "out"]


def test_find_preview_target_ignores_empty_and_metadata_files(tmp_path):
    module = _load_module()
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    empty_csv = output_dir / "empty.csv"
    empty_csv.write_text("")

    metadata_csv = output_dir / "._artifact.csv"
    metadata_csv.write_text("metadata")

    valid_csv = output_dir / "artifact.csv"
    valid_csv.write_text("a,b\n1,2\n")

    target, files = module.find_preview_target([output_dir])

    assert target == valid_csv
    assert files == [valid_csv]
