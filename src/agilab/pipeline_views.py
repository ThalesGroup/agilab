from __future__ import annotations

import ast
import json
import logging
import re
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

from agi_env import AgiEnv

logger = logging.getLogger(__name__)


def _pipeline_role_from_question(question: Any) -> str:
    """Return the first non-empty line of the question as the inferred role."""
    if not isinstance(question, str):
        return ""
    for line in question.splitlines():
        cleaned = line.strip()
        if cleaned:
            return cleaned
    return ""


def _pipeline_step_kind(entry: Dict[str, Any]) -> str:
    """Infer the execution kind from the saved engine marker."""
    raw = str(entry.get("R", "") or "").strip().lower()
    if raw == "agi.install":
        return "install"
    if raw == "agi.run":
        return "run"
    if raw == "runpy":
        return "python"
    return raw or "stage"


def _pipeline_expr_to_text(node: ast.AST) -> str:
    """Convert an AST expression to a short display string."""
    try:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            left = _pipeline_expr_to_text(node.left)
            right = _pipeline_expr_to_text(node.right)
            if left and right:
                return f"{left} / {right}"
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "str"
            and len(node.args) == 1
            and not node.keywords
        ):
            return _pipeline_expr_to_text(node.args[0])
        return ast.unparse(node).strip()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return ""


def _pipeline_extract_app_name(code: str) -> str:
    """Extract APP = '...' from a stage snippet."""
    if not isinstance(code, str) or not code.strip():
        return ""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        match = re.search(r'^\s*APP\s*=\s*[\'"]([^\'"]+)[\'"]', code, re.MULTILINE)
        return match.group(1).strip() if match else ""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "APP":
                    return _pipeline_expr_to_text(node.value)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "APP" and node.value is not None:
                return _pipeline_expr_to_text(node.value)
    return ""


