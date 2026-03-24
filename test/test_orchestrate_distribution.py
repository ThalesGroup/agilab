from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


def _load_module():
    module_path = Path("src/agilab/orchestrate_distribution.py")
    spec = importlib.util.spec_from_file_location("agilab_orchestrate_distribution_tests", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_extract_chunk_info_supports_dict_and_tuple_shapes():
    module = _load_module()

    assert module.extract_chunk_info(
        {"partition_key": "alpha", "weights_key": 3},
        "partition_key",
        "weights_key",
    ) == ("alpha", 3)
    assert module.extract_chunk_info(
        ({"partition": "beta", "weights_key": 5}, 7),
        "partition_key",
        "weights_key",
    ) == ("beta", 7)
    assert module.extract_chunk_info(("gamma", 11), "partition_key", "weights_key") == ("gamma", 11)
    assert module.extract_chunk_info([], "partition_key", "weights_key") == ("unknown", 1)


def test_show_tree_warns_and_falls_back_for_non_numeric_sizes(monkeypatch):
    module = _load_module()
    calls: list[tuple[str, str, bool, str]] = []
    warnings: list[str] = []

    monkeypatch.setattr(
        module,
        "st",
        SimpleNamespace(
            warning=warnings.append,
            error=lambda message: None,
        ),
    )
    monkeypatch.setattr(
        module,
        "draw_distribution",
        lambda graph, partition_key, show_leaf_list, title: calls.append(
            (graph.__class__.__name__, partition_key, show_leaf_list, title)
        ),
    )

    module.show_tree(
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
    module = _load_module()
    warnings: list[str] = []
    monkeypatch.setattr(module, "st", SimpleNamespace(warning=warnings.append))

    module.workload_barchart(
        workers=[],
        work_plan_metadata=[],
        partition_key="partition",
        weights_key="size",
        weights_unit="files",
    )

    assert warnings == ["No data available for workload distribution."]
