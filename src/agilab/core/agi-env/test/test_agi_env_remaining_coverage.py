from __future__ import annotations

import builtins
import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import agi_env.agi_env as agi_env_module
import pytest
from agi_env import AgiEnv
from agi_env.agi_logger import AgiLogger


MODULE_PATH = Path("src/agilab/core/agi-env/src/agi_env/agi_env.py").resolve()


def _load_agi_env_variant(
    module_name: str,
    monkeypatch,
    *,
    fail_imports: set[str] | None = None,
    formatted_tb_type=None,
):
    fail_imports = fail_imports or set()
    real_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in fail_imports:
            raise ImportError(f"forced missing {name}")
        if name == "IPython.core.ultratb" and formatted_tb_type is not None:
            return SimpleNamespace(FormattedTB=formatted_tb_type)
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_agi_env_import_fallbacks_cover_optional_ipython_and_pwd(monkeypatch):
    module = _load_agi_env_variant(
        "agi_env.agi_env_optional_fallbacks",
        monkeypatch,
        fail_imports={"IPython.core.ultratb", "pwd"},
    )

    assert module.FormattedTB is None
    assert module.pwd is None


def test_agi_env_import_honours_call_pdb_override_and_color_scheme(monkeypatch):
    captured: dict[str, object] = {}

    class _FakeFormattedTB:
        def __init__(self, mode, call_pdb, color_scheme=None):
            captured["mode"] = mode
            captured["call_pdb"] = call_pdb
            captured["color_scheme"] = color_scheme

    monkeypatch.setenv("AGILAB_CALL_PDB", "yes")
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: False), raising=False)

    module = _load_agi_env_variant(
        "agi_env.agi_env_formatted_tb_variant",
        monkeypatch,
        formatted_tb_type=_FakeFormattedTB,
    )

    assert module.sys.excepthook is not None
    assert captured == {
        "mode": "Verbose",
        "call_pdb": True,
        "color_scheme": "NoColor",
    }


