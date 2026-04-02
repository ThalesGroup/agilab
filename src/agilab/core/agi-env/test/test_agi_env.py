import asyncio
import getpass
import logging
import shlex
import sys

import pytest
from pathlib import Path
from unittest import mock

from agi_env import AgiEnv
import agi_env.agi_env as agi_env_module

from agi_env.agi_logger import AgiLogger
from agi_env.defaults import get_default_openai_model

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


def test_humanize_validation_errors_model_level(env):
    from pydantic import BaseModel, ValidationError, model_validator

    class TestModel(BaseModel):
        value: int = 1

        @model_validator(mode="before")
        @classmethod
        def fail(cls, data):
            raise ValueError("rename hint")

    with pytest.raises(ValidationError) as exc:
        TestModel()

    errors = env.humanize_validation_errors(exc.value)
    assert any("(model)" in e for e in errors)
    assert any("rename hint" in e for e in errors)

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


def test_blank_log_and_export_dirs_fall_back_to_home_defaults(tmp_path: Path, monkeypatch):
    agipath = AgiEnv.locate_agilab_installation(verbose=False)
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    monkeypatch.delenv("AGI_LOG_DIR", raising=False)
    monkeypatch.delenv("AGI_EXPORT_DIR", raising=False)

    env = object.__new__(AgiEnv)
    env.home_abs = fake_home
    env.target = "sb3_trainer"
    env.agilab_pck = agipath
    env.read_agilab_path = lambda: None

    env.init_envars_app(
        {
            "AGI_LOG_DIR": "",
            "AGI_EXPORT_DIR": "   ",
        }
    )

    assert env.AGILAB_LOG_ABS == fake_home / "log"
    assert env.runenv == fake_home / "log" / "execute" / "sb3_trainer"
    assert env.AGILAB_EXPORT_ABS == fake_home / "export"
    assert env.export_apps == fake_home / "export" / "apps-zip"


def test_blank_log_and_export_dirs_do_not_mask_process_overrides(tmp_path: Path, monkeypatch):
    agipath = AgiEnv.locate_agilab_installation(verbose=False)
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    monkeypatch.setenv("AGI_LOG_DIR", "process-log")
    monkeypatch.setenv("AGI_EXPORT_DIR", "process-export")

    env = object.__new__(AgiEnv)
    env.home_abs = fake_home
    env.target = "sb3_trainer"
    env.agilab_pck = agipath
    env.read_agilab_path = lambda: None

    env.init_envars_app(
        {
            "AGI_LOG_DIR": "",
            "AGI_EXPORT_DIR": "   ",
        }
    )

    assert env.AGILAB_LOG_ABS == fake_home / "process-log"
    assert env.runenv == fake_home / "process-log" / "execute" / "sb3_trainer"
    assert env.AGILAB_EXPORT_ABS == fake_home / "process-export"
    assert env.export_apps == fake_home / "process-export" / "apps-zip"


