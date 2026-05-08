from __future__ import annotations

import ast
import importlib
import importlib.util
import json
from pathlib import Path
import sys
import types


def _load_module(module_name: str, relative_path: str):
    module_path = Path(relative_path)
    importlib.invalidate_caches()
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


pipeline_views = _load_module("agilab.pipeline_views", "src/agilab/pipeline_views.py")


def test_pipeline_extracts_app_and_agi_run_kwargs():
    code = """
APP = "flight_trajectory_project"
AGI.run(
    data_in=str(share / "flight_trajectory/dataset"),
    data_out=share / "flight_trajectory/pipeline",
    report_out=output_dir,
)
"""

    assert pipeline_views._pipeline_extract_app_name(code) == "flight_trajectory_project"
    kind, kwargs = pipeline_views._pipeline_find_agi_call(code)
    assert kind == "run"
    assert kwargs["data_in"] == "share / flight_trajectory/dataset"
    assert kwargs["data_out"] == "share / flight_trajectory/pipeline"
    assert kwargs["report_out"] == "output_dir"


def test_load_pipeline_conceptual_dot_accepts_json_schema(tmp_path):
    payload = {
        "direction": "LR",
        "nodes": [
            {"id": "a", "label": "State"},
            {"id": "b", "label": "Decision"},
        ],
        "edges": [{"source": "a", "target": "b", "label": "flow"}],
    }
    view_file = tmp_path / "pipeline_view.json"
    view_file.write_text(json.dumps(payload), encoding="utf-8")

    path, dot = pipeline_views.load_pipeline_conceptual_dot(env=None, lab_dir=tmp_path)

    assert path == view_file
    assert "digraph PipelineConceptual" in dot
    assert 'rankdir="LR"' in dot
    assert 'a -> b [label="flow"]' in dot


def test_build_pipeline_graph_data_infers_artifact_edge_over_sequence():
    entries = [
        {
            "Q": "Generate topology",
            "R": "agi.run",
            "C": 'APP = "network_sim_project"\nAGI.run(data_out=share / "network/pipeline")',
        },
        {
            "Q": "Train PPO-GNN routing policy",
            "R": "agi.run",
            "C": 'APP = "sb3_trainer_project"\nAGI.run(data_in=share / "network/pipeline", data_out=share / "trainer/output")',
        },
    ]

    nodes, sequence_edges, artefact_edges = pipeline_views._build_pipeline_graph_data(entries)

    assert [node["group"] for node in nodes] == ["sim", "trainer"]
    assert sequence_edges == []
    assert artefact_edges == [{"source": 0, "target": 1, "label": "share / network/pipeline"}]


def test_pipeline_format_io_items_hides_redundant_names():
    items = {"data_in": "share / dataset", "weights_in": "weights.json"}

    rendered = pipeline_views._pipeline_format_io_items(items, {"data_in"})

    assert rendered == "share / dataset, weights_in=weights.json"


def test_pipeline_view_helper_functions_cover_text_group_and_labels():
    assert pipeline_views._pipeline_role_from_question(" \nPlan route\nThen execute") == "Plan route"
    assert pipeline_views._pipeline_role_from_question(None) == ""
    assert pipeline_views._pipeline_step_kind({"R": "agi.install"}) == "install"
    assert pipeline_views._pipeline_step_kind({"R": "runpy"}) == "python"
    assert pipeline_views._pipeline_group_from_project("flight_trajectory_project") == "trajectory"
    assert pipeline_views._pipeline_group_from_project("") == ""
    assert "\n" in pipeline_views._pipeline_wrap_text("alpha beta gamma delta", width=8)
    assert pipeline_views._pipeline_graphviz_escape('a"b\\c\nd') == 'a\\"b\\\\c\\nd'
    assert pipeline_views._pipeline_edge_label("share / path / artefact") == "share / path / artefact"
    assert pipeline_views._pipeline_format_io_items({"data_out": "demo.csv"}, {"data_out"}) == "demo.csv"


