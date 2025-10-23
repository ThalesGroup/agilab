"""Random topology generation helpers inspired by the FlowSynth legacy scripts."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Iterable

import networkx as nx
import numpy as np

__all__ = ["generate_mixed_topology"]


@dataclass(frozen=True)
class _EdgeProfile:
    bearer: str
    capacity_range: tuple[int, int]
    latency_range: tuple[int, int]


_EDGE_PROFILES = {
    "sat": _EdgeProfile("Sat", (8_000, 15_000), (240, 580)),
    "ivdl": _EdgeProfile("ivdl", (900, 4_000), (45, 120)),
    "opt": _EdgeProfile("Opt", (7_000, 18_000), (8, 35)),
}


def _choose_profile(label: str) -> _EdgeProfile:
    return _EDGE_PROFILES.get(label.lower(), _EDGE_PROFILES["ivdl"])


def _assign_node_type(node_id: int, rng: random.Random) -> str:
    if node_id == 0:
        return "ngf"
    roll = rng.random()
    if roll < 0.25:
        return "ngf"
    if roll < 0.55:
        return "hrc"
    return "lrc"


def _random_degree_sequence(size: int, rng: np.random.Generator) -> list[int]:
    return rng.choice([2, 3], size=size, p=[0.3, 0.7]).tolist()


def _ensure_component_connectivity(graph: nx.Graph, rng: random.Random) -> None:
    components = [list(component) for component in nx.connected_components(graph)]
    if len(components) <= 1:
        return
    for idx in range(len(components) - 1):
        src = rng.choice(components[idx])
        dst = rng.choice(components[idx + 1])
        if not graph.has_edge(src, dst):
            graph.add_edge(src, dst, label=rng.choice(["opt", "ivdl"]))


def _add_backbone_links(graph: nx.Graph, net_size: int, rng: random.Random) -> None:
    hub = 0
    for node in range(1, net_size):
        if not graph.has_edge(hub, node):
            graph.add_edge(hub, node, label="sat")


def _pair_candidates(graph: nx.Graph, node: int, candidates: Iterable[int]) -> list[int]:
    banned = {node}
    banned.update(graph.neighbors(node))
    return [candidate for candidate in candidates if candidate not in banned]


def generate_mixed_topology(net_size: int, *, seed: int | None = None) -> nx.MultiDiGraph:
    """Generate a directed multigraph representing a mixed transport network."""

    if net_size < 4:
        raise ValueError("net_size must be >= 4 for a meaningful topology")

    base_rng = random.Random(seed)
    np_seed = base_rng.randrange(1, 2**32 - 1) if seed is not None else None
    np_rng = np.random.default_rng(np_seed)

    base = nx.Graph()
    base.add_nodes_from(range(net_size))

    non_hub_nodes = list(range(1, net_size))
    base_rng.shuffle(non_hub_nodes)
    degree_targets = {
        node: target for node, target in zip(non_hub_nodes, _random_degree_sequence(len(non_hub_nodes), np_rng))
    }

    # Start with a random chain to ensure connectivity amongst non-hub nodes
    for left, right in zip(non_hub_nodes, non_hub_nodes[1:]):
        base.add_edge(left, right, label=base_rng.choice(["opt", "ivdl"]))

    active_nodes = [node for node in non_hub_nodes if base.degree(node) < degree_targets[node]]
    while active_nodes:
        node = base_rng.choice(active_nodes)
        candidates = _pair_candidates(base, node, non_hub_nodes)
        if not candidates:
            active_nodes = [n for n in active_nodes if base.degree(n) < degree_targets[n]]
            continue
        partner = base_rng.choice(candidates)
        base.add_edge(node, partner, label=base_rng.choice(["opt", "ivdl"]))

        if base.degree(node) >= degree_targets[node]:
            active_nodes = [n for n in active_nodes if base.degree(n) < degree_targets[n]]
        if base.degree(partner) >= degree_targets.get(partner, base.degree(partner)) and partner in active_nodes:
            active_nodes = [n for n in active_nodes if base.degree(n) < degree_targets[n]]

    _ensure_component_connectivity(base, base_rng)
    _add_backbone_links(base, net_size, base_rng)

    graph = nx.MultiDiGraph()
    for node in base.nodes:
        graph.add_node(
            node,
            label=str(node),
            type=_assign_node_type(node, base_rng),
            bufferSizes=32_000,
            x_position=100,
            y_postiion=200,
            z_position=100,
        )

    edge_id = 1
    for u, v, data in base.edges(data=True):
        profile = _choose_profile(data.get("label", "ivdl"))
        capacity = float(base_rng.randint(*profile.capacity_range))
        latency = float(base_rng.randint(*profile.latency_range))
        attrs = {
            "bearer": profile.bearer,
            "capacity": capacity,
            "latency": latency,
            "betweenness": 0,
            "nb_sp": 0,
            "bw_allocated": 0,
        }
        for source, target in ((u, v), (v, u)):
            graph.add_edge(source, target, id=edge_id, **attrs)
            edge_id += 1

    return graph
