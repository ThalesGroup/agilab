"""Worker entry point for the ILP demo."""

from __future__ import annotations

from typing import Any, Dict, List
from types import SimpleNamespace

from agi_node.agi_dispatcher import BaseWorker
from agi_node.dag_worker import DagWorker

from ilp_worker.demand import Demand
from ilp_worker.flyenv import Flyenv
from ilp_worker.milp import MILP


class _MutableNamespace(SimpleNamespace):
    """SimpleNamespace that also supports item-style access."""

    def __getitem__(self, key):
        return getattr(self, key)

    def __setitem__(self, key, value):
        setattr(self, key, value)


class IlpWorker(DagWorker):  # pragma: no cover - executed within workers
    worker_vars: Dict[str, Any] = {}

    def __init__(self, env=None, **kwargs: Any) -> None:
        super().__init__()
        self.env = env or BaseWorker.env
        self.kwargs = kwargs
        self._flyenv = Flyenv()
        self._solver = MILP(self._flyenv)

    @staticmethod
    def pool_init(vars: Dict[str, Any]) -> None:
        IlpWorker.worker_vars = vars

    def work_pool(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        demands_payload = payload.get("demands", [])
        demands = [
            Demand(
                item["source"],
                item["destination"],
                item["bandwidth"],
                item.get("priority", 1),
                item.get("max_packet_loss", 10),
                item.get("max_latency", 750),
            )
            for item in demands_payload
        ]
        results = self._solver.solve(demands)
        return {
            "allocations": [
                {
                    "source": result.demand.source,
                    "destination": result.demand.destination,
                    "bandwidth": result.demand.bw,
                    "routed": result.routed,
                    "path": result.path,
                }
                for result in results
            ]
        }

    def work_done(self, worker_df: Any) -> None:
        pass



__all__ = ["IlpWorker"]
