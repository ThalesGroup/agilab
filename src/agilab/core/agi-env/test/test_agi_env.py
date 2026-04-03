import asyncio
import ast
import getpass
import logging
import shlex
import shutil
import sys
from io import BytesIO
from types import SimpleNamespace

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


def test_app_settings_file_points_to_user_workspace_and_is_seeded(tmp_path: Path, monkeypatch):
    agipath = AgiEnv.locate_agilab_installation(verbose=False)
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    share_dir = fake_home / ".local" / "share" / "agilab"
    share_dir.mkdir(parents=True, exist_ok=True)
    (share_dir / ".agilab-path").write_text(str(agipath) + "\n")
    monkeypatch.setenv("HOME", str(fake_home))

    AgiEnv.reset()
    env = AgiEnv(apps_path=agipath / "apps", app="mycode_project", verbose=1)

    expected_workspace = fake_home / ".agilab" / "apps" / "mycode_project" / "app_settings.toml"
    assert env.app_settings_file == expected_workspace
    assert env.app_settings_file.exists()
    assert env.app_settings_source_file.exists()
    assert env.app_settings_file.read_text(encoding="utf-8") == env.app_settings_source_file.read_text(
        encoding="utf-8"
    )


def test_user_workspace_app_settings_override_source_cluster_toggle(tmp_path: Path, monkeypatch):
    """Persisted per-user settings must win over versioned source defaults."""

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
    workspace_settings = fake_home / ".agilab" / "apps" / "mycode_project" / "app_settings.toml"
    workspace_settings.parent.mkdir(parents=True, exist_ok=True)
    workspace_settings.write_text("[cluster]\ncluster_enabled = false\n", encoding="utf-8")

    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("AGI_CLUSTER_SHARE", raising=False)
    monkeypatch.delenv("AGI_SHARE_DIR", raising=False)

    fake_apps = tmp_path / "apps"
    fake_app = fake_apps / "mycode_project"
    (fake_app / "src" / "mycode").mkdir(parents=True, exist_ok=True)
    (fake_app / "src" / "app_settings.toml").write_text("[cluster]\ncluster_enabled = true\n", encoding="utf-8")

    AgiEnv.reset()
    AgiEnv._share_mount_warning_keys.clear()

    mock_logger = mock.Mock()
    with mock.patch.object(AgiLogger, "configure", return_value=mock_logger), mock.patch.object(
        AgiEnv, "_init_apps", lambda self: None
    ):
        env = AgiEnv(apps_path=fake_apps, app="mycode_project", verbose=1)

    assert env.agi_share_path == env.AGI_LOCAL_SHARE


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


def test_missing_flattened_active_app_falls_back_to_builtin_copy(tmp_path: Path, monkeypatch):
    """When a stale flattened app root exists, prefer the valid builtin copy."""

    agipath = AgiEnv.locate_agilab_installation(verbose=False)
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    share_root = fake_home / ".local" / "share" / "agilab"
    share_root.mkdir(parents=True, exist_ok=True)
    (share_root / ".agilab-path").write_text(str(agipath) + "\n", encoding="utf-8")

    wrong_app = tmp_path / "apps" / "flight_project"
    wrong_app.mkdir(parents=True, exist_ok=True)
    (wrong_app / "pyproject.toml").write_text("[project]\nname='wrong-flight'\n", encoding="utf-8")

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

    env = AgiEnv(active_app=wrong_app, verbose=0)

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


def test_clean_envar_value_handles_blank_values_and_process_fallback(monkeypatch):
    monkeypatch.setenv("AGI_DEMO", " from-process ")

    assert agi_env_module._clean_envar_value({"AGI_DEMO": " value "}, "AGI_DEMO") == "value"
    assert agi_env_module._clean_envar_value({"AGI_DEMO": "   "}, "AGI_DEMO") is None
    assert (
        agi_env_module._clean_envar_value(
            {"AGI_DEMO": ""},
            "AGI_DEMO",
            fallback_to_process=True,
        )
        == "from-process"
    )


def test_load_dotenv_values_discards_blank_assignments(tmp_path: Path):
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "OPENAI_MODEL=\n"
        "APP_DEFAULT=   \n"
        "AGI_LOG_DIR=/tmp/logs\n"
        "TABLE_MAX_ROWS=1000\n",
        encoding="utf-8",
    )

    values = agi_env_module._load_dotenv_values(dotenv_path)

    assert values == {
        "AGI_LOG_DIR": "/tmp/logs",
        "TABLE_MAX_ROWS": "1000",
    }


