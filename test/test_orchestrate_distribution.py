from __future__ import annotations

import importlib
import importlib.util
from types import SimpleNamespace

from pathlib import Path
import sys
import types

import plotly.graph_objects as go
import pytest


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


def _load_module_with_missing(module_name: str, relative_path: str, *missing_modules: str):
    original_import = __import__

    def _patched_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in missing_modules:
            raise ModuleNotFoundError(name)
        return original_import(name, globals, locals, fromlist, level)

    module_path = Path(relative_path)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("builtins.__import__", _patched_import)
        importlib.invalidate_caches()
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module


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


def test_extract_chunk_info_covers_fallback_keys_and_scalar_shape():
    assert orchestrate_distribution.extract_chunk_info(
        {"other": "value"},
        "partition key",
        "weights key",
    ) == ("{'other': 'value'}", 1)
    assert orchestrate_distribution.extract_chunk_info(
        {"partition": "fallback", "weights_key": None, "size": 7},
        "partition key",
        "weights key",
    ) == ("fallback", 7)
    assert orchestrate_distribution.extract_chunk_info(([{"partition": "nested"}],), "partition_key", "weights_key") == ("nested", 1)
    assert orchestrate_distribution.extract_chunk_info("standalone", "partition_key", "weights_key") == ("standalone", 1)


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


def test_show_tree_warns_for_empty_and_reports_invalid_worker_ids(monkeypatch):
    warnings: list[str] = []
    errors: list[str] = []
    calls: list[str] = []
    monkeypatch.setattr(
        orchestrate_distribution,
        "st",
        SimpleNamespace(warning=warnings.append, error=errors.append),
    )
    monkeypatch.setattr(orchestrate_distribution, "draw_distribution", lambda *_args, **_kwargs: calls.append("drawn"))

    orchestrate_distribution.show_tree([], [], [], "partition", "size")
    assert warnings == ["No workers with assigned chunks found."]

    orchestrate_distribution.show_tree(
        workers=["bad-worker-id"],
        work_plan_metadata=[[{"partition": "p1", "size": 3}]],
        work_plan=[[["leaf-a"]]],
        partition_key="partition",
        weights_key="size",
    )
    assert errors == ["Worker identifier 'bad-worker-id' is not in the expected 'ip-number' format."]
    assert calls == ["drawn"]


def test_show_tree_builds_leaf_graph_for_valid_workers(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        orchestrate_distribution,
        "st",
        SimpleNamespace(warning=lambda *_a, **_k: None, error=lambda *_a, **_k: None),
    )
    monkeypatch.setattr(
        orchestrate_distribution,
        "draw_distribution",
        lambda graph, partition_key, show_leaf_list, title: captured.update(
            graph=graph,
            partition_key=partition_key,
            show_leaf_list=show_leaf_list,
            title=title,
        ),
    )

    orchestrate_distribution.show_tree(
        workers=["127.0.0.1-1"],
        work_plan_metadata=[[{"partition": "p1", "size": 4}]],
        work_plan=[[["leaf-a", "leaf-b"]]],
        partition_key="partition",
        weights_key="size",
        show_leaf_list=True,
    )

    graph = captured["graph"]
    assert isinstance(graph, orchestrate_distribution.nx.Graph)
    assert captured["partition_key"] == "partition"
    assert captured["show_leaf_list"] is True
    assert captured["title"] == "Distribution Tree"
    assert "leaf-a" in graph.nodes
    assert "leaf-b" in graph.nodes


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


def test_import_plotly_graph_objects_reports_missing_optional_viz_extra():
    def missing_plotly(_name):
        raise ModuleNotFoundError("plotly")

    with pytest.raises(RuntimeError, match=r"agilab\[viz\]"):
        orchestrate_distribution.import_plotly_graph_objects(missing_plotly)


