"""Time-stepped routing environment for SB3 training.

It plays through a fixed horizon of demand snapshots (one per step) and lets
the agent output a per-demand allocation fraction between 0 and 1. Reward is
the average served bandwidth fraction. This is intentionally lightweight and
serves as a scaffold: replace observation/action/reward with domain-specific
logic (link loads, paths, feasible routing) when real data is available.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple, List, Optional

import gymnasium as gym
import numpy as np
import pandas as pd
# Optional LinkSim helpers; fall back to lightweight stubs if the worker package is missing.
try:
    from link_sim_worker.link_sim_worker import (
        calculate_capacity_from_snr_db,
        calculate_fspl,
        SpatialHeatmap,
        compute_line_of_sight,
    )
except Exception:  # pragma: no cover - fallback only when link_sim_worker missing
    def calculate_fspl(freq_mhz: float, distances_km):
        """Free-space path loss in dB."""
        d = np.asarray(distances_km, dtype=float)
        return 20 * np.log10(np.maximum(d * 1e3, 1e-3)) + 20 * np.log10(freq_mhz) + 32.44

    def calculate_capacity_from_snr_db(bw_hz: float, snr_db):
        snr_linear = np.power(10.0, np.asarray(snr_db, dtype=float) / 10.0)
        return (bw_hz * np.log2(1.0 + snr_linear)) / 1e6

    class SpatialHeatmap:  # minimal stub
        @staticmethod
        def load(path: str):
            return None

    def compute_line_of_sight(tx_state, rx_state, tx_cfg, rx_cfgs, heatmaps):
        """Simplified LOS: FSPL + Shannon."""
        bw_hz = float(tx_cfg.get("shannon_bande_Hz", 20_000_000.0))
        freq_mhz = float(tx_cfg.get("frequency_MHz", 20_000.0))
        tx_power = float(tx_cfg.get("power", 10.0))
        tx_gain = float(tx_cfg.get("tx_gain_db", tx_cfg.get("TX_gain_db", 30.0)))
        rx_gain = float(rx_cfgs[0].get("rx_gain_db", rx_cfgs[0].get("RX_gain_db", 30.0))) if rx_cfgs else 30.0
        distances_km = np.linalg.norm(np.asarray(tx_state)[:, :3] - np.asarray(rx_state)[:, :3], axis=1) / 1000.0
        fspl_db = calculate_fspl(freq_mhz, distances_km)
        noise_dbm = -174 + 10 * np.log10(bw_hz)
        rx_power_dbm = tx_power + tx_gain + rx_gain - fspl_db
        snr_db = rx_power_dbm - noise_dbm
        cap_mbps = calculate_capacity_from_snr_db(bw_hz, snr_db)
        return pd.DataFrame({"Shannon_capacity_Mbps": cap_mbps})


class TimeRoutingEnv(gym.Env):
    """Lightweight time-stepped routing env."""

    metadata = {"render_modes": []}

    def __init__(
        self,
        *,
        demands_path: str | None = None,
        demands: Iterable[dict[str, Any]] | None = None,
        trajectories_glob: str | None = None,
        trajectories_base: str | Path | None = None,
        sat_trajectories_glob: str | None = None,
        time_step_s: float = 1.0,
        time_horizon: int | None = None,
        seed: int | None = None,
        max_paths: int = 3,
        auto_start_span_s: float | None = None,
        auto_duration_s: float | None = None,
        arrival_rate_hz: float | None = None,
        duration_mean_s: float | None = None,
        contention_mode: str = "proportional",
        predictive_alpha: float = 0.7,
        predictive_min_factor: float = 0.5,
        history_length: int = 8,
    ) -> None:
        super().__init__()
        self.DEFAULT_FREQ_MHZ = 20_000.0
        self.DEFAULT_BW_HZ = 20_000_000.0
        self.DEFAULT_TX_POWER_DBM = 40.0
        self.DEFAULT_TX_GAIN_DB = 30.0
        self.DEFAULT_RX_GAIN_DB = 30.0
        self._rng = np.random.default_rng(seed)
        self._t = 0
        self.time_step_s = max(0.1, float(time_step_s))
        self.auto_start_span_s = auto_start_span_s
        self.auto_duration_s = auto_duration_s
        self.arrival_rate_hz = arrival_rate_hz
        self.duration_mean_s = duration_mean_s
        self.contention_mode = contention_mode
        self.predictive_alpha = float(predictive_alpha)
        self.predictive_min_factor = float(predictive_min_factor)
        self.history_length = max(1, int(history_length))
        self._edge_capacity_history: dict[tuple[int, int], list[float]] = {}
        self.demands = self._load_demands(demands_path, demands)
        if not self.demands:
            self.demands = [{"source": "0", "destination": "0", "bandwidth": 0.0}]
        self.trajectories = {}
        self.trajectories.update(self._load_trajectories(trajectories_glob, base=trajectories_base))
        self.trajectories.update(self._load_trajectories(sat_trajectories_glob, base=trajectories_base))
        self.heatmap_ivdl = self._load_heatmap(Path("link_sim/dataset/CloudMapIvdl.npz"))
        self.heatmap_sat = self._load_heatmap(Path("link_sim/dataset/CloudMapSat.npz"))
        self.sensor_configs = self._load_sensor_configs(Path("link_sim/dataset/antenna_conf.json"))
        self.time_grid = self._build_time_grid(time_horizon=time_horizon)
        self.time_horizon = len(self.time_grid)
        self._assign_time_windows()
        self.max_paths = max(1, int(max_paths))
        n_demands = len(self.demands)
        if n_demands == 0:
            # keep a trivial dimension to avoid SB3 errors; reward will be 0
            n_demands = 1

        self.observation_space = gym.spaces.Box(
            low=0.0, high=1.0, shape=(n_demands * 4,), dtype=np.float32
        )
        self.action_space = gym.spaces.Box(
            low=0.0, high=1.0, shape=(n_demands,), dtype=np.float32
        )

        # cache bandwidths for reward computation
        self._bandwidths = np.array(
            [
                max(1.0, float(item.get("bandwidth", 0.0)))
                for item in (self.demands or [{}])
            ],
            dtype=np.float32,
        )
        self._last_capacities = np.zeros_like(self._bandwidths, dtype=np.float32)
        self._last_latencies = np.zeros_like(self._bandwidths, dtype=np.float32)
        self._priorities = np.array(
            [max(1.0, float(item.get("priority", 1.0))) for item in (self.demands or [{}])],
            dtype=np.float32,
        )
        self._latency_targets = np.array(
            [float(item.get("max_latency", 750)) for item in (self.demands or [{}])],
            dtype=np.float32,
        )

    # ----------------------------
    # Data loaders
    # ----------------------------
    def _load_demands(
        self,
        path: str | None,
        demands: Iterable[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        if demands:
            return [self._normalize_demand(d) for d in demands if isinstance(d, dict)]
        if not path:
            return []
        try:
            payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
        except Exception:
            return []
        if isinstance(payload, list):
            return [self._normalize_demand(d) for d in payload if isinstance(d, dict)]
        return []

    def _normalize_demand(self, d: dict[str, Any]) -> dict[str, Any]:
        out = dict(d)
        out.setdefault("start_time", d.get("start"))
        if out.get("end_time") is None and "duration" in d and out.get("start_time") is not None:
            out["end_time"] = float(out["start_time"]) + float(d.get("duration", 0))
        # Carry over service-aware hints if present
        try:
            out["priority"] = float(out.get("priority", 1.0))
        except Exception:
            out["priority"] = 1.0
        if "max_latency" not in out:
            if "latency" in out:
                out["max_latency"] = out.get("latency")
            elif "latency_ms" in out:
                out["max_latency"] = out.get("latency_ms")
            else:
                out["max_latency"] = 750
        return out

    def _assign_time_windows(self) -> None:
        """Assign start/end times to demands that lack them."""
        horizon_s = self.time_grid[-1] if self.time_grid else 0.0
        for d in self.demands:
            start = d.get("start_time")
            end = d.get("end_time")
            if start is None:
                if self.arrival_rate_hz:
                    # exponential arrival
                    rate = max(1e-6, float(self.arrival_rate_hz))
                    start = float(self._rng.exponential(1.0 / rate))
                elif self.auto_start_span_s is not None:
                    start = float(self._rng.uniform(0.0, self.auto_start_span_s))
                else:
                    start = 0.0
                d["start_time"] = start
            if end is None:
                if self.duration_mean_s:
                    dur = float(self._rng.exponential(self.duration_mean_s))
                elif self.auto_duration_s is not None:
                    dur = float(self.auto_duration_s)
                else:
                    dur = 0.0
                d["end_time"] = float(start + dur) if dur > 0 else None
            # Clamp to horizon
            if horizon_s > 0 and d.get("start_time") is not None:
                d["start_time"] = float(min(d["start_time"], horizon_s))
            if horizon_s > 0 and d.get("end_time") is not None:
                d["end_time"] = float(min(d["end_time"], horizon_s))

    def _load_trajectories(self, glob_pattern: str | None, base: str | Path | None = None) -> dict[str, pd.DataFrame]:
        """Load trajectory parquet files keyed by node id."""
        if not glob_pattern:
            return {}
        frames: dict[str, pd.DataFrame] = {}
        import glob
        pattern = glob_pattern
        if base and not Path(pattern).expanduser().is_absolute():
            pattern = str(Path(base).expanduser() / pattern)

        for fname in glob.glob(pattern):
            try:
                df = pd.read_parquet(fname)
            except Exception:
                try:
                    df = pd.read_csv(fname)
                except Exception:
                    continue
            if not {"time_s", "latitude", "longitude"}.issubset(df.columns):
                continue
            df = df.sort_values("time_s")
            node_id = self._infer_node_id(fname)
            frames[node_id] = df
        return frames

    @staticmethod
    def _infer_node_id(path: str) -> str:
        stem = Path(path).stem  # type: ignore[name-defined]
        match = re.search(r"(\d+)", stem)
        return match.group(1) if match else stem

    def _load_heatmap(self, path: Path) -> SpatialHeatmap | None:
        try:
            if not path.is_absolute():
                # assume agi_share_dir/base resolution done upstream
                path = Path(self._root_share()).expanduser() / path
            return SpatialHeatmap.load(str(path))
        except Exception:
            return None

    def _root_share(self) -> Path:
        """Best-effort share root from env hint."""
        # The worker passes trajectories_base already; fallback to user home.
        return Path.home()

    def _load_sensor_configs(self, path: Path) -> dict[str, Any]:
        try:
            if not path.is_absolute():
                path = Path(self._root_share()).expanduser() / path
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _build_time_grid(self, time_horizon: int | None) -> List[float]:
        """Build a common time grid across all trajectories."""
        if self.trajectories:
            starts = []
            ends = []
            for df in self.trajectories.values():
                starts.append(df["time_s"].min())
                ends.append(df["time_s"].max())
            t0 = min(starts) if starts else 0.0
            t1 = max(ends) if ends else t0
        else:
            t0, t1 = 0.0, 0.0
        if time_horizon is not None:
            t1 = t0 + (time_horizon * self.time_step_s)
        n_steps = max(1, int(math.ceil((t1 - t0) / self.time_step_s)))
        return [t0 + i * self.time_step_s for i in range(n_steps)]

    def _build_graph(self, t: float):
        """Construct a directed graph with capacities/latencies from LOS for all node pairs in demands."""
        node_ids = {str(d.get("source", "0")) for d in self.demands} | {str(d.get("destination", "0")) for d in self.demands}
        pos_cache: dict[str, Optional[tuple[float, float, float, float, float]]] = {}
        for nid in node_ids:
            pos_cache[nid] = self._interp_position(nid, t)

        tx_list = []
        rx_list = []
        edges = []
        nodes = list(node_ids)
        for i, src in enumerate(nodes):
            for j, dst in enumerate(nodes):
                if i == j:
                    continue
                p1 = pos_cache.get(src)
                p2 = pos_cache.get(dst)
                if p1 is None or p2 is None:
                    continue
                tx_list.append(p1)
                rx_list.append(p2)
                edges.append((src, dst))

        capacities = np.full(len(edges), np.nan, dtype=float)
        latencies = np.full(len(edges), 0.0, dtype=float)
        if edges:
            tx_state = np.array(tx_list, dtype=float)
            rx_state = np.array(rx_list, dtype=float)
            tx_cfg = self._pick_sensor("classique_plane")
            rx_cfgs = self._pick_sensor_list("sat")
            capacities = self._capacity_from_los_batch(tx_state, rx_state, tx_cfg, rx_cfgs)
            latencies = np.array(
                [
                    self._haversine_km(pos_cache[src][0], pos_cache[src][1], pos_cache[dst][0], pos_cache[dst][1]) / 299_792 * 1000
                    if pos_cache.get(src) and pos_cache.get(dst) else 0.0
                    for src, dst in edges
                ],
                dtype=float,
            )

        G = nx.DiGraph()
        for nid in nodes:
            G.add_node(int(nid))
        for (src, dst), cap, lat in zip(edges, capacities, latencies):
            if not np.isfinite(cap) or cap <= 0:
                continue
            G.add_edge(int(src), int(dst), capacity=float(cap), latency=float(lat))
            # Track history for simple capacity prediction (anticipation)
            hist = self._edge_capacity_history.setdefault((int(src), int(dst)), [])
            hist.append(float(cap))
            if len(hist) > self.history_length:
                hist.pop(0)

        dist_list = []
        for (src, dst) in edges:
            p1 = pos_cache.get(src)
            p2 = pos_cache.get(dst)
            if p1 and p2:
                dist_list.append(self._haversine_km(p1[0], p1[1], p2[0], p2[1]))
        return G, dist_list

    def _predict_capacity(self, u: int, v: int, current_cap: float) -> float:
        """Simple one-step forecast using exponential smoothing."""
        hist = self._edge_capacity_history.get((u, v))
        if not hist or len(hist) < 2 or not np.isfinite(current_cap):
            return current_cap
        prev = hist[-2] if len(hist) >= 2 else hist[-1]
        if not np.isfinite(prev):
            return current_cap
        predicted = self.predictive_alpha * current_cap + (1 - self.predictive_alpha) * prev
        return max(predicted, self.predictive_min_factor * current_cap)

    def _candidate_paths(self, G: nx.DiGraph) -> dict[int, dict[str, Any]]:
        """Return selected path and candidates for each demand."""
        paths: dict[int, dict[str, Any]] = {}
        for idx, d in enumerate(self.demands):
            src = int(d.get("source", 0))
            dst = int(d.get("destination", 0))
            if src not in G or dst not in G or src == dst:
                continue
            try:
                k_paths = []
                for path in nx.shortest_simple_paths(
                    G,
                    src,
                    dst,
                    weight=lambda u, v, data: 1.0
                    / max(
                        self._predict_capacity(u, v, data.get("capacity", 1e-6)),
                        1e-6,
                    ),
                ):
                    k_paths.append(path)
                    if len(k_paths) >= self.max_paths:
                        break
            except Exception:
                k_paths = []
            if not k_paths:
                continue
            # Select path based on fixed heuristic: highest min-capacity
            best_path = None
            best_cap = -np.inf
            for path in k_paths:
                caps = []
                predicted_caps = []
                for u, v in zip(path[:-1], path[1:]):
                    cap_curr = G.edges[u, v].get("capacity", np.nan)
                    cap_eff = self._predict_capacity(u, v, cap_curr)
                    caps.append(cap_eff)
                    predicted_caps.append(cap_eff)
                min_cap = np.nanmin(caps) if caps else 0.0
                if min_cap > best_cap:
                    best_cap = min_cap
                    best_path = path
            if best_path:
                paths[idx] = {
                    "paths": k_paths,
                    "selected_path": best_path,
                    "path_capacity": best_cap,
                    "predicted_capacity": best_cap,
                }
        self._paths_cache = paths
        return paths

    def reset(self, *, seed: int | None = None, options: Dict[str, Any] | None = None):
        super().reset(seed=seed)
        self._t = 0
        obs = self._build_observation()
        info: Dict[str, Any] = {"time_index": self._t}
        return obs, info

    def step(self, action: Any) -> Tuple[Any, float, bool, bool, Dict[str, Any]]:
        action = np.asarray(action, dtype=np.float32)
        # pad/trim to match n_demands
        if action.shape[0] < self._bandwidths.shape[0]:
            pad = np.zeros(self._bandwidths.shape[0] - action.shape[0], dtype=np.float32)
            action = np.concatenate([action, pad])
        elif action.shape[0] > self._bandwidths.shape[0]:
            action = action[: self._bandwidths.shape[0]]

        served_fraction = np.clip(action, 0.0, 1.0)

        t_now = self.time_grid[min(self._t, len(self.time_grid) - 1)]
        G, distances = self._build_graph(t_now)
        active_mask = self._active_mask(t_now)
        served_fraction = served_fraction * active_mask.astype(np.float32)

        # Path selection per demand
        paths = self._candidate_paths(G)
        requested = self._bandwidths * served_fraction

        # Accumulate edge loads (base delivered = min(requested, bottleneck))
        edge_loads: dict[tuple[int, int], float] = {}
        path_edges: dict[int, list[tuple[int, int]]] = {}
        for idx, req in enumerate(requested):
            if req <= 0 or idx not in paths:
                continue
            path = paths[idx]["selected_path"]
            path_edges[idx] = []
            for u, v in zip(path[:-1], path[1:]):
                path_edges[idx].append((u, v))

        delivered = np.zeros_like(requested)
        path_latencies = np.zeros_like(requested)
        edge_use_counts: dict[tuple[int, int], int] = {}
        scale_factors: dict[tuple[int, int], float] = {}
        for idx, req in enumerate(requested):
            if req <= 0 or idx not in paths:
                continue
            path = paths[idx]["selected_path"]
            caps = []
            lats = []
            for u, v in zip(path[:-1], path[1:]):
                cap = G.edges[u, v].get("capacity", np.nan)
                lat = G.edges[u, v].get("latency", 0.0)
                edge_use_counts[(u, v)] = edge_use_counts.get((u, v), 0) + 1
                caps.append(cap)
                lats.append(lat)
            min_cap = np.nanmin(caps) if caps else 0.0
            total_lat = float(np.nansum(lats)) if lats else 0.0
            delivered[idx] = np.minimum(req, min_cap)
            path_latencies[idx] = total_lat
            # Build base edge load with this min_cap allocation
            for u, v in path_edges.get(idx, []):
                edge_loads[(u, v)] = edge_loads.get((u, v), 0.0) + float(delivered[idx])

        # Proportional contention scaling: enforce per-edge capacity limits
        if edge_loads:
            scale_factors: dict[tuple[int, int], float] = {}
            for (u, v), load in edge_loads.items():
                cap = G.edges[u, v].get("capacity", np.nan)
                if not np.isfinite(cap) or cap <= 0:
                    scale_factors[(u, v)] = 0.0
                else:
                    scale_factors[(u, v)] = min(1.0, cap / max(load, 1e-6))

            for idx, req in enumerate(requested):
                if req <= 0 or idx not in paths:
                    continue
                path = paths[idx]["selected_path"]
                path_scale = 1.0
                for u, v in zip(path[:-1], path[1:]):
                    path_scale = min(path_scale, scale_factors.get((u, v), 1.0))
                delivered[idx] = delivered[idx] * path_scale

        self._last_capacities = np.array([paths.get(i, {}).get("path_capacity", np.nan) for i in range(len(self.demands))], dtype=float)
        self._last_latencies = path_latencies

        over = np.maximum(requested - delivered, 0.0)
        # Latency penalty vs targets
        lat_penalty = 0.0
        if np.isfinite(path_latencies).any():
            over_lat = path_latencies - self._latency_targets
            over_lat = np.maximum(over_lat, 0.0)
            lat_penalty = float(np.mean(over_lat / np.maximum(self._latency_targets, 1.0)))

        # Priority-weighted reward
        reward = float(np.mean((delivered * self._priorities) / np.maximum(self._bandwidths, 1.0))) \
            - 0.5 * float(np.mean(over / np.maximum(self._bandwidths, 1.0))) \
            - 0.1 * lat_penalty

        terminated = self._t + 1 >= self.time_horizon
        truncated = False
        self._t += 1
        obs = self._build_observation()
        info: Dict[str, Any] = {
            "time_index": self._t,
            "allocations": served_fraction.tolist(),
            "distances_km": distances,
            "capacity_mbps": self._last_capacities.tolist(),
            "delivered_mbps": delivered.tolist(),
            "paths": {k: v["selected_path"] for k, v in paths.items()},
            "latencies_ms": path_latencies.tolist(),
            "services": [d.get("service") for d in self.demands],
            "priorities": self._priorities.tolist(),
            "latency_targets": self._latency_targets.tolist(),
            "edge_scale_factors": {f"{u}->{v}": sf for (u, v), sf in scale_factors.items()} if edge_loads else {},
            "predicted_capacity_mbps": [paths.get(i, {}).get("predicted_capacity") for i in range(len(self.demands))],
        }
        return obs, reward, terminated, truncated, info

    def _build_observation(self) -> Any:
        max_bw = float(np.max(self._bandwidths)) if self._bandwidths.size else 1.0
        bw_norm = self._bandwidths / max_bw
        cap_norm = np.zeros_like(bw_norm)
        if self._last_capacities.size:
            cap_norm = self._last_capacities / np.maximum(np.nanmax(self._last_capacities), 1.0)
        lat_norm = np.zeros_like(bw_norm)
        if self._last_latencies.size:
            lat_norm = self._last_latencies / np.maximum(np.nanmax(self._last_latencies), 1.0)
        active_mask = self._active_mask(self.time_grid[min(self._t, len(self.time_grid) - 1)]).astype(np.float32)
        return np.concatenate(
            [
                bw_norm.astype(np.float32),
                cap_norm.astype(np.float32),
                lat_norm.astype(np.float32),
                active_mask.astype(np.float32),
            ]
        )

    # ----------------------------
    # Geometry helpers
    # ----------------------------
    def _pair_distances(self, t: float) -> List[float]:
        """Return distances (km) for each demand's src/dst at time t."""
        distances: List[float] = []
        for demand in self.demands:
            src = str(demand.get("source", "0"))
            dst = str(demand.get("destination", "0"))
            p1 = self._interp_position(src, t)
            p2 = self._interp_position(dst, t)
            if p1 is None or p2 is None:
                distances.append(1e6)
                continue
            distances.append(self._haversine_km(*p1, *p2))
        return distances

    def _interp_position(self, node_id: str, t: float) -> Optional[tuple[float, float, float, float, float]]:
        df = self.trajectories.get(str(node_id))
        if df is None or df.empty:
            return None
        times = df["time_s"].values
        idx = np.searchsorted(times, t, side="left")
        if idx <= 0:
            row = df.iloc[0]
        elif idx >= len(df):
            row = df.iloc[-1]
        else:
            t0, t1 = times[idx - 1], times[idx]
            frac = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
            row0 = df.iloc[idx - 1]
            row1 = df.iloc[idx]
            lat = row0["latitude"] + frac * (row1["latitude"] - row0["latitude"])
            lon = row0["longitude"] + frac * (row1["longitude"] - row0["longitude"])
            alt = row0.get("alt_m", 0.0) + frac * (row1.get("alt_m", 0.0) - row0.get("alt_m", 0.0))
            pitch = row0.get("pitch_deg", 0.0) + frac * (row1.get("pitch_deg", 0.0) - row0.get("pitch_deg", 0.0))
            bearing = row0.get("bearing_deg", 0.0) + frac * (row1.get("bearing_deg", 0.0) - row0.get("bearing_deg", 0.0))
            return float(lat), float(lon), float(alt), float(pitch), float(bearing)
        return (
            float(row["latitude"]),
            float(row["longitude"]),
            float(row.get("alt_m", 0.0)),
            float(row.get("pitch_deg", 0.0)),
            float(row.get("bearing_deg", 0.0)),
        )

    @staticmethod
    def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        r = 6371.0
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        return float(2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a)))

    def _pair_capacities(self, t: float) -> Tuple[np.ndarray, List[float]]:
        """Compute capacity per demand using LinkSim LOS; fallback to FSPL."""
        n = len(self.demands)
        distances = np.full(n, np.inf, dtype=float)
        capacities = np.full(n, np.nan, dtype=float)

        # precompute positions for all nodes at time t
        node_ids = {str(d.get("source", "0")) for d in self.demands} | {str(d.get("destination", "0")) for d in self.demands}
        pos_cache: dict[str, Optional[tuple[float, float, float, float, float]]] = {}
        for nid in node_ids:
            pos_cache[nid] = self._interp_position(nid, t)

        tx_cfg = self._pick_sensor("classique_plane")
        rx_cfgs = self._pick_sensor_list("sat")

        valid_tx = []
        valid_rx = []
        valid_indices = []

        for idx, demand in enumerate(self.demands):
            src = str(demand.get("source", "0"))
            dst = str(demand.get("destination", "0"))
            p1 = pos_cache.get(src)
            p2 = pos_cache.get(dst)
            if p1 is None or p2 is None:
                continue
            valid_indices.append(idx)
            valid_tx.append(p1)
            valid_rx.append(p2)
            distances[idx] = self._haversine_km(p1[0], p1[1], p2[0], p2[1])

        if valid_tx:
            tx_state = np.array(valid_tx, dtype=float)
            rx_state = np.array(valid_rx, dtype=float)
            caps = self._capacity_from_los_batch(tx_state, rx_state, tx_cfg, rx_cfgs)
            for idx_local, idx_global in enumerate(valid_indices):
                capacities[idx_global] = caps[idx_local]

        # fallback: FSPL-based capacity where LOS failed
        mask = ~np.isfinite(capacities)
        if mask.any():
            fspl_db = calculate_fspl(self.DEFAULT_FREQ_MHZ, distances[mask])
            rx_power_dbm = (
                self.DEFAULT_TX_POWER_DBM
                + self.DEFAULT_TX_GAIN_DB
                + self.DEFAULT_RX_GAIN_DB
                - fspl_db
            )
            noise_dbm = -174 + 10 * math.log10(self.DEFAULT_BW_HZ)
            snr_db = rx_power_dbm - noise_dbm
            capacities[mask] = calculate_capacity_from_snr_db(self.DEFAULT_BW_HZ, snr_db)

        return capacities, distances.tolist()

    def _active_mask(self, t: float) -> np.ndarray:
        mask = np.ones(len(self.demands), dtype=bool)
        for idx, d in enumerate(self.demands):
            start = d.get("start_time", 0.0)
            end = d.get("end_time", None)
            if start is not None and t < float(start):
                mask[idx] = False
            if end is not None and t > float(end):
                mask[idx] = False
        return mask

    def _pick_sensor(self, key: str) -> Dict[str, Any]:
        sensors = self.sensor_configs.get(key) or []
        if isinstance(sensors, list) and sensors:
            return sensors[0]
        if isinstance(self.sensor_configs, dict):
            # fallback to first available sensor list
            for val in self.sensor_configs.values():
                if isinstance(val, list) and val:
                    return val[0]
        return {
            "frequency_MHz": self.DEFAULT_FREQ_MHZ,
            "Half-Power_Beamwidth": [30.0, 30.0],
            "ref_loss_db": 3.0,
            "ref_frac": 0.5,
            "efficiency": 0.6,
            "directional": False,
            "power": 10.0,
            "shannon_bande_Hz": self.DEFAULT_BW_HZ,
        }

    def _pick_sensor_list(self, key: str) -> List[Dict[str, Any]]:
        sensors = self.sensor_configs.get(key) or []
        if isinstance(sensors, list) and sensors:
            return sensors
        # fallback to any list
        if isinstance(self.sensor_configs, dict):
            for val in self.sensor_configs.values():
                if isinstance(val, list) and val:
                    return val
        return [self._pick_sensor(key)]

    def _capacity_from_los_batch(self, tx_state, rx_state, tx_cfg, rx_cfgs) -> np.ndarray:
        """Vectorized LOS capacity for multiple link pairs."""
        if self.heatmap_ivdl is None or self.heatmap_sat is None:
            return np.full(len(tx_state), np.nan, dtype=float)
        try:
            df = compute_line_of_sight(
                tx_state,
                rx_state,
                tx_cfg,
                rx_cfgs,
                (self.heatmap_ivdl, self.heatmap_sat),
            )
            if "Shannon_capacity_Mbps" in df:
                caps = np.asarray(df["Shannon_capacity_Mbps"], dtype=float)
            else:
                caps = np.full(len(tx_state), np.nan, dtype=float)
            return caps
        except Exception:
            return np.full(len(tx_state), np.nan, dtype=float)


__all__ = ["TimeRoutingEnv"]