def test_agi_env_remaining_wrappers_delegate_support_helpers(monkeypatch, tmp_path: Path):
    env = object.__new__(AgiEnv)
    env.app = "demo_project"
    env.app_src = tmp_path / "demo_project"
    env.active_app = tmp_path / "apps" / "demo_project"
    env.apps_path = tmp_path / "apps"
    env.builtin_apps_path = tmp_path / "apps" / "builtin"
    env.apps_repository_root = tmp_path / "repo_apps"
    env.home_abs = tmp_path / "home"
    env.resources_path = tmp_path / ".agilab"
    env.envars = {"APPS_PATH": str(env.apps_path)}
    env.app_data_rel = tmp_path / "share" / "demo"
    env.agi_share_path_abs = tmp_path / "share"
    env.user = "agi"
    env.projects = ["demo_project"]

    captured: dict[str, object] = {}

    def _capture_app_settings_source_roots(**kwargs):
        captured["app_settings_source_roots"] = kwargs
        return [tmp_path / "src"]

    def _capture_mode(mode):
        captured["mode"] = mode
        return 7

    def _capture_locate(**kwargs):
        captured["locate"] = kwargs
        return tmp_path / "install"

    def _capture_copy_existing_projects(src, dst, **kwargs):
        captured["copy_existing_projects"] = (src, dst, kwargs)

    def _capture_clone_project(*args, **kwargs):
        captured["clone_project"] = (args, kwargs)

    def _capture_clone_directory(*args, **kwargs):
        captured["clone_directory"] = (args, kwargs)

    def _capture_read_gitignore(gitignore_path):
        captured["read_gitignore"] = gitignore_path
        return "spec"

    def _capture_unzip_data(*args, **kwargs):
        captured["unzip_data"] = (args, kwargs)

    monkeypatch.setattr(
        agi_env_module,
        "app_settings_source_roots",
        _capture_app_settings_source_roots,
    )
    monkeypatch.setattr(agi_env_module, "mode_to_int", _capture_mode)
    monkeypatch.setattr(
        agi_env_module,
        "locate_agilab_installation_path",
        _capture_locate,
    )
    monkeypatch.setattr(
        agi_env_module,
        "copy_missing_projects",
        _capture_copy_existing_projects,
    )
    monkeypatch.setattr(
        agi_env_module,
        "clone_app_project",
        _capture_clone_project,
    )
    monkeypatch.setattr(
        agi_env_module,
        "clone_project_directory",
        _capture_clone_directory,
    )
    monkeypatch.setattr(
        agi_env_module,
        "load_gitignore_spec",
        _capture_read_gitignore,
    )
    monkeypatch.setattr(
        agi_env_module,
        "extract_dataset_archive",
        _capture_unzip_data,
    )

    source_roots = env._app_settings_source_roots("other_project")
    mode_value = env.mode2int("pcd")
    located = AgiEnv.locate_agilab_installation()
    located_alias = AgiEnv.locate_agi_installation()
    env.copy_existing_projects(tmp_path / "src_apps", tmp_path / "dst_apps")
    env.clone_project(Path("flight_telemetry_project"), Path("demo_project"))
    env.clone_directory(Path("src"), Path("dst"), {"old": "new"}, "spec", Path("root"))
    gitignore = env.read_gitignore(tmp_path / ".gitignore")
    env.unzip_data(tmp_path / "dataset.7z", "dataset/demo")

    assert source_roots == [tmp_path / "src"]
    assert captured["app_settings_source_roots"]["target_app"] == "other_project"
    assert mode_value == 7
    assert captured["mode"] == "pcd"
    assert located == tmp_path / "install"
    assert located_alias == tmp_path / "install"
    assert captured["copy_existing_projects"][0] == tmp_path / "src_apps"
    assert captured["copy_existing_projects"][1] == tmp_path / "dst_apps"
    clone_args, clone_kwargs = captured["clone_project"]
    assert clone_args[:2] == (Path("flight_telemetry_project"), Path("demo_project"))
    assert clone_kwargs["apps_path"] == env.apps_path
    dir_args, dir_kwargs = captured["clone_directory"]
    assert dir_args[:5] == (Path("src"), Path("dst"), {"old": "new"}, "spec", Path("root"))
    assert dir_kwargs["replace_content_fn"] == env.replace_content
    assert gitignore == "spec"
    assert captured["read_gitignore"] == tmp_path / ".gitignore"
    unzip_args, unzip_kwargs = captured["unzip_data"]
    assert unzip_args[0] == tmp_path / "dataset.7z"
    assert unzip_kwargs["extract_to"] == "dataset/demo"
    assert unzip_kwargs["app_data_rel"] == env.app_data_rel


def _prepare_fake_home(tmp_path: Path, monkeypatch, *, env_text: str) -> Path:
    for key in (
        "AGI_CLUSTER_ENABLED",
        "AGI_CLUSTER_SHARE",
        "AGI_LOCAL_SHARE",
        "AGILAB_SHARE_USER",
        "APPS_PATH",
        "APPS_REPOSITORY",
        "IS_SOURCE_ENV",
        "IS_WORKER_ENV",
    ):
        monkeypatch.delenv(key, raising=False)
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    share_root = fake_home / ".local" / "share" / "agilab"
    share_root.mkdir(parents=True, exist_ok=True)
    (share_root / ".agilab-path").write_text(str(tmp_path / "ignored"), encoding="utf-8")
    (fake_home / "clustershare").mkdir()
    (fake_home / "localshare").mkdir()
    env_dir = fake_home / ".agilab"
    env_dir.mkdir(parents=True, exist_ok=True)
    (env_dir / ".env").write_text(env_text, encoding="utf-8")
    monkeypatch.setenv("HOME", str(fake_home))
    return fake_home


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
            "agi_env": SimpleNamespace(
                origin=str(agi_env_pkg / "__init__.py"),
                submodule_search_locations=[str(agi_env_pkg)],
            ),
            "agi_node": SimpleNamespace(
                origin=str(agi_node_pkg / "__init__.py"),
                submodule_search_locations=[str(agi_node_pkg)],
            ),
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


