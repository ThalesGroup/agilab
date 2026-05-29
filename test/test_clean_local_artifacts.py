from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "clean_local_artifacts.py"

spec = importlib.util.spec_from_file_location("clean_local_artifacts", MODULE_PATH)
assert spec is not None and spec.loader is not None
clean_local_artifacts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(clean_local_artifacts)


def _seed_stale_build_libs(root: Path) -> list[Path]:
    targets = [
        root / "src/agilab/core/agi-env/build/lib",
        root / "src/agilab/core/agi-node/build/lib",
    ]
    for target in targets:
        target.mkdir(parents=True)
        (target / "stale.py").write_text("VALUE = 1\n", encoding="utf-8")
    return targets


def test_clean_stale_build_libs_dry_run_keeps_existing_trees(tmp_path: Path) -> None:
    targets = _seed_stale_build_libs(tmp_path)

    results = clean_local_artifacts.clean_stale_build_libs(tmp_path, apply=False)

    assert [result.action for result in results] == ["would-remove", "would-remove"]
    assert [result.path for result in results] == [
        "src/agilab/core/agi-env/build/lib",
        "src/agilab/core/agi-node/build/lib",
    ]
    assert all(target.exists() for target in targets)


def test_clean_stale_build_libs_apply_removes_existing_trees(tmp_path: Path) -> None:
    targets = _seed_stale_build_libs(tmp_path)

    results = clean_local_artifacts.clean_stale_build_libs(tmp_path, apply=True)

    assert [result.action for result in results] == ["removed", "removed"]
    assert all(not target.exists() for target in targets)


def test_clean_stale_build_libs_reports_missing_trees(tmp_path: Path) -> None:
    results = clean_local_artifacts.clean_stale_build_libs(tmp_path, apply=True)

    assert [result.action for result in results] == ["missing", "missing"]
