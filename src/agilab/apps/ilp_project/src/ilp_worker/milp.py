"""MILP allocator backed by a free solver implementation (PuLP + CBC)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence, Tuple

import pulp

from ilp_worker.demand import Demand

EdgeKey = Tuple[int, int, int]


@dataclass(slots=True)
class AllocationResult:
    """Container describing how a demand has been routed."""

    demand: Demand
    path: List[EdgeKey]
    available_capacity: float
    latency: float
    bearers: List[str]

    @property
    def routed(self) -> bool:
        return bool(self.path)

    @property
    def delivered_bandwidth(self) -> float:
        return min(self.demand.bw, self.available_capacity) if self.path else 0.0


class MILP:
    """Mixed-integer allocator that mirrors the legacy Gurobi model using PuLP."""

    def __init__(self, env, logger: logging.Logger | None = None, solver: pulp.LpSolver | None = None) -> None:
        self.env = env
        self.logger = logger or logging.getLogger(__name__)
        self._solver = solver

    # Public API -----------------------------------------------------------------
    def solve(self, demands: Sequence[Demand]) -> List[AllocationResult]:
        """Route the provided demands by solving a MILP with a free solver backend."""

        if not demands:
            return []

        edges_meta = self._collect_edge_metadata()
        outgoing, incoming = self._build_adjacent_edge_maps(edges_meta)
        demand_models = self._normalise_demands(demands)

        problem, flow_vars, y_vars, phi_vars = self._build_problem(
            demand_models,
            edges_meta,
            outgoing,
            incoming,
        )

        solver = self._solver or pulp.PULP_CBC_CMD(msg=False)
        status = problem.solve(solver)
        status_label = pulp.LpStatus.get(problem.status, str(problem.status))
        if status_label != "Optimal":
            self.logger.warning("MILP solver returned status %s; falling back to greedy results", status_label)
            return self._fallback_greedy(demands, edges_meta)

        return self._extract_results(
            demand_models,
            edges_meta,
            flow_vars,
            y_vars,
            phi_vars,
            outgoing,
        )

    # Problem construction -------------------------------------------------------
    def _collect_edge_metadata(self) -> List[dict]:
        metadata: List[dict] = []
        graph = self.env.graph
        for idx, (u, v, key) in enumerate(self.env.non_ordered_edges):
            state = self.env.graph_state[idx]
            capacity = float(state[0])
            latency = float(state[2])
            raw_bearer = graph.get_edge_data(u, v).get(key, {}).get("bearer")
            bearer = str(raw_bearer).upper() if raw_bearer else ""
            metadata.append(
                {
                    "index": idx,
                    "edge": (u, v, key),
                    "capacity": capacity,
                    "latency": latency,
                    "bearer": bearer,
                }
            )
        return metadata

    def _build_adjacent_edge_maps(
        self,
        edges_meta: Sequence[dict],
    ) -> Tuple[Dict[int, List[int]], Dict[int, List[int]]]:
        outgoing: Dict[int, List[int]] = {}
        incoming: Dict[int, List[int]] = {}
        for meta in edges_meta:
            u, v, _ = meta["edge"]
            outgoing.setdefault(u, []).append(meta["index"])
            incoming.setdefault(v, []).append(meta["index"])
        return outgoing, incoming

    def _normalise_demands(self, demands: Sequence[Demand]) -> List[dict]:
        normalised: List[dict] = []
        for idx, demand in enumerate(demands):
            demand_key = f"d{idx}"
            priority = float(getattr(demand, "priority", 1) or 1)
            max_latency = float(getattr(demand, "max_latency", 750))
            min_bw = float(getattr(demand, "min_bw", demand.bw))
            normalised.append(
                {
                    "id": demand_key,
                    "demand": demand,
                    "source": int(demand.source),
                    "sink": int(demand.destination),
                    "bandwidth": float(demand.bw),
                    "min_bw": min_bw,
                    "priority": max(priority, 1e-3),
                    "max_latency": max_latency,
                }
            )
        return normalised

    def _build_problem(
        self,
        demand_models: Sequence[dict],
        edges_meta: Sequence[dict],
        outgoing: Dict[int, List[int]],
        incoming: Dict[int, List[int]],
    ) -> Tuple[pulp.LpProblem, Dict[Tuple[str, int], pulp.LpVariable], Dict[Tuple[str, int], pulp.LpVariable], Dict[str, pulp.LpVariable]]:
        problem = pulp.LpProblem("ilp_allocator", pulp.LpMaximize)

        flow_vars: Dict[Tuple[str, int], pulp.LpVariable] = {}
        y_vars: Dict[Tuple[str, int], pulp.LpVariable] = {}
        phi_vars: Dict[str, pulp.LpVariable] = {}

        edge_indices = [meta["index"] for meta in edges_meta]

        for model in demand_models:
            demand_id = model["id"]
            phi_vars[demand_id] = pulp.LpVariable(f"phi_{demand_id}", lowBound=0, upBound=1, cat="Binary")
            for edge_idx in edge_indices:
                flow_vars[(demand_id, edge_idx)] = pulp.LpVariable(
                    f"flow_{demand_id}_{edge_idx}",
                    lowBound=0,
                    cat="Integer",
                )
                y_vars[(demand_id, edge_idx)] = pulp.LpVariable(
                    f"use_{demand_id}_{edge_idx}",
                    lowBound=0,
                    upBound=1,
                    cat="Binary",
                )

        # Capacity constraints
        for meta in edges_meta:
            edge_idx = meta["index"]
            capacity = meta["capacity"]
            problem += (
                pulp.lpSum(flow_vars[(model["id"], edge_idx)] for model in demand_models) <= capacity,
                f"capacity_{edge_idx}",
            )

        # Flow-to-usage linking
        for model in demand_models:
            demand_id = model["id"]
            bandwidth = model["bandwidth"]
            for edge_idx in edge_indices:
                problem += (
                    flow_vars[(demand_id, edge_idx)] <= bandwidth * y_vars[(demand_id, edge_idx)],
                    f"link_flow_{demand_id}_{edge_idx}",
                )

        # Flow conservation and single-path structure
        nodes: Iterable[int] = self.env.graph.nodes
        for model in demand_models:
            demand_id = model["id"]
            source = model["source"]
            sink = model["sink"]
            bandwidth = model["bandwidth"]
            min_bw = model["min_bw"]

            for node in nodes:
                outgoing_edges = outgoing.get(node, [])
                incoming_edges = incoming.get(node, [])

                outflow = pulp.lpSum(flow_vars[(demand_id, idx)] for idx in outgoing_edges)
                inflow = pulp.lpSum(flow_vars[(demand_id, idx)] for idx in incoming_edges)
                out_use = pulp.lpSum(y_vars[(demand_id, idx)] for idx in outgoing_edges)
                in_use = pulp.lpSum(y_vars[(demand_id, idx)] for idx in incoming_edges)

                if node == source:
                    problem += outflow - inflow >= min_bw * phi_vars[demand_id], f"source_min_{demand_id}_{node}"
                    problem += outflow - inflow <= bandwidth * phi_vars[demand_id], f"source_max_{demand_id}_{node}"
                    problem += out_use == phi_vars[demand_id], f"source_use_{demand_id}_{node}"
                elif node == sink:
                    problem += inflow - outflow >= min_bw * phi_vars[demand_id], f"sink_min_{demand_id}_{node}"
                    problem += inflow - outflow <= bandwidth * phi_vars[demand_id], f"sink_max_{demand_id}_{node}"
                    problem += in_use == phi_vars[demand_id], f"sink_use_{demand_id}_{node}"
                else:
                    problem += outflow - inflow == 0, f"flow_cons_{demand_id}_{node}"
                    if outgoing_edges or incoming_edges:
                        problem += out_use == in_use, f"use_cons_{demand_id}_{node}"

        # Latency budgets
        for model in demand_models:
            demand_id = model["id"]
            max_latency = model["max_latency"]
            problem += (
                pulp.lpSum(
                    meta["latency"] * y_vars[(demand_id, meta["index"])]
                    for meta in edges_meta
                )
                <= max_latency * phi_vars[demand_id],
                f"latency_{demand_id}",
            )

        # Objective: maximise routed high-priority flow and prefer low-latency paths
        objective_terms = []
        flow_weight = 1.0
        service_weight = 1_000_000.0
        latency_penalty = 0.01

        for model in demand_models:
            demand_id = model["id"]
            priority = model["priority"]
            source = model["source"]
            source_outflow = pulp.lpSum(flow_vars[(demand_id, idx)] for idx in outgoing.get(source, []))
            latency_sum = pulp.lpSum(
                meta["latency"] * y_vars[(demand_id, meta["index"])] for meta in edges_meta
            )

            objective_terms.append(service_weight / priority * phi_vars[demand_id])
            objective_terms.append(flow_weight / priority * source_outflow)
            objective_terms.append(-latency_penalty / priority * latency_sum)

        problem += pulp.lpSum(objective_terms)

        return problem, flow_vars, y_vars, phi_vars

    # Result processing ----------------------------------------------------------
    def _extract_results(
        self,
        demand_models: Sequence[dict],
        edges_meta: Sequence[dict],
        flow_vars: Dict[Tuple[str, int], pulp.LpVariable],
        y_vars: Dict[Tuple[str, int], pulp.LpVariable],
        phi_vars: Dict[str, pulp.LpVariable],
        outgoing: Dict[int, List[int]],
    ) -> List[AllocationResult]:
        results: List[AllocationResult] = []
        edges = [meta["edge"] for meta in edges_meta]
        latencies = {meta["index"]: meta["latency"] for meta in edges_meta}
        bearers = {meta["index"]: meta["bearer"] for meta in edges_meta}

        for model in demand_models:
            demand = model["demand"]
            demand_id = model["id"]
            phi_value = pulp.value(phi_vars[demand_id]) or 0.0

            if phi_value < 0.5:
                results.append(
                    AllocationResult(
                        demand=demand,
                        path=[],
                        available_capacity=0.0,
                        latency=0.0,
                        bearers=[],
                    )
                )
                continue

            edge_indices = self._reconstruct_path(
                model,
                edges_meta,
                flow_vars,
                y_vars,
            )

            if not edge_indices:
                self.logger.warning("Unable to reconstruct path for demand %s; marking as unrouted", demand)
                results.append(
                    AllocationResult(
                        demand=demand,
                        path=[],
                        available_capacity=0.0,
                        latency=0.0,
                        bearers=[],
                    )
                )
                continue

            flows = [pulp.value(flow_vars[(demand_id, idx)]) or 0.0 for idx in edge_indices]
            allocated_bw = min(flows) if flows else 0.0
            total_latency = sum(latencies[idx] for idx in edge_indices)
            bearer_sequence = [bearers[idx] for idx in edge_indices if bearers[idx]]

            results.append(
                AllocationResult(
                    demand=demand,
                    path=[edges[idx] for idx in edge_indices],
                    available_capacity=allocated_bw,
                    latency=total_latency,
                    bearers=bearer_sequence,
                )
            )

        return results

    def _reconstruct_path(
        self,
        model: dict,
        edges_meta: Sequence[dict],
        flow_vars: Dict[Tuple[str, int], pulp.LpVariable],
        y_vars: Dict[Tuple[str, int], pulp.LpVariable],
    ) -> List[int]:
        """Recover a simple path from the MILP decision variables."""

        demand_id = model["id"]
        source = model["source"]
        sink = model["sink"]
        epsilon = 1e-6

        candidate_paths: Iterable[Sequence[int]] = self.env.paths.get(f"{source}:{sink}", [])
        edges_by_tail: Dict[Tuple[int, int], List[int]] = {}
        for meta in edges_meta:
            edge_idx = meta["index"]
            u, v, _ = meta["edge"]
            edges_by_tail.setdefault((u, v), []).append(edge_idx)

        def edge_used(idx: int) -> bool:
            return (pulp.value(y_vars[(demand_id, idx)]) or 0.0) > 0.5 or (pulp.value(flow_vars[(demand_id, idx)]) or 0.0) > epsilon

        for nodes_path in candidate_paths:
            edge_indices: List[int] = []
            feasible = True
            for u, v in zip(nodes_path[:-1], nodes_path[1:]):
                candidates = edges_by_tail.get((u, v), [])
                match_idx = next((idx for idx in candidates if edge_used(idx)), None)
                if match_idx is None:
                    feasible = False
                    break
                edge_indices.append(match_idx)
            if feasible and edge_indices:
                return edge_indices

        return []

    # Greedy fallback ------------------------------------------------------------
    def _fallback_greedy(self, demands: Sequence[Demand], edges_meta: Sequence[dict]) -> List[AllocationResult]:
        """Last-resort allocator that mirrors the legacy greedy behaviour."""

        from copy import deepcopy

        graph = self.env.graph
        residual: Dict[EdgeKey, float] = {
            meta["edge"]: meta["capacity"] for meta in edges_meta
        }

        results: List[AllocationResult] = []

        for demand in demands:
            candidate_paths: Iterable[Sequence[int]] = self.env.paths.get(f"{demand.source}:{demand.destination}", [])
            best_path: List[EdgeKey] = []
            best_latency = float("inf")
            best_bw = 0.0
            best_bearers: List[str] = []

            for nodes_path in candidate_paths:
                path_edges: List[EdgeKey] = []
                path_latency = 0.0
                path_bw = demand.bw
                path_bearers: List[str] = []
                feasible = True

                for u, v in zip(nodes_path[:-1], nodes_path[1:]):
                    edge_data = graph.get_edge_data(u, v, default={})
                    chosen_edge: EdgeKey | None = None
                    chosen_latency = 0.0
                    chosen_bearer = ""
                    for key, metadata in edge_data.items():
                        edge = (u, v, key)
                        residual_capacity = residual.get(edge, 0.0)
                        if residual_capacity < demand.bw:
                            continue
                        chosen_edge = edge
                        chosen_latency = float(metadata.get("latency", 0.0))
                        raw_bearer = metadata.get("bearer")
                        chosen_bearer = str(raw_bearer).upper() if raw_bearer else ""
                        break
                    if chosen_edge is None:
                        feasible = False
                        break
                    path_edges.append(chosen_edge)
                    path_latency += chosen_latency
                    path_bearers.append(chosen_bearer)
                    path_bw = min(path_bw, residual[chosen_edge])

                if not feasible or path_latency > demand.max_latency:
                    continue

                if path_bw > best_bw or (path_bw == best_bw and path_latency < best_latency):
                    best_path = deepcopy(path_edges)
                    best_latency = path_latency
                    best_bw = path_bw
                    best_bearers = path_bearers

            if not best_path:
                results.append(
                    AllocationResult(
                        demand=demand,
                        path=[],
                        available_capacity=0.0,
                        latency=0.0,
                        bearers=[],
                    )
                )
                continue

            for edge in best_path:
                residual[edge] -= best_bw

            results.append(
                AllocationResult(
                    demand=demand,
                    path=best_path,
                    available_capacity=best_bw,
                    latency=best_latency,
                    bearers=best_bearers,
                )
            )

        return results


__all__ = ["AllocationResult", "MILP"]