def test_blank_env_assignments_are_treated_as_unset_globally(tmp_path: Path, monkeypatch):
    agipath = AgiEnv.locate_agilab_installation(verbose=False)
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    share_dir = fake_home / ".local" / "share" / "agilab"
    share_dir.mkdir(parents=True, exist_ok=True)
    (share_dir / ".agilab-path").write_text(str(agipath) + "\n")
    (fake_home / ".agilab").mkdir(parents=True, exist_ok=True)
    (fake_home / ".agilab" / ".env").write_text(
        "\n".join(
            [
                "IS_SOURCE_ENV=1",
                "OPENAI_MODEL=",
                "APP_DEFAULT=",
                "TABLE_MAX_ROWS=",
                "AGI_LOG_DIR=",
                "AGI_EXPORT_DIR=",
                "MLFLOW_TRACKING_DIR=",
                "AGI_PYTHON_VERSION=",
                "CLUSTER_CREDENTIALS=",
                "AGI_SCHEDULER_IP=",
            ]
        )
        + "\n"
    )
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("AGI_LOG_DIR", raising=False)
    monkeypatch.delenv("AGI_EXPORT_DIR", raising=False)

    env = AgiEnv(apps_path=agipath / "apps", app=None, verbose=1)

    assert env.app == "flight_project"
    assert env.OPENAI_MODEL == get_default_openai_model()
    assert env.TABLE_MAX_ROWS == 1000000
    assert env.AGILAB_LOG_ABS == fake_home / "log"
    assert env.AGILAB_EXPORT_ABS == fake_home / "export"
    assert env.MLFLOW_TRACKING_DIR == fake_home / ".mlflow"
    assert env.python_version == "3.13"
    assert env.user == getpass.getuser()
    assert env.scheduler_ip == "127.0.0.1"
    assert "OPENAI_MODEL" not in env.envars
    assert "APP_DEFAULT" not in env.envars
    assert "TABLE_MAX_ROWS" not in env.envars
    assert "AGI_LOG_DIR" not in env.envars


def test_cluster_share_missing_raises_for_cluster_enabled_app(tmp_path: Path, monkeypatch):
    """Cluster-enabled apps must fail fast when the configured cluster share is unavailable."""

    agipath = AgiEnv.locate_agilab_installation(verbose=False)
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    (fake_home / ".agilab").mkdir(parents=True, exist_ok=True)
    (fake_home / ".agilab" / ".env").write_text(
        "AGI_CLUSTER_ENABLED=1\nAGI_CLUSTER_SHARE=/nonexistent_cluster_share\n"
    )
    monkeypatch.delenv("AGI_CLUSTER_SHARE", raising=False)
    monkeypatch.delenv("AGI_SHARE_DIR", raising=False)
    share_dir = fake_home / ".local" / "share" / "agilab"
    share_dir.mkdir(parents=True, exist_ok=True)
    (share_dir / ".agilab-path").write_text(str(agipath) + "\n")

    # Create a fake app with cluster_enabled = true in app_settings.toml
    # so _cluster_enabled_from_settings() returns True (the real mycode_project
    # has cluster_enabled = false which would prevent the warning from firing).
    fake_apps = tmp_path / "apps"
    fake_app = fake_apps / "mycode_project"
    fake_app_src = fake_app / "src" / "mycode"
    fake_app_src.mkdir(parents=True, exist_ok=True)
    (fake_app / "src" / "app_settings.toml").write_text(
        "[cluster]\ncluster_enabled = true\n"
    )

    monkeypatch.setenv("HOME", str(fake_home))

    AgiEnv.reset()
    AgiEnv._share_mount_warning_keys.clear()

    mock_logger = mock.Mock()
    with mock.patch.object(AgiLogger, "configure", return_value=mock_logger):
        with pytest.raises(RuntimeError, match="Cluster mode requires AGI_CLUSTER_SHARE"):
            AgiEnv(apps_path=fake_apps, app="mycode_project", verbose=1)


def test_cluster_enabled_raises_when_app_src_invalid(tmp_path: Path, monkeypatch):
    """Even with a broken app src, cluster-enabled envs must not fall back to localshare."""

    agipath = AgiEnv.locate_agilab_installation(verbose=False)
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    share_dir = fake_home / ".local" / "share" / "agilab"
    share_dir.mkdir(parents=True, exist_ok=True)
    (share_dir / ".agilab-path").write_text(str(agipath) + "\n")
    (fake_home / ".agilab").mkdir(parents=True, exist_ok=True)
    (fake_home / ".agilab" / ".env").write_text(
        "AGI_CLUSTER_ENABLED=1\nAGI_CLUSTER_SHARE=/nonexistent_cluster_share\n"
    )
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("AGI_CLUSTER_SHARE", raising=False)
    monkeypatch.delenv("AGI_SHARE_DIR", raising=False)

    # Create an app with an unusable `src` entry to mimic a transient broken path
    # during local build steps (e.g. pre-Cython local compilation).
    fake_apps = tmp_path / "apps"
    bad_app = fake_apps / "broken_project"
    bad_app.mkdir(parents=True, exist_ok=True)
    (bad_app / "src").write_text("broken")

    AgiEnv.reset()
    AgiEnv._share_mount_warning_keys.clear()

    mock_logger = mock.Mock()
    with mock.patch.object(AgiLogger, "configure", return_value=mock_logger), mock.patch.object(
        AgiEnv, "_init_apps", lambda self: None
    ):
        with pytest.raises(RuntimeError, match="Cluster mode requires AGI_CLUSTER_SHARE"):
            AgiEnv(apps_path=fake_apps, app="broken_project", verbose=1)


