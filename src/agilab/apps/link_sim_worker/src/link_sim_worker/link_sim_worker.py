import csv
import pandas as pd
import polars as pl
import os
import re
import numpy as np
import glob
import warnings
from pathlib import Path
warnings.filterwarnings('ignore')
import math
import json
import multiprocessing as mp
import random
from noise import pnoise2
from datetime import datetime as dt
import traceback
import logging
from typing import Any, Union
from concurrent.futures import ThreadPoolExecutor, as_completed
from types import SimpleNamespace

from agi_node.polars_worker import PolarsWorker
from agi_node.agi_dispatcher import BaseWorker

logger = logging.getLogger(__name__)

_DATAFRAME_SUFFIXES = (".csv", ".parquet", ".pq", ".parq")


def _iter_data_files(folder: Path, *, include_parquet: bool = True) -> list[Path]:
    patterns = ["*.csv"]
    if include_parquet:
        patterns.extend(["*.parquet", "*.pq", "*.parq"])
    files: list[Path] = []
    for pattern in patterns:
        files.extend(sorted(folder.glob(pattern)))
    return [path for path in files if not path.name.startswith("._")]


def _load_dataframe(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".parquet", ".pq", ".parq"}:
        try:
            return pd.read_parquet(path)
        except Exception:
            return pl.read_parquet(path).to_pandas()
    raise ValueError(f"Unsupported data file format: {path.suffix}")


def _ensure_plane_identifier(
    raw_value: Any,
    label: str,
    label_map: dict[str, int],
    next_available: int,
) -> tuple[int, int]:
    plane_numeric: int | None = None
    if raw_value is not None:
        try:
            plane_numeric = int(raw_value)
        except (TypeError, ValueError):
            pass

    if plane_numeric is None:
        plane_numeric = label_map.get(label)
        if plane_numeric is None:
            plane_numeric = next_available
            label_map[label] = plane_numeric
            next_available = plane_numeric + 1
    else:
        if label not in label_map:
            label_map[label] = plane_numeric
        if plane_numeric >= next_available:
            next_available = plane_numeric + 1

    return plane_numeric, next_available


class _MutableNamespace(SimpleNamespace):
    def __getitem__(self, key):
        return getattr(self, key)

    def __setitem__(self, key, value):
        setattr(self, key, value)


