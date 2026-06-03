from __future__ import annotations

import glob
import json
import logging
from pathlib import Path
from typing import Any

import networkx as nx
import pandas as pd
import plotly.graph_objects as go
from IPython.display import Markdown

logger = logging.getLogger(__name__)


def _coerce_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_items = value.replace(";", ",").replace("\n", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        raw_items = [str(item) for item in value]
    else:
        raw_items = [str(value)]
    items: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        cleaned = str(item).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        items.append(cleaned)
    return items


def _read_toml_dict(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    try:
        candidate = Path(path).expanduser()
    except (OSError, RuntimeError, TypeError, ValueError):
        return {}
    if not candidate.exists():
        return {}
    try:
        import tomllib

        with open(candidate, "rb") as handle:
            payload = tomllib.load(handle)
    except (OSError, ValueError, tomllib.TOMLDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _page_setting_sources(export_payload: dict[str, Any]) -> list[dict[str, Any]]:
    page_key = "view_maps_network"
    sources: list[dict[str, Any]] = []
    for candidate in (
        Path(export_payload.get("artifact_dir") or "") / "app_settings.toml",
        export_payload.get("app_settings_file"),
    ):
        payload = _read_toml_dict(candidate)
        if not payload:
            continue
        direct = payload.get(page_key)
        if isinstance(direct, dict):
            sources.append(direct)
        pages = payload.get("pages")
        if isinstance(pages, dict):
            nested = pages.get(page_key)
            if isinstance(nested, dict):
                sources.append(nested)
    return sources


def _first_nonempty_setting(sources: list[dict[str, Any]], *keys: str) -> str:
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in keys:
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _setting_list(sources: list[dict[str, Any]], *keys: str) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in keys:
            for item in _coerce_str_list(source.get(key)):
                if item in seen:
                    continue
                seen.add(item)
                items.append(item)
    return items


def _candidate_base_dirs(export_payload: dict[str, Any], sources: list[dict[str, Any]]) -> list[Path]:
    artifact_dir = Path(export_payload.get("artifact_dir") or ".").expanduser()
    roots: list[Path] = [
        artifact_dir,
        artifact_dir / "pipeline",
        Path.home() / "localshare",
        Path.home() / "export",
    ]
    subdirs = _setting_list(sources, "dataset_subpath", "datadir_rel")
    for base in list(roots):
        for subdir in subdirs:
            roots.append(base / subdir)
    unique: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        try:
            resolved = root.expanduser().resolve(strict=False)
        except (OSError, RuntimeError, TypeError, ValueError):
            resolved = root.expanduser()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def _resolve_declared_path(value: str, base_dirs: list[Path]) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    for base in base_dirs:
        candidate = (base / raw).expanduser()
        if candidate.exists():
            return candidate
    return None


def _expand_globs(patterns: list[str], base_dirs: list[Path]) -> list[Path]:
    matches: list[Path] = []
    seen: set[Path] = set()
    for raw_pattern in patterns:
        pattern = str(raw_pattern or "").strip()
        if not pattern:
            continue
        path = Path(pattern).expanduser()
        candidates = [str(path)] if path.is_absolute() else [str(base / pattern) for base in base_dirs]
        for candidate in candidates:
            for match in glob.glob(candidate, recursive=True):
                path_match = Path(match).expanduser()
                if not path_match.is_file():
                    continue
                try:
                    resolved = path_match.resolve(strict=False)
                except (OSError, RuntimeError, TypeError, ValueError):
                    resolved = path_match
                if resolved in seen:
                    continue
                seen.add(resolved)
                matches.append(resolved)
    matches.sort(key=lambda path: path.stat().st_mtime if path.exists() else 0.0, reverse=True)
    return matches


def _discover_topology_path(sources: list[dict[str, Any]], base_dirs: list[Path]) -> Path | None:
    declared = _first_nonempty_setting(sources, "edges_file")
    resolved = _resolve_declared_path(declared, base_dirs)
    if resolved and resolved.exists():
        return resolved
    patterns = [
        "pipeline/topology.gml",
        "pipeline/ilp_topology.gml",
        "pipeline/topology.json",
        "network_sim/pipeline/topology.gml",
        "network_sim/pipeline/ilp_topology.gml",
        "network_sim/pipeline/topology.json",
    ]
    matches = _expand_globs(patterns, base_dirs)
    return matches[0] if matches else None


def _discover_trajectory_paths(sources: list[dict[str, Any]], base_dirs: list[Path]) -> list[Path]:
    patterns = _setting_list(sources, "traj_glob", "default_traj_globs")
    if not patterns:
        patterns = [
            "flight_trajectory/pipeline/*.csv",
            "flight_trajectory/pipeline/*.parquet",
            "*trajectory*/pipeline/*.csv",
            "*trajectory*/pipeline/*.parquet",
        ]
    return _expand_globs(patterns, base_dirs)


def _load_graph(path: Path | None) -> nx.Graph | None:
    if path is None or not path.exists():
        return None
    try:
        return nx.read_gml(path)
    except Exception:
        logger.debug("Unable to load %s as GML graph", path, exc_info=True)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.debug("Unable to load %s as JSON graph", path, exc_info=True)
        return None
    graph = nx.Graph()
    if isinstance(payload, dict):
        for node in payload.get("nodes", []) or []:
            if isinstance(node, dict):
                node_id = str(node.get("id", "") or "").strip()
                if node_id:
                    graph.add_node(node_id, **{k: v for k, v in node.items() if k != "id"})
            elif node is not None:
                graph.add_node(str(node))
        for edge in payload.get("edges", []) or []:
            if isinstance(edge, dict):
                source = str(edge.get("source", "") or "").strip()
                target = str(edge.get("target", "") or "").strip()
                if source and target:
                    graph.add_edge(source, target, **{k: v for k, v in edge.items() if k not in {"source", "target"}})
            elif isinstance(edge, (list, tuple)) and len(edge) >= 2:
                graph.add_edge(str(edge[0]), str(edge[1]))
    elif isinstance(payload, list):
        for edge in payload:
            if isinstance(edge, (list, tuple)) and len(edge) >= 2:
                graph.add_edge(str(edge[0]), str(edge[1]))
    return graph if graph.number_of_nodes() else None


def _load_frame(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".parquet", ".pq", ".parq"}:
        return pd.read_parquet(path)
    return pd.read_csv(path)


def _first_column(columns: dict[str, str], *names: str) -> str:
    for name in names:
        candidate = columns.get(name)
        if candidate:
            return candidate
    return ""


def _best_id_column(df: pd.DataFrame) -> str:
    lowered = {column.lower(): column for column in df.columns}
    for candidate in (
        "plane_id",
        "trajectory_id",
        "node_id",
        "flight_id",
        "id",
        "plane_label",
        "stable_flight_id",
        "sat_name",
        "name",
        "callsign",
        "call_sign",
    ):
        column = lowered.get(candidate)
        if column:
            return column
    return ""


def _load_positions(paths: list[Path]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in paths:
        try:
            df = _load_frame(path)
        except Exception:
            logger.debug("Skipping unreadable trajectory artifact %s", path, exc_info=True)
            continue
        lowered = {column.lower(): column for column in df.columns}
        time_col = _first_column(lowered, "time_s", "t_now_s", "time", "t", "time_index")
        lat_col = _first_column(lowered, "latitude", "lat")
        lon_col = _first_column(lowered, "longitude", "lon", "long")
        alt_col = _first_column(lowered, "alt_m", "altitude_m", "altitude", "alt")
        id_col = _best_id_column(df)
        if not (time_col and lat_col and lon_col and id_col):
            continue
        subset = pd.DataFrame(
            {
                "node_id": df[id_col].astype(str),
                "time_value": pd.to_numeric(df[time_col], errors="coerce"),
                "lat": pd.to_numeric(df[lat_col], errors="coerce"),
                "lon": pd.to_numeric(df[lon_col], errors="coerce"),
                "alt": pd.to_numeric(df[alt_col], errors="coerce") if alt_col else 0.0,
            }
        ).dropna(subset=["node_id", "lat", "lon"])
        if subset.empty:
            continue
        subset["source_file"] = str(path)
        subset = subset.sort_values("time_value")
        frames.append(subset.groupby("node_id", as_index=False).tail(1))
    if not frames:
        return pd.DataFrame(columns=["node_id", "lat", "lon", "alt", "source_file"])
    result = pd.concat(frames, ignore_index=True)
    return result.groupby("node_id", as_index=False).tail(1).reset_index(drop=True)


def _geo_map_figure(graph: nx.Graph | None, positions: pd.DataFrame, *, title: str) -> go.Figure:
    fig = go.Figure()
    pos_index = positions.set_index("node_id", drop=False)
    if graph is not None:
        edge_lons: list[float | None] = []
        edge_lats: list[float | None] = []
        for source, target in graph.edges():
            if str(source) not in pos_index.index or str(target) not in pos_index.index:
                continue
            src = pos_index.loc[str(source)]
            dst = pos_index.loc[str(target)]
            edge_lons.extend([float(src["lon"]), float(dst["lon"]), None])
            edge_lats.extend([float(src["lat"]), float(dst["lat"]), None])
        if edge_lons:
            fig.add_trace(
                go.Scattergeo(
                    lon=edge_lons,
                    lat=edge_lats,
                    mode="lines",
                    line=dict(width=1.5, color="#5b6c87"),
                    opacity=0.7,
                    name="Topology",
                    hoverinfo="skip",
                )
            )
    fig.add_trace(
        go.Scattergeo(
            lon=positions["lon"],
            lat=positions["lat"],
            text=positions["node_id"],
            mode="markers+text",
            textposition="top center",
            marker=dict(size=9, color="#1f77b4", line=dict(width=1, color="#ffffff")),
            name="Nodes",
            hovertemplate="Node: %{text}<br>Lat: %{lat}<br>Lon: %{lon}<extra></extra>",
        )
    )
    fig.update_layout(
        title=title,
        height=620,
        margin=dict(l=10, r=10, t=50, b=10),
        geo=dict(
            projection_type="equirectangular",
            showland=True,
            landcolor="#eef3f8",
            showcountries=True,
            countrycolor="#b9c4d0",
            showocean=True,
            oceancolor="#dbe8f4",
            fitbounds="locations",
        ),
        legend=dict(orientation="h"),
    )
    return fig


def _topology_figure(graph: nx.Graph, *, title: str) -> go.Figure:
    pos = nx.spring_layout(graph, seed=42)
    edge_x: list[float | None] = []
    edge_y: list[float | None] = []
    for source, target in graph.edges():
        x0, y0 = pos[source]
        x1, y1 = pos[target]
        edge_x.extend([x0, x1, None])
        edge_y.extend([y0, y1, None])
    node_x = [pos[node][0] for node in graph.nodes()]
    node_y = [pos[node][1] for node in graph.nodes()]
    node_text = [str(node) for node in graph.nodes()]
    fig = go.Figure(
        data=[
            go.Scatter(x=edge_x, y=edge_y, mode="lines", line=dict(width=1.2, color="#8fa0bc"), hoverinfo="skip"),
            go.Scatter(
                x=node_x,
                y=node_y,
                mode="markers+text",
                text=node_text,
                textposition="top center",
                marker=dict(size=10, color="#1f77b4"),
                hovertemplate="Node: %{text}<extra></extra>",
            ),
        ]
    )
    fig.update_layout(
        title=title,
        height=620,
        margin=dict(l=10, r=10, t=50, b=10),
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        showlegend=False,
    )
    return fig


def _summary_markdown(
    *,
    title: str,
    topology_path: Path | None,
    trajectory_paths: list[Path],
    graph: nx.Graph | None,
    positions: pd.DataFrame,
    expected_artifacts: list[str],
    checked_roots: list[Path],
) -> Markdown:
    lines = [f"#### {title}", ""]
    if topology_path is not None:
        lines.append(f"- Topology source: `{topology_path}`")
    else:
        lines.append("- Topology source: not found")
    if trajectory_paths:
        lines.append(f"- Trajectory files: {len(trajectory_paths)}")
        lines.append(f"  - First match: `{trajectory_paths[0]}`")
    else:
        lines.append("- Trajectory files: none found")
    if graph is not None:
        lines.append(f"- Graph nodes/edges: {graph.number_of_nodes()} / {graph.number_of_edges()}")
    if not positions.empty:
        lines.append(f"- Positioned nodes: {len(positions)}")
    if graph is None and positions.empty:
        lines.extend(
            [
                "",
                "No notebook-native map could be rendered because no topology or trajectory artifacts were found.",
            ]
        )
        if expected_artifacts:
            lines.append("- Expected artifacts:")
            lines.extend(f"  - `{artifact}`" for artifact in expected_artifacts)
        lines.append("- Checked roots:")
        lines.extend(f"  - `{root}`" for root in checked_roots)
    return Markdown("\n".join(lines))


def render_inline(*, page: str, record: dict[str, Any], export_payload: dict[str, Any]) -> list[Any]:
    sources = _page_setting_sources(export_payload)
    base_dirs = _candidate_base_dirs(export_payload, sources)
    topology_path = _discover_topology_path(sources, base_dirs)
    trajectory_paths = _discover_trajectory_paths(sources, base_dirs)
    graph = _load_graph(topology_path)
    positions = _load_positions(trajectory_paths)
    title = str(record.get("label") or page or "Maps Network")
    outputs: list[Any] = [
        _summary_markdown(
            title=title,
            topology_path=topology_path,
            trajectory_paths=trajectory_paths,
            graph=graph,
            positions=positions,
            expected_artifacts=[str(item) for item in record.get("artifacts", [])],
            checked_roots=base_dirs,
        )
    ]
    if not positions.empty:
        outputs.append(_geo_map_figure(graph, positions, title=title))
    elif graph is not None:
        outputs.append(_topology_figure(graph, title=title))
    return outputs