def test_cluster_enabled_from_process_env_when_app_src_invalid(tmp_path: Path, monkeypatch):
    """Use process environment as fallback when app settings cannot be read."""

    agipath = AgiEnv.locate_agilab_installation(verbose=False)
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    (fake_home / ".local" / "share" / "agilab").mkdir(parents=True, exist_ok=True)
    share_dir = fake_home / ".local" / "share" / "agilab"
    (share_dir / ".agilab-path").write_text(str(agipath) + "\n")
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("AGI_CLUSTER_ENABLED", "1")
    monkeypatch.setenv("AGI_CLUSTER_SHARE", str(share_dir / "cluster_shared"))
    (share_dir / "cluster_shared").mkdir(exist_ok=True, parents=True)

    monkeypatch.delenv("AGI_SHARE_DIR", raising=False)
    fake_apps = tmp_path / "apps"
    bad_app = fake_apps / "broken_project"
    bad_app.mkdir(parents=True, exist_ok=True)
    (bad_app / "src").write_text("broken")

    AgiEnv.reset()
    AgiEnv._share_mount_warning_keys.clear()
    mock_logger = mock.Mock()
    with mock.patch.object(AgiEnv, "_init_apps", lambda self: None), mock.patch.object(
        AgiLogger, "configure", return_value=mock_logger
    ):
        env = AgiEnv(apps_path=fake_apps, app="broken_project", verbose=1)

    assert env.agi_share_path == env.AGI_CLUSTER_SHARE


def test_cluster_share_same_as_local_share_raises(tmp_path: Path, monkeypatch):
    """Cluster mode must reject a cluster-share setting that points to localshare."""

    agipath = AgiEnv.locate_agilab_installation(verbose=False)
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    share_dir = fake_home / ".local" / "share" / "agilab"
    share_dir.mkdir(parents=True, exist_ok=True)
    (share_dir / ".agilab-path").write_text(str(agipath) + "\n")
    (fake_home / ".agilab").mkdir(parents=True, exist_ok=True)
    same_share = fake_home / "localshare"
    same_share.mkdir()
    (fake_home / ".agilab" / ".env").write_text(
        f"AGI_CLUSTER_ENABLED=1\nAGI_CLUSTER_SHARE={same_share}\nAGI_LOCAL_SHARE={same_share}\n"
    )

    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("AGI_SHARE_DIR", raising=False)

    fake_apps = tmp_path / "apps"
    fake_app = fake_apps / "mycode_project"
    fake_app_src = fake_app / "src" / "mycode"
    fake_app_src.mkdir(parents=True, exist_ok=True)
    (fake_app / "src" / "app_settings.toml").write_text(
        "[cluster]\ncluster_enabled = true\n"
    )

    AgiEnv.reset()

    with pytest.raises(RuntimeError, match="AGI_CLUSTER_SHARE to be distinct from AGI_LOCAL_SHARE"):
        AgiEnv(apps_path=fake_apps, app="mycode_project", verbose=1)