class SpatialHeatmap:

    def __init__(
        self,
        x_min,
        x_max,
        z_min,
        z_max,
        step,
        center=(0, 0),
        cloud_presence_threshold=0.0,
        cloud_noise_scale=None,
        density_noise_scale=None,
        cloud_amplitude=1.5,
        tile_size_x=50,
        tile_size_z=50,
        num_cores=None,
        heatmap=None,
        presence_octaves=4,
        presence_persistence=0.5,
        presence_lacunarity=2.0,
        density_octaves=2,
        density_persistence=0.5,
        density_lacunarity=2.0,
    ):

        self.x_min = x_min
        self.x_max = x_max
        self.z_min = z_min
        self.z_max = z_max
        self.step = step
        self.center = center
        self.cloud_presence_threshold = cloud_presence_threshold
        self.cloud_noise_scale = cloud_noise_scale or 1 / 200_000.0
        self.density_noise_scale = density_noise_scale or 1 / 300_000.0
        self.cloud_amplitude = cloud_amplitude
        self.tile_size_x = tile_size_x
        self.tile_size_z = tile_size_z
        self.num_cores = num_cores or mp.cpu_count()

        self.x_coords = np.arange(x_min, x_max, step)
        self.z_coords = np.arange(z_min, z_max, step)

        self.nx = len(self.x_coords)
        self.nz = len(self.z_coords)
        self.presence_octaves = presence_octaves
        self.presence_persistence = presence_persistence
        self.presence_lacunarity = presence_lacunarity
        self.density_octaves = density_octaves
        self.density_persistence = density_persistence
        self.density_lacunarity = density_lacunarity
        if heatmap is not None:
            self.heatmap = heatmap

    @classmethod
    def load(cls, filename):
        path = Path(filename)
        if not path.is_file():
            raise FileNotFoundError(f"File not found: {filename}")
        data = np.load(filename)
        files = set(data.files)
        # Older heatmap archives omitted advanced noise parameters. Fall back to
        # the generation defaults so legacy datasets keep working.
        presence_octaves = data['presence_octaves'].item() if 'presence_octaves' in files else 4
        presence_persistence = data['presence_persistence'].item() if 'presence_persistence' in files else 0.5
        presence_lacunarity = data['presence_lacunarity'].item() if 'presence_lacunarity' in files else 2.0
        density_octaves = data['density_octaves'].item() if 'density_octaves' in files else 2
        density_persistence = data['density_persistence'].item() if 'density_persistence' in files else 0.5
        density_lacunarity = data['density_lacunarity'].item() if 'density_lacunarity' in files else 2.0

        obj = cls(
            x_min=data['x_min'].item(),
            x_max=data['x_max'].item(),
            z_min=data['z_min'].item(),
            z_max=data['z_max'].item(),
            step=data['step'].item(),
            center=tuple(data['center']),
            cloud_presence_threshold=data['cloud_presence_threshold'].item(),
            cloud_noise_scale=data['cloud_noise_scale'].item(),
            density_noise_scale=data['density_noise_scale'].item(),
            cloud_amplitude=data['cloud_amplitude'].item(),
            tile_size_x=data['tile_size_x'].item(),
            tile_size_z=data['tile_size_z'].item(),
            presence_octaves=presence_octaves,
            presence_persistence=presence_persistence,
            presence_lacunarity=presence_lacunarity,
            density_octaves=density_octaves,
            density_persistence=density_persistence,
            density_lacunarity=density_lacunarity,
        )
        return obj

    @classmethod
    def from_file_or_generate(cls, save_uri, force_init, **kwargs):
        """
        Factory method: load from file if exists, else generate new heatmap
        kwargs are passed to __init__ if generating.
        """
        path = Path(save_uri)
        if force_init:
            print("force skip loading...")
            return cls(**kwargs)
        elif save_uri and path.is_file():
            print(f"Loading heatmap from {save_uri}")
            return cls.load(save_uri)
        else:
            if save_uri:
                print(f"Save file does not exist: {save_uri}, generating new heatmap.")
            return cls(**kwargs)

    def _perlin2d_scalar(self, x, z, octaves=None, persistence=None, lacunarity=None):
        # Use self values if none provided (or pass all from self)
        octaves = self.presence_octaves if octaves is None else octaves
        persistence = self.presence_persistence if persistence is None else persistence
        lacunarity = self.presence_lacunarity if lacunarity is None else lacunarity
        return pnoise2(x, z, octaves=octaves, persistence=persistence, lacunarity=lacunarity)

    def _process_tile(self, tile_bounds):
        z_start, z_end, x_start, x_end = tile_bounds
        rows = z_end - z_start
        cols = x_end - x_start

        tile_heatmap = np.zeros((rows, cols), dtype=np.float32)

        for i_local, i in enumerate(range(z_start, z_end)):
            z = self.z_coords[i]
            for j_local, j in enumerate(range(x_start, x_end)):
                x = self.x_coords[j]

                nx_presence = (x + self.center[0]) * self.cloud_noise_scale
                nz_presence = (z + self.center[1]) * self.cloud_noise_scale
                presence_val = self._perlin2d_scalar(
                    nx_presence,
                    nz_presence,
                    self.presence_octaves,
                    self.presence_persistence,
                    self.presence_lacunarity,
                )

                if presence_val > self.cloud_presence_threshold:
                    nx_density = (x + self.center[0]) * self.density_noise_scale
                    nz_density = (z + self.center[1]) * self.density_noise_scale
                    density_val = self._perlin2d_scalar(
                        nx_density,
                        nz_density,
                        self.density_octaves,
                        self.density_persistence,
                        self.density_lacunarity,
                    )
                    density_norm = (density_val + 0.5) / 2
                    density = density_norm * self.cloud_amplitude
                    tile_heatmap[i_local, j_local] = np.clip(density, 0, 9999)
                else:
                    tile_heatmap[i_local, j_local] = 0

        return (z_start, z_end, x_start, x_end, tile_heatmap)

    def _generate_heatmap(self):
        # Create tile bounds
        tile_bounds_list = []
        for z_start in range(0, self.nz, self.tile_size_z):
            z_end = min(z_start + self.tile_size_z, self.nz)
            for x_start in range(0, self.nx, self.tile_size_x):
                x_end = min(x_start + self.tile_size_x, self.nx)
                tile_bounds_list.append((z_start, z_end, x_start, x_end))

        print(f"Generating heatmap with {len(tile_bounds_list)} tiles on {self.num_cores} cores...")

        with mp.Pool(self.num_cores) as pool:
            results = pool.map(self._process_tile, tile_bounds_list)

        heatmap = np.zeros((self.nz, self.nx), dtype=np.float32)
        for z_start, z_end, x_start, x_end, tile in results:
            heatmap[z_start:z_end, x_start:x_end] = tile

        return heatmap

    def query_points(self, points: np.ndarray) -> np.ndarray:
        """
        Query heatmap values at multiple (X, Y, Z) points.
        Returns an array of heatmap values sampled at the (X, Z) coordinates of the points.

        Args:
            points (np.ndarray): Array of shape (N, 3), with columns [X, Y, Z].

        Returns:
            np.ndarray: Array of length N with heatmap values at corresponding (X, Z) points.
        """
        if points.shape[1] != 3:
            raise ValueError("Input points array must have shape (N, 3)")

        # Extract X and Z from points
        xs = points[:, 0]
        zs = points[:, 2]

        # Convert coords to indices
        rows, cols = self.coord_to_index(xs, zs)

        # Prepare output array
        values = np.zeros(len(points), dtype=np.float32)

        # For each point, fetch heatmap value if in bounds
        for i, (row, col) in enumerate(zip(rows, cols)):
            if 0 <= row < self.nz and 0 <= col < self.nx:
                values[i] = self.heatmap[row, col]
            else:
                values[i] = 0.0

        return values

    def coord_to_index(self, x, z):
        """
        Vectorized coordinate to index conversion.
        Accepts scalar or numpy arrays for x and z.
        Returns rows and cols as numpy arrays.
        """
        x = np.asarray(x)
        z = np.asarray(z)

        cols = np.round(((x - self.center[0]) + (self.x_max - self.x_min) / 2) / self.step).astype(int)
        rows = np.round(((z - self.center[1]) + (self.z_max - self.z_min) / 2) / self.step).astype(int)
        return rows, cols

    def __getitem__(self, coords):
        if isinstance(coords, tuple) and len(coords) == 2:
            x, z = coords
            # Shift query coords by center offset because the grid coords exclude center:
            # The grid coordinates self.x_coords are absolute world coords,
            # so no shift is necessary here.
            row, col = self.coord_to_index(x, z)
            print(row, col)
            if 0 <= row < self.nz and 0 <= col < self.nx:
                return self.heatmap[row, col]
            else:
                return 0.0  # Out of bounds return 0
        else:
            raise KeyError("Coordinates must be a tuple (x, z)")

    def save(self, filename):
        if os.path.exists(filename):
            os.remove(filename)
            print("File removed.")
        else:
            print("File does not exist.")
        np.savez_compressed(
            filename,
            x_min=self.x_min,
            x_max=self.x_max,
            z_min=self.z_min,
            z_max=self.z_max,
            step=self.step,
            center=self.center,
            cloud_presence_threshold=self.cloud_presence_threshold,
            cloud_noise_scale=self.cloud_noise_scale,
            density_noise_scale=self.density_noise_scale,
            cloud_amplitude=self.cloud_amplitude,
            tile_size_x=self.tile_size_x,
            tile_size_z=self.tile_size_z,
            presence_octaves=self.presence_octaves,
            presence_persistence=self.presence_persistence,
            presence_lacunarity=self.presence_lacunarity,
            density_octaves=self.density_octaves,
            density_persistence=self.density_persistence,
            density_lacunarity=self.density_lacunarity,
        )
        print(f"Heatmap data and properties saved to {filename}")

    def compute_density_for_points(self, xs, zs):
        # Use the same noise parameters as in _process_tile
        # 1. Cloud presence
        nx_presence = (xs) * self.cloud_noise_scale
        nz_presence = (zs) * self.cloud_noise_scale

        # Vectorize Perlin for presence
        perlin = np.vectorize(self._perlin2d_scalar)
        presence_val = perlin(nx_presence, nz_presence,
                              self.presence_octaves if hasattr(self, 'presence_octaves') else 4,
                              self.presence_persistence if hasattr(self, 'presence_persistence') else 0.5,
                              self.presence_lacunarity if hasattr(self, 'presence_lacunarity') else 2.0)

        mask = presence_val > self.cloud_presence_threshold

        densities = np.zeros_like(xs, dtype=np.float32)
        if np.any(mask):
            # 2. Density
            nx_density = (xs[mask]) * self.density_noise_scale
            nz_density = (zs[mask]) * self.density_noise_scale
            density_val = perlin(nx_density, nz_density,
                                 self.density_octaves if hasattr(self, 'density_octaves') else 2,
                                 self.density_persistence if hasattr(self, 'density_persistence') else 0.5,
                                 self.density_lacunarity if hasattr(self, 'density_lacunarity') else 2.0)
            density_norm = (density_val + 0.5) / 2
            density = density_norm * self.cloud_amplitude
            densities[mask] = np.clip(density, 0, 255)
        return densities

    def compute_density_for_point(self, x, z):
        nx_presence = (x + self.center[0]) * self.cloud_noise_scale
        nz_presence = (z + self.center[1]) * self.cloud_noise_scale
        presence_val = self._perlin2d_scalar(nx_presence, nz_presence, octaves=4, persistence=0.5, lacunarity=2.0)

        if presence_val > self.cloud_presence_threshold:
            nx_density = (x + self.center[0]) * self.density_noise_scale
            nz_density = (z + self.center[1]) * self.density_noise_scale
            density_val = self._perlin2d_scalar(nx_density, nz_density, octaves=2)
            density_norm = (density_val + 0.5) / 2
            density = density_norm * self.cloud_amplitude
            return np.clip(density, 0, 9999)
        else:
            return 0.0
"""
Signal Propagation and Geometry Utilities
========================================

This module provides tools for computing signal propagation, geometric relationships,
antenna pattern effects, and data processing for aircraft/satellite scenarios.
Functions are vectorized for efficiency and designed for scientific clarity.
"""

def compute_bearing_and_pitch(origin_geodetic, target_geodetic):
    """
    Compute compass bearing and elevation pitch from origin points to target points.

    Parameters
    ----------
    origin_geodetic : np.ndarray
        Shape (N, 3) array of [latitude_deg, longitude_deg, altitude_m] for origin points.
    target_geodetic : np.ndarray
        Shape (N, 3) array of [latitude_deg, longitude_deg, altitude_m] for target points.

    Returns
    -------
    np.ndarray
        (N, 2) array: columns [bearing_deg, pitch_deg].

    Notes
    -----
    - Bearing is the clockwise angle from geographic north to the target (0° = north).
    - Pitch is the elevation angle above the local horizontal to the target.
    - Uses the spherical Earth model and great-circle geometry for bearing,
      linear altitude difference for pitch.
    """
    origin_geodetic = np.asarray(origin_geodetic)
    target_geodetic = np.asarray(target_geodetic)

    # Convert to radians
    origin_lat_rad = np.deg2rad(origin_geodetic[:, 0])
    origin_lon_rad = np.deg2rad(origin_geodetic[:, 1])
    origin_alt_m = origin_geodetic[:, 2]

    target_lat_rad = np.deg2rad(target_geodetic[:, 0])
    target_lon_rad = np.deg2rad(target_geodetic[:, 1])
    target_alt_m = target_geodetic[:, 2]

    delta_lon_rad = target_lon_rad - origin_lon_rad

    # Bearing calculation
    x_comp = np.sin(delta_lon_rad) * np.cos(target_lat_rad)
    y_comp = (np.cos(origin_lat_rad) * np.sin(target_lat_rad) -
              np.sin(origin_lat_rad) * np.cos(target_lat_rad) * np.cos(delta_lon_rad))
    bearing_rad = np.arctan2(x_comp, y_comp)
    bearing_deg = (np.rad2deg(bearing_rad) + 360) % 360

    # Great-circle distance (meters)
    delta_lat_rad = target_lat_rad - origin_lat_rad
    a = (np.sin(delta_lat_rad / 2) ** 2 +
         np.cos(origin_lat_rad) * np.cos(target_lat_rad) * np.sin(delta_lon_rad / 2) ** 2)
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
    EARTH_RADIUS = 6_371_000.0  # meters
    surface_distance_m = EARTH_RADIUS * c

    # Pitch calculation
    delta_altitude = target_alt_m - origin_alt_m
    pitch_rad = np.arctan2(delta_altitude, surface_distance_m)
    pitch_deg = np.rad2deg(pitch_rad)

    return np.column_stack((bearing_deg, pitch_deg))

