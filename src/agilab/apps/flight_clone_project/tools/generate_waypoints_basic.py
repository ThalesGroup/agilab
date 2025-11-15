"""
Utility script to regenerate the demo flight waypoints archive.

It produces a ``dataset/waypoints.geojson`` containing 20 routes that span the
main Ukrainian air bridge (Kyiv ↔ Dnipro/Lviv/Odesa), then repacks it into
``dataset.7z`` so the worker assets stay lightweight.
"""
from __future__ import annotations
import argparse
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import shutil
import py7zr
FLIGHT_ID_PREFIX = 'UKBB-UKDD'
PLANE_TYPE = 'ukraine_corridor'
ORIGIN = 'UKBB'  # Kyiv Zhulyany
DESTINATION = 'UKDD'  # Dnipro
COMMON_PREFIX = [(30.8947, 50.345), (31.25, 50.05)]
COMMON_SUFFIX = [(34.2, 48.9), (35.1006, 48.3572)]
VARIANT_MIDPOINTS: list[list[tuple[float, float]]] = [
    [(31.7, 49.8), (33.6, 49.1)],
    [(31.5, 49.6), (33.9, 48.9)],
    [(31.2, 49.4), (33.5, 48.7)],
    [(32.0, 49.5), (33.8, 48.6)],
    [(32.3, 49.3), (33.9, 48.5)],
    [(32.5, 49.2), (34.1, 48.4)],
    [(32.8, 49.1), (34.3, 48.3)],
    [(31.9, 49.0), (34.5, 48.2)],
    [(31.1, 49.2), (34.7, 48.4)],
    [(30.9, 49.4), (34.4, 48.6)],
    [(31.4, 49.8), (33.3, 49.1)],
    [(31.6, 50.0), (33.2, 49.3)],
    [(32.4, 49.8), (33.0, 49.0)],
    [(32.7, 49.6), (33.2, 48.8)],
    [(33.1, 49.4), (33.6, 48.6)],
    [(33.4, 49.2), (33.8, 48.4)],
    [(33.7, 49.0), (34.0, 48.3)],
    [(31.8, 48.8), (34.2, 48.1)],
    [(31.2, 48.9), (34.4, 48.0)],
    [(30.8, 49.1), (34.6, 48.2)],
]


def build_feature(index: int, midpoints: list[tuple[float, float]]) ->dict[
    str, object]:
    coords = COMMON_PREFIX + midpoints + COMMON_SUFFIX
    return {'type': 'Feature', 'properties': {'flight_id':
        f'{FLIGHT_ID_PREFIX}-{index:02d}', 'plane_type': PLANE_TYPE,
        'origin': ORIGIN, 'destination': DESTINATION, 'track_variant':
        index}, 'geometry': {'type': 'LineString', 'coordinates': [[lon,
        lat] for lon, lat in coords]}}


def build_geojson() ->dict[str, object]:
    return {'type': 'FeatureCollection', 'name':
        'flight_clone_missions', 'created': datetime.now(tz=timezone.
        utc).isoformat(), 'features': [build_feature(idx + 1, midpoints) for
        idx, midpoints in enumerate(VARIANT_MIDPOINTS)]}


def write_archive(output: Path, geojson: dict[str, object]) ->None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        dataset_dir = tmp_path / 'dataset'
        dataset_dir.mkdir()
        geojson_path = dataset_dir / 'waypoints.geojson'
        geojson_path.write_text(json.dumps(geojson, indent=2), encoding='utf-8'
            )
        assets_dir = Path(__file__).resolve().parents[1] / 'dataset_assets'
        if assets_dir.exists():
            for asset in assets_dir.iterdir():
                shutil.copy2(asset, dataset_dir / asset.name)
        with py7zr.SevenZipFile(output, mode='w') as archive:
            archive.write(geojson_path, arcname='dataset/waypoints.geojson')
            if assets_dir.exists():
                for asset in assets_dir.iterdir():
                    archive.write(dataset_dir / asset.name, arcname=f'dataset/{asset.name}')


def main() ->None:
    tools_dir = Path(__file__).resolve().parent
    project_root = tools_dir.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=project_root / 'src' /
        'flight_clone_worker' / 'dataset.7z', help=
        'Target archive location (defaults to the packaged dataset under src/).'
        )
    args = parser.parse_args()
    geojson = build_geojson()
    write_archive(args.output, geojson)
    print(
        f'Wrote {len(VARIANT_MIDPOINTS)} trajectory variants to {args.output}')


if __name__ == '__main__':
    main()
