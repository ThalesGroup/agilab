"""Manager side scaffolding for the Network Simulation app."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, List, Tuple

import networkx as nx

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


class NetworkSimApp(BaseWorker):
    """Minimal manager that generates synthetic network topologies."""

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
        """Generate a topology immediately in the manager process."""
        return self._generate_and_persist(self.args, self.dir_path)

    def _generate_and_persist(
        self,
        args: NetworkSimArgs,
        output_dir: Path,
    ) -> dict[str, Any]:
        graph = generate_mixed_topology(args.net_size, seed=args.seed)

        gml_path = output_dir / args.topology_filename
        nx.write_gml(graph, gml_path)

        summary = {
            "net_size": args.net_size,
            "seed": args.seed,
            "nodes": graph.number_of_nodes(),
            "edges": graph.number_of_edges(),
            "topology_file": str(gml_path),
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
