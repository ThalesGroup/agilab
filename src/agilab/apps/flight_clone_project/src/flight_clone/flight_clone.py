import subprocess
import sys
import traceback
import shutil
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
import json
import math
import copy
import re
import itertools
import pandas as pd
from agi_node.agi_dispatcher import BaseWorker, WorkDispatcher
from agi_env import normalize_path
warnings.filterwarnings('ignore')
import logging
from .flight_clone_args import FlightCloneArgs, FlightCloneArgsTD, dump_args, ensure_defaults, load_args, merge_args, resolve_data_in_for_env
logger = logging.getLogger(__name__)


class FlightClone(BaseWorker):
    args_loader = staticmethod(load_args)
    args_merger = staticmethod(merge_args)
    args_dumper = staticmethod(dump_args)
    args_ensure_defaults = staticmethod(ensure_defaults)
    managed_pc_path_fields = 'data_in', 'data_out'
    """FlightClone class provides methods to orchestrate the run."""
    ivq_logs = None

    def __init__(self, env, args: (FlightCloneArgs | None)=None, **raw_args:
        Any) ->None:
        super().__init__()
        self.env = env
        if args is None:
            if not raw_args:
                raise ValueError(
                    'FlightClone requires arguments via args model or keyword values'
                    )
            args = FlightCloneArgs(**raw_args)
        original_data_in = Path(args.data_in if args else raw_args.get(
            'data_in', ''))
        self.setup_args(args, env=env, error=
            'FlightClone requires an initialized FlightCloneArgs instance'
            , output_field='data_in', output_parents_up=1)
        initial_data_out = getattr(self, 'data_out', None)
        self.data_in = resolve_data_in_for_env(env, self.args.data_in)
        self.args.data_in = self.data_in
        WorkDispatcher.args = self.args.model_dump(mode='json')
        self.data_out = self._resolve_output_root(self.data_in)
        self.args.data_out = self.data_out
        if not original_data_in.is_absolute():
            repo_dataset = (Path.cwd() / original_data_in).resolve()
            repo_data_parent = repo_dataset.parent
            if repo_data_parent.exists(
                ) and repo_data_parent != self.data_in.parent and str(
                repo_data_parent).startswith(str(Path.cwd())):
                try:
                    shutil.rmtree(repo_data_parent, ignore_errors=True,
                        onerror=WorkDispatcher._onerror)
                except Exception:
                    logger.debug(
                        'Failed to remove repository data directory %s',
                        repo_data_parent, exc_info=True)
        if initial_data_out:
            candidate_out = Path(initial_data_out)
            if not candidate_out.is_absolute():
                repo_data_out = (Path.cwd() / candidate_out).resolve()
            else:
                repo_data_out = candidate_out
            if repo_data_out.exists(
                ) and repo_data_out != self.data_out and str(repo_data_out
                ).startswith(str(Path.cwd())):
                try:
                    shutil.rmtree(repo_data_out, ignore_errors=True,
                        onerror=WorkDispatcher._onerror)
                except Exception:
                    logger.debug(
                        'Failed to remove repository dataframe directory %s',
                        repo_data_out, exc_info=True)
        self.num_flights = max(1, int(self.args.num_flights))
        self.beam_file = self.args.beam_file
        self.sat_file = self.args.sat_file
        self.waypoints = self.args.waypoints
        payload = self.args.model_dump(mode='json')
        payload['data_out'] = str(self.data_out)
        WorkDispatcher.args = payload
        self._maybe_regenerate_waypoints()
        self._ensure_ukraine_localization()
        self._reset_output()

    @classmethod
    def from_toml(cls, env, settings_path: (str | Path)='app_settings.toml',
        section: str='args', **overrides: FlightCloneArgsTD
        ) ->'FlightClone':
        base = load_args(settings_path, section=section)
        merged = merge_args(base, overrides or None)
        return cls(env, args=merged)

    def to_toml(self, settings_path: (str | Path)='app_settings.toml',
        section: str='args', create_missing: bool=True) ->None:
        dump_args(self.args, settings_path, section=section, create_missing
            =create_missing)

    def as_dict(self) ->dict[str, Any]:
        payload = self.args.model_dump(mode='json')
        payload['data_out'] = str(self.data_out)
        return payload

    def _resolve_output_root(self, dataset_root: Path) ->Path:
        parent = (dataset_root.parent if dataset_root.parent !=
            dataset_root else dataset_root)
        target = Path(normalize_path(parent / 'dataframe'))
        try:
            target = target.expanduser().resolve(strict=False)
        except Exception:
            target = target.expanduser()
        return target

    def _reset_output(self) ->None:
        try:
            if self.data_out.exists():
                shutil.rmtree(self.data_out, ignore_errors=True, onerror=
                    WorkDispatcher._onerror)
            self.data_out.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            logger.error('warning issue while trying to remove directory: %s',
                exc)

    def haversine(self, lon1, lat1, lon2, lat2):
        """
        Calculate the great-circle distance between two points
        on the Earth specified by longitude and latitude.
        Returns distance in kilometers.
        """
        lon1, lat1, lon2, lat2 = map(math.radians, [lon1, lat1, lon2, lat2])
        dlon = lon2 - lon1
        dlat = lat2 - lat1
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2
            ) * math.sin(dlon / 2) ** 2
        c = 2 * math.asin(math.sqrt(a))
        R = 6371.0
        return R * c

    def build_distribution(self, workers):
        """build_distrib: to provide the list of files per planes (level1) and per workers (level2)
        the level 1 has been think to prevent that à job that requires all the output-data of a plane have to wait for another
        my_code_worker which would have collapse the overall performance

        Args:

        Returns:

        """
        try:
            waypoints_path = self.data_in / self.waypoints
            with open(waypoints_path, 'r') as file:
                list_waypoints = json.load(file)
            template_features = list_waypoints.get('features', [])
            if not template_features:
                raise ValueError(f'No features found in {waypoints_path}')
            total_requested = max(1, int(self.num_flights))
            synthetic_features = self._synthesize_features(template_features,
                total_requested)
            if len(synthetic_features) < total_requested:
                raise ValueError(
                    'Synthesis pipeline failed to produce enough waypoint variants.'
                    )
            collection_created = list_waypoints.get('created')
            flight_jobs = self._prepare_waypoint_files(features=
                synthetic_features, total_requested=total_requested,
                created_ts=collection_created)
            if not flight_jobs:
                return [], [], 'flight', 'files', 'km'
            weighted_jobs = [(job['index'], job['weight']) for job in
                flight_jobs]
            job_lookup = {job['index']: job for job in flight_jobs}
            workers_chunks = WorkDispatcher.make_chunks(len(weighted_jobs),
                weighted_jobs, verbose=self.verbose, workers=workers,
                threshold=12)
            workers_plan: list[list[list[str]]] = []
            workers_metadata: list[list[dict[str, Any]]] = []
            for worker_chunks in workers_chunks:
                worker_plan: list[list[str]] = []
                worker_meta: list[dict[str, Any]] = []
                for chunk in worker_chunks:
                    if chunk is None:
                        continue
                    if isinstance(chunk, list) and chunk:
                        chunk = chunk[0]
                    if isinstance(chunk, tuple):
                        flight_index = chunk[0]
                        total_length = chunk[1] if len(chunk) > 1 else None
                    else:
                        flight_index = chunk
                        total_length = None
                    job = job_lookup[flight_index]
                    if total_length is None:
                        total_length = job['weight']
                    worker_plan.append([{'flight_index': job['index'],
                        'waypoints_file': job['relative_path'],
                        'waypoint_feature': job['feature']}])
                    worker_meta.append({'flight': job['flight_id'],
                        'flight_index': job['index'], 'files': 1,
                        'waypoints_file': job['relative_path'],
                        'distance_km': round(total_length, 3), 'weight':
                        total_length})
                workers_plan.append(worker_plan)
                workers_metadata.append(worker_meta)
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                f'Waypoints file not found at {self.data_in / self.waypoints}'
                ) from exc
        except Exception as e:
            print(traceback.format_exc())
            print(f'warning issue while trying to build distribution: {e}')
            return [[]], [], 'flight', 'files', 'km'
        return workers_plan, workers_metadata, 'flight', 'files', 'km'

    def _maybe_regenerate_waypoints(self) ->None:
        """Optionally rebuild the waypoint catalog from bundled generator assets."""
        regenerate = bool(getattr(self.args, 'regenerate_waypoints', False))
        if not regenerate:
            return
        if (self.args.data_source or '').lower() != 'file':
            logger.info(
                'Skipping waypoint regeneration because data_source=%s is not file-based'
                , self.args.data_source)
            return
        try:
            self._regenerate_uswc_waypoints()
        except FileNotFoundError as exc:
            logger.warning(
                'Skipping waypoint regeneration because required assets are missing: %s'
                , exc)
            return
        except Exception as exc:
            logger.error('Failed to regenerate waypoints catalog: %s', exc,
                exc_info=True)
            raise

    def _regenerate_uswc_waypoints(self) ->None:
        """Rebuild waypoints.geojson from the forward/reverse USWC trajectory assets."""
        package_root = Path(__file__).resolve().parent
        project_root = package_root.parents[1]
        tools_dir = project_root / 'tools'
        generator_scripts = [tools_dir / 'uswc_trajectory_forward.py', 
            tools_dir / 'uswc_trajectory_reverse.py'] if tools_dir.exists(
            ) else []
        for script_path in generator_scripts:
            if not script_path.exists():
                logger.debug('Skipping missing waypoint generator script: %s',
                    script_path)
                continue
            try:
                result = subprocess.run([sys.executable, str(script_path)],
                    check=True, capture_output=True, text=True)
            except subprocess.CalledProcessError as exc:
                stdout = exc.stdout.strip() if exc.stdout else ''
                stderr = exc.stderr.strip() if exc.stderr else ''
                logger.error(
                    """Waypoint generator %s failed with return code %s.
STDOUT:
%s
STDERR:
%s"""
                    , script_path, exc.returncode, stdout, stderr)
                raise RuntimeError(
                    f'Failed to regenerate waypoint assets via {script_path.name}'
                    ) from exc
            else:
                if result.stdout.strip():
                    logger.debug('Waypoint generator %s output:\n%s',
                        script_path.name, result.stdout.strip())
                if result.stderr.strip():
                    logger.warning('Waypoint generator %s stderr output:\n%s',
                        script_path.name, result.stderr.strip())
        data_in_root = self.data_in
        dataset_candidates: list[Path] = [data_in_root]
        if not data_in_root.is_absolute():
            env_home = getattr(self.env, 'home_abs', None)
            if env_home:
                dataset_candidates.append(Path(env_home) / data_in_root)
            dataset_candidates.append(Path.home() / data_in_root)
        search_dirs: list[Path] = []
        for candidate in dataset_candidates:
            try:
                resolved_candidate = Path(candidate).expanduser().resolve(
                    strict=False)
            except Exception:
                continue
            if resolved_candidate.is_dir():
                search_dirs.append(resolved_candidate)
        if not search_dirs:
            raise FileNotFoundError(
                f'Missing USWC trajectory assets. No dataset directory found for data_in={self.data_in}'
                )
        seen_dirs: set[Path] = set()
        ordered_search_dirs: list[Path] = []
        for candidate in search_dirs:
            marker = candidate.resolve(strict=False) if candidate.exists(
                ) else candidate
            if marker in seen_dirs:
                continue
            seen_dirs.add(marker)
            ordered_search_dirs.append(candidate)
        source_paths: list[Path] | None = None
        missing_locations: list[str] = []
        for candidate in ordered_search_dirs:
            forward_path = candidate / 'uswc_trajectories_forward.geojson'
            reverse_path = candidate / 'uswc_trajectories_reverse.geojson'
            if forward_path.exists() and reverse_path.exists():
                source_paths = [forward_path, reverse_path]
                break
            missing_locations.append(str(candidate))
        if source_paths is None:
            raise FileNotFoundError(
                'Missing USWC trajectory assets. Checked: ' + ', '.join(
                missing_locations))
        aggregated_features: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for src_path in source_paths:
            raw = json.loads(src_path.read_text(encoding='utf-8'))
            for idx, feature in enumerate(raw.get('features', []), start=1):
                geometry = feature.get('geometry') or {}
                if geometry.get('type') != 'LineString':
                    logger.debug(
                        'Skipping feature without LineString geometry in %s',
                        src_path)
                    continue
                coordinates = geometry.get('coordinates') or []
                if len(coordinates) < 2:
                    logger.warning(
                        'Skipping trajectory %s feature #%d due to insufficient coordinates'
                        , src_path, idx)
                    continue
                normalised_coords: list[list[float]] = []
                invalid_coord = False
                bad_entry: Any | None = None
                for entry in coordinates:
                    if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                        invalid_coord = True
                        bad_entry = entry
                        break
                    lon = float(entry[0])
                    lat = float(entry[1])
                    if len(entry) >= 3:
                        alt = float(entry[2])
                        normalised_coords.append([lon, lat, alt])
                    else:
                        normalised_coords.append([lon, lat])
                if invalid_coord:
                    logger.warning(
                        'Skipping trajectory %s feature #%d due to malformed coordinate %s'
                        , src_path, idx, bad_entry)
                    continue
                properties = feature.get('properties') or {}
                base_label = properties.get('route_label'
                    ) or f'{src_path.stem}_{idx:02d}'
                candidate_id = str(properties.get('flight_id') or base_label)
                if candidate_id in seen_ids:
                    suffix = 2
                    while f'{candidate_id}-{suffix}' in seen_ids:
                        suffix += 1
                    candidate_id = f'{candidate_id}-{suffix}'
                seen_ids.add(candidate_id)
                merged_props = dict(properties)
                merged_props['flight_id'] = candidate_id
                merged_props.setdefault('origin', properties.get('start_code'))
                merged_props.setdefault('destination', properties.get(
                    'end_code'))
                merged_props.setdefault('plane_type', properties.get(
                    'plane_type', 'uswc'))
                merged_props['source_file'] = src_path.name
                aggregated_features.append({'type': 'Feature', 'properties':
                    merged_props, 'geometry': {'type': 'LineString',
                    'coordinates': normalised_coords}})
        if not aggregated_features:
            raise ValueError(
                'No valid USWC trajectory features were discovered.')
        waypoints_path = (self.data_in / self.waypoints).expanduser()
        waypoints_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {'type': 'FeatureCollection', 'name': 'uswc_waypoints',
            'created': datetime.now(tz=timezone.utc).isoformat(),
            'features': aggregated_features}
        tmp_path = waypoints_path.with_name(f'{waypoints_path.name}.tmp')
        tmp_path.write_text(json.dumps(payload, indent=2), encoding='utf-8')
        tmp_path.replace(waypoints_path)
        logger.info('Regenerated %d waypoint trajectories into %s', len(
            aggregated_features), waypoints_path)

    def _ensure_ukraine_localization(self) ->None:
        """
        Recenter waypoint, beam, and satellite assets over Ukraine.

        Legacy datasets shipped with US West Coast coordinates. To keep the
        Streamlit experience aligned with the modern scenario we translate all
        assets so the centroid lands near Kyiv when the dataset has not been
        migrated yet.
        """

        dataset_root = Path(self.data_in).expanduser()
        sentinel = dataset_root / '.ukraine_localized'
        waypoints_path = (dataset_root / self.waypoints).expanduser()
        if sentinel.exists() or not waypoints_path.exists():
            return
        current_center = self._compute_waypoint_centroid(waypoints_path)
        if current_center is None:
            return
        target_center = (32.0, 49.0)
        delta_lon = target_center[0] - current_center[0]
        delta_lat = target_center[1] - current_center[1]
        if abs(delta_lon) < 0.05 and abs(delta_lat) < 0.05:
            sentinel.write_text('already localized', encoding='utf-8')
            return
        logger.info('Recentering flight clone dataset by Δlon=%s Δlat=%s',
            round(delta_lon, 4), round(delta_lat, 4))
        self._shift_waypoints_file(waypoints_path, delta_lon, delta_lat)
        for csv_name in ('beams.csv', 'satellites.csv'):
            csv_path = dataset_root / csv_name
            if csv_path.exists():
                self._shift_csv_coordinates(csv_path, delta_lon, delta_lat)
        sentinel.write_text('ukraine', encoding='utf-8')

    def _compute_waypoint_centroid(self, path: Path
        ) ->tuple[float, float] | None:
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
        except Exception as exc:
            logger.warning('Unable to read %s: %s', path, exc)
            return None
        total_lon = 0.0
        total_lat = 0.0
        samples = 0
        for feature in payload.get('features', []):
            geometry = feature.get('geometry') or {}
            coordinates = geometry.get('coordinates') or []
            if not coordinates:
                continue
            sequence = coordinates[0] if isinstance(coordinates[0][0],
                list) else coordinates
            for entry in sequence:
                if len(entry) < 2:
                    continue
                try:
                    total_lon += float(entry[0])
                    total_lat += float(entry[1])
                    samples += 1
                except (TypeError, ValueError):
                    continue
        if not samples:
            return None
        return total_lon / samples, total_lat / samples

    def _shift_waypoints_file(self, path: Path, delta_lon: float,
        delta_lat: float) ->None:
        payload = json.loads(path.read_text(encoding='utf-8'))
        for feature in payload.get('features', []):
            geometry = feature.get('geometry') or {}
            coordinates = geometry.get('coordinates') or []
            if not coordinates:
                continue
            nested = isinstance(coordinates[0][0], list)
            sequence = coordinates[0] if nested else coordinates
            for entry in sequence:
                if len(entry) >= 2:
                    entry[0] = float(entry[0]) + delta_lon
                    entry[1] = float(entry[1]) + delta_lat
            if nested:
                geometry['coordinates'] = [sequence]
            else:
                geometry['coordinates'] = sequence
        path.write_text(json.dumps(payload, indent=2), encoding='utf-8')

    def _shift_csv_coordinates(self, path: Path, delta_lon: float,
        delta_lat: float) ->None:
        try:
            if path.name == 'beams.csv':
                df = pd.read_csv(path, header=None, names=['beam', 'lon',
                    'lat'])
                df['lon'] = df['lon'].astype(float) + delta_lon
                df['lat'] = df['lat'].astype(float) + delta_lat
                df.to_csv(path, header=False, index=False)
            else:
                df = pd.read_csv(path)
                if 'beam_long' in df.columns:
                    df['beam_long'] = df['beam_long'].astype(float) + delta_lon
                if 'beam_lat' in df.columns:
                    df['beam_lat'] = df['beam_lat'].astype(float) + delta_lat
                df.to_csv(path, index=False)
        except Exception as exc:
            logger.warning('Unable to shift %s: %s', path, exc)

    def _prepare_waypoint_files(self, *, features: Iterable[dict[str, Any]],
        total_requested: int, created_ts: (str | None)=None) ->list[dict[
        str, Any]]:
        split_dir = self.data_in / f'{Path(self.waypoints).stem}_split'
        try:
            if split_dir.exists():
                shutil.rmtree(split_dir, ignore_errors=True, onerror=
                    WorkDispatcher._onerror)
            split_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            logger.error("Failed to prepare waypoint split directory '%s': %s",
                split_dir, exc)
            raise
        group_pattern = itertools.cycle([2, 3, 4])
        group_assignments: dict[int, tuple[int, int]] = {}
        cursor = 0
        while cursor < total_requested:
            group_size = next(group_pattern)
            indices = list(range(cursor, min(cursor + group_size,
                total_requested)))
            actual_size = len(indices)
            if not indices:
                break
            for position, flight_idx in enumerate(indices):
                group_assignments[flight_idx] = actual_size, position
            cursor += actual_size
        source_features = list(features)
        if not source_features:
            raise ValueError('No waypoint features available to prepare jobs.')
        if len(source_features) < total_requested:
            raise ValueError(
                'Waypoint feature pool smaller than requested flights after synthesis.'
                )
        jobs: list[dict[str, Any]] = []
        for idx in range(total_requested):
            feature = copy.deepcopy(source_features[idx])
            properties = feature.get('properties') or {}
            if not properties:
                feature['properties'] = {}
            flight_label = properties.get('flight_id') or f'flight-{idx:03d}'
            safe_label = re.sub('[^A-Za-z0-9._-]+', '-', flight_label).strip(
                '-') or f'flight-{idx:03d}'
            filename = f'{idx:03d}_{safe_label}.geojson'
            target_path = split_dir / filename
            geometry = feature.get('geometry') or {}
            coordinates = geometry.get('coordinates', [])
            if not coordinates:
                logger.warning('Flight %s has no coordinates, skipping',
                    flight_label)
                continue
            sequence = coordinates[0] if isinstance(coordinates[0][0], list
                ) else coordinates
            if not sequence:
                logger.warning(
                    'Flight %s has an empty coordinate sequence, skipping',
                    flight_label)
                continue
            total_length: float | None = 0.0
            for coord_a, coord_b in zip(sequence, sequence[1:]):
                try:
                    lon1, lat1 = float(coord_a[0]), float(coord_a[1])
                    lon2, lat2 = float(coord_b[0]), float(coord_b[1])
                except (TypeError, ValueError, IndexError) as exc:
                    logger.warning(
                        'Skipping malformed coordinate pair in flight %s: %s',
                        flight_label, exc)
                    total_length = None
                    break
                total_length += self.haversine(lon1, lat1, lon2, lat2)
            if total_length is None:
                logger.warning(
                    'Skipping flight %s because a malformed coordinate prevented distance calculation'
                    , flight_label)
                continue
            group_size, group_position = group_assignments.get(idx, (1, 0))
            feature['properties']['loop_group_size'] = group_size
            feature['properties']['loop_position'] = group_position
            payload = {'type': 'FeatureCollection', 'name': feature.get(
                'name', f'flight_{idx:03d}'), 'created': created_ts,
                'features': [feature]}
            if created_ts is None:
                payload.pop('created', None)
            with open(target_path, 'w') as handle:
                json.dump(payload, handle, indent=2)
            try:
                relative_path = str(target_path.relative_to(self.data_in))
            except ValueError:
                relative_path = str(target_path)
            jobs.append({'index': idx, 'flight_id': flight_label,
                'relative_path': relative_path, 'absolute_path': str(
                target_path), 'weight': total_length, 'feature': feature})
        return jobs

    def _synthesize_features(self, templates: list[dict[str, Any]],
        total_requested: int) ->list[dict[str, Any]]:
        """Generate synthetic waypoint variants matching the requested flight count."""
        if total_requested <= 0:
            return []
        if not templates:
            raise ValueError(
                'Cannot synthesize waypoint variants without template features.'
                )
        synthesized: list[dict[str, Any]] = []
        template_count = len(templates)
        golden = (math.sqrt(5) - 1) / 2
        for idx in range(total_requested):
            template = copy.deepcopy(templates[idx % template_count])
            properties = template.setdefault('properties', {})
            base_label = properties.get('flight_id'
                ) or f'flight-{idx % template_count:03d}'
            properties['flight_id'] = f'{base_label}-S{idx + 1:03d}'
            properties['synthetic_source_index'] = idx % template_count
            if 'route_label' in properties:
                properties['route_label'
                    ] = f"{properties['route_label']}-S{idx + 1:03d}"
            if 'track_variant' in properties:
                properties['track_variant'
                    ] = f"{properties['track_variant']}-S{idx + 1:03d}"
            geometry = template.get('geometry') or {}
            coordinates = geometry.get('coordinates', [])
            if not coordinates:
                synthesized.append(template)
                continue
            nested = isinstance(coordinates[0][0], (list, tuple))
            sequence = coordinates[0] if nested else coordinates
            jitter_lon = 0.06 * math.sin((idx + 1) * golden * 2 * math.pi)
            jitter_lat = 0.06 * math.cos((idx + 1) * golden * 2 * math.pi)
            adjusted: list[list[float]] = []
            for point in sequence:
                lon = float(point[0]) + jitter_lon
                lat = float(point[1]) + jitter_lat
                if len(point) >= 3:
                    adjusted.append([lon, lat, point[2]])
                else:
                    adjusted.append([lon, lat])
            geometry['coordinates'] = [adjusted] if nested else adjusted
            synthesized.append(template)
        return synthesized

    def _synthesize_additional_features(self, base_features: list[dict[str,
        Any]], extra_count: int) ->list[dict[str, Any]]:
        """Create additional waypoint variants by lightly perturbing existing routes."""
        if extra_count <= 0 or not base_features:
            return []
        synthesized: list[dict[str, Any]] = []
        template_count = len(base_features)
        for idx in range(extra_count):
            template = copy.deepcopy(base_features[idx % template_count])
            properties = template.setdefault('properties', {})
            base_label = properties.get('flight_id'
                ) or f'flight-{idx % template_count:03d}'
            suffix = idx // template_count + 2
            properties['flight_id'] = f'{base_label}-S{suffix}'
            if 'route_label' in properties:
                properties['route_label'
                    ] = f"{properties['route_label']}-S{suffix}"
            if 'track_variant' in properties:
                properties['track_variant'
                    ] = f"{properties['track_variant']}-S{suffix}"
            geometry = template.get('geometry') or {}
            coordinates = geometry.get('coordinates', [])
            if not coordinates:
                synthesized.append(template)
                continue
            nested = isinstance(coordinates[0][0], (list, tuple))
            sequence = coordinates[0] if nested else coordinates
            jitter_lon = 0.04 * (idx % 5 - 2)
            jitter_lat = 0.04 * (idx // 5 % 5 - 2)
            adjusted_sequence: list[list[float]] = []
            for point in sequence:
                lon = float(point[0]) + jitter_lon
                lat = float(point[1]) + jitter_lat
                if len(point) >= 3:
                    adjusted_sequence.append([lon, lat, point[2]])
                else:
                    adjusted_sequence.append([lon, lat])
            if nested:
                geometry['coordinates'] = [adjusted_sequence]
            else:
                geometry['coordinates'] = adjusted_sequence
            synthesized.append(template)
        return synthesized