def _build_demo_app(app_root: Path, *, with_worker: bool = True) -> None:
    (app_root / "src" / "demo").mkdir(parents=True, exist_ok=True)
    (app_root / "src" / "demo" / "demo.py").write_text("class Demo:\n    pass\n", encoding="utf-8")
    if with_worker:
        (app_root / "src" / "demo_worker").mkdir(parents=True, exist_ok=True)
        (app_root / "src" / "demo_worker" / "demo_worker.py").write_text(
            "class BaseWorker:\n    pass\n\nclass DemoWorker(BaseWorker):\n    pass\n",
            encoding="utf-8",
        )
    (app_root / "pyproject.toml").write_text("[project]\nname='demo-project'\n", encoding="utf-8")


def test_agi_env_misc_wrappers_cover_remaining_helper_branches(tmp_path: Path):
    env = object.__new__(AgiEnv)
    env.hw_rapids_capable = True
    env._share_root_cache = None
    env.agi_share_path = ""
    env.home_abs = tmp_path
    env.target = "demo"
    env.agilab_pck = tmp_path / "agilab"
    env.agilab_pck.mkdir()
    env.read_agilab_path = lambda: None
    mock_logger = mock.Mock()
    AgiEnv.logger = mock_logger

    errors = env.humanize_validation_errors(
        SimpleNamespace(
            errors=lambda: [
                {
                    "loc": ("settings", "name"),
                    "msg": "invalid",
                    "type": "value_error",
                    "ctx": {"input_value": "bad"},
                }
            ]
        )
    )

    assert "Received: `bad`" in errors[0]
    assert env.mode2str(0b0111) == "rdcp"
    assert AgiEnv._app_settings_aliases("demo_project") == {"demo_project", "demo_worker"}
    assert AgiEnv._candidate_app_settings_path(tmp_path) is None

    envars = {"CLUSTER_CREDENTIALS": "agi:secret"}
    env.init_envars_app(envars)
    assert env.CLUSTER_CREDENTIALS == "agi:secret"
    assert envars["CLUSTER_CREDENTIALS"] == env.CLUSTER_CREDENTIALS

    with pytest.raises(RuntimeError, match="agi_share_path is not configured"):
        env.share_root_path()


def test_get_projects_handles_invalid_missing_and_failed_dangling_cleanup(tmp_path: Path, monkeypatch):
    apps_root = tmp_path / "apps"
    apps_root.mkdir()
    dangling = apps_root / "dangling_project"
    dangling.symlink_to(apps_root / "missing_project")
    mock_logger = mock.Mock()
    monkeypatch.setattr(AgiEnv, "logger", mock_logger, raising=False)
    env = object.__new__(AgiEnv)
    original_unlink = Path.unlink

    def _broken_unlink(self, *args, **kwargs):
        if self == dangling:
            raise OSError("busy")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(agi_env_module.Path, "unlink", _broken_unlink, raising=False)

    projects = env.get_projects(object(), tmp_path / "does-not-exist", apps_root)

    assert projects == []
    assert mock_logger.warning.called


def test_create_symlink_replaces_existing_regular_file(tmp_path: Path, monkeypatch):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    dest = tmp_path / "dest"
    dest.write_text("occupied", encoding="utf-8")
    mock_logger = mock.Mock()
    monkeypatch.setattr(AgiEnv, "logger", mock_logger, raising=False)

    AgiEnv.create_symlink(src_dir, dest)

    assert dest.is_symlink()
    assert mock_logger.warning.called


