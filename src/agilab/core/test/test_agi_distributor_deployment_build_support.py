import os
import shutil
import subprocess
from pathlib import Path
from shlex import quote
from types import SimpleNamespace

import pytest

from agi_cluster.agi_distributor import AGI
import agi_cluster.agi_distributor.deployment_build_support as deployment_build_support
from agi_cluster.agi_distributor import uv_source_support


@pytest.fixture(autouse=True)
def _reset_agi_build_state():
    snapshot = {
        "env": getattr(AGI, "env", None),
        "_mode": getattr(AGI, "_mode", None),
        "_dask_client": getattr(AGI, "_dask_client", None),
        "agi_workers": getattr(AGI, "agi_workers", None),
        "install_worker_group": getattr(AGI, "install_worker_group", None),
        "verbose": AGI.verbose,
    }
    try:
        AGI.env = None
        AGI._mode = 0
        AGI._dask_client = None
        AGI.agi_workers = {}
        AGI.verbose = 0
        yield
    finally:
        AGI.env = snapshot["env"]
        AGI._mode = snapshot["_mode"]
        AGI._dask_client = snapshot["_dask_client"]
        AGI.agi_workers = snapshot["agi_workers"]
        AGI.install_worker_group = snapshot["install_worker_group"]
        AGI.verbose = snapshot["verbose"]


def _editable_overlay_arg(path: Path) -> str:
    return f"--with-editable {quote(str(path))}"


@pytest.mark.parametrize(
    ("baseworker", "expected"),
    [
        ("AgentWorker", "agi_dispatcher, agent_worker"),
        ("DagWorker", "agi_dispatcher, dag_worker"),
        ("PandasWorker", "agi_dispatcher, pandas_worker"),
        ("PolarsWorker", "agi_dispatcher, polars_worker"),
        ("FireducksWorker", "agi_dispatcher, fireducks_worker"),
        ("UnknownWorker", "agi_dispatcher, "),
    ],
)
def test_worker_packages_maps_supported_workers(baseworker, expected):
    assert deployment_build_support._worker_packages(baseworker) == expected


def test_worker_packages_prefers_resolved_worker_group_for_derived_worker():
    assert (
        deployment_build_support._worker_packages(
            "Sb3TrainerWorker",
            worker_group="dag-worker",
        )
        == "agi_dispatcher, dag_worker"
    )


@pytest.mark.parametrize(
    ("worker_group", "expected"),
    [
        ("pandas-worker", "agi_dispatcher, pandas_worker"),
        ("polars-worker", "agi_dispatcher, polars_worker"),
        ("fireducks-worker", "agi_dispatcher, fireducks_worker"),
    ],
)
def test_worker_packages_maps_explicit_worker_groups(worker_group, expected):
    assert deployment_build_support._worker_packages("Sb3TrainerWorker", worker_group=worker_group) == expected


def test_build_module_command_prefers_source_build_script(tmp_path):
    agi_node_path = tmp_path / "agi-node"
    build_script = agi_node_path / "src" / "agi_node" / "agi_dispatcher" / "build.py"
    build_script.parent.mkdir(parents=True, exist_ok=True)
    build_script.write_text("print('build')\n", encoding="utf-8")

    env = SimpleNamespace(
        is_source_env=True,
        agi_node=agi_node_path,
        setup_app_module="agi_node.agi_dispatcher.build",
    )

    assert deployment_build_support._build_module_command(env) == f'python "{build_script}"'


def test_build_module_command_prefers_legacy_source_build_script(tmp_path):
    agi_node_path = tmp_path / "agi-node"
    build_script = agi_node_path / "agi_dispatcher" / "build.py"
    build_script.parent.mkdir(parents=True, exist_ok=True)
    build_script.write_text("print('build')\n", encoding="utf-8")

    env = SimpleNamespace(
        is_source_env=True,
        agi_node=agi_node_path,
        setup_app_module="agi_node.agi_dispatcher.build",
    )

    assert deployment_build_support._build_module_command(env) == f'python "{build_script}"'


