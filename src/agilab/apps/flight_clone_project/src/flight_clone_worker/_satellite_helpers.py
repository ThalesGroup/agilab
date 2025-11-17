"""Local copy of the sat_trajectory_worker helpers used as a fallback.

The preferred code path imports from ``sat_trajectory_worker`` directly so we
stay in sync with the upstream project. When that package is not available
inside a packaged worker (for instance when only flight_clone_worker is
installed), these helpers keep the satellite overlay features functional.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, Tuple

import numpy as np
import pandas as pd
from sgp4.api import Satrec, WGS72, jday


DEFAULT_EPOCH = datetime(2025, 6, 27, 0, 0, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class TLEEntry:
    """Container holding the raw TLE payload for a satellite."""

    name: str
    line1: str
    line2: str


def load_tle_catalog(source: str | Path) -> Dict[str, TLEEntry]:
    """
    Parse a NORAD 3-line element file and return a mapping keyed by sat name.

    The parser tolerates duplicate entries and keeps the most recent block for
    each spacecraft so downstream consumers always see the latest orbit.
    """

    catalog: Dict[str, TLEEntry] = {}
    path = Path(source).expanduser()
    if not path.exists():
        return catalog

    with path.open(encoding="utf-8", errors="ignore") as handle:
        lines = [line.strip() for line in handle if line.strip()]

    idx = 0
    total = len(lines)
    while idx + 2 < total:
        header = lines[idx]
        if not header.startswith("0 "):
            idx += 1
            continue
        name = header[2:].strip() or header
        line1 = lines[idx + 1]
        line2 = lines[idx + 2]
        if not (line1.startswith("1 ") and line2.startswith("2 ")):
            idx += 1
            continue
        catalog[name] = TLEEntry(name=name, line1=line1, line2=line2)
        idx += 3

    return catalog


def _semimajor_axis_km(satrec: Satrec) -> float | None:
    """Derive the semi-major axis when datasets do not provide it."""

    mu = 398600.4418  # km^3 / s^2
    try:
        mean_motion_rad_min = satrec.no_kozai
        mean_motion_rad_s = mean_motion_rad_min / 60.0
        return (mu / (mean_motion_rad_s**2)) ** (1.0 / 3.0)
    except Exception:
        return None


def compute_trajectory(
    entry: TLEEntry | Tuple[str, str, str] | Iterable[str],
    *,
    duration_s: int,
    step_s: int = 60,
    epoch: datetime | None = None,
) -> pd.DataFrame:
    """Propagate a TLE and return a dataframe with per-timestep geodetic samples."""

    if isinstance(entry, TLEEntry):
        name, line1, line2 = entry.name, entry.line1, entry.line2
    else:  # fallback tuple/list
        name, line1, line2 = list(entry)

    sat = Satrec.twoline2rv(line1, line2, WGS72)
    sma_km = _semimajor_axis_km(sat) or 0.0
    mu = 398600.4418
    speed_ms = float(np.sqrt(mu / sma_km) * 1000) if sma_km else np.nan
    epoch = epoch or DEFAULT_EPOCH

    samples: list[dict[str, float | str]] = []
    for offset in range(0, max(1, duration_s) + 1, max(1, step_s)):
        instant = epoch + timedelta(seconds=offset)
        jd, fr = jday(
            instant.year,
            instant.month,
            instant.day,
            instant.hour,
            instant.minute,
            instant.second + instant.microsecond / 1e6,
        )
        error, position_km, _velocity = sat.sgp4(jd, fr)
        if error != 0:
            samples.append(
                {
                    "time_s": offset,
                    "sat_track_lat": np.nan,
                    "sat_track_long": np.nan,
                    "sat_track_alt_m": np.nan,
                    "sat": name,
                    "sat_speed_ms": speed_ms,
                }
            )
            continue
        x, y, z = position_km
        hyp = float(np.hypot(x, y))
        lat = np.degrees(np.arctan2(z, hyp))
        lon = np.degrees(np.arctan2(y, x))
        alt_m = float(np.sqrt(x**2 + y**2 + z**2) * 1000.0)
        samples.append(
            {
                "time_s": offset,
                "sat_track_lat": lat,
                "sat_track_long": lon,
                "sat_track_alt_m": alt_m,
                "sat": name,
                "sat_speed_ms": speed_ms,
            }
        )

    return pd.DataFrame(samples)


__all__ = ["TLEEntry", "load_tle_catalog", "compute_trajectory", "DEFAULT_EPOCH"]
