import pytest
from pathlib import Path
from unittest import mock

from agi_env import AgiEnv


@pytest.fixture
def env():
    agipath = AgiEnv.locate_agilab_installation(verbose=False)
    apps_dir = agipath / 'apps'
    return AgiEnv(apps_dir=apps_dir, app='flight_project', verbose=1)

def test_replace_content_replaces_whole_words(env):
    txt = 'foo foo_bar barfoo bar Foo foo.'
    rename_map = {'foo': 'baz', 'bar': 'qux', 'Foo': 'Baz'}
    out = env.replace_content(txt, rename_map)
    assert out == 'baz foo_bar barfoo qux Baz baz.'

def test_change_app_reinitializes_on_change(monkeypatch, env):
    called = {'count': 0, 'kwargs': None}
    def fake_init(self, *a, **k):
        called['count'] += 1
        called['kwargs'] = k
    apps_path = AgiEnv.locate_agilab_installation(verbose=False) / "apps"
    flight_path = apps_path / 'flight_project'
    env.app = flight_path
    mycode_name = "mycode_path"
    with mock.patch.object(AgiEnv, '__init__', fake_init, create=True):
        env.change_app(mycode_name)
    assert called['count'] == 1
    assert called['kwargs'].get('apps_dir') == apps_path
    assert called['kwargs'].get('app') == mycode_name
    assert 'install_type' not in called['kwargs']

def test_change_app_noop_when_same_app(monkeypatch, env):
    called = {'count': 0}
    def fake_init(self, *a, **k):
        called['count'] += 1
    apps_path = AgiEnv.locate_agilab_installation(verbose=False) / "apps"
    flight_path = apps_path / 'flight_project'
    env.app = flight_path
    with mock.patch.object(AgiEnv, '__init__', fake_init, create=True):
        env.change_app('flight_project')
    assert called['count'] == 0

def test_humanize_validation_errors(env):
    from pydantic import BaseModel, ValidationError, constr
    class TestModel(BaseModel):
        name: constr(min_length=3)
    with pytest.raises(ValidationError) as exc:
        TestModel(name='a')
    errors = env.humanize_validation_errors(exc.value)
    assert any('name' in e for e in errors)

def test_create_rename_map_basic(env, tmp_path: Path):
    src = tmp_path / 'flight_project'
    dst = tmp_path / 'tata_project'
    src.mkdir(); dst.mkdir()
    mapping = env.create_rename_map(src, dst)
    assert mapping.get('flight_project') == 'tata_project'
    assert mapping.get('flight') == 'tata'
    assert mapping.get('Flight') == 'Tata'
    assert mapping.get('FlightWorker') == 'TataWorker'
    assert mapping.get('FlightArgs') == 'TataArgs'
    assert mapping.get('src/flight') == 'src/tata'

def test_locate_helper_exists():
    assert hasattr(AgiEnv, 'locate_agilab_installation')
