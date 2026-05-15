"""SimPy-based worker for the built-in UAV queue project."""

from __future__ import annotations

import json
import logging
import math
import random
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import networkx as nx
import pandas as pd
import simpy

from agi_node.agi_dispatcher import BaseWorker
from agi_node.pandas_worker import PandasWorker
from uav_queue.reduction import write_reduce_artifact

logger = logging.getLogger(__name__)
_runtime: dict[str, object] = {}


def _artifact_dir(env: object, leaf: str) -> Path:
    export_root = getattr(env, "AGILAB_EXPORT_ABS", None)
    target = str(getattr(env, "target", "") or "")
    relative = Path(target) / leaf if target else Path(leaf)
    if export_root is not None:
        return Path(export_root) / relative
    resolve_share_path = getattr(env, "resolve_share_path", None)
    if callable(resolve_share_path):
        return Path(resolve_share_path(relative))
    return Path.home() / "export" / relative


@dataclass(frozen=True)
class RelayConfig:
    relay_id: str
    base_x_m: float
    base_y_m: float
    amplitude_m: float
    period_s: float
    service_rate_pps: float
    queue_capacity_pkts: int
    background_rate_pps: float
    base_alt_m: float = 900.0
    bias_ms: float = 0.0


class RelayRuntime:
    """Runtime state for one relay queue."""

    def __init__(self, env: simpy.Environment, config: RelayConfig):
        self.env = env
        self.config = config
        self.buffer = simpy.Resource(env, capacity=1)

    def occupancy(self) -> int:
        return int(self.buffer.count + len(self.buffer.queue))

    def position(self, time_s: float) -> tuple[float, float]:
        period = self.config.period_s if self.config.period_s > 0 else 1.0
        phase = 2.0 * math.pi * (time_s / period)
        y_pos = self.config.base_y_m + self.config.amplitude_m * math.sin(phase)
        return self.config.base_x_m, y_pos


def _distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    return float(math.dist(a, b))


def _meters_to_geo(
    x_m: float,
    y_m: float,
    *,
    base_latitude: float,
    base_longitude: float,
) -> tuple[float, float]:
    lat = base_latitude + (y_m / 111_320.0)
    lon_scale = 111_320.0 * max(math.cos(math.radians(base_latitude)), 1e-6)
    lon = base_longitude + (x_m / lon_scale)
    return float(lat), float(lon)


def _sanitize_slug(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_-]+", "_", value.strip())
    cleaned = cleaned.strip("_")
    return cleaned or "uav_queue_run"


def _safe_mean(series: pd.Series) -> float | None:
    if series.empty:
        return None
    return float(series.mean())


def _build_topology_graph(
    *,
    source_id: str,
    sink_id: str,
    relays: list[dict[str, Any]],
    packet_size_bytes: int,
    source_rate_pps: float,
    source_geo: dict[str, float],
    sink_geo: dict[str, float],
) -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    graph.add_node(
        source_id,
        node_type="plane",
        latitude=source_geo["latitude"],
        longitude=source_geo["longitude"],
        altitude=source_geo["alt_m"],
    )
    graph.add_node(
        sink_id,
        node_type="ground",
        latitude=sink_geo["latitude"],
        longitude=sink_geo["longitude"],
        altitude=sink_geo["alt_m"],
    )

    for relay in relays:
        relay_id = str(relay["relay_id"])
        graph.add_node(
            relay_id,
            node_type="relay",
            latitude=float(relay["latitude"]),
            longitude=float(relay["longitude"]),
            altitude=float(relay["alt_m"]),
        )
        uplink_capacity = max(float(relay["service_rate_pps"]), source_rate_pps) * packet_size_bytes * 8.0 / 1_000_000.0
        downlink_capacity = float(relay["service_rate_pps"]) * packet_size_bytes * 8.0 / 1_000_000.0
        graph.add_edge(
            source_id,
            relay_id,
            bearer="ivdl",
            capacity=round(uplink_capacity, 4),
            latency=round(float(relay["source_latency_ms"]), 3),
        )
        graph.add_edge(
            relay_id,
            sink_id,
            bearer="opt",
            capacity=round(downlink_capacity, 4),
            latency=round(float(relay["sink_latency_ms"]), 3),
        )
    return graph


