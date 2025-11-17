"""Manager side scaffolding for the Network Simulation app."""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

import networkx as nx
import numpy as np
import pandas as pd

from agi_node.agi_dispatcher import BaseWorker, WorkDispatcher

from .network_sim_args import (
    ArgsOverrides,
    NetworkSimArgs,
    dump_args,
    ensure_defaults,
    load_args,
    merge_args,
)
from .topology import generate_mixed_topology

logger = logging.getLogger(__name__)

DEMAND_QUANTILE = 0.95
PLANE_ID_RE = re.compile(r"plane[_-]?(\d+)")


@dataclass(frozen=True)
class DemandRecord:
    flow_id: str
    source: int
    destination: int
    bandwidth: float
    latency: float


@dataclass(frozen=True)
class LinkRecord:
    source: int
    target: int
    capacity: float
    latency: float
    snr: float | None = None
    bearer: str = "ivdl"


def _resolve_child_path(root: Path, candidate: Path) -> Path:
    """Return an absolute path ensuring ``candidate`` lives under ``root`` when relative."""

    path = candidate.expanduser()
    if path.is_absolute():
        return path
    return (root / path).expanduser()


def _load_node_metadata(flows_dir: Path) -> Dict[int, dict[str, Any]]:
    nodes_path = flows_dir / "nodes_ip.json"
    topology_path = flows_dir / "topology.json"
    if not nodes_path.exists():
        raise FileNotFoundError(
            f"nodes_ip.json not found under {flows_dir}. Did you populate the FlowSynth dataset?"
        )
    if not topology_path.exists():
        raise FileNotFoundError(
            f"topology.json not found under {flows_dir}. Did you export the FlowSynth topology?"
        )

    nodes_ip = json.loads(nodes_path.read_text(encoding="utf-8"))
    graph = nx.read_gml(topology_path, destringizer=int)

    nodes: Dict[int, dict[str, Any]] = {}
    for node_id, attrs in graph.nodes(data=True):
        record: dict[str, Any] = {
            "label": attrs.get("label", str(node_id)),
            "type": attrs.get("type", ""),
            "ip": nodes_ip.get(str(node_id), ""),
        }
        for coord_key in ("x_position", "y_position", "z_position", "lat", "lon"):
            if coord_key in attrs:
                record[coord_key] = attrs[coord_key]
        nodes[node_id] = record
    return nodes


def _iter_traffic_files(root: Path):
    for route_dir in root.glob("RouteID=*"):
        if not route_dir.is_dir():
            continue
        for candidate in route_dir.iterdir():
            if candidate.name.startswith("_") or not candidate.is_file():
                continue
            yield candidate


def _read_frame(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".parquet", ".pq", ".parq"}:
        return pd.read_parquet(path)
    return pd.read_csv(path)


def _load_flow_demands(traffic_dir: Path) -> List[DemandRecord]:
    if not traffic_dir.exists():
        raise FileNotFoundError(
            f"FlowSynth traffic directory '{traffic_dir}' is missing. Ensure traffic-gen.ipynb was executed."
        )

    aggregates: Dict[str, dict[str, Any]] = {}

    for file_path in _iter_traffic_files(traffic_dir):
        try:
            frame = _read_frame(file_path)
        except Exception as exc:  # pragma: no cover - diagnostics aid
            logger.warning("Skipping %s: failed to load dataframe (%s)", file_path, exc)
            continue

        required = {"FlowID", "SrcID", "DstID", "bandwidth", "latency"}
        if not required.issubset(frame.columns):
            logger.warning("Skipping %s: missing required columns %s", file_path, sorted(required))
            continue

        frame = frame[list(required)].copy()
        frame["FlowID"] = frame["FlowID"].astype(str)
        frame["SrcID"] = frame["SrcID"].astype(int)
        frame["DstID"] = frame["DstID"].astype(int)
        frame["bandwidth"] = frame["bandwidth"].astype(float)
        frame["latency"] = frame["latency"].astype(float)

        for flow_id, group in frame.groupby("FlowID"):
            payload = aggregates.setdefault(
                flow_id,
                {
                    "source": int(group["SrcID"].iloc[0]),
                    "destination": int(group["DstID"].iloc[0]),
                    "bandwidth": [],
                    "latency": [],
                },
            )
            payload["bandwidth"].extend(group["bandwidth"].tolist())
            payload["latency"].extend(group["latency"].tolist())

    demands: List[DemandRecord] = []
    for flow_id, payload in aggregates.items():
        samples = payload["bandwidth"]
        if not samples:
            continue
        bw = float(np.quantile(samples, DEMAND_QUANTILE))
        lat_samples = payload["latency"]
        latency = float(np.quantile(lat_samples, DEMAND_QUANTILE)) if lat_samples else 0.0
        demands.append(
            DemandRecord(
                flow_id=flow_id,
                source=payload["source"],
                destination=payload["destination"],
                bandwidth=bw,
                latency=latency,
            )
        )

    return demands


