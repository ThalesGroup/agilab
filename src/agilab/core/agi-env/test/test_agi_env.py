import asyncio
import ast
import getpass
import logging
import os
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


def test_change_app_rejects_empty_name_and_missing_apps_path(monkeypatch):
    env = object.__new__(AgiEnv)
    env.app = "flight_project"
    env.apps_path = None

    with pytest.raises(ValueError, match="app name must be non-empty"):
        env.change_app("")

    monkeypatch.setattr(AgiEnv, "apps_path", None, raising=False)
    env.app = Path("")
    with pytest.raises(RuntimeError, match="apps_path is not configured"):
        env.change_app("demo_project")


def test_change_app_cleans_stale_destination_after_init_failure(tmp_path: Path):
    apps_root = tmp_path / "apps"
    apps_root.mkdir()
    stale_target = apps_root / "demo_project"
    stale_target.mkdir()

    env = object.__new__(AgiEnv)
    env.app = str(apps_root / "flight_project")

    def _failing_init(self, *args, **kwargs):
        raise RuntimeError("boom")

    with mock.patch.object(AgiEnv, "__init__", _failing_init, create=True):
        with pytest.raises(RuntimeError, match="boom"):
            env.change_app("demo_project")

    assert not stale_target.exists()

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


def test_init_envars_app_honours_relative_mlflow_and_pages_overrides(tmp_path: Path, monkeypatch):
    env = object.__new__(AgiEnv)
    env.home_abs = tmp_path / "home"
    env.home_abs.mkdir()
    env.target = "sb3_trainer"
    env.agilab_pck = tmp_path / "pkg"
    env.agilab_pck.mkdir()
    env.read_agilab_path = lambda: None
    monkeypatch.setattr(AgiEnv, "logger", mock.Mock(), raising=False)

    env.init_envars_app(
        {
            "MLFLOW_TRACKING_DIR": "mlruns",
            "AGI_PAGES_DIR": str(tmp_path / "custom-pages"),
        }
    )

    assert env.MLFLOW_TRACKING_DIR == env.home_abs / "mlruns"
    assert env.AGILAB_PAGES_ABS == tmp_path / "custom-pages"


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

    app_name = "demo_project"
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
    fake_app = fake_apps / app_name
    fake_app_src = fake_app / "src" / "demo"
    fake_app_src.mkdir(parents=True, exist_ok=True)
    (fake_app / "src" / "app_settings.toml").write_text(
        "[cluster]\ncluster_enabled = true\n"
    )
    workspace_settings = fake_home / ".agilab" / "apps" / app_name / "app_settings.toml"
    workspace_settings.parent.mkdir(parents=True, exist_ok=True)
    workspace_settings.write_text("[cluster]\ncluster_enabled = true\n")

    monkeypatch.setenv("HOME", str(fake_home))

    AgiEnv.reset()
    AgiEnv._share_mount_warning_keys.clear()

    mock_logger = mock.Mock()
    with mock.patch.object(AgiLogger, "configure", return_value=mock_logger):
        with pytest.raises(RuntimeError, match="Cluster mode requires AGI_CLUSTER_SHARE"):
            AgiEnv(apps_path=fake_apps, app=app_name, verbose=1)


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

    app_name = "demo_project"
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
    fake_app = fake_apps / app_name
    fake_app_src = fake_app / "src" / "demo"
    fake_app_src.mkdir(parents=True, exist_ok=True)
    (fake_app / "src" / "app_settings.toml").write_text(
        "[cluster]\ncluster_enabled = true\n"
    )
    workspace_settings = fake_home / ".agilab" / "apps" / app_name / "app_settings.toml"
    workspace_settings.parent.mkdir(parents=True, exist_ok=True)
    workspace_settings.write_text("[cluster]\ncluster_enabled = true\n")

    AgiEnv.reset()

    with pytest.raises(RuntimeError, match="AGI_CLUSTER_SHARE to be distinct from AGI_LOCAL_SHARE"):
        AgiEnv(apps_path=fake_apps, app=app_name, verbose=1)


def test_cluster_enabled_from_apps_repository_when_app_src_invalid(tmp_path: Path, monkeypatch):
    """Read cluster toggle from APPS_REPOSITORY when active app source is invalid."""

    app_name = "demo_project"
    agipath = AgiEnv.locate_agilab_installation(verbose=False)
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    share_root = fake_home / ".local" / "share" / "agilab"
    share_root.mkdir(parents=True, exist_ok=True)
    (share_root / ".agilab-path").write_text(str(agipath) + "\n")

    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("APPS_REPOSITORY", str(tmp_path / "repo"))

    app_repo = tmp_path / "repo" / "src" / "agilab" / "apps" / app_name / "src"
    app_repo.mkdir(parents=True, exist_ok=True)
    (app_repo / "app_settings.toml").write_text("[cluster]\ncluster_enabled = true\n")

    cluster_share = fake_home / "cluster_share"
    cluster_share.mkdir()
    monkeypatch.setenv("AGI_CLUSTER_SHARE", str(cluster_share))

    fake_apps = tmp_path / "apps"
    bad_app = fake_apps / app_name
    bad_app.mkdir(parents=True, exist_ok=True)
    (bad_app / "src").write_text("broken")

    AgiEnv.reset()
    AgiEnv._share_mount_warning_keys.clear()

    mock_logger = mock.Mock()
    with mock.patch.object(AgiLogger, "configure", return_value=mock_logger), mock.patch.object(
        AgiEnv, "_init_apps", lambda self: None
    ), mock.patch.object(AgiEnv, "_ensure_repository_app_link", lambda self: False):
        env = AgiEnv(apps_path=fake_apps, app=app_name, verbose=1)

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
    (builtin_app / "uv_config.toml").write_text("[tool.uv]\n", encoding="utf-8")
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
    assert env.uvproject == (builtin_app / "uv_config.toml").resolve()