def test_cluster_enabled_from_apps_repository_when_app_src_invalid(tmp_path: Path, monkeypatch):
    """Read cluster toggle from APPS_REPOSITORY when active app source is invalid."""

    agipath = AgiEnv.locate_agilab_installation(verbose=False)
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    share_root = fake_home / ".local" / "share" / "agilab"
    share_root.mkdir(parents=True, exist_ok=True)
    (share_root / ".agilab-path").write_text(str(agipath) + "\n")

    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("APPS_REPOSITORY", str(tmp_path / "repo"))

    app_repo = tmp_path / "repo" / "src" / "agilab" / "apps" / "mycode_project" / "src"
    app_repo.mkdir(parents=True, exist_ok=True)
    (app_repo / "app_settings.toml").write_text("[cluster]\ncluster_enabled = true\n")

    cluster_share = fake_home / "cluster_share"
    cluster_share.mkdir()
    monkeypatch.setenv("AGI_CLUSTER_SHARE", str(cluster_share))

    fake_apps = tmp_path / "apps"
    bad_app = fake_apps / "mycode_project"
    bad_app.mkdir(parents=True, exist_ok=True)
    (bad_app / "src").write_text("broken")

    AgiEnv.reset()
    AgiEnv._share_mount_warning_keys.clear()

    mock_logger = mock.Mock()
    with mock.patch.object(AgiLogger, "configure", return_value=mock_logger), mock.patch.object(
        AgiEnv, "_init_apps", lambda self: None
    ), mock.patch.object(AgiEnv, "_ensure_repository_app_link", lambda self: False):
        env = AgiEnv(apps_path=fake_apps, app="mycode_project", verbose=1)

    assert env.agi_share_path == env.AGI_CLUSTER_SHARE


def test_active_app_override_uses_builtin_path_even_when_env_apps_path_is_set(tmp_path: Path, monkeypatch):
    """When active_app is explicit, resolve manager/worker from that path (not APPS_PATH)."""

    agipath = AgiEnv.locate_agilab_installation(verbose=False)
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    share_root = fake_home / ".local" / "share" / "agilab"
    share_root.mkdir(parents=True, exist_ok=True)
    (share_root / ".agilab-path").write_text(str(agipath) + "\n", encoding="utf-8")

    wrong_apps = tmp_path / "wrong_apps"
    wrong_app = wrong_apps / "flight_project"
    (wrong_app / "src").mkdir(parents=True, exist_ok=True)
    (wrong_app / "pyproject.toml").write_text("[project]\nname='wrong-flight'\n", encoding="utf-8")

    env_dir = fake_home / ".agilab"
    env_dir.mkdir(parents=True, exist_ok=True)
    (env_dir / ".env").write_text(f"APPS_PATH={wrong_apps}\n", encoding="utf-8")

    builtin_app = tmp_path / "apps" / "builtin" / "flight_project"
    (builtin_app / "src" / "flight").mkdir(parents=True, exist_ok=True)
    (builtin_app / "src" / "flight_worker").mkdir(parents=True, exist_ok=True)
    (builtin_app / "pyproject.toml").write_text("[project]\nname='flight-project'\n", encoding="utf-8")
    (builtin_app / "src" / "flight" / "flight.py").write_text("class Flight:\n    pass\n", encoding="utf-8")
    (builtin_app / "src" / "flight_worker" / "flight_worker.py").write_text(
        "class BaseWorker:\n    pass\n\nclass FlightWorker(BaseWorker):\n    pass\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("HOME", str(fake_home))
    AgiEnv.reset()

    env = AgiEnv(active_app=builtin_app, verbose=0)

    assert env.active_app == builtin_app.resolve()
    assert env.manager_path == (builtin_app / "src" / "flight" / "flight.py").resolve()
    assert env.worker_path == (builtin_app / "src" / "flight_worker" / "flight_worker.py").resolve()


def test_run_nonzero_command_does_not_log_traceback_for_runtime_error(tmp_path: Path, monkeypatch):
    mock_logger = mock.Mock()
    monkeypatch.setattr(AgiEnv, "logger", mock_logger)

    cmd = f"{shlex.quote(sys.executable)} -c \"import sys; sys.exit(3)\""
    with pytest.raises(RuntimeError, match="Command failed with exit code 3"):
        asyncio.run(AgiEnv.run(cmd, tmp_path))

    assert any(
        call.args
        and call.args[0] == "Command failed with exit code %s: %s"
        and call.args[1] == 3
        for call in mock_logger.error.call_args_list
    )
    error_messages = [
        " ".join(str(part) for part in call.args)
        for call in mock_logger.error.call_args_list
    ]
    assert not any("Traceback (most recent call last)" in msg for msg in error_messages)


def test_run_unexpected_exception_logs_traceback(tmp_path: Path, monkeypatch):
    mock_logger = mock.Mock()
    monkeypatch.setattr(AgiEnv, "logger", mock_logger)

    async def _raise_value_error(*args, **kwargs):
        raise ValueError("broken exec")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _raise_value_error)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", _raise_value_error)

    cmd = f"{shlex.quote(sys.executable)} -c \"print('hello')\""
    with pytest.raises(RuntimeError, match="Command execution error: broken exec"):
        asyncio.run(AgiEnv.run(cmd, tmp_path))


