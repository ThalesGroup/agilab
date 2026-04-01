from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest
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


def test_collect_candidate_roots_expands_relative_paths_from_home(monkeypatch, tmp_path):
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    relative_data = Path("relative/input")
    relative_out = Path("relative/output")

    monkeypatch.setattr(
        orchestrate_execute.Path,
        "home",
        classmethod(lambda cls: home_dir),
    )

    env = SimpleNamespace(
        dataframe_path=relative_data,
        app_data_rel=None,
    )
    roots = orchestrate_execute.collect_candidate_roots(
        env,
        {
            "data_in": str(relative_data),
            "data_out": str(relative_out),
        },
    )

    assert roots == [
        home_dir / relative_data,
        home_dir / relative_out,
    ]


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


def test_find_preview_target_returns_none_when_latest_file_disappears(tmp_path, monkeypatch):
    older_csv = tmp_path / "older.csv"
    older_csv.write_text("a,b\n1,2\n", encoding="utf-8")

    newest_csv = tmp_path / "newest.csv"
    newest_csv.write_text("a,b\n3,4\n", encoding="utf-8")

    original_stat = orchestrate_execute.Path.stat
    newest_calls = {"count": 0}

    def flaky_stat(self: Path, *args, **kwargs):
        if self == newest_csv:
            newest_calls["count"] += 1
            if newest_calls["count"] >= 5:
                raise FileNotFoundError("simulated race")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(orchestrate_execute.Path, "stat", flaky_stat)

    target, files = orchestrate_execute.find_preview_target([older_csv, newest_csv])

    assert target is None
    assert files == [older_csv, newest_csv]


def test_pending_execute_action_round_trip():
    session_state = {}

    assert orchestrate_execute.consume_pending_execute_action(session_state) is None

    orchestrate_execute.queue_pending_execute_action(session_state, "run")
    assert session_state[orchestrate_execute.PENDING_EXECUTE_ACTION_KEY] == "run"
    assert orchestrate_execute.consume_pending_execute_action(session_state) == "run"
    assert orchestrate_execute.consume_pending_execute_action(session_state) is None


def test_render_graph_preview_draws_and_labels_source(monkeypatch):
    calls: list[tuple[str, object]] = []

    fake_st = SimpleNamespace(
        caption=lambda message: calls.append(("caption", message)),
        pyplot=lambda fig, width=None: calls.append(("pyplot", (fig, width))),
    )
    fake_ax = SimpleNamespace(axis=lambda mode: calls.append(("axis", mode)))
    fake_fig = object()
    fake_plt = SimpleNamespace(
        subplots=lambda figsize=None: (fake_fig, fake_ax),
        close=lambda fig: calls.append(("close", fig)),
    )

    monkeypatch.setattr(orchestrate_execute, "st", fake_st)
    monkeypatch.setattr(orchestrate_execute, "plt", fake_plt)
    monkeypatch.setattr(orchestrate_execute.nx, "spring_layout", lambda graph_preview, seed=None: {"n1": (0.0, 0.0)})
    monkeypatch.setattr(orchestrate_execute.nx, "draw_networkx_nodes", lambda *args, **kwargs: calls.append(("nodes", kwargs.get("node_color"))))
    monkeypatch.setattr(orchestrate_execute.nx, "draw_networkx_edges", lambda *args, **kwargs: calls.append(("edges", kwargs.get("alpha"))))
    monkeypatch.setattr(orchestrate_execute.nx, "draw_networkx_labels", lambda *args, **kwargs: calls.append(("labels", kwargs.get("font_size"))))

    graph = orchestrate_execute.nx.Graph()
    graph.add_node("n1")

    orchestrate_execute._render_graph_preview(graph, "preview.json")

    assert ("caption", "Graph preview generated from JSON output") in calls
    assert ("caption", "Source: preview.json") in calls
    assert ("nodes", "skyblue") in calls
    assert ("edges", 0.5) in calls
    assert ("labels", 9) in calls
    assert ("axis", "off") in calls
    assert ("pyplot", (fake_fig, "stretch")) in calls
    assert ("close", fake_fig) in calls


def test_render_graph_preview_requires_matplotlib(monkeypatch):
    monkeypatch.setattr(orchestrate_execute, "plt", None)
    monkeypatch.setattr(orchestrate_execute, "_MATPLOTLIB_IMPORT_ERROR", ModuleNotFoundError("matplotlib"))

    graph = orchestrate_execute.nx.Graph()

    with pytest.raises(RuntimeError, match="matplotlib unavailable"):
        orchestrate_execute._render_graph_preview(graph, None)