def _pipeline_find_agi_call(code: str) -> Tuple[str, Dict[str, str]]:
    """Return the AGI call kind and its keyword args inferred from snippet code."""
    if not isinstance(code, str) or not code.strip():
        return "", {}
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return "", {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if not isinstance(func.value, ast.Name) or func.value.id != "AGI":
            continue
        if func.attr not in {"run", "install"}:
            continue
        kwargs: Dict[str, str] = {}
        for kw in node.keywords:
            if kw.arg:
                kwargs[kw.arg] = _pipeline_expr_to_text(kw.value)
        return func.attr, kwargs
    return "", {}


def _pipeline_group_from_project(project: str) -> str:
    """Return the compact group suffix derived from the project name."""
    stem = str(project or "").strip().removesuffix("_project")
    if not stem:
        return ""
    return stem.split("_")[-1]


def _pipeline_wrap_text(text: str, width: int) -> str:
    """Wrap text without truncating it."""
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    return textwrap.fill(
        cleaned,
        width=width,
        break_long_words=False,
        break_on_hyphens=False,
    )


def _pipeline_graphviz_escape(value: Any) -> str:
    """Escape a value for Graphviz string attributes."""
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _pipeline_conceptual_view_candidates(env: Optional[AgiEnv], lab_dir: Optional[Path]) -> List[Path]:
    """Return candidate locations for an app-provided conceptual pipeline view."""
    names = ("pipeline_view.dot", "pipeline_view.json")
    roots: List[Path] = []
    if env is not None:
        for raw in (
            getattr(env, "active_app", None),
            getattr(env, "app_src", None),
        ):
            if raw:
                try:
                    roots.append(Path(raw))
                except (RuntimeError, TypeError):
                    pass
    if lab_dir is not None:
        roots.append(Path(lab_dir))

    candidates: List[Path] = []
    seen: set[Path] = set()
    for root in roots:
        try:
            resolved_root = root.expanduser().resolve()
        except (OSError, RuntimeError):
            continue
        for name in names:
            candidate = resolved_root / name
            if candidate not in seen:
                candidates.append(candidate)
                seen.add(candidate)
    return candidates


def _pipeline_dot_from_json(payload: Dict[str, Any]) -> str:
    """Build a Graphviz DOT graph from a small JSON conceptual-view schema."""
    dot_inline = payload.get("dot")
    if isinstance(dot_inline, str) and dot_inline.strip():
        return dot_inline.strip()

    graph_attrs = {
        "rankdir": str(payload.get("direction", "TB")),
        "bgcolor": "transparent",
        "nodesep": str(payload.get("nodesep", "0.24")),
        "ranksep": str(payload.get("ranksep", "0.45")),
        "splines": str(payload.get("splines", "polyline")),
        "concentrate": str(payload.get("concentrate", "true")).lower(),
    }
    graph_attrs.update({str(k): str(v) for k, v in (payload.get("graph") or {}).items()})
    node_defaults = {
        "shape": "box",
        "style": "rounded,filled",
        "color": "#c7d2e4",
        "fontname": "Helvetica",
        "fontsize": "10",
        "penwidth": "1.0",
        "margin": "0.18,0.10",
    }
    node_defaults.update({str(k): str(v) for k, v in (payload.get("node") or {}).items()})
    edge_defaults = {
        "fontname": "Helvetica",
        "fontsize": "9",
        "color": "#93a4c2",
    }
    edge_defaults.update({str(k): str(v) for k, v in (payload.get("edge") or {}).items()})

    def _attrs(attrs: Dict[str, Any]) -> str:
        items = [f'{key}="{_pipeline_graphviz_escape(value)}"' for key, value in attrs.items()]
        return ", ".join(items)

    lines = [
        "digraph PipelineConceptual {",
        f"  graph [{_attrs(graph_attrs)}];",
        f"  node [{_attrs(node_defaults)}];",
        f"  edge [{_attrs(edge_defaults)}];",
    ]
    for node in payload.get("nodes", []) or []:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id", "")).strip()
        if not node_id:
            continue
        attrs = {str(k): str(v) for k, v in node.items() if k != "id"}
        lines.append(f"  {node_id} [{_attrs(attrs)}];")
    for edge in payload.get("edges", []) or []:
        if not isinstance(edge, dict):
            continue
        source = str(edge.get("source", "")).strip()
        target = str(edge.get("target", "")).strip()
        if not source or not target:
            continue
        attrs = {str(k): str(v) for k, v in edge.items() if k not in {"source", "target"}}
        attr_suffix = f" [{_attrs(attrs)}]" if attrs else ""
        lines.append(f"  {source} -> {target}{attr_suffix};")
    lines.append("}")
    return "\n".join(lines)


def load_pipeline_conceptual_dot(env: Optional[AgiEnv], lab_dir: Optional[Path]) -> Tuple[Optional[Path], str]:
    """Load an app-provided conceptual pipeline view when available."""
    for candidate in _pipeline_conceptual_view_candidates(env, lab_dir):
        if not candidate.is_file():
            continue
        try:
            if candidate.suffix.lower() == ".dot":
                return candidate, candidate.read_text(encoding="utf-8").strip()
            if candidate.suffix.lower() == ".json":
                payload = json.loads(candidate.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    dot = _pipeline_dot_from_json(payload).strip()
                    if dot:
                        return candidate, dot
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.warning("Failed to load conceptual pipeline view from %s: %s", candidate, exc)
    return None, ""


def _pipeline_infer_entry(step_index: int, entry: Dict[str, Any]) -> Dict[str, Any]:
    """Infer pipeline metadata from a lab stage entry."""
    code = str(entry.get("C", "") or "")
    role = _pipeline_role_from_question(entry.get("Q", ""))
    project = _pipeline_extract_app_name(code)
    agi_call_kind, kwargs = _pipeline_find_agi_call(code)
    consumes = {key: value for key, value in kwargs.items() if key.endswith("_in")}
    produces = {key: value for key, value in kwargs.items() if key.endswith("_out")}
    kind = _pipeline_step_kind(entry)
    if kind == "stage" and agi_call_kind:
        kind = agi_call_kind
    group = _pipeline_group_from_project(project)
    return {
        "index": step_index,
        "label": f"{step_index + 1}",
        "role": role or f"Stage {step_index + 1}",
        "kind": kind,
        "project": project,
        "group": group,
        "consumes": consumes,
        "produces": produces,
    }


def _pipeline_edge_label(value: str) -> str:
    """Shorten an inferred artefact path for graph labels."""
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.replace("\\n", " ").replace("\n", " ")
    return _pipeline_wrap_text(text, width=30)


def _pipeline_format_io_items(items: Dict[str, str], redundant_keys: set[str]) -> str:
    """Format inferred IO items while hiding redundant generic arg names."""
    rendered: List[str] = []
    for key, value in items.items():
        if key in redundant_keys:
            rendered.append(str(value))
        else:
            rendered.append(f"{key}={value}")
    return ", ".join(rendered)


def _pipeline_graphviz_label(step_meta: Dict[str, Any]) -> str:
    """Build a compact Graphviz label for a stage node."""
    role = _pipeline_wrap_text(
        str(step_meta.get("role", "") or f"Stage {step_meta.get('index', 0) + 1}"),
        width=38,
    )
    group = str(step_meta.get("group", "") or "")
    kind = str(step_meta.get("kind", "") or "")
    parts = [f"{step_meta.get('index', 0) + 1}. {role}"]
    footer = " · ".join(part for part in (group, kind) if part)
    if footer:
        parts.append(_pipeline_wrap_text(footer, width=24))
    return "\n".join(parts).replace('"', '\\"')


def _build_pipeline_graph_data(step_entries: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Infer nodes, sequence edges, and artefact edges for the pipeline view."""
    nodes = [_pipeline_infer_entry(index, entry) for index, entry in enumerate(step_entries)]
    artefact_edges: List[Dict[str, Any]] = []
    produced_by_value: Dict[str, int] = {}
    for node in nodes:
        for value in node["produces"].values():
            value_key = str(value or "").strip()
            if value_key and value_key not in produced_by_value:
                produced_by_value[value_key] = int(node["index"])
    existing_pairs = set()
    for node in nodes:
        for value in node["consumes"].values():
            value_key = str(value or "").strip()
            if not value_key:
                continue
            source_index = produced_by_value.get(value_key)
            target_index = int(node["index"])
            if source_index is None or source_index == target_index:
                continue
            pair = (source_index, target_index)
            if pair in existing_pairs:
                continue
            existing_pairs.add(pair)
            artefact_edges.append(
                {
                    "source": source_index,
                    "target": target_index,
                    "label": _pipeline_edge_label(value_key),
                }
            )
    sequence_edges: List[Dict[str, Any]] = []
    for source_index in range(max(0, len(nodes) - 1)):
        pair = (source_index, source_index + 1)
        if pair in existing_pairs:
            continue
        sequence_edges.append({"source": source_index, "target": source_index + 1})
    return nodes, sequence_edges, artefact_edges


def render_pipeline_view(step_entries: List[Dict[str, Any]], *, title: str = "Pipeline view") -> None:
    """Render an inferred pipeline graph and metadata table inside an expander."""
    if not step_entries:
        return
    nodes, sequence_edges, artefact_edges = _build_pipeline_graph_data(step_entries)
    with st.expander(title, expanded=False):
        graph_lines = [
            "digraph Pipeline {",
            '  graph [rankdir=TB, bgcolor="transparent", nodesep="0.18", ranksep="0.45", splines=polyline, concentrate=true];',
            '  node [shape=box, style="rounded,filled", color="#c7d2e4", fontname="Helvetica", fontsize=9, penwidth=1.0, margin="0.34,0.14", width=2.9];',
            '  edge [fontname="Helvetica", fontsize=8, color="#93a4c2", minlen=1];',
        ]
        for node in nodes:
            node_id = f"step_{node['index']}"
            if node["kind"] == "install":
                fill = "#f6f0ff"
            elif node["kind"] == "run":
                fill = "#eef8f1"
            else:
                fill = "#f6f8fc"
            graph_lines.append(f'  {node_id} [label="{_pipeline_graphviz_label(node)}", fillcolor="{fill}"];')
        for edge in sequence_edges:
            graph_lines.append(
                f'  step_{edge["source"]} -> step_{edge["target"]} [style=dashed, color="#c5cfdf", arrowhead=vee];'
            )
        for edge in artefact_edges:
            label = str(edge.get("label", "") or "").replace('"', '\\"')
            label_clause = f', label="{label}"' if label else ""
            graph_lines.append(
                f'  step_{edge["source"]} -> step_{edge["target"]} [color="#4f6fbf", penwidth=1.7, arrowhead=vee{label_clause}];'
            )
        graph_lines.append("}")
        st.graphviz_chart("\n".join(graph_lines), width="content")

        rows = []
        for node in nodes:
            rows.append(
                {
                    "stage": node["label"],
                    "role": node["role"],
                    "group": node["group"],
                    "in": _pipeline_format_io_items(node["consumes"], {"data_in"}),
                    "out": _pipeline_format_io_items(node["produces"], {"data_out"}),
                }
            )
        st.dataframe(
            pd.DataFrame(rows),
            width="stretch",
            hide_index=True,
            column_config={
                "stage": st.column_config.TextColumn("stage", width="small"),
                "role": st.column_config.TextColumn("role", width="medium"),
                "group": st.column_config.TextColumn("group", width="small"),
                "in": st.column_config.TextColumn("in", width="large"),
                "out": st.column_config.TextColumn("out", width="large"),
            },
        )
