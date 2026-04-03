from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path
import sys


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