def calculate_cloud_loss(
        origins: np.ndarray,
        target_origins: np.ndarray,
        angles: np.ndarray,
        max_d: np.ndarray,
        heatmaps: tuple
) -> np.ndarray:
    """
    Estimate cloud attenuation loss along the line-of-sight path.

    Parameters
    ----------
    transmitter_xyz : np.ndarray
        (N, 3) array: Cartesian coordinates (meters) of transmission origin points.
    receiver_xyz : np.ndarray
        (N, 3) array: Cartesian coordinates (meters) of receivers (not directly used here).
    transmitter_orientation : np.ndarray
        Array of angles for orientation (not directly used here).
    propagation_distance : np.ndarray
        (N,) array of propagation distances in meters (or km, as appropriate).
    cloud_heatmaps : tuple
        Tuple of two SpatialHeatmap objects: (IVDL_heatmap, Satellite_heatmap).

    Returns
    -------
    np.ndarray
        Array of estimated cloud attenuation values (same length as input).

    Notes
    -----
    - The function chooses the appropriate cloud field based on the spatial
      position (Y axis) and queries the density at the transmitter position.
    - Loss is scaled by the path distance for one heatmap, or directly sampled for another.
    """
    if origins[0, 1] > 300_000 or target_origins[0, 1] > 300_000:
        values = heatmaps[1].compute_density_for_points(origins[:, 0], origins[:, 2])
    else:
        values = heatmaps[0].compute_density_for_points(origins[:, 0], origins[:, 2]) * max_d
    return values

def convert_angles_to_directions(bearing_pitch_angles: np.ndarray) -> np.ndarray:
    """
    Convert [bearing_deg, pitch_deg] angles to normalized 3D unit vectors.

    Parameters
    ----------
    bearing_pitch_angles : np.ndarray
        (N, 2) array: Each row is [bearing_deg, pitch_deg].

    Returns
    -------
    np.ndarray
        (N, 3) array of 3D unit vectors [x, z, y].

    Notes
    -----
    Converts from spherical to Cartesian coordinates:
        x = cos(pitch) * sin(bearing)
        y = cos(pitch) * cos(bearing)
        z = sin(pitch)
    (Angles in radians.)
    """
    bearing_pitch_angles = np.atleast_2d(bearing_pitch_angles).astype(float)
    if bearing_pitch_angles.shape[1] != 2:
        raise ValueError("angles must be of shape (N,2) with bearing and pitch")
    bearing_rad = np.deg2rad(bearing_pitch_angles[:, 0])
    pitch_rad = np.deg2rad(bearing_pitch_angles[:, 1])

    x_component = np.cos(pitch_rad) * np.sin(bearing_rad)
    y_component = np.cos(pitch_rad) * np.cos(bearing_rad)
    z_component = np.sin(pitch_rad)

    direction_vectors = np.stack((x_component, z_component, y_component), axis=1)
    norm = np.linalg.norm(direction_vectors, axis=1, keepdims=True)
    return direction_vectors / norm
def geo_to_xyz(geodetic_coords: np.ndarray) -> np.ndarray:
    """
    Convert geographic coordinates [lat, lon, alt] to Cartesian [X_east, Z_up, Y_north].

    Parameters
    ----------
    geodetic_coords : np.ndarray
        (N, 3) array of [latitude_deg, longitude_deg, altitude_m].

    Returns
    -------
    np.ndarray
        (N, 3) array of [X_east, Z_up, Y_north] in meters.

    Notes
    -----
    Uses a flat Earth approximation: multiplies radians by Earth's radius (6,371,000 m).
    """
    EARTH_RADIUS = 6_371_000.0
    geodetic_coords = np.asarray(geodetic_coords, dtype=float)
    latitude_rad = np.deg2rad(geodetic_coords[:, 0])
    longitude_rad = np.deg2rad(geodetic_coords[:, 1])
    altitude_m = geodetic_coords[:, 2]

    x_east = EARTH_RADIUS * longitude_rad
    y_north = EARTH_RADIUS * latitude_rad
    z_up = altitude_m

    return np.vstack((x_east, z_up, y_north)).T


def combine_csvs_from_folder(
    flights_folder_path,
    satellites_folder_path,
    index_column='time_s'
) -> pd.DataFrame:
    """Merge flight and satellite telemetry into a time-aligned DataFrame."""
    flights_folder = Path(flights_folder_path)
    satellites_folder = Path(satellites_folder_path)

    if not flights_folder.is_dir():
        print(f"Error: Folder '{flights_folder_path}' not found.")
        return None
    if not satellites_folder.is_dir():
        print(f"Error: Folder '{satellites_folder_path}' not found.")
        return None

    flight_files = _iter_data_files(flights_folder, include_parquet=True)
    satellite_files = _iter_data_files(satellites_folder, include_parquet=True)

    if not flight_files:
        print(f"No dataframes found in '{flights_folder_path}'.")
        return None
    if len(flight_files) < 2:
        print(f"need at least 2 plane trajectory in '{flights_folder_path}'.")
        return None

    plane_names: list[str] = []
    plane_ids: list[int] = []
    dataframes_list: list[pd.DataFrame] = []
    json_label: dict[int, str] = {}
    label_map: dict[str, int] = {}
    next_plane_id = 0
    max_trajectory_length = 0

    for file_path in flight_files:
        try:
            df = _load_dataframe(file_path)
            df = df.copy()
            if 'worker_id' in df.columns:
                df.drop('worker_id', axis=1, inplace=True)
            if 'time_s' in df.columns:
                df['time_s'] = pd.to_numeric(df['time_s'], errors='coerce')
                df = df.dropna(subset=['time_s'])
                df.sort_values('time_s', inplace=True)
            plane_label = str(
                df['plane_label'].iloc[0]
                if 'plane_label' in df.columns
                else file_path.stem.replace('_traj', '')
            )
            raw_plane_value = df['plane_id'].iloc[0] if 'plane_id' in df.columns else None
            plane_numeric, next_plane_id = _ensure_plane_identifier(
                raw_plane_value,
                plane_label,
                label_map,
                next_plane_id,
            )
            df['plane_id'] = plane_numeric
            df['plane_label'] = plane_label
            if {'plane_id', 'time_s'}.issubset(df.columns):
                df = df.drop_duplicates(subset=['plane_id', 'time_s'], keep='last')
                df['time_s'] = df['time_s'].astype(int)
            plane_names.append(plane_label)
            plane_ids.append(plane_numeric)
            max_trajectory_length = max(max_trajectory_length, df.shape[0])
            df['source_file'] = flights_folder / file_path.name
            df['file_name'] = file_path.name
            json_label[plane_numeric] = plane_label
            dataframes_list.append(df)
        except pd.errors.EmptyDataError:
            print(f"Warning: {file_path.name} is empty and will be skipped.")
        except Exception as exc:
            print(f"Error reading {file_path.name}: {exc}")

    for file_path in satellite_files:
        try:
            df = _load_dataframe(file_path)
            df = df.copy()
            if 'worker_id' in df.columns:
                df.drop('worker_id', axis=1, inplace=True)
            if 'time_s' in df.columns:
                df['time_s'] = pd.to_numeric(df['time_s'], errors='coerce')
                df = df.dropna(subset=['time_s'])
                df.sort_values('time_s', inplace=True)
            plane_label = str(
                df['plane_label'].iloc[0]
                if 'plane_label' in df.columns
                else file_path.stem.replace('_traj', '')
            )
            raw_plane_value = df['plane_id'].iloc[0] if 'plane_id' in df.columns else None
            plane_numeric, next_plane_id = _ensure_plane_identifier(
                raw_plane_value,
                plane_label,
                label_map,
                next_plane_id,
            )
            df['plane_id'] = plane_numeric
            df['plane_label'] = plane_label
            if {'plane_id', 'time_s'}.issubset(df.columns):
                df = df.drop_duplicates(subset=['plane_id', 'time_s'], keep='last')
                df['time_s'] = df['time_s'].astype(int)
            df['source_file'] = satellites_folder / file_path.name
            df['file_name'] = file_path.name
            json_label[plane_numeric] = plane_label
            dataframes_list.append(df)
        except pd.errors.EmptyDataError:
            print(f"Warning: {file_path.name} is empty and will be skipped.")
        except Exception as exc:
            print(f"Error reading {file_path.name}: {exc}")

    if not dataframes_list:
        print("No files could be successfully read and processed.")
        return None

    combined_df = pd.concat(dataframes_list, ignore_index=True)

    if index_column in combined_df.columns:
        combined_df[index_column] = pd.to_numeric(combined_df[index_column], errors='coerce')
        combined_df = combined_df.dropna(subset=[index_column])
        combined_df[index_column] = combined_df[index_column].astype(int)
        if 'plane_id' in combined_df.columns:
            combined_df.sort_values(by=['plane_id', index_column], inplace=True)
            combined_df = combined_df.drop_duplicates(subset=['plane_id', index_column], keep='last')
    else:
        print(
            f"\nWarning: Column '{index_column}' not found in the combined DataFrame."
        )
        print("The DataFrame will be returned without this index set.")
        print("Available columns:", combined_df.columns.tolist())

    max_time = int(combined_df[index_column].max())
    timeline = np.arange(0, max_time + 1, dtype=int)

    frames: list[pd.DataFrame] = []
    for pid, group in combined_df.groupby('plane_id', sort=False):
        group = group.sort_values(index_column)
        group = group.drop_duplicates(subset=[index_column], keep='last')
        group = group.set_index(index_column, drop=False)
        group = group[~group.index.duplicated(keep='last')]
        reindexed = group.reindex(timeline)
        reindexed[index_column] = reindexed.index
        reindexed['plane_id'] = pid
        reindexed['plane_label'] = json_label.get(pid, str(pid))
        frames.append(reindexed.ffill())

    combined_df = pd.concat(frames)
    combined_df.index.name = index_column
    return combined_df, json_label, max_trajectory_length, plane_names, plane_ids

