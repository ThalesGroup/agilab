"""
Generic trajectory generator from GeoJSON waypoints.

- Input: one or more GeoJSON FeatureCollections of Point waypoints.
- Output: GeoJSON FeatureCollection containing:
    * One LineString feature per input file (the full path of each route).
    * Optionally, sampled Point features with timestamps, speed, heading, altitude.

Assumptions (kept deliberately simple & generic):
- Constant ground speed per route.
- Linear interpolation in latitude/longitude per segment (sufficient for short/mid distances).
- Altitude linearly interpolated between waypoints if provided (else a default).

This tool is intended for benign uses such as simulation, visualization, game development,
and testing. It is **not** for operational/military planning.
"""
from __future__ import annotations
import argparse
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Tuple, Dict, Any


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) ->float:
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(
        dlambda / 2.0) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) ->float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2
        ) * math.cos(dl)
    brng = math.degrees(math.atan2(x, y))
    return (brng + 360) % 360


def lerp(a: float, b: float, t: float) ->float:
    return a + (b - a) * t


def interpolate_point(lat1: float, lon1: float, lat2: float, lon2: float,
    frac: float) ->Tuple[float, float]:
    return lerp(lat1, lat2, frac), lerp(lon1, lon2, frac)


def parse_waypoints_from_geojson(path: Path, default_alt: float) ->List[Tuple
    [float, float, float]]:
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('type') != 'FeatureCollection':
        raise ValueError(f'{path} is not a GeoJSON FeatureCollection')
    points: List[Tuple[float, float, float]] = []
    for feat in data.get('features', []):
        if feat.get('type') != 'Feature':
            continue
        geom = feat.get('geometry', {})
        if geom.get('type') != 'Point':
            continue
        coords = geom.get('coordinates', [])
        if not isinstance(coords, list) or len(coords) < 2:
            continue
        lon, lat = coords[:2]
        alt = coords[2] if len(coords) > 2 else feat.get('properties', {}).get(
            'alt', default_alt)
        points.append((lat, lon, float(alt)))
    if len(points) < 2:
        raise ValueError(f'{path} must contain at least two Point waypoints')
    return points


def generate_track(points: List[Tuple[float, float, float]], speed_m_s:
    float, sample_s: int, start_time: datetime) ->Tuple[List[List[float]],
    List[Dict[str, Any]]]:
    """
    Build a LineString coordinate list and sampled Point features.
    Returns (line_coords, point_features)
    """
    line_coords: List[List[float]] = []
    sampled_points: List[Dict[str, Any]] = []
    t = start_time
    for i in range(len(points) - 1):
        lat1, lon1, alt1 = points[i]
        lat2, lon2, alt2 = points[i + 1]
        seg_dist = haversine_m(lat1, lon1, lat2, lon2)
        if seg_dist <= 0:
            continue
        seg_time = seg_dist / speed_m_s
        n = max(1, int(math.ceil(seg_time / sample_s)))
        bearing = bearing_deg(lat1, lon1, lat2, lon2)
        for k in range(n):
            frac = k / n
            lat, lon = interpolate_point(lat1, lon1, lat2, lon2, frac)
            alt = lerp(alt1, alt2, frac)
            line_coords.append([lon, lat, alt])
            sampled_points.append({'type': 'Feature', 'geometry': {'type':
                'Point', 'coordinates': [lon, lat, alt]}, 'properties': {
                'timestamp': t.replace(tzinfo=timezone.utc).isoformat().
                replace('+00:00', 'Z'), 'speed_m_s': speed_m_s,
                'heading_deg': bearing, 'segment_index': i}})
            t = t + timedelta(seconds=sample_s)
        line_coords.append([lon2, lat2, alt2])
        sampled_points.append({'type': 'Feature', 'geometry': {'type':
            'Point', 'coordinates': [lon2, lat2, alt2]}, 'properties': {
            'timestamp': t.replace(tzinfo=timezone.utc).isoformat().replace
            ('+00:00', 'Z'), 'speed_m_s': speed_m_s, 'heading_deg': bearing,
            'segment_index': i}})
        t = t + timedelta(seconds=sample_s)
    return line_coords, sampled_points


def build_featurecollection(inputs: List[Path], speed_m_s: float, sample_s:
    int, start_time: str, default_alt: float, include_samples: bool) ->Dict[
    str, Any]:
    if start_time.lower() == 'now':
        start_dt = datetime.now(tz=timezone.utc)
    else:
        start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
    features: List[Dict[str, Any]] = []
    for src in inputs:
        pts = parse_waypoints_from_geojson(src, default_alt)
        line_coords, samples = generate_track(pts, speed_m_s, sample_s,
            start_dt)
        line = {'type': 'Feature', 'geometry': {'type': 'LineString',
            'coordinates': line_coords}, 'properties': {'source': src.name,
            'created': datetime.now(tz=timezone.utc).isoformat().replace(
            '+00:00', 'Z'), 'point_count': len(samples) if include_samples else
            len(line_coords), 'speed_m_s': speed_m_s, 'sample_interval_s':
            sample_s}}
        features.append(line)
        if include_samples:
            features.extend(samples)
    return {'type': 'FeatureCollection', 'features': features}


def main() ->None:
    parser = argparse.ArgumentParser(description=
        'Generate generic trajectories from GeoJSON waypoint files.')
    parser.add_argument('--input', '-i', type=Path, nargs='+', required=
        True, help=
        'One or more GeoJSON files of Point waypoints (FeatureCollection).')
    parser.add_argument('--output', '-o', type=Path, required=True, help=
        'Output GeoJSON FeatureCollection.')
    parser.add_argument('--speed-m-s', type=float, default=200.0, help=
        'Constant speed (m/s). Default: 200.')
    parser.add_argument('--sample-s', type=int, default=30, help=
        'Sampling interval in seconds. Default: 30.')
    parser.add_argument('--start', type=str, default='now', help=
        "Start time ISO-8601 or 'now'. Default: now")
    parser.add_argument('--default-alt', type=float, default=1000.0, help=
        'Default altitude (m) when missing. Default: 1000.')
    parser.add_argument('--include-samples', action='store_true', help=
        'Include sampled Point features with timestamps (otherwise only LineStrings).'
        )
    args = parser.parse_args()
    fc = build_featurecollection(args.input, args.speed_m_s, args.sample_s,
        args.start, args.default_alt, args.include_samples)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(fc, indent=2), encoding='utf-8')
    print(f"Wrote {len(fc['features'])} features to {args.output}")


if __name__ == '__main__':
    main()
