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
from typing import Any, Dict, Iterable, Tuple, List

import gymnasium as gym
import numpy as np
import pandas as pd
from link_sim_worker.link_sim_worker import (
    calculate_capacity_from_snr_db,
    calculate_fspl,
)


class TimeRoutingEnv(gym.Env):
    """Lightweight time-stepped routing env."""

    metadata = {"render_modes": []}

    def __init__(
        self,
        *,
        demands_path: str | None = None,
        demands: Iterable[dict[str, Any]] | None = None,
        trajectories_glob: str | None = None,
        time_step_s: float = 1.0,
        time_horizon: int | None = None,
        seed: int | None = None,
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
        self.demands = self._load_demands(demands_path, demands)
        if not self.demands:
            self.demands = [{"source": "0", "destination": "0", "bandwidth": 0.0}]
        self.trajectories = self._load_trajectories(trajectories_glob)
        self.time_grid = self._build_time_grid(time_horizon=time_horizon)
        self.time_horizon = len(self.time_grid)
        n_demands = len(self.demands)
        if n_demands == 0:
            # keep a trivial dimension to avoid SB3 errors; reward will be 0
            n_demands = 1

        self.observation_space = gym.spaces.Box(
            low=0.0, high=1.0, shape=(n_demands,), dtype=np.float32
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

    # ----------------------------
    # Data loaders
    # ----------------------------
    def _load_demands(
        self,
        path: str | None,
        demands: Iterable[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        if demands:
            return [d for d in demands if isinstance(d, dict)]
        if not path:
            return []
        try:
            payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
        except Exception:
            return []
        if isinstance(payload, list):
            return [d for d in payload if isinstance(d, dict)]
        return []

    def _load_trajectories(self, glob_pattern: str | None) -> dict[str, pd.DataFrame]:
        """Load trajectory parquet files keyed by node id."""
        if not glob_pattern:
            return {}
        frames: dict[str, pd.DataFrame] = {}
        import glob

        for fname in glob.glob(glob_pattern):
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

        # LinkSim-inspired link budget: FSPL -> SNR -> capacity
        distances = self._pair_distances(self.time_grid[min(self._t, len(self.time_grid) - 1)])
        fspl_db = calculate_fspl(self.DEFAULT_FREQ_MHZ, np.asarray(distances, dtype=float))
        rx_power_dbm = (
            self.DEFAULT_TX_POWER_DBM
            + self.DEFAULT_TX_GAIN_DB
            + self.DEFAULT_RX_GAIN_DB
            - fspl_db
        )
        noise_dbm = -174 + 10 * math.log10(self.DEFAULT_BW_HZ)
        snr_db = rx_power_dbm - noise_dbm
        capacities_mbps = calculate_capacity_from_snr_db(self.DEFAULT_BW_HZ, snr_db)

        requested = self._bandwidths * served_fraction
        delivered = np.minimum(requested, capacities_mbps)
        reward = float(np.mean(delivered / np.maximum(self._bandwidths, 1.0)))

        terminated = self._t + 1 >= self.time_horizon
        truncated = False
        self._t += 1
        obs = self._build_observation()
        info: Dict[str, Any] = {
            "time_index": self._t,
            "allocations": served_fraction.tolist(),
            "distances_km": distances,
            "capacity_mbps": capacities_mbps.tolist(),
            "delivered_mbps": delivered.tolist(),
        }
        return obs, reward, terminated, truncated, info

    def _build_observation(self) -> Any:
        # Normalized bandwidth demand as a placeholder observation.
        max_bw = float(np.max(self._bandwidths)) if self._bandwidths.size else 1.0
        norm = self._bandwidths / max_bw
        return norm.astype(np.float32)

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

    def _interp_position(self, node_id: str, t: float):
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
            return float(lat), float(lon)
        return float(row["latitude"]), float(row["longitude"])

    @staticmethod
    def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        r = 6371.0
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        return float(2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


__all__ = ["TimeRoutingEnv"]