def calculate_capacity_from_snr_db(
        bandwidth_hz,
        snr_db
):
    """
    Compute Shannon channel capacity (Mbps) given bandwidth and SNR (in dB).

    Parameters
    ----------
    bandwidth_hz : float or np.ndarray
        Channel bandwidth in Hz (must be > 0).
    snr_db : float or np.ndarray
        Signal-to-noise ratio in dB.

    Returns
    -------
    np.ndarray
        Channel capacity in Mbps.

    Notes
    -----
    Uses formula:
        C = B * log2(1 + SNR_linear)
        SNR_linear = 10^(SNR_dB/10)
    """
    bandwidth_array = np.asarray(bandwidth_hz, dtype=float)
    snr_db_array = np.asarray(snr_db, dtype=float)

    try:
        bandwidth_broadcast, snr_broadcast = np.broadcast_arrays(bandwidth_array, snr_db_array)
    except ValueError:
        raise ValueError("bandwidth_hz and snr_db must be broadcastable to the same shape.")

    valid_bandwidth = bandwidth_broadcast > 0
    channel_capacity = np.full(bandwidth_broadcast.shape, np.nan, dtype=float)
    snr_linear = 10.0 ** (snr_broadcast[valid_bandwidth] / 10.0)
    channel_capacity[valid_bandwidth] = bandwidth_broadcast[valid_bandwidth] * np.log2(1 + snr_linear) / 1e6
    return channel_capacity

def watts_to_dBm(power_watts: float) -> float:
    """
    Convert transmit power in watts to dBm.

    Parameters
    ----------
    power_watts : float
        Power in watts (must be > 0).

    Returns
    -------
    float
        Power in dBm.

    Notes
    -----
    Uses dBm = 10 * log10(power_watts * 1000)
    """
    if power_watts <= 0:
        raise ValueError("Power must be positive.")
    return 10 * math.log10(power_watts * 1000)

def calculate_antenna_gain(beamwidth_degrees, efficiency=0.7) -> float:
    """
    Estimate antenna gain (dBi) from half-power beamwidths and efficiency.

    Parameters
    ----------
    beamwidth_degrees : tuple or ndarray
        Tuple of (horizontal_bw_deg, vertical_bw_deg) or array-like of shape (..., 2).
    efficiency : float or ndarray
        Antenna efficiency between 0 and 1.

    Returns
    -------
    float or ndarray
        Antenna gain in dBi.

    Notes
    -----
    Formula:
        G_linear = efficiency * (41253 / (HPBW_horizontal * HPBW_vertical))
        G_dBi = 10 * log10(G_linear)
    """
    if isinstance(beamwidth_degrees, (tuple, list)):
        h_bw, v_bw = beamwidth_degrees
        if h_bw <= 0 or v_bw <= 0:
            raise ValueError("Beamwidths must be positive.")
        if not (0 < efficiency <= 1):
            raise ValueError("Efficiency must be between 0 and 1.")
    else:
        h_bw, v_bw = beamwidth_degrees[:, 0], beamwidth_degrees[:, 1]
        if np.any(h_bw <= 0) or np.any(v_bw <= 0):
            raise ValueError("All beamwidth values must be positive.")
        if np.any((efficiency <= 0) | (efficiency > 1)):
            raise ValueError("All efficiency values must be between 0 (exclusive) and 1 (inclusive).")
    gain_linear = efficiency * (41253 / (h_bw * v_bw))
    gain_dBi = 10 * np.log10(gain_linear)
    return gain_dBi

def calculate_off_axis_loss_elliptical(
        hpbw_degrees: Union[tuple, np.ndarray],
        off_axis_angles,
        ref_loss_db: Union[float, np.ndarray],
        ref_frac: Union[float, np.ndarray]
) -> np.ndarray:
    """
    Calculate off-axis antenna loss (dB) using elliptical Gaussian model.

    Parameters
    ----------
    hpbw_degrees : tuple or ndarray
        (Azimuth_HPWB_deg, Elevation_HPWB_deg) or array shape (..., 2).
    off_axis_angles : np.ndarray
        (N, 2) array of off-axis angles [azimuth_deg, elevation_deg].
    ref_loss_db : float
        Reference loss (dB) at ref_frac * HPBW.
    ref_frac : float
        Fraction of HPBW for reference loss (0 < ref_frac < 1).

    Returns
    -------
    np.ndarray
        (N,) array of loss values in dB.

    Notes
    -----
    Models loss as quadratic in angle, with scaling set by ref_loss_db at ref_frac*HPBW.
    """
    if isinstance(hpbw_degrees, (tuple, list)):
        hpbw_az, hpbw_el = hpbw_degrees
        if hpbw_az <= 0 or hpbw_el <= 0:
            raise ValueError("Both HPBW values must be positive.")
        if not (0 < ref_frac < 1):
            raise ValueError("ref_frac must be between 0 and 1.")
    else:
        hpbw_az, hpbw_el = hpbw_degrees[:, 0], hpbw_degrees[:, 1]
        if np.any(hpbw_az <= 0) or np.any(hpbw_el <= 0):
            raise ValueError("Both HPBW values must be positive.")
        if np.any((0 > ref_frac) | (ref_frac > 1)):
            raise ValueError("ref_frac must be between 0 and 1.")
    off_axis = np.abs(np.asarray(off_axis_angles, dtype=float))
    if off_axis.ndim != 2 or off_axis.shape[1] != 2:
        raise ValueError("off_axis_angles must be of shape (N,2).")

    lin2db = 10 * np.log10(np.e)
    sigma_az = (ref_frac * hpbw_az) / np.sqrt(2 * ref_loss_db / lin2db)
    sigma_el = (ref_frac * hpbw_el) / np.sqrt(2 * ref_loss_db / lin2db)

    loss_az = lin2db * off_axis[:, 0] ** 2 / (2 * sigma_az ** 2)
    loss_el = lin2db * off_axis[:, 1] ** 2 / (2 * sigma_el ** 2)

    return loss_az + loss_el