def _extract_plane_id(label: str) -> int | None:
    match = PLANE_ID_RE.search(label)
    if match:
        return int(match.group(1))
    digits = "".join(ch for ch in label if ch.isdigit())
    return int(digits) if digits else None


def _extract_float(payload: dict[str, Any], key: str) -> float | None:
    value = payload.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _classify_bearer(capacity: float, latency: float) -> str:
    if latency >= 150:
        return "Sat"
    if capacity >= 5_000:
        return "Opt"
    return "ivdl"


def _load_link_metrics(link_dir: Path) -> Dict[Tuple[int, int], LinkRecord]:
    if not link_dir.exists():
        raise FileNotFoundError(
            f"LinkSim output directory '{link_dir}' is missing. Run the LinkSim worker first."
        )

    aggregates: dict[Tuple[int, int], dict[str, list[float]]] = defaultdict(
        lambda: {"capacity": [], "latency": [], "snr": []}
    )

    for result_file in sorted(link_dir.glob("*_vision.json")):
        source_label = result_file.stem.replace("_vision", "")
        src_id = _extract_plane_id(source_label)
        if src_id is None:
            logger.warning("Unable to infer plane id from %s", source_label)
            continue

        try:
            payload = json.loads(result_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:  # pragma: no cover - unexpected runtime issue
            logger.warning("Skipping %s: invalid JSON (%s)", result_file, exc)
            continue

        rows = payload.get("data") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            logger.warning("Skipping %s: unexpected JSON structure", result_file)
            continue

        for entry in rows:
            if not isinstance(entry, dict):
                continue
            for column, value in entry.items():
                if not column.startswith("antenna_") or not isinstance(value, dict):
                    continue
                for target_label, metrics in value.items():
                    dst_id = _extract_plane_id(str(target_label))
                    if dst_id is None:
                        continue

                    capacity = _extract_float(metrics, "Shannon_capacity_Mbps")
                    if capacity is None:
                        continue
                    latency = _extract_float(metrics, "lag_ms")
                    snr = _extract_float(metrics, "SNR")

                    bucket = aggregates[(src_id, dst_id)]
                    bucket["capacity"].append(capacity)
                    if latency is not None:
                        bucket["latency"].append(latency)
                    if snr is not None:
                        bucket["snr"].append(snr)

    links: Dict[Tuple[int, int], LinkRecord] = {}
    for (src, dst), bucket in aggregates.items():
        if not bucket["capacity"]:
            continue
        capacity = float(np.median(bucket["capacity"]))
        latency = float(np.median(bucket["latency"])) if bucket["latency"] else 0.0
        snr = float(np.median(bucket["snr"])) if bucket["snr"] else None
        bearer = _classify_bearer(capacity, latency)
        links[(src, dst)] = LinkRecord(
            source=src,
            target=dst,
            capacity=capacity,
            latency=max(latency, 0.0),
            snr=snr,
            bearer=bearer,
        )

    return links


def _build_graph(nodes: Dict[int, dict[str, Any]], links: Dict[Tuple[int, int], LinkRecord]) -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    for node_id, attrs in nodes.items():
        node_attrs = {"label": attrs.get("label", str(node_id))}
        if attrs.get("type"):
            node_attrs["type"] = attrs["type"]
        if attrs.get("ip"):
            node_attrs["ip"] = attrs["ip"]
        for coord_key in ("x_position", "y_position", "z_position", "lat", "lon"):
            if attrs.get(coord_key) is not None:
                node_attrs[coord_key] = attrs[coord_key]
        graph.add_node(node_id, **node_attrs)

    edge_id = 1
    for metrics in links.values():
        edge_attrs = {
            "bearer": metrics.bearer,
            "capacity": float(metrics.capacity),
            "latency": float(metrics.latency),
        }
        if metrics.snr is not None:
            edge_attrs["snr"] = float(metrics.snr)
        graph.add_edge(metrics.source, metrics.target, id=edge_id, **edge_attrs)
        edge_id += 1

    return graph


class NetworkSimApp(BaseWorker):
    """Generate ILP-ready topology/flow datasets from FlowSynth and LinkSim outputs."""

    worker_vars: dict[str, Any] = {}
    _FLIGHT_SUFFIXES = (".parquet", ".pq", ".parq", ".csv")
    _EXCLUDE_BASENAME = {"beams", "satellites", "norad_3le", "topology", "topology_summary"}

    def __init__(
        self,
        env,
        args: NetworkSimArgs | None = None,
        **overrides: ArgsOverrides,
    ) -> None:
        super().__init__()
        self.env = env

        if args is None:
            allowed = set(NetworkSimArgs.model_fields.keys())
            clean = {k: v for k, v in overrides.items() if k in allowed}
            if extra := set(overrides) - allowed:
                logger.debug("Ignoring extra NetworkSimArgs keys: %s", sorted(extra))
            args = NetworkSimArgs(**clean)

        args = ensure_defaults(args, env=env)
        self.args = args

        data_in = self._resolve_data_dir(env, args.data_in)
        data_in.mkdir(parents=True, exist_ok=True)
        self.dir_path = data_in
        self.args.data_in = data_in
        WorkDispatcher.args = self.as_dict()

    @classmethod
    def from_toml(
        cls,
        env,
        settings_path: str | Path = "app_settings.toml",
        section: str = "args",
        **overrides: ArgsOverrides,
    ) -> "NetworkSimApp":
        base = load_args(settings_path, section=section)
        merged = ensure_defaults(merge_args(base, overrides or None), env=env)
        return cls(env, args=merged)

    def to_toml(
        self,
        settings_path: str | Path = "app_settings.toml",
        section: str = "args",
        create_missing: bool = True,
    ) -> None:
        dump_args(self.args, settings_path, section=section, create_missing=create_missing)

    def as_dict(self) -> dict[str, Any]:
        payload = self.args.model_dump(mode="json")
        payload["data_in"] = str(self.dir_path)
        return payload

    def simulate(self) -> dict[str, Any]:
        """Generate the ILP dataset immediately in the manager process."""
        return self._generate_and_persist(self.args, self.dir_path)

    def _generate_and_persist(
        self,
        args: NetworkSimArgs,
        output_dir: Path,
    ) -> dict[str, Any]:
        flows_dir = _resolve_child_path(output_dir, args.flows_dir)
        link_dir = _resolve_child_path(output_dir, args.link_results_dir)

        nodes = _load_node_metadata(flows_dir)
        demands = _load_flow_demands(flows_dir / "traffic_df")
        links = _load_link_metrics(link_dir)

        if not links:
            raise FileNotFoundError(
                f"No link budget artefacts found under '{link_dir}'. Run LinkSim first."
            )

        graph = _build_graph(nodes, links)
        gml_path = output_dir / args.topology_filename
        gml_path.parent.mkdir(parents=True, exist_ok=True)
        nx.write_gml(graph, gml_path)

        demands_payload = [
            {
                "flow_id": demand.flow_id,
                "source": demand.source,
                "destination": demand.destination,
                "bandwidth": demand.bandwidth,
                "latency": demand.latency,
            }
            for demand in demands
        ]
        demands_path = output_dir / args.demands_filename
        demands_path.parent.mkdir(parents=True, exist_ok=True)
        demands_path.write_text(json.dumps(demands_payload, indent=2), encoding="utf-8")

        summary = {
            "nodes": graph.number_of_nodes(),
            "edges": graph.number_of_edges(),
            "flows": len(demands_payload),
            "topology_file": str(gml_path),
            "demands_file": str(demands_path),
        }

        summary_path = output_dir / args.summary_filename
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

        return summary

    def _discover_flight_files(self) -> List[Path]:
        """Return the list of flight simulation artefacts available for dispatch."""
        base = self.dir_path

        search_roots = [
            base / "dataframe" / "flights",
            base / "dataframe" / "flight_simulation",
            base / "dataframe",
            base / "flights",
            base / "flight_simulation",
            base / "csv",
            base / "parquet",
            base,
        ]

        ordered: list[Path] = []
        seen: set[Path] = set()

        for root in search_roots:
            if not root.exists() or not root.is_dir():
                continue

            candidates: list[Path] = []
            for suffix in self._FLIGHT_SUFFIXES:
                candidates.extend(sorted(root.glob(f"*{suffix}")))

            if root == base:
                candidates = [
                    path
                    for path in candidates
                    if path.stem.lower() not in self._EXCLUDE_BASENAME
                ]

            filtered = [
                path
                for path in candidates
                if not path.name.startswith("._") and path.is_file()
            ]

            for path in filtered:
                if path not in seen:
                    ordered.append(path)
                    seen.add(path)

            if filtered and root != base:
                # Prefer the first dedicated directory that contains data.
                break

        return ordered

    def build_distribution(
        self,
        workers: dict[str, int],
    ) -> Tuple[List[List], List[List[Tuple[str, int]]], str, str, str]:
        """Partition flight simulation artefacts across workers."""
        flight_files = self._discover_flight_files()
        if not flight_files:
            raise FileNotFoundError(
                f"No flight simulation files found under '{self.dir_path}'."
            )

        worker_slots = max(1, sum(workers.values()) if workers else 1)
        plan: List[List[Tuple[dict[str, Any], list[str]]]] = [[] for _ in range(worker_slots)]
        metadata: List[List[Tuple[str, int]]] = [[] for _ in range(worker_slots)]

        for index, flight_path in enumerate(flight_files):
            worker_idx = index % worker_slots
            try:
                rel_path = str(flight_path.relative_to(self.dir_path))
            except ValueError:
                rel_path = str(flight_path)

            plan[worker_idx].append(
                (
                    {
                        "functions name": "work_pool",
                        "args": rel_path,
                    },
                    [],
                )
            )

            try:
                weight = int(flight_path.stat().st_size)
            except OSError:
                weight = 1

            metadata[worker_idx].append((flight_path.stem or f"flight_{index}", weight))

        return plan, metadata, "flight", "files", "bytes"


class NetworkSim(NetworkSimApp):
    """Backwards-compatible alias expected by legacy installers."""


__all__ = ["NetworkSimApp", "NetworkSim"]