def test_pipeline_expr_inference_and_candidate_discovery(tmp_path):
    code = (
        'APP = "demo_project"\n'
        'AGI.install(data_in=str(root / "dataset"), data_out=share / "demo/output")\n'
    )
    inferred = pipeline_views._pipeline_infer_entry(1, {"Q": "Prepare demo", "R": "", "C": code})

    assert inferred["project"] == "demo_project"
    assert inferred["kind"] == "install"
    assert inferred["consumes"] == {"data_in": "root / dataset"}
    assert inferred["produces"] == {"data_out": "share / demo/output"}
    assert "2. Prepare demo" in pipeline_views._pipeline_graphviz_label(inferred)

    active_app = tmp_path / "active_app"
    app_src = tmp_path / "app_src"
    lab_dir = tmp_path / "lab"
    for root in (active_app, app_src, lab_dir):
        root.mkdir()
    env = type("Env", (), {"active_app": active_app, "app_src": app_src})()

    candidates = pipeline_views._pipeline_conceptual_view_candidates(env, lab_dir)

    assert candidates[0] == active_app / "pipeline_view.dot"
    assert candidates[1] == active_app / "pipeline_view.json"
    assert lab_dir / "pipeline_view.dot" in candidates


def test_pipeline_extract_app_name_regex_fallback_and_expr_helpers(monkeypatch):
    assert pipeline_views._pipeline_extract_app_name('APP = "regex_project"\nif broken') == "regex_project"
    assert pipeline_views._pipeline_extract_app_name("APP =\n") == ""
    assert pipeline_views._pipeline_expr_to_text(ast.parse('"literal"', mode="eval").body) == "literal"
    assert pipeline_views._pipeline_expr_to_text(ast.parse('str(root / "demo")', mode="eval").body) == "root / demo"
    assert pipeline_views._pipeline_expr_to_text(ast.parse('root / "demo"', mode="eval").body) == "root / demo"
    monkeypatch.setattr(pipeline_views.ast, "unparse", lambda _node: (_ for _ in ()).throw(RuntimeError("boom")))
    assert pipeline_views._pipeline_expr_to_text(ast.parse("value", mode="eval").body) == ""


def test_pipeline_view_helpers_cover_guard_and_duplicate_branches(monkeypatch):
    assert pipeline_views._pipeline_role_from_question(" \n\t ") == ""
    assert pipeline_views._pipeline_extract_app_name('APP: str = "annotated_project"\nprint(APP)') == "annotated_project"
    assert pipeline_views._pipeline_find_agi_call("if broken(") == ("", {})
    assert pipeline_views._pipeline_find_agi_call("tool.run(data_in='x')") == ("", {})
    assert pipeline_views._pipeline_find_agi_call("AGI.serve(data_in='x')") == ("", {})
    assert pipeline_views._pipeline_group_from_project("   ") == ""
    assert pipeline_views._pipeline_wrap_text("   ", width=8) == ""
    assert pipeline_views._pipeline_edge_label("") == ""

    class BrokenPathInput:
        pass

    broken_env = type("Env", (), {"active_app": BrokenPathInput(), "app_src": None})()
    assert pipeline_views._pipeline_conceptual_view_candidates(broken_env, None) == []

    original_expanduser = pipeline_views.Path.expanduser

    def _raise_for_boom(self):
        if self.name == "boom-root":
            raise RuntimeError("boom")
        return original_expanduser(self)

    monkeypatch.setattr(pipeline_views.Path, "expanduser", _raise_for_boom, raising=False)
    flaky_env = type("Env", (), {"active_app": "boom-root", "app_src": None})()
    assert pipeline_views._pipeline_conceptual_view_candidates(flaky_env, None) == []

    nodes, sequence_edges, artefact_edges = pipeline_views._build_pipeline_graph_data(
        [
            {"Q": "Produce", "R": "agi.run", "C": 'APP = "demo_project"\nAGI.run(data_out=share / "demo/out")'},
            {"Q": "Blank consume", "R": "agi.run", "C": 'APP = "demo_project"\nAGI.run(data_in="")'},
            {"Q": "Missing consume", "R": "agi.run", "C": 'APP = "demo_project"\nAGI.run(data_in=share / "missing/out")'},
            {
                "Q": "Duplicate consume",
                "R": "agi.run",
                "C": (
                    'APP = "demo_project"\n'
                    'AGI.run(data_in=share / "demo/out", report_in=share / "demo/out")'
                ),
            },
        ]
    )

    assert len(nodes) == 4
    assert artefact_edges == [{"source": 0, "target": 3, "label": "share / demo/out"}]
    assert sequence_edges == [{"source": 0, "target": 1}, {"source": 1, "target": 2}, {"source": 2, "target": 3}]