class UavQueueWorker(PandasWorker):
    """Run one lightweight UAV queue scenario and export queue telemetry."""

    pool_vars: dict[str, object] = {}

    def start(self):
        global _runtime
        if isinstance(self.args, dict):
            self.args = SimpleNamespace(**self.args)
        elif not isinstance(self.args, SimpleNamespace):
            self.args = SimpleNamespace(**vars(self.args))

        data_paths = self.setup_data_directories(
            source_path=self.args.data_in,
            target_path=self.args.data_out,
            target_subdir="results",
            reset_target=False,
        )
        self.args.data_in = data_paths.normalized_input
        self.args.data_out = data_paths.normalized_output
        self.data_out = data_paths.output_path
        self.reset_target = bool(getattr(self.args, "reset_target", False))
        self.artifact_dir = _artifact_dir(self.env, "queue_analysis")
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.pool_vars = {"args": self.args}
        _runtime = self.pool_vars

    def pool_init(self, worker_vars):
        global _runtime
        _runtime = worker_vars

    def _current_args(self) -> SimpleNamespace:
        args = _runtime.get("args", self.args)
        if isinstance(args, dict):
            return SimpleNamespace(**args)
        return args

    def work_init(self) -> None:
        return None

    def works(self, workers_plan: Any, workers_plan_metadata: Any) -> float:
        """Execute assigned scenario batches while keeping custom artifact exports."""

        assigned_batches: list[Any] = []
        if isinstance(workers_plan, list) and len(workers_plan) > self._worker_id:
            worker_batches = workers_plan[self._worker_id]
            if isinstance(worker_batches, list):
                assigned_batches = worker_batches

        self.work_init()
        for batch in assigned_batches:
            if isinstance(batch, (list, tuple)):
                work_items = list(batch)
            else:
                work_items = [batch]
            for work_item in work_items:
                result = self.work_pool(work_item)
                self.work_done(result)

        self.stop()

        if BaseWorker._t0 is None:
            BaseWorker._t0 = time.time()
        return time.time() - BaseWorker._t0

    def _load_scenario(self, file_path: str | Path) -> dict[str, Any]:
        source = Path(str(file_path)).expanduser()
        payload = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Scenario file must contain a JSON object: {source}")
        relays = payload.get("relays")
        if not isinstance(relays, list) or len(relays) < 2:
            raise ValueError(f"Scenario file must declare at least two relays: {source}")
        return payload

    def work_pool(self, file_path):
        args = self._current_args()
        scenario = self._load_scenario(file_path)
        scenario_name = str(scenario.get("scenario") or Path(str(file_path)).stem)
        sim_time_s = float(getattr(args, "sim_time_s", scenario.get("sim_time_s", 30.0)))
        sampling_interval_s = float(
            getattr(args, "sampling_interval_s", scenario.get("sampling_interval_s", 0.5))
        )
        source_rate_pps = float(getattr(args, "source_rate_pps", scenario.get("source_rate_pps", 14.0)))
        routing_policy = str(getattr(args, "routing_policy", "shortest_path"))
        queue_weight = float(getattr(args, "queue_weight", 2.5))
        random_seed = int(getattr(args, "random_seed", 2026))
        packet_size_bytes = int(scenario.get("packet_size_bytes", 1200))
        geo_origin = scenario.get("geo_origin") if isinstance(scenario.get("geo_origin"), dict) else {}
        base_latitude = float(geo_origin.get("latitude", 48.8566))
        base_longitude = float(geo_origin.get("longitude", 2.3522))
        geo_altitude_m = float(geo_origin.get("alt_m", 900.0))

        source_node = scenario.get("source_node") or {"node_id": "uav_source", "x_m": 0.0, "y_m": 0.0}
        sink_node = scenario.get("sink_node") or {"node_id": "ground_sink", "x_m": 1000.0, "y_m": 0.0}
        source_id = str(source_node.get("node_id", "uav_source"))
        sink_id = str(sink_node.get("node_id", "ground_sink"))
        source_pos = (float(source_node.get("x_m", 0.0)), float(source_node.get("y_m", 0.0)))
        sink_pos = (float(sink_node.get("x_m", 1000.0)), float(sink_node.get("y_m", 0.0)))
        source_alt_m = float(source_node.get("alt_m", geo_altitude_m + 220.0))
        sink_alt_m = float(sink_node.get("alt_m", 40.0))
        source_lat, source_lon = _meters_to_geo(
            source_pos[0],
            source_pos[1],
            base_latitude=base_latitude,
            base_longitude=base_longitude,
        )
        sink_lat, sink_lon = _meters_to_geo(
            sink_pos[0],
            sink_pos[1],
            base_latitude=base_latitude,
            base_longitude=base_longitude,
        )

        env = simpy.Environment()
        rng = random.Random(random_seed)
        packet_events: list[dict[str, object]] = []
        queue_timeseries: list[dict[str, object]] = []
        node_positions: list[dict[str, object]] = []

        relay_configs = [
            RelayConfig(
                relay_id=str(item["relay_id"]),
                base_x_m=float(item["base_x_m"]),
                base_y_m=float(item["base_y_m"]),
                amplitude_m=float(item.get("amplitude_m", 0.0)),
                period_s=float(item.get("period_s", 20.0)),
                service_rate_pps=float(item.get("service_rate_pps", 10.0)),
                queue_capacity_pkts=int(item.get("queue_capacity_pkts", 10)),
                background_rate_pps=float(item.get("background_rate_pps", 0.0)),
                base_alt_m=float(item.get("alt_m", item.get("base_alt_m", geo_altitude_m))),
                bias_ms=float(item.get("bias_ms", 0.0)),
            )
            for item in scenario["relays"]
        ]
        relays = {cfg.relay_id: RelayRuntime(env, cfg) for cfg in relay_configs}

        packet_counter = 0

        def route_latency_ms(relay: RelayRuntime, now_s: float) -> float:
            relay_pos = relay.position(now_s)
            path_length = _distance_m(source_pos, relay_pos) + _distance_m(relay_pos, sink_pos)
            return 2.0 + path_length / 120.0 + relay.config.bias_ms

        def choose_relay(now_s: float) -> RelayRuntime:
            scored: list[tuple[float, float, str, RelayRuntime]] = []
            for relay in relays.values():
                base_ms = route_latency_ms(relay, now_s)
                queue_penalty_ms = 0.0
                if routing_policy == "queue_aware":
                    queue_penalty_ms = (
                        relay.occupancy() / max(relay.config.service_rate_pps, 1e-6)
                    ) * 1000.0 * queue_weight
                score_ms = base_ms + queue_penalty_ms
                scored.append((score_ms, base_ms, relay.config.relay_id, relay))
            return min(scored, key=lambda item: (item[0], item[1], item[2]))[3]

        def submit_packet(origin_kind: str, relay: RelayRuntime | None = None):
            nonlocal packet_counter

            packet_counter += 1
            packet_id = packet_counter
            created_s = float(env.now)
            chosen = relay or choose_relay(created_s)
            chosen_latency_ms = route_latency_ms(chosen, created_s)
            queue_depth_before = chosen.occupancy()

            if queue_depth_before >= chosen.config.queue_capacity_pkts:
                packet_events.append(
                    {
                        "packet_id": packet_id,
                        "scenario": scenario_name,
                        "origin_kind": origin_kind,
                        "routing_policy": routing_policy if origin_kind == "source" else "background",
                        "relay": chosen.config.relay_id,
                        "status": "dropped",
                        "drop_reason": "queue_overflow",
                        "created_s": round(created_s, 6),
                        "queue_wait_ms": None,
                        "e2e_delay_ms": None,
                        "route_latency_ms": round(chosen_latency_ms, 3),
                        "queue_depth_before": queue_depth_before,
                    }
                )
                return

            def _run():
                with chosen.buffer.request() as req:
                    queue_enter_s = float(env.now)
                    yield req
                    service_start_s = float(env.now)
                    queue_wait_ms = (service_start_s - queue_enter_s) * 1000.0
                    service_time_s = 1.0 / max(chosen.config.service_rate_pps, 1e-6)
                    yield env.timeout(service_time_s + chosen_latency_ms / 1000.0)
                    delivered_s = float(env.now)
                    packet_events.append(
                        {
                            "packet_id": packet_id,
                            "scenario": scenario_name,
                            "origin_kind": origin_kind,
                            "routing_policy": routing_policy if origin_kind == "source" else "background",
                            "relay": chosen.config.relay_id,
                            "status": "delivered",
                            "drop_reason": "",
                            "created_s": round(created_s, 6),
                            "queue_wait_ms": round(queue_wait_ms, 3),
                            "e2e_delay_ms": round((delivered_s - created_s) * 1000.0, 3),
                            "route_latency_ms": round(chosen_latency_ms, 3),
                            "queue_depth_before": queue_depth_before,
                        }
                    )

            env.process(_run())

        def source_process():
            while env.now < sim_time_s:
                inter_arrival = rng.expovariate(source_rate_pps)
                yield env.timeout(inter_arrival)
                if env.now > sim_time_s:
                    break
                submit_packet("source")

        def background_process(relay: RelayRuntime):
            rate = relay.config.background_rate_pps
            if rate <= 0:
                return
            while env.now < sim_time_s:
                inter_arrival = rng.expovariate(rate)
                yield env.timeout(inter_arrival)
                if env.now > sim_time_s:
                    break
                submit_packet("background", relay=relay)

        def monitor():
            while env.now <= sim_time_s + 1e-9:
                now_s = float(env.now)
                node_positions.append(
                    {
                        "time_s": round(now_s, 3),
                        "node": source_id,
                        "role": "source",
                        "x_m": round(source_pos[0], 3),
                        "y_m": round(source_pos[1], 3),
                        "latitude": round(source_lat, 6),
                        "longitude": round(source_lon, 6),
                        "alt_m": round(source_alt_m, 3),
                    }
                )
                node_positions.append(
                    {
                        "time_s": round(now_s, 3),
                        "node": sink_id,
                        "role": "sink",
                        "x_m": round(sink_pos[0], 3),
                        "y_m": round(sink_pos[1], 3),
                        "latitude": round(sink_lat, 6),
                        "longitude": round(sink_lon, 6),
                        "alt_m": round(sink_alt_m, 3),
                    }
                )
                for relay in relays.values():
                    x_pos, y_pos = relay.position(now_s)
                    lat, lon = _meters_to_geo(
                        x_pos,
                        y_pos,
                        base_latitude=base_latitude,
                        base_longitude=base_longitude,
                    )
                    queue_timeseries.append(
                        {
                            "time_s": round(now_s, 3),
                            "relay": relay.config.relay_id,
                            "queue_depth_pkts": relay.occupancy(),
                            "service_rate_pps": relay.config.service_rate_pps,
                        }
                    )
                    node_positions.append(
                        {
                            "time_s": round(now_s, 3),
                            "node": relay.config.relay_id,
                            "role": "relay",
                            "x_m": round(x_pos, 3),
                            "y_m": round(y_pos, 3),
                            "latitude": round(lat, 6),
                            "longitude": round(lon, 6),
                            "alt_m": round(relay.config.base_alt_m, 3),
                        }
                    )
                yield env.timeout(sampling_interval_s)

        env.process(source_process())
        for relay in relays.values():
            env.process(background_process(relay))
        env.process(monitor())

        drain_time_s = max(
            (
                (relay.config.queue_capacity_pkts / max(relay.config.service_rate_pps, 1e-6)) + 2.0
                for relay in relays.values()
            ),
            default=5.0,
        )
        env.run(until=sim_time_s + drain_time_s)

        packet_df = pd.DataFrame(packet_events)
        queue_df = pd.DataFrame(queue_timeseries)
        positions_df = pd.DataFrame(node_positions)

        source_df = packet_df.loc[packet_df["origin_kind"] == "source"].copy()
        delivered_source = source_df.loc[source_df["status"] == "delivered"].copy()
        total_generated = int(len(source_df))
        total_delivered = int(len(delivered_source))
        total_dropped = int((source_df["status"] == "dropped").sum()) if not source_df.empty else 0
        pdr = (float(total_delivered) / float(total_generated)) if total_generated else 0.0

        queue_means = (
            queue_df.groupby("relay", as_index=False)["queue_depth_pkts"].mean().rename(columns={"queue_depth_pkts": "mean_queue_depth"})
            if not queue_df.empty
            else pd.DataFrame(columns=["relay", "mean_queue_depth"])
        )

        if not source_df.empty:
            routing_summary = (
                source_df.groupby("relay", as_index=False)
                .agg(
                    packets_generated=("packet_id", "count"),
                    packets_delivered=("status", lambda s: int((s == "delivered").sum())),
                    packets_dropped=("status", lambda s: int((s == "dropped").sum())),
                    mean_queue_wait_ms=("queue_wait_ms", "mean"),
                    mean_e2e_delay_ms=("e2e_delay_ms", "mean"),
                )
                .merge(queue_means, on="relay", how="left")
            )
        else:
            routing_summary = pd.DataFrame(
                columns=[
                    "relay",
                    "packets_generated",
                    "packets_delivered",
                    "packets_dropped",
                    "mean_queue_wait_ms",
                    "mean_e2e_delay_ms",
                    "mean_queue_depth",
                ]
            )

        bottleneck_relay = ""
        if not queue_df.empty:
            bottleneck_relay = str(
                queue_df.groupby("relay")["queue_depth_pkts"].mean().sort_values(ascending=False).index[0]
            )

        summary_metrics = {
            "scenario": scenario_name,
            "routing_policy": routing_policy,
            "sim_time_s": sim_time_s,
            "sampling_interval_s": sampling_interval_s,
            "source_rate_pps": source_rate_pps,
            "packet_size_bytes": packet_size_bytes,
            "queue_weight": queue_weight,
            "random_seed": random_seed,
            "packets_generated": total_generated,
            "packets_delivered": total_delivered,
            "packets_dropped": total_dropped,
            "pdr": round(pdr, 4),
            "mean_e2e_delay_ms": round(_safe_mean(delivered_source["e2e_delay_ms"]) or 0.0, 3),
            "mean_queue_wait_ms": round(_safe_mean(delivered_source["queue_wait_ms"]) or 0.0, 3),
            "max_queue_depth_pkts": int(queue_df["queue_depth_pkts"].max()) if not queue_df.empty else 0,
            "bottleneck_relay": bottleneck_relay,
            "notes": (
                "Built-in AGILAB UAV queue demo inspired by the SimPy buffer-based queueing "
                "pattern described in UavNetSim."
            ),
        }
        summary_metrics["artifact_stem"] = (
            f"{_sanitize_slug(summary_metrics['scenario'])}_{routing_policy}_seed{random_seed}"
        )

        packet_df = packet_df.sort_values(["created_s", "packet_id"]).reset_index(drop=True)
        queue_df = queue_df.sort_values(["time_s", "relay"]).reset_index(drop=True)
        positions_df = positions_df.sort_values(["time_s", "node"]).reset_index(drop=True)
        routing_summary = routing_summary.sort_values("relay").reset_index(drop=True)

        relays_at_zero = positions_df.loc[positions_df["role"] == "relay"].sort_values("node").groupby("node", as_index=False).first()
        relay_specs: list[dict[str, Any]] = []
        for relay in relay_configs:
            relay_row = relays_at_zero.loc[relays_at_zero["node"] == relay.relay_id]
            if relay_row.empty:
                x_pos, y_pos = relay.base_x_m, relay.base_y_m
                lat, lon = _meters_to_geo(
                    x_pos,
                    y_pos,
                    base_latitude=base_latitude,
                    base_longitude=base_longitude,
                )
            else:
                row = relay_row.iloc[0]
                lat = float(row["latitude"])
                lon = float(row["longitude"])
            relay_pos = (relay.base_x_m, relay.base_y_m)
            relay_specs.append(
                {
                    "relay_id": relay.relay_id,
                    "latitude": lat,
                    "longitude": lon,
                    "alt_m": relay.base_alt_m,
                    "service_rate_pps": relay.service_rate_pps,
                    "source_latency_ms": 1.0 + (_distance_m(source_pos, relay_pos) / 240.0),
                    "sink_latency_ms": 1.0 + (_distance_m(relay_pos, sink_pos) / 240.0) + relay.bias_ms,
                }
            )

        sample_times = sorted(queue_df["time_s"].dropna().unique().tolist())
        allocation_rows: list[dict[str, Any]] = []
        for time_index, sample_time in enumerate(sample_times):
            window_start = max(0.0, float(sample_time) - sampling_interval_s)
            window_packets = source_df.loc[
                (source_df["created_s"] > window_start) & (source_df["created_s"] <= float(sample_time) + 1e-9)
            ].copy()
            queue_slice = queue_df.loc[queue_df["time_s"] == sample_time]
            for relay in relay_configs:
                relay_packets = window_packets.loc[window_packets["relay"] == relay.relay_id]
                delivered_packets = relay_packets.loc[relay_packets["status"] == "delivered"]
                queue_row = queue_slice.loc[queue_slice["relay"] == relay.relay_id]
                queue_depth = (
                    float(queue_row.iloc[0]["queue_depth_pkts"])
                    if not queue_row.empty
                    else 0.0
                )
                bandwidth = len(relay_packets) * packet_size_bytes * 8.0 / max(sampling_interval_s, 1e-6) / 1_000_000.0
                delivered_bandwidth = (
                    len(delivered_packets) * packet_size_bytes * 8.0 / max(sampling_interval_s, 1e-6) / 1_000_000.0
                )
                allocation_rows.append(
                    {
                        "time_index": time_index,
                        "t_now_s": round(float(sample_time), 3),
                        "source": source_id,
                        "destination": sink_id,
                        "relay": relay.relay_id,
                        "bandwidth": round(bandwidth, 4),
                        "delivered_bandwidth": round(delivered_bandwidth, 4),
                        "routed": int(len(relay_packets)),
                        "packets_delivered": int(len(delivered_packets)),
                        "packets_dropped": int((relay_packets["status"] == "dropped").sum()) if not relay_packets.empty else 0,
                        "latency": round(_safe_mean(delivered_packets["e2e_delay_ms"]) or 0.0, 3),
                        "queue_depth_pkts": round(queue_depth, 3),
                        "path": [[source_id, relay.relay_id], [relay.relay_id, sink_id]],
                        "bearers": ["ivdl", "opt"],
                    }
                )
        allocations_df = pd.DataFrame(allocation_rows).sort_values(["time_index", "relay"]).reset_index(drop=True)

        topology_graph = _build_topology_graph(
            source_id=source_id,
            sink_id=sink_id,
            relays=relay_specs,
            packet_size_bytes=packet_size_bytes,
            source_rate_pps=source_rate_pps,
            source_geo={"latitude": source_lat, "longitude": source_lon, "alt_m": source_alt_m},
            sink_geo={"latitude": sink_lat, "longitude": sink_lon, "alt_m": sink_alt_m},
        )
        demands_payload = [
            {
                "flow_id": f"{_sanitize_slug(scenario_name)}_source_to_sink",
                "source": source_id,
                "destination": sink_id,
                "bandwidth": round(source_rate_pps * packet_size_bytes * 8.0 / 1_000_000.0, 4),
                "latency": round(_safe_mean(delivered_source["e2e_delay_ms"]) or 0.0, 3),
                "priority": 1.0,
            }
        ]
        trajectory_frames: dict[str, pd.DataFrame] = {}
        for node, group in positions_df.groupby("node", sort=True):
            trajectory_frames[f"{_sanitize_slug(str(node))}_trajectory.csv"] = (
                group.loc[:, ["time_s", "node", "role", "latitude", "longitude", "alt_m"]]
                .rename(columns={"node": "node_id"})
                .assign(uav_id=lambda df: df["node_id"])
                .sort_values("time_s")
                .reset_index(drop=True)
            )
        trajectory_summary = {
            "scenario": scenario_name,
            "planned_trajectories": len(trajectory_frames),
            "expected_min_total_trajectories": len(trajectory_frames),
            "time_start_s": 0.0,
            "time_end_s": round(sim_time_s, 3),
            "sampling_interval_s": sampling_interval_s,
            "trajectory_files": sorted(trajectory_frames.keys()),
        }

        return {
            "summary_metrics": summary_metrics,
            "packet_events": packet_df,
            "queue_timeseries": queue_df,
            "node_positions": positions_df,
            "routing_summary": routing_summary,
            "topology_graph": topology_graph,
            "demands": demands_payload,
            "allocations_steps": allocations_df,
            "trajectory_summary": trajectory_summary,
            "trajectory_frames": trajectory_frames,
        }

    def work_done(self, result: dict[str, Any] | None = None) -> None:
        if not result:
            return

        metrics = dict(result["summary_metrics"])
        stem = str(metrics["artifact_stem"])
        destinations = [Path(self.data_out) / stem, Path(self.artifact_dir) / stem]
        csv_payloads = {
            "packet_events": result["packet_events"],
            "queue_timeseries": result["queue_timeseries"],
            "node_positions": result["node_positions"],
            "routing_summary": result["routing_summary"],
        }

        for root in destinations:
            if self.reset_target and root.exists():
                shutil.rmtree(root, ignore_errors=True, onerror=self._onerror)
            root.mkdir(parents=True, exist_ok=True)
            (root / f"{stem}_summary_metrics.json").write_text(
                json.dumps(metrics, indent=2),
                encoding="utf-8",
            )
            write_reduce_artifact(
                metrics,
                root,
                worker_id=getattr(self, "_worker_id", 0),
            )
            for name, df in csv_payloads.items():
                payload_df = df if isinstance(df, pd.DataFrame) else pd.DataFrame(df)
                payload_df.to_csv(root / f"{stem}_{name}.csv", index=False)
            pipeline_dir = root / "pipeline"
            pipeline_dir.mkdir(parents=True, exist_ok=True)
            nx.write_gml(result["topology_graph"], pipeline_dir / "topology.gml")
            (pipeline_dir / "demands.json").write_text(
                json.dumps(result["demands"], indent=2),
                encoding="utf-8",
            )
            allocations_df = result["allocations_steps"]
            if not isinstance(allocations_df, pd.DataFrame):
                allocations_df = pd.DataFrame(allocations_df)
            allocations_df.to_csv(pipeline_dir / "allocations_steps.csv", index=False)
            (pipeline_dir / "_trajectory_summary.json").write_text(
                json.dumps(result["trajectory_summary"], indent=2),
                encoding="utf-8",
            )
            for file_name, df in sorted(result["trajectory_frames"].items()):
                payload_df = df if isinstance(df, pd.DataFrame) else pd.DataFrame(df)
                payload_df.to_csv(pipeline_dir / file_name, index=False)

        logger.info("Saved UAV queue artifacts to %s and %s", self.data_out, self.artifact_dir)
