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


_AGIENV_PROCESS_ENV_KEYS = {
    "AGI_CLUSTER_ENABLED",
    "AGI_CLUSTER_SHARE",
    "AGI_DEMO_FLAG",
    "AGI_EXPORT_DIR",
    "AGI_LOCAL_SHARE",
    "AGI_LOG_DIR",
    "AGILAB_SHARE_USER",
    "APP_DEFAULT",
    "APPS_PATH",
    "APPS_REPOSITORY",
    "AZURE_OPENAI_API_KEY",
    "CLUSTER_CREDENTIALS",
    "IS_SOURCE_ENV",
    "IS_WORKER_ENV",
    "OPENAI_API_KEY",
    "STREAMLIT_MAX_MESSAGE_SIZE",
    "STREAMLIT_SERVER_MAX_MESSAGE_SIZE",
    "UV_RUN_RECURSION_DEPTH",
}


@pytest.fixture(autouse=True)
def isolate_agienv_process_state(monkeypatch):
    saved = {key: os.environ.get(key) for key in _AGIENV_PROCESS_ENV_KEYS}
    AgiEnv.reset()
    AgiEnv.envars = {}
    for key in _AGIENV_PROCESS_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    yield
    AgiEnv.reset()
    AgiEnv.envars = {}
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


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
    captured = {}

    def _fake_replace(txt, rename_map):
        captured["args"] = (txt, rename_map)
        return "patched"

    with mock.patch.object(agi_env_module, "replace_text_content", _fake_replace):
        out = env.replace_content("foo", {"foo": "bar"})

    assert out == "patched"
    assert captured["args"] == ("foo", {"foo": "bar"})

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
    env.app = "flight_telemetry_project"
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
    env.app = str(apps_root / "flight_telemetry_project")

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


def test_init_envars_app_uses_optional_agi_pages_provider(tmp_path: Path, monkeypatch):
    env = object.__new__(AgiEnv)
    env.home_abs = tmp_path / "home"
    env.home_abs.mkdir()
    env.target = "sb3_trainer"
    env.agilab_pck = tmp_path / "pkg"
    env.agilab_pck.mkdir()
    env.read_agilab_path = lambda: None
    pages_root = tmp_path / "installed-agi-pages"
    pages_root.mkdir()
    monkeypatch.setattr(AgiEnv, "logger", mock.Mock(), raising=False)
    monkeypatch.setattr(agi_env_module, "_optional_agi_pages_bundles_root", lambda: pages_root)

    env.init_envars_app({"MLFLOW_TRACKING_DIR": "mlruns"})

    assert env.AGILAB_PAGES_ABS == pages_root


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
    monkeypatch.delenv("AGI_CLUSTER_SHARE", raising=False)

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
    wrong_app = wrong_apps / "flight_telemetry_project"
    (wrong_app / "src").mkdir(parents=True, exist_ok=True)
    (wrong_app / "pyproject.toml").write_text("[project]\nname='wrong-flight'\n", encoding="utf-8")

    env_dir = fake_home / ".agilab"
    env_dir.mkdir(parents=True, exist_ok=True)
    (env_dir / ".env").write_text(f"APPS_PATH={wrong_apps}\n", encoding="utf-8")

    builtin_app = tmp_path / "apps" / "builtin" / "flight_telemetry_project"
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


def test_explicit_apps_path_wins_over_stale_env_apps_path(tmp_path: Path, monkeypatch):
    """A source launch must not be pulled back to a persisted agi-space APPS_PATH."""

    agipath = AgiEnv.locate_agilab_installation(verbose=False)
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    share_root = fake_home / ".local" / "share" / "agilab"
    share_root.mkdir(parents=True, exist_ok=True)
    (share_root / ".agilab-path").write_text(str(agipath) + "\n", encoding="utf-8")

    stale_apps = tmp_path / "agi-space" / "apps"
    (stale_apps / "builtin" / "flight_telemetry_project").mkdir(parents=True, exist_ok=True)
    env_dir = fake_home / ".agilab"
    env_dir.mkdir(parents=True, exist_ok=True)
    (env_dir / ".env").write_text(f"APPS_PATH={stale_apps}\nIS_SOURCE_ENV=1\n", encoding="utf-8")

    source_apps = tmp_path / "agilab-src" / "src" / "agilab" / "apps"
    builtin_app = source_apps / "builtin" / "flight_telemetry_project"
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

    env = AgiEnv(apps_path=source_apps, app="flight_telemetry_project", verbose=0)

    assert env.apps_path == source_apps.resolve()
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

    wrong_app = tmp_path / "apps" / "flight_telemetry_project"
    wrong_app.mkdir(parents=True, exist_ok=True)
    (wrong_app / "pyproject.toml").write_text("[project]\nname='wrong-flight'\n", encoding="utf-8")

    builtin_app = tmp_path / "apps" / "builtin" / "flight_telemetry_project"
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
    flat_app = apps_root / "flight_telemetry_project"
    (flat_app / "src").mkdir(parents=True, exist_ok=True)
    (flat_app / "pyproject.toml").write_text("[project]\nname='wrong-flight'\n", encoding="utf-8")

    builtin_app = apps_root / "builtin" / "flight_telemetry_project"
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