def test_normalize_path_and_windows_drive_fix(monkeypatch):
    assert agi_env_module.normalize_path("relative/path") == "relative/path"
    assert agi_env_module.normalize_path("") == "."

    monkeypatch.setattr(agi_env_module.os, "name", "nt", raising=False)
    assert agi_env_module._fix_windows_drive(r"C:Users\\agi") == r"C:\Users\\agi"
    assert agi_env_module._fix_windows_drive(r"C:\\Users\\agi") == r"C:\\Users\\agi"


def test_agienv_meta_prefers_instance_attributes_and_class_fallback():
    class Dummy(metaclass=agi_env_module._AgiEnvMeta):
        _instance = None
        _lock = None
        class_value = "class"

        @classmethod
        def current(cls):
            return cls._instance

        @classmethod
        def reset(cls):
            cls._instance = None

    Dummy._instance = type("Instance", (), {"dynamic_value": "instance"})()

    assert Dummy.dynamic_value == "instance"
    assert Dummy.class_value == "class"
    with pytest.raises(AttributeError):
        _ = Dummy.missing_value


def test_content_renamer_updates_ast_nodes(monkeypatch):
    mock_logger = mock.Mock()
    monkeypatch.setattr(AgiEnv, "logger", mock_logger)

    source = ast.parse(
        "import foo.mod\n"
        "from foo.pkg import Foo, foo_helper\n"
        "class Foo:\n"
        "    def foo(self, foo_arg):\n"
        "        global foo\n"
        "        for foo in [foo_arg]:\n"
        "            self.foo = foo\n"
        "            return foo\n"
    )
    rename_map = {
        "foo": "bar",
        "Foo": "Baz",
        "foo_helper": "bar_helper",
        "foo_arg": "bar_arg",
    }

    transformed = agi_env_module.ContentRenamer(rename_map).visit(source)
    rendered = ast.unparse(transformed)

    assert "import bar.mod" in rendered
    assert "from bar.pkg import Baz, bar_helper" in rendered
    assert "class Baz" in rendered
    assert "def bar(self, bar_arg)" in rendered
    assert "global bar" in rendered
    assert "for bar in [bar_arg]" in rendered
    assert "self.bar = bar" in rendered

    nonlocal_node = ast.Nonlocal(names=["foo", "other"])
    updated_nonlocal = agi_env_module.ContentRenamer(rename_map).visit_nonlocal(nonlocal_node)
    assert updated_nonlocal.names == ["bar", "other"]
    assert mock_logger.info.call_count > 0


def test_is_relative_to_returns_expected_result(tmp_path: Path):
    parent = tmp_path / "parent"
    child = parent / "child"
    child.mkdir(parents=True)

    assert agi_env_module._is_relative_to(child, parent) is True
    assert agi_env_module._is_relative_to(tmp_path / "other", parent) is False


def test_app_settings_aliases_and_candidate_paths(tmp_path: Path):
    assert agi_env_module.AgiEnv._app_settings_aliases("demo_project") == {"demo_project", "demo_worker"}
    assert agi_env_module.AgiEnv._app_settings_aliases("demo_worker") == {"demo_worker", "demo_project"}
    assert agi_env_module.AgiEnv._app_settings_aliases("demo_project_worker") == {
        "demo_project",
        "demo_project_worker",
    }
    assert agi_env_module.AgiEnv._app_settings_aliases(None) == set()

    src_dir = tmp_path / "demo_project" / "src"
    src_dir.mkdir(parents=True)
    src_settings = src_dir / "app_settings.toml"
    src_settings.write_text("[cluster]\ncluster_enabled = false\n", encoding="utf-8")

    assert agi_env_module.AgiEnv._candidate_app_settings_path(src_dir) == src_settings
    assert agi_env_module.AgiEnv._candidate_app_settings_path(src_dir.parent) == src_settings
    assert agi_env_module.AgiEnv._candidate_app_settings_path(object()) is None