def calculate_fspl(frequency_mhz, distance_km):
    """
    Calculate Free-Space Path Loss (FSPL, dB) given frequency and distance.

    Parameters
    ----------
    frequency_mhz : float or ndarray
        Frequency in MHz (> 0).
    distance_km : float or ndarray
        Distance in kilometers (> 0).

    Returns
    -------
    float or ndarray
        FSPL in dB.

    Notes
    -----
    Uses:
        FSPL(dB) = 32.44 + 20 * log10(frequency_MHz) + 20 * log10(distance_km)
    """
    freq = np.asarray(frequency_mhz, dtype=float)
    dist = np.asarray(distance_km, dtype=float)
    fspl = 32.44 + 20 * np.log10(freq) + 20 * np.log10(dist)
    if fspl.shape == ():
        return float(fspl)
    return fspl

def calculate_haversine_distance_3d(pointA_geodetic, pointB_geodetic):
    """
    Compute 3D distance between geodetic coordinates (lat, lon, alt) in kilometers.

    Parameters
    ----------
    pointA_geodetic : np.ndarray
        (N, 3) array of [lat_deg, lon_deg, alt_m].
    pointB_geodetic : np.ndarray
        (N, 3) array of [lat_deg, lon_deg, alt_m].

    Returns
    -------
    np.ndarray
        (N,) array of 3D distances in kilometers.

    Notes
    -----
    - Computes great-circle surface distance via haversine, then adds vertical distance.
    """
    EARTH_RADIUS = 6_371_000.0  # meters
    lat1_rad = np.deg2rad(pointA_geodetic[:, 0])
    lon1_rad = np.deg2rad(pointA_geodetic[:, 1])
    lat2_rad = np.deg2rad(pointB_geodetic[:, 0])
    lon2_rad = np.deg2rad(pointB_geodetic[:, 1])
    alt1_m = pointA_geodetic[:, 2]
    alt2_m = pointB_geodetic[:, 2]

    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    a = (np.sin(dlat / 2) ** 2 +
         np.cos(lat1_rad) * np.cos(lat2_rad) * np.sin(dlon / 2) ** 2)
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
    surface_distance_m = EARTH_RADIUS * c

    dz = alt2_m - alt1_m
    total_distance_m = np.sqrt(surface_distance_m ** 2 + dz ** 2)

    return total_distance_m / 1000.0

def approximate_lat_lon_diff_meters(
        lat1_deg, lon1_deg, lat2_deg, lon2_deg
):
    """
    Approximate east (dx) and north (dy) displacements in meters between lat/lon pairs.

    Parameters
    ----------
    lat1_deg, lon1_deg, lat2_deg, lon2_deg : float or ndarray
        Coordinates in degrees.

    Returns
    -------
    tuple
        dx, dy: Displacements in meters (east, north).

    Notes
    -----
    Uses equirectangular approximation (accurate for small distances):
        dx = R * (lon2 - lon1) * cos(mean_lat)
        dy = R * (lat2 - lat1)
    """
    R_EARTH = 6378137.0
    lat1_rad = np.deg2rad(lat1_deg)
    lat2_rad = np.deg2rad(lat2_deg)
    lon1_rad = np.deg2rad(lon1_deg)
    lon2_rad = np.deg2rad(lon2_deg)
    delta_lat = lat2_rad - lat1_rad
    delta_lon = lon2_rad - lon1_rad
    mean_lat = (lat1_rad + lat2_rad) * 0.5

    dy = R_EARTH * delta_lat
    dx = R_EARTH * delta_lon * np.cos(mean_lat)
    return dx, dy

def compute_az_el_error(
        observer_geodetic,
        observer_pitch_deg,
        observer_yaw_deg,
        target_geodetic
):
    """
    Compute pointing (azimuth/elevation) errors between observer orientation and target direction.

    Parameters
    ----------
    observer_geodetic : np.ndarray
        (N, 3) array: [lat, lon, alt] for observer.
    observer_pitch_deg : float or ndarray
        Observer pitch angles (deg).
    observer_yaw_deg : float or ndarray
        Observer yaw (bearing) angles (deg).
    target_geodetic : np.ndarray
        (N, 3) array: [lat, lon, alt] for target.

    Returns
    -------
    np.ndarray
        (N, 2) array: [azimuth_error_deg, elevation_error_deg].

    Notes
    -----
    - Azimuth error is weighted by squared cosine of elevation.
    """
    dx, dy = approximate_lat_lon_diff_meters(
        observer_geodetic[:, 0], observer_geodetic[:, 1],
        target_geodetic[:, 0], target_geodetic[:, 1]
    )
    dz = target_geodetic[:, 2] - observer_geodetic[:, 2]
    bearing_to_target = (np.degrees(np.arctan2(dx, dy)) + 360) % 360
    normalized_yaw = np.mod(observer_yaw_deg, 360)
    azimuth_error = ((bearing_to_target - normalized_yaw + 180) % 360) - 180

    horiz_distance = np.hypot(dx, dy)
    elevation_to_target = np.degrees(np.arctan2(dz, horiz_distance))
    elevation_error = elevation_to_target - observer_pitch_deg

    weight = np.cos(np.radians(elevation_to_target)) ** 2
    azimuth_error = azimuth_error * weight

    return np.column_stack((azimuth_error, elevation_error))

def compute_relative_orientation_matrix(
        plane_states, sensor_config
):
    """
    Combine plane orientation and sensor mounting to get absolute sensor pointing.

    Parameters
    ----------
    plane_states : np.ndarray
        (N, 5) array with plane attitude [pitch, bearing] in last two columns.
    sensor_config : dict
        Must contain "bearing" and "pitch" offsets in degrees.

    Returns
    -------
    np.ndarray
        (N, 2) array: [absolute_bearing_deg, absolute_pitch_deg].

    Notes
    -----
    Handles gimbal wrap-around for pitch > 180° or < 0°.
    """
    absolute_bearing = np.mod(plane_states[:, 4] + sensor_config["bearing"], 360)
    absolute_pitch = plane_states[:, 3] + 90 + sensor_config["pitch"]
    pitch_out_of_bounds = (absolute_pitch >= 180) | (absolute_pitch < 0)
    absolute_pitch[pitch_out_of_bounds] = (180 - np.mod(absolute_pitch[pitch_out_of_bounds], 180))
    absolute_pitch = absolute_pitch - 90
    absolute_bearing[pitch_out_of_bounds] = (absolute_bearing[pitch_out_of_bounds] + 180) % 360
    return np.column_stack((absolute_bearing, absolute_pitch))

def compute_best_sensor_off_axis(
        transmitter_plane_states,
        receiver_plane_states,
        sensor_config_list
):
    """
    For all sensors, compute off-axis loss; select best for each time step.

    Parameters
    ----------
    transmitter_plane_states : np.ndarray
        (N, 5) transmitter state history.
    receiver_plane_states : np.ndarray
        (N, 5) receiver state history.
    sensor_config_list : list of dict
        Sensor configurations with beamwidths, loss, efficiency.

    Returns
    -------
    tuple:
        - np.ndarray: Off-axis loss (best per timestep, dB)
        - np.ndarray: HPBW of best sensor per timestep
        - np.ndarray: Efficiency of best sensor per timestep

    Notes
    -----
    For each time, chooses the sensor with minimal total (az + el) error,
    and computes corresponding off-axis loss using beamwidth, reference loss, etc.
    """
    all_sensor_orientations = [
        compute_relative_orientation_matrix(receiver_plane_states, sensor)
        for sensor in sensor_config_list
    ]
    all_errors = [
        compute_az_el_error(
            receiver_plane_states[:, :3],
            orientation[:, 1], orientation[:, 0],
            transmitter_plane_states[:, :3]
        )
        for orientation in all_sensor_orientations
    ]
    error_stack = np.abs(np.stack(all_errors, axis=0))  # shape (num_sensors, N, 2)
    total_error_scores = error_stack.sum(axis=2)  # sum az+el per sensor
    best_sensor_indices = np.argmin(total_error_scores, axis=0)
    time_indices = np.arange(error_stack.shape[1])
    best_errors = error_stack[best_sensor_indices, time_indices, :]

    HPBW_stack = np.stack([s["Half-Power_Beamwidth"] for s in sensor_config_list], axis=0)
    hpbw_best = HPBW_stack[best_sensor_indices]

    ref_loss_db_stack = np.stack([s["ref_loss_db"] for s in sensor_config_list], axis=0)
    ref_loss_db_best = ref_loss_db_stack[best_sensor_indices]

    ref_frac_stack = np.stack([s["ref_frac"] for s in sensor_config_list], axis=0)
    ref_frac_best = ref_frac_stack[best_sensor_indices]

    efficiency_stack = np.stack([s["efficiency"] for s in sensor_config_list], axis=0)
    efficiency_best = efficiency_stack[best_sensor_indices]

    off_axis_loss_best = calculate_off_axis_loss_elliptical(
        hpbw_best, best_errors, ref_loss_db_best, ref_frac_best
    )
    return off_axis_loss_best, hpbw_best, efficiency_best