def test_change_app_handles_none_current_app_and_path_fallbacks(tmp_path: Path, monkeypatch):
    apps_root = tmp_path / "apps"
    apps_root.mkdir()
    env = object.__new__(AgiEnv)
    env.app = None
    env.apps_path = apps_root
    captured: list[dict[str, object]] = []

    def _fake_init(self, *args, **kwargs):
        captured.append(kwargs)

    with mock.patch.object(AgiEnv, "__init__", _fake_init, create=True):
        env.change_app("demo_project")

    assert captured[-1]["app"] == "demo_project"

    class _BadCurrent:
        def __str__(self) -> str:
            return "trigger-current"

    class _BadRequested:
        def __str__(self) -> str:
            return "trigger-request"

    class _FakePath:
        def __init__(self, value):
            if value in {"trigger-current", "trigger-request"}:
                raise ValueError("bad path")
            self._path = Path(value)

        @property
        def name(self):
            return self._path.name

        @property
        def parent(self):
            return self._path.parent

    env.app = _BadCurrent()
    monkeypatch.setattr(agi_env_module, "Path", _FakePath)

    with mock.patch.object(AgiEnv, "__init__", _fake_init, create=True):
        env.change_app(_BadRequested())

    assert captured[-1]["app"] == "trigger-request"


def test_init_covers_verbose_modes_invalid_app_suffix_and_active_app_resolve_fallback(
    tmp_path: Path, monkeypatch
):
    _prepare_fake_home(
        tmp_path,
        monkeypatch,
        env_text="IS_SOURCE_ENV=no\nIS_WORKER_ENV=0\nAGI_CLUSTER_ENABLED=0\n",
    )
    monkeypatch.setenv("AGI_CLUSTER_ENABLED", "0")
    repo_apps = tmp_path / "repo-apps"
    app_root = repo_apps / "demo_project"
    _build_demo_app(app_root)
    site_root = tmp_path / "site-packages"
    _configure_fake_installed_specs(monkeypatch, site_root)

    mock_logger = mock.Mock()
    AgiEnv.reset()
    with mock.patch.object(AgiLogger, "configure", return_value=mock_logger), \
         mock.patch.object(AgiEnv, "_init_apps", lambda self: None), \
         mock.patch.object(AgiEnv, "_init_resources", lambda self, _path: None), \
         mock.patch.object(AgiEnv, "_get_apps_repository_root", lambda self: repo_apps), \
         mock.patch.object(AgiEnv, "resolve_user_app_settings_file", lambda self, ensure_exists=False: None), \
         mock.patch.object(AgiEnv, "find_source_app_settings_file", lambda self: None):
        env_quiet = AgiEnv(apps_path=repo_apps, app="demo_project", verbose=None)
    assert env_quiet.uv == "uv --quiet"

    AgiEnv.reset()
    with mock.patch.object(AgiLogger, "configure", return_value=mock_logger), \
         mock.patch.object(AgiEnv, "_init_apps", lambda self: None), \
         mock.patch.object(AgiEnv, "_init_resources", lambda self, _path: None), \
         mock.patch.object(AgiEnv, "_get_apps_repository_root", lambda self: repo_apps), \
         mock.patch.object(AgiEnv, "resolve_user_app_settings_file", lambda self, ensure_exists=False: None), \
         mock.patch.object(AgiEnv, "find_source_app_settings_file", lambda self: None):
        env_verbose = AgiEnv(apps_path=repo_apps, app="demo_project", verbose=3)

    assert env_verbose.uv == "uv --verbose"

    AgiEnv.reset()
    with mock.patch.object(AgiLogger, "configure", return_value=mock_logger), \
         mock.patch.object(AgiEnv, "_get_apps_repository_root", lambda self: repo_apps):
        with pytest.raises(ValueError, match="must end with '_project' or '_worker'"):
            AgiEnv(apps_path=repo_apps, app="demo", verbose=0)

    original_resolve = agi_env_module.Path.resolve

    def _patched_resolve(self, *args, **kwargs):
        if self == app_root:
            raise OSError("resolve failed")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(agi_env_module.Path, "resolve", _patched_resolve, raising=False)
    AgiEnv.reset()
    with mock.patch.object(AgiLogger, "configure", return_value=mock_logger), \
         mock.patch.object(AgiEnv, "_init_apps", lambda self: None), \
         mock.patch.object(AgiEnv, "_init_resources", lambda self, _path: None), \
         mock.patch.object(AgiEnv, "_get_apps_repository_root", lambda self: repo_apps), \
         mock.patch.object(AgiEnv, "resolve_user_app_settings_file", lambda self, ensure_exists=False: None), \
         mock.patch.object(AgiEnv, "find_source_app_settings_file", lambda self: None):
        env = AgiEnv(apps_path=repo_apps, app="demo_project", verbose=0)

    assert env.active_app == app_root