def test_find_source_and_user_app_settings_cover_workspace_seed_paths(tmp_path: Path):
    env = object.__new__(AgiEnv)
    env.app = "demo_project"
    env.home_abs = tmp_path / "home"
    env.home_abs.mkdir()
    env.resources_path = env.home_abs / ".agilab"
    env.resources_path.mkdir(parents=True)
    env.envars = {}
    env.apps_repository_root = None
    env._get_apps_repository_root = lambda: None

    active_app = tmp_path / "apps" / "demo_project"
    active_src = active_app / "src"
    active_src.mkdir(parents=True)
    source_settings = active_src / "app_settings.toml"
    source_settings.write_text("[cluster]\ncluster_enabled = true\n", encoding="utf-8")

    env.active_app = active_app
    env.app_src = active_src
    env.apps_path = tmp_path / "apps"
    env.builtin_apps_path = None

    found = env.find_source_app_settings_file("demo_worker")
    assert found == source_settings

    workspace_file = env.resolve_user_app_settings_file("demo_project")
    assert workspace_file.exists()
    assert workspace_file.read_text(encoding="utf-8") == source_settings.read_text(encoding="utf-8")

    blank_env = object.__new__(AgiEnv)
    blank_env.app = "blank_project"
    blank_env.target = "blank_project"
    blank_env.resources_path = tmp_path / "resources"
    blank_env.resources_path.mkdir(parents=True)
    blank_env.find_source_app_settings_file = lambda _app_name=None: None
    touched = blank_env.resolve_user_app_settings_file(ensure_exists=True)
    assert touched.exists()
    assert touched.read_text(encoding="utf-8") == ""
    unresolved = blank_env.resolve_user_app_settings_file(ensure_exists=False)
    assert unresolved == blank_env.resources_path / "apps" / "blank_project" / "app_settings.toml"


def test_get_import_mapping_and_base_info_support_ast_nodes(monkeypatch):
    env = object.__new__(AgiEnv)

    source = (
        "import pkg.module as mod\n"
        "from demo.worker import DemoWorker\n"
        "from another.pkg import helper\n"
    )
    mapping = env.get_import_mapping(source)
    assert mapping["mod"] == "pkg.module"
    assert mapping["DemoWorker"] == "demo.worker"
    assert mapping["helper"] == "another.pkg"

    name_base = ast.parse("class Child(Base):\n    pass\n").body[0].bases[0]
    attr_base = ast.parse("class Child(mod.DemoWorker):\n    pass\n").body[0].bases[0]
    assert env.extract_base_info(name_base, mapping) == ("Base", None)
    assert env.extract_base_info(attr_base, mapping) == ("DemoWorker", "pkg.module")
    assert env.get_full_attribute_name(attr_base) == "mod.DemoWorker"

    mock_logger = mock.Mock()
    monkeypatch.setattr(AgiEnv, "logger", mock_logger)
    with pytest.raises(SyntaxError):
        env.get_import_mapping("def broken(:\n")
    assert mock_logger.error.called


def test_read_gitignore_and_check_internet_cover_success_and_failure(tmp_path: Path, monkeypatch):
    env = object.__new__(AgiEnv)
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("*.pyc\nbuild/\n", encoding="utf-8")

    spec = env.read_gitignore(gitignore)
    assert spec.match_file("module.pyc") is True
    assert spec.match_file("build/output.txt") is True
    assert spec.match_file("README.md") is False
    assert env.is_valid_ip("192.168.0.10") is True
    assert env.is_valid_ip("999.1.1.1") is False

    mock_logger = mock.Mock()
    monkeypatch.setattr(AgiEnv, "logger", mock_logger)

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(agi_env_module.urllib.request, "urlopen", lambda *_a, **_k: _Resp())
    assert env.check_internet() is True

    def _raise(*_args, **_kwargs):
        raise OSError("offline")

    monkeypatch.setattr(agi_env_module.urllib.request, "urlopen", _raise)
    assert env.check_internet() is False
    assert mock_logger.error.called