def test_draw_distribution_requires_matplotlib(monkeypatch):
    monkeypatch.setattr(orchestrate_distribution, "plt", None)
    monkeypatch.setattr(orchestrate_distribution, "Patch", None)
    monkeypatch.setattr(orchestrate_distribution, "_MATPLOTLIB_IMPORT_ERROR", ModuleNotFoundError("missing"))

    with pytest.raises(RuntimeError, match="matplotlib unavailable"):
        orchestrate_distribution.draw_distribution(
            orchestrate_distribution.nx.Graph(),
            "partition",
            False,
            "Demo",
        )


def test_draw_distribution_renders_graph_and_legend(monkeypatch):
    calls = {"legend": 0, "pyplot": 0}

    class FakeAxis:
        def text(self, *_args, **_kwargs):
            return None

    fake_plt = SimpleNamespace(
        figure=lambda **_kwargs: None,
        margins=lambda **_kwargs: None,
        gca=lambda: FakeAxis(),
        legend=lambda **_kwargs: calls.__setitem__("legend", calls["legend"] + 1),
        tight_layout=lambda: None,
        title=lambda *_args, **_kwargs: None,
        axis=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(orchestrate_distribution, "plt", fake_plt)
    monkeypatch.setattr(orchestrate_distribution, "Patch", lambda **kwargs: kwargs)
    monkeypatch.setattr(
        orchestrate_distribution,
        "st",
        SimpleNamespace(pyplot=lambda *_args, **_kwargs: calls.__setitem__("pyplot", calls["pyplot"] + 1)),
    )
    monkeypatch.setattr(orchestrate_distribution.nx, "draw_networkx_nodes", lambda *_a, **_k: None)
    monkeypatch.setattr(orchestrate_distribution.nx, "draw_networkx_edges", lambda *_a, **_k: None)
    monkeypatch.setattr(orchestrate_distribution.nx, "draw_networkx_labels", lambda *_a, **_k: None)
    monkeypatch.setattr(orchestrate_distribution.nx, "draw_networkx_edge_labels", lambda *_a, **_k: None)

    graph = orchestrate_distribution.nx.Graph()
    graph.add_node("ip", level=0)
    graph.add_node("worker", level=1)
    graph.add_edge("ip", "worker", weight=2)

    orchestrate_distribution.draw_distribution(graph, "partition", False, "Demo")

    assert calls == {"legend": 1, "pyplot": 1}


def test_draw_distribution_renders_leaf_list_nodes_when_enabled(monkeypatch):
    calls = {"legend": 0, "pyplot": 0}
    node_calls: list[list[str]] = []

    class FakeAxis:
        def text(self, *_args, **_kwargs):
            return None

    fake_plt = SimpleNamespace(
        figure=lambda **_kwargs: None,
        margins=lambda **_kwargs: None,
        gca=lambda: FakeAxis(),
        legend=lambda **_kwargs: calls.__setitem__("legend", calls["legend"] + 1),
        tight_layout=lambda: None,
        title=lambda *_args, **_kwargs: None,
        axis=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(orchestrate_distribution, "plt", fake_plt)
    monkeypatch.setattr(orchestrate_distribution, "Patch", lambda **kwargs: kwargs)
    monkeypatch.setattr(
        orchestrate_distribution,
        "st",
        SimpleNamespace(pyplot=lambda *_args, **_kwargs: calls.__setitem__("pyplot", calls["pyplot"] + 1)),
    )
    monkeypatch.setattr(
        orchestrate_distribution.nx,
        "draw_networkx_nodes",
        lambda _graph, _pos, nodelist, **_kwargs: node_calls.append(list(nodelist)),
    )
    monkeypatch.setattr(orchestrate_distribution.nx, "draw_networkx_edges", lambda *_a, **_k: None)
    monkeypatch.setattr(orchestrate_distribution.nx, "draw_networkx_edge_labels", lambda *_a, **_k: None)

    graph = orchestrate_distribution.nx.Graph()
    graph.add_node("ip", level=0)
    graph.add_node("worker", level=1)
    graph.add_node("partition", level=2)
    graph.add_node("leaf-a", level=3)
    graph.add_edge("ip", "worker", weight=2)

    orchestrate_distribution.draw_distribution(graph, "partition", True, "Demo")

    assert ["leaf-a"] in node_calls
    assert calls == {"legend": 1, "pyplot": 1}


def test_show_graph_warns_for_empty_and_invalid_workers(monkeypatch):
    warnings: list[str] = []
    errors: list[str] = []
    calls: list[str] = []
    monkeypatch.setattr(
        orchestrate_distribution,
        "st",
        SimpleNamespace(warning=warnings.append, error=errors.append),
    )
    monkeypatch.setattr(orchestrate_distribution, "draw_distribution", lambda *_args, **_kwargs: calls.append("drawn"))

    orchestrate_distribution.show_graph([], [], [], "partition", "size")
    assert warnings == ["No workers with assigned chunks found."]

    orchestrate_distribution.show_graph(
        workers=["bad-worker-id"],
        work_plan_metadata=[[{"partition": "p1", "size": 3}]],
        work_plan=[[("node", [])]],
        partition_key="partition",
        weights_key="size",
    )
    assert errors == ["Worker identifier 'bad-worker-id' is not in the expected 'ip-number' format."]
    assert calls == ["drawn"]


def test_show_graph_builds_leaf_graph_for_valid_workers(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        orchestrate_distribution,
        "st",
        SimpleNamespace(warning=lambda *_a, **_k: None, error=lambda *_a, **_k: None),
    )
    monkeypatch.setattr(
        orchestrate_distribution,
        "draw_distribution",
        lambda graph, partition_key, show_leaf_list, title: captured.update(
            graph=graph,
            partition_key=partition_key,
            show_leaf_list=show_leaf_list,
            title=title,
        ),
    )

    orchestrate_distribution.show_graph(
        workers=["127.0.0.1-1"],
        work_plan_metadata=[[{"partition": "p1", "size": "bad"}]],
        work_plan=[[("node", ["leaf-a", "leaf-b"])]],
        partition_key="partition",
        weights_key="size",
        show_leaf_list=True,
    )

    graph = captured["graph"]
    assert isinstance(graph, orchestrate_distribution.nx.DiGraph)


def test_show_graph_accepts_single_value_items_without_dependencies(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        orchestrate_distribution,
        "st",
        SimpleNamespace(warning=lambda *_a, **_k: None, error=lambda *_a, **_k: None),
    )
    monkeypatch.setattr(
        orchestrate_distribution,
        "draw_distribution",
        lambda graph, partition_key, show_leaf_list, title: captured.update(
            graph=graph,
            partition_key=partition_key,
            show_leaf_list=show_leaf_list,
            title=title,
        ),
    )

    orchestrate_distribution.show_graph(
        workers=["127.0.0.1-1"],
        work_plan_metadata=[[{"partition": "p1", "size": "bad"}]],
        work_plan=[[("node-only",)]],
        partition_key="partition",
        weights_key="size",
        show_leaf_list=True,
    )

    graph = captured["graph"]
    assert isinstance(graph, orchestrate_distribution.nx.DiGraph)
    assert captured["title"] == "Workplan"
    assert "p1\nfiles: 0 size" in graph.nodes
    assert "node-only" not in graph.nodes


def test_orchestrate_distribution_import_fallback_sets_matplotlib_error():
    module = _load_module_with_missing(
        "agilab.orchestrate_distribution_no_matplotlib",
        "src/agilab/orchestrate_distribution.py",
        "matplotlib.pyplot",
    )

    assert module.plt is None
    assert module.Patch is None
    assert isinstance(module._MATPLOTLIB_IMPORT_ERROR, ModuleNotFoundError)


def test_orchestrate_distribution_import_fallback_sets_networkx_error():
    module = _load_module_with_missing(
        "agilab.orchestrate_distribution_no_networkx",
        "src/agilab/orchestrate_distribution.py",
        "networkx",
    )
    warnings: list[str] = []

    module.st = SimpleNamespace(warning=warnings.append)

    assert module.nx is None
    assert isinstance(module._NETWORKX_IMPORT_ERROR, ModuleNotFoundError)
    module.show_tree(["127.0.0.1-0"], [[("p1", 1)]], [[["file.csv"]]], "partition", "size")
    assert warnings
    assert "agilab[ui]" in warnings[0]


def test_orchestrate_page_import_survives_missing_networkx():
    module_name = "agilab_page_orchestrate_missing_networkx"
    module_path = Path("src/agilab/pages/2_ORCHESTRATE.py")
    original_import = __import__
    removed_modules = {
        name: sys.modules.pop(name, None)
        for name in ("agilab.orchestrate_distribution", "agilab.orchestrate_execute")
    }

    def _patched_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in {"networkx", "networkx.readwrite"}:
            raise ModuleNotFoundError(name)
        return original_import(name, globals, locals, fromlist, level)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("builtins.__import__", _patched_import)
        importlib.invalidate_caches()
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        finally:
            for name, previous in removed_modules.items():
                if previous is not None:
                    sys.modules[name] = previous

    assert callable(module.show_graph)
    assert callable(module.render_execute_section)


def test_workload_barchart_emits_plotly_figure(monkeypatch):
    plotted = []

    class FakeBar:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeFigure:
        def __init__(self):
            self.traces = []
            self.annotations = []
            self.layout = {}

        def add_trace(self, trace):
            self.traces.append(trace)

        def update_layout(self, **kwargs):
            self.layout.update(kwargs)

        def add_annotation(self, **kwargs):
            self.annotations.append(kwargs)

    monkeypatch.setattr(go, "Figure", FakeFigure)
    monkeypatch.setattr(go, "Bar", FakeBar)
    monkeypatch.setattr(
        orchestrate_distribution,
        "st",
        SimpleNamespace(plotly_chart=lambda fig, **_kwargs: plotted.append(fig), warning=lambda *_a, **_k: None),
    )

    orchestrate_distribution.workload_barchart(
        workers=["127.0.0.1-1"],
        work_plan_metadata=[[{"partition": "alpha", "size": 3}, {"partition": "beta", "size": 2}]],
        partition_key="partition",
        weights_key="size",
        weights_unit="files",
    )

    assert len(plotted) == 1
    assert len(plotted[0].traces) == 2
    assert plotted[0].layout["legend_title"] == "Partition"


def test_workload_barchart_aggregates_partition_totals_and_annotations(monkeypatch):
    plotted = []

    class FakeBar:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeFigure:
        def __init__(self):
            self.traces = []
            self.annotations = []
            self.layout = {}

        def add_trace(self, trace):
            self.traces.append(trace)

        def update_layout(self, **kwargs):
            self.layout.update(kwargs)

        def add_annotation(self, **kwargs):
            self.annotations.append(kwargs)

    monkeypatch.setattr(go, "Figure", FakeFigure)
    monkeypatch.setattr(go, "Bar", FakeBar)
    monkeypatch.setattr(
        orchestrate_distribution,
        "st",
        SimpleNamespace(plotly_chart=lambda fig, **_kwargs: plotted.append(fig), warning=lambda *_a, **_k: None),
    )

    orchestrate_distribution.workload_barchart(
        workers=["127.0.0.1-1", "127.0.0.1-2"],
        work_plan_metadata=[
            [{"partition": "alpha", "size": 3}, {"partition": "alpha", "size": 2}],
            [{"partition": "beta", "size": 4}],
        ],
        partition_key="partition",
        weights_key="size",
        weights_unit="files",
    )

    figure = plotted[0]
    assert len(figure.traces) == 2
    assert figure.traces[0].kwargs["y"] == [5]
    assert len(figure.annotations) == 2
    assert figure.layout["yaxis_title"] == "Size (files)"