def test_init_missing_worker_and_empty_projects_log_before_invalid_scheduler(tmp_path: Path, monkeypatch):
    _prepare_fake_home(
        tmp_path,
        monkeypatch,
        env_text="IS_SOURCE_ENV=1\nAGI_CLUSTER_ENABLED=0\nAGI_SCHEDULER_IP=bad-ip\n",
    )
    fake_apps = tmp_path / "apps"
    _build_demo_app(fake_apps / "demo_project", with_worker=False)
    mock_logger = mock.Mock()
    AgiEnv.reset()

    with mock.patch.object(AgiLogger, "configure", return_value=mock_logger), \
         mock.patch.object(AgiEnv, "_init_apps", lambda self: None), \
         mock.patch.object(AgiEnv, "_get_apps_repository_root", lambda self: None), \
         mock.patch.object(AgiEnv, "get_projects", lambda self, *args: []):
        with pytest.raises(ValueError, match="Invalid scheduler IP address"):
            AgiEnv(apps_path=fake_apps, app="demo_project", verbose=0)

    info_messages = [" ".join(str(part) for part in call.args) for call in mock_logger.info.call_args_list]
    assert any("Missing DemoWorker definition" in message for message in info_messages)
    assert any("Could not find any target project app" in message for message in info_messages)


def test_init_preserves_existing_dataset_without_stamp_and_uses_windows_export_bin(tmp_path: Path, monkeypatch):
    fake_home = _prepare_fake_home(
        tmp_path,
        monkeypatch,
        env_text="IS_SOURCE_ENV=1\nAGI_CLUSTER_ENABLED=0\n",
    )
    fake_apps = tmp_path / "apps"
    app_root = fake_apps / "demo_project"
    _build_demo_app(app_root)
    worker_dir = app_root / "src" / "demo_worker"
    dataset_archive = worker_dir / "dataset.7z"
    dataset_archive.write_text("archive", encoding="utf-8")
    dataset_root = fake_home / "localshare" / "demo" / "dataset"
    dataset_root.mkdir(parents=True)
    (dataset_root / "existing.csv").write_text("value\n", encoding="utf-8")
    mock_logger = mock.Mock()
    unzip_calls: list[tuple[Path, object]] = []
    original_sys_path = list(sys.path)
    demo_src = app_root / "src"
    if str(demo_src) in sys.path:
        sys.path.remove(str(demo_src))
    AgiEnv.reset()

    try:
        with mock.patch.object(AgiLogger, "configure", return_value=mock_logger), \
             mock.patch.object(AgiEnv, "_init_apps", lambda self: None), \
             mock.patch.object(AgiEnv, "unzip_data", lambda self, archive, extract_to, force_extract=False: unzip_calls.append((archive, extract_to))):
            env = AgiEnv(apps_path=fake_apps, app="demo_project", verbose=0)
        assert unzip_calls == []
        assert str(demo_src) in sys.path
        assert env.export_local_bin == 'export PATH="~/.local/bin:$PATH";'
    finally:
        sys.path[:] = original_sys_path


