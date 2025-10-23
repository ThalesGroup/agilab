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

        data_uri = Path(args.data_uri).expanduser()
        if env._is_managed_pc:
            home = Path.home()
            data_uri = Path(str(data_uri).replace(str(home), str(home / "MyApp")))

        data_uri.mkdir(parents=True, exist_ok=True)
        self.dir_path = data_uri
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
        payload["data_uri"] = str(self.dir_path)
        return payload

    def simulate(self) -> dict[str, Any]:
        """Generate a topology immediately in the manager process."""

        return self._generate_and_persist(self.args, self.dir_path)

    def _generate_and_persist(self, args: NetworkSimArgs, output_dir: Path) -> dict[str, Any]:
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

    def build_distribution(
        self,
        workers: dict[str, int],
    ) -> Tuple[List[List], List[List[Tuple[str, int]]], str, str, str]:
        """Create a simple distribution plan with a single generation task."""

        job_args = self.as_dict()
        task = ({"functions name": "generate_topology", "args": job_args}, [])

        worker_slots = max(1, sum(workers.values()) if workers else 1)
        plan = [[] for _ in range(worker_slots)]
        metadata = [[] for _ in range(worker_slots)]
        plan[0].append(task)
        metadata[0].append(("generate_topology", 1))
        return plan, metadata, "job", "count", "weight"


# Backwards-compatible alias expected by the dispatcher
class NetworkSim(NetworkSimApp):
    pass


__all__ = ["NetworkSim", "NetworkSimApp"]