def test_parse_level_recognizes_common_patterns():
    assert agi_env_module.parse_level("12:34:56 INFO booting", logging.WARNING) == logging.INFO
    assert agi_env_module.parse_level("level=error details", logging.INFO) == logging.ERROR
    assert agi_env_module.parse_level("level=debug details", logging.INFO) == logging.DEBUG
    assert agi_env_module.parse_level("plain text", logging.WARNING) == logging.WARNING


def test_strip_time_level_prefix_and_packaging_detection():
    assert agi_env_module.strip_time_level_prefix("12:34:56 INFO started") == "started"
    assert agi_env_module.strip_time_level_prefix("12:34:56,123 WARNING: be careful") == "be careful"
    assert agi_env_module.is_packaging_cmd("uv pip install agilab") is True
    assert agi_env_module.is_packaging_cmd("python -m pytest") is False


def test_ensure_dir_logs_only_on_first_creation(tmp_path: Path, monkeypatch):
    target = tmp_path / "new-dir"
    mock_logger = mock.Mock()
    monkeypatch.setattr("agi_env.agi_env.logger", mock_logger)

    created = agi_env_module._ensure_dir(target)
    reused = agi_env_module._ensure_dir(target)

    assert created == target
    assert reused == target
    assert target.is_dir()
    mkdir_logs = [
        call.args[0]
        for call in mock_logger.info.call_args_list
        if call.args and isinstance(call.args[0], str)
    ]
    assert mkdir_logs == [f"mkdir {target}"]


def test_select_hook_prefers_local_candidate_and_fallback(tmp_path: Path, monkeypatch):
    local_hook = tmp_path / "pre_install.py"
    local_hook.write_text("print('local')\n", encoding="utf-8")

    selected, shared = agi_env_module._select_hook(local_hook, "pre_install.py", "pre_install")
    assert selected == local_hook
    assert shared is False

    fallback = tmp_path / "shared.py"
    fallback.write_text("print('shared')\n", encoding="utf-8")
    missing = tmp_path / "missing.py"
    monkeypatch.setattr("agi_env.agi_env._resolve_worker_hook", lambda _name: fallback)
    selected, shared = agi_env_module._select_hook(missing, "pre_install.py", "pre_install")
    assert selected == fallback
    assert shared is True


def test_select_hook_raises_when_no_candidate_found(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("agi_env.agi_env._resolve_worker_hook", lambda _name: None)
    missing = tmp_path / "missing.py"

    with pytest.raises(FileNotFoundError, match="Unable to resolve pre_install script"):
        agi_env_module._select_hook(missing, "pre_install.py", "pre_install")