def test_unzip_data_handles_missing_archive_existing_dataset_and_force_refresh(tmp_path: Path, monkeypatch):
    env = object.__new__(AgiEnv)
    env.app_data_rel = "demo"
    env.agi_share_path_abs = tmp_path / "share"
    env.agi_share_path_abs.mkdir(parents=True)
    env.user = Path.home().name
    env.home_abs = Path.home()

    mock_logger = mock.Mock()
    monkeypatch.setattr(AgiEnv, "logger", mock_logger)
    monkeypatch.setattr(AgiEnv, "verbose", 2, raising=False)

    missing_archive = tmp_path / "missing.7z"
    env.unzip_data(missing_archive, "dataset/demo")
    assert mock_logger.warning.called

    dest = env.agi_share_path_abs / "dataset" / "demo"
    dataset = dest / "dataset"
    dataset.mkdir(parents=True)
    archive = tmp_path / "demo.7z"
    archive.write_bytes(b"7z")

    env.unzip_data(archive, "dataset/demo")
    stamp = dataset / ".agilab_dataset_stamp"
    assert stamp.exists()
    assert stamp.read_text(encoding="utf-8") == str(archive)

    removed = []

    original_rmtree = shutil.rmtree

    def _fake_rmtree(path, onerror=None):
        removed.append(Path(path))
        original_rmtree(path)

    class _FakeSevenZip:
        def __init__(self, path, mode="r"):
            assert Path(path) == archive
            assert mode == "r"

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extractall(self, path):
            target = Path(path) / "dataset"
            target.mkdir(parents=True, exist_ok=True)
            (target / "payload.txt").write_text("ok", encoding="utf-8")

    monkeypatch.setattr(agi_env_module.shutil, "rmtree", _fake_rmtree)
    monkeypatch.setattr(agi_env_module.py7zr, "SevenZipFile", _FakeSevenZip)

    env.unzip_data(archive, "dataset/demo", force_extract=True)
    assert removed == [dataset]
    assert (dataset / "payload.txt").exists()


