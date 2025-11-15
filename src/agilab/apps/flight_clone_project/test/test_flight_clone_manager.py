import json
import sys
from pathlib import Path
import pytest
script_path = Path(__file__).resolve()
apps_dir = script_path.parents[2]
active_app_path = script_path.parents[1]
src_path = active_app_path / 'src'
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))
from agi_env import AgiEnv
from flight_clone import FlightClone, FlightCloneArgs


class DummyEnv:

    def __init__(self, home_abs: Path):
        self.home_abs = Path(home_abs)
        self.verbose = 0
        self._is_managed_pc = False
        self.base_worker_cls = 'polars_worker'
        self.data_rel = Path('flight_clone')
        self.dataset_archive = self.home_abs / 'dataset.7z'


@pytest.fixture
def flight_clone():
    env = AgiEnv(apps_dir=apps_dir, active_app=active_app_path.name,
        verbose=True)
    args = FlightCloneArgs(data_in='flight_clone/dataset', waypoints=
        'waypoints.geojson', num_flights=1, beam_file='beams.csv', sat_file
        ='satellites.csv')
    return FlightClone(env=env, args=args)


def test_build_distribution(flight_clone):
    workers = {'worker1': 2, 'worker2': 3}
    planes, chunks, level1, level2, status = flight_clone.build_distribution(
        workers)
    assert isinstance(planes, list)
    assert isinstance(chunks, list)
    assert level1
    assert level2


def test_synthesized_waypoints_match_requested_count(tmp_path):
    dataset_dir = tmp_path / 'dataset'
    dataset_dir.mkdir()
    waypoints_path = dataset_dir / 'waypoints.geojson'
    payload = {'type': 'FeatureCollection', 'features': [{'type': 'Feature',
        'properties': {'flight_id': 'template_forward'}, 'geometry': {
        'type': 'LineString', 'coordinates': [[-122.0, 37.0, 1000], [-121.5,
        37.5, 1200], [-121.0, 38.0, 1500]]}}, {'type': 'Feature',
        'properties': {'flight_id': 'template_reverse'}, 'geometry': {
        'type': 'LineString', 'coordinates': [[-121.0, 38.0, 1500], [-121.5,
        37.5, 1200], [-122.0, 37.0, 1000]]}}]}
    waypoints_path.write_text(json.dumps(payload), encoding='utf-8')
    env = DummyEnv(tmp_path)
    args = FlightCloneArgs(data_in=dataset_dir, waypoints=
        'waypoints.geojson', num_flights=5, beam_file='beams.csv', sat_file
        ='satellites.csv')
    trajectory = FlightClone(env=env, args=args)
    workers_plan, workers_metadata, *_ = trajectory.build_distribution({
        'worker': 1})
    split_dir = dataset_dir / 'waypoints_split'
    split_files = sorted(split_dir.glob('*.geojson'))
    assert len(split_files) == 5
    assert all('-S' in file.stem for file in split_files)
    assigned_ids = [entry['flight'] for worker_entries in workers_metadata for
        entry in worker_entries]
    assert len(assigned_ids) == 5
    assert all('-S' in flight_id for flight_id in assigned_ids)
    assert workers_plan, 'Expected non-empty worker plan output'


def test_dataset_localization_shifts_assets(tmp_path):
    dataset_dir = tmp_path / 'dataset'
    dataset_dir.mkdir()
    waypoints_path = dataset_dir / 'waypoints.geojson'
    sample_payload = {'type': 'FeatureCollection', 'features': [{'type':
        'Feature', 'properties': {'flight_id': 'legacy-uswc'}, 'geometry': {
        'type': 'LineString', 'coordinates': [[-122.0, 37.5, 1000], [-121.0,
        38.0, 1200]]}}]}
    waypoints_path.write_text(json.dumps(sample_payload), encoding='utf-8')
    (dataset_dir / 'beams.csv').write_text('1,-122.0,37.5\n1,-121.5,37.6\n1,-121.0,37.7\n'
        , encoding='utf-8')
    (dataset_dir / 'satellites.csv').write_text(
        'beam,sat,ant,beam_long,beam_lat,beam_alt\n1,Echo-17,N1,-122.0,37.5,100\n'
        , encoding='utf-8')
    env = AgiEnv(apps_dir=apps_dir, active_app=active_app_path.name,
        verbose=False)
    args = FlightCloneArgs(data_in=str(dataset_dir), waypoints=
        'waypoints.geojson', num_flights=1, beam_file='beams.csv', sat_file=
        'satellites.csv', regenerate_waypoints=False)
    FlightClone(env=env, args=args)
    sentinel = dataset_dir / '.ukraine_localized'
    assert sentinel.exists()
    updated = json.loads(waypoints_path.read_text(encoding='utf-8'))
    coords = updated['features'][0]['geometry']['coordinates']
    mean_lon = sum(pt[0] for pt in coords) / len(coords)
    mean_lat = sum(pt[1] for pt in coords) / len(coords)
    assert 31.0 < mean_lon < 34.5
    assert 48.0 < mean_lat < 50.5