@pytest.mark.parametrize(
    ("pyvers_worker", "expected"),
    [
        ("3.13", "3.13"),
        ("3.13t", "3.13t"),
        ("3.14t", "3.14t"),
    ],
)
def test_python_site_version_handles_free_thread_suffix(pyvers_worker, expected):
    assert deployment_build_support._python_site_version(pyvers_worker) == expected


def test_project_uv_adds_free_threading_prefix(monkeypatch):
    env = SimpleNamespace(
        is_free_threading_available=True,
        envars={"127.0.0.1_CMD_PREFIX": "env TEST=1"},
        uv="uv",
    )

    monkeypatch.setattr(deployment_build_support, "python_supports_free_threading", lambda: True)
    assert deployment_build_support._project_uv(env) == "env TEST=1 PYTHON_GIL=0 uv"


def test_build_support_environment_helpers_cover_edge_branches(monkeypatch):
    monkeypatch.delenv("AGI_INTERNET_ON", raising=False)
    monkeypatch.delenv("UV_INDEX_URL", raising=False)
    monkeypatch.delenv("UV_EXTRA_INDEX_URL", raising=False)
    monkeypatch.delenv("UV_FIND_LINKS", raising=False)

    class _BrokenEnvars:
        def get(self, _key):
            raise RuntimeError("broken env source")

    assert deployment_build_support._envar_value(_BrokenEnvars(), "MISSING") is None
    assert deployment_build_support._uv_resolver_mode({}) == "online"
    assert deployment_build_support._uv_resolver_mode({"AGI_INTERNET_ON": True}) == "online"
    assert deployment_build_support._uv_resolver_mode({"AGI_INTERNET_ON": False}) == "cache-only"
    assert deployment_build_support._uv_resolver_mode({"AGI_INTERNET_ON": 1}) == "online"
    assert deployment_build_support._uv_resolver_mode({"AGI_INTERNET_ON": 0}) == "cache-only"
    assert deployment_build_support._uv_resolver_mode({"AGI_INTERNET_ON": float("nan")}) == "cache-only"

    assert deployment_build_support._uv_offline_flag(SimpleNamespace(envars={"AGI_INTERNET_ON": True})) == ""
    assert deployment_build_support._uv_offline_flag(SimpleNamespace(envars={"AGI_INTERNET_ON": False})) == "--offline "
    assert deployment_build_support._uv_offline_flag(SimpleNamespace(envars={"AGI_INTERNET_ON": 1})) == ""
    assert deployment_build_support._uv_offline_flag(SimpleNamespace(envars={"AGI_INTERNET_ON": 0})) == "--offline "
    assert (
        deployment_build_support._uv_offline_flag(SimpleNamespace(envars={"AGI_INTERNET_ON": float("nan")}))
        == "--offline "
    )
    assert deployment_build_support._uv_offline_flag(SimpleNamespace(envars={"AGI_INTERNET_ON": "'yes'"})) == ""

    assert deployment_build_support._env_truthy(_BrokenEnvars(), "FLAG") is False
    assert deployment_build_support._env_truthy({"FLAG": True}, "FLAG") is True
    assert deployment_build_support._env_truthy({"FLAG": 1}, "FLAG") is True
    assert deployment_build_support._env_truthy({"FLAG": float("nan")}, "FLAG") is False
    assert deployment_build_support._env_truthy({"FLAG": "enabled"}, "FLAG") is True

    env = SimpleNamespace(is_free_threading_available=False, envars={}, uv="uv")
    monkeypatch.setattr(deployment_build_support, "python_supports_free_threading", lambda: True)
    assert deployment_build_support._project_uv(env) == "uv"


def test_worker_build_commands_request_build_tool_overlay():
    bdist_cmd = deployment_build_support._bdist_egg_command(
        uv="uv",
        module_cmd="python -m agi_node.agi_dispatcher.build",
        app_path_arg='"/apps/demo_project"',
        packages="agi_dispatcher,pandas_worker",
        wenv_arg='"/wenv/demo_worker"',
        verbose=0,
    )
    build_ext_cmd = deployment_build_support._build_ext_command(
        uv="uv",
        module_cmd="python -m agi_node.agi_dispatcher.build",
        app_path_arg='"/apps/demo_project"',
        wenv_arg='"/wenv/demo_worker"',
        verbose=0,
    )

    assert "run --no-sync --with setuptools --with cython" in bdist_cmd
    assert "run --no-sync --with setuptools --with cython" in build_ext_cmd
    assert " -q " in f" {bdist_cmd} "
    assert " -q " in f" {build_ext_cmd} "