def test_select_hook_wrapper_uses_local_resolver(tmp_path: Path, monkeypatch):
    fallback = tmp_path / "shared.py"
    fallback.write_text("print('shared')\n", encoding="utf-8")
    missing = tmp_path / "missing.py"
    monkeypatch.setattr("agi_env.agi_env._resolve_worker_hook", lambda _name: fallback)

    selected, shared = agi_env_module._select_hook(missing, "pre_install.py", "pre_install")

    assert selected == fallback
    assert shared is True


def test_resolve_worker_hook_wrapper_uses_hook_support(monkeypatch):
    captured = {}

    def _fake_resolve(filename, *, module_file):
        captured["args"] = (filename, module_file)
        return Path("/tmp/pre_install.py")

    monkeypatch.setattr(agi_env_module, "resolve_worker_hook", _fake_resolve)

    assert agi_env_module._resolve_worker_hook("pre_install.py") == Path("/tmp/pre_install.py")
    assert captured["args"] == ("pre_install.py", agi_env_module.__file__)


def test_read_agilab_path_wrapper_uses_installation_support(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    marker = fake_home / ".local" / "share" / "agilab" / ".agilab-path"
    install_root = tmp_path / "install-root"
    install_root.mkdir()
    captured = {}

    monkeypatch.setattr(agi_env_module.Path, "home", staticmethod(lambda: fake_home))

    def _fake_marker_path(**kwargs):
        captured["marker_kwargs"] = kwargs
        return marker

    def _fake_read(marker_path, *, logger=None):
        captured["read_args"] = (marker_path, logger)
        return install_root

    monkeypatch.setattr(agi_env_module, "installation_marker_path", _fake_marker_path)
    monkeypatch.setattr(agi_env_module, "read_agilab_installation_marker", _fake_read)

    assert AgiEnv.read_agilab_path() == install_root
    assert captured["marker_kwargs"]["home"] == fake_home
    assert captured["read_args"][0] == marker
    assert captured["read_args"][1] == AgiEnv.logger


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


def test_agienv_meta_handles_missing_instance_slot_and_current_returns_cached_instance():
    class Dummy(metaclass=agi_env_module._AgiEnvMeta):
        _lock = None
        class_value = "class"

    assert Dummy.class_value == "class"

    AgiEnv.reset()
    sentinel = object.__new__(AgiEnv)
    AgiEnv._instance = sentinel
    try:
        assert AgiEnv.current() is sentinel
    finally:
        AgiEnv.reset()


def test_init_worker_env_flag_requires_app_and_sets_skip_repo_links(tmp_path: Path, monkeypatch):
    fake_home = tmp_path / "worker-home"
    fake_home.mkdir()
    share_root = fake_home / ".local" / "share" / "agilab"
    share_root.mkdir(parents=True, exist_ok=True)
    (fake_home / "clustershare" / "worker-user").mkdir(parents=True)
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
    (fake_home / "clustershare" / "worker-user").mkdir(parents=True)
    (fake_home / "localshare").mkdir()
    env_dir = fake_home / ".agilab"
    env_dir.mkdir(parents=True, exist_ok=True)
    (env_dir / ".env").write_text("IS_SOURCE_ENV=no\nIS_WORKER_ENV=0\nAGI_CLUSTER_ENABLED=0\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("AGI_CLUSTER_ENABLED", "0")
    monkeypatch.setenv("AGILAB_SHARE_USER", "worker-user")

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


def test_init_active_app_alias_falls_back_to_string_name_and_origin_only_packages(
    tmp_path: Path, monkeypatch
):
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
            "agi_env": SimpleNamespace(origin=str(agi_env_pkg / "__init__.py")),
            "agi_node": SimpleNamespace(origin=str(agi_node_pkg / "__init__.py")),
        }
        if name in {"agi_core", "agi_cluster", "agi_cluster.agi_distributor.cli"}:
            raise ModuleNotFoundError(name)
        return mapping.get(name)

    class _NonPathActiveApp:
        def __fspath__(self):
            raise TypeError("not path-like")

        def __str__(self):
            return "demo_project"

    monkeypatch.setattr(agi_env_module.importlib.util, "find_spec", _fake_spec)
    mock_logger = mock.Mock()
    AgiEnv.reset()
    with mock.patch.object(AgiLogger, "configure", return_value=mock_logger), \
         mock.patch.object(AgiEnv, "_init_apps", lambda self: None), \
         mock.patch.object(AgiEnv, "_init_resources", lambda self, _path: None), \
         mock.patch.object(AgiEnv, "_get_apps_repository_root", lambda self: repo_apps), \
         mock.patch.object(AgiEnv, "resolve_user_app_settings_file", lambda self, ensure_exists=False: None), \
         mock.patch.object(AgiEnv, "find_source_app_settings_file", lambda self: None):
        env = AgiEnv(apps_path=repo_apps, active_app=_NonPathActiveApp(), verbose=0)

    assert env.app == "demo_project"
    assert env.active_app == app_root.resolve()
    assert env.env_pck == agi_env_pkg.resolve()
    assert env.node_pck == agi_node_pkg.resolve()


def test_init_worker_install_type_detects_wenv_apps_path(tmp_path: Path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    share_root = fake_home / ".local" / "share" / "agilab"
    share_root.mkdir(parents=True, exist_ok=True)
    (share_root / ".agilab-path").write_text(str(tmp_path / "ignored"), encoding="utf-8")
    (fake_home / "clustershare" / "worker-user").mkdir(parents=True)
    (fake_home / "localshare").mkdir()
    env_dir = fake_home / ".agilab"
    env_dir.mkdir(parents=True, exist_ok=True)
    (env_dir / ".env").write_text("AGI_CLUSTER_ENABLED=0\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("AGI_CLUSTER_ENABLED", "0")
    monkeypatch.setenv("AGILAB_SHARE_USER", "worker-user")

    site_root = tmp_path / "site-packages"
    _configure_fake_installed_specs(monkeypatch, site_root)
    wenv_apps = tmp_path / "wenv" / "demo_worker"
    wenv_apps.mkdir(parents=True, exist_ok=True)

    mock_logger = mock.Mock()
    AgiEnv.reset()
    with mock.patch.object(AgiLogger, "configure", return_value=mock_logger), \
         mock.patch.object(AgiEnv, "_init_apps", lambda self: None), \
         mock.patch.object(AgiEnv, "_init_resources", lambda self, _path: None), \
         mock.patch.object(AgiEnv, "_get_apps_repository_root", lambda self: None), \
         mock.patch.object(AgiEnv, "resolve_user_app_settings_file", lambda self, ensure_exists=False: None), \
         mock.patch.object(AgiEnv, "find_source_app_settings_file", lambda self: None):
        env = AgiEnv(apps_path=wenv_apps, app="demo_worker", verbose=0)

    assert env.is_worker_env is True
    assert env.skip_repo_links is True
    assert env.active_app == (fake_home / "wenv" / "demo_worker")


def test_init_resolve_install_type_falls_back_when_apps_path_resolution_breaks(
    tmp_path: Path, monkeypatch
):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    share_root = fake_home / ".local" / "share" / "agilab"
    share_root.mkdir(parents=True, exist_ok=True)
    (share_root / ".agilab-path").write_text(str(tmp_path / "ignored"), encoding="utf-8")
    (fake_home / "clustershare").mkdir()
    (fake_home / "localshare").mkdir()
    env_dir = fake_home / ".agilab"
    env_dir.mkdir(parents=True, exist_ok=True)
    (env_dir / ".env").write_text("AGI_CLUSTER_ENABLED=0\n", encoding="utf-8")
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
    _configure_fake_installed_specs(monkeypatch, site_root)

    original_resolve = Path.resolve
    resolve_calls = {"repo_apps": 0}

    def _patched_resolve(self, *args, **kwargs):
        if self == repo_apps:
            resolve_calls["repo_apps"] += 1
            if resolve_calls["repo_apps"] == 2:
                raise RuntimeError("resolve broke")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", _patched_resolve, raising=False)
    mock_logger = mock.Mock()
    AgiEnv.reset()
    with mock.patch.object(AgiLogger, "configure", return_value=mock_logger), \
         mock.patch.object(AgiEnv, "_init_apps", lambda self: None), \
         mock.patch.object(AgiEnv, "_init_resources", lambda self, _path: None), \
         mock.patch.object(AgiEnv, "_get_apps_repository_root", lambda self: repo_apps), \
         mock.patch.object(AgiEnv, "resolve_user_app_settings_file", lambda self, ensure_exists=False: None), \
         mock.patch.object(AgiEnv, "find_source_app_settings_file", lambda self: None):
        env = AgiEnv(apps_path=repo_apps, app="demo_project", verbose=0)

    assert env.install_type == 0
    assert env.is_worker_env is False
    assert env.active_app == app_root.resolve()
    assert resolve_calls["repo_apps"] >= 2


def _configure_fake_installed_specs(monkeypatch, site_root: Path):
    agilab_pkg = site_root / "agilab"
    agi_env_pkg = site_root / "agi_env"
    agi_node_pkg = site_root / "agi_node"
    dispatcher_dir = agi_node_pkg / "agi_dispatcher"
    for pkg in (agilab_pkg, agi_env_pkg, agi_node_pkg, dispatcher_dir):
        pkg.mkdir(parents=True, exist_ok=True)
    (agilab_pkg / "__init__.py").write_text("", encoding="utf-8")
    (agi_env_pkg / "__init__.py").write_text("", encoding="utf-8")
    (agi_node_pkg / "__init__.py").write_text("", encoding="utf-8")
    (dispatcher_dir / "__init__.py").write_text("", encoding="utf-8")
    (dispatcher_dir / "pre_install.py").write_text("print('pre')\n", encoding="utf-8")
    (dispatcher_dir / "post_install.py").write_text("print('post')\n", encoding="utf-8")

    def _fake_spec(name):
        mapping = {
            "agilab": SimpleNamespace(origin=str(agilab_pkg / "__init__.py")),
            "agi_env": SimpleNamespace(origin=str(agi_env_pkg / "__init__.py"), submodule_search_locations=[str(agi_env_pkg)]),
            "agi_node": SimpleNamespace(origin=str(agi_node_pkg / "__init__.py"), submodule_search_locations=[str(agi_node_pkg)]),
            "agi_node.agi_dispatcher": SimpleNamespace(
                origin=str(dispatcher_dir / "__init__.py"),
                submodule_search_locations=[str(dispatcher_dir)],
            ),
        }
        if name in {"agi_core", "agi_cluster", "agi_cluster.agi_distributor.cli"}:
            raise ModuleNotFoundError(name)
        return mapping.get(name)

    monkeypatch.setattr(agi_env_module.importlib.util, "find_spec", _fake_spec)
    return agilab_pkg, agi_env_pkg, agi_node_pkg


def test_init_prefers_worker_sources_already_staged_in_wenv(tmp_path: Path, monkeypatch):
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
    (app_root / "src" / "demo" / "demo.py").write_text("class Demo:\n    pass\n", encoding="utf-8")
    (app_root / "pyproject.toml").write_text("[project]\nname='demo-project'\n", encoding="utf-8")

    wenv_worker = fake_home / "wenv" / "demo_worker" / "src" / "demo_worker"
    wenv_worker.mkdir(parents=True, exist_ok=True)
    (wenv_worker / "demo_worker.py").write_text(
        "class BaseWorker:\n    pass\n\nclass DemoWorker(BaseWorker):\n    pass\n",
        encoding="utf-8",
    )
    (wenv_worker / "pyproject.toml").write_text("[project]\nname='demo-worker'\n", encoding="utf-8")

    site_root = tmp_path / "site-packages"
    _configure_fake_installed_specs(monkeypatch, site_root)

    AgiEnv.reset()
    mock_logger = mock.Mock()
    with mock.patch.object(AgiLogger, "configure", return_value=mock_logger), \
         mock.patch.object(AgiEnv, "_init_apps", lambda self: None), \
         mock.patch.object(AgiEnv, "_init_resources", lambda self, _path: None), \
         mock.patch.object(AgiEnv, "_get_apps_repository_root", lambda self: repo_apps), \
         mock.patch.object(AgiEnv, "resolve_user_app_settings_file", lambda self, ensure_exists=False: None), \
         mock.patch.object(AgiEnv, "find_source_app_settings_file", lambda self: None), \
         mock.patch.object(AgiEnv, "_ensure_repository_app_link", lambda self: False):
        env = AgiEnv(apps_path=repo_apps, app="demo_project", verbose=0)

    assert env.app_src == env.wenv_abs / "src"
    assert env.worker_path == wenv_worker / "demo_worker.py"
    assert env.worker_pyproject == wenv_worker / "pyproject.toml"
    assert env.dataset_archive == wenv_worker / "dataset.7z"


def test_init_copies_packaged_app_when_repo_worker_is_missing(tmp_path: Path, monkeypatch):
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
    (app_root / "src" / "demo" / "demo.py").write_text("class Demo:\n    pass\n", encoding="utf-8")
    (app_root / "pyproject.toml").write_text("[project]\nname='demo-project'\n", encoding="utf-8")

    site_root = tmp_path / "site-packages"
    agilab_pkg, _agi_env_pkg, _agi_node_pkg = _configure_fake_installed_specs(monkeypatch, site_root)
    packaged_app = agilab_pkg / "apps" / "demo_project"
    (packaged_app / "src" / "demo").mkdir(parents=True, exist_ok=True)
    (packaged_app / "src" / "demo_worker").mkdir(parents=True, exist_ok=True)
    (packaged_app / "src" / "demo" / "demo.py").write_text("class Demo:\n    pass\n", encoding="utf-8")
    (packaged_app / "src" / "demo_worker" / "demo_worker.py").write_text(
        "class BaseWorker:\n    pass\n\nclass DemoWorker(BaseWorker):\n    pass\n",
        encoding="utf-8",
    )
    (packaged_app / "pyproject.toml").write_text("[project]\nname='demo-project'\n", encoding="utf-8")

    AgiEnv.reset()
    mock_logger = mock.Mock()
    with mock.patch.object(AgiLogger, "configure", return_value=mock_logger), \
         mock.patch.object(AgiEnv, "_init_apps", lambda self: None), \
         mock.patch.object(AgiEnv, "_init_resources", lambda self, _path: None), \
         mock.patch.object(AgiEnv, "_get_apps_repository_root", lambda self: repo_apps), \
         mock.patch.object(AgiEnv, "resolve_user_app_settings_file", lambda self, ensure_exists=False: None), \
         mock.patch.object(AgiEnv, "find_source_app_settings_file", lambda self: None), \
         mock.patch.object(AgiEnv, "_ensure_repository_app_link", lambda self: False):
        env = AgiEnv(apps_path=repo_apps, app="demo_project", verbose=0)

    copied_worker = app_root / "src" / "demo_worker" / "demo_worker.py"
    assert copied_worker.exists()
    assert env.worker_path == copied_worker
    assert env.worker_pyproject == copied_worker.parent / "pyproject.toml"
    assert env.dataset_archive == copied_worker.parent / "dataset.7z"


def test_init_ignores_free_threaded_request_when_runtime_lacks_support(tmp_path: Path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    share_root = fake_home / ".local" / "share" / "agilab"
    share_root.mkdir(parents=True, exist_ok=True)
    (share_root / ".agilab-path").write_text(str(tmp_path / "ignored"), encoding="utf-8")
    (fake_home / "clustershare").mkdir()
    (fake_home / "localshare").mkdir()
    env_dir = fake_home / ".agilab"
    env_dir.mkdir(parents=True, exist_ok=True)
    (env_dir / ".env").write_text(
        "IS_SOURCE_ENV=no\nIS_WORKER_ENV=0\nAGI_CLUSTER_ENABLED=0\nAGI_PYTHON_FREE_THREADED=1\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("AGI_CLUSTER_ENABLED", "0")

    repo_apps = tmp_path / "repo-apps"
    app_root = repo_apps / "demo_project"
    (app_root / "src" / "demo").mkdir(parents=True, exist_ok=True)
    (app_root / "src" / "demo" / "demo.py").write_text("class Demo:\n    pass\n", encoding="utf-8")
    (app_root / "pyproject.toml").write_text("[project]\nname='demo-project'\n", encoding="utf-8")

    wenv_worker = fake_home / "wenv" / "demo_worker" / "src" / "demo_worker"
    wenv_worker.mkdir(parents=True, exist_ok=True)
    (wenv_worker / "demo_worker.py").write_text(
        "class BaseWorker:\n    pass\n\nclass DemoWorker(BaseWorker):\n    pass\n",
        encoding="utf-8",
    )
    (wenv_worker / "pyproject.toml").write_text(
        "[project]\nname='demo-worker'\n\n[tool.freethread_info]\nis_app_freethreaded = true\n",
        encoding="utf-8",
    )

    site_root = tmp_path / "site-packages"
    _configure_fake_installed_specs(monkeypatch, site_root)

    AgiEnv.reset()
    mock_logger = mock.Mock()
    with mock.patch.object(AgiLogger, "configure", return_value=mock_logger), \
         mock.patch.object(AgiEnv, "_init_apps", lambda self: None), \
         mock.patch.object(AgiEnv, "_init_resources", lambda self, _path: None), \
         mock.patch.object(AgiEnv, "_get_apps_repository_root", lambda self: repo_apps), \
         mock.patch.object(AgiEnv, "resolve_user_app_settings_file", lambda self, ensure_exists=False: None), \
         mock.patch.object(AgiEnv, "find_source_app_settings_file", lambda self: None), \
         mock.patch.object(AgiEnv, "_ensure_repository_app_link", lambda self: False), \
         mock.patch.object(agi_env_module, "python_supports_free_threading", lambda: False):
        env = AgiEnv(apps_path=repo_apps, app="demo_project", verbose=0)

    assert env.is_free_threading_available is False
    assert env.uv_worker == env.uv


def test_content_renamer_wrapper_binds_agi_logger(monkeypatch):
    mock_logger = mock.Mock()
    monkeypatch.setattr(AgiEnv, "logger", mock_logger)

    renamer = agi_env_module.ContentRenamer({"foo": "bar"})

    assert renamer.logger is mock_logger


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


def test_source_analysis_wrappers_use_support_module(monkeypatch):
    env = object.__new__(AgiEnv)
    captured = {}

    def _fake_mapping(source, *, logger):
        captured["mapping"] = (source, logger)
        return {"Base": "demo.base"}

    def _fake_extract(base, import_mapping):
        captured["extract"] = (base, import_mapping)
        return ("Base", "demo.base")

    def _fake_full_name(node):
        captured["full_name"] = node
        return "mod.Base"

    monkeypatch.setattr(agi_env_module, "build_import_mapping", _fake_mapping)
    monkeypatch.setattr(agi_env_module, "extract_ast_base_info", _fake_extract)
    monkeypatch.setattr(agi_env_module, "build_full_attribute_name", _fake_full_name)

    name_base = ast.parse("class Child(Base):\n    pass\n").body[0].bases[0]
    attr_base = ast.parse("class Child(mod.Base):\n    pass\n").body[0].bases[0]

    mapping = env.get_import_mapping("import demo.base")
    assert mapping == {"Base": "demo.base"}
    assert captured["mapping"] == ("import demo.base", AgiEnv.logger)

    assert env.extract_base_info(name_base, mapping) == ("Base", "demo.base")
    assert captured["extract"] == (name_base, mapping)

    assert env.get_full_attribute_name(attr_base) == "mod.Base"
    assert captured["full_name"] is attr_base


def test_worker_source_wrappers_use_support_module(monkeypatch):
    env = object.__new__(AgiEnv)
    captured = {}

    def _fake_get_base_classes(module_path, class_name, *, logger, import_mapping_fn, extract_base_info_fn):
        captured["base_classes"] = (
            module_path,
            class_name,
            logger,
            import_mapping_fn,
            extract_base_info_fn,
        )
        return [("DemoWorker", "demo.worker")]

    def _fake_get_base_worker_cls(module_path, class_name, *, logger, get_base_classes_fn):
        captured["base_worker"] = (module_path, class_name, logger, get_base_classes_fn)
        return ("DemoWorker", "demo.worker")

    monkeypatch.setattr(agi_env_module, "discover_base_classes", _fake_get_base_classes)
    monkeypatch.setattr(agi_env_module, "discover_base_worker_cls", _fake_get_base_worker_cls)

    assert env.get_base_classes("worker.py", "DemoWorker") == [("DemoWorker", "demo.worker")]
    assert captured["base_classes"] == (
        "worker.py",
        "DemoWorker",
        AgiEnv.logger,
        env.get_import_mapping,
        env.extract_base_info,
    )

    assert env.get_base_worker_cls("worker.py", "DemoWorker") == ("DemoWorker", "demo.worker")
    assert captured["base_worker"] == (
        "worker.py",
        "DemoWorker",
        AgiEnv.logger,
        env.get_base_classes,
    )


def test_is_relative_to_wrapper_uses_support_module(monkeypatch, tmp_path: Path):
    captured = {}

    def _fake_is_relative_to(path, other):
        captured["args"] = (path, other)
        return True

    monkeypatch.setattr(agi_env_module, "is_path_relative_to", _fake_is_relative_to)

    parent = tmp_path / "parent"
    child = parent / "child"
    assert agi_env_module._is_relative_to(child, parent) is True
    assert captured["args"] == (child, parent)


def test_read_gitignore_and_check_internet_cover_success_and_failure(tmp_path: Path, monkeypatch):
    env = object.__new__(AgiEnv)
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("*.pyc\nbuild/\n", encoding="utf-8")
    captured = {}

    def _fake_load_gitignore(path):
        captured["path"] = path
        return "gitignore-spec"

    monkeypatch.setattr(agi_env_module, "load_gitignore_spec", _fake_load_gitignore)

    assert env.read_gitignore(gitignore) == "gitignore-spec"
    assert captured["path"] == gitignore
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
            raise agi_env_module.py7zr.exceptions.Bad7zFile("bad archive")

    monkeypatch.setattr(agi_env_module.py7zr, "SevenZipFile", _BrokenSevenZip)

    with pytest.raises(RuntimeError, match="Extraction failed"):
        env.unzip_data(archive, "dataset/demo", force_extract=True)


def test_unzip_data_propagates_unexpected_extraction_bug(tmp_path: Path, monkeypatch):
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
            raise ValueError("extract bug")

    monkeypatch.setattr(agi_env_module.py7zr, "SevenZipFile", _BrokenSevenZip)

    with pytest.raises(ValueError, match="extract bug"):
        env.unzip_data(archive, "dataset/demo", force_extract=True)


def test_locate_agilab_installation_wrapper_uses_installation_support(monkeypatch, tmp_path: Path):
    expected = tmp_path / "repo-root"
    captured = {}

    def _fake_locate(**kwargs):
        captured.update(kwargs)
        return expected

    monkeypatch.setattr(agi_env_module, "locate_agilab_installation_path", _fake_locate)

    assert AgiEnv.locate_agilab_installation() == expected
    assert captured["module_file"] == agi_env_module.__file__
    assert captured["find_spec"] == agi_env_module.importlib.util.find_spec


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
    source = apps_path / "flight_telemetry_project"
    (source / "src" / "flight").mkdir(parents=True)
    (source / "src" / "flight_worker").mkdir(parents=True)
    (source / ".venv").mkdir(parents=True)
    (source / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (source / "README.md").write_text("flight_telemetry_project uses Flight and flight_worker.\n", encoding="utf-8")
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

    env.clone_project(Path("flight_telemetry_project"), Path("demo_project"))

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

    existing = env.apps_path / "flight_telemetry_project"
    existing.mkdir()
    dest = env.apps_path / "demo_project"
    dest.mkdir()
    env.clone_project(Path("flight_telemetry_project"), Path("demo_project"))
    assert dest.exists()


def test_run_supports_export_only_and_fire_and_forget(tmp_path: Path, monkeypatch):
    mock_logger = mock.Mock()
    monkeypatch.setattr(AgiEnv, "logger", mock_logger)
    monkeypatch.setattr(AgiEnv, "verbose", 1, raising=False)

    noop = asyncio.run(AgiEnv.run('export PATH="~/.local/bin:$PATH";', tmp_path))
    assert noop == ""

    created = {}

    class _Proc:
        async def wait(self):
            return 0

    async def _fake_exec(*args, **kwargs):
        created["cmd"] = args
        return _Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    monkeypatch.setattr(asyncio, "create_task", lambda coro: created.setdefault("coro", coro))
    result = asyncio.run(AgiEnv.run("echo hi", tmp_path, wait=False))
    assert result == 0
    assert created["coro"] is not None
    created["coro"].close()


def test_run_fire_and_forget_applies_exported_path_and_uv_preview_flag(tmp_path: Path, monkeypatch):
    process_env = {"PATH": "/usr/bin"}
    created: dict[str, object] = {}

    class _Proc:
        async def wait(self):
            return 0

    async def _fake_exec(*args, **kwargs):
        created["cmd"] = args
        created["kwargs"] = kwargs
        return _Proc()

    monkeypatch.setattr(AgiEnv, "_build_env", staticmethod(lambda _venv: process_env))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    monkeypatch.setattr(
        asyncio,
        "create_task",
        lambda coro: created.setdefault("task", asyncio.get_running_loop().create_task(coro)),
    )

    result = asyncio.run(AgiEnv.run('export PATH="~/.local/bin:$PATH"; uv sync', tmp_path, wait=False))

    assert result == 0
    assert created["cmd"] == ("uv", "--preview-features", "extra-build-dependencies", "sync")
    assert process_env["PATH"].startswith(str(Path.home() / ".local/bin"))
    assert created["kwargs"]["cwd"] == str(tmp_path)


def test_run_wait_rewrites_exported_path_and_uv_preview_flag(tmp_path: Path, monkeypatch):
    process_env = {"PATH": "/usr/bin"}
    created: dict[str, object] = {}

    class _Stream:
        async def readline(self):
            return b""

    class _Proc:
        def __init__(self):
            self.stdout = _Stream()
            self.stderr = _Stream()
            self.returncode = 0

        async def wait(self):
            return self.returncode

    async def _fake_exec(*args, **kwargs):
        created["args"] = args
        created["kwargs"] = kwargs
        return _Proc()

    monkeypatch.setattr(AgiEnv, "_build_env", staticmethod(lambda _venv: process_env))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

    result = asyncio.run(AgiEnv.run('export PATH="~/.local/bin:$PATH"; uv sync', tmp_path, wait=True))

    assert result == ""
    assert created["args"] == ("uv", "--preview-features", "extra-build-dependencies", "sync")
    assert process_env["PATH"].startswith(str(Path.home() / ".local/bin"))
    assert created["kwargs"]["cwd"] == str(tmp_path)


def test_run_wait_shell_fallback_uses_plain_callback_and_skips_blank_lines(tmp_path: Path, monkeypatch):
    streamed: list[str] = []

    class _Stream:
        def __init__(self, lines):
            self._lines = list(lines)

        async def readline(self):
            if self._lines:
                return self._lines.pop(0)
            return b""

    class _Proc:
        def __init__(self):
            self.stdout = _Stream([b"\n", b"stdout line\n", b""])
            self.stderr = _Stream([b"\n", b"stderr line\n", b""])
            self.returncode = 0

        async def wait(self):
            return self.returncode

    async def _unexpected_exec(*args, **kwargs):
        raise AssertionError("plain exec should not be used for shell syntax")

    async def _fake_shell(cmd, **kwargs):
        return _Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _unexpected_exec)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", _fake_shell)

    result = asyncio.run(AgiEnv.run("echo hi; echo bye", tmp_path, wait=True, log_callback=streamed.append))

    assert result == "stdout line\nstderr line"
    assert streamed == ["stdout line", "stderr line"]


def test_run_wait_nonzero_pip_network_failure_adds_hint(tmp_path: Path, monkeypatch):
    mock_logger = mock.Mock()
    monkeypatch.setattr(AgiEnv, "logger", mock_logger)

    class _Stream:
        def __init__(self, lines):
            self._lines = list(lines)

        async def readline(self):
            if self._lines:
                return self._lines.pop(0)
            return b""

    class _Proc:
        def __init__(self):
            self.stdout = _Stream([b""])
            self.stderr = _Stream(
                [
                    b"ERROR: failed to establish a new connection\n",
                    b"building wheel failed\n",
                    b"",
                ]
            )
            self.returncode = 1

        async def wait(self):
            return self.returncode

    async def _fake_exec(*args, **kwargs):
        return _Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(AgiEnv.run("pip install hatchling", tmp_path, wait=True))

    assert "pip could not reach the package index" in str(exc_info.value)
    mock_logger.error.assert_any_call("Command failed with exit code %s: %s", 1, "pip install hatchling")


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

    async def _unexpected_exec(*args, **kwargs):
        raise AssertionError("plain exec should not be used for shell syntax")

    async def _fake_shell(cmd, **kwargs):
        return _FakeProc()

    monkeypatch.setattr(AgiEnv, "_build_env", staticmethod(lambda _venv: dict(process_env)))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _unexpected_exec)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", _fake_shell)

    stdout, stderr = asyncio.run(
        AgiEnv._run_bg(
            "uv pip install demo; true",
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


def test_log_info_uses_logger_when_available(monkeypatch):
    fake_logger = mock.Mock()
    monkeypatch.setattr(AgiEnv, "logger", fake_logger)

    AgiEnv.log_info(123)

    fake_logger.info.assert_called_once_with("123")


def test_log_info_prints_when_logger_missing(monkeypatch, capsys):
    monkeypatch.setattr(AgiEnv, "logger", None)

    AgiEnv.log_info("hello")

    assert capsys.readouterr().out.strip() == "hello"


def test_build_env_delegates_instance_pythonpath_entries(monkeypatch, tmp_path: Path):
    captured = {}
    fake_instance = object.__new__(AgiEnv)
    fake_instance._pythonpath_entries = [str(tmp_path / "instance-src")]
    monkeypatch.setattr(AgiEnv, "_instance", fake_instance, raising=False)
    monkeypatch.setenv("UV_RUN_RECURSION_DEPTH", "2")

    def _fake_builder(**kwargs):
        captured.update(kwargs)
        return {"PATH": "demo"}

    monkeypatch.setattr(agi_env_module, "build_subprocess_env", _fake_builder)

    result = AgiEnv._build_env(tmp_path)

    assert result == {"PATH": "demo"}
    assert captured["venv"] == tmp_path
    assert captured["pythonpath_entries"] == [str(tmp_path / "instance-src")]
    assert captured["sys_prefix"] == sys.prefix
    assert captured["base_env"]["UV_RUN_RECURSION_DEPTH"] == "2"


def test_build_env_delegates_class_pythonpath_entries_when_instance_missing(monkeypatch, tmp_path: Path):
    captured = {}
    class_entries = [str(tmp_path / "class-src")]
    monkeypatch.setattr(AgiEnv, "_instance", None, raising=False)
    monkeypatch.setattr(AgiEnv, "_pythonpath_entries", class_entries, raising=False)

    def _fake_builder(**kwargs):
        captured.update(kwargs)
        return {"PYTHONPATH": "demo"}

    monkeypatch.setattr(agi_env_module, "build_subprocess_env", _fake_builder)

    result = AgiEnv._build_env()

    assert result == {"PYTHONPATH": "demo"}
    assert captured["venv"] is None
    assert captured["pythonpath_entries"] == class_entries


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

    assert env.share_root_path() == fake_home / "clustershare"
    assert env.resolve_share_path(None) == fake_home / "clustershare"
    assert env.resolve_share_path("demo/data") == fake_home / "clustershare" / "demo" / "data"
    assert env.resolve_share_path("/tmp/absolute") == Path("/tmp/absolute").resolve(strict=False)


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
        "AGI_CLUSTER_SHARE=cluster_mount\nSTREAMLIT_SERVER_MAX_MESSAGE_SIZE=256\nIS_SOURCE_ENV=yes\n",
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


def test_get_projects_returns_sorted_names_when_glob_order_varies(tmp_path: Path, monkeypatch):
    (tmp_path / "zeta_project").mkdir()
    (tmp_path / "alpha_project").mkdir()

    real_glob = agi_env_module.Path.glob

    def _fake_glob(self: Path, pattern: str):
        if self == tmp_path and pattern == "*_project":
            return iter([tmp_path / "zeta_project", tmp_path / "alpha_project"])
        return real_glob(self, pattern)

    monkeypatch.setattr(agi_env_module.Path, "glob", _fake_glob)

    env = object.__new__(AgiEnv)

    assert env.get_projects(tmp_path) == ["alpha_project", "zeta_project"]


def test_apps_repository_root_wrapper_uses_repository_support(monkeypatch):
    env = object.__new__(AgiEnv)
    env.envars = {"APPS_REPOSITORY": "/tmp/repo"}
    captured = {}

    def _fake_get_apps_repository_root(*, envars, environ, logger, fix_windows_drive_fn):
        captured["args"] = {
            "envars": envars,
            "environ": environ,
            "logger": logger,
            "fix_windows_drive_fn": fix_windows_drive_fn,
        }
        return Path("/tmp/repo/src/agilab/apps")

    monkeypatch.setattr(agi_env_module, "resolve_apps_repository_root", _fake_get_apps_repository_root)

    assert env._get_apps_repository_root() == Path("/tmp/repo/src/agilab/apps")
    assert captured["args"]["envars"] == env.envars
    assert captured["args"]["environ"] is os.environ
    assert captured["args"]["logger"] == AgiEnv.logger
    assert captured["args"]["fix_windows_drive_fn"] is agi_env_module._fix_windows_drive


def test_pythonpath_helper_wrappers_use_repository_support(monkeypatch, tmp_path: Path):
    env = object.__new__(AgiEnv)
    env.env_pck = tmp_path / "envpkg"
    env.node_pck = tmp_path / "nodepkg"
    env.core_pck = tmp_path / "corepkg"
    env.cluster_pck = tmp_path / "clusterpkg"
    env.dist_abs = tmp_path / "dist"
    env.app_src = tmp_path / "app_src"
    env.wenv_abs = tmp_path / "wenv"
    env.agilab_pck = tmp_path / "agilab_pck"
    captured = {}

    def _fake_collect(**kwargs):
        captured["collect"] = kwargs
        return ["/tmp/alpha", "/tmp/beta"]

    def _fake_configure(entries, *, sys_path, environ):
        captured["configure"] = {
            "entries": entries,
            "sys_path": sys_path,
            "environ": environ,
        }

    def _fake_dedupe(paths):
        captured["dedupe"] = list(paths)
        return ["/tmp/unique"]

    monkeypatch.setattr(agi_env_module, "build_pythonpath_entries", _fake_collect)
    monkeypatch.setattr(agi_env_module, "apply_pythonpath_entries", _fake_configure)
    monkeypatch.setattr(agi_env_module, "dedupe_existing_paths", _fake_dedupe)
    monkeypatch.setattr(agi_env_module.sys, "path", ["/existing"], raising=False)
    monkeypatch.setenv("PYTHONPATH", "/existing")

    entries = env._collect_pythonpath_entries()
    env._configure_pythonpath(entries)

    assert entries == ["/tmp/alpha", "/tmp/beta"]
    assert captured["collect"]["env_pck"] == env.env_pck
    assert captured["collect"]["node_pck"] == env.node_pck
    assert captured["collect"]["dedupe_paths_fn"] == env._dedupe_paths
    assert env._pythonpath_entries == entries
    assert captured["configure"]["entries"] == entries
    assert captured["configure"]["sys_path"] is agi_env_module.sys.path
    assert captured["configure"]["environ"] is os.environ
    assert env._dedupe_paths([Path("/tmp/demo")]) == ["/tmp/unique"]


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
