import os
from pathlib import Path
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


def test_worker_pyproject_source_missing_raises(tmp_path):
    env = SimpleNamespace(
        worker_pyproject=tmp_path / "missing_worker.toml",
        manager_pyproject=tmp_path / "missing_manager.toml",
    )

    with pytest.raises(FileNotFoundError, match="Missing pyproject.toml"):
        deployment_build_support._worker_pyproject_source(env)


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
    app_path.mkdir(parents=True, exist_ok=True)
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
    assert any("pip install agi-env" in cmd for cmd, _ in commands)
    assert any("pip install agi-node" in cmd for cmd, _ in commands)
    assert any("bdist_egg" in cmd for cmd, _ in commands)
    assert str(egg_path) in uploads


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

    assert any(f'--offline --project "{env.active_app}" pip install -e \'{env.agi_env}\'' in cmd for cmd, _ in commands)
    assert any(f'--offline --project "{env.active_app}" pip install -e \'{env.agi_node}\'' in cmd for cmd, _ in commands)


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
