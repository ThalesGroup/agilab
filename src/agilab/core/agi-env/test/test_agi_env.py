import pytest
from pathlib import Path
from unittest import mock

from agi_env import AgiEnv

from agi_env.agi_logger import AgiLogger

logger = AgiLogger.get_logger(__name__)


@pytest.fixture
def env(tmp_path, monkeypatch):
    agipath = AgiEnv.locate_agilab_installation(verbose=False)
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    share_dir = fake_home / ".local" / "share" / "agilab"
    logger.info(f"mkdir {share_dir}")
    share_dir.mkdir(parents=True, exist_ok=True)
    (share_dir / ".agilab-path").write_text(str(agipath) + "\n")
    monkeypatch.setenv("HOME", str(fake_home))
    apps_path = agipath / 'apps'
    return AgiEnv(apps_path=apps_path, app='mycode_project', verbose=1)

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
    current_app_path = apps_path / 'mycode_project'
    env.app = current_app_path
    mycode_name = "mycode_path"
    with mock.patch.object(AgiEnv, '__init__', fake_init, create=True):
        env.change_app(mycode_name)
    assert called['count'] == 1
    assert called['kwargs'].get('apps_path') == apps_path
    assert called['kwargs'].get('app') == mycode_name
    assert 'install_type' not in called['kwargs']

def test_change_app_noop_when_same_app(monkeypatch, env):
    called = {'count': 0}
    def fake_init(self, *a, **k):
        called['count'] += 1
    apps_path = AgiEnv.locate_agilab_installation(verbose=False) / "apps"
    current_app_path = apps_path / 'mycode_project'
    env.app = current_app_path
    with mock.patch.object(AgiEnv, '__init__', fake_init, create=True):
        env.change_app('mycode_project')
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
    src = tmp_path / 'alpha_project'
    dst = tmp_path / 'bravo_project'
    src.mkdir(); dst.mkdir()
    mapping = env.create_rename_map(src, dst)
    assert mapping.get('alpha_project') == 'bravo_project'
    assert mapping.get('alpha') == 'bravo'
    assert mapping.get('Alpha') == 'Bravo'
    assert mapping.get('AlphaWorker') == 'BravoWorker'
    assert mapping.get('AlphaArgs') == 'BravoArgs'
    assert mapping.get('src/alpha') == 'src/bravo'

def test_locate_helper_exists():
    assert hasattr(AgiEnv, 'locate_agilab_installation')


def test_cluster_share_warning_deduplicated(tmp_path: Path, monkeypatch):
    """Only log the cluster-share fallback warning once per process."""

    agipath = AgiEnv.locate_agilab_installation(verbose=False)
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    share_dir = fake_home / ".local" / "share" / "agilab"
    share_dir.mkdir(parents=True, exist_ok=True)
    (share_dir / ".agilab-path").write_text(str(agipath) + "\n")
    monkeypatch.setenv("HOME", str(fake_home))

    AgiEnv.reset()
    AgiEnv._share_mount_warning_keys.clear()

    mock_logger = mock.Mock()
    with mock.patch.object(AgiLogger, "configure", return_value=mock_logger):
        apps_path = agipath / "apps"
        AgiEnv(apps_path=apps_path, app="mycode_project", verbose=1)
        AgiEnv(apps_path=apps_path, app="mycode_project", verbose=1)

    warning_calls = [
        call
        for call in mock_logger.warning.call_args_list
        if call.args
        and isinstance(call.args[0], str)
        and "AGI_CLUSTER_SHARE is not mounted" in call.args[0]
    ]
    assert len(warning_calls) == 1