def compute_line_of_sight(
        transmitter_state,
        receiver_state,
        transmitter_sensor_config,
        receiver_sensor_configs,
        heatmaps: SpatialHeatmap
) -> pd.DataFrame:
    """
    Compute full line-of-sight signal model between two objects (planes/satellites).

    Parameters
    ----------
    transmitter_state : np.ndarray
        (N, 5) array for transmitting plane/satellite [lat, lon, alt, pitch, bearing].
    receiver_state : np.ndarray
        (N, 5) array for receiving plane/satellite.
    transmitter_sensor_config : dict
        Sensor configuration for transmitter.
    receiver_sensor_configs : list of dict
        All sensor configs for receiver.
    cloud_heatmaps : tuple
        (IVDL_heatmap, SAT_heatmap) objects for cloud attenuation.

    Returns
    -------
    pd.DataFrame
        Time series DataFrame of path loss, antenna loss, cloud loss, power, SNR, and capacity.

    Notes
    -----
    The radio link budget includes FSPL, antenna gain, off-axis and cloud loss, SNR, capacity.
    """
    abs_sensor_orientation = compute_relative_orientation_matrix(transmitter_state, transmitter_sensor_config)
    target_off_axis_loss, target_hpbw, target_efficiency = compute_best_sensor_off_axis(
        transmitter_state, receiver_state, receiver_sensor_configs)
    tx_to_rx_off_axis_error = compute_az_el_error(
        transmitter_state[:, :3], abs_sensor_orientation[:, 1], abs_sensor_orientation[:, 0], receiver_state[:, :3])
    great_circle_distance_km = calculate_haversine_distance_3d(
        transmitter_state[:, :3], receiver_state[:, :3])
    transmitter_xyz = geo_to_xyz(transmitter_state[:, :3])
    receiver_xyz = geo_to_xyz(receiver_state[:, :3])
    fspl_db = calculate_fspl(transmitter_sensor_config["frequency_MHz"], great_circle_distance_km)
    receiver_gain_dBi = calculate_antenna_gain(target_hpbw, target_efficiency)

    if transmitter_sensor_config["directional"]:
        off_axis_loss = calculate_off_axis_loss_elliptical(
            transmitter_sensor_config["Half-Power_Beamwidth"],
            tx_to_rx_off_axis_error,
            transmitter_sensor_config["ref_loss_db"],
            transmitter_sensor_config["ref_frac"]
        )
        transmitter_gain_dBi = calculate_antenna_gain(
            transmitter_sensor_config["Half-Power_Beamwidth"], transmitter_sensor_config["efficiency"])
    else:
        off_axis_loss = 0
        transmitter_gain_dBi = 0

    cloud_loss = calculate_cloud_loss(
        transmitter_xyz, receiver_xyz, abs_sensor_orientation, great_circle_distance_km, heatmaps)
    transmitter_power_dBm = watts_to_dBm(transmitter_sensor_config["power"])
    received_power_dBm = (transmitter_power_dBm + transmitter_gain_dBi +
                          receiver_gain_dBi - off_axis_loss - fspl_db -
                          target_off_axis_loss - cloud_loss)
    noise_floor_dBm = -174 + 10 * math.log10(transmitter_sensor_config["shannon_bande_Hz"])
    snr_dB = received_power_dBm - noise_floor_dBm
    lag = great_circle_distance_km / 299_792
    channel_capacity_Mbps = calculate_capacity_from_snr_db(
        transmitter_sensor_config["shannon_bande_Hz"], snr_dB)

    return pd.DataFrame({
        "Free-Space Path Loss(Db)": fspl_db,
        "off_axis_loss(Db)": off_axis_loss,
        "target_off_axis_loss": target_off_axis_loss,
        "cloud_loss": cloud_loss,
        "Gt": transmitter_gain_dBi,
        "Gr": receiver_gain_dBi,
        "Pt": transmitter_power_dBm,
        "Pr": received_power_dBm,
        "SNR": snr_dB,
        "Shannon_capacity_Mbps": channel_capacity_Mbps,
        "distance": great_circle_distance_km,
        "lag_ms": lag * 1000
    })


