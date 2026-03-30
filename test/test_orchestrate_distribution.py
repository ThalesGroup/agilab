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


orchestrate_distribution = _import_agilab_module("agilab.orchestrate_distribution")


def test_extract_chunk_info_supports_dict_and_tuple_shapes():
    assert orchestrate_distribution.extract_chunk_info(
        {"partition_key": "alpha", "weights_key": 3},
        "partition_key",
        "weights_key",
    ) == ("alpha", 3)
    assert orchestrate_distribution.extract_chunk_info(
        ({"partition": "beta", "weights_key": 5}, 7),
        "partition_key",
        "weights_key",
    ) == ("beta", 7)
    assert orchestrate_distribution.extract_chunk_info(("gamma", 11), "partition_key", "weights_key") == ("gamma", 11)
    assert orchestrate_distribution.extract_chunk_info([], "partition_key", "weights_key") == ("unknown", 1)


def test_show_tree_warns_and_falls_back_for_non_numeric_sizes(monkeypatch):
    calls: list[tuple[str, str, bool, str]] = []
    warnings: list[str] = []

    monkeypatch.setattr(
        orchestrate_distribution,
        "st",
        SimpleNamespace(
            warning=warnings.append,
            error=lambda message: None,
        ),
    )
    monkeypatch.setattr(
        orchestrate_distribution,
        "draw_distribution",
        lambda graph, partition_key, show_leaf_list, title: calls.append(
            (graph.__class__.__name__, partition_key, show_leaf_list, title)
        ),
    )

    orchestrate_distribution.show_tree(
        workers=["127.0.0.1-1"],
        work_plan_metadata=[[{"partition": "p1", "size": "bad"}]],
        work_plan=[[["file1"]]],
        partition_key="partition",
        weights_key="size",
        show_leaf_list=False,
    )

    assert warnings == ["Non-numeric size 'bad' for partition 'p1' treated as 1."]
    assert calls == [("Graph", "partition", False, "Distribution Tree")]


def test_workload_barchart_warns_when_no_data(monkeypatch):
    warnings: list[str] = []
    monkeypatch.setattr(orchestrate_distribution, "st", SimpleNamespace(warning=warnings.append))

    orchestrate_distribution.workload_barchart(
        workers=[],
        work_plan_metadata=[],
        partition_key="partition",
        weights_key="size",
        weights_unit="files",
    )

    assert warnings == ["No data available for workload distribution."]