def test_pipeline_dot_from_json_honors_inline_dot_and_skips_invalid_entries():
    assert pipeline_views._pipeline_dot_from_json({"dot": " digraph X { a -> b } "}) == "digraph X { a -> b }"

    dot = pipeline_views._pipeline_dot_from_json(
        {
            "nodes": [{"id": "a", "label": "Alpha"}, {"label": "missing-id"}, "bad"],
            "edges": [
                {"source": "a", "target": "b", "label": "flow"},
                {"source": "", "target": "b"},
                "bad",
            ],
        }
    )

    assert 'a [label="Alpha"]' in dot
    assert 'a -> b [label="flow"]' in dot
    assert "missing-id" not in dot


def test_load_pipeline_conceptual_dot_prefers_dot_and_logs_invalid_json(monkeypatch, tmp_path):
    dot_file = tmp_path / "pipeline_view.dot"
    dot_file.write_text("digraph Demo { a -> b }", encoding="utf-8")

    path, dot = pipeline_views.load_pipeline_conceptual_dot(env=None, lab_dir=tmp_path)

    assert path == dot_file
    assert dot == "digraph Demo { a -> b }"

    dot_file.unlink()
    (tmp_path / "pipeline_view.json").write_text("{bad json", encoding="utf-8")
    warnings: list[str] = []
    monkeypatch.setattr(pipeline_views.logger, "warning", lambda *args: warnings.append(str(args[0])))

    path, dot = pipeline_views.load_pipeline_conceptual_dot(env=None, lab_dir=tmp_path)

    assert path is None
    assert dot == ""
    assert warnings


def test_build_pipeline_graph_data_adds_sequence_edges_for_non_artifact_steps():
    entries = [
        {"Q": "Install demo", "R": "agi.install", "C": 'APP = "demo_project"\nAGI.install(data_out=share / "demo/out")'},
        {"Q": "Explain result", "R": "runpy", "C": "print('done')"},
    ]

    nodes, sequence_edges, artefact_edges = pipeline_views._build_pipeline_graph_data(entries)

    assert nodes[0]["kind"] == "install"
    assert nodes[1]["kind"] == "python"
    assert artefact_edges == []
    assert sequence_edges == [{"source": 0, "target": 1}]


def test_render_pipeline_view_emits_graph_and_table(monkeypatch):
    captured = {"graphviz": [], "frames": []}

    class FakeExpander:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    fake_column_config = types.SimpleNamespace(TextColumn=lambda label, **kwargs: {"label": label, **kwargs})
    fake_st = types.SimpleNamespace(
        expander=lambda *args, **kwargs: FakeExpander(),
        graphviz_chart=lambda graph, **kwargs: captured["graphviz"].append((graph, kwargs)),
        dataframe=lambda frame, **kwargs: captured["frames"].append((frame, kwargs)),
        column_config=fake_column_config,
    )
    monkeypatch.setattr(pipeline_views, "st", fake_st)

    entries = [
        {
            "Q": "Install assets",
            "R": "agi.install",
            "C": 'APP = "demo_project"\nAGI.install(data_out=share / "demo/out")',
        },
        {
            "Q": "Run experiment",
            "R": "agi.run",
            "C": 'APP = "demo_project"\nAGI.run(data_in=share / "demo/out", report_out=share / "demo/report")',
        },
    ]

    pipeline_views.render_pipeline_view(entries, title="Custom pipeline")

    assert captured["graphviz"]
    graph_source, graph_kwargs = captured["graphviz"][0]
    assert "digraph Pipeline" in graph_source
    assert 'fillcolor="#f6f0ff"' in graph_source
    assert 'fillcolor="#eef8f1"' in graph_source
    assert graph_kwargs["width"] == "content"

    frame, frame_kwargs = captured["frames"][0]
    assert list(frame["stage"]) == ["1", "2"]
    assert frame_kwargs["width"] == "stretch"
    assert frame_kwargs["hide_index"] is True
    assert "column_config" in frame_kwargs


def test_render_pipeline_view_returns_early_when_no_entries(monkeypatch):
    fake_st = types.SimpleNamespace(
        expander=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("should not run")),
        graphviz_chart=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("should not run")),
        dataframe=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("should not run")),
        column_config=types.SimpleNamespace(TextColumn=lambda *args, **kwargs: None),
    )
    monkeypatch.setattr(pipeline_views, "st", fake_st)

    pipeline_views.render_pipeline_view([])