def test_clone_project_renames_sources_respects_gitignore_and_copies_data(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    apps_path = tmp_path / "apps"
    source = apps_path / "flight_project"
    (source / "src" / "flight").mkdir(parents=True)
    (source / "src" / "flight_worker").mkdir(parents=True)
    (source / ".venv").mkdir(parents=True)
    (source / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (source / "README.md").write_text("flight_project uses Flight and flight_worker.\n", encoding="utf-8")
    (source / "ignored.txt").write_text("skip me\n", encoding="utf-8")
    (source / "archive.7z").write_bytes(b"7z")
    (source / "src" / "flight" / "flight.py").write_text(
        "class Flight:\n    pass\n",
        encoding="utf-8",
    )
    (source / "src" / "flight_worker" / "flight_worker.py").write_text(
        "class FlightWorker:\n    pass\n",
        encoding="utf-8",
    )
    (home / "data" / "flight").mkdir(parents=True)
    (home / "data" / "flight" / "sample.csv").write_text("x\n1\n", encoding="utf-8")

    env = object.__new__(AgiEnv)
    env.apps_path = apps_path
    env.home_abs = home
    env.projects = []
    monkeypatch.setattr(AgiEnv, "logger", mock.Mock())

    env.clone_project(Path("flight_project"), Path("demo_project"))

    cloned = apps_path / "demo_project"
    assert cloned.exists()
    assert not (cloned / "ignored.txt").exists()
    assert (cloned / ".venv").is_symlink()
    assert (cloned / "archive.7z").read_bytes() == b"7z"
    assert (cloned / "README.md").read_text(encoding="utf-8") == "demo_project uses Demo and demo_worker.\n"
    assert (cloned / "src" / "demo" / "demo.py").exists()
    assert (cloned / "src" / "demo_worker" / "demo_worker.py").exists()
    assert "class Demo" in (cloned / "src" / "demo" / "demo.py").read_text(encoding="utf-8")
    assert "class DemoWorker" in (cloned / "src" / "demo_worker" / "demo_worker.py").read_text(encoding="utf-8")
    assert (home / "data" / "demo" / "sample.csv").exists()
    assert Path("demo_project") in env.projects


def test_clone_project_noops_when_source_missing_or_destination_exists(tmp_path: Path, monkeypatch):
    env = object.__new__(AgiEnv)
    env.apps_path = tmp_path / "apps"
    env.apps_path.mkdir()
    env.home_abs = tmp_path / "home"
    env.home_abs.mkdir()
    env.projects = []
    monkeypatch.setattr(AgiEnv, "logger", mock.Mock())

    env.clone_project(Path("missing_project"), Path("demo_project"))
    assert not (env.apps_path / "demo_project").exists()

    existing = env.apps_path / "flight_project"
    existing.mkdir()
    dest = env.apps_path / "demo_project"
    dest.mkdir()
    env.clone_project(Path("flight_project"), Path("demo_project"))
    assert dest.exists()


def test_run_supports_export_only_and_fire_and_forget(tmp_path: Path, monkeypatch):
    mock_logger = mock.Mock()
    monkeypatch.setattr(AgiEnv, "logger", mock_logger)
    monkeypatch.setattr(AgiEnv, "verbose", 1, raising=False)

    noop = asyncio.run(AgiEnv.run('export PATH="~/.local/bin:$PATH";', tmp_path))
    assert noop == ""

    created = {}

    async def _fake_shell(*args, **kwargs):
        created["cmd"] = args[0]
        return SimpleNamespace()

    monkeypatch.setattr(asyncio, "create_subprocess_shell", _fake_shell)
    monkeypatch.setattr(asyncio, "create_task", lambda coro: created.setdefault("coro", coro))
    result = asyncio.run(AgiEnv.run("echo hi", tmp_path, wait=False))
    assert result == 0
    assert created["coro"] is not None
    created["coro"].close()


def test_run_async_and_run_bg_cover_success_and_nonzero_paths(tmp_path: Path, monkeypatch):
    mock_logger = mock.Mock()
    monkeypatch.setattr(AgiEnv, "logger", mock_logger)

    success_cmd = f"{shlex.quote(sys.executable)} -c \"import sys; print('out'); print('err', file=sys.stderr)\""
    last_line = asyncio.run(AgiEnv.run_async(success_cmd, venv=tmp_path, cwd=tmp_path, timeout=10))
    assert last_line == "err"

    fail_cmd = f"{shlex.quote(sys.executable)} -c \"import sys; sys.exit(4)\""
    with pytest.raises(RuntimeError, match="exit code 4"):
        asyncio.run(AgiEnv.run_async(fail_cmd, venv=tmp_path, cwd=tmp_path, timeout=10))

    streamed: list[str] = []
    stdout, stderr = asyncio.run(
        AgiEnv._run_bg(
            success_cmd,
            cwd=tmp_path,
            venv=tmp_path,
            timeout=10,
            env_override={"AGI_DEMO_FLAG": "1"},
            remove_env={"PYTHONHOME"},
            log_callback=lambda message, **_kwargs: streamed.append(message),
        )
    )
    assert "out" in streamed
    assert "err" in streamed

    with pytest.raises(RuntimeError, match="exit 4"):
        asyncio.run(AgiEnv._run_bg(fail_cmd, cwd=tmp_path, venv=tmp_path, timeout=10))


def test_run_agi_handles_missing_snippet_missing_venv_and_install_snippet(tmp_path: Path, monkeypatch):
    env = object.__new__(AgiEnv)
    env.runenv = tmp_path / "runenv"
    env.target = "demo_project"

    logs: list[str] = []
    result = asyncio.run(env.run_agi("print('hello')", log_callback=logs.append, venv=tmp_path))
    assert result == ("", "")
    assert logs == ["Could not determine snippet name from code."]

    logs.clear()
    code = "async def main():\n    await Agi.demo_run()\n"
    stdout, stderr = asyncio.run(env.run_agi(code, log_callback=logs.append, venv=tmp_path))
    assert stdout == ""
    assert "Run INSTALL first" in stderr

    project_root = tmp_path / "install_project"
    project_root.mkdir()
    captured = {}

    async def _fake_run_bg(cmd, cwd=None, venv=None, remove_env=None, log_callback=None, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["venv"] = venv
        captured["remove_env"] = remove_env
        return "done", ""

    monkeypatch.setattr(AgiEnv, "_run_bg", staticmethod(_fake_run_bg))
    logs.clear()
    install_code = "async def main():\n    await Agi.demo_install()\n"
    result = asyncio.run(env.run_agi(install_code, log_callback=logs.append, venv=project_root))
    assert result == ("done", "")
    assert Path(captured["cwd"]) == project_root
    assert Path(captured["venv"]) == Path(sys.prefix)
    assert captured["remove_env"] == {"PYTHONPATH", "PYTHONHOME"}
    assert logs[-1] == "Process finished"