def test_init_dataset_stamp_probe_failure_appends_sys_path_and_sets_windows_export_bin(
    tmp_path: Path, monkeypatch
):
    fake_home = _prepare_fake_home(
        tmp_path,
        monkeypatch,
        env_text="IS_SOURCE_ENV=1\nAGI_CLUSTER_ENABLED=0\n",
    )
    fake_apps = tmp_path / "apps"
    app_root = fake_apps / "demo_project"
    _build_demo_app(app_root)
    worker_dir = app_root / "src" / "demo_worker"
    dataset_archive = worker_dir / "dataset.7z"
    dataset_archive.write_text("archive", encoding="utf-8")
    dataset_root = fake_home / "localshare" / "demo" / "dataset"
    dataset_root.mkdir(parents=True)
    (dataset_root / "existing.csv").write_text("value\n", encoding="utf-8")
    stamp_path = dataset_root / ".agilab_dataset_stamp"
    stamp_path.write_text("stamp", encoding="utf-8")

    original_stat = agi_env_module.Path.stat
    original_os_name = agi_env_module.os.name
    original_sys_path = list(sys.path)
    demo_src = app_root / "src"
    if str(demo_src) in sys.path:
        sys.path.remove(str(demo_src))

    def _patched_stat(self, *args, **kwargs):
        if self == stamp_path and not args and not kwargs:
            raise OSError("stamp stat failed")
        return original_stat(self, *args, **kwargs)

    def _configure_worker_runtime(self, **_kwargs):
        self.target = "demo"
        self.target_worker = "demo_worker"
        self.target_worker_class = "DemoWorker"
        self.app_src = demo_src
        self.worker_path = worker_dir / "demo_worker.py"
        self.worker_pyproject = worker_dir / "pyproject.toml"
        self.dataset_archive = dataset_archive
        self.wenv_abs = fake_home / "wenv" / "demo_worker"
        self.dist_abs = self.wenv_abs / "dist"

    def _init_apps_and_flip_windows(_self):
        agi_env_module.os.name = "nt"

    monkeypatch.setattr(agi_env_module.Path, "stat", _patched_stat, raising=False)
    mock_logger = mock.Mock()
    unzip_calls: list[tuple[Path, object]] = []
    AgiEnv.reset()

    try:
        with mock.patch.object(AgiLogger, "configure", return_value=mock_logger), \
             mock.patch.object(AgiEnv, "_init_resources", lambda self, _path: None), \
             mock.patch.object(AgiEnv, "_configure_worker_runtime", _configure_worker_runtime), \
             mock.patch.object(AgiEnv, "_init_apps", _init_apps_and_flip_windows), \
             mock.patch.object(AgiEnv, "get_base_worker_cls", lambda self, *_args: ("BaseWorker", None)), \
             mock.patch.object(AgiEnv, "get_projects", lambda self, *_args: ["demo_project"]), \
             mock.patch.object(AgiEnv, "_get_apps_repository_root", lambda self: None), \
             mock.patch.object(AgiEnv, "unzip_data", lambda self, archive, extract_to, force_extract=False: unzip_calls.append((archive, extract_to))):
            env = AgiEnv(apps_path=fake_apps, app="demo_project", verbose=0)

        assert unzip_calls == []
        assert str(demo_src) in sys.path
        assert env.export_local_bin == ""
    finally:
        agi_env_module.os.name = original_os_name
        sys.path[:] = original_sys_path


def test_init_resources_logs_warning_when_legacy_resource_cannot_be_removed(tmp_path: Path, monkeypatch):
    env = object.__new__(AgiEnv)
    env.resources_path = tmp_path / ".agilab"
    env.resources_path.mkdir(parents=True)
    env.st_resources = tmp_path / "resources"
    env.st_resources.mkdir()
    env.is_source_env = True
    legacy = env.resources_path / "code_editor.scss"
    legacy.write_text("body {}\n", encoding="utf-8")
    resources_src = tmp_path / "src_resources"
    resources_src.mkdir()
    (resources_src / ".env").write_text("AGI_CLUSTER_ENABLED=0\n", encoding="utf-8")
    mock_logger = mock.Mock()
    monkeypatch.setattr(AgiEnv, "logger", mock_logger, raising=False)
    original_unlink = agi_env_module.Path.unlink

    def _broken_unlink(self, *args, **kwargs):
        if self == legacy:
            raise OSError("busy")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(agi_env_module.Path, "unlink", _broken_unlink, raising=False)

    env._init_resources(resources_src)

    assert mock_logger.warning.called
