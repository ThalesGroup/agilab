from __future__ import annotations

import importlib
from types import SimpleNamespace

from pathlib import Path
import sys
import types


def _import_agilab_module(module_name: str):
    src_root = Path(__file__).resolve().parents[1] / "src"
    package_root = src_root / "agilab"
    src_root_str = str(src_root)
    package_root_str = str(package_root)
    if src_root_str not in sys.path:
        sys.path.insert(0, src_root_str)
    pkg = sys.modules.get("agilab")
    if pkg is None or not hasattr(pkg, "__path__"):
        pkg = types.ModuleType("agilab")
        pkg.__path__ = [package_root_str]
        sys.modules["agilab"] = pkg
    else:
        package_path = list(pkg.__path__)
        if package_root_str not in package_path:
            pkg.__path__ = [package_root_str, *package_path]
    importlib.invalidate_caches()
    return importlib.import_module(module_name)


orchestrate_execute = _import_agilab_module("agilab.orchestrate_execute")


def test_collect_candidate_roots_deduplicates_paths(tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir()

    env = SimpleNamespace(
        dataframe_path=shared,
        app_data_rel=shared,
    )
    roots = orchestrate_execute.collect_candidate_roots(
        env,
        {
            "data_in": str(shared),
            "data_out": str(shared / "out"),
        },
    )

    assert roots == [shared, shared / "out"]


def test_find_preview_target_ignores_empty_and_metadata_files(tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    empty_csv = output_dir / "empty.csv"
    empty_csv.write_text("")

    metadata_csv = output_dir / "._artifact.csv"
    metadata_csv.write_text("metadata")

    valid_csv = output_dir / "artifact.csv"
    valid_csv.write_text("a,b\n1,2\n")

    target, files = orchestrate_execute.find_preview_target([output_dir])

    assert target == valid_csv
    assert files == [valid_csv]


def test_pending_execute_action_round_trip():
    session_state = {}

    assert orchestrate_execute.consume_pending_execute_action(session_state) is None

    orchestrate_execute.queue_pending_execute_action(session_state, "run")
    assert session_state[orchestrate_execute.PENDING_EXECUTE_ACTION_KEY] == "run"
    assert orchestrate_execute.consume_pending_execute_action(session_state) == "run"
    assert orchestrate_execute.consume_pending_execute_action(session_state) is None