def test_worker_build_commands_keep_overlay_without_quiet_flag_when_verbose():
    bdist_cmd = deployment_build_support._bdist_egg_command(
        uv="uv",
        module_cmd="python -m agi_node.agi_dispatcher.build",
        app_path_arg='"/apps/demo_project"',
        packages="agi_dispatcher,pandas_worker",
        wenv_arg='"/wenv/demo_worker"',
        verbose=2,
    )
    build_ext_cmd = deployment_build_support._build_ext_command(
        uv="uv",
        module_cmd="python -m agi_node.agi_dispatcher.build",
        app_path_arg='"/apps/demo_project"',
        wenv_arg='"/wenv/demo_worker"',
        verbose=2,
    )

    assert "run --no-sync --with setuptools --with cython" in bdist_cmd
    assert "run --no-sync --with setuptools --with cython" in build_ext_cmd
    assert " -q " not in f" {bdist_cmd} "
    assert " -q " not in f" {build_ext_cmd} "


def test_source_worker_build_overlay_includes_editable_core_projects(tmp_path):
    env = SimpleNamespace(
        is_source_env=True,
        agi_env=tmp_path / "core" / "agi-env",
        agi_node=tmp_path / "core" / "agi-node",
    )

    overlay = deployment_build_support._build_run_overlay_args(env)

    assert "--with setuptools" in overlay
    assert "--with cython" in overlay
    assert _editable_overlay_arg(env.agi_env) in overlay
    assert _editable_overlay_arg(env.agi_node) in overlay


def test_worker_pyproject_source_missing_raises(tmp_path):
    env = SimpleNamespace(
        worker_pyproject=tmp_path / "missing_worker.toml",
        manager_pyproject=tmp_path / "missing_manager.toml",
    )

    with pytest.raises(FileNotFoundError, match="Missing pyproject.toml"):
        deployment_build_support._worker_pyproject_source(env)


def test_worker_pyproject_source_falls_back_to_manager_pyproject(tmp_path):
    manager = tmp_path / "manager.toml"
    manager.write_text("[project]\nname='manager'\n", encoding="utf-8")
    env = SimpleNamespace(worker_pyproject=tmp_path / "missing.toml", manager_pyproject=manager)

    assert deployment_build_support._worker_pyproject_source(env) == manager