def test_explicit_apps_root_prefers_builtin_copy_over_flattened_stub(tmp_path: Path, monkeypatch):
    """When apps_path points at the apps root, prefer apps/builtin/<app> over a stale flat stub."""

    agipath = AgiEnv.locate_agilab_installation(verbose=False)
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    share_root = fake_home / ".local" / "share" / "agilab"
    share_root.mkdir(parents=True, exist_ok=True)
    (share_root / ".agilab-path").write_text(str(agipath) + "\n", encoding="utf-8")

    apps_root = tmp_path / "apps"
    flat_app = apps_root / "flight_project"
    (flat_app / "src").mkdir(parents=True, exist_ok=True)
    (flat_app / "pyproject.toml").write_text("[project]\nname='wrong-flight'\n", encoding="utf-8")

    builtin_app = apps_root / "builtin" / "flight_project"
    (builtin_app / "src" / "flight").mkdir(parents=True, exist_ok=True)
    (builtin_app / "src" / "flight_worker").mkdir(parents=True, exist_ok=True)
    (builtin_app / "pyproject.toml").write_text("[project]\nname='flight-project'\n", encoding="utf-8")
    (builtin_app / "uv_config.toml").write_text("[tool.uv]\n", encoding="utf-8")
    (builtin_app / "src" / "flight" / "flight.py").write_text("class Flight:\n    pass\n", encoding="utf-8")
    (builtin_app / "src" / "flight_worker" / "flight_worker.py").write_text(
        "class BaseWorker:\n    pass\n\nclass FlightWorker(BaseWorker):\n    pass\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("HOME", str(fake_home))
    AgiEnv.reset()

    env = AgiEnv(apps_path=apps_root, active_app=flat_app, verbose=0)

    assert env.active_app == builtin_app.resolve()
    assert env.worker_path == (builtin_app / "src" / "flight_worker" / "flight_worker.py").resolve()
    assert env.uvproject == (builtin_app / "uv_config.toml").resolve()


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


def test_run_nonzero_command_prefers_last_subprocess_line_in_runtime_error(tmp_path: Path, monkeypatch):
    mock_logger = mock.Mock()
    monkeypatch.setattr(AgiEnv, "logger", mock_logger)

    cmd = (
        f"{shlex.quote(sys.executable)} -c "
        "\"import sys; print('RuntimeError: concise failure', file=sys.stderr); sys.exit(5)\""
    )

    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(AgiEnv.run(cmd, tmp_path))

    assert str(exc_info.value) == "Command failed with exit code 5: concise failure"
    assert "sys.exit(5)" not in str(exc_info.value)


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


def test_clean_envar_value_handles_mapping_errors_and_dotenv_none(monkeypatch, tmp_path):
    class BadMapping(dict):
        def get(self, key, default=None):
            raise RuntimeError("boom")

    monkeypatch.setenv("AGI_DEMO", " process-value ")
    assert (
        agi_env_module._clean_envar_value(
            BadMapping(),
            "AGI_DEMO",
            fallback_to_process=True,
        )
        == "process-value"
    )

    monkeypatch.setattr(
        agi_env_module,
        "dotenv_values",
        lambda **_kwargs: {"A": " ", "B": None, "C": " 1 "},
    )
    assert agi_env_module._load_dotenv_values(tmp_path / ".env") == {"C": " 1 "}


def test_resolve_worker_hook_prefers_installed_spec_location_and_resource_cache(tmp_path, monkeypatch):
    installed_dir = tmp_path / "installed" / "agi_dispatcher"
    installed_dir.mkdir(parents=True)
    installed_hook = installed_dir / "pre_install.py"
    installed_hook.write_text("print('installed')\n", encoding="utf-8")

    agi_env_module._resolve_worker_hook.cache_clear()
    monkeypatch.setattr(
        agi_env_module.importlib.util,
        "find_spec",
        lambda _name: SimpleNamespace(
            submodule_search_locations=[str(installed_dir)],
            origin=str(installed_dir / "__init__.py"),
        ),
    )
    assert agi_env_module._resolve_worker_hook("pre_install.py") == installed_hook

    resource_root = tmp_path / "resources"
    resource_root.mkdir()
    resource_hook = resource_root / "post_install.py"
    resource_hook.write_text("print('resource')\n", encoding="utf-8")
    cache_parent = tmp_path / "cache-parent"
    cache_parent.mkdir()

    agi_env_module._resolve_worker_hook.cache_clear()
    monkeypatch.setattr(
        agi_env_module,
        "__file__",
        str(tmp_path / "sandbox" / "nested" / "agi_env.py"),
    )
    monkeypatch.setattr(agi_env_module.importlib.util, "find_spec", lambda _name: None)
    monkeypatch.setattr(agi_env_module.importlib_resources, "files", lambda _name: resource_root)
    monkeypatch.setattr(agi_env_module.tempfile, "gettempdir", lambda: str(cache_parent))

    resolved = agi_env_module._resolve_worker_hook("post_install.py")

    assert resolved == cache_parent / "agi_node_hooks" / "post_install.py"
    assert resolved.read_text(encoding="utf-8") == "print('resource')\n"


def test_normalize_path_and_windows_drive_fix(monkeypatch):
    assert agi_env_module.normalize_path("relative/path") == "relative/path"
    assert agi_env_module.normalize_path("") == "."

    monkeypatch.setattr(agi_env_module.os, "name", "nt", raising=False)
    assert agi_env_module._fix_windows_drive(r"C:Users\\agi") == r"C:\Users\\agi"
    assert agi_env_module._fix_windows_drive(r"C:\\Users\\agi") == r"C:\\Users\\agi"


def test_normalize_path_windows_resolve_fallback_and_worker_hook_none(monkeypatch, tmp_path):
    original_os_name = os.name
    original_resolve = Path.resolve
    monkeypatch.setattr(agi_env_module.os, "name", "nt", raising=False)

    def _patched_resolve(self, *args, **kwargs):
        if self == Path("demo"):
            raise RuntimeError("boom")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", _patched_resolve, raising=False)
    assert agi_env_module.normalize_path("demo").endswith("demo")
    monkeypatch.setattr(agi_env_module.os, "name", original_os_name, raising=False)
    monkeypatch.setattr(Path, "resolve", original_resolve, raising=False)

    agi_env_module._resolve_worker_hook.cache_clear()
    monkeypatch.setattr(
        agi_env_module,
        "__file__",
        str(tmp_path / "sandbox" / "nested" / "agi_env.py"),
    )
    monkeypatch.setattr(
        agi_env_module.importlib.util,
        "find_spec",
        lambda _name: (_ for _ in ()).throw(ModuleNotFoundError("missing")),
    )
    monkeypatch.setattr(
        agi_env_module.importlib_resources,
        "files",
        lambda _name: (_ for _ in ()).throw(AttributeError("no resources")),
    )
    with mock.patch.object(agi_env_module.Path, "exists", lambda self: False):
        assert agi_env_module._resolve_worker_hook("pre_install.py") is None


def test_read_agilab_path_logs_invalid_marker_and_locate_agilab_installation_spec(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    share_dir = fake_home / ".local" / "share" / "agilab"
    share_dir.mkdir(parents=True)
    (share_dir / ".agilab-path").write_text(str(tmp_path / "missing-install"), encoding="utf-8")

    mock_logger = mock.Mock()
    monkeypatch.setattr(AgiEnv, "logger", mock_logger, raising=False)
    monkeypatch.setattr(agi_env_module.Path, "home", staticmethod(lambda: fake_home))

    assert AgiEnv.read_agilab_path() is None
    assert mock_logger.error.called

    installed_root = tmp_path / "site-packages" / "agilab"
    installed_root.mkdir(parents=True)
    (installed_root / "apps").mkdir()
    init_file = installed_root / "__init__.py"
    init_file.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        agi_env_module.importlib.util,
        "find_spec",
        lambda _name: SimpleNamespace(origin=str(init_file)),
    )

    assert AgiEnv.locate_agilab_installation() == installed_root.resolve()


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


def test_agienv_current_and_meta_setattr_cover_instance_and_class_paths():
    AgiEnv.reset()
    with pytest.raises(RuntimeError, match="has not been initialised"):
        AgiEnv.current()

    class Dummy(metaclass=agi_env_module._AgiEnvMeta):
        _instance = SimpleNamespace()
        _lock = None

    Dummy.dynamic_value = "instance-bound"
    assert Dummy._instance.dynamic_value == "instance-bound"

    Dummy.helper = staticmethod(lambda: "ok")
    assert Dummy.helper() == "ok"


def test_init_worker_env_flag_requires_app_and_sets_skip_repo_links(tmp_path: Path, monkeypatch):
    fake_home = tmp_path / "worker-home"
    fake_home.mkdir()
    share_root = fake_home / ".local" / "share" / "agilab"
    share_root.mkdir(parents=True, exist_ok=True)
    (fake_home / "clustershare").mkdir()
    (fake_home / "localshare").mkdir()
    (share_root / ".agilab-path").write_text(str(AgiEnv.locate_agilab_installation(verbose=False)), encoding="utf-8")
    env_dir = fake_home / ".agilab"
    env_dir.mkdir(parents=True, exist_ok=True)
    (env_dir / ".env").write_text("IS_SOURCE_ENV=false\nIS_WORKER_ENV=maybe\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(fake_home))

    AgiEnv.reset()
    with mock.patch.object(AgiEnv, "_init_apps", lambda self: None):
        with pytest.raises(ValueError, match="app is required when self.is_worker_env"):
            AgiEnv(apps_path=tmp_path / "apps", app=None, verbose=0)


def test_init_installed_env_uses_package_fallbacks_and_explicit_apps_path(tmp_path: Path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    share_root = fake_home / ".local" / "share" / "agilab"
    share_root.mkdir(parents=True, exist_ok=True)
    (share_root / ".agilab-path").write_text(str(tmp_path / "ignored"), encoding="utf-8")
    (fake_home / "clustershare").mkdir()
    (fake_home / "localshare").mkdir()
    env_dir = fake_home / ".agilab"
    env_dir.mkdir(parents=True, exist_ok=True)
    (env_dir / ".env").write_text("IS_SOURCE_ENV=no\nIS_WORKER_ENV=0\nAGI_CLUSTER_ENABLED=0\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("AGI_CLUSTER_ENABLED", "0")

    repo_apps = tmp_path / "repo-apps"
    app_root = repo_apps / "demo_project"
    (app_root / "src" / "demo").mkdir(parents=True, exist_ok=True)
    (app_root / "src" / "demo_worker").mkdir(parents=True, exist_ok=True)
    (app_root / "src" / "demo" / "demo.py").write_text("class Demo:\n    pass\n", encoding="utf-8")
    (app_root / "src" / "demo_worker" / "demo_worker.py").write_text(
        "class BaseWorker:\n    pass\n\nclass DemoWorker(BaseWorker):\n    pass\n",
        encoding="utf-8",
    )
    (app_root / "pyproject.toml").write_text("[project]\nname='demo-project'\n", encoding="utf-8")

    site_root = tmp_path / "site-packages"
    agilab_pkg = site_root / "agilab"
    agi_env_pkg = site_root / "agi_env"
    agi_node_pkg = site_root / "agi_node"
    for pkg in (agilab_pkg, agi_env_pkg, agi_node_pkg):
        pkg.mkdir(parents=True, exist_ok=True)
        (pkg / "__init__.py").write_text("", encoding="utf-8")

    def _fake_spec(name):
        mapping = {
            "agilab": SimpleNamespace(origin=str(agilab_pkg / "__init__.py")),
            "agi_env": SimpleNamespace(origin=str(agi_env_pkg / "__init__.py"), submodule_search_locations=[str(agi_env_pkg)]),
            "agi_node": SimpleNamespace(origin=str(agi_node_pkg / "__init__.py"), submodule_search_locations=[str(agi_node_pkg)]),
        }
        if name in {"agi_core", "agi_cluster", "agi_cluster.agi_distributor.cli"}:
            raise ModuleNotFoundError(name)
        return mapping.get(name)

    monkeypatch.setattr(agi_env_module.importlib.util, "find_spec", _fake_spec)
    mock_logger = mock.Mock()
    AgiEnv.reset()
    with mock.patch.object(AgiLogger, "configure", return_value=mock_logger), \
         mock.patch.object(AgiEnv, "_init_apps", lambda self: None), \
         mock.patch.object(AgiEnv, "_init_resources", lambda self, _path: None), \
         mock.patch.object(AgiEnv, "_get_apps_repository_root", lambda self: repo_apps), \
         mock.patch.object(AgiEnv, "resolve_user_app_settings_file", lambda self, ensure_exists=False: None), \
         mock.patch.object(AgiEnv, "find_source_app_settings_file", lambda self: None):
        env = AgiEnv(apps_path=repo_apps, app="demo_project", verbose=0)

    assert env.is_source_env is False
    assert env.is_worker_env is False
    assert env.apps_path == repo_apps
    assert env.apps_repository_root == repo_apps
    assert env.core_pck == agi_env_pkg.parent
    assert env.cluster_pck == env.core_pck
    assert env.cli == env.cluster_pck / "agi_distributor/cli.py"
    assert env.active_app == app_root.resolve()
    assert env.skip_repo_links is False


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


def test_init_resources_copies_seed_files_and_handles_installed_and_source_extras(tmp_path: Path, monkeypatch):
    resources_src = tmp_path / "resources-src"
    resources_src.mkdir()
    (resources_src / ".env").write_text("OPENAI_MODEL=gpt-5.4\n", encoding="utf-8")
    (resources_src / "seed.json").write_text('{"ok": true}\n', encoding="utf-8")

    installed = object.__new__(AgiEnv)
    installed.resources_path = tmp_path / "installed-home" / ".agilab"
    installed.resources_path.mkdir(parents=True)
    installed.is_source_env = False
    installed.st_resources = tmp_path / "st-resources"
    installed.st_resources.mkdir()
    (installed.st_resources / "custom_buttons.json").write_text("buttons\n", encoding="utf-8")
    (installed.st_resources / "info_bar.json").write_text("info\n", encoding="utf-8")
    (installed.st_resources / "code_editor.scss").write_text("scss\n", encoding="utf-8")

    installed._init_resources(resources_src)

    assert (installed.resources_path / ".env").read_text(encoding="utf-8") == "OPENAI_MODEL=gpt-5.4\n"
    assert (installed.resources_path / "seed.json").read_text(encoding="utf-8") == '{"ok": true}\n'
    assert (installed.resources_path / "custom_buttons.json").read_text(encoding="utf-8") == "buttons\n"
    assert (installed.resources_path / "info_bar.json").read_text(encoding="utf-8") == "info\n"
    assert (installed.resources_path / "code_editor.scss").read_text(encoding="utf-8") == "scss\n"

    source_env = object.__new__(AgiEnv)
    source_env.resources_path = tmp_path / "source-home" / ".agilab"
    source_env.resources_path.mkdir(parents=True)
    source_env.is_source_env = True
    source_env.st_resources = installed.st_resources
    legacy = source_env.resources_path / "custom_buttons.json"
    legacy.write_text("legacy\n", encoding="utf-8")
    monkeypatch.setattr(AgiEnv, "logger", mock.Mock(), raising=False)

    source_env._init_resources(resources_src)

    assert not legacy.exists()
    assert (source_env.resources_path / ".env").exists()


def test_init_apps_sets_files_and_only_copies_missing_resource_files(tmp_path: Path):
    env = object.__new__(AgiEnv)
    env.app_src = tmp_path / "demo_project" / "src"
    env.app_src.mkdir(parents=True)
    env.resources_path = tmp_path / "home" / ".agilab"
    env.resources_path.mkdir(parents=True)
    env.active_app = tmp_path / "demo_project"
    env.agilab_pck = tmp_path / "agilab_pkg"
    resources_dir = env.agilab_pck / "resources"
    resources_dir.mkdir(parents=True)
    (resources_dir / "fresh.json").write_text('{"fresh": true}\n', encoding="utf-8")
    (resources_dir / "keep.json").write_text('{"should": "not-overwrite"}\n', encoding="utf-8")
    existing = env.resources_path / "keep.json"
    existing.write_text('{"kept": true}\n', encoding="utf-8")
    workspace_settings = env.resources_path / "apps" / "demo_project" / "app_settings.toml"
    workspace_settings.parent.mkdir(parents=True)
    workspace_settings.write_text("[cluster]\n", encoding="utf-8")

    env.find_source_app_settings_file = lambda: None
    env.resolve_user_app_settings_file = lambda: workspace_settings

    env._init_apps()

    assert env.app_settings_source_file == env.app_src / "app_settings.toml"
    assert env.app_settings_file == workspace_settings
    assert env.app_args_form == env.app_src / "app_args_form.py"
    assert env.app_args_form.exists()
    assert env.gitignore_file == env.active_app / ".gitignore"
    assert (env.resources_path / "fresh.json").exists()
    assert existing.read_text(encoding="utf-8") == '{"kept": true}\n'


def test_ensure_repository_app_link_covers_missing_existing_and_success(tmp_path: Path):
    env = object.__new__(AgiEnv)
    env.app = "demo_project"
    env.active_app = tmp_path / "apps" / "demo_project"
    env.active_app.parent.mkdir(parents=True)
    repo_root = tmp_path / "repo-apps"
    repo_root.mkdir()
    AgiEnv.logger = mock.Mock()

    env._get_apps_repository_root = lambda: None
    assert env._ensure_repository_app_link() is False

    env._get_apps_repository_root = lambda: repo_root
    assert env._ensure_repository_app_link() is False

    candidate = repo_root / "demo_project"
    candidate.mkdir()

    env.active_app.write_text("busy", encoding="utf-8")
    assert env._ensure_repository_app_link() is False
    env.active_app.unlink()

    stale_target = tmp_path / "apps" / "old_demo_project"
    stale_target.mkdir()
    env.active_app.symlink_to(stale_target, target_is_directory=True)

    assert env._ensure_repository_app_link() is True
    assert env.active_app.is_symlink()
    assert env.active_app.resolve() == candidate.resolve()


def test_app_settings_source_roots_collect_aliases_repo_builtin_worker_and_export(tmp_path: Path):
    env = object.__new__(AgiEnv)
    env.app = "demo_project"
    env.home_abs = tmp_path / "home"
    env.home_abs.mkdir()
    env.app_src = tmp_path / "current" / "demo_project" / "src"
    env.app_src.mkdir(parents=True)
    env.active_app = env.app_src.parent
    env.apps_path = tmp_path / "apps"
    env.apps_path.mkdir()
    env.builtin_apps_path = tmp_path / "apps" / "builtin"
    env.builtin_apps_path.mkdir(parents=True)
    repo_root = tmp_path / "repo-apps"
    repo_root.mkdir()
    env.apps_repository_root = None
    env._get_apps_repository_root = lambda: repo_root
    env.envars = {"AGI_EXPORT_DIR": "export-root"}

    roots = env._app_settings_source_roots("demo_worker")
    roots_set = set(roots)

    assert env.app_src in roots_set
    assert env.active_app in roots_set
    assert env.active_app / "src" in roots_set
    assert env.apps_path / "demo_worker" in roots_set
    assert env.apps_path / "demo_project" in roots_set
    assert env.builtin_apps_path / "demo_worker" in roots_set
    assert env.builtin_apps_path / "demo_project" in roots_set
    assert repo_root in roots_set
    assert repo_root / "demo_worker" in roots_set
    assert repo_root / "demo_project" in roots_set
    assert env.home_abs / "wenv" / "demo_worker" in roots_set
    assert env.home_abs / "wenv" / "demo_project" in roots_set
    assert env.home_abs / "export-root" in roots_set
    assert env.home_abs / "export-root" / "demo_project" in roots_set


def test_resolve_user_app_settings_requires_target_name():
    env = object.__new__(AgiEnv)
    env.app = None
    env.target = None

    with pytest.raises(RuntimeError, match="without an app name"):
        env.resolve_user_app_settings_file()


def test_copy_file_logs_missing_source_and_copy_errors(tmp_path: Path, monkeypatch):
    missing = tmp_path / "missing.txt"
    destination = tmp_path / "dest.txt"
    mock_logger = mock.Mock()
    monkeypatch.setattr(AgiEnv, "logger", mock_logger, raising=False)

    AgiEnv._copy_file(missing, destination)
    assert mock_logger.info.called

    source = tmp_path / "source.txt"
    source.write_text("demo", encoding="utf-8")
    monkeypatch.setattr(agi_env_module.shutil, "copy2", lambda *_a, **_k: (_ for _ in ()).throw(OSError("denied")))

    AgiEnv._copy_file(source, destination)
    assert mock_logger.error.called


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


def test_unzip_data_skips_for_owner_mismatch_parent_failure_and_refresh_permission(tmp_path: Path, monkeypatch):
    archive = tmp_path / "demo.7z"
    archive.write_bytes(b"7z")
    mock_logger = mock.Mock()
    monkeypatch.setattr(AgiEnv, "logger", mock_logger)
    monkeypatch.setattr(AgiEnv, "verbose", 2, raising=False)

    env = object.__new__(AgiEnv)
    env.app_data_rel = "demo"
    env.agi_share_path_abs = tmp_path / "share"
    env.agi_share_path_abs.mkdir(parents=True)
    env.home_abs = tmp_path / "managed-home"
    env.home_abs.mkdir()
    env.user = "someone-else"

    env.unzip_data(archive, "dataset/demo")
    assert (env.agi_share_path_abs / "dataset" / "demo").exists()
    assert not (env.agi_share_path_abs / "dataset" / "demo" / "dataset").exists()

    failing_env = object.__new__(AgiEnv)
    failing_env.app_data_rel = "demo"
    failing_env.agi_share_path_abs = tmp_path / "share-failing"
    failing_env.agi_share_path_abs.mkdir(parents=True)
    failing_env.home_abs = Path.home()
    failing_env.user = Path.home().name

    original_ensure_dir = agi_env_module._ensure_dir

    def _broken_ensure_dir(path):
        if Path(path) == failing_env.agi_share_path_abs / "dataset":
            raise OSError("denied")
        return original_ensure_dir(path)

    monkeypatch.setattr(agi_env_module, "_ensure_dir", _broken_ensure_dir)
    failing_env.unzip_data(archive, "dataset/demo")
    assert not (failing_env.agi_share_path_abs / "dataset" / "demo").exists()

    refresh_env = object.__new__(AgiEnv)
    refresh_env.app_data_rel = "demo"
    refresh_env.agi_share_path_abs = tmp_path / "share-refresh"
    refresh_env.agi_share_path_abs.mkdir(parents=True)
    refresh_env.home_abs = Path.home()
    refresh_env.user = Path.home().name
    dataset = refresh_env.agi_share_path_abs / "dataset" / "demo" / "dataset"
    dataset.mkdir(parents=True)

    monkeypatch.setattr(agi_env_module, "_ensure_dir", original_ensure_dir)
    monkeypatch.setattr(agi_env_module.shutil, "rmtree", lambda *_a, **_k: (_ for _ in ()).throw(PermissionError("busy")))
    refresh_env.unzip_data(archive, "dataset/demo", force_extract=True)
    assert dataset.exists()


def test_unzip_data_raises_runtime_error_when_extraction_fails(tmp_path: Path, monkeypatch):
    env = object.__new__(AgiEnv)
    env.app_data_rel = "demo"
    env.agi_share_path_abs = tmp_path / "share"
    env.agi_share_path_abs.mkdir(parents=True)
    env.user = Path.home().name
    env.home_abs = Path.home()
    archive = tmp_path / "demo.7z"
    archive.write_bytes(b"7z")
    monkeypatch.setattr(AgiEnv, "logger", mock.Mock(), raising=False)

    class _BrokenSevenZip:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extractall(self, path):
            raise ValueError("bad archive")

    monkeypatch.setattr(agi_env_module.py7zr, "SevenZipFile", _BrokenSevenZip)

    with pytest.raises(RuntimeError, match="Extraction failed"):
        env.unzip_data(archive, "dataset/demo", force_extract=True)


def test_read_agilab_path_logs_permission_and_missing_file_errors(tmp_path: Path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    share_dir = fake_home / ".local" / "share" / "agilab"
    share_dir.mkdir(parents=True)
    marker = share_dir / ".agilab-path"
    marker.write_text("demo\n", encoding="utf-8")
    mock_logger = mock.Mock()
    monkeypatch.setattr(agi_env_module.Path, "home", staticmethod(lambda: fake_home))
    monkeypatch.setattr(AgiEnv, "logger", mock_logger, raising=False)

    original_open = Path.open

    def _permission_open(self, *args, **kwargs):
        if self == marker:
            raise PermissionError("denied")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(agi_env_module.Path, "open", _permission_open, raising=False)
    assert AgiEnv.read_agilab_path() is None

    def _missing_open(self, *args, **kwargs):
        if self == marker:
            raise FileNotFoundError("gone")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(agi_env_module.Path, "open", _missing_open, raising=False)
    assert AgiEnv.read_agilab_path() is None
    assert mock_logger.error.call_count >= 2


def test_ensure_defaults_falls_back_when_home_or_env_loading_fail(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(AgiEnv, "resources_path", None, raising=False)
    monkeypatch.setattr(AgiEnv, "envars", None, raising=False)
    monkeypatch.setattr(agi_env_module.Path, "home", staticmethod(lambda: (_ for _ in ()).throw(RuntimeError("no home"))))
    monkeypatch.setattr(agi_env_module, "_load_dotenv_values", lambda *_a, **_k: (_ for _ in ()).throw(OSError("bad env")))

    AgiEnv._ensure_defaults()

    assert AgiEnv.resources_path.name == ".agilab"
    assert AgiEnv.envars == {}


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


def test_clone_project_handles_missing_existing_and_template_sources(tmp_path: Path, monkeypatch):
    apps_path = tmp_path / "apps"
    templates = apps_path / "templates"
    templates.mkdir(parents=True)

    env = object.__new__(AgiEnv)
    env.apps_path = apps_path
    env.home_abs = tmp_path / "home"
    env.home_abs.mkdir()
    env.projects = []
    monkeypatch.setattr(AgiEnv, "logger", mock.Mock(), raising=False)

    env.clone_project(Path("missing"), Path("demo"))
    assert env.projects == []

    existing_source = apps_path / "alpha_project"
    existing_source.mkdir(parents=True)
    existing_dest = apps_path / "beta_project"
    existing_dest.mkdir(parents=True)
    env.clone_project(Path("alpha"), Path("beta"))
    assert env.projects == []

    shutil.rmtree(existing_dest)
    template_source = templates / "template_project"
    template_source.mkdir(parents=True)

    recorded = {}

    def _fake_clone_directory(source_dir, dest_dir, rename_map, spec, source_root):
        recorded["source_dir"] = source_dir
        recorded["dest_dir"] = dest_dir
        recorded["rename_map"] = rename_map

    env.clone_directory = _fake_clone_directory
    env._cleanup_rename = lambda root, rename_map: recorded.setdefault("cleanup", (root, rename_map))
    monkeypatch.setattr(agi_env_module.shutil, "copytree", lambda *_a, **_k: (_ for _ in ()).throw(OSError("copy failed")))

    env.clone_project(Path("template"), Path("gamma"))

    assert recorded["source_dir"] == template_source
    assert recorded["dest_dir"] == apps_path / "gamma_project"
    assert env.projects[0] == Path("gamma_project")


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


def test_run_fire_and_forget_applies_exported_path_and_uv_preview_flag(tmp_path: Path, monkeypatch):
    process_env = {"PATH": "/usr/bin"}
    created: dict[str, object] = {}

    async def _fake_shell(cmd, **kwargs):
        created["cmd"] = cmd
        created["kwargs"] = kwargs
        return SimpleNamespace()

    monkeypatch.setattr(AgiEnv, "_build_env", staticmethod(lambda _venv: process_env))
    monkeypatch.setattr(asyncio, "create_subprocess_shell", _fake_shell)
    monkeypatch.setattr(
        asyncio,
        "create_task",
        lambda coro: created.setdefault("task", asyncio.get_running_loop().create_task(coro)),
    )

    result = asyncio.run(AgiEnv.run('export PATH="~/.local/bin:$PATH"; uv sync', tmp_path, wait=False))

    assert result == 0
    assert " ".join(str(created["cmd"]).split()) == "uv --preview-features extra-build-dependencies sync"
    assert process_env["PATH"].startswith(str(Path.home() / ".local/bin"))
    assert created["kwargs"]["cwd"] == str(tmp_path)


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


def test_run_bg_shell_fallback_handles_blank_lines_and_simple_callback(tmp_path: Path, monkeypatch):
    streamed: list[str] = []
    process_env = {"PATH": "/usr/bin", "PYTHONHOME": "/tmp/home"}

    class _FakeStream:
        def __init__(self, lines):
            self._lines = list(lines)

        async def readline(self):
            if self._lines:
                return self._lines.pop(0)
            return b""

    class _FakeProc:
        def __init__(self):
            self.stdout = None
            self.stderr = _FakeStream([b"\n", b"stderr line\n", b""])
            self.returncode = 0

        async def wait(self):
            return self.returncode

        async def communicate(self):
            return b"", b"stderr line\n"

    async def _raise_exec(*args, **kwargs):
        raise ValueError("boom")

    async def _fake_shell(cmd, **kwargs):
        return _FakeProc()

    monkeypatch.setattr(AgiEnv, "_build_env", staticmethod(lambda _venv: dict(process_env)))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _raise_exec)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", _fake_shell)

    stdout, stderr = asyncio.run(
        AgiEnv._run_bg(
            "uv pip install demo",
            cwd=tmp_path,
            venv=tmp_path,
            timeout=10,
            remove_env={"PYTHONHOME"},
            log_callback=streamed.append,
        )
    )

    assert stdout == ""
    assert stderr == "stderr line\n"
    assert streamed == ["stderr line"]


def test_build_env_strips_uv_run_recursion_depth(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("UV_RUN_RECURSION_DEPTH", "1")
    monkeypatch.setenv("PYTHONPATH", "/tmp/demo")
    monkeypatch.setenv("PYTHONHOME", "/tmp/home")
    foreign_source = tmp_path / "foreign-source"
    foreign_source.mkdir()
    fake_instance = object.__new__(AgiEnv)
    fake_instance._pythonpath_entries = [str(foreign_source)]
    monkeypatch.setattr(AgiEnv, "_instance", fake_instance, raising=False)

    env = AgiEnv._build_env(tmp_path)

    assert env.get("VIRTUAL_ENV") == str(tmp_path / ".venv")
    assert "UV_RUN_RECURSION_DEPTH" not in env
    assert "PYTHONPATH" not in env
    assert "PYTHONHOME" not in env


def test_build_env_uses_class_pythonpath_entries_without_venv(monkeypatch, tmp_path: Path):
    class_entries = [str(tmp_path / "alpha"), str(tmp_path / "beta")]
    monkeypatch.setattr(AgiEnv, "_instance", None, raising=False)
    monkeypatch.setattr(AgiEnv, "_pythonpath_entries", class_entries, raising=False)
    monkeypatch.setenv("UV_RUN_RECURSION_DEPTH", "3")
    monkeypatch.setenv("PYTHONPATH", "/tmp/ignored")
    monkeypatch.setenv("PYTHONHOME", "/tmp/home")
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)

    env = AgiEnv._build_env()

    assert "VIRTUAL_ENV" not in env
    assert env["PYTHONPATH"] == os.pathsep.join(class_entries)
    assert "PYTHONHOME" not in env
    assert "UV_RUN_RECURSION_DEPTH" not in env


def test_build_env_keeps_instance_pythonpath_entries_for_current_venv(monkeypatch, tmp_path: Path):
    current_venv = Path(sys.prefix).resolve()
    instance_entries = [str(tmp_path / "src-one"), str(tmp_path / "src-two")]
    fake_instance = object.__new__(AgiEnv)
    fake_instance._pythonpath_entries = instance_entries
    monkeypatch.setattr(AgiEnv, "_instance", fake_instance, raising=False)
    monkeypatch.setenv("PYTHONPATH", "/tmp/ignored")
    monkeypatch.setenv("PYTHONHOME", "/tmp/home")

    env = AgiEnv._build_env(current_venv)

    assert env["VIRTUAL_ENV"] == str(current_venv)
    assert env["PATH"].split(os.pathsep)[0] == str(current_venv / "bin")
    assert env["PYTHONPATH"] == os.pathsep.join(instance_entries)
    assert "PYTHONHOME" not in env


def test_log_info_uses_logger_when_available(monkeypatch):
    fake_logger = mock.Mock()
    monkeypatch.setattr(AgiEnv, "logger", fake_logger)

    AgiEnv.log_info(123)

    fake_logger.info.assert_called_once_with("123")


def test_log_info_prints_when_logger_missing(monkeypatch, capsys):
    monkeypatch.setattr(AgiEnv, "logger", None)

    AgiEnv.log_info("hello")

    assert capsys.readouterr().out.strip() == "hello"


def test_last_non_empty_output_line_skips_blank_entries():
    lines = [None, "   ", "\n", " useful detail  "]

    assert AgiEnv._last_non_empty_output_line(lines) == "useful detail"


def test_last_non_empty_output_line_returns_none_for_empty_input():
    assert AgiEnv._last_non_empty_output_line([None, "", "   "]) is None


def test_format_command_failure_message_falls_back_to_command_and_appends_hint():
    message = AgiEnv._format_command_failure_message(
        7,
        "demo command",
        lines=[None, "", "   "],
        diagnostic_hint="check worker manifest",
    )

    assert message == "Command failed with exit code 7: demo command\ncheck worker manifest"


def test_run_async_nonzero_command_prefers_last_subprocess_line_in_runtime_error(tmp_path: Path, monkeypatch):
    mock_logger = mock.Mock()
    monkeypatch.setattr(AgiEnv, "logger", mock_logger)

    cmd = (
        f"{shlex.quote(sys.executable)} -c "
        "\"import sys; print('FileNotFoundError: missing artifact', file=sys.stderr); sys.exit(6)\""
    )

    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(AgiEnv.run_async(cmd, venv=tmp_path, cwd=tmp_path, timeout=10))

    assert str(exc_info.value) == "Command failed with exit code 6: missing artifact"
    assert "sys.exit(6)" not in str(exc_info.value)


def test_run_bg_timeout_kills_process_and_raises_runtime_error(tmp_path: Path, monkeypatch):
    class _Stream:
        async def readline(self):
            return b""

    class _Proc:
        def __init__(self):
            self.stdout = _Stream()
            self.stderr = _Stream()
            self.returncode = None
            self.killed = False

        async def wait(self):
            await asyncio.sleep(1)
            return 0

        async def communicate(self):
            return b"", b""

        def kill(self):
            self.killed = True

    proc = _Proc()

    async def _fake_exec(*_args, **_kwargs):
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

    with pytest.raises(RuntimeError, match="Timeout expired for command: echo slow"):
        asyncio.run(AgiEnv._run_bg("echo slow", cwd=tmp_path, venv=tmp_path, timeout=0.01))

    assert proc.killed is True


def test_run_async_wraps_non_runtime_stream_errors(tmp_path: Path, monkeypatch):
    class _BrokenStream:
        async def readline(self):
            raise ValueError("stream broke")

    class _QuietStream:
        async def readline(self):
            return b""

    class _Proc:
        def __init__(self):
            self.stdout = _BrokenStream()
            self.stderr = _QuietStream()
            self.returncode = 0
            self.killed = False

        async def wait(self):
            return 0

        async def communicate(self):
            return b"", b""

        def kill(self):
            self.killed = True

    proc = _Proc()
    mock_logger = mock.Mock()

    async def _fake_exec(*_args, **_kwargs):
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    monkeypatch.setattr(AgiEnv, "_build_env", staticmethod(lambda _venv: {}))
    monkeypatch.setattr(AgiEnv, "logger", mock_logger, raising=False)

    with pytest.raises(RuntimeError, match="Subprocess execution error for: echo boom"):
        asyncio.run(AgiEnv.run_async("echo boom", cwd=tmp_path, venv=tmp_path, timeout=1))

    assert proc.killed is True
    assert mock_logger.error.called

    assert proc.killed is True


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


def test_run_agi_without_callback_uses_logger_and_logging_paths(tmp_path: Path, monkeypatch):
    env = object.__new__(AgiEnv)
    env.runenv = tmp_path / "runenv"
    env.target = "demo_project"

    mock_logger = mock.Mock()
    finished = []
    monkeypatch.setattr(AgiEnv, "logger", mock_logger)
    monkeypatch.setattr(agi_env_module.logging, "info", lambda message: finished.append(message))

    result = asyncio.run(env.run_agi("print('hello')", venv=tmp_path))
    assert result == ("", "")
    mock_logger.info.assert_any_call("Could not determine snippet name from code.")

    code = "async def main():\n    await Agi.demo_run()\n"
    stdout, stderr = asyncio.run(env.run_agi(code, venv=tmp_path))
    assert stdout == ""
    assert "Run INSTALL first" in stderr
    mock_logger.warning.assert_any_call(f"No virtual environment found in {tmp_path}. Run INSTALL first.")

    project_root = tmp_path / "project"
    project_root.mkdir()
    project_venv = project_root / ".venv"
    project_venv.mkdir()
    (project_venv / "pyvenv.cfg").write_text("home = /tmp\n", encoding="utf-8")

    async def _fake_run_bg(cmd, cwd=None, venv=None, remove_env=None, log_callback=None, **kwargs):
        return "done", ""

    monkeypatch.setattr(AgiEnv, "_run_bg", staticmethod(_fake_run_bg))
    install_code = "async def main():\n    await Agi.demo_install()\n"
    result = asyncio.run(env.run_agi(install_code, venv=project_root))

    assert result == ("done", "")
    assert finished[-1] == "Process finished"


def test_share_root_resolution_and_mode_helpers(tmp_path: Path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    env = object.__new__(AgiEnv)
    env._share_root_cache = None
    env.agi_share_path = "clustershare"
    env.home_abs = fake_home
    env.is_worker_env = False
    env.target = "demo_project"
    env.app = "demo_project"
    env.hw_rapids_capable = False

    assert env.share_root_path() == fake_home / "clustershare"
    assert env.resolve_share_path(None) == fake_home / "clustershare"
    assert env.resolve_share_path("demo/data") == fake_home / "clustershare" / "demo" / "data"
    assert env.resolve_share_path("/tmp/absolute") == Path("/tmp/absolute").resolve(strict=False)
    assert env._share_target_name() == "demo"
    assert env.mode2str(0b0111) == "_dcp"
    assert env.mode2int("pc") == 6
    assert env.is_valid_ip("192.168.20.130") is True
    assert env.is_valid_ip("999.1.1.1") is False


def test_share_root_resolution_worker_uses_runtime_home_and_init_honours_share_override(tmp_path: Path, monkeypatch):
    fake_home = tmp_path / "worker-home"
    fake_home.mkdir()
    manager_home = tmp_path / "manager-home"
    manager_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    env = object.__new__(AgiEnv)
    env._share_root_cache = None
    env.agi_share_path = "clustershare"
    env.home_abs = manager_home
    env.is_worker_env = True
    env.target = "demo_worker"
    env.app = "demo_worker"

    assert env.share_root_path() == fake_home / "clustershare"

    agipath = AgiEnv.locate_agilab_installation(verbose=False)
    share_dir = fake_home / ".local" / "share" / "agilab"
    share_dir.mkdir(parents=True, exist_ok=True)
    (share_dir / ".agilab-path").write_text(str(agipath) + "\n", encoding="utf-8")
    (fake_home / ".agilab").mkdir(parents=True, exist_ok=True)
    (fake_home / ".agilab" / ".env").write_text(
        "AGI_SHARE_DIR=cluster_mount\nSTREAMLIT_SERVER_MAX_MESSAGE_SIZE=256\nIS_SOURCE_ENV=yes\n",
        encoding="utf-8",
    )

    fake_apps = tmp_path / "apps"
    fake_app = fake_apps / "demo_project"
    (fake_app / "src" / "demo").mkdir(parents=True, exist_ok=True)
    (fake_app / "src" / "demo_worker").mkdir(parents=True, exist_ok=True)
    (fake_app / "src" / "demo" / "demo.py").write_text("class Demo:\n    pass\n", encoding="utf-8")
    (fake_app / "src" / "demo_worker" / "demo_worker.py").write_text(
        "class BaseWorker:\n    pass\n\nclass DemoWorker(BaseWorker):\n    pass\n",
        encoding="utf-8",
    )
    (fake_app / "pyproject.toml").write_text("[project]\nname='demo-project'\n", encoding="utf-8")

    AgiEnv.reset()
    mock_logger = mock.Mock()
    with mock.patch.object(AgiLogger, "configure", return_value=mock_logger), mock.patch.object(
        AgiEnv, "_init_apps", lambda self: None
    ):
        init_env = AgiEnv(apps_path=fake_apps, app="demo_project", verbose=0)

    assert init_env.AGI_CLUSTER_SHARE == "cluster_mount"
    assert os.environ["STREAMLIT_SERVER_MAX_MESSAGE_SIZE"] == "256"
    assert init_env.is_source_env is True


def test_set_env_var_updates_process_and_env_file(tmp_path: Path, monkeypatch):
    resources = tmp_path / ".agilab"
    resources.mkdir()
    monkeypatch.setattr(AgiEnv, "resources_path", resources, raising=False)
    monkeypatch.setattr(AgiEnv, "envars", {}, raising=False)
    monkeypatch.delenv("AGI_DEMO_FLAG", raising=False)

    AgiEnv.set_env_var("AGI_DEMO_FLAG", "1")

    assert os.environ["AGI_DEMO_FLAG"] == "1"
    assert AgiEnv.envars["AGI_DEMO_FLAG"] == "1"
    assert "AGI_DEMO_FLAG=1" in (resources / ".env").read_text(encoding="utf-8")


def test_read_agilab_path_active_and_home_helpers(tmp_path: Path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    share_dir = fake_home / ".local" / "share" / "agilab"
    share_dir.mkdir(parents=True)
    marker = share_dir / ".agilab-path"
    install_root = tmp_path / "agilab_install"
    install_root.mkdir()
    marker.write_text(str(install_root), encoding="utf-8")
    monkeypatch.setenv("HOME", str(fake_home))

    env = object.__new__(AgiEnv)
    env.app = "alpha_project"
    switched: list[str] = []
    env.change_app = lambda target: switched.append(target)

    assert AgiEnv.read_agilab_path() == install_root
    env.active("beta_project")
    env.active("alpha_project")
    assert switched == ["beta_project"]

    monkeypatch.setattr(agi_env_module.Path, "home", staticmethod(lambda: fake_home))
    assert env.has_agilab_anywhere_under_home(fake_home / "agilab" / "demo") is True
    assert env.has_agilab_anywhere_under_home(tmp_path / "outside" / "demo") is False


def test_get_projects_and_copy_existing_projects_handle_symlinks_and_nested_projects(tmp_path: Path, monkeypatch):
    src_apps = tmp_path / "src_apps"
    dst_apps = tmp_path / "dst_apps"
    src_apps.mkdir()
    dst_apps.mkdir()
    nested = src_apps / "group" / "alpha_project"
    nested.mkdir(parents=True)
    (nested / "app.py").write_text("print('ok')\n", encoding="utf-8")
    good = src_apps / "beta_project"
    good.mkdir()
    dangling = src_apps / "dangling_project"
    dangling.symlink_to(src_apps / "missing_project")

    mock_logger = mock.Mock()
    monkeypatch.setattr(AgiEnv, "logger", mock_logger, raising=False)
    env = object.__new__(AgiEnv)

    projects = env.get_projects(src_apps)
    env.copy_existing_projects(src_apps, dst_apps)

    assert "beta_project" in projects
    assert "dangling_project" not in projects
    assert not dangling.exists()
    assert (dst_apps / "group" / "alpha_project" / "app.py").exists()


def test_apps_repository_root_and_pythonpath_helpers(tmp_path: Path, monkeypatch):
    repo_root = tmp_path / "repo"
    apps_root = repo_root / "src" / "agilab" / "apps"
    (apps_root / "alpha_project").mkdir(parents=True)

    env = object.__new__(AgiEnv)
    env.envars = {"APPS_REPOSITORY": f"'{repo_root}'"}
    mock_logger = mock.Mock()
    monkeypatch.setattr(AgiEnv, "logger", mock_logger, raising=False)

    assert env._get_apps_repository_root() == apps_root

    alt_repo = tmp_path / "alt-repo"
    alt_apps = alt_repo / "nested" / "apps"
    (alt_apps / "beta_project").mkdir(parents=True)
    env.envars = {"APPS_REPOSITORY": str(alt_repo)}
    assert env._get_apps_repository_root() == alt_apps

    env.envars = {"APPS_REPOSITORY": str(tmp_path / "missing-repo")}
    assert env._get_apps_repository_root() is None
    assert mock_logger.info.called

    package_root = tmp_path / "pkg-root"
    env_pkg = package_root / "envpkg"
    node_pkg = package_root / "nodepkg"
    core_pkg = package_root / "corepkg"
    cluster_pkg = package_root / "clusterpkg"
    for pkg in (env_pkg, node_pkg, core_pkg, cluster_pkg):
        (pkg / "__init__.py").parent.mkdir(parents=True, exist_ok=True)
        (pkg / "__init__.py").write_text("", encoding="utf-8")
    dist_abs = tmp_path / "dist"
    app_src = tmp_path / "app_src"
    wenv_abs = tmp_path / "wenv"
    agilab_pck = tmp_path / "agilab_pck"
    for path in (dist_abs, app_src, wenv_abs / "src", agilab_pck / "agilab"):
        path.mkdir(parents=True, exist_ok=True)

    env.env_pck = env_pkg
    env.node_pck = node_pkg
    env.core_pck = core_pkg
    env.cluster_pck = cluster_pkg
    env.dist_abs = dist_abs
    env.app_src = app_src
    env.wenv_abs = wenv_abs
    env.agilab_pck = agilab_pck

    entries = env._collect_pythonpath_entries()

    assert str(package_root) in entries
    assert str(dist_abs) in entries
    assert str(app_src) in entries
    assert str(wenv_abs / "src") in entries
    assert str(agilab_pck / "agilab") in entries
    assert env._dedupe_paths([dist_abs, dist_abs, tmp_path / "missing"]) == [str(dist_abs)]

    monkeypatch.setattr(agi_env_module.sys, "path", ["/existing"], raising=False)
    monkeypatch.setenv("PYTHONPATH", "/existing")
    env._configure_pythonpath(entries[:2])
    assert entries[0] in agi_env_module.sys.path
    assert entries[1] in os.environ["PYTHONPATH"]


def test_apps_repository_root_handles_unreadable_alt_apps_dirs(tmp_path: Path, monkeypatch):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    unreadable_apps = repo_root / "nested" / "apps"
    unreadable_apps.mkdir(parents=True)

    env = object.__new__(AgiEnv)
    env.envars = {"APPS_REPOSITORY": str(repo_root)}
    mock_logger = mock.Mock()
    monkeypatch.setattr(AgiEnv, "logger", mock_logger, raising=False)

    original_iterdir = Path.iterdir

    def _broken_iterdir(self):
        if self == unreadable_apps:
            raise OSError("no access")
        return original_iterdir(self)

    monkeypatch.setattr(agi_env_module.Path, "iterdir", _broken_iterdir, raising=False)

    assert env._get_apps_repository_root() is None
    assert mock_logger.info.called


def test_copy_existing_projects_warns_on_conflicting_destination_file(tmp_path: Path, monkeypatch):
    src_apps = tmp_path / "src_apps"
    dst_apps = tmp_path / "dst_apps"
    source_project = src_apps / "gamma_project"
    source_project.mkdir(parents=True)
    (source_project / "app.py").write_text("print('ok')\n", encoding="utf-8")

    dst_apps.mkdir()
    conflicting = dst_apps / "gamma_project"
    conflicting.write_text("busy", encoding="utf-8")

    mock_logger = mock.Mock()
    monkeypatch.setattr(AgiEnv, "logger", mock_logger, raising=False)
    env = object.__new__(AgiEnv)

    original_unlink = Path.unlink

    def _broken_unlink(self, *args, **kwargs):
        if self == conflicting:
            raise OSError("locked")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(agi_env_module.Path, "unlink", _broken_unlink, raising=False)

    env.copy_existing_projects(src_apps, dst_apps)

    assert conflicting.exists()
    assert not (dst_apps / "gamma_project" / "app.py").exists()
    assert mock_logger.warning.called


def test_create_symlink_and_windows_link_helpers_log_expected_paths(tmp_path: Path, monkeypatch):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    dest = tmp_path / "dest"

    mock_logger = mock.Mock()
    monkeypatch.setattr(AgiEnv, "logger", mock_logger, raising=False)

    AgiEnv.create_symlink(src_dir, dest)
    assert dest.is_symlink()

    AgiEnv.create_symlink(src_dir, dest)
    assert mock_logger.info.called

    failing = tmp_path / "failing"
    monkeypatch.setattr(agi_env_module.Path, "symlink_to", lambda self, *_a, **_k: (_ for _ in ()).throw(OSError("denied")), raising=False)
    AgiEnv.create_symlink(src_dir, failing)
    assert mock_logger.error.called

    calls = []
    monkeypatch.setattr(agi_env_module.subprocess, "check_call", lambda cmd: calls.append(cmd))
    AgiEnv.create_junction_windows(src_dir, tmp_path / "junction")
    assert calls

    def _raise_called_process_error(_cmd):
        raise agi_env_module.subprocess.CalledProcessError(1, "mklink")

    monkeypatch.setattr(agi_env_module.subprocess, "check_call", _raise_called_process_error)
    AgiEnv.create_junction_windows(src_dir, tmp_path / "junction_fail")

    monkeypatch.setattr(AgiEnv, "has_admin_rights", staticmethod(lambda: False))
    fake_create = lambda *_args, **_kwargs: 0
    monkeypatch.setattr(
        agi_env_module.ctypes,
        "windll",
        SimpleNamespace(kernel32=SimpleNamespace(CreateSymbolicLinkW=fake_create)),
        raising=False,
    )
    AgiEnv.create_symlink_windows(src_dir, tmp_path / "windows_link")
    assert mock_logger.info.called


def test_create_symlink_windows_logs_success_and_failure(tmp_path: Path, monkeypatch):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    dest = tmp_path / "dest"
    mock_logger = mock.Mock()
    monkeypatch.setattr(AgiEnv, "logger", mock_logger, raising=False)
    monkeypatch.setattr(AgiEnv, "has_admin_rights", staticmethod(lambda: True))

    def _success(*_args, **_kwargs):
        return 1

    monkeypatch.setattr(
        agi_env_module.ctypes,
        "windll",
        SimpleNamespace(kernel32=SimpleNamespace(CreateSymbolicLinkW=_success)),
        raising=False,
    )
    monkeypatch.setattr(agi_env_module.ctypes, "GetLastError", lambda: 5, raising=False)
    AgiEnv.create_symlink_windows(src_dir, dest)

    def _failure(*_args, **_kwargs):
        return 0

    monkeypatch.setattr(
        agi_env_module.ctypes,
        "windll",
        SimpleNamespace(kernel32=SimpleNamespace(CreateSymbolicLinkW=_failure)),
        raising=False,
    )
    AgiEnv.create_symlink_windows(src_dir, dest)

    assert mock_logger.info.called


def test_locate_agilab_installation_falls_back_to_repo_and_parent(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(agi_env_module.importlib.util, "find_spec", lambda _name: None)

    repo_root = tmp_path / "repo-root"
    (repo_root / "apps").mkdir(parents=True)
    monkeypatch.setattr(
        agi_env_module,
        "__file__",
        str(repo_root / "x" / "y" / "z" / "w" / "agi_env.py"),
    )
    assert AgiEnv.locate_agilab_installation() == repo_root

    fallback_root = tmp_path / "fallback" / "agilab"
    (fallback_root / "apps").mkdir(parents=True)
    monkeypatch.setattr(
        agi_env_module,
        "__file__",
        str(fallback_root / "pkg" / "one" / "two" / "agi_env.py"),
    )
    assert AgiEnv.locate_agilab_installation() == fallback_root


def test_clone_directory_covers_symlink_readlink_fallback_and_existing_destination(tmp_path: Path, monkeypatch):
    source_root = tmp_path / "source"
    source_root.mkdir()
    target_file = source_root / "target.txt"
    target_file.write_text("payload\n", encoding="utf-8")
    symlink_item = source_root / "link.txt"
    symlink_item.symlink_to(target_file)
    venv_dir = source_root / ".venv"
    venv_dir.mkdir()

    dest_root = tmp_path / "dest"
    dest_root.mkdir()
    existing_link = dest_root / "link.txt"
    existing_link.write_text("occupied\n", encoding="utf-8")

    env = object.__new__(AgiEnv)
    spec = agi_env_module.PathSpec.from_lines(agi_env_module.GitWildMatchPattern, [])

    original_readlink = os.readlink
    original_symlink = os.symlink

    def _patched_readlink(path):
        if Path(path) == symlink_item:
            raise OSError("readlink failed")
        return original_readlink(path)

    def _patched_symlink(src, dst, target_is_directory=False):
        if Path(dst) == existing_link:
            raise FileExistsError("already exists")
        return original_symlink(src, dst, target_is_directory=target_is_directory)

    monkeypatch.setattr(agi_env_module.os, "readlink", _patched_readlink)
    monkeypatch.setattr(agi_env_module.os, "symlink", _patched_symlink)

    env.clone_directory(source_root, dest_root, {}, spec, source_root)

    assert existing_link.read_text(encoding="utf-8") == "occupied\n"
    assert (dest_root / ".venv").is_symlink()


def test_copy_existing_projects_warns_when_symlink_cannot_be_removed(tmp_path: Path, monkeypatch):
    src_apps = tmp_path / "src_apps"
    dst_apps = tmp_path / "dst_apps"
    source_project = src_apps / "gamma_project"
    source_project.mkdir(parents=True)
    (source_project / "app.py").write_text("print('ok')\n", encoding="utf-8")

    dst_apps.mkdir()
    target = dst_apps / "missing_project"
    symlink_path = dst_apps / "gamma_project"
    symlink_path.symlink_to(target)

    mock_logger = mock.Mock()
    monkeypatch.setattr(AgiEnv, "logger", mock_logger, raising=False)
    env = object.__new__(AgiEnv)

    original_unlink = Path.unlink

    def _broken_unlink(self, *args, **kwargs):
        if self == symlink_path:
            raise OSError("busy")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(agi_env_module.Path, "unlink", _broken_unlink, raising=False)

    env.copy_existing_projects(src_apps, dst_apps)

    assert symlink_path.is_symlink()
    assert mock_logger.warning.called


def test_is_local_and_has_admin_rights_helpers(monkeypatch):
    AgiEnv._ip_local_cache = {"127.0.0.1", "::1"}
    assert AgiEnv.is_local("") is True

    addrs = {
        "en0": [
            SimpleNamespace(family=agi_env_module.socket.AF_INET, address="192.168.10.10"),
        ]
    }
    monkeypatch.setattr(agi_env_module.psutil, "net_if_addrs", lambda: addrs)
    assert AgiEnv.is_local("192.168.10.10") is True
    assert "192.168.10.10" in AgiEnv._ip_local_cache
    assert AgiEnv.is_local("192.168.10.11") is False

    monkeypatch.setattr(
        agi_env_module.ctypes,
        "windll",
        SimpleNamespace(shell32=SimpleNamespace(IsUserAnAdmin=lambda: 1)),
        raising=False,
    )
    assert AgiEnv.has_admin_rights() == 1

    class _BrokenShell32:
        def IsUserAnAdmin(self):
            raise OSError("denied")

    monkeypatch.setattr(
        agi_env_module.ctypes,
        "windll",
        SimpleNamespace(shell32=_BrokenShell32()),
        raising=False,
    )
    assert AgiEnv.has_admin_rights() is False


def test_create_symlink_windows_hits_success_and_failure_branches(tmp_path: Path, monkeypatch):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    dest = tmp_path / "dest"
    mock_logger = mock.Mock()
    monkeypatch.setattr(AgiEnv, "logger", mock_logger, raising=False)
    monkeypatch.setattr(AgiEnv, "has_admin_rights", staticmethod(lambda: True))

    class _CreateSymbolicLink:
        def __init__(self, result):
            self._result = result
            self.restype = None
            self.argtypes = None

        def __call__(self, *_args, **_kwargs):
            return self._result

    monkeypatch.setattr(
        agi_env_module.ctypes,
        "windll",
        SimpleNamespace(kernel32=SimpleNamespace(CreateSymbolicLinkW=_CreateSymbolicLink(1))),
        raising=False,
    )
    monkeypatch.setattr(agi_env_module.ctypes, "GetLastError", lambda: 5, raising=False)
    AgiEnv.create_symlink_windows(src_dir, dest)

    monkeypatch.setattr(
        agi_env_module.ctypes,
        "windll",
        SimpleNamespace(kernel32=SimpleNamespace(CreateSymbolicLinkW=_CreateSymbolicLink(0))),
        raising=False,
    )
    AgiEnv.create_symlink_windows(src_dir, dest)

    info_messages = [" ".join(str(part) for part in call.args) for call in mock_logger.info.call_args_list]
    assert any("Created symbolic link" in message for message in info_messages)
    assert any("Failed to create symbolic link" in message for message in info_messages)