class Plane:

    def __init__(
        self,
        config_path,
        flights_folder,
        satellites_folder,
        services_file,
        ivdl_heatmap_path,
        sat_heatmap_path,
        mean_service_duration=20,
        overlap_service_percent=20,
        cloud_attenuation=1,
        verbose=False,
    ):
        """
        Initialize a Plane simulation object, loading configuration, flights, satellites, services, and cloud heatmaps.

        Parameters:
            cfg_path (str or Path): Path to plane sensor configuration JSON.
            plane_folder (str or Path): Folder containing plane flight CSV data.
            sat_folder (str or Path): Folder containing satellite CSV data.
            service_file (str or Path): JSON file with service definitions.
            IVDL_clouds_heatmap_path (str or Path): File path for IVDL heatmap cache.
            SAT_clouds_heatmap_path (str or Path): File path for satellite heatmap cache.
            mean_live_service_time (int): Mean duration of live service in time steps (default 20).
            overlap_live_service (int): Percent overlap for live service timing variability (default 20).
            cloud_attenuation (float): Attenuation factor for clouds.

        Attributes:
            self.flights (pd.DataFrame): Combined flights and satellites data.
            self.services (list): Loaded service definitions.
            self.sensor_conf (dict): Sensor configuration data.
            self.IVDL_heatmap, self.Sat_heatmap (SpatialHeatmap): Cloud density heatmaps.

        Description:
            Loads all necessary data and sets up heatmaps for attenuation calculations.
        """
        self.cloud_attenuation = cloud_attenuation

        # Load IVDL and Satellite heatmaps
        self.ivdl_heatmap = SpatialHeatmap.from_file_or_generate(
            save_uri=ivdl_heatmap_path,
            force_init=False,
            x_min=-1_000_000, x_max=1_000_000,
            z_min=-1_000_000, z_max=1_000_000,
            step=200,
            cloud_amplitude=0.8,
            tile_size_x=50,
            tile_size_z=50,
            density_noise_scale=0.000005,
            cloud_noise_scale=0.000007,
            center=(264_768.0, 5_278_273.0),
            presence_octaves=4,
            presence_persistence=0.5,
            presence_lacunarity=2.0,
            density_octaves=2,
            density_persistence=0.5,
            density_lacunarity=2.0,
        )
        self.sat_heatmap = SpatialHeatmap.from_file_or_generate(
            save_uri=sat_heatmap_path,
            force_init=False,
            x_min=-1_000_000, x_max=1_000_000,
            z_min=-1_000_000, z_max=1_000_000,
            step=200,
            cloud_amplitude=0.8,
            tile_size_x=50,
            tile_size_z=50,
            density_noise_scale=0.000005,
            cloud_noise_scale=0.000007,
            center=(264_768.0, 5_278_273.0),
            presence_octaves=4,
            presence_persistence=0.5,
            presence_lacunarity=2.0,
            density_octaves=2,
            density_persistence=0.5,
            density_lacunarity=2.0,
        )
        self.overlap_service_percent = overlap_service_percent
        self.mean_service_duration = mean_service_duration

        # Load services and sensor config
        with open(services_file, 'r', encoding='utf-8') as f:
            self.services_list = json.load(f)
        with open(Path(config_path).expanduser(), 'r') as file:
            self.sensors_config = json.load(file)

        # Load flights and satellites data
        self.flight_data, self.label_by_plane_id, self.sat_min_length, \
            self.plane_names, self.plane_ids = combine_csvs_from_folder(
            Path(flights_folder).expanduser(),
            Path(satellites_folder).expanduser(),
            "time_s"
        )
        self._sensor_key_for_plane: dict[int, str] = {}
        for pid in pd.unique(self.flight_data['plane_id']):
            plane_rows = self.flight_data[self.flight_data['plane_id'] == pid]
            raw_type = plane_rows['plane_type'].iloc[0] if not plane_rows.empty else ""
            sensor_key = self._resolve_sensor_key(raw_type)
            self._sensor_key_for_plane[pid] = sensor_key
            normalized_type = self._shorten_sensor_key(sensor_key)
            self.flight_data.loc[self.flight_data['plane_id'] == pid, 'plane_type'] = normalized_type
        self.flight_data_i_plane_id = self.flight_data.set_index("plane_id", drop=False, inplace=False)

    def _resolve_sensor_key(self, plane_type_raw: str) -> str:
        plane_lower = str(plane_type_raw or "").lower().strip()
        if not plane_lower:
            plane_lower = "plane"

        direct_matches = [
            key for key in self.sensors_config
            if plane_lower == key.lower()
        ]
        if direct_matches:
            return direct_matches[0]

        fuzzy_matches = [
            key for key in self.sensors_config
            if plane_lower in key.lower() or key.lower() in plane_lower
        ]
        if not fuzzy_matches:
            hint = "sat" if "sat" in plane_lower else "plane"
            fuzzy_matches = [
                key for key in self.sensors_config
                if hint in key.lower()
            ]
        if not fuzzy_matches:
            fuzzy_matches = list(self.sensors_config.keys())

        return min(fuzzy_matches, key=len)

    @staticmethod
    def _shorten_sensor_key(sensor_key: str) -> str:
        tokens = [token for token in re.split(r"[\W_]+", str(sensor_key)) if token]
        if not tokens:
            return str(sensor_key)
        return min(tokens, key=len)

    def calculate_line_of_sight_matrix(self, plane_id):
        """
        Compute line-of-sight signal data matrix for a specific plane communicating with others.

        Parameters:
            plane_id (int): Index or ID of the plane to compute the matrix for.

        Returns:
            pd.Series: Time-indexed series where each element is a dict of signal characteristics
                       for all other planes and associated services.

        Description:
            Computes signal loss and power characteristics for all pairs involving the given plane,
            including cloud losses, antenna gains, and service scheduling.
        """
        # Get a DataFrame row for plane_id
        first_row = self.flight_data.loc[0]
        source_entry = first_row[first_row['plane_id'] == plane_id]["source_file"].iloc[0]
        source_path = Path(source_entry)
        df_current_plane = _load_dataframe(source_path)
        if 'worker_id' in df_current_plane.columns:
            df_current_plane = df_current_plane.drop(columns=['worker_id'])
        type_entry = first_row[first_row['plane_id'] == plane_id]["plane_type"].iloc[0]
        is_plane = "plane" in str(type_entry).lower()
        trajectory_length = df_current_plane.shape[0] if is_plane else self.sat_min_length

        # Gather trajectories for all planes
        trajectories = []

        for pid in pd.unique(self.flight_data.loc[0, 'plane_id']):
            plane_rows = self.flight_data_i_plane_id.loc[pid]
            required_cols = ['latitude', 'longitude', 'alt_m', 'pitch_deg', 'bearing_deg']
            missing_cols = [col for col in required_cols if col not in plane_rows.columns]
            if missing_cols:
                raise ValueError(f"Missing columns {missing_cols} for plane ID {pid}. "
                                 f"Available: {plane_rows.columns.tolist()}")
            trajectories.append(plane_rows[required_cols].iloc[:trajectory_length].to_numpy())

        def compute_target_signal(plane_id, target_plane_id, sensor_params):
            if target_plane_id != plane_id:
                target_key = self._sensor_key_for_plane.get(target_plane_id)
                if target_key is None:
                    target_key = next(iter(self.sensors_config.keys()))
                return compute_line_of_sight(
                    trajectories[plane_id],
                    trajectories[target_plane_id],
                    sensor_params,
                    self.sensors_config[target_key],
                    (self.ivdl_heatmap, self.sat_heatmap)
                )
            else:
                return pd.DataFrame(None)

        def process_sensor(sensor_idx, sensor_params, plane_id):
            # Inner thread pool for targets
            with ThreadPoolExecutor() as target_executor:
                futures = {
                    target_executor.submit(compute_target_signal, plane_id, target_id, sensor_params): target_id
                    for target_id in pd.unique(self.flight_data.loc[0, 'plane_id'])
                }

                signal_data_per_target = []
                signal_colnames_per_target = []

                for future in as_completed(futures):
                    target_id = futures[future]
                    try:
                        df = future.result()
                    except Exception as e:
                        print(f"Error processing target {target_id}: {e}")
                        df = pd.DataFrame(None)

                    signal_data_per_target.append(df)
                    signal_colnames_per_target.append(f"{self.label_by_plane_id[target_id]}_signal")

            # Process and merge dataframes as in your original code
            processed_dfs = [df.apply(lambda row: row.to_dict(), axis=1) for df in signal_data_per_target]
            merged_df = pd.concat(processed_dfs, axis=1)
            merged_df.columns = signal_colnames_per_target
            merged_df = merged_df.apply(lambda row: row.to_dict(), axis=1)

            return merged_df, f"antenna_{sensor_idx}"

        sensor_results_by_plane = []
        sensor_column_names = []

        sensor_key = self._sensor_key_for_plane.get(plane_id)
        if sensor_key is None:
            sensor_defs = next(iter(self.sensors_config.values()))
        else:
            sensor_defs = self.sensors_config.get(sensor_key, next(iter(self.sensors_config.values())))

        with ThreadPoolExecutor() as sensor_executor:
            futures = {
                sensor_executor.submit(process_sensor, idx, params, plane_id): idx
                for idx, params in enumerate(sensor_defs)
            }

            for future in as_completed(futures):
                try:
                    merged_df, col_name = future.result()
                    sensor_results_by_plane.append(merged_df)
                    sensor_column_names.append(col_name)
                except Exception as e:
                    print(f"Error processing sensor {futures[future]}: {e}")

        # Service schedule generation
        origin_plane_name = None
        available_plane_ids = self.plane_ids.copy()
        available_plane_names = self.plane_names.copy()
        for i, pid in enumerate(self.plane_ids):
            if pid == plane_id:
                available_plane_ids.pop(i)
                origin_plane_name = available_plane_names.pop(i)
                break
        # Compute time slotting for services
        full_traj_length = self.flight_data.set_index("plane_id", inplace=False, drop=False).loc[plane_id].shape[0]
        estimated_segments = int(full_traj_length / 60 / self.mean_service_duration)
        random_jitter = random.randint(
            -int((full_traj_length / 60 / 20) * 20 / 100),
            int((full_traj_length / 60 / 20) * self.overlap_service_percent / 100)
        )
        num_segments = estimated_segments + random_jitter
        segment_boundaries = []
        # FIX NEED TO SECURE FIRST AND LAST BEING [0,full_traj_length]
        for seg_idx in range(num_segments - 1):
            segment_boundaries.append(int(full_traj_length / num_segments) * (seg_idx + 1))
        for seg_idx in range(num_segments - 1):
            segment_boundaries[seg_idx] += random.randint(
                -int(full_traj_length * (1 / (num_segments * 2))),
                int(full_traj_length * (1 / (num_segments * 2)))
            )

        # Assign services per time slot
        # For each trajectory segment we assemble a synthetic "service" list by cloning
        # the templates loaded from services_conf. The emitting plane becomes the
        # origin and we splice in a random peer as destination so downstream users
        # can interpret rows as directional traffic hints.
        services_for_all_segments = []
        if origin_plane_name is not None:
            logger = logging.getLogger(__name__)
            for segment_idx in range(len(segment_boundaries) + 1):
                service_for_segment = []
                segment_len = random.randint(0, 3)
                logger.debug(
                    "Plane %s generating %d service(s) for segment %d",
                    origin_plane_name,
                    segment_len,
                    segment_idx,
                )
                for _ in range(segment_len):
                    chosen_service = random.choice(self.services_list).copy()
                    chosen_service["origin"] = origin_plane_name
                    dest = random.choice(available_plane_names) if available_plane_names else None
                    chosen_service["destination"] = dest
                    logger.debug(
                        "  service template=%s origin=%s destination=%s",
                        chosen_service.get("service_id") or chosen_service.get("name") or "unknown",
                        origin_plane_name,
                        dest,
                    )
                    service_for_segment.append(chosen_service)
                services_for_all_segments.append(service_for_segment)

        # Build intervals and flatten service schedule into a time-indexed Series
        start_indices = [0] + segment_boundaries
        end_indices = segment_boundaries + [full_traj_length]
        time_slot_service_list = []
        for start, end, service in zip(start_indices, end_indices, services_for_all_segments):
            time_slot_service_list.extend([service] * (end - start))
        services_series = pd.Series(time_slot_service_list)

        sensor_results_by_plane.append(services_series)
        sensor_column_names.append("services")

        # Final DataFrame assembly
        df_all_sensors = pd.concat(sensor_results_by_plane, axis=1)
        df_all_sensors.columns = sensor_column_names
        df_all_sensors = df_all_sensors.apply(lambda row: row.to_dict(), axis=1)

        return df_all_sensors


