"""Manager side scaffolding for the ILP application."""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

from agi_env import AgiEnv
from agi_node.agi_dispatcher import BaseWorker, WorkDispatcher

from .ilp_args import (
    IlpArgs,
    dump_args,
    ensure_defaults,
    load_args,
    merge_args,
)
from ilp_worker import Demand, Flyenv, MILP

logger = logging.getLogger(__name__)


class IlpApp(BaseWorker):
    """Minimal manager orchestrating the legacy ILP demo algorithm."""

    def __init__(
        self,
        env: AgiEnv,
        args: IlpArgs | None = None,
        **raw_args: Any,
    ) -> None:
        super().__init__()
        self.env = env
        if args is None:
            if not raw_args:
                raise ValueError("IlpApp requires arguments provided via args model or keyword values")
            args = IlpArgs(**raw_args)

        self.setup_args(args, env=env, error="IlpApp requires an initialized IlpArgs instance")
        self.data_dir = Path(self.args.data_uri).expanduser()
        self.data_dir.mkdir(parents=True, exist_ok=True)

        WorkDispatcher.args = self.as_dict() | {"dir_path": str(self.data_dir)}

    def _extend_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload["data_uri"] = str(self.data_dir)
        return payload

    def build_distribution(self, workers: dict[str, int]) -> tuple[list[list[list[dict[str, Any]]]], list[list[tuple[int, int]]], str, str, str]:
        """Partition synthetic demands across the available workers."""

        flyenv = Flyenv()
        flyenv.seed(self.args.seed)
        flyenv.generate_environment(self.args.topology, [])
        _, raw_demands, _ = flyenv.generate_connectivity_demand(self.args.num_demands)

        scaled_demands = self._scale_demands(raw_demands)

        payloads: list[dict[str, Any]] = []
        for demand in scaled_demands:
            payloads.append(
                {
                    "source": demand.source,
                    "destination": demand.destination,
                    "bandwidth": demand.bw,
                    "priority": getattr(demand, "priority", 1),
                    "max_packet_loss": getattr(demand, "max_packet_loss", 10),
                    "max_latency": getattr(demand, "max_latency", 750),
                }
            )

        worker_slots = sum(workers.values()) if workers else 1
        worker_slots = max(worker_slots, 1)
        chunk_size = max(math.ceil(len(payloads) / worker_slots), 1)

        workers_plan: list[list[tuple[dict[str, Any], list[str]]]] = [
            [] for _ in range(worker_slots)
        ]
        workers_metadata: list[list[tuple[str, int]]] = [[] for _ in range(worker_slots)]

        for idx in range(worker_slots):
            chunk = payloads[idx * chunk_size : (idx + 1) * chunk_size]
            if not chunk:
                continue
            workers_plan[idx].append(
                (
                    {
                        "functions name": "work_pool",
                        "args": {"demands": chunk},
                    },
                    [],
                )
            )
            total_bw = sum(item["bandwidth"] for item in chunk)
            workers_metadata[idx].append((f"batch_{idx}_{len(chunk)}", total_bw))

        if not any(workers_plan):
            workers_plan[0].append(
                (
                    {
                        "functions name": "work_pool",
                        "args": {"demands": []},
                    },
                    [],
                )
            )
            workers_metadata[0].append(("batch_0_0", 0))

        return workers_plan, workers_metadata, "demand", "count", "bw"

    def simulate(self) -> list[dict[str, Any]]:
        """Generate synthetic demands and run the greedy allocator."""
        flyenv = Flyenv()
        flyenv.seed(self.args.seed)
        if self.args.topology != "topo3N":
            flyenv.generate_environment(self.args.topology, flyenv.demands)

        _, demand_list, _ = flyenv.generate_connectivity_demand(self.args.num_demands)
        scaled_demands = self._scale_demands(demand_list)

        solver = MILP(flyenv, logger=logger)
        allocations = solver.solve(scaled_demands)

        results: list[dict[str, Any]] = []
        for allocation in allocations:
            results.append(
                {
                    "source": allocation.demand.source,
                    "destination": allocation.demand.destination,
                    "bandwidth": allocation.demand.bw,
                    "delivered_bandwidth": allocation.delivered_bandwidth,
                    "routed": allocation.routed,
                    "path": allocation.path,
                    "bearers": allocation.bearers,
                    "latency": allocation.latency,
                }
            )

        return results

    def _scale_demands(self, demands: list[Demand]) -> list[Demand]:
        if self.args.demand_scale == 1.0:
            return demands

        scaled: list[Demand] = []
        for demand in demands:
            new_bw = max(1, int(demand.bw * self.args.demand_scale))
            cloned = Demand(
                demand.source,
                demand.destination,
                new_bw,
                demand.priority,
                demand.max_packet_loss,
                demand.max_latency,
            )
            scaled.append(cloned)
        return scaled


__all__ = ["IlpApp"]


class Ilp(IlpApp):
    """Backward-compatible alias expected by AGI dispatcher."""


__all__.append("Ilp")