def _git_commit(repo: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=agilab@example.test",
            "-c",
            "user.name=AGILAB Test",
            "commit",
            "-m",
            "initial",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def test_directory_fingerprint_uses_git_tree_for_clean_source(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git is required for git tree fingerprint coverage")

    src = tmp_path / "repo" / "app" / "src"
    package = src / "demo"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git_commit(tmp_path / "repo")

    fingerprint = deployment_build_support._directory_fingerprint(src)

    assert fingerprint == [
        {
            "strategy": "git-tree",
            "path": src.resolve(strict=False).as_posix(),
            "git_root": (tmp_path / "repo").resolve(strict=False).as_posix(),
            "rel": "app/src",
            "tree": fingerprint[0]["tree"],
        }
    ]
    assert fingerprint[0]["tree"]


def test_directory_fingerprint_falls_back_when_git_source_is_dirty(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git is required for git tree fingerprint coverage")

    src = tmp_path / "repo" / "app" / "src"
    package = src / "demo"
    package.mkdir(parents=True)
    module = package / "__init__.py"
    module.write_text("VALUE = 1\n", encoding="utf-8")
    _git_commit(tmp_path / "repo")
    module.write_text("VALUE = 2\n", encoding="utf-8")

    fingerprint = deployment_build_support._directory_fingerprint(src)

    assert fingerprint
    assert fingerprint[0].get("strategy") != "git-tree"
    assert any(entry.get("rel") == "demo/__init__.py" for entry in fingerprint)


def test_build_support_fingerprint_edge_cases(monkeypatch, tmp_path):
    missing = tmp_path / "missing.txt"
    directory = tmp_path / "directory"
    directory.mkdir()
    assert deployment_build_support._file_fingerprint(missing) is None
    assert deployment_build_support._file_fingerprint(directory) is None
    assert deployment_build_support._optional_file_fingerprint(None) is None
    assert deployment_build_support._optional_file_fingerprint(object()) is None
    assert deployment_build_support._git_directory_fingerprint(missing) == []

    class _BrokenPath:
        def exists(self):
            return True

        def expanduser(self):
            raise OSError("cannot resolve")

    assert deployment_build_support._git_directory_fingerprint(_BrokenPath()) is None

    source = tmp_path / "repo" / "src"
    source.mkdir(parents=True)

    def _missing_git(*_args, **_kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(deployment_build_support.subprocess, "run", _missing_git)
    assert deployment_build_support._git_directory_fingerprint(source) is None

    def _outside_repo(*_args, **_kwargs):
        return subprocess.CompletedProcess(_args[0], 0, stdout=str(tmp_path / "other") + "\n", stderr="")

    monkeypatch.setattr(deployment_build_support.subprocess, "run", _outside_repo)
    assert deployment_build_support._git_directory_fingerprint(source) is None


def test_worker_build_cache_helpers_cover_disabled_and_missing_outputs(tmp_path):
    env = SimpleNamespace(
        wenv_abs=tmp_path / "wenv",
        envars={deployment_build_support.DISABLE_BUILD_CACHE_ENV: "1"},
        active_app=tmp_path / "app",
        worker_pyproject=tmp_path / "worker.toml",
        manager_pyproject=tmp_path / "manager.toml",
        uvproject=tmp_path / "uv.toml",
        base_worker_cls="PandasWorker",
        pyvers_worker="3.13",
    )
    env.wenv_abs.mkdir()

    assert deployment_build_support._worker_build_outputs_exist(env.wenv_abs, is_cy=False) is False
    assert deployment_build_support._worker_build_outputs_exist(env.wenv_abs, is_cy=True) is False
    assert (
        deployment_build_support._worker_build_cache_hit(
            env=env,
            packages="agi_dispatcher, pandas_worker",
            worker_group=None,
            is_cy=False,
            module_cmd="python -m build",
            core_install_commands=[],
        )
        is False
    )
    deployment_build_support._record_worker_build_cache(
        env=env,
        packages="agi_dispatcher, pandas_worker",
        worker_group=None,
        is_cy=False,
        module_cmd="python -m build",
        core_install_commands=[],
    )
    assert not deployment_build_support._build_cache_path(env.wenv_abs).exists()


def test_copy_cython_worker_lib_raises_when_output_missing(tmp_path):
    wenv_abs = tmp_path / "wenv"
    (wenv_abs / "dist").mkdir(parents=True, exist_ok=True)

    with pytest.raises(RuntimeError, match="build_ext failed"):
        deployment_build_support._copy_cython_worker_lib(
            wenv_abs=wenv_abs,
            pyvers_worker="3.13",
            build_output="",
            failure_message="build_ext failed",
        )


def test_upload_built_eggs_uses_sorted_order(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    egg_b = dist_dir / "z-last.egg"
    egg_a = dist_dir / "a-first.egg"
    egg_b.write_text("b", encoding="utf-8")
    egg_a.write_text("a", encoding="utf-8")
    uploads: list[str] = []

    class _Client:
        def upload_file(self, path):
            uploads.append(Path(path).name)

    deployment_build_support._upload_built_eggs(_Client(), dist_dir)

    assert uploads == ["a-first.egg", "z-last.egg"]


def test_copy_cython_worker_lib_prefers_latest_output(tmp_path):
    wenv_abs = tmp_path / "wenv"
    dist_dir = wenv_abs / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    older_lib = dist_dir / "worker_old_cy.so"
    newer_lib = dist_dir / "worker_new_cy.so"
    older_lib.write_text("old", encoding="utf-8")
    newer_lib.write_text("new", encoding="utf-8")
    os.utime(older_lib, (1, 1))
    os.utime(newer_lib, (2, 2))

    deployment_build_support._copy_cython_worker_lib(
        wenv_abs=wenv_abs,
        pyvers_worker="3.13",
        build_output="",
        failure_message="build_ext failed",
    )

    destination = wenv_abs / ".venv" / "lib" / "python3.13" / "site-packages"
    assert (destination / "worker_new_cy.so").exists()
    assert not (destination / "worker_old_cy.so").exists()


def _build_env(tmp_path: Path, *, base_worker_cls: str = "PandasWorker", free_threading: bool = False):
    app_path = tmp_path / "app"
    app_src = app_path / "src" / "demo_worker"
    app_src.mkdir(parents=True, exist_ok=True)
    (app_src / "demo_worker.py").write_text("VALUE = 1\n", encoding="utf-8")
    wenv_abs = tmp_path / "wenv"
    (wenv_abs / "dist").mkdir(parents=True, exist_ok=True)
    worker_pyproject = tmp_path / "worker_pyproject.toml"
    worker_pyproject.write_text("[project]\nname='worker'\n", encoding="utf-8")
    manager_pyproject = tmp_path / "manager_pyproject.toml"
    manager_pyproject.write_text("[project]\nname='manager'\n", encoding="utf-8")
    uvproject = tmp_path / "uv.toml"
    uvproject.write_text("[tool.uv]\n", encoding="utf-8")
    agi_env_path = tmp_path / "agi-env"
    agi_env_path.mkdir(parents=True, exist_ok=True)
    agi_node_path = tmp_path / "agi-node"
    agi_node_path.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        wenv_abs=wenv_abs,
        base_worker_cls=base_worker_cls,
        active_app=app_path,
        setup_app_module="agi_node.agi_dispatcher.build",
        uv="uv",
        envars={"127.0.0.1_CMD_PREFIX": "env TEST=1"} if free_threading else {},
        is_free_threading_available=free_threading,
        worker_pyproject=worker_pyproject,
        manager_pyproject=manager_pyproject,
        uvproject=uvproject,
        agi_env=agi_env_path,
        agi_node=agi_node_path,
        is_source_env=False,
        verbose=0,
        pyvers_worker="3.13",
        target_worker="demo_worker",
    )


@pytest.mark.asyncio
async def test_build_lib_local_non_cython_uploads_egg(tmp_path):
    env = _build_env(tmp_path)
    egg_path = env.wenv_abs / "dist" / "demo.egg"
    egg_path.write_text("egg", encoding="utf-8")
    uploads = []
    commands = []

    class _Client:
        def upload_file(self, path):
            uploads.append(path)

    async def _fake_run(cmd, cwd):
        commands.append((cmd, str(cwd)))
        return ""

    AGI.env = env
    AGI._mode = AGI.PYTHON_MODE
    AGI._dask_client = _Client()
    AGI.agi_workers = {"pandas": "pandas-worker"}

    await deployment_build_support.build_lib_local(
        AGI,
        ensure_optional_extras_fn=uv_source_support.ensure_optional_extras,
        stage_uv_sources_fn=uv_source_support.stage_uv_sources_for_copied_pyproject,
        validate_worker_uv_sources_fn=uv_source_support.validate_worker_uv_sources,
        run_fn=_fake_run,
    )

    assert (env.wenv_abs / env.worker_pyproject.name).exists()
    assert any("pip install agi-env agi-node" in cmd for cmd, _ in commands)
    assert any("bdist_egg" in cmd for cmd, _ in commands)
    assert str(egg_path) in uploads


@pytest.mark.asyncio
async def test_build_lib_local_reuses_cached_worker_artifacts(tmp_path):
    env = _build_env(tmp_path)
    egg_path = env.wenv_abs / "dist" / "demo.egg"
    egg_path.write_text("egg", encoding="utf-8")
    uploads: list[str] = []
    commands: list[tuple[str, str]] = []

    class _Client:
        def upload_file(self, path):
            uploads.append(path)

    async def _fake_run(cmd, cwd):
        commands.append((cmd, str(cwd)))
        return ""

    AGI.env = env
    AGI._mode = AGI.PYTHON_MODE
    AGI._dask_client = _Client()
    AGI.agi_workers = {"pandas": "pandas-worker"}

    await deployment_build_support.build_lib_local(
        AGI,
        ensure_optional_extras_fn=uv_source_support.ensure_optional_extras,
        stage_uv_sources_fn=uv_source_support.stage_uv_sources_for_copied_pyproject,
        validate_worker_uv_sources_fn=uv_source_support.validate_worker_uv_sources,
        run_fn=_fake_run,
    )
    first_command_count = len(commands)

    await deployment_build_support.build_lib_local(
        AGI,
        ensure_optional_extras_fn=uv_source_support.ensure_optional_extras,
        stage_uv_sources_fn=uv_source_support.stage_uv_sources_for_copied_pyproject,
        validate_worker_uv_sources_fn=uv_source_support.validate_worker_uv_sources,
        run_fn=_fake_run,
    )

    assert first_command_count > 0
    assert len(commands) == first_command_count
    assert uploads == [str(egg_path), str(egg_path)]


@pytest.mark.asyncio
async def test_build_lib_local_cache_invalidates_when_source_changes(tmp_path):
    env = _build_env(tmp_path)
    egg_path = env.wenv_abs / "dist" / "demo.egg"
    egg_path.write_text("egg", encoding="utf-8")
    commands: list[tuple[str, str]] = []

    async def _fake_run(cmd, cwd):
        commands.append((cmd, str(cwd)))
        return ""

    AGI.env = env
    AGI._mode = AGI.PYTHON_MODE
    AGI._dask_client = None
    AGI.agi_workers = {"pandas": "pandas-worker"}

    await deployment_build_support.build_lib_local(
        AGI,
        ensure_optional_extras_fn=uv_source_support.ensure_optional_extras,
        stage_uv_sources_fn=uv_source_support.stage_uv_sources_for_copied_pyproject,
        validate_worker_uv_sources_fn=uv_source_support.validate_worker_uv_sources,
        run_fn=_fake_run,
    )
    first_command_count = len(commands)
    (env.active_app / "src" / "demo_worker" / "demo_worker.py").write_text("VALUE = 2\n", encoding="utf-8")

    await deployment_build_support.build_lib_local(
        AGI,
        ensure_optional_extras_fn=uv_source_support.ensure_optional_extras,
        stage_uv_sources_fn=uv_source_support.stage_uv_sources_for_copied_pyproject,
        validate_worker_uv_sources_fn=uv_source_support.validate_worker_uv_sources,
        run_fn=_fake_run,
    )

    assert len(commands) > first_command_count


@pytest.mark.asyncio
async def test_build_lib_local_uses_free_threading_uv_prefix(monkeypatch, tmp_path):
    env = _build_env(tmp_path, free_threading=True)
    (env.wenv_abs / "dist" / "demo.egg").write_text("egg", encoding="utf-8")
    commands = []

    async def _fake_run(cmd, cwd):
        commands.append((cmd, str(cwd)))
        return ""

    AGI.env = env
    AGI._mode = AGI.PYTHON_MODE
    AGI._dask_client = None
    AGI.agi_workers = {"pandas": "pandas-worker"}
    monkeypatch.setattr(deployment_build_support, "python_supports_free_threading", lambda: True)

    await deployment_build_support.build_lib_local(
        AGI,
        ensure_optional_extras_fn=uv_source_support.ensure_optional_extras,
        stage_uv_sources_fn=uv_source_support.stage_uv_sources_for_copied_pyproject,
        validate_worker_uv_sources_fn=uv_source_support.validate_worker_uv_sources,
        run_fn=_fake_run,
    )

    assert commands
    assert all(cmd.startswith("env TEST=1 PYTHON_GIL=0 uv ") for cmd, _ in commands)


@pytest.mark.asyncio
async def test_build_lib_local_uses_editable_core_installs_in_source_env(monkeypatch, tmp_path):
    monkeypatch.delenv("AGI_INTERNET_ON", raising=False)
    monkeypatch.delenv("UV_INDEX_URL", raising=False)
    env = _build_env(tmp_path)
    env.is_source_env = True
    env.envars = {"AGI_INTERNET_ON": "0"}
    (env.wenv_abs / "dist" / "demo.egg").write_text("egg", encoding="utf-8")
    commands = []

    async def _fake_run(cmd, cwd):
        commands.append((cmd, str(cwd)))
        return ""

    AGI.env = env
    AGI._mode = AGI.PYTHON_MODE
    AGI._dask_client = None
    AGI.agi_workers = {"pandas": "pandas-worker"}

    await deployment_build_support.build_lib_local(
        AGI,
        ensure_optional_extras_fn=uv_source_support.ensure_optional_extras,
        stage_uv_sources_fn=uv_source_support.stage_uv_sources_for_copied_pyproject,
        validate_worker_uv_sources_fn=uv_source_support.validate_worker_uv_sources,
        run_fn=_fake_run,
    )

    assert any(
        (
            f'--offline --project "{env.active_app}" pip install --upgrade --no-deps '
            f"-e '{env.agi_env}' -e '{env.agi_node}'"
        )
        in cmd
        for cmd, _ in commands
    )
    assert any(
        _editable_overlay_arg(env.agi_env) in cmd and _editable_overlay_arg(env.agi_node) in cmd
        for cmd, _ in commands
    )


@pytest.mark.asyncio
async def test_build_lib_local_uses_uv_index_url_mirror_when_internet_disabled(
    monkeypatch, tmp_path
):
    monkeypatch.delenv("AGI_INTERNET_ON", raising=False)
    monkeypatch.delenv("UV_INDEX_URL", raising=False)
    env = _build_env(tmp_path)
    env.is_source_env = True
    env.envars = {
        "AGI_INTERNET_ON": "0",
        "UV_INDEX_URL": "http://mirror.local/simple",
    }
    (env.wenv_abs / "dist" / "demo.egg").write_text("egg", encoding="utf-8")
    commands = []

    async def _fake_run(cmd, cwd):
        commands.append((cmd, str(cwd)))
        return ""

    AGI.env = env
    AGI._mode = AGI.PYTHON_MODE
    AGI._dask_client = None
    AGI.agi_workers = {"pandas": "pandas-worker"}

    await deployment_build_support.build_lib_local(
        AGI,
        ensure_optional_extras_fn=uv_source_support.ensure_optional_extras,
        stage_uv_sources_fn=uv_source_support.stage_uv_sources_for_copied_pyproject,
        validate_worker_uv_sources_fn=uv_source_support.validate_worker_uv_sources,
        run_fn=_fake_run,
    )

    assert commands
    assert not any("--offline" in cmd for cmd, _ in commands)
    assert any(
        (
            f'--project "{env.active_app}" pip install --upgrade --no-deps '
            f"-e '{env.agi_env}' -e '{env.agi_node}'"
        )
        in cmd
        for cmd, _ in commands
    )
    assert any(
        _editable_overlay_arg(env.agi_env) in cmd and _editable_overlay_arg(env.agi_node) in cmd
        for cmd, _ in commands
    )


def test_build_support_resolver_modes_for_offline_mirror_and_wheelhouse(monkeypatch):
    monkeypatch.delenv("AGI_INTERNET_ON", raising=False)
    monkeypatch.delenv("UV_INDEX_URL", raising=False)
    monkeypatch.delenv("UV_EXTRA_INDEX_URL", raising=False)
    monkeypatch.delenv("UV_FIND_LINKS", raising=False)

    cache_only = SimpleNamespace(envars={"AGI_INTERNET_ON": "0"})
    assert deployment_build_support._uv_resolver_mode(cache_only.envars) == "cache-only"
    assert deployment_build_support._uv_offline_flag(cache_only) == "--offline "

    mirror = SimpleNamespace(
        envars={
            "AGI_INTERNET_ON": "0",
            "UV_EXTRA_INDEX_URL": "http://mirror.local/simple",
        }
    )
    assert deployment_build_support._uv_resolver_mode(mirror.envars) == "mirror"
    assert deployment_build_support._uv_offline_flag(mirror) == ""

    wheelhouse = SimpleNamespace(
        envars={
            "AGI_INTERNET_ON": "0",
            "UV_FIND_LINKS": "/mnt/wheelhouse",
        }
    )
    assert deployment_build_support._uv_resolver_mode(wheelhouse.envars) == "wheelhouse"
    assert deployment_build_support._uv_offline_flag(wheelhouse) == "--offline "

    placeholder = SimpleNamespace(
        envars={
            "AGI_INTERNET_ON": "0",
            "UV_INDEX_URL": "None",
        }
    )
    assert deployment_build_support._uv_resolver_mode(placeholder.envars) == "cache-only"
    assert deployment_build_support._uv_offline_flag(placeholder) == "--offline "


@pytest.mark.asyncio
async def test_build_lib_local_cython_copies_worker_lib(tmp_path):
    env = _build_env(tmp_path)
    env.verbose = 2
    worker_lib = env.wenv_abs / "dist" / "demo_cy.so"
    worker_lib.write_text("binary", encoding="utf-8")
    commands = []

    async def _fake_run(cmd, cwd):
        commands.append((cmd, str(cwd)))
        if "build_ext" in cmd:
            return "build ok"
        return ""

    AGI.env = env
    AGI._mode = AGI.CYTHON_MODE
    AGI._dask_client = None
    AGI.agi_workers = {"pandas": "pandas-worker"}

    await deployment_build_support.build_lib_local(
        AGI,
        ensure_optional_extras_fn=uv_source_support.ensure_optional_extras,
        stage_uv_sources_fn=uv_source_support.stage_uv_sources_for_copied_pyproject,
        validate_worker_uv_sources_fn=uv_source_support.validate_worker_uv_sources,
        run_fn=_fake_run,
    )

    target = env.wenv_abs / ".venv/lib/python3.13/site-packages/demo_cy.so"
    assert target.exists()
    assert any("build_ext" in cmd for cmd, _ in commands)
    assert any(
        f'--app-path "{env.active_app}"' in cmd and f'-b "{env.wenv_abs}"' in cmd
        for cmd, _ in commands
        if "build_ext" in cmd
    )


@pytest.mark.asyncio
async def test_build_lib_local_selects_fireducks_package(tmp_path):
    env = _build_env(tmp_path, base_worker_cls="FireducksWorker")
    (env.wenv_abs / "dist" / "demo.egg").write_text("egg", encoding="utf-8")
    commands = []

    async def _fake_run(cmd, cwd):
        commands.append((cmd, str(cwd)))
        return ""

    AGI.env = env
    AGI._mode = 0
    AGI._dask_client = SimpleNamespace(upload_file=lambda *_args, **_kwargs: None)
    AGI.agi_workers = {"fireducks": "fireducks-worker"}

    await deployment_build_support.build_lib_local(
        AGI,
        ensure_optional_extras_fn=uv_source_support.ensure_optional_extras,
        stage_uv_sources_fn=uv_source_support.stage_uv_sources_for_copied_pyproject,
        validate_worker_uv_sources_fn=uv_source_support.validate_worker_uv_sources,
        run_fn=_fake_run,
    )

    assert any("fireducks_worker" in cmd for cmd, _ in commands)


@pytest.mark.asyncio
async def test_build_lib_local_uses_resolved_group_for_derived_worker(tmp_path):
    env = _build_env(tmp_path, base_worker_cls="Sb3TrainerWorker")
    (env.wenv_abs / "dist" / "demo.egg").write_text("egg", encoding="utf-8")
    commands = []

    async def _fake_run(cmd, cwd):
        commands.append((cmd, str(cwd)))
        return ""

    AGI.env = env
    AGI._mode = 0
    AGI._dask_client = SimpleNamespace(upload_file=lambda *_args, **_kwargs: None)
    AGI.agi_workers = {"dag": "dag-worker"}
    AGI.install_worker_group = ["dag-worker"]

    await deployment_build_support.build_lib_local(
        AGI,
        ensure_optional_extras_fn=uv_source_support.ensure_optional_extras,
        stage_uv_sources_fn=uv_source_support.stage_uv_sources_for_copied_pyproject,
        validate_worker_uv_sources_fn=uv_source_support.validate_worker_uv_sources,
        run_fn=_fake_run,
    )

    assert any("dag_worker" in cmd for cmd, _ in commands)


@pytest.mark.asyncio
async def test_build_lib_remote_logs_when_pool_open_zero():
    AGI.verbose = 1
    AGI._dask_client = SimpleNamespace(
        scheduler=SimpleNamespace(pool=SimpleNamespace(open=0)),
        scheduler_info=lambda: {"workers": {"tcp://127.0.0.1:8787": {}}},
    )

    await deployment_build_support.build_lib_remote(AGI)