class LinkSimWorker(PolarsWorker):
    """class derived from AgiDagWorker"""
    pool_vars = {}

    def start(self):
        global global_vars

        if not isinstance(self.args, _MutableNamespace):
            payload = self.args if isinstance(self.args, dict) else vars(self.args)
            self.args = _MutableNamespace(**payload)

        if getattr(self, "pool_vars", None) is None:
            self.pool_vars = {}

        source_root = getattr(self.args, "data_in", None)
        if source_root is None:
            raise ValueError("LinkSimWorker requires a 'data_in' argument")

        reset_target = getattr(self.args, "reset_target", False)
        data_paths = self.setup_data_directories(
            source_path=source_root,
            target_path=getattr(self.args, "data_out", None),
            target_subdir="dataframe",
            reset_target=reset_target,
        )
        normalized_data_in = data_paths.normalized_input
        self.data_in = Path(normalized_data_in)
        self.args.data_in = normalized_data_in
        self.args.data_out = data_paths.normalized_output
        self.data_out = data_paths.normalized_output
        self.data_flight = self.args.data_flight
        self.data_sat = self.args.data_sat
        self.output_format = self.args.output_format
        self.plane_conf = self.args.plane_conf
        self.cloud_heatmap_IVDL = self.args.cloud_heatmap_IVDL
        self.cloud_heatmap_sat = self.args.cloud_heatmap_sat
        self.services_conf = self.args.services_conf

        # Dataset (inputs) vs dataframe (outputs)
        self.dataset_root = self.data_in
        self.plane_conf_path = self.dataset_root / self.plane_conf
        self.services_conf_path = self.dataset_root / self.services_conf
        self.cloud_heatmap_ivdl_path = self.dataset_root / self.cloud_heatmap_IVDL
        self.cloud_heatmap_sat_path = self.dataset_root / self.cloud_heatmap_sat
        self.flights_folder = self.dataset_root / self.data_flight
        self.satellites_folder = self.dataset_root / self.data_sat

        if not self.plane_conf_path.exists():
            antenna_conf = self.dataset_root / "antenna_conf.json"
            if antenna_conf.exists():
                logging.info(
                    "plane_conf.json not found; using %s instead", antenna_conf.name
                )
                self.plane_conf_path = antenna_conf
                self.plane_conf = antenna_conf.name
                self.args.plane_conf = antenna_conf.name

        for required_path in [
            self.plane_conf_path,
            self.services_conf_path,
            self.flights_folder,
            self.satellites_folder,
        ]:
            if not required_path.exists():
                raise FileNotFoundError(
                    f"Required LinkSim asset missing: {required_path}. "
                    "Run AGI.install_link_sim or copy the dataset before executing."
                )

        logging.info(f"from: {__file__}")

        self.args["data_in"] = data_paths.normalized_input
        self.args["data_out"] = data_paths.normalized_output

        if self.verbose > 1:
            logging.info(f"Worker #{self._worker_id} dataframe root path = {self.data_out}")

        if self.verbose > 0:
            logging.info(f"start _worker_id {self._worker_id}\n")
        args = self.args

        self.pool_vars["args"] = self.args
        self.pool_vars["verbose"] = self.verbose
        global_vars = self.pool_vars

        # Ensure optional attributes exist on the worker (legacy workers expect them)
        defaults = {
            "mean_service_duration": 20,
            "overlap_service_percent": 20,
            "cloud_attenuation": 1.0,
        }
        for attr, fallback in defaults.items():
            value = getattr(self.args, attr, None)
            if value is None and hasattr(self, attr):
                value = getattr(self, attr)
            if value is None:
                value = fallback
            setattr(self, attr, value)
            self.args[attr] = value

    def work_init(self):
        """Initialize work by reading from shared space."""
        global global_vars
        pass

    def pool_init(self, worker_vars):
        """Initialize the pool with worker variables.

        Args:
            worker_vars (dict): Variables specific to the worker.

        """
        global global_vars
        global_vars = worker_vars

    def work_pool(self, file):
        global global_vars
        try:
            plane_id = int(file)
        except (TypeError, ValueError):
            raise TypeError(f"Unexpected work item {file!r}; expected plane identifier")

        self.currfile = plane_id

        try:
            data_out = Path(self.data_out)
            flight_sight = Plane(
                self.plane_conf_path,
                self.flights_folder,
                self.satellites_folder,
                self.services_conf_path,
                self.cloud_heatmap_ivdl_path,
                self.cloud_heatmap_sat_path,
                mean_service_duration=self.mean_service_duration,
                overlap_service_percent=self.overlap_service_percent,
                cloud_attenuation=self.cloud_attenuation,
                verbose=self.verbose,
            )
            df = flight_sight.calculate_line_of_sight_matrix(plane_id)
            self.json_label = flight_sight.label_by_plane_id
            df = pl.from_pandas(df).to_frame()
            return df
        except ValueError as e:
            print(f'Initialization failed: {e}')

    def work_done(self, worker_df):
        """Concatenate dataframe if any and save the results.
        Args:
            worker_df (pl.DataFrame): Output dataframe for one plane.
        """
        if worker_df.is_empty():
            return

        plane_id = self.currfile
        data_out = Path(self.args['data_out']).expanduser()

        try:
            os.makedirs(data_out, exist_ok=True)

            df_pd = worker_df.to_pandas()
            if (
                df_pd.shape[1] == 1
                and df_pd.iloc[:, 0].map(lambda v: isinstance(v, dict)).all()
            ):
                flat_df = pd.DataFrame(df_pd.iloc[:, 0].tolist())
            else:
                flat_df = df_pd

            base_name = self.json_label[plane_id]
            output_format = getattr(self.args, 'output_format', 'json') or 'json'
            output_format = output_format.lower()
            if output_format == 'json':
                filename = data_out / f"{base_name}_vision.json"
                flat_df.to_json(str(filename), orient='records', indent=2)
            elif output_format == 'parquet':
                filename = data_out / f"{base_name}_vision.parquet"
                flat_df.to_parquet(str(filename), engine='pyarrow', index=False)
            elif output_format == 'csv':
                filename = data_out / f"{base_name}_vision.csv"
                flat_df.to_csv(str(filename), index=False)
            else:
                raise ValueError(f"Unsupported output_format: {output_format}")
        except Exception as e:
            print(traceback.format_exc())
            print(f'Error saving dataframe for plane {plane_id} : {e}')

    def stop(self):
        try:
            """Finalize the worker by listing saved dataframes."""
            files = glob.glob(os.path.join(Path(self.args['data_out']).
                expanduser(), '**'), recursive=True)
            df_files = [f for f in files if re.search('\\.(csv|parquet)$', f)]
            n_df = len(df_files)
            if self.verbose > 0:
                print(f'LinkSimWorker.worker_end - {n_df} dataframes:')
                for f in df_files:
                    print(Path(f))
                if not n_df:
                    print('No dataframe created')
        except Exception as err:
            print(f'Error while trying to find dataframes: {err}')
        super().stop()
