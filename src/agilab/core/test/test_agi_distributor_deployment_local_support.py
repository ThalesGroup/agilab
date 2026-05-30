from __future__ import annotations

import getpass
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
import tomlkit

from agi_cluster.agi_distributor import (
    deployment_editable_install_support,
    deployment_local_support,
    deployment_stage_cache_support,
    uv_source_support,
)


def _venv_python(project: Path, *, os_name: str | None = None) -> Path:
    return deployment_local_support._project_venv_python(
        project,
        os_name=os_name or os.name,
    )


def _write_venv_python(
    project: Path,
    *,
    python_version: str | None = None,
    os_name: str | None = None,
) -> Path:
    python_path = _venv_python(project, os_name=os_name)
    python_path.parent.mkdir(parents=True, exist_ok=True)
    python_path.write_text("", encoding="utf-8")
    if python_version is not None:
        (project / ".venv" / "pyvenv.cfg").write_text(
            f"version = {python_version}\n",
            encoding="utf-8",
        )
    return python_path


def _write_editable_direct_url(
    venv_project: Path,
    package_project: Path,
    *,
    python_version: str = "3.13",
) -> None:
    site_packages = deployment_local_support._project_site_packages_dir(
        venv_project,
        python_version=python_version,
    )
    dist_info = (
        site_packages / f"{package_project.name.replace('-', '_')}-0.0.dist-info"
    )
    dist_info.mkdir(parents=True, exist_ok=True)
    (dist_info / "direct_url.json").write_text(
        json.dumps(
            {
                "url": package_project.resolve(strict=False).as_uri(),
                "dir_info": {"editable": True},
            }
        ),
        encoding="utf-8",
    )


def test_editable_install_cache_path_lives_outside_project_venv(tmp_path):
    cache_path = deployment_local_support._editable_install_cache_path(tmp_path)

    assert cache_path.parent == tmp_path.parent / ".agilab-editable-install-cache"
    assert cache_path.name.startswith(f"{tmp_path.name}-")
    assert cache_path.name.endswith(".json")
    assert tmp_path / ".venv" not in cache_path.parents


async def _call_deploy_local_worker(
    agi_cls,
    src: Path,
    wenv_rel: Path,
    options_worker: str,
    *,
    agi_version_missing_on_pypi_fn,
    runtime_file: str | None = None,
    run_fn,
    set_env_var_fn,
    log,
) -> None:
    await deployment_local_support.deploy_local_worker(
        agi_cls,
        src,
        wenv_rel,
        options_worker,
        agi_version_missing_on_pypi_fn=agi_version_missing_on_pypi_fn,
        worker_site_packages_dir_fn=uv_source_support.worker_site_packages_dir,
        write_staged_uv_sources_pth_fn=uv_source_support.write_staged_uv_sources_pth,
        runtime_file=runtime_file or deployment_local_support.__file__,
        run_fn=run_fn,
        set_env_var_fn=set_env_var_fn,
        log=log,
    )


def test_force_remove_falls_back_to_subprocess_when_path_survives(
    monkeypatch, tmp_path
):
    target = tmp_path / "stubborn"
    target.mkdir(parents=True, exist_ok=True)
    calls = []
    env_logger = mock.Mock()

    monkeypatch.setattr(
        deployment_local_support.shutil, "rmtree", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        deployment_local_support.subprocess,
        "run",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    deployment_local_support._force_remove(target, env_logger=env_logger)

    assert calls
    assert calls[0][0][0] == ["cmd", "/c", "rmdir", "/s", "/q", str(target)]
    assert "shell" not in calls[0][1]
    assert env_logger.warn.called


def test_force_remove_unlinks_symlink_without_touching_target(tmp_path):
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    target = tmp_path / "linked"
    target.symlink_to(canonical, target_is_directory=True)

    deployment_local_support._force_remove(target)

    assert not target.exists()
    assert not target.is_symlink()
    assert canonical.exists()


def test_force_remove_propagates_non_filesystem_errors(monkeypatch, tmp_path):
    target = tmp_path / "stubborn"
    target.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        deployment_local_support.shutil,
        "rmtree",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    with pytest.raises(RuntimeError, match="boom"):
        deployment_local_support._force_remove(target)


def test_force_remove_onerror_handles_oserror_and_skips_logger_when_missing(
    monkeypatch, tmp_path
):
    target = tmp_path / "stubborn"
    child = target / "child"
    target.mkdir(parents=True, exist_ok=True)
    chmod_calls = []
    subprocess_calls = []

    def _broken_remove(_path):
        raise OSError("still locked")

    def _fake_rmtree(_path, onerror):
        onerror(_broken_remove, str(child), (OSError, OSError("locked"), None))

    monkeypatch.setattr(deployment_local_support.shutil, "rmtree", _fake_rmtree)
    monkeypatch.setattr(
        deployment_local_support.os,
        "chmod",
        lambda path, mode: chmod_calls.append((path, mode)),
    )
    monkeypatch.setattr(
        deployment_local_support.subprocess,
        "run",
        lambda *args, **kwargs: subprocess_calls.append((args, kwargs)),
    )

    deployment_local_support._force_remove(target)

    assert chmod_calls == [(str(child), deployment_local_support.stat.S_IWRITE)]
    assert subprocess_calls


def test_force_remove_swallows_filesystem_error_and_uses_subprocess(
    monkeypatch, tmp_path
):
    target = tmp_path / "stubborn"
    target.mkdir(parents=True, exist_ok=True)
    subprocess_calls = []

    def _fake_rmtree(*_args, **_kwargs):
        raise OSError("cannot remove")

    monkeypatch.setattr(deployment_local_support.shutil, "rmtree", _fake_rmtree)
    monkeypatch.setattr(
        deployment_local_support.subprocess,
        "run",
        lambda *args, **kwargs: subprocess_calls.append((args, kwargs)),
    )

    deployment_local_support._force_remove(target)

    assert subprocess_calls


def test_deploy_local_worker_venv_cleanup_is_conditional() -> None:
    source = Path(deployment_local_support.__file__).read_text(encoding="utf-8")

    assert '_force_remove(app_path / ".venv"' not in source
    assert "_remove_project_venv_if_mismatched(\n        app_path," in source
    assert "_remove_project_venv_if_mismatched(\n        worker_venv_project," in source
    assert "if worker_venv_project is None:" in source
    assert '_force_remove(wenv_abs / ".venv"' in source


def test_cleanup_editable_ignores_missing_entries():
    removed = []

    class _Entry:
        def __init__(self, name, *, missing=False):
            self.name = name
            self.missing = missing

        def unlink(self):
            if self.missing:
                raise FileNotFoundError(self.name)
            removed.append(self.name)

    class _SitePackages:
        def glob(self, pattern):
            if pattern == "__editable__.agi_env*.pth":
                return [_Entry("env.pth")]
            if pattern == "__editable__.agi_cluster*.pth":
                return [_Entry("cluster.pth", missing=True)]
            return []

    deployment_local_support._cleanup_editable(_SitePackages())

    assert removed == ["env.pth"]


def test_cleanup_editable_shadow_packages_removes_core_import_shadow(tmp_path):
    site_packages = deployment_local_support._project_site_packages_dir(
        tmp_path,
        python_version="3.13",
    )
    shadow_package = site_packages / "agi_cluster"
    shadow_module = site_packages / "agi_env.py"
    keep_package = site_packages / "other_package"
    shadow_package.mkdir(parents=True)
    shadow_module.write_text("# stale module\n", encoding="utf-8")
    keep_package.mkdir()
    package_cluster = tmp_path / "core" / "agi-cluster"
    package_env = tmp_path / "core" / "agi-env"

    removed = deployment_local_support._cleanup_editable_shadow_packages(
        tmp_path,
        [package_cluster, package_env],
        python_version="3.13",
    )

    assert sorted(path.name for path in removed) == ["agi_cluster", "agi_env.py"]
    assert not shadow_package.exists()
    assert not shadow_module.exists()
    assert keep_package.exists()


@pytest.mark.asyncio
async def test_install_into_project_venv_uses_target_python(tmp_path):
    calls = []
    package_path = tmp_path / "pkg"
    package_path.mkdir()

    async def _fake_run(cmd, cwd):
        calls.append((cmd, cwd))

    await deployment_local_support._install_into_project_venv(
        "uv",
        tmp_path,
        package_path,
        run_fn=_fake_run,
    )

    assert calls == [
        (
            f'uv venv --allow-existing "{tmp_path / ".venv"}"',
            tmp_path,
        ),
        (
            f'uv pip install --python "{_venv_python(tmp_path)}" '
            f'--upgrade --no-deps "{package_path}"',
            tmp_path,
        ),
    ]


@pytest.mark.asyncio
async def test_install_into_project_venv_reuses_existing_target_python(tmp_path):
    calls = []
    package_path = tmp_path / "pkg"
    package_path.mkdir()
    venv_python = _write_venv_python(tmp_path)

    async def _fake_run(cmd, cwd):
        calls.append((cmd, cwd))

    await deployment_local_support._install_into_project_venv(
        "uv",
        tmp_path,
        package_path,
        run_fn=_fake_run,
    )

    assert calls == [
        (
            f'uv pip install --python "{venv_python}" --upgrade --no-deps "{package_path}"',
            tmp_path,
        ),
    ]


@pytest.mark.asyncio
async def test_install_into_project_venv_reuses_existing_matching_python_version(
    tmp_path,
):
    calls = []
    package_path = tmp_path / "pkg"
    package_path.mkdir()
    venv_python = _write_venv_python(tmp_path)
    (tmp_path / ".venv" / "pyvenv.cfg").write_text("version_info = 3.13.13.final.0\n", encoding="utf-8")

    async def _fake_run(cmd, cwd):
        calls.append((cmd, cwd))

    await deployment_local_support._install_into_project_venv(
        "uv",
        tmp_path,
        package_path,
        run_fn=_fake_run,
        python_version="3.13",
    )

    assert calls == [
        (
            f'uv pip install --python "{venv_python}" --upgrade --no-deps "{package_path}"',
            tmp_path,
        ),
    ]


@pytest.mark.asyncio
async def test_install_into_project_venv_recreates_existing_mismatched_python_version(
    tmp_path,
):
    calls = []
    package_path = tmp_path / "pkg"
    package_path.mkdir()
    venv_python = _write_venv_python(tmp_path)
    (tmp_path / ".venv" / "pyvenv.cfg").write_text("version_info = 3.12.9.final.0\n", encoding="utf-8")

    async def _fake_run(cmd, cwd):
        calls.append((cmd, cwd))

    await deployment_local_support._install_into_project_venv(
        "uv",
        tmp_path,
        package_path,
        run_fn=_fake_run,
        python_version="3.13",
    )

    assert calls == [
        (
            f'uv venv --allow-existing --python 3.13 "{tmp_path / ".venv"}"',
            tmp_path,
        ),
        (
            f'uv pip install --python "{venv_python}" --upgrade --no-deps "{package_path}"',
            tmp_path,
        ),
    ]


@pytest.mark.asyncio
async def test_install_into_project_venv_skips_cached_editable_metadata(tmp_path):
    calls = []
    package_path = tmp_path / "pkg"
    package_path.mkdir()
    (package_path / "pyproject.toml").write_text(
        "[project]\nname='demo-pkg'\n", encoding="utf-8"
    )
    venv_python = _write_venv_python(tmp_path, python_version="3.13.13")

    async def _fake_run(cmd, cwd):
        calls.append((cmd, cwd))
        _write_editable_direct_url(tmp_path, package_path)

    await deployment_local_support._install_into_project_venv(
        "uv",
        tmp_path,
        package_path,
        run_fn=_fake_run,
        editable=True,
        no_deps=False,
        python_version="3.13",
    )
    await deployment_local_support._install_into_project_venv(
        "uv",
        tmp_path,
        package_path,
        run_fn=_fake_run,
        editable=True,
        no_deps=False,
        python_version="3.13",
    )

    assert calls == [
        (
            f'uv pip install --python "{venv_python}" --upgrade -e "{package_path}"',
            tmp_path,
        )
    ]


@pytest.mark.asyncio
async def test_install_into_project_venv_invalidates_editable_metadata_cache(tmp_path):
    calls = []
    package_path = tmp_path / "pkg"
    package_path.mkdir()
    pyproject = package_path / "pyproject.toml"
    pyproject.write_text("[project]\nname='demo-pkg'\n", encoding="utf-8")
    venv_python = _write_venv_python(tmp_path, python_version="3.13.13")

    async def _fake_run(cmd, cwd):
        calls.append((cmd, cwd))
        _write_editable_direct_url(tmp_path, package_path)

    for _ in range(2):
        await deployment_local_support._install_into_project_venv(
            "uv",
            tmp_path,
            package_path,
            run_fn=_fake_run,
            editable=True,
            no_deps=False,
            python_version="3.13",
        )
    pyproject.write_text(
        "[project]\nname='demo-pkg'\ndependencies=['numpy']\n",
        encoding="utf-8",
    )
    await deployment_local_support._install_into_project_venv(
        "uv",
        tmp_path,
        package_path,
        run_fn=_fake_run,
        editable=True,
        no_deps=False,
        python_version="3.13",
    )

    assert calls == [
        (
            f'uv pip install --python "{venv_python}" --upgrade -e "{package_path}"',
            tmp_path,
        ),
        (
            f'uv pip install --python "{venv_python}" --upgrade -e "{package_path}"',
            tmp_path,
        ),
    ]


@pytest.mark.asyncio
async def test_install_many_into_project_venv_skips_cached_editables(tmp_path):
    calls = []
    package_a = tmp_path / "pkg_a"
    package_b = tmp_path / "pkg_b"
    for package_path in (package_a, package_b):
        package_path.mkdir()
        (package_path / "pyproject.toml").write_text(
            f"[project]\nname='{package_path.name}'\n", encoding="utf-8"
        )
    venv_python = _write_venv_python(tmp_path, python_version="3.13.13")

    async def _fake_run(cmd, cwd):
        calls.append((cmd, cwd))
        _write_editable_direct_url(tmp_path, package_a)
        _write_editable_direct_url(tmp_path, package_b)

    await deployment_local_support._install_many_into_project_venv(
        "uv",
        tmp_path,
        [package_a, package_b],
        run_fn=_fake_run,
        editable=True,
        no_deps=True,
        python_version="3.13",
    )
    await deployment_local_support._install_many_into_project_venv(
        "uv",
        tmp_path,
        [package_a, package_b],
        run_fn=_fake_run,
        editable=True,
        no_deps=True,
        python_version="3.13",
    )

    assert calls == [
        (
            f'uv pip install --python "{venv_python}" --upgrade --no-deps '
            f'-e "{package_a}" -e "{package_b}"',
            tmp_path,
        )
    ]


@pytest.mark.asyncio
async def test_install_many_into_project_venv_cleans_cached_core_shadow(tmp_path):
    calls = []
    package_cluster = tmp_path / "agi-cluster"
    package_cluster.mkdir()
    (package_cluster / "pyproject.toml").write_text(
        "[project]\nname='agi-cluster'\n",
        encoding="utf-8",
    )
    venv_python = _write_venv_python(tmp_path, python_version="3.13.13")

    async def _fake_run(cmd, cwd):
        calls.append((cmd, cwd))
        _write_editable_direct_url(tmp_path, package_cluster)

    await deployment_local_support._install_many_into_project_venv(
        "uv",
        tmp_path,
        [package_cluster],
        run_fn=_fake_run,
        editable=True,
        no_deps=True,
        python_version="3.13",
    )
    shadow_package = (
        deployment_local_support._project_site_packages_dir(
            tmp_path,
            python_version="3.13",
        )
        / "agi_cluster"
    )
    shadow_package.mkdir()
    (shadow_package / "__init__.py").write_text(
        "class StageRequest: ...\n",
        encoding="utf-8",
    )

    await deployment_local_support._install_many_into_project_venv(
        "uv",
        tmp_path,
        [package_cluster],
        run_fn=_fake_run,
        editable=True,
        no_deps=True,
        python_version="3.13",
    )

    assert calls == [
        (
            f'uv pip install --python "{venv_python}" --upgrade --no-deps '
            f'-e "{package_cluster}"',
            tmp_path,
        )
    ]
    assert not shadow_package.exists()


@pytest.mark.asyncio
async def test_install_many_into_project_venv_reinstalls_only_missing_editable_proofs(
    tmp_path,
):
    calls = []
    package_a = tmp_path / "pkg_a"
    package_b = tmp_path / "pkg_b"
    for package_path in (package_a, package_b):
        package_path.mkdir()
        (package_path / "pyproject.toml").write_text(
            f"[project]\nname='{package_path.name}'\n",
            encoding="utf-8",
        )
    venv_python = _write_venv_python(tmp_path, python_version="3.13.13")

    async def _fake_run(cmd, cwd):
        calls.append((cmd, cwd))
        if str(package_a) in cmd:
            _write_editable_direct_url(tmp_path, package_a)
        if str(package_b) in cmd:
            _write_editable_direct_url(tmp_path, package_b)

    await deployment_local_support._install_many_into_project_venv(
        "uv",
        tmp_path,
        [package_a, package_b],
        run_fn=_fake_run,
        editable=True,
        no_deps=True,
        python_version="3.13",
    )
    stale_direct_url = (
        deployment_local_support._project_site_packages_dir(
            tmp_path,
            python_version="3.13",
        )
        / "pkg_b-0.0.dist-info"
        / "direct_url.json"
    )
    stale_direct_url.unlink()
    await deployment_local_support._install_many_into_project_venv(
        "uv",
        tmp_path,
        [package_a, package_b],
        run_fn=_fake_run,
        editable=True,
        no_deps=True,
        python_version="3.13",
    )

    assert calls == [
        (
            f'uv pip install --python "{venv_python}" --upgrade --no-deps '
            f'-e "{package_a}" -e "{package_b}"',
            tmp_path,
        ),
        (
            f'uv pip install --python "{venv_python}" --upgrade --no-deps '
            f'-e "{package_b}"',
            tmp_path,
        ),
    ]


def test_remove_project_venv_if_mismatched_preserves_matching_venv(tmp_path):
    venv_python = _write_venv_python(tmp_path, python_version="3.13.13")

    removed = deployment_local_support._remove_project_venv_if_mismatched(
        tmp_path,
        python_version="3.13.13",
    )

    assert removed is False
    assert venv_python.exists()


def test_remove_project_venv_if_mismatched_removes_broken_venv(tmp_path):
    venv_root = tmp_path / ".venv"
    venv_root.mkdir()
    (venv_root / "pyvenv.cfg").write_text("version = 3.13.13\n", encoding="utf-8")

    removed = deployment_local_support._remove_project_venv_if_mismatched(
        tmp_path,
        python_version="3.13",
    )

    assert removed is True
    assert not venv_root.exists()


def test_shared_worker_venv_project_is_disabled_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("AGILAB_SHARED_WORKER_VENV", raising=False)
    app_path = tmp_path / "app"
    wenv_abs = tmp_path / "wenv"
    app_path.mkdir()
    wenv_abs.mkdir()

    assert (
        deployment_local_support._shared_worker_venv_project(
            {},
            active_app=app_path,
            wenv_abs=wenv_abs,
            python_version="3.13",
            run_type="sync",
            options_worker="",
            worker_core_add_specs=[],
            hw_rapids_capable=False,
        )
        is None
    )


def test_shared_worker_venv_project_uses_compatible_cache_key(monkeypatch, tmp_path):
    monkeypatch.setenv("AGILAB_SHARED_WORKER_VENV", "1")
    app_path = tmp_path / "app"
    wenv_abs = tmp_path / "wenv"
    app_path.mkdir()
    wenv_abs.mkdir()
    (app_path / "pyproject.toml").write_text(
        "[project]\nname='app'\n", encoding="utf-8"
    )
    (wenv_abs / "pyproject.toml").write_text(
        "[project]\nname='worker'\n", encoding="utf-8"
    )

    first = deployment_local_support._shared_worker_venv_project(
        {},
        active_app=app_path,
        wenv_abs=wenv_abs,
        python_version="3.13",
        run_type="sync",
        options_worker=" --extra pandas-worker",
        worker_core_add_specs=["/core/agi-env", "/core/agi-node"],
        hw_rapids_capable=False,
    )
    second = deployment_local_support._shared_worker_venv_project(
        {},
        active_app=app_path,
        wenv_abs=wenv_abs,
        python_version="3.13",
        run_type="sync",
        options_worker=" --extra pandas-worker",
        worker_core_add_specs=["/core/agi-node", "/core/agi-env"],
        hw_rapids_capable=False,
    )
    changed = deployment_local_support._shared_worker_venv_project(
        {},
        active_app=app_path,
        wenv_abs=wenv_abs,
        python_version="3.13",
        run_type="sync",
        options_worker=" --extra polars-worker",
        worker_core_add_specs=["/core/agi-env", "/core/agi-node"],
        hw_rapids_capable=False,
    )

    assert first == second
    assert first is not None
    assert first.parent == wenv_abs.parent / ".runtime-cache"
    assert first.name.startswith("py3.13-")
    assert changed != first


def test_deploy_stage_cache_enabled_respects_refresh_and_disable(monkeypatch):
    monkeypatch.delenv("AGILAB_REFRESH_LOCKS", raising=False)
    monkeypatch.delenv("AGILAB_DISABLE_DEPLOY_STAGE_CACHE", raising=False)

    assert deployment_local_support._deploy_stage_cache_enabled({}) is True
    assert (
        deployment_local_support._deploy_stage_cache_enabled(
            {"AGILAB_DISABLE_DEPLOY_STAGE_CACHE": "1"}
        )
        is False
    )
    assert (
        deployment_local_support._deploy_stage_cache_enabled(
            {"AGILAB_REFRESH_LOCKS": "1"}
        )
        is False
    )


def test_deploy_stage_cache_support_edge_cases(monkeypatch, tmp_path):
    class _BrokenEnvars:
        def get(self, _key):
            raise RuntimeError("broken env source")

    assert deployment_stage_cache_support._env_value(_BrokenEnvars(), "FLAG") is None
    assert deployment_stage_cache_support._env_value({"FLAG": "  'yes'  "}, "FLAG") == "yes"
    assert deployment_stage_cache_support._env_truthy({"FLAG": '"on"'}, "FLAG") is True
    assert deployment_stage_cache_support._load_deploy_stage_cache(tmp_path / "missing.json") == {
        "schema": deployment_local_support.DEPLOY_STAGE_CACHE_SCHEMA,
        "stages": {},
    }

    invalid_cache = tmp_path / "invalid-cache.json"
    invalid_cache.write_text("[]", encoding="utf-8")
    assert deployment_stage_cache_support._load_deploy_stage_cache(invalid_cache) == {
        "schema": deployment_local_support.DEPLOY_STAGE_CACHE_SCHEMA,
        "stages": {},
    }

    cache_path = tmp_path / "cache" / "stages.json"
    deployment_stage_cache_support._write_deploy_stage_cache(
        cache_path,
        {"stages": {"manager-sync": {"digest": "abc"}}},
    )
    assert json.loads(cache_path.read_text(encoding="utf-8"))["stages"]["manager-sync"]["digest"] == "abc"

    trace_path = tmp_path / "trace" / "deploy.json"
    deployment_stage_cache_support._write_deploy_timing_trace(
        trace_path,
        stages=[{"stage": "manager-sync", "result": "ran", "seconds": 0.1}],
        results={"manager-sync": "ran"},
        app_path=tmp_path / "app",
        worker_project=tmp_path / "worker",
    )
    assert json.loads(trace_path.read_text(encoding="utf-8"))["schema"] == (
        deployment_local_support.DEPLOY_TIMING_TRACE_SCHEMA
    )

    def _raise_os_error(*_args, **_kwargs):
        raise OSError("write blocked")

    monkeypatch.setattr(Path, "write_text", _raise_os_error)
    deployment_stage_cache_support._write_deploy_stage_cache(tmp_path / "blocked.json", {})
    deployment_stage_cache_support._write_deploy_timing_trace(
        tmp_path / "blocked-trace.json",
        stages=[],
        results={},
        app_path=tmp_path,
        worker_project=tmp_path,
    )


def test_deploy_stage_fingerprints_and_copy_stamps_cover_edge_cases(monkeypatch, tmp_path):
    missing = tmp_path / "missing.txt"
    file_path = tmp_path / "data.txt"
    file_path.write_text("payload", encoding="utf-8")
    directory = tmp_path / "tree"
    nested = directory / "nested"
    nested.mkdir(parents=True)
    (nested / "item.txt").write_text("value", encoding="utf-8")

    missing_fp = deployment_stage_cache_support._deploy_stage_file_fingerprint(missing)
    assert missing_fp["missing"] is True
    dir_as_file = deployment_stage_cache_support._deploy_stage_file_fingerprint(directory)
    assert dir_as_file["kind"] == "directory"
    tree_fp = deployment_stage_cache_support._deploy_stage_directory_fingerprint(directory)
    assert tree_fp["kind"] == "directory"
    assert any(entry["path"] == "nested/item.txt" for entry in tree_fp["entries"])
    file_tree_fp = deployment_stage_cache_support._deploy_stage_directory_fingerprint(file_path)
    assert file_tree_fp["sha256"]

    stamp_path = deployment_stage_cache_support._deploy_copy_stamp_path(
        tmp_path / "output.txt",
        directory=False,
    )
    payload = deployment_stage_cache_support._deploy_copy_stamp_payload(
        kind="dataset",
        source=file_path,
        destination=tmp_path / "output.txt",
        source_fingerprint=deployment_stage_cache_support._deploy_stage_file_fingerprint(file_path),
    )
    assert not deployment_stage_cache_support._deploy_copy_stamp_matches(
        stamp_path,
        payload,
        output_probe=lambda: True,
    )
    deployment_stage_cache_support._write_deploy_copy_stamp(stamp_path, payload)
    assert deployment_stage_cache_support._deploy_copy_stamp_matches(
        stamp_path,
        payload,
        output_probe=lambda: True,
    )
    assert not deployment_stage_cache_support._deploy_copy_stamp_matches(
        stamp_path,
        {**payload, "kind": "other"},
        output_probe=lambda: True,
    )
    assert not deployment_stage_cache_support._deploy_copy_stamp_matches(
        stamp_path,
        payload,
        output_probe=lambda: (_ for _ in ()).throw(OSError("probe failed")),
    )
    assert deployment_stage_cache_support._deploy_stage_project_inputs(None, file_path) == [
        file_path / "pyproject.toml",
        file_path / "uv.lock",
        file_path / "uv_config.toml",
        file_path / "setup.py",
        file_path / "setup.cfg",
    ]

    def _raise_os_error(*_args, **_kwargs):
        raise OSError("write blocked")

    monkeypatch.setattr(Path, "write_text", _raise_os_error)
    deployment_stage_cache_support._write_deploy_copy_stamp(tmp_path / "blocked.json", payload)


def test_deploy_stage_fingerprints_cover_unreadable_and_large_inputs(monkeypatch, tmp_path):
    class _BrokenPath:
        def expanduser(self):
            return self

        def resolve(self, *, strict=False):
            del strict
            raise RuntimeError("cannot resolve")

        def as_posix(self):
            return "broken-path"

    assert deployment_stage_cache_support._deploy_stage_file_fingerprint(_BrokenPath()) == {
        "path": "broken-path",
        "missing": True,
    }
    assert deployment_stage_cache_support._deploy_stage_directory_fingerprint(_BrokenPath()) == {
        "path": "broken-path",
        "missing": True,
    }

    large_file = tmp_path / "large.bin"
    large_file.write_bytes(b"abc")
    monkeypatch.setattr(deployment_stage_cache_support, "DEPLOY_STAGE_CACHE_HASH_LIMIT", 1)
    large_fp = deployment_stage_cache_support._deploy_stage_file_fingerprint(large_file)
    assert "sha256" not in large_fp
    assert "mtime_ns" in large_fp
    monkeypatch.setattr(
        deployment_stage_cache_support,
        "DEPLOY_STAGE_CACHE_HASH_LIMIT",
        8 * 1024 * 1024,
    )

    readable_file = tmp_path / "readable.txt"
    readable_file.write_text("payload", encoding="utf-8")
    original_read_bytes = Path.read_bytes

    def _raise_read_bytes(path):
        if path == readable_file:
            raise OSError("blocked")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", _raise_read_bytes)
    unreadable_file_fp = deployment_stage_cache_support._deploy_stage_file_fingerprint(readable_file)
    assert "sha256" not in unreadable_file_fp
    assert "mtime_ns" in unreadable_file_fp

    tree = tmp_path / "tree"
    tree.mkdir()
    original_stat = Path.stat

    def _raise_stat(path, *args, **kwargs):
        if path == tree:
            raise OSError("stat blocked")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", _raise_stat)
    assert deployment_stage_cache_support._deploy_stage_directory_fingerprint(tree)["missing"] is True
    monkeypatch.setattr(Path, "stat", original_stat)

    original_rglob = Path.rglob

    def _raise_rglob(path, pattern):
        if path == tree:
            raise OSError("blocked")
        return original_rglob(path, pattern)

    monkeypatch.setattr(Path, "rglob", _raise_rglob)
    unreadable_tree_fp = deployment_stage_cache_support._deploy_stage_directory_fingerprint(tree)
    assert unreadable_tree_fp["unreadable"] is True
    monkeypatch.setattr(Path, "rglob", lambda _path, _pattern: [tmp_path / "external.txt"])
    (tmp_path / "external.txt").write_text("outside", encoding="utf-8")
    external_tree_fp = deployment_stage_cache_support._deploy_stage_directory_fingerprint(tree)
    assert external_tree_fp["entries"][0]["path"] == "external.txt"

    broken_link = tree / "broken-link"
    try:
        broken_link.symlink_to(tree / "missing-target")
    except (OSError, NotImplementedError):
        broken_link = tree / "plain"
    monkeypatch.setattr(Path, "rglob", lambda _path, _pattern: [broken_link])
    other_tree_fp = deployment_stage_cache_support._deploy_stage_directory_fingerprint(tree)
    assert other_tree_fp["entries"][0]["kind"] == "other"

    bad_child = tree / "bad-child"
    monkeypatch.setattr(Path, "rglob", lambda _path, _pattern: [bad_child])
    original_is_dir = Path.is_dir

    def _raise_is_dir(path):
        if path == bad_child:
            raise OSError("bad child")
        return original_is_dir(path)

    monkeypatch.setattr(Path, "is_dir", _raise_is_dir)
    bad_child_tree_fp = deployment_stage_cache_support._deploy_stage_directory_fingerprint(tree)
    assert bad_child_tree_fp["entries"] == [{"path": "bad-child", "unreadable": True}]


def test_dependency_module_and_pth_import_roots_cover_edge_branches(monkeypatch, tmp_path):
    modules = deployment_local_support._dependency_modules_from_info(
        {
            "agi-env": {"name": "agi-env"},
            "dask": {"name": "dask", "extras": {"distributed"}},
            "pillow": {"name": "pillow", "extras": set()},
        }
    )
    assert modules == ("dask", "distributed", "PIL")

    site_packages = tmp_path / "site-packages"
    site_packages.mkdir()
    relative_root = site_packages / "relative-src"
    absolute_root = tmp_path / "absolute-src"
    relative_root.mkdir()
    absolute_root.mkdir()
    (site_packages / "demo.pth").write_text(
        "\n# comment\nimport site\nrelative-src\n" + str(absolute_root) + "\n",
        encoding="utf-8",
    )
    roots = deployment_local_support._pth_import_roots(site_packages)
    assert roots == (relative_root.resolve(strict=False), absolute_root.resolve(strict=False))
    assert deployment_local_support._module_available_on_root(relative_root, ".")

    original_read_text = Path.read_text

    def _raise_for_pth(path, *args, **kwargs):
        if path.name == "demo.pth":
            raise OSError("blocked")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _raise_for_pth)
    assert deployment_local_support._pth_import_roots(site_packages) == ()

    original_glob = Path.glob

    def _raise_for_site_packages(path, pattern):
        if path == site_packages and pattern == "*.pth":
            raise OSError("blocked")
        return original_glob(path, pattern)

    monkeypatch.setattr(Path, "glob", _raise_for_site_packages)
    assert deployment_local_support._pth_import_roots(site_packages) == ()


def test_editable_install_support_edge_cases(tmp_path):
    cache_path = tmp_path / "editable-cache.json"
    assert deployment_editable_install_support._load_editable_install_cache(cache_path) == {
        "schema": deployment_local_support.EDITABLE_INSTALL_CACHE_SCHEMA,
        "installs": {},
    }
    cache_path.write_text("[]", encoding="utf-8")
    assert deployment_editable_install_support._load_editable_install_cache(cache_path) == {
        "schema": deployment_local_support.EDITABLE_INSTALL_CACHE_SCHEMA,
        "installs": {},
    }
    deployment_editable_install_support._write_editable_install_cache(
        cache_path,
        {"installs": {"demo": {"digest": "abc"}}},
    )
    assert json.loads(cache_path.read_text(encoding="utf-8"))["installs"]["demo"]["digest"] == "abc"
    assert deployment_editable_install_support._editable_install_project(object()) is None

    site_packages = deployment_local_support._project_site_packages_dir(
        tmp_path,
        python_version="3.13",
    )
    site_packages.mkdir(parents=True)
    package_project = tmp_path / "pkg"
    package_project.mkdir()
    (package_project / "pyproject.toml").write_text("[project]\nname='pkg'\n", encoding="utf-8")
    bad_dist = site_packages / "bad.dist-info"
    bad_dist.mkdir()
    (bad_dist / "direct_url.json").write_text("{bad json", encoding="utf-8")
    noneditable_dist = site_packages / "noneditable.dist-info"
    noneditable_dist.mkdir()
    (noneditable_dist / "direct_url.json").write_text(
        json.dumps({"url": package_project.resolve(strict=False).as_uri(), "dir_info": {}}),
        encoding="utf-8",
    )
    remote_dist = site_packages / "remote.dist-info"
    remote_dist.mkdir()
    (remote_dist / "direct_url.json").write_text(
        json.dumps({"url": "file://remote.example/tmp/pkg", "dir_info": {"editable": True}}),
        encoding="utf-8",
    )
    good_dist = site_packages / "good.dist-info"
    good_dist.mkdir()
    (good_dist / "direct_url.json").write_text(
        json.dumps(
            {
                "url": package_project.resolve(strict=False).as_uri(),
                "dir_info": {"editable": True},
            }
        ),
        encoding="utf-8",
    )
    assert deployment_editable_install_support._editable_install_proof_exists(
        tmp_path,
        package_project,
        python_version="3.13",
    )


def test_editable_install_proof_accepts_windows_file_url(tmp_path):
    site_packages = deployment_local_support._project_site_packages_dir(
        tmp_path,
        os_name="nt",
        python_version="3.13",
    )
    site_packages.mkdir(parents=True)
    dist_info = site_packages / "windows.dist-info"
    dist_info.mkdir()
    (dist_info / "direct_url.json").write_text(
        json.dumps({"url": "file:///C:/src/pkg", "dir_info": {"editable": True}}),
        encoding="utf-8",
    )

    assert deployment_editable_install_support._editable_install_proof_exists(
        tmp_path,
        Path("C:/src/pkg"),
        os_name="nt",
        python_version="3.13",
    )


def test_editable_install_support_remaining_error_edges(monkeypatch, tmp_path):
    shadow_file = tmp_path / "shadow.py"
    shadow_file.write_text("# stale\n", encoding="utf-8")
    original_unlink = Path.unlink

    def _unlink_race(path, *args, **kwargs):
        if path == shadow_file:
            raise FileNotFoundError
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", _unlink_race)
    assert deployment_editable_install_support._remove_site_package_shadow(shadow_file) is False

    original_write_text = Path.write_text

    def _raise_write_text(*_args, **_kwargs):
        raise OSError("blocked")

    monkeypatch.setattr(Path, "write_text", _raise_write_text)
    deployment_editable_install_support._write_editable_install_cache(
        tmp_path / "blocked-cache.json",
        {"installs": {"demo": {"digest": "abc"}}},
    )
    monkeypatch.setattr(Path, "write_text", original_write_text)

    site_packages = deployment_local_support._project_site_packages_dir(
        tmp_path,
        python_version="3.13",
    )
    site_packages.mkdir(parents=True, exist_ok=True)
    package_project = tmp_path / "pkg"
    package_project.mkdir()

    original_glob = Path.glob

    def _raise_glob(path, pattern):
        if path == site_packages and pattern == "*.dist-info/direct_url.json":
            raise OSError("blocked")
        return original_glob(path, pattern)

    monkeypatch.setattr(Path, "glob", _raise_glob)
    assert not deployment_editable_install_support._editable_install_proof_exists(
        tmp_path,
        package_project,
        python_version="3.13",
    )
    monkeypatch.setattr(Path, "glob", original_glob)

    for index, payload in enumerate(
        [
            [],
            {"dir_info": {"editable": True}},
            {"url": "https://example.test/pkg", "dir_info": {"editable": True}},
            {"url": "file://remote.example/tmp/pkg", "dir_info": {"editable": True}},
        ],
        start=1,
    ):
        dist_info = site_packages / f"invalid-{index}.dist-info"
        dist_info.mkdir()
        (dist_info / "direct_url.json").write_text(json.dumps(payload), encoding="utf-8")
    assert not deployment_editable_install_support._editable_install_proof_exists(
        tmp_path,
        package_project,
        python_version="3.13",
    )

    monkeypatch.setattr(
        deployment_editable_install_support,
        "_load_editable_install_cache",
        lambda _path: {"installs": []},
    )
    assert not deployment_editable_install_support._editable_install_cache_hit(
        uv_cmd="uv",
        package_project=package_project,
        venv_project=tmp_path,
        editable=True,
        no_deps=False,
        python_version="3.13",
        os_name="posix",
    )
    monkeypatch.setattr(
        deployment_editable_install_support,
        "_editable_install_proof_exists",
        lambda *_args, **_kwargs: True,
    )
    deployment_editable_install_support._record_editable_install_cache(
        uv_cmd="uv",
        package_project=package_project,
        venv_project=tmp_path,
        editable=True,
        no_deps=False,
        python_version="3.13",
        os_name="posix",
    )


@pytest.mark.asyncio
async def test_run_cached_deploy_stage_reuses_and_invalidates_metadata(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    input_file = project / "pyproject.toml"
    input_file.write_text("[project]\nname='demo'\n", encoding="utf-8")
    output_file = _venv_python(project)
    cache_path = tmp_path / "wenv" / ".agilab-stage-cache.json"
    calls = []

    async def _fake_run(cmd, cwd):
        calls.append((cmd, cwd))
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text("", encoding="utf-8")

    await deployment_local_support._run_cached_deploy_stage(
        stage_name="manager-sync",
        cmd="uv sync",
        cwd=project,
        run_fn=_fake_run,
        cache_enabled=True,
        cache_state=deployment_local_support._load_deploy_stage_cache(cache_path),
        cache_path=cache_path,
        inputs=[input_file],
        output_probe=output_file.exists,
        log=mock.Mock(),
    )
    await deployment_local_support._run_cached_deploy_stage(
        stage_name="manager-sync",
        cmd="uv sync",
        cwd=project,
        run_fn=_fake_run,
        cache_enabled=True,
        cache_state=deployment_local_support._load_deploy_stage_cache(cache_path),
        cache_path=cache_path,
        inputs=[input_file],
        output_probe=output_file.exists,
        log=mock.Mock(),
    )

    input_file.write_text(
        "[project]\nname='demo'\ndependencies=['numpy']\n", encoding="utf-8"
    )
    await deployment_local_support._run_cached_deploy_stage(
        stage_name="manager-sync",
        cmd="uv sync",
        cwd=project,
        run_fn=_fake_run,
        cache_enabled=True,
        cache_state=deployment_local_support._load_deploy_stage_cache(cache_path),
        cache_path=cache_path,
        inputs=[input_file],
        output_probe=output_file.exists,
        log=mock.Mock(),
    )

    assert calls == [("uv sync", project), ("uv sync", project)]


@pytest.mark.asyncio
async def test_run_cached_deploy_stage_requires_output_probe(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    input_file = project / "pyproject.toml"
    input_file.write_text("[project]\nname='demo'\n", encoding="utf-8")
    output_file = _venv_python(project)
    cache_path = tmp_path / "wenv" / ".agilab-stage-cache.json"
    calls = []

    async def _fake_run(cmd, cwd):
        calls.append((cmd, cwd))
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text("", encoding="utf-8")

    await deployment_local_support._run_cached_deploy_stage(
        stage_name="worker-sync",
        cmd="uv sync --project worker",
        cwd=project,
        run_fn=_fake_run,
        cache_enabled=True,
        cache_state=deployment_local_support._load_deploy_stage_cache(cache_path),
        cache_path=cache_path,
        inputs=[input_file],
        output_probe=output_file.exists,
        log=mock.Mock(),
    )
    output_file.unlink()
    await deployment_local_support._run_cached_deploy_stage(
        stage_name="worker-sync",
        cmd="uv sync --project worker",
        cwd=project,
        run_fn=_fake_run,
        cache_enabled=True,
        cache_state=deployment_local_support._load_deploy_stage_cache(cache_path),
        cache_path=cache_path,
        inputs=[input_file],
        output_probe=output_file.exists,
        log=mock.Mock(),
    )

    assert calls == [
        ("uv sync --project worker", project),
        ("uv sync --project worker", project),
    ]


@pytest.mark.asyncio
async def test_deploy_plan_enforces_dependencies_and_records_results(tmp_path):
    calls = []

    async def _fake_run(cmd, cwd):
        calls.append((cmd, cwd))

    plan = deployment_local_support._DeployPlan(
        run_fn=_fake_run,
        cache_enabled=False,
        cache_state={
            "schema": deployment_local_support.DEPLOY_STAGE_CACHE_SCHEMA,
            "stages": {},
        },
        cache_path=tmp_path / "cache.json",
        log=mock.Mock(),
    )
    first = deployment_local_support._DeployPlanNode(
        name="manager-sync",
        cmd="uv sync --project manager",
        cwd=tmp_path,
        inputs=[],
        output_probe=lambda: True,
    )
    second = deployment_local_support._DeployPlanNode(
        name="worker-sync",
        cmd="uv sync --project worker",
        cwd=tmp_path,
        inputs=[],
        output_probe=lambda: True,
        dependencies=("manager-sync",),
    )

    with pytest.raises(RuntimeError, match="missing dependencies: manager-sync"):
        await plan.run(second)

    assert await plan.run(first) == "ran"
    assert await plan.run(second) == "ran"
    assert calls == [
        ("uv sync --project manager", tmp_path),
        ("uv sync --project worker", tmp_path),
    ]
    assert plan.results == {"manager-sync": "ran", "worker-sync": "ran"}


@pytest.mark.asyncio
async def test_deploy_plan_records_cached_skips(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    input_file = project / "pyproject.toml"
    input_file.write_text("[project]\nname='demo'\n", encoding="utf-8")
    output_file = _venv_python(project)
    cache_path = tmp_path / "wenv" / ".agilab-stage-cache.json"
    calls = []

    async def _fake_run(cmd, cwd):
        calls.append((cmd, cwd))
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text("", encoding="utf-8")

    node = deployment_local_support._DeployPlanNode(
        name="manager-sync",
        cmd="uv sync --project manager",
        cwd=project,
        inputs=[input_file],
        output_probe=output_file.exists,
    )
    first_plan = deployment_local_support._DeployPlan(
        run_fn=_fake_run,
        cache_enabled=True,
        cache_state=deployment_local_support._load_deploy_stage_cache(cache_path),
        cache_path=cache_path,
        log=mock.Mock(),
    )

    assert await first_plan.run(node) == "ran"

    second_plan = deployment_local_support._DeployPlan(
        run_fn=_fake_run,
        cache_enabled=True,
        cache_state=deployment_local_support._load_deploy_stage_cache(cache_path),
        cache_path=cache_path,
        log=mock.Mock(),
    )

    assert await second_plan.run(node) == "skipped"
    assert calls == [("uv sync --project manager", project)]
    assert second_plan.results == {"manager-sync": "skipped"}


@pytest.mark.asyncio
async def test_deploy_plan_records_stage_timings(tmp_path):
    calls = []
    times = iter([1.0, 1.25, 2.0, 2.01])

    async def _fake_run(cmd, cwd):
        calls.append((cmd, cwd))

    plan = deployment_local_support._DeployPlan(
        run_fn=_fake_run,
        cache_enabled=False,
        cache_state={
            "schema": deployment_local_support.DEPLOY_STAGE_CACHE_SCHEMA,
            "stages": {},
        },
        cache_path=tmp_path / "cache.json",
        log=mock.Mock(),
        time_fn=lambda: next(times),
    )

    assert await plan.run(
        deployment_local_support._DeployPlanNode(
            name="manager-sync",
            cmd="uv sync --project manager",
            cwd=tmp_path,
            inputs=[],
            output_probe=lambda: True,
        )
    ) == "ran"
    plan.record_timing("worker-build-lib", "ran", 0.01)

    assert calls == [("uv sync --project manager", tmp_path)]
    assert plan.timings == [
        {"stage": "manager-sync", "result": "ran", "seconds": 0.25},
        {"stage": "worker-build-lib", "result": "ran", "seconds": 0.01},
    ]


def test_write_deploy_timing_trace_is_structured(tmp_path):
    app_path = tmp_path / "app"
    worker_project = tmp_path / "wenv"
    trace_path = deployment_local_support._deploy_timing_trace_path(worker_project)

    deployment_local_support._write_deploy_timing_trace(
        trace_path,
        stages=[
            {"stage": "manager-sync", "result": "skipped", "seconds": 0.001},
            {"stage": "worker-build-lib", "result": "ran", "seconds": 0.2},
        ],
        results={"manager-sync": "skipped"},
        app_path=app_path,
        worker_project=worker_project,
    )

    payload = json.loads(trace_path.read_text(encoding="utf-8"))
    assert payload == {
        "schema": deployment_local_support.DEPLOY_TIMING_TRACE_SCHEMA,
        "app_path": app_path.resolve(strict=False).as_posix(),
        "worker_project": worker_project.resolve(strict=False).as_posix(),
        "stages": [
            {"stage": "manager-sync", "result": "skipped", "seconds": 0.001},
            {"stage": "worker-build-lib", "result": "ran", "seconds": 0.2},
        ],
        "results": {"manager-sync": "skipped"},
    }


@pytest.mark.asyncio
async def test_install_into_project_venv_can_resolve_dependencies_with_worker_python(
    tmp_path,
):
    calls = []
    package_path = tmp_path / "pkg"
    package_path.mkdir()

    async def _fake_run(cmd, cwd):
        calls.append((cmd, cwd))

    await deployment_local_support._install_into_project_venv(
        "uv --offline",
        tmp_path,
        package_path,
        run_fn=_fake_run,
        editable=True,
        no_deps=False,
        python_version="3.13",
    )

    assert calls == [
        (
            f'uv --offline venv --allow-existing --python 3.13 "{tmp_path / ".venv"}"',
            tmp_path,
        ),
        (
            f'uv --offline pip install --python "{_venv_python(tmp_path)}" '
            f'--upgrade -e "{package_path}"',
            tmp_path,
        ),
    ]


def test_project_venv_python_uses_windows_layout(tmp_path):
    assert deployment_local_support._project_venv_python(tmp_path, os_name="nt") == (
        tmp_path / ".venv" / "Scripts" / "python.exe"
    )


def test_resolve_install_spec_prefers_project_path_over_distribution_metadata(
    tmp_path, monkeypatch
):
    project_path = tmp_path / "agi-env"
    project_path.mkdir()
    (project_path / "pyproject.toml").write_text(
        "[project]\nname='agi-env'\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        deployment_local_support,
        "_resolve_distribution_install_spec",
        lambda _name: "agi-env==0.0.0",
    )

    assert deployment_local_support._resolve_install_spec(
        project_path, "agi-env"
    ) == str(project_path)


def test_resolve_install_spec_falls_back_to_distribution_metadata_for_non_project_path(
    tmp_path, monkeypatch
):
    project_path = tmp_path / "agi-env"
    project_path.mkdir()
    monkeypatch.setattr(
        deployment_local_support,
        "_resolve_distribution_install_spec",
        lambda _name: "agi-env==0.0.0",
    )

    assert (
        deployment_local_support._resolve_install_spec(project_path, "agi-env")
        == "agi-env==0.0.0"
    )


def test_build_worker_core_add_commands_marks_local_projects_editable(tmp_path):
    env_project = tmp_path / "agi-env"
    node_project = tmp_path / "agi-node"
    wenv = tmp_path / "wenv"
    for project in (env_project, node_project, wenv):
        project.mkdir()
    (env_project / "pyproject.toml").write_text(
        "[project]\nname='agi-env'\n", encoding="utf-8"
    )
    (node_project / "pyproject.toml").write_text(
        "[project]\nname='agi-node'\n", encoding="utf-8"
    )

    commands = deployment_local_support._build_worker_core_add_commands(
        "uv",
        wenv,
        [str(env_project), str(node_project)],
        offline_flag="--offline ",
        prefix="PIP_INDEX_URL=https://test.pypi.org/simple; ",
    )

    assert commands == [
        (
            "PIP_INDEX_URL=https://test.pypi.org/simple; "
            f'uv --offline --project {wenv} add --editable "{env_project}" "{node_project}"'
        )
    ]


def test_build_worker_core_add_commands_keeps_distribution_specs_non_editable(tmp_path):
    env_project = tmp_path / "agi-env"
    wenv = tmp_path / "wenv"
    for project in (env_project, wenv):
        project.mkdir()
    (env_project / "pyproject.toml").write_text(
        "[project]\nname='agi-env'\n", encoding="utf-8"
    )

    commands = deployment_local_support._build_worker_core_add_commands(
        "uv",
        wenv,
        [
            str(env_project),
            "agi-node @ git+https://example.invalid/repo.git@main#subdirectory=agi-node",
        ],
    )

    assert commands == [
        f'uv --project {wenv} add --editable "{env_project}"',
        'uv --project {} add "agi-node @ git+https://example.invalid/repo.git@main#subdirectory=agi-node"'.format(
            wenv
        ),
    ]


def test_is_local_project_install_spec_treats_unreadable_paths_as_non_local(
    monkeypatch,
):
    def _raise_os_error(_path):
        raise OSError("unreadable")

    monkeypatch.setattr(deployment_local_support, "_is_python_project", _raise_os_error)

    assert (
        deployment_local_support._is_local_project_install_spec("/unreadable/path")
        is False
    )


def test_resolve_distribution_install_spec_returns_none_when_distribution_is_missing(
    monkeypatch,
):
    def _missing(_name):
        raise deployment_local_support.PackageNotFoundError

    monkeypatch.setattr(deployment_local_support, "pkg_distribution", _missing)

    assert (
        deployment_local_support._resolve_distribution_install_spec("agi-env") is None
    )


def test_resolve_distribution_install_spec_uses_direct_url_git_revision(monkeypatch):
    class _Dist:
        version = "1.2.3"

        @staticmethod
        def read_text(name):
            assert name == "direct_url.json"
            return (
                '{"url":"https://github.com/ThalesGroup/agilab.git",'
                '"vcs_info":{"vcs":"git","requested_revision":"main"},'
                '"subdirectory":"src/agilab/core/agi-env"}'
            )

    monkeypatch.setattr(
        deployment_local_support, "pkg_distribution", lambda _name: _Dist()
    )

    assert (
        deployment_local_support._resolve_distribution_install_spec("agi-env")
        == "agi-env @ git+https://github.com/ThalesGroup/agilab.git@main#subdirectory=src/agilab/core/agi-env"
    )


def test_resolve_distribution_install_spec_uses_direct_url_with_subdirectory_without_vcs(
    monkeypatch,
):
    class _Dist:
        version = "2026.4.20"

        @staticmethod
        def read_text(name):
            assert name == "direct_url.json"
            return '{"url":"https://example.com/agi-env.tar.gz","subdirectory":"src/agi-env"}'

    monkeypatch.setattr(
        deployment_local_support, "pkg_distribution", lambda _name: _Dist()
    )

    assert (
        deployment_local_support._resolve_distribution_install_spec("agi-env")
        == "agi-env @ https://example.com/agi-env.tar.gz#subdirectory=src/agi-env"
    )


def test_resolve_distribution_install_spec_falls_back_to_installed_version(monkeypatch):
    class _Dist:
        version = "2026.4.20"

        @staticmethod
        def read_text(_name):
            return None

    monkeypatch.setattr(
        deployment_local_support, "pkg_distribution", lambda _name: _Dist()
    )

    assert (
        deployment_local_support._resolve_distribution_install_spec("agi-env")
        == "agi-env==2026.4.20"
    )


def test_resolve_distribution_install_spec_ignores_invalid_direct_url_json(monkeypatch):
    class _Dist:
        version = "2026.4.20"

        @staticmethod
        def read_text(_name):
            return "{invalid-json"

    monkeypatch.setattr(
        deployment_local_support, "pkg_distribution", lambda _name: _Dist()
    )

    assert (
        deployment_local_support._resolve_distribution_install_spec("agi-env")
        == "agi-env==2026.4.20"
    )


def test_format_dependency_spec_and_repo_helpers_cover_edge_cases(tmp_path):
    assert (
        deployment_local_support._format_dependency_spec(
            "pandas",
            {"performance"},
            [">=2", "<3"],
        )
        == "pandas[performance]>=2,<3"
    )
    assert deployment_local_support._is_within_repo(tmp_path / "child", None) is False
    assert deployment_local_support._is_within_repo(tmp_path / "child", False) is False

    class _BrokenPath:
        def resolve(self):
            raise RuntimeError("resolve failed")

    assert deployment_local_support._is_within_repo(_BrokenPath(), tmp_path) is False


def test_read_agilab_repo_root_normalizes_missing_marker(monkeypatch):
    monkeypatch.setattr(
        deployment_local_support.AgiEnv,
        "read_agilab_path",
        staticmethod(lambda: False),
    )

    assert deployment_local_support._read_agilab_repo_root() is None


def test_parse_dependency_names_skips_non_strings_and_invalid_requirements():
    assert deployment_local_support._parse_dependency_names(
        ["numpy>=1.26", 3, None, "not["]
    ) == {"numpy"}


def test_manager_dependency_names_returns_empty_for_missing_or_invalid_pyproject(
    tmp_path,
):
    missing = tmp_path / "missing.toml"
    invalid = tmp_path / "invalid.toml"
    invalid.write_text("[project\nname = 'broken'\n", encoding="utf-8")

    assert deployment_local_support._manager_dependency_names(missing) == set()
    assert deployment_local_support._manager_dependency_names(invalid) == set()


def test_manager_overlay_core_sources_recovers_when_second_parse_fails(
    tmp_path, monkeypatch
):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "demo"
dependencies = ["agi-env"]
""".strip(),
        encoding="utf-8",
    )
    agi_env_path = tmp_path / "agi-env"
    agi_env_path.mkdir()

    real_parse = tomlkit.parse
    parse_calls = {"count": 0}

    def _parse(text):
        parse_calls["count"] += 1
        if parse_calls["count"] == 1:
            return real_parse(text)
        raise OSError("cannot reparse")

    monkeypatch.setattr(deployment_local_support.tomlkit, "parse", _parse)

    # The overlay stores POSIX separators (uv requires them on every platform).
    assert deployment_local_support._manager_overlay_core_sources(
        pyproject,
        {"agi-env": agi_env_path},
    ) == {"agi-env": agi_env_path.resolve(strict=False).as_posix()}


def test_manager_overlay_core_sources_preserves_existing_paths_and_adds_missing_ones(
    tmp_path,
):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "demo"
dependencies = ["agi-env", "agi-node"]

[tool.uv.sources]
agi-env = { path = "../already-local" }
agi-node = { path = "   " }
""".strip(),
        encoding="utf-8",
    )
    agi_env_path = tmp_path / "agi-env"
    agi_node_path = tmp_path / "agi-node"
    agi_env_path.mkdir()
    agi_node_path.mkdir()

    # The overlay stores POSIX separators (uv requires them on every platform).
    assert deployment_local_support._manager_overlay_core_sources(
        pyproject,
        {
            "agi-env": agi_env_path,
            "agi-node": agi_node_path,
        },
    ) == {"agi-node": agi_node_path.resolve(strict=False).as_posix()}


def test_write_manager_sync_overlay_bootstraps_missing_tables(tmp_path):
    source_pyproject = tmp_path / "pyproject.toml"
    source_pyproject.write_text("", encoding="utf-8")
    overlay_dir = tmp_path / "overlay"

    deployment_local_support._write_manager_sync_overlay(
        source_pyproject,
        overlay_dir,
        local_core_sources={
            "agi-env": str((tmp_path / "agi-env").resolve(strict=False))
        },
    )

    overlay_doc = tomlkit.parse(
        (overlay_dir / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert overlay_doc["tool"]["uv"]["sources"]["agi-env"]["path"] == str(
        (tmp_path / "agi-env").resolve(strict=False)
    )


def test_write_manager_sync_overlay_normalizes_paths_and_skips_invalid_entries(
    tmp_path,
):
    source_dir = tmp_path / "apps" / "demo"
    source_dir.mkdir(parents=True, exist_ok=True)
    abs_dep = tmp_path / "abs-dep"
    abs_dep.mkdir()
    source_pyproject = source_dir / "pyproject.toml"
    # TOML literal strings ('...') keep Windows backslashes intact when paths
    # are absolute (e.g. C:\\Users\\...).  uv stores POSIX-style separators back
    # into the overlay, so the assertions below compare against ``as_posix()``.
    source_pyproject.write_text(
        f"""
[project]
name = "demo"

[tool.uv.sources]
demo = {{ workspace = true }}
non_dict = "skip-me"
blank = {{ path = "   " }}
rel = {{ path = "../shared" }}
abs = {{ path = '{abs_dep}' }}
""".strip(),
        encoding="utf-8",
    )
    overlay_dir = tmp_path / "overlay"

    deployment_local_support._write_manager_sync_overlay(
        source_pyproject,
        overlay_dir,
        local_core_sources={},
    )

    overlay_doc = tomlkit.parse(
        (overlay_dir / "pyproject.toml").read_text(encoding="utf-8")
    )
    sources = overlay_doc["tool"]["uv"]["sources"]
    assert "demo" not in sources
    assert sources["non_dict"] == "skip-me"
    assert sources["blank"]["path"] == "   "
    assert sources["rel"]["path"] == (
        (source_dir / "../shared").resolve(strict=False).as_posix()
    )
    assert sources["abs"]["path"] == abs_dep.resolve(strict=False).as_posix()


def test_shell_env_prefix_returns_empty_for_no_overrides():
    assert deployment_local_support._shell_env_prefix({}) == ""


def test_uv_offline_flag_handles_failing_lookup_false_and_nan(monkeypatch):
    monkeypatch.delenv("AGI_INTERNET_ON", raising=False)
    monkeypatch.delenv("UV_INDEX_URL", raising=False)

    class _BrokenEnvars:
        def get(self, _key):
            raise RuntimeError("boom")

    assert deployment_local_support._uv_offline_flag(_BrokenEnvars()) == ""
    assert (
        deployment_local_support._uv_offline_flag({"AGI_INTERNET_ON": False})
        == "--offline "
    )
    assert (
        deployment_local_support._uv_offline_flag({"AGI_INTERNET_ON": float("nan")})
        == "--offline "
    )


def test_uv_offline_flag_accepts_quoted_truthy_env_values(monkeypatch):
    monkeypatch.setenv("AGI_INTERNET_ON", '"1"')

    assert deployment_local_support._uv_offline_flag({}) == ""


def test_uv_offline_flag_accepts_quoted_truthy_envar_values(monkeypatch):
    monkeypatch.delenv("AGI_INTERNET_ON", raising=False)

    assert (
        deployment_local_support._uv_offline_flag({"AGI_INTERNET_ON": "'true'"}) == ""
    )
    assert deployment_local_support._uv_offline_flag({"AGI_INTERNET_ON": '"yes"'}) == ""
    assert deployment_local_support._uv_offline_flag({"AGI_INTERNET_ON": '"on"'}) == ""


def test_uv_offline_flag_keeps_quoted_false_values_offline(monkeypatch):
    monkeypatch.delenv("AGI_INTERNET_ON", raising=False)
    monkeypatch.delenv("UV_INDEX_URL", raising=False)

    assert (
        deployment_local_support._uv_offline_flag({"AGI_INTERNET_ON": '"0"'})
        == "--offline "
    )
    assert (
        deployment_local_support._uv_offline_flag({"AGI_INTERNET_ON": "'false'"})
        == "--offline "
    )


def test_uv_offline_flag_uses_uv_index_url_mirror_when_internet_disabled(monkeypatch):
    monkeypatch.delenv("AGI_INTERNET_ON", raising=False)
    monkeypatch.delenv("UV_INDEX_URL", raising=False)
    monkeypatch.delenv("UV_EXTRA_INDEX_URL", raising=False)
    monkeypatch.delenv("UV_FIND_LINKS", raising=False)

    assert (
        deployment_local_support._uv_offline_flag(
            {
                "AGI_INTERNET_ON": "0",
                "UV_INDEX_URL": "http://mirror.local/simple",
            }
        )
        == ""
    )

    monkeypatch.setenv("UV_INDEX_URL", "http://mirror.local/simple")
    assert deployment_local_support._uv_offline_flag({"AGI_INTERNET_ON": "0"}) == ""

    monkeypatch.setenv("UV_INDEX_URL", "")
    assert (
        deployment_local_support._uv_offline_flag({"AGI_INTERNET_ON": "0"})
        == "--offline "
    )


def test_uv_resolver_mode_covers_extra_index_wheelhouse_and_placeholders(monkeypatch):
    monkeypatch.delenv("AGI_INTERNET_ON", raising=False)
    monkeypatch.delenv("UV_INDEX_URL", raising=False)
    monkeypatch.delenv("UV_EXTRA_INDEX_URL", raising=False)
    monkeypatch.delenv("UV_FIND_LINKS", raising=False)

    assert (
        deployment_local_support._uv_resolver_mode(
            {
                "AGI_INTERNET_ON": "0",
                "UV_EXTRA_INDEX_URL": "http://mirror.local/simple",
            }
        )
        == "mirror"
    )
    assert (
        deployment_local_support._uv_offline_flag(
            {
                "AGI_INTERNET_ON": "0",
                "UV_EXTRA_INDEX_URL": "http://mirror.local/simple",
            }
        )
        == ""
    )

    assert (
        deployment_local_support._uv_resolver_mode(
            {
                "AGI_INTERNET_ON": "0",
                "UV_FIND_LINKS": "/mnt/wheelhouse",
            }
        )
        == "wheelhouse"
    )
    assert (
        deployment_local_support._uv_offline_flag(
            {
                "AGI_INTERNET_ON": "0",
                "UV_FIND_LINKS": "/mnt/wheelhouse",
            }
        )
        == "--offline "
    )

    assert (
        deployment_local_support._uv_resolver_mode(
            {
                "AGI_INTERNET_ON": "0",
                "UV_INDEX_URL": "None",
                "UV_EXTRA_INDEX_URL": "null",
            }
        )
        == "cache-only"
    )


def test_local_worker_post_install_env_prefix_disables_cluster_only_for_non_dask():
    assert (
        deployment_local_support._local_worker_post_install_env_prefix(
            SimpleNamespace(_mode=0, DASK_MODE=4),
            os_name="posix",
        )
        == "AGI_CLUSTER_ENABLED=0 "
    )
    assert (
        deployment_local_support._local_worker_post_install_env_prefix(
            SimpleNamespace(_mode=4, DASK_MODE=4),
            os_name="posix",
        )
        == ""
    )
    assert (
        deployment_local_support._local_worker_post_install_env_prefix(
            SimpleNamespace(_mode=0, DASK_MODE=4),
            os_name="nt",
        )
        == 'set "AGI_CLUSTER_ENABLED=0" && '
    )


def test_infer_repo_root_from_runtime_returns_none_for_short_path():
    assert (
        deployment_local_support._infer_repo_root_from_runtime("too-short.py") is None
    )


def test_infer_repo_root_from_runtime_returns_none_for_root_path():
    assert deployment_local_support._infer_repo_root_from_runtime("/") is None


def test_update_pyproject_dependencies_filters_to_worker_sources(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname='worker'\n", encoding="utf-8")

    worker_source = str(tmp_path / "worker" / "pyproject.toml")
    manager_source = str(tmp_path / "manager" / "pyproject.toml")
    dependency_info = {
        "scipy": {
            "name": "scipy",
            "extras": set(),
            "specifiers": [">=1.15.2,<1.17"],
            "sources": {worker_source},
        },
        "pip": {
            "name": "pip",
            "extras": set(),
            "specifiers": [">=24"],
            "sources": {manager_source},
        },
    }

    deployment_local_support._update_pyproject_dependencies(
        pyproject,
        dependency_info,
        worker_pyprojects={worker_source},
        pinned_versions={"scipy": "1.16.1", "pip": "24.0"},
        filter_to_worker=True,
    )

    content = pyproject.read_text(encoding="utf-8")
    assert "scipy==1.16.1" in content
    assert "pip==24.0" not in content


def test_update_pyproject_dependencies_skips_invalid_existing_specs(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "worker"
dependencies = ["numpy["]
""".strip(),
        encoding="utf-8",
    )

    worker_source = str(tmp_path / "worker" / "pyproject.toml")
    dependency_info = {
        "scipy": {
            "name": "scipy",
            "extras": set(),
            "specifiers": [">=1.15.2,<1.17"],
            "sources": {worker_source},
        },
    }

    deployment_local_support._update_pyproject_dependencies(
        pyproject,
        dependency_info,
        worker_pyprojects={worker_source},
        pinned_versions={"scipy": "1.16.1"},
        filter_to_worker=True,
    )

    content = pyproject.read_text(encoding="utf-8")
    assert 'dependencies = ["numpy[", "scipy==1.16.1"]' in content


def test_update_pyproject_dependencies_bootstraps_missing_file_and_pinned_extras(
    tmp_path,
):
    pyproject = tmp_path / "pyproject.toml"

    deployment_local_support._update_pyproject_dependencies(
        pyproject,
        {
            "pandas": {
                "name": "pandas",
                "extras": {"performance"},
                "specifiers": [">=2"],
                "sources": {"worker"},
            },
        },
        worker_pyprojects=set(),
        pinned_versions={"pandas": "2.2.3"},
    )

    content = pyproject.read_text(encoding="utf-8")
    assert 'dependencies = ["pandas[performance]==2.2.3"]' in content


def test_update_pyproject_dependencies_normalizes_non_array_dependencies(
    monkeypatch, tmp_path
):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname='worker'\n", encoding="utf-8")
    project_doc = tomlkit.document()
    project_tbl = tomlkit.table()
    project_tbl["dependencies"] = ("numpy>=1",)
    project_doc["project"] = project_tbl

    monkeypatch.setattr(
        deployment_local_support.tomlkit, "parse", lambda _text: project_doc
    )

    deployment_local_support._update_pyproject_dependencies(
        pyproject,
        {
            "scipy": {
                "name": "scipy",
                "extras": set(),
                "specifiers": [">=1.15"],
                "sources": {"worker"},
            },
        },
        worker_pyprojects=set(),
        pinned_versions=None,
    )

    content = pyproject.read_text(encoding="utf-8")
    assert 'dependencies = ["numpy>=1", "scipy>=1.15"]' in content


def test_update_pyproject_dependencies_normalizes_plain_sequence_dependencies(
    monkeypatch, tmp_path
):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname='worker'\n", encoding="utf-8")

    monkeypatch.setattr(
        deployment_local_support.tomlkit,
        "parse",
        lambda _text: {"project": {"dependencies": ("numpy>=1", "pandas>=2")}},
    )

    deployment_local_support._update_pyproject_dependencies(
        pyproject,
        {
            "scipy": {
                "name": "scipy",
                "extras": set(),
                "specifiers": [">=1.15"],
                "sources": {"worker"},
            },
        },
        worker_pyprojects=set(),
        pinned_versions=None,
    )

    content = pyproject.read_text(encoding="utf-8")
    assert 'dependencies = ["numpy>=1", "pandas>=2", "scipy>=1.15"]' in content


def test_update_pyproject_dependencies_propagates_unexpected_requirement_bug(
    monkeypatch, tmp_path
):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        "[project]\nname='worker'\ndependencies=['numpy>=1']\n", encoding="utf-8"
    )

    def _boom(_text):
        raise ValueError("unexpected requirement mapper bug")

    monkeypatch.setattr(deployment_local_support, "Requirement", _boom)

    with pytest.raises(ValueError, match="unexpected requirement mapper bug"):
        deployment_local_support._update_pyproject_dependencies(
            pyproject,
            dependency_info={},
            worker_pyprojects=set(),
            pinned_versions=None,
        )


def test_gather_dependency_specs_skips_agi_packages_and_keeps_exact_pins(tmp_path):
    first = tmp_path / "project_a"
    second = tmp_path / "project_b"
    first.mkdir(parents=True, exist_ok=True)
    second.mkdir(parents=True, exist_ok=True)
    (first / "pyproject.toml").write_text(
        """
[project]
name = "a"
dependencies = ["agi-env", "numpy>=1.0", "scipy>=1.0,<2"]
""".strip(),
        encoding="utf-8",
    )
    (second / "pyproject.toml").write_text(
        """
[project]
name = "b"
dependencies = ["scipy==1.16.1", "pandas[performance]>=2"]
""".strip(),
        encoding="utf-8",
    )

    dependency_info, worker_pyprojects = (
        deployment_local_support._gather_dependency_specs([first, second])
    )

    assert str((first / "pyproject.toml").resolve()) in worker_pyprojects
    assert str((second / "pyproject.toml").resolve()) in worker_pyprojects
    assert "agi-env" not in dependency_info
    assert dependency_info["numpy"]["specifiers"] == [">=1.0"]
    assert dependency_info["scipy"]["has_exact"] is True
    assert dependency_info["scipy"]["specifiers"] == ["==1.16.1"]
    assert dependency_info["pandas"]["extras"] == {"performance"}


def test_gather_dependency_specs_keeps_exact_pin_when_later_ranges_appear(tmp_path):
    exact = tmp_path / "exact"
    ranged = tmp_path / "ranged"
    exact.mkdir(parents=True, exist_ok=True)
    ranged.mkdir(parents=True, exist_ok=True)
    (exact / "pyproject.toml").write_text(
        """
[project]
name = "exact"
dependencies = ["scipy==1.16.1"]
""".strip(),
        encoding="utf-8",
    )
    (ranged / "pyproject.toml").write_text(
        """
[project]
name = "ranged"
dependencies = ["scipy>=1.15,<1.17"]
""".strip(),
        encoding="utf-8",
    )

    dependency_info, _worker_pyprojects = (
        deployment_local_support._gather_dependency_specs([exact, ranged])
    )

    assert dependency_info["scipy"]["has_exact"] is True
    assert dependency_info["scipy"]["specifiers"] == ["==1.16.1"]


def test_gather_dependency_specs_skips_invalid_pyproject_and_dependency_entries(
    tmp_path,
):
    good = tmp_path / "good"
    bad = tmp_path / "bad"
    weird = tmp_path / "weird"
    for path in (good, bad, weird):
        path.mkdir(parents=True, exist_ok=True)

    (good / "pyproject.toml").write_text(
        """
[project]
name = "good"
dependencies = ["numpy>=1.0"]
""".strip(),
        encoding="utf-8",
    )
    (bad / "pyproject.toml").write_text("[project\nname='broken'\n", encoding="utf-8")
    (weird / "pyproject.toml").write_text(
        """
[project]
name = "weird"
dependencies = ["numpy["]
""".strip(),
        encoding="utf-8",
    )

    dependency_info, worker_pyprojects = (
        deployment_local_support._gather_dependency_specs([good, bad, weird])
    )

    assert str((good / "pyproject.toml").resolve()) in worker_pyprojects
    assert str((bad / "pyproject.toml").resolve()) not in worker_pyprojects
    assert str((weird / "pyproject.toml").resolve()) in worker_pyprojects
    assert set(dependency_info) == {"numpy"}


def test_gather_dependency_specs_propagates_unexpected_parse_bug(monkeypatch, tmp_path):
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    (project / "pyproject.toml").write_text(
        "[project]\nname='demo'\n", encoding="utf-8"
    )

    def _boom(_text):
        raise ValueError("unexpected parse bug")

    monkeypatch.setattr(deployment_local_support.tomlkit, "parse", _boom)

    with pytest.raises(ValueError, match="unexpected parse bug"):
        deployment_local_support._gather_dependency_specs([project])


def test_gather_dependency_specs_skips_none_missing_duplicate_and_false_marker_entries(
    tmp_path,
):
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    (project / "pyproject.toml").write_text(
        """
[project]
name = "demo"
dependencies = ["numpy>=1.0", "scipy>=1.0; python_version < '2'"]
""".strip(),
        encoding="utf-8",
    )

    dependency_info, worker_pyprojects = (
        deployment_local_support._gather_dependency_specs(
            [None, project, tmp_path / "missing", project]
        )
    )

    assert worker_pyprojects == {str((project / "pyproject.toml").resolve())}
    assert set(dependency_info) == {"numpy"}


@pytest.mark.asyncio
async def test_deploy_local_worker_non_source_flow(tmp_path):
    app_path = tmp_path / "app"
    app_path.mkdir(parents=True, exist_ok=True)
    (app_path / "pyproject.toml").write_text(
        "[project]\nname='demo-app'\n", encoding="utf-8"
    )

    agi_env_root = tmp_path / "agi_env"
    (agi_env_root / "src" / "agi_env" / "resources").mkdir(parents=True, exist_ok=True)
    (agi_env_root / "src" / "agi_env" / "resources" / "sample.txt").write_text(
        "x", encoding="utf-8"
    )
    agi_node_root = tmp_path / "agi_node"
    agi_node_root.mkdir(parents=True, exist_ok=True)

    cluster_pck = tmp_path / "cluster_pck"
    (cluster_pck / "agi_distributor").mkdir(parents=True, exist_ok=True)
    (cluster_pck / "agi_distributor" / "cli.py").write_text(
        "print('cli')", encoding="utf-8"
    )

    wenv_abs = tmp_path / "worker_env"
    wenv_abs.mkdir(parents=True, exist_ok=True)
    (wenv_abs / "pyproject.toml").write_text(
        "[project]\nname='worker-app'\n", encoding="utf-8"
    )

    env = SimpleNamespace(
        is_source_env=False,
        is_worker_env=False,
        install_type=1,
        agi_env=agi_env_root,
        agi_node=agi_node_root,
        active_app=app_path,
        wenv_abs=wenv_abs,
        wenv_rel=Path("worker_env"),
        uv="uv",
        uv_worker="uv",
        python_version="3.13",
        pyvers_worker="3.13",
        envars={},
        verbose=1,
        env_pck=agi_env_root / "src" / "agi_env",
        dataset_archive=tmp_path / "missing.7z",
        target_worker="demo_worker",
        post_install_rel="demo.post_install",
        user=getpass.getuser(),
        cluster_pck=cluster_pck,
        logger=SimpleNamespace(warn=lambda *_a, **_k: None),
    )
    commands = []

    async def _fake_run(cmd, cwd):
        commands.append((cmd, str(cwd)))
        return ""

    async def _fake_build():
        return None

    async def _fake_uninstall():
        return None

    agi_cls = SimpleNamespace(
        env=env,
        _run_type="sync",
        _mode=0,
        DASK_MODE=4,
        _rapids_enabled=False,
        _install_done_local=False,
        _hardware_supports_rapids=lambda: False,
        _build_lib_local=_fake_build,
        _uninstall_modules=_fake_uninstall,
    )

    await _call_deploy_local_worker(
        agi_cls,
        app_path,
        Path("worker_env"),
        " --extra pandas-worker",
        agi_version_missing_on_pypi_fn=lambda _p: False,
        run_fn=_fake_run,
        set_env_var_fn=lambda *_a, **_k: None,
        log=mock.Mock(),
    )

    assert agi_cls._install_done_local is True
    assert any(" add agi-env" in cmd for cmd, _ in commands)
    assert any(" add agi-node" in cmd for cmd, _ in commands)
    assert any(
        "AGI_CLUSTER_ENABLED=0" in cmd and "demo.post_install" in cmd
        for cmd, _ in commands
    )
    assert any(
        f'"{app_path}"' in cmd and "demo.post_install" in cmd for cmd, _ in commands
    )
    assert any("threaded" in cmd for cmd, _ in commands)


@pytest.mark.asyncio
async def test_deploy_local_worker_reuses_cached_uv_stages(tmp_path):
    app_path = tmp_path / "app"
    app_path.mkdir(parents=True, exist_ok=True)
    (app_path / "pyproject.toml").write_text(
        "[project]\nname='demo-app'\n", encoding="utf-8"
    )
    _write_venv_python(app_path, python_version="3.13.13")

    agi_env_root = tmp_path / "agi_env"
    (agi_env_root / "src" / "agi_env" / "resources").mkdir(parents=True, exist_ok=True)
    (agi_env_root / "src" / "agi_env" / "resources" / "sample.txt").write_text(
        "x", encoding="utf-8"
    )
    agi_node_root = tmp_path / "agi_node"
    agi_node_root.mkdir(parents=True, exist_ok=True)

    cluster_pck = tmp_path / "cluster_pck"
    (cluster_pck / "agi_distributor").mkdir(parents=True, exist_ok=True)
    (cluster_pck / "agi_distributor" / "cli.py").write_text(
        "print('cli')", encoding="utf-8"
    )

    wenv_abs = tmp_path / "worker_env"
    wenv_abs.mkdir(parents=True, exist_ok=True)
    (wenv_abs / "pyproject.toml").write_text(
        "[project]\nname='worker-app'\n", encoding="utf-8"
    )
    _write_venv_python(wenv_abs, python_version="3.13.13")

    env = SimpleNamespace(
        is_source_env=False,
        is_worker_env=False,
        install_type=1,
        agi_env=agi_env_root,
        agi_node=agi_node_root,
        active_app=app_path,
        wenv_abs=wenv_abs,
        wenv_rel=Path("worker_env"),
        uv="uv",
        uv_worker="uv",
        python_version="3.13",
        pyvers_worker="3.13",
        envars={},
        verbose=1,
        env_pck=agi_env_root / "src" / "agi_env",
        dataset_archive=tmp_path / "missing.7z",
        target_worker="demo_worker",
        post_install_rel="demo.post_install",
        user=getpass.getuser(),
        cluster_pck=cluster_pck,
        logger=SimpleNamespace(warn=lambda *_a, **_k: None),
    )
    commands = []

    async def _fake_run(cmd, cwd):
        commands.append((cmd, str(cwd)))
        return ""

    async def _fake_build():
        return None

    async def _fake_uninstall():
        return None

    agi_cls = SimpleNamespace(
        env=env,
        _run_type="sync",
        _mode=0,
        DASK_MODE=4,
        _rapids_enabled=False,
        _install_done_local=False,
        _hardware_supports_rapids=lambda: False,
        _build_lib_local=_fake_build,
        _uninstall_modules=_fake_uninstall,
    )

    await _call_deploy_local_worker(
        agi_cls,
        app_path,
        Path("worker_env"),
        " --extra pandas-worker",
        agi_version_missing_on_pypi_fn=lambda _p: False,
        run_fn=_fake_run,
        set_env_var_fn=lambda *_a, **_k: None,
        log=mock.Mock(),
    )
    first_commands = list(commands)
    commands.clear()
    agi_cls._install_done_local = False

    await _call_deploy_local_worker(
        agi_cls,
        app_path,
        Path("worker_env"),
        " --extra pandas-worker",
        agi_version_missing_on_pypi_fn=lambda _p: False,
        run_fn=_fake_run,
        set_env_var_fn=lambda *_a, **_k: None,
        log=mock.Mock(),
    )

    assert (wenv_abs / ".agilab-stage-cache.json").exists()
    assert any(
        cmd.startswith("uv sync") and str(app_path) in cmd for cmd, _ in first_commands
    )
    assert any(
        cmd.startswith("uv sync") and str(wenv_abs) in cmd for cmd, _ in first_commands
    )
    assert any(" add agi-env" in cmd for cmd, _ in first_commands)
    assert not any(
        cmd.startswith("uv sync") and str(app_path) in cmd for cmd, _ in commands
    )
    assert not any(
        cmd.startswith("uv sync") and str(wenv_abs) in cmd for cmd, _ in commands
    )
    assert not any(
        " add agi-env" in cmd or " add agi-node" in cmd for cmd, _ in commands
    )
    assert any(
        "pip install --python" in cmd and str(app_path) in cmd for cmd, _ in commands
    )
    assert any("threaded" in cmd for cmd, _ in commands)


@pytest.mark.asyncio
async def test_deploy_local_worker_shared_worker_venv_uses_runtime_cache(tmp_path):
    app_path = tmp_path / "app"
    app_path.mkdir(parents=True, exist_ok=True)
    (app_path / "pyproject.toml").write_text(
        "[project]\nname='demo-app'\n", encoding="utf-8"
    )

    agi_env_root = tmp_path / "agi_env"
    (agi_env_root / "src" / "agi_env" / "resources").mkdir(parents=True, exist_ok=True)
    (agi_env_root / "src" / "agi_env" / "resources" / "sample.txt").write_text(
        "x", encoding="utf-8"
    )
    agi_node_root = tmp_path / "agi_node"
    agi_node_root.mkdir(parents=True, exist_ok=True)

    cluster_pck = tmp_path / "cluster_pck"
    (cluster_pck / "agi_distributor").mkdir(parents=True, exist_ok=True)
    (cluster_pck / "agi_distributor" / "cli.py").write_text(
        "print('cli')", encoding="utf-8"
    )

    wenv_abs = tmp_path / "worker_env"
    wenv_abs.mkdir(parents=True, exist_ok=True)
    (wenv_abs / "pyproject.toml").write_text(
        "[project]\nname='worker-app'\n", encoding="utf-8"
    )
    (wenv_abs / ".venv").mkdir()

    env = SimpleNamespace(
        is_source_env=False,
        is_worker_env=False,
        install_type=1,
        agi_env=agi_env_root,
        agi_node=agi_node_root,
        active_app=app_path,
        wenv_abs=wenv_abs,
        wenv_rel=Path("worker_env"),
        uv="uv",
        uv_worker="uv",
        python_version="3.13",
        pyvers_worker="3.13",
        envars={"AGILAB_SHARED_WORKER_VENV": "1"},
        verbose=1,
        env_pck=agi_env_root / "src" / "agi_env",
        dataset_archive=tmp_path / "missing.7z",
        target_worker="demo_worker",
        post_install_rel="demo.post_install",
        user=getpass.getuser(),
        cluster_pck=cluster_pck,
        logger=SimpleNamespace(warn=lambda *_a, **_k: None),
    )
    commands = []

    async def _fake_run(cmd, cwd):
        commands.append((cmd, str(cwd)))
        return ""

    async def _fake_build():
        return None

    async def _fake_uninstall():
        return None

    agi_cls = SimpleNamespace(
        env=env,
        _run_type="sync",
        _mode=0,
        DASK_MODE=4,
        _rapids_enabled=False,
        _install_done_local=False,
        _hardware_supports_rapids=lambda: False,
        _build_lib_local=_fake_build,
        _uninstall_modules=_fake_uninstall,
    )

    await _call_deploy_local_worker(
        agi_cls,
        app_path,
        Path("worker_env"),
        " --extra pandas-worker",
        agi_version_missing_on_pypi_fn=lambda _p: False,
        run_fn=_fake_run,
        set_env_var_fn=lambda *_a, **_k: None,
        log=mock.Mock(),
    )

    cache_root = wenv_abs.parent / ".runtime-cache"
    worker_commands = [cmd for cmd, cwd in commands if cwd == str(wenv_abs)]
    manager_commands = [cmd for cmd, cwd in commands if cwd == str(app_path)]

    assert not (wenv_abs / ".venv").exists()
    assert cache_root.exists()
    assert any(
        "UV_PROJECT_ENVIRONMENT=" in cmd and str(cache_root) in cmd
        for cmd in worker_commands
    )
    assert any(f'pip install --python "{cache_root}' in cmd for cmd in worker_commands)
    assert not any("UV_PROJECT_ENVIRONMENT=" in cmd for cmd in manager_commands)


@pytest.mark.asyncio
async def test_deploy_local_worker_rapids_reuses_cli_and_falls_back_from_localhost_ssh(
    tmp_path,
):
    app_path = tmp_path / "app"
    app_path.mkdir(parents=True, exist_ok=True)
    (app_path / "pyproject.toml").write_text(
        "[project]\nname='demo-app'\n", encoding="utf-8"
    )

    agi_env_root = tmp_path / "agi_env"
    (agi_env_root / "src" / "agi_env" / "resources").mkdir(parents=True, exist_ok=True)
    (agi_env_root / "src" / "agi_env" / "resources" / "sample.txt").write_text(
        "x", encoding="utf-8"
    )
    agi_node_root = tmp_path / "agi_node"
    agi_node_root.mkdir(parents=True, exist_ok=True)

    cluster_pck = tmp_path / "cluster_pck"
    (cluster_pck / "agi_distributor").mkdir(parents=True, exist_ok=True)
    (cluster_pck / "agi_distributor" / "cli.py").write_text(
        "print('cli')", encoding="utf-8"
    )

    wenv_abs = tmp_path / "worker_env"
    wenv_abs.mkdir(parents=True, exist_ok=True)
    (wenv_abs / "pyproject.toml").write_text(
        "[project]\nname='worker-app'\n", encoding="utf-8"
    )
    existing_cli = wenv_abs.parent / "cli.py"
    existing_cli.write_text("print('existing cli')", encoding="utf-8")

    env = SimpleNamespace(
        is_source_env=False,
        is_worker_env=False,
        install_type=1,
        agi_env=agi_env_root,
        agi_node=agi_node_root,
        active_app=app_path,
        wenv_abs=wenv_abs,
        wenv_rel=Path("worker_env"),
        uv="uv",
        uv_worker="uv",
        python_version="3.13",
        pyvers_worker="3.13",
        envars={},
        verbose=1,
        env_pck=agi_env_root / "src" / "agi_env",
        dataset_archive=tmp_path / "missing.7z",
        target_worker="demo_worker",
        post_install_rel="demo.post_install",
        user="another-user",
        cluster_pck=cluster_pck,
        logger=SimpleNamespace(warn=lambda *_a, **_k: None),
    )
    commands = []
    ssh_calls = []
    env_vars = []

    async def _fake_run(cmd, cwd):
        commands.append((cmd, str(cwd)))
        return ""

    async def _fake_build():
        return None

    async def _fake_uninstall():
        return None

    async def _fake_ssh(_ip, cmd):
        ssh_calls.append(cmd)
        raise ConnectionError("localhost ssh denied")

    agi_cls = SimpleNamespace(
        env=env,
        _run_type="sync --dev",
        _mode=4,
        DASK_MODE=4,
        _rapids_enabled=True,
        _install_done_local=False,
        _hardware_supports_rapids=lambda: True,
        _build_lib_local=_fake_build,
        _uninstall_modules=_fake_uninstall,
        exec_ssh=_fake_ssh,
    )

    await _call_deploy_local_worker(
        agi_cls,
        app_path,
        Path("worker_env"),
        " --extra pandas-worker",
        agi_version_missing_on_pypi_fn=lambda _p: False,
        run_fn=_fake_run,
        set_env_var_fn=lambda *args: env_vars.append(args),
        log=mock.Mock(),
    )

    assert agi_cls._install_done_local is True
    assert ("127.0.0.1", "hw_rapids_capable") in env_vars
    assert ssh_calls and any("demo.post_install" in cmd for cmd in ssh_calls)
    assert any("demo.post_install" in cmd for cmd, _ in commands)
    assert not any(
        "AGI_CLUSTER_ENABLED=0" in cmd and "demo.post_install" in cmd
        for cmd, _ in commands
    )
    assert any(
        "uv sync --config-file uv_config.toml --project" in cmd and str(app_path) in cmd
        for cmd, _ in commands
    )
    assert any(
        "uv sync --python 3.13 --config-file uv_config.toml --project" in cmd
        and str(wenv_abs) in cmd
        for cmd, _ in commands
    )
    wenv_token = wenv_abs.as_posix()
    assert any(
        f"--project {wenv_token}" in cmd and "add 'dask[distributed]'" in cmd
        for cmd, _ in commands
    )
    assert not any(
        "uv sync" in cmd and str(wenv_abs) in cmd and "--extra pandas-worker" in cmd
        for cmd, _ in commands
    )
    assert any(f'python "{existing_cli}" threaded' in cmd for cmd, _ in commands)


@pytest.mark.asyncio
async def test_deploy_local_worker_install_type_zero_non_source_covers_dependency_flow(
    tmp_path, monkeypatch
):
    repo_root = tmp_path / "repo" / "src" / "agilab"
    env_project = repo_root / "core" / "agi-env"
    node_project = repo_root / "core" / "agi-node"
    core_project = repo_root / "core" / "agi-core"
    cluster_project = repo_root / "core" / "agi-cluster"
    for project in (env_project, node_project, core_project, cluster_project):
        project.mkdir(parents=True, exist_ok=True)
        (project / "pyproject.toml").write_text(
            "[project]\nname='demo'\ndependencies=['pip>=1']\n",
            encoding="utf-8",
        )
    (env_project / "src" / "agi_env" / "resources").mkdir(parents=True, exist_ok=True)
    (env_project / "src" / "agi_env" / "resources" / "resource.txt").write_text(
        "x", encoding="utf-8"
    )

    app_path = tmp_path / "app"
    app_path.mkdir(parents=True, exist_ok=True)
    (app_path / "pyproject.toml").write_text(
        "[project]\nname='app'\n", encoding="utf-8"
    )
    (app_path / "src").mkdir(parents=True, exist_ok=True)
    (app_path / "src" / "Trajectory.7z").write_text("traj", encoding="utf-8")
    (app_path / ".venv").mkdir(parents=True, exist_ok=True)
    (app_path / "uv.lock").write_text("lock", encoding="utf-8")

    wenv_abs = tmp_path / "wenv"
    wenv_abs.mkdir(parents=True, exist_ok=True)
    (wenv_abs / "pyproject.toml").write_text(
        "[project]\nname='worker'\n", encoding="utf-8"
    )
    _write_venv_python(wenv_abs, python_version="3.13.13")
    (wenv_abs / "_uv_sources" / "ilp_worker").mkdir(parents=True, exist_ok=True)

    env_pck = tmp_path / "env_pck" / "agi_env"
    env_pck.mkdir(parents=True, exist_ok=True)
    (env_pck.parent / "__editable__.agi_env-demo.pth").write_text("x", encoding="utf-8")

    dataset_archive = tmp_path / "dataset.7z"
    dataset_archive.write_text("dataset", encoding="utf-8")
    share_root = tmp_path / "share"
    sat_path = share_root / "sat_trajectory" / "dataframe" / "Trajectory"
    sat_path.mkdir(parents=True, exist_ok=True)
    (sat_path / "a.csv").write_text("x", encoding="utf-8")
    (sat_path / "b.csv").write_text("y", encoding="utf-8")

    cluster_pck = tmp_path / "cluster_pck"
    (cluster_pck / "agi_distributor").mkdir(parents=True, exist_ok=True)
    (cluster_pck / "agi_distributor" / "cli.py").write_text(
        "print('cli')", encoding="utf-8"
    )

    env = SimpleNamespace(
        is_source_env=False,
        is_worker_env=False,
        install_type=0,
        agi_env=env_project,
        agi_node=node_project,
        agi_cluster=cluster_project,
        active_app=app_path,
        wenv_abs=wenv_abs,
        wenv_rel=Path("wenv"),
        uv="uv",
        uv_worker="uv",
        python_version="3.13",
        pyvers_worker="3.13",
        envars={},
        verbose=1,
        env_pck=env_pck,
        dataset_archive=dataset_archive,
        target_worker="demo_worker",
        post_install_rel="demo.post_install",
        user="another-user",
        cluster_pck=cluster_pck,
        share_root_path=lambda: share_root,
        logger=SimpleNamespace(warn=lambda *_a, **_k: None),
    )
    commands = []
    ssh_calls = []

    async def _fake_run(cmd, cwd):
        commands.append((cmd, str(cwd)))
        return ""

    async def _fake_build():
        return None

    async def _fake_uninstall():
        return None

    async def _fake_ssh(_ip, cmd):
        ssh_calls.append(cmd)
        raise ConnectionError("localhost ssh denied")

    monkeypatch.setattr(
        deployment_local_support.AgiEnv,
        "read_agilab_path",
        staticmethod(lambda: repo_root),
    )

    agi_cls = SimpleNamespace(
        env=env,
        _run_type="sync --dev",
        _rapids_enabled=True,
        _install_done_local=False,
        _hardware_supports_rapids=lambda: True,
        _build_lib_local=_fake_build,
        _uninstall_modules=_fake_uninstall,
        exec_ssh=_fake_ssh,
    )

    await _call_deploy_local_worker(
        agi_cls,
        app_path,
        Path("wenv"),
        " --extra pandas-worker",
        agi_version_missing_on_pypi_fn=lambda _p: True,
        run_fn=_fake_run,
        set_env_var_fn=lambda *_a, **_k: None,
        log=mock.Mock(),
    )

    manager_toml = (app_path / "pyproject.toml").read_text(encoding="utf-8")
    worker_toml = (wenv_abs / "pyproject.toml").read_text(encoding="utf-8")
    assert "pip" in manager_toml
    assert "pip==" not in worker_toml
    assert (wenv_abs / "src" / "demo_worker" / "dataset.7z").exists()
    assert (wenv_abs / "src" / "demo_worker" / "Trajectory.7z").exists() is False
    pth_path = (
        deployment_local_support._project_site_packages_dir(
            wenv_abs, python_version="3.13"
        )
        / "agilab_uv_sources.pth"
    )
    pth_content = pth_path.read_text(encoding="utf-8").strip()
    # Path depth differs between POSIX (.venv/lib/python3.13/site-packages) and
    # Windows (.venv/Lib/site-packages); compare against the actual depth.
    relative_levels = len(pth_path.parent.relative_to(wenv_abs).parts)
    expected_prefix = "../" * relative_levels + "_uv_sources"
    assert pth_content == expected_prefix
    assert agi_cls._install_done_local is True
    assert any(
        f'add --editable "{env_project}" "{node_project}"' in cmd
        and str(wenv_abs) in cmd
        for cmd, _ in commands
    )
    manager_python = _venv_python(app_path)
    assert any(
        f'pip install --python "{manager_python}" --upgrade "{cluster_project}"' in cmd
        for cmd, _ in commands
    )
    assert not any(
        f'--no-deps "{cluster_project}"' in cmd and str(app_path) in cwd
        for cmd, cwd in commands
    )
    assert not any("add agi-env" in cmd and str(wenv_abs) in cmd for cmd, _ in commands)
    assert any("config-file uv_config.toml" in cmd for cmd, _ in commands)
    assert any(
        "pip install --python" in cmd and str(wenv_abs / ".venv") in cmd
        for cmd, _ in commands
    )
    assert any("demo.post_install" in cmd for cmd in ssh_calls)


@pytest.mark.asyncio
async def test_deploy_local_worker_install_type_zero_non_source_uses_distribution_specs_for_non_project_paths(
    tmp_path,
    monkeypatch,
):
    app_path = tmp_path / "app"
    app_path.mkdir(parents=True, exist_ok=True)
    (app_path / "pyproject.toml").write_text(
        "[project]\nname='app'\n", encoding="utf-8"
    )
    (app_path / ".venv").mkdir(parents=True, exist_ok=True)
    (app_path / "uv.lock").write_text("lock", encoding="utf-8")

    wenv_abs = tmp_path / "wenv"
    wenv_abs.mkdir(parents=True, exist_ok=True)
    (wenv_abs / "pyproject.toml").write_text(
        "[project]\nname='worker'\n", encoding="utf-8"
    )
    (wenv_abs / ".venv").mkdir(parents=True, exist_ok=True)

    env_pck = tmp_path / "site-packages" / "agi_env"
    env_pck.mkdir(parents=True, exist_ok=True)
    (env_pck / "resources").mkdir(parents=True, exist_ok=True)

    node_pck = tmp_path / "site-packages" / "agi_node"
    node_pck.mkdir(parents=True, exist_ok=True)

    cluster_pck = tmp_path / "site-packages" / "agi_cluster"
    (cluster_pck / "agi_distributor").mkdir(parents=True, exist_ok=True)
    (cluster_pck / "agi_distributor" / "cli.py").write_text(
        "print('cli')", encoding="utf-8"
    )

    env = SimpleNamespace(
        is_source_env=False,
        is_worker_env=False,
        install_type=0,
        agi_env=tmp_path / "bad" / "agi_env",
        agi_node=tmp_path / "bad" / "agi_node",
        agi_cluster=tmp_path / "bad" / "agi_cluster",
        active_app=app_path,
        wenv_abs=wenv_abs,
        wenv_rel=Path("wenv"),
        uv="uv",
        uv_worker="uv",
        python_version="3.13",
        pyvers_worker="3.13",
        envars={},
        verbose=1,
        env_pck=env_pck,
        dataset_archive=tmp_path / "missing.7z",
        target_worker="demo_worker",
        post_install_rel="demo.post_install",
        user="another-user",
        cluster_pck=cluster_pck,
        share_root_path=lambda: tmp_path / "share",
        logger=SimpleNamespace(warn=lambda *_a, **_k: None),
    )
    commands = []

    async def _fake_run(cmd, cwd):
        commands.append((cmd, str(cwd)))
        return ""

    async def _fake_build():
        return None

    async def _fake_uninstall():
        return None

    async def _fake_ssh(_ip, _cmd):
        raise ConnectionError("localhost ssh denied")

    monkeypatch.setattr(
        deployment_local_support.AgiEnv, "read_agilab_path", staticmethod(lambda: None)
    )
    monkeypatch.setattr(
        deployment_local_support,
        "_infer_repo_root_from_runtime",
        lambda _runtime_file: None,
    )
    monkeypatch.setattr(
        deployment_local_support,
        "_resolve_distribution_install_spec",
        lambda package_name: f"{package_name} @ git+https://example.invalid/repo.git@main#subdirectory={package_name}",
    )

    agi_cls = SimpleNamespace(
        env=env,
        _run_type="sync",
        _rapids_enabled=False,
        _install_done_local=False,
        _hardware_supports_rapids=lambda: False,
        _build_lib_local=_fake_build,
        _uninstall_modules=_fake_uninstall,
        exec_ssh=_fake_ssh,
        _mode=0,
        DASK_MODE=4,
    )

    await _call_deploy_local_worker(
        agi_cls,
        app_path,
        Path("wenv"),
        "",
        agi_version_missing_on_pypi_fn=lambda _p: False,
        runtime_file="short.py",
        run_fn=_fake_run,
        set_env_var_fn=lambda *_a, **_k: None,
        log=mock.Mock(),
    )

    assert not any(f'"{tmp_path / "bad" / "agi_env"}"' in cmd for cmd, _ in commands)
    assert any(
        "agi-env @ git+https://example.invalid/repo.git@main#subdirectory=agi-env"
        in cmd
        for cmd, _ in commands
    )
    assert any(
        "agi-node @ git+https://example.invalid/repo.git@main#subdirectory=agi-node"
        in cmd
        for cmd, _ in commands
    )


@pytest.mark.asyncio
async def test_deploy_local_worker_preserves_existing_dependency_ranges(
    tmp_path, monkeypatch
):
    repo_root = tmp_path / "repo" / "src" / "agilab"
    env_project = repo_root / "core" / "agi-env"
    node_project = repo_root / "core" / "agi-node"
    core_project = repo_root / "core" / "agi-core"
    cluster_project = repo_root / "core" / "agi-cluster"
    for project in (env_project, node_project, core_project, cluster_project):
        project.mkdir(parents=True, exist_ok=True)
    (env_project / "src" / "agi_env" / "resources").mkdir(parents=True, exist_ok=True)
    (env_project / "src" / "agi_env" / "resources" / "resource.txt").write_text(
        "x", encoding="utf-8"
    )
    (env_project / "pyproject.toml").write_text(
        "[project]\nname='agi-env'\ndependencies=['pip>=1']\n", encoding="utf-8"
    )
    (node_project / "pyproject.toml").write_text(
        "[project]\nname='agi-node'\ndependencies=['scipy==1.16.1']\n",
        encoding="utf-8",
    )
    (core_project / "pyproject.toml").write_text(
        "[project]\nname='agi-core'\ndependencies=[]\n", encoding="utf-8"
    )
    (cluster_project / "pyproject.toml").write_text(
        "[project]\nname='agi-cluster'\ndependencies=['pip>=1']\n",
        encoding="utf-8",
    )

    app_path = tmp_path / "app"
    app_path.mkdir(parents=True, exist_ok=True)
    (app_path / "pyproject.toml").write_text(
        "[project]\nname='app'\ndependencies=['scipy>=1.15.2,<1.17']\n",
        encoding="utf-8",
    )
    (app_path / "src").mkdir(parents=True, exist_ok=True)
    (app_path / ".venv").mkdir(parents=True, exist_ok=True)
    (app_path / "uv.lock").write_text("lock", encoding="utf-8")

    wenv_abs = tmp_path / "wenv"
    wenv_abs.mkdir(parents=True, exist_ok=True)
    (wenv_abs / "pyproject.toml").write_text(
        "[project]\nname='worker'\n", encoding="utf-8"
    )
    (wenv_abs / ".venv").mkdir(parents=True, exist_ok=True)
    (wenv_abs / "_uv_sources" / "ilp_worker").mkdir(parents=True, exist_ok=True)

    env_pck = tmp_path / "env_pck" / "agi_env"
    env_pck.mkdir(parents=True, exist_ok=True)
    (env_pck.parent / "__editable__.agi_env-demo.pth").write_text("x", encoding="utf-8")

    cluster_pck = tmp_path / "cluster_pck"
    (cluster_pck / "agi_distributor").mkdir(parents=True, exist_ok=True)
    (cluster_pck / "agi_distributor" / "cli.py").write_text(
        "print('cli')", encoding="utf-8"
    )

    env = SimpleNamespace(
        is_source_env=False,
        is_worker_env=False,
        install_type=0,
        agi_env=env_project,
        agi_node=node_project,
        agi_cluster=cluster_project,
        active_app=app_path,
        wenv_abs=wenv_abs,
        wenv_rel=Path("wenv"),
        uv="uv",
        uv_worker="uv",
        python_version="3.13",
        pyvers_worker="3.13",
        envars={},
        verbose=1,
        env_pck=env_pck,
        dataset_archive=tmp_path / "dataset.7z",
        target_worker="demo_worker",
        post_install_rel="demo.post_install",
        user="another-user",
        cluster_pck=cluster_pck,
        share_root_path=lambda: tmp_path / "share",
        logger=SimpleNamespace(warn=lambda *_a, **_k: None),
    )
    commands = []

    async def _fake_run(cmd, cwd):
        commands.append((cmd, str(cwd)))
        return ""

    async def _fake_build():
        return None

    async def _fake_uninstall():
        return None

    async def _fake_ssh(_ip, _cmd):
        raise ConnectionError("localhost ssh denied")

    monkeypatch.setattr(
        deployment_local_support.AgiEnv,
        "read_agilab_path",
        staticmethod(lambda: repo_root),
    )

    agi_cls = SimpleNamespace(
        env=env,
        _run_type="sync --dev",
        _rapids_enabled=False,
        _install_done_local=False,
        _hardware_supports_rapids=lambda: False,
        _build_lib_local=_fake_build,
        _uninstall_modules=_fake_uninstall,
        exec_ssh=_fake_ssh,
    )

    await _call_deploy_local_worker(
        agi_cls,
        app_path,
        Path("wenv"),
        " --extra pandas-worker",
        agi_version_missing_on_pypi_fn=lambda _p: False,
        run_fn=_fake_run,
        set_env_var_fn=lambda *_a, **_k: None,
        log=mock.Mock(),
    )

    manager_toml = (app_path / "pyproject.toml").read_text(encoding="utf-8")
    assert "scipy>=1.15.2,<1.17" in manager_toml
    assert "scipy==1.16.1" not in manager_toml
    assert any(
        f'add --editable "{env_project}" "{node_project}"' in cmd
        and str(wenv_abs) in cmd
        for cmd, _ in commands
    )
    assert any("sync --project" in cmd for cmd, _ in commands)


@pytest.mark.asyncio
async def test_deploy_local_worker_infers_repo_root_to_avoid_rewriting_source_app(
    tmp_path, monkeypatch
):
    repo_root = tmp_path / "repo" / "src" / "agilab"
    env_project = repo_root / "core" / "agi-env"
    node_project = repo_root / "core" / "agi-node"
    core_project = repo_root / "core" / "agi-core"
    cluster_project = repo_root / "core" / "agi-cluster"
    for project in (env_project, node_project, core_project, cluster_project):
        project.mkdir(parents=True, exist_ok=True)
    (env_project / "src" / "agi_env" / "resources").mkdir(parents=True, exist_ok=True)
    (env_project / "src" / "agi_env" / "resources" / "resource.txt").write_text(
        "x", encoding="utf-8"
    )
    (env_project / "pyproject.toml").write_text(
        "[project]\nname='agi-env'\ndependencies=['pip>=1']\n", encoding="utf-8"
    )
    (node_project / "pyproject.toml").write_text(
        "[project]\nname='agi-node'\ndependencies=['scipy==1.16.1']\n",
        encoding="utf-8",
    )
    (core_project / "pyproject.toml").write_text(
        "[project]\nname='agi-core'\ndependencies=[]\n", encoding="utf-8"
    )
    (cluster_project / "pyproject.toml").write_text(
        "[project]\nname='agi-cluster'\ndependencies=['pip>=1']\n",
        encoding="utf-8",
    )

    fake_module_file = (
        repo_root
        / "core"
        / "agi-cluster"
        / "src"
        / "agi_cluster"
        / "agi_distributor"
        / "agi_distributor.py"
    )
    fake_module_file.parent.mkdir(parents=True, exist_ok=True)
    fake_module_file.write_text(
        "# fake module path for repo inference\n", encoding="utf-8"
    )

    app_path = repo_root / "apps" / "builtin" / "demo_project"
    app_path.mkdir(parents=True, exist_ok=True)
    (app_path / "pyproject.toml").write_text(
        "[project]\nname='demo-project'\ndependencies=['py7zr']\n",
        encoding="utf-8",
    )
    (app_path / "src").mkdir(parents=True, exist_ok=True)
    (app_path / ".venv").mkdir(parents=True, exist_ok=True)
    (app_path / "uv.lock").write_text("lock", encoding="utf-8")

    wenv_abs = tmp_path / "wenv"
    wenv_abs.mkdir(parents=True, exist_ok=True)
    (wenv_abs / "pyproject.toml").write_text(
        "[project]\nname='worker'\n", encoding="utf-8"
    )
    (wenv_abs / ".venv").mkdir(parents=True, exist_ok=True)
    (wenv_abs / "_uv_sources" / "ilp_worker").mkdir(parents=True, exist_ok=True)

    env_pck = tmp_path / "env_pck" / "agi_env"
    env_pck.mkdir(parents=True, exist_ok=True)
    (env_pck.parent / "__editable__.agi_env-demo.pth").write_text("x", encoding="utf-8")

    cluster_pck = tmp_path / "cluster_pck"
    (cluster_pck / "agi_distributor").mkdir(parents=True, exist_ok=True)
    (cluster_pck / "agi_distributor" / "cli.py").write_text(
        "print('cli')", encoding="utf-8"
    )

    env = SimpleNamespace(
        is_source_env=False,
        is_worker_env=False,
        install_type=0,
        agi_env=env_project,
        agi_node=node_project,
        agi_cluster=cluster_project,
        active_app=app_path,
        wenv_abs=wenv_abs,
        wenv_rel=Path("wenv"),
        uv="uv",
        uv_worker="uv",
        python_version="3.13",
        pyvers_worker="3.13",
        envars={},
        verbose=1,
        env_pck=env_pck,
        dataset_archive=tmp_path / "dataset.7z",
        target_worker="demo_worker",
        post_install_rel="demo.post_install",
        user="another-user",
        cluster_pck=cluster_pck,
        share_root_path=lambda: tmp_path / "share",
        logger=SimpleNamespace(warn=lambda *_a, **_k: None),
    )
    commands = []

    async def _fake_run(cmd, cwd):
        commands.append((cmd, str(cwd)))
        return ""

    async def _fake_build():
        return None

    async def _fake_uninstall():
        return None

    async def _fake_ssh(_ip, _cmd):
        raise ConnectionError("localhost ssh denied")

    monkeypatch.setattr(
        deployment_local_support.AgiEnv, "read_agilab_path", staticmethod(lambda: None)
    )

    agi_cls = SimpleNamespace(
        env=env,
        _run_type="sync --dev",
        _rapids_enabled=False,
        _install_done_local=False,
        _hardware_supports_rapids=lambda: False,
        _build_lib_local=_fake_build,
        _uninstall_modules=_fake_uninstall,
        exec_ssh=_fake_ssh,
    )

    await _call_deploy_local_worker(
        agi_cls,
        app_path,
        Path("wenv"),
        " --extra pandas-worker",
        agi_version_missing_on_pypi_fn=lambda _p: False,
        runtime_file=str(fake_module_file),
        run_fn=_fake_run,
        set_env_var_fn=lambda *_a, **_k: None,
        log=mock.Mock(),
    )

    manager_toml = (app_path / "pyproject.toml").read_text(encoding="utf-8")
    assert "py7zr" in manager_toml
    assert "pip>=1" not in manager_toml
    assert "scipy==1.16.1" not in manager_toml
    assert any(
        f'add --editable "{env_project}" "{node_project}"' in cmd
        and str(wenv_abs) in cmd
        for cmd, _ in commands
    )


@pytest.mark.asyncio
async def test_deploy_local_worker_source_env_branch(tmp_path, monkeypatch):
    monkeypatch.delenv("AGI_INTERNET_ON", raising=False)
    app_path = tmp_path / "app"
    app_path.mkdir(parents=True, exist_ok=True)
    (app_path / "pyproject.toml").write_text(
        "[project]\nname='app'\n", encoding="utf-8"
    )
    wenv_abs = tmp_path / "wenv"
    wenv_abs.mkdir(parents=True, exist_ok=True)
    (wenv_abs / "pyproject.toml").write_text(
        "[project]\nname='worker'\n", encoding="utf-8"
    )
    agi_env = tmp_path / "agi_env"
    agi_node = tmp_path / "agi_node"
    agi_cluster = tmp_path / "agi_cluster"
    for project in (agi_env, agi_node, agi_cluster):
        project.mkdir(parents=True, exist_ok=True)
        (project / "pyproject.toml").write_text(
            f"[project]\nname='{project.name.replace('_', '-')}'\nversion='0.0.1'\n",
            encoding="utf-8",
        )
        (project / "dist").mkdir(parents=True, exist_ok=True)
    (agi_env / "dist" / "agi_env-0.0.1-py3-none-any.whl").write_text(
        "whl", encoding="utf-8"
    )
    old_node_whl = agi_node / "dist" / "agi_node-0.0.1-py3-none-any.whl"
    new_node_whl = agi_node / "dist" / "agi_node-0.0.2-py3-none-any.whl"
    old_node_whl.write_text("old-whl", encoding="utf-8")
    new_node_whl.write_text("new-whl", encoding="utf-8")
    os.utime(old_node_whl, (1, 1))
    os.utime(new_node_whl, (2, 2))
    cluster_pck = tmp_path / "cluster_pck"
    (cluster_pck / "agi_distributor").mkdir(parents=True, exist_ok=True)
    (cluster_pck / "agi_distributor" / "cli.py").write_text(
        "print('cli')", encoding="utf-8"
    )

    env = SimpleNamespace(
        is_source_env=True,
        is_worker_env=False,
        install_type=1,
        agi_env=agi_env,
        agi_node=agi_node,
        agi_cluster=agi_cluster,
        active_app=app_path,
        wenv_abs=wenv_abs,
        wenv_rel=Path("wenv"),
        uv="uv",
        uv_worker="uv",
        python_version="3.13",
        pyvers_worker="3.13",
        envars={"AGI_INTERNET_ON": "0"},
        verbose=1,
        env_pck=tmp_path / "env_pck",
        dataset_archive=tmp_path / "missing.7z",
        target_worker="demo_worker",
        post_install_rel="demo.post_install",
        user=getpass.getuser(),
        cluster_pck=cluster_pck,
        share_root_path=lambda: tmp_path / "share",
        logger=SimpleNamespace(warn=lambda *_a, **_k: None),
    )
    commands = []

    async def _fake_run(cmd, cwd):
        commands.append((cmd, str(cwd)))
        return ""

    async def _fake_build():
        return None

    async def _fake_uninstall():
        return None

    agi_cls = SimpleNamespace(
        env=env,
        _run_type="sync",
        _rapids_enabled=False,
        _install_done_local=False,
        _hardware_supports_rapids=lambda: False,
        _build_lib_local=_fake_build,
        _uninstall_modules=_fake_uninstall,
    )

    await _call_deploy_local_worker(
        agi_cls,
        app_path,
        Path("wenv"),
        " --extra pandas-worker",
        agi_version_missing_on_pypi_fn=lambda _p: False,
        run_fn=_fake_run,
        set_env_var_fn=lambda *_a, **_k: None,
        log=mock.Mock(),
    )

    assert agi_cls._install_done_local is True
    assert any(
        "uv --offline sync" in cmd and str(app_path) in cmd for cmd, _ in commands
    )
    assert any(
        (
            f'uv --offline pip install --python "{_venv_python(app_path)}" '
            f'--upgrade --no-deps -e "{agi_env}" -e "{agi_node}" '
            f'-e "{agi_cluster}" -e "{app_path}"'
        )
        in cmd
        for cmd, _ in commands
    )
    assert any(
        f'uv --offline --project "{agi_env}" build --wheel' in cmd
        for cmd, _ in commands
    )
    assert any(
        f'uv --offline --project "{agi_node}" build --wheel' in cmd
        for cmd, _ in commands
    )
    assert any(
        f'uv --offline --project {wenv_abs} add --editable "{agi_env}" "{agi_node}"'
        in cmd
        for cmd, _ in commands
    )
    worker_python = _venv_python(wenv_abs)
    assert any(
        f'uv --offline venv --allow-existing --python 3.13 "{wenv_abs / ".venv"}"'
        in cmd
        for cmd, _ in commands
    )
    assert any(
        (
            f'uv --offline pip install --python "{worker_python}" --upgrade --no-deps '
            f'-e "{agi_env}" -e "{agi_node}" -e "{app_path}"'
        )
        in cmd
        for cmd, _ in commands
    )
    assert not any(f'pip install --project "{wenv_abs}"' in cmd for cmd, _ in commands)
    assert (wenv_abs / "agi_node-0.0.2-py3-none-any.whl").exists()
    assert not (wenv_abs / "agi_node-0.0.1-py3-none-any.whl").exists()


@pytest.mark.asyncio
async def test_deploy_local_worker_source_env_offline_manager_overlay_for_external_app(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("AGI_INTERNET_ON", raising=False)
    repo_root = tmp_path / "repo" / "src" / "agilab"
    (repo_root / "apps").mkdir(parents=True, exist_ok=True)
    env_project = repo_root / "core" / "agi-env"
    node_project = repo_root / "core" / "agi-node"
    cluster_project = repo_root / "core" / "agi-cluster"
    for project, name in (
        (env_project, "agi-env"),
        (node_project, "agi-node"),
        (cluster_project, "agi-cluster"),
    ):
        project.mkdir(parents=True, exist_ok=True)
        (project / "pyproject.toml").write_text(
            f"[project]\nname='{name}'\n", encoding="utf-8"
        )
        (project / "dist").mkdir(parents=True, exist_ok=True)
    (env_project / "dist" / "agi_env-0.0.1-py3-none-any.whl").write_text(
        "whl", encoding="utf-8"
    )
    (node_project / "dist" / "agi_node-0.0.1-py3-none-any.whl").write_text(
        "whl", encoding="utf-8"
    )

    fake_module_file = (
        repo_root
        / "core"
        / "agi-cluster"
        / "src"
        / "agi_cluster"
        / "agi_distributor"
        / "agi_distributor.py"
    )
    fake_module_file.parent.mkdir(parents=True, exist_ok=True)
    fake_module_file.write_text(
        "# fake module path for repo inference\n", encoding="utf-8"
    )

    external_apps_root = tmp_path / "external_apps"
    app_path = external_apps_root / "sb3_trainer_project"
    sat_project = external_apps_root / "sat_trajectory_project"
    app_path.mkdir(parents=True, exist_ok=True)
    sat_project.mkdir(parents=True, exist_ok=True)
    (sat_project / "pyproject.toml").write_text(
        "[project]\nname='sat-trajectory-project'\n", encoding="utf-8"
    )
    (app_path / "pyproject.toml").write_text(
        """
[project]
name = "sb3_trainer_project"
dependencies = ["agi-env", "agi-node", "sat-trajectory-project", "numpy>=1.26"]

[tool.uv.sources.sb3_trainer_project]
workspace = true

[tool.uv.sources."sat-trajectory-project"]
path = "../sat_trajectory_project"
""",
        encoding="utf-8",
    )
    (app_path / "src").mkdir(parents=True, exist_ok=True)
    (app_path / ".venv").mkdir(parents=True, exist_ok=True)
    (app_path / "uv.lock").write_text("lock", encoding="utf-8")

    wenv_abs = tmp_path / "wenv"
    wenv_abs.mkdir(parents=True, exist_ok=True)
    (wenv_abs / "pyproject.toml").write_text(
        "[project]\nname='worker'\n", encoding="utf-8"
    )
    (wenv_abs / ".venv").mkdir(parents=True, exist_ok=True)
    (wenv_abs / "_uv_sources" / "demo_worker").mkdir(parents=True, exist_ok=True)

    cluster_pck = tmp_path / "cluster_pck"
    (cluster_pck / "agi_distributor").mkdir(parents=True, exist_ok=True)
    (cluster_pck / "agi_distributor" / "cli.py").write_text(
        "print('cli')", encoding="utf-8"
    )

    env = SimpleNamespace(
        is_source_env=True,
        is_worker_env=False,
        install_type=1,
        agi_env=env_project,
        agi_node=node_project,
        agi_cluster=cluster_project,
        active_app=app_path,
        wenv_abs=wenv_abs,
        wenv_rel=Path("wenv"),
        uv="uv",
        uv_worker="uv",
        python_version="3.13",
        pyvers_worker="3.13",
        envars={"AGI_INTERNET_ON": "0"},
        verbose=1,
        env_pck=tmp_path / "env_pck",
        dataset_archive=tmp_path / "missing.7z",
        target_worker="demo_worker",
        post_install_rel="demo.post_install",
        user=getpass.getuser(),
        cluster_pck=cluster_pck,
        share_root_path=lambda: tmp_path / "share",
        logger=SimpleNamespace(warn=lambda *_a, **_k: None),
    )
    commands = []

    async def _fake_run(cmd, cwd):
        commands.append((cmd, str(cwd)))
        return ""

    async def _fake_build():
        return None

    async def _fake_uninstall():
        return None

    staged_overlay_root = tmp_path / "manager-sync-overlay-source"

    class _FakeTemporaryDirectory:
        def __init__(self, *args, **kwargs):
            del args, kwargs

        def __enter__(self):
            staged_overlay_root.mkdir(parents=True, exist_ok=True)
            return str(staged_overlay_root)

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        deployment_local_support.AgiEnv, "read_agilab_path", staticmethod(lambda: None)
    )
    monkeypatch.setattr(
        deployment_local_support, "TemporaryDirectory", _FakeTemporaryDirectory
    )

    agi_cls = SimpleNamespace(
        env=env,
        _run_type="sync --dev",
        _rapids_enabled=False,
        _install_done_local=False,
        _hardware_supports_rapids=lambda: False,
        _build_lib_local=_fake_build,
        _uninstall_modules=_fake_uninstall,
    )

    await _call_deploy_local_worker(
        agi_cls,
        app_path,
        Path("wenv"),
        " --extra pandas-worker",
        agi_version_missing_on_pypi_fn=lambda _p: False,
        runtime_file=str(fake_module_file),
        run_fn=_fake_run,
        set_env_var_fn=lambda *_a, **_k: None,
        log=mock.Mock(),
    )

    overlay_doc = tomlkit.parse(
        (staged_overlay_root / "pyproject.toml").read_text(encoding="utf-8")
    )
    overlay_sources = overlay_doc["tool"]["uv"]["sources"]
    # The overlay stores POSIX separators (uv requires them on every platform).
    assert (
        str(overlay_sources["agi-env"]["path"])
        == env_project.resolve(strict=False).as_posix()
    )
    assert (
        str(overlay_sources["agi-node"]["path"])
        == node_project.resolve(strict=False).as_posix()
    )
    assert (
        str(overlay_sources["sat-trajectory-project"]["path"])
        == sat_project.resolve(strict=False).as_posix()
    )
    assert "sb3_trainer_project" not in overlay_sources
    assert any(
        "--project" in cmd
        and "--active --no-install-project" in cmd
        and str(staged_overlay_root) in cmd
        for cmd, _ in commands
    )
    assert any(
        (
            f'uv --offline pip install --python "{_venv_python(wenv_abs)}" '
            f'--upgrade --no-deps -e "{env_project}" -e "{node_project}" '
            f'-e "{app_path}"'
        )
        in cmd
        for cmd, _ in commands
    )


@pytest.mark.asyncio
async def test_deploy_local_worker_offline_manager_overlay_preserves_local_sources(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("AGI_INTERNET_ON", raising=False)
    repo_root = tmp_path / "repo" / "src" / "agilab"
    (repo_root / "apps").mkdir(parents=True, exist_ok=True)
    env_project = repo_root / "core" / "agi-env"
    node_project = repo_root / "core" / "agi-node"
    core_project = repo_root / "core" / "agi-core"
    cluster_project = repo_root / "core" / "agi-cluster"
    for project, name in (
        (env_project, "agi-env"),
        (node_project, "agi-node"),
        (core_project, "agi-core"),
        (cluster_project, "agi-cluster"),
    ):
        project.mkdir(parents=True, exist_ok=True)
        (project / "pyproject.toml").write_text(
            f"[project]\nname='{name}'\n", encoding="utf-8"
        )
    (env_project / "src" / "agi_env" / "resources").mkdir(parents=True, exist_ok=True)
    (env_project / "src" / "agi_env" / "resources" / "resource.txt").write_text(
        "x", encoding="utf-8"
    )

    fake_module_file = (
        repo_root
        / "core"
        / "agi-cluster"
        / "src"
        / "agi_cluster"
        / "agi_distributor"
        / "agi_distributor.py"
    )
    fake_module_file.parent.mkdir(parents=True, exist_ok=True)
    fake_module_file.write_text(
        "# fake module path for repo inference\n", encoding="utf-8"
    )

    external_apps_root = tmp_path / "external_apps"
    app_path = external_apps_root / "sb3_trainer_project"
    sat_project = external_apps_root / "sat_trajectory_project"
    app_path.mkdir(parents=True, exist_ok=True)
    sat_project.mkdir(parents=True, exist_ok=True)
    (sat_project / "pyproject.toml").write_text(
        "[project]\nname='sat-trajectory-project'\n", encoding="utf-8"
    )
    (app_path / "pyproject.toml").write_text(
        """
[project]
name = "sb3_trainer_project"
dependencies = ["agi-env", "agi-node", "sat-trajectory-project", "numpy>=1.26"]

[tool.uv.sources.sb3_trainer_project]
workspace = true

[tool.uv.sources."sat-trajectory-project"]
path = "../sat_trajectory_project"
""",
        encoding="utf-8",
    )
    (app_path / "src").mkdir(parents=True, exist_ok=True)
    (app_path / ".venv").mkdir(parents=True, exist_ok=True)
    (app_path / "uv.lock").write_text("lock", encoding="utf-8")

    wenv_abs = tmp_path / "wenv"
    wenv_abs.mkdir(parents=True, exist_ok=True)
    (wenv_abs / "pyproject.toml").write_text(
        "[project]\nname='worker'\n", encoding="utf-8"
    )
    (wenv_abs / ".venv").mkdir(parents=True, exist_ok=True)
    (wenv_abs / "_uv_sources" / "demo_worker").mkdir(parents=True, exist_ok=True)

    env_pck = tmp_path / "env_pck" / "agi_env"
    env_pck.mkdir(parents=True, exist_ok=True)
    cluster_pck = tmp_path / "cluster_pck"
    (cluster_pck / "agi_distributor").mkdir(parents=True, exist_ok=True)
    (cluster_pck / "agi_distributor" / "cli.py").write_text(
        "print('cli')", encoding="utf-8"
    )

    env = SimpleNamespace(
        is_source_env=False,
        is_worker_env=False,
        install_type=0,
        agi_env=env_project,
        agi_node=node_project,
        agi_cluster=cluster_project,
        active_app=app_path,
        wenv_abs=wenv_abs,
        wenv_rel=Path("wenv"),
        uv="uv",
        uv_worker="uv",
        python_version="3.13",
        pyvers_worker="3.13",
        envars={"AGI_INTERNET_ON": "0"},
        verbose=1,
        env_pck=env_pck,
        dataset_archive=tmp_path / "missing.7z",
        target_worker="demo_worker",
        post_install_rel="demo.post_install",
        user=getpass.getuser(),
        cluster_pck=cluster_pck,
        share_root_path=lambda: tmp_path / "share",
        logger=SimpleNamespace(warn=lambda *_a, **_k: None),
    )
    commands = []

    async def _fake_run(cmd, cwd):
        commands.append((cmd, str(cwd)))
        return ""

    async def _fake_build():
        return None

    async def _fake_uninstall():
        return None

    staged_overlay_root = tmp_path / "manager-sync-overlay"

    class _FakeTemporaryDirectory:
        def __init__(self, *args, **kwargs):
            del args, kwargs

        def __enter__(self):
            staged_overlay_root.mkdir(parents=True, exist_ok=True)
            return str(staged_overlay_root)

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        deployment_local_support.AgiEnv, "read_agilab_path", staticmethod(lambda: None)
    )
    monkeypatch.setattr(
        deployment_local_support, "TemporaryDirectory", _FakeTemporaryDirectory
    )

    agi_cls = SimpleNamespace(
        env=env,
        _run_type="sync --dev",
        _rapids_enabled=False,
        _install_done_local=False,
        _hardware_supports_rapids=lambda: False,
        _build_lib_local=_fake_build,
        _uninstall_modules=_fake_uninstall,
    )

    await _call_deploy_local_worker(
        agi_cls,
        app_path,
        Path("wenv"),
        " --extra pandas-worker",
        agi_version_missing_on_pypi_fn=lambda _p: False,
        runtime_file=str(fake_module_file),
        run_fn=_fake_run,
        set_env_var_fn=lambda *_a, **_k: None,
        log=mock.Mock(),
    )

    overlay_doc = tomlkit.parse(
        (staged_overlay_root / "pyproject.toml").read_text(encoding="utf-8")
    )
    overlay_sources = overlay_doc["tool"]["uv"]["sources"]
    # The overlay stores POSIX separators (uv requires them on every platform).
    assert (
        str(overlay_sources["agi-env"]["path"])
        == env_project.resolve(strict=False).as_posix()
    )
    assert (
        str(overlay_sources["agi-node"]["path"])
        == node_project.resolve(strict=False).as_posix()
    )
    assert (
        str(overlay_sources["sat-trajectory-project"]["path"])
        == sat_project.resolve(strict=False).as_posix()
    )
    assert "sb3_trainer_project" not in overlay_sources
    assert any(
        "sync --project" in cmd
        and "--active --no-install-project" in cmd
        and str(staged_overlay_root) in cmd
        for cmd, _ in commands
    )
    manager_python = _venv_python(app_path)
    expected_manager_installs = [
        f'pip install --python "{manager_python}" --upgrade --no-deps -e "{app_path}"',
        f'pip install --python "{manager_python}" --upgrade "{env_project}"',
        f'pip install --python "{manager_python}" --upgrade "{node_project}"',
        f'pip install --python "{manager_python}" --upgrade --no-deps "{core_project}"',
        f'pip install --python "{manager_python}" --upgrade "{cluster_project}"',
    ]
    for expected in expected_manager_installs:
        assert any(expected in cmd for cmd, _ in commands), "\n".join(
            cmd for cmd, _ in commands
        )
    assert any(
        f'add --editable "{env_project}" "{node_project}"' in cmd
        and str(wenv_abs) in cmd
        for cmd, _ in commands
    )


@pytest.mark.asyncio
async def test_deploy_local_worker_install_type_zero_uses_resource_fallbacks_and_free_threaded_python(
    tmp_path, monkeypatch
):
    repo_root = tmp_path / "repo" / "src" / "agilab"
    env_project = repo_root / "core" / "agi-env"
    node_project = repo_root / "core" / "agi-node"
    core_project = repo_root / "core" / "agi-core"
    cluster_project = repo_root / "core" / "agi-cluster"
    for project in (env_project, node_project, core_project, cluster_project):
        project.mkdir(parents=True, exist_ok=True)
    (env_project / "pyproject.toml").write_text(
        "[project]\nname='agi-env'\ndependencies=['pip>=1']\n", encoding="utf-8"
    )
    (node_project / "pyproject.toml").write_text(
        "[project]\nname='agi-node'\ndependencies=['scipy>=1']\n", encoding="utf-8"
    )
    (core_project / "pyproject.toml").write_text(
        "[project]\nname='agi-core'\ndependencies=[]\n", encoding="utf-8"
    )
    (cluster_project / "pyproject.toml").write_text(
        "[project]\nname='agi-cluster'\ndependencies=[]\n", encoding="utf-8"
    )

    app_path = tmp_path / "app"
    app_path.mkdir(parents=True, exist_ok=True)
    (app_path / "pyproject.toml").write_text(
        "[project]\nname='app'\n", encoding="utf-8"
    )
    (app_path / ".venv").mkdir(parents=True, exist_ok=True)
    (app_path / "uv.lock").write_text("lock", encoding="utf-8")
    legacy_manager_resources = app_path / "agilab/core/agi-env/src/agi_env/resources"
    legacy_manager_resources.mkdir(parents=True, exist_ok=True)
    (legacy_manager_resources / "old.txt").write_text("old", encoding="utf-8")
    manager_resources = (
        deployment_local_support._project_site_packages_dir(
            app_path, python_version="3.13"
        )
        / "agi_env"
        / "resources"
    )
    manager_resources.mkdir(parents=True, exist_ok=True)
    (manager_resources / "old.txt").write_text("old", encoding="utf-8")

    wenv_abs = tmp_path / "wenv"
    wenv_abs.mkdir(parents=True, exist_ok=True)
    (wenv_abs / "pyproject.toml").write_text(
        "[project]\nname='worker'\n", encoding="utf-8"
    )
    deployment_local_support._project_site_packages_dir(
        wenv_abs, python_version="3.13t"
    ).mkdir(parents=True, exist_ok=True)
    _write_venv_python(wenv_abs, python_version="3.13.13")
    (wenv_abs / "_uv_sources").mkdir(parents=True, exist_ok=True)
    resources_dest = wenv_abs / "agilab/core/agi-env/src/agi_env/resources"
    resources_dest.mkdir(parents=True, exist_ok=True)
    (resources_dest / "old.txt").write_text("old", encoding="utf-8")

    env_pck = tmp_path / "env_pck" / "agi_env"
    (env_pck / "resources").mkdir(parents=True, exist_ok=True)
    (env_pck / "resources" / "resource.txt").write_text("resource", encoding="utf-8")
    (env_pck.parent / "__editable__.agi_env-demo.pth").write_text("x", encoding="utf-8")

    cluster_pck = tmp_path / "cluster_pck"
    (cluster_pck / "agi_distributor").mkdir(parents=True, exist_ok=True)
    (cluster_pck / "agi_distributor" / "cli.py").write_text(
        "print('cli')", encoding="utf-8"
    )

    env = SimpleNamespace(
        is_source_env=False,
        is_worker_env=False,
        install_type=0,
        agi_env=env_project,
        agi_node=node_project,
        agi_cluster=cluster_project,
        active_app=app_path,
        wenv_abs=wenv_abs,
        wenv_rel=Path("wenv"),
        uv="uv",
        uv_worker="uv",
        python_version="3.13",
        pyvers_worker="3.13t",
        envars={},
        verbose=1,
        env_pck=env_pck,
        dataset_archive=tmp_path / "missing.7z",
        target_worker="demo_worker",
        post_install_rel="demo.post_install",
        user=getpass.getuser(),
        cluster_pck=cluster_pck,
        share_root_path=lambda: tmp_path / "share",
        logger=SimpleNamespace(warn=lambda *_a, **_k: None),
    )
    commands = []
    log = mock.Mock()

    async def _fake_run(cmd, cwd):
        commands.append((cmd, str(cwd)))
        return ""

    async def _fake_build():
        return None

    async def _fake_uninstall():
        return None

    monkeypatch.setattr(
        deployment_local_support.AgiEnv,
        "read_agilab_path",
        staticmethod(lambda: repo_root),
    )
    monkeypatch.setattr(
        deployment_local_support,
        "pkg_version",
        lambda name: (_ for _ in ()).throw(
            deployment_local_support.PackageNotFoundError(name)
        )
        if name == "scipy"
        else "1.0",
    )

    agi_cls = SimpleNamespace(
        env=env,
        _run_type="sync",
        _rapids_enabled=False,
        _install_done_local=False,
        _hardware_supports_rapids=lambda: False,
        _build_lib_local=_fake_build,
        _uninstall_modules=_fake_uninstall,
    )

    await _call_deploy_local_worker(
        agi_cls,
        app_path,
        Path("wenv"),
        "",
        agi_version_missing_on_pypi_fn=lambda _p: False,
        run_fn=_fake_run,
        set_env_var_fn=lambda *_a, **_k: None,
        log=log,
    )

    assert (manager_resources / "resource.txt").exists()
    assert not (legacy_manager_resources / "old.txt").exists()
    assert not (app_path / "agilab").exists()
    assert (resources_dest / "resource.txt").exists()
    assert (
        deployment_local_support._project_site_packages_dir(
            wenv_abs, python_version="3.13t"
        )
        / "agilab_uv_sources.pth"
    ).exists()
    log.debug.assert_called()


@pytest.mark.asyncio
async def test_deploy_local_worker_source_env_missing_agi_env_wheel_raises(tmp_path):
    app_path = tmp_path / "app"
    app_path.mkdir(parents=True, exist_ok=True)
    (app_path / "pyproject.toml").write_text(
        "[project]\nname='app'\n", encoding="utf-8"
    )
    wenv_abs = tmp_path / "wenv"
    wenv_abs.mkdir(parents=True, exist_ok=True)
    (wenv_abs / "pyproject.toml").write_text(
        "[project]\nname='worker'\n", encoding="utf-8"
    )
    agi_env = tmp_path / "agi_env"
    agi_node = tmp_path / "agi_node"
    agi_cluster = tmp_path / "agi_cluster"
    for project in (agi_env, agi_node, agi_cluster):
        (project / "dist").mkdir(parents=True, exist_ok=True)
    (agi_node / "dist" / "agi_node-0.0.1-py3-none-any.whl").write_text(
        "whl", encoding="utf-8"
    )

    env = SimpleNamespace(
        is_source_env=True,
        is_worker_env=False,
        install_type=1,
        agi_env=agi_env,
        agi_node=agi_node,
        agi_cluster=agi_cluster,
        active_app=app_path,
        wenv_abs=wenv_abs,
        wenv_rel=Path("wenv"),
        uv="uv",
        uv_worker="uv",
        python_version="3.13",
        pyvers_worker="3.13",
        envars={},
        verbose=0,
        env_pck=tmp_path / "env_pck",
        dataset_archive=tmp_path / "missing.7z",
        target_worker="demo_worker",
        post_install_rel="demo.post_install",
        user=getpass.getuser(),
        cluster_pck=tmp_path / "cluster_pck",
        share_root_path=lambda: tmp_path / "share",
        logger=SimpleNamespace(warn=lambda *_a, **_k: None),
    )

    agi_cls = SimpleNamespace(
        env=env,
        _run_type="sync",
        _rapids_enabled=False,
        _install_done_local=False,
        _hardware_supports_rapids=lambda: False,
        _build_lib_local=lambda: None,
        _uninstall_modules=lambda: None,
    )

    async def _fake_build():
        return None

    async def _fake_uninstall():
        return None

    agi_cls._build_lib_local = _fake_build
    agi_cls._uninstall_modules = _fake_uninstall

    async def _fake_run(*_args, **_kwargs):
        return ""

    with pytest.raises(RuntimeError, match="build --wheel"):
        await _call_deploy_local_worker(
            agi_cls,
            app_path,
            Path("wenv"),
            "",
            agi_version_missing_on_pypi_fn=lambda _p: False,
            run_fn=_fake_run,
            set_env_var_fn=lambda *_a, **_k: None,
            log=mock.Mock(),
        )


@pytest.mark.asyncio
async def test_deploy_local_worker_source_env_missing_agi_node_wheel_raises(tmp_path):
    app_path = tmp_path / "app"
    app_path.mkdir(parents=True, exist_ok=True)
    (app_path / "pyproject.toml").write_text(
        "[project]\nname='app'\n", encoding="utf-8"
    )
    wenv_abs = tmp_path / "wenv"
    wenv_abs.mkdir(parents=True, exist_ok=True)
    (wenv_abs / "pyproject.toml").write_text(
        "[project]\nname='worker'\n", encoding="utf-8"
    )
    agi_env = tmp_path / "agi_env"
    agi_node = tmp_path / "agi_node"
    agi_cluster = tmp_path / "agi_cluster"
    for project in (agi_env, agi_node, agi_cluster):
        (project / "dist").mkdir(parents=True, exist_ok=True)
    (agi_env / "dist" / "agi_env-0.0.1-py3-none-any.whl").write_text(
        "whl", encoding="utf-8"
    )

    env = SimpleNamespace(
        is_source_env=True,
        is_worker_env=False,
        install_type=1,
        agi_env=agi_env,
        agi_node=agi_node,
        agi_cluster=agi_cluster,
        active_app=app_path,
        wenv_abs=wenv_abs,
        wenv_rel=Path("wenv"),
        uv="uv",
        uv_worker="uv",
        python_version="3.13",
        pyvers_worker="3.13",
        envars={},
        verbose=0,
        env_pck=tmp_path / "env_pck",
        dataset_archive=tmp_path / "missing.7z",
        target_worker="demo_worker",
        post_install_rel="demo.post_install",
        user=getpass.getuser(),
        cluster_pck=tmp_path / "cluster_pck",
        share_root_path=lambda: tmp_path / "share",
        logger=SimpleNamespace(warn=lambda *_a, **_k: None),
    )

    async def _fake_build():
        return None

    async def _fake_uninstall():
        return None

    agi_cls = SimpleNamespace(
        env=env,
        _run_type="sync",
        _rapids_enabled=False,
        _install_done_local=False,
        _hardware_supports_rapids=lambda: False,
        _build_lib_local=_fake_build,
        _uninstall_modules=_fake_uninstall,
    )

    async def _fake_run(cmd, _cwd):
        return ""

    with pytest.raises(RuntimeError, match="build --wheel"):
        await _call_deploy_local_worker(
            agi_cls,
            app_path,
            Path("wenv"),
            "",
            agi_version_missing_on_pypi_fn=lambda _p: False,
            run_fn=_fake_run,
            set_env_var_fn=lambda *_a, **_k: None,
            log=mock.Mock(),
        )


@pytest.mark.asyncio
async def test_deploy_local_worker_handles_archive_copy_edge_cases_and_missing_cli(
    tmp_path, monkeypatch
):
    app_path = tmp_path / "app"
    active_src = app_path / "src"
    active_src.mkdir(parents=True, exist_ok=True)
    archive = active_src / "Trajectory.7z"
    archive.write_text("traj", encoding="utf-8")
    (app_path / "pyproject.toml").write_text(
        "[project]\nname='demo-app'\n", encoding="utf-8"
    )

    agi_env_root = tmp_path / "agi_env"
    (agi_env_root / "src" / "agi_env" / "resources").mkdir(parents=True, exist_ok=True)
    (agi_env_root / "src" / "agi_env" / "resources" / "sample.txt").write_text(
        "x", encoding="utf-8"
    )
    agi_node_root = tmp_path / "agi_node"
    agi_node_root.mkdir(parents=True, exist_ok=True)

    wenv_abs = tmp_path / "worker_env"
    wenv_abs.mkdir(parents=True, exist_ok=True)
    (wenv_abs / "pyproject.toml").write_text(
        "[project]\nname='worker-app'\n", encoding="utf-8"
    )

    cluster_pck = tmp_path / "cluster_pck"
    (cluster_pck / "agi_distributor").mkdir(parents=True, exist_ok=True)

    env = SimpleNamespace(
        is_source_env=False,
        is_worker_env=False,
        install_type=1,
        agi_env=agi_env_root,
        agi_node=agi_node_root,
        active_app=app_path,
        wenv_abs=wenv_abs,
        wenv_rel=Path("worker_env"),
        uv="uv",
        uv_worker="uv",
        python_version="3.13",
        pyvers_worker="3.13",
        envars={},
        verbose=1,
        env_pck=agi_env_root / "src" / "agi_env",
        dataset_archive=archive,
        target_worker="demo_worker",
        post_install_rel="demo.post_install",
        user=getpass.getuser(),
        cluster_pck=cluster_pck,
        logger=SimpleNamespace(warn=lambda *_a, **_k: None),
        share_root_path=lambda: tmp_path / "share",
    )
    log = mock.Mock()

    async def _fake_run(cmd, _cwd):
        return ""

    async def _fake_build():
        return None

    async def _fake_uninstall():
        return None

    original_copy2 = deployment_local_support.shutil.copy2
    original_rglob = Path.rglob
    copy_calls = []

    def _patched_rglob(self, pattern):
        if self == active_src and pattern == "Trajectory.7z":
            return iter([archive])
        return original_rglob(self, pattern)

    def _patched_copy2(src, dst, *args, **kwargs):
        src_path = Path(src)
        dst_path = Path(dst)
        copy_calls.append((src_path, dst_path))
        if src_path.name == "Trajectory.7z":
            raise PermissionError("copy denied")
        return original_copy2(src, dst, *args, **kwargs)

    monkeypatch.setattr(Path, "rglob", _patched_rglob)
    monkeypatch.setattr(deployment_local_support.shutil, "copy2", _patched_copy2)

    agi_cls = SimpleNamespace(
        env=env,
        _run_type="sync",
        _rapids_enabled=False,
        _install_done_local=False,
        _hardware_supports_rapids=lambda: False,
        _build_lib_local=_fake_build,
        _uninstall_modules=_fake_uninstall,
    )

    with pytest.raises(FileNotFoundError):
        await _call_deploy_local_worker(
            agi_cls,
            app_path,
            Path("worker_env"),
            "",
            agi_version_missing_on_pypi_fn=lambda _p: False,
            run_fn=_fake_run,
            set_env_var_fn=lambda *_a, **_k: None,
            log=log,
        )

    assert sum(1 for src, _dst in copy_calls if src.name == "Trajectory.7z") == 1
    log.warning.assert_called()


@pytest.mark.asyncio
async def test_deploy_local_worker_handles_shallow_repo_root_and_rglob_oserror(
    tmp_path, monkeypatch
):
    app_path = tmp_path / "app"
    active_src = app_path / "src"
    active_src.mkdir(parents=True, exist_ok=True)
    (app_path / "pyproject.toml").write_text(
        "[project]\nname='demo-app'\n", encoding="utf-8"
    )

    agi_env_root = tmp_path / "agi_env"
    (agi_env_root / "src" / "agi_env" / "resources").mkdir(parents=True, exist_ok=True)
    (agi_env_root / "src" / "agi_env" / "resources" / "sample.txt").write_text(
        "x", encoding="utf-8"
    )
    agi_node_root = tmp_path / "agi_node"
    agi_node_root.mkdir(parents=True, exist_ok=True)

    cluster_pck = tmp_path / "cluster_pck"
    (cluster_pck / "agi_distributor").mkdir(parents=True, exist_ok=True)
    (cluster_pck / "agi_distributor" / "cli.py").write_text(
        "print('cli')", encoding="utf-8"
    )

    wenv_abs = tmp_path / "worker_env"
    wenv_abs.mkdir(parents=True, exist_ok=True)
    (wenv_abs / "pyproject.toml").write_text(
        "[project]\nname='worker-app'\n", encoding="utf-8"
    )

    env = SimpleNamespace(
        is_source_env=False,
        is_worker_env=False,
        install_type=0,
        agi_env=agi_env_root,
        agi_node=agi_node_root,
        active_app=app_path,
        wenv_abs=wenv_abs,
        wenv_rel=Path("worker_env"),
        uv="uv",
        uv_worker="uv",
        python_version="3.13",
        pyvers_worker="3.13",
        envars={},
        verbose=1,
        env_pck=agi_env_root / "src" / "agi_env",
        dataset_archive=tmp_path / "missing.7z",
        target_worker="demo_worker",
        post_install_rel="demo.post_install",
        user=getpass.getuser(),
        cluster_pck=cluster_pck,
        logger=SimpleNamespace(warn=lambda *_a, **_k: None),
        share_root_path=lambda: tmp_path / "share",
    )

    async def _fake_run(_cmd, _cwd):
        return ""

    async def _fake_build():
        return None

    async def _fake_uninstall():
        return None

    original_rglob = Path.rglob

    def _patched_rglob(self, pattern):
        if self == active_src and pattern == "Trajectory.7z":
            raise OSError("scan failed")
        return original_rglob(self, pattern)

    monkeypatch.setattr(
        deployment_local_support.AgiEnv,
        "read_agilab_path",
        staticmethod(lambda: Path("/repo")),
    )
    monkeypatch.setattr(Path, "rglob", _patched_rglob)

    agi_cls = SimpleNamespace(
        env=env,
        _run_type="sync",
        _rapids_enabled=False,
        _install_done_local=False,
        _hardware_supports_rapids=lambda: False,
        _build_lib_local=_fake_build,
        _uninstall_modules=_fake_uninstall,
    )

    await _call_deploy_local_worker(
        agi_cls,
        app_path,
        Path("worker_env"),
        "",
        agi_version_missing_on_pypi_fn=lambda _p: False,
        run_fn=_fake_run,
        set_env_var_fn=lambda *_a, **_k: None,
        log=mock.Mock(),
    )

    assert agi_cls._install_done_local is True


@pytest.mark.asyncio
async def test_deploy_local_worker_skips_duplicate_trajectory_archive_after_sat_scan_error(
    tmp_path,
    monkeypatch,
):
    app_path = tmp_path / "app"
    active_src = app_path / "src"
    active_src.mkdir(parents=True, exist_ok=True)
    archive = active_src / "Trajectory.7z"
    archive.write_text("traj", encoding="utf-8")
    (app_path / "pyproject.toml").write_text(
        "[project]\nname='demo-app'\n", encoding="utf-8"
    )

    agi_env_root = tmp_path / "agi_env"
    (agi_env_root / "src" / "agi_env" / "resources").mkdir(parents=True, exist_ok=True)
    (agi_env_root / "src" / "agi_env" / "resources" / "sample.txt").write_text(
        "x", encoding="utf-8"
    )
    agi_node_root = tmp_path / "agi_node"
    agi_node_root.mkdir(parents=True, exist_ok=True)

    cluster_pck = tmp_path / "cluster_pck"
    (cluster_pck / "agi_distributor").mkdir(parents=True, exist_ok=True)
    (cluster_pck / "agi_distributor" / "cli.py").write_text(
        "print('cli')", encoding="utf-8"
    )

    wenv_abs = tmp_path / "worker_env"
    wenv_abs.mkdir(parents=True, exist_ok=True)
    (wenv_abs / "pyproject.toml").write_text(
        "[project]\nname='worker-app'\n", encoding="utf-8"
    )

    env = SimpleNamespace(
        is_source_env=False,
        is_worker_env=False,
        install_type=1,
        agi_env=agi_env_root,
        agi_node=agi_node_root,
        active_app=app_path,
        wenv_abs=wenv_abs,
        wenv_rel=Path("worker_env"),
        uv="uv",
        uv_worker="uv",
        python_version="3.13",
        pyvers_worker="3.13",
        envars={},
        verbose=1,
        env_pck=agi_env_root / "src" / "agi_env",
        dataset_archive=archive,
        target_worker="demo_worker",
        post_install_rel="demo.post_install",
        user=getpass.getuser(),
        cluster_pck=cluster_pck,
        logger=SimpleNamespace(warn=lambda *_a, **_k: None),
        share_root_path=lambda: tmp_path / "share",
    )

    async def _fake_run(_cmd, _cwd):
        return ""

    async def _fake_build():
        return None

    async def _fake_uninstall():
        return None

    original_rglob = Path.rglob
    original_resolve = Path.resolve
    copy_calls = []

    def _patched_rglob(self, pattern):
        if self == active_src and pattern == "Trajectory.7z":
            return iter([archive])
        return original_rglob(self, pattern)

    def _patched_resolve(self, *args, **kwargs):
        if self == (tmp_path / "share" / "sat_trajectory"):
            raise OSError("resolve failed")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "rglob", _patched_rglob)
    monkeypatch.setattr(Path, "resolve", _patched_resolve, raising=False)
    monkeypatch.setattr(
        deployment_local_support.shutil,
        "copy2",
        lambda src, dst, *args, **kwargs: copy_calls.append((Path(src), Path(dst))),
    )

    agi_cls = SimpleNamespace(
        env=env,
        _run_type="sync",
        _rapids_enabled=False,
        _install_done_local=False,
        _hardware_supports_rapids=lambda: False,
        _build_lib_local=_fake_build,
        _uninstall_modules=_fake_uninstall,
    )

    await _call_deploy_local_worker(
        agi_cls,
        app_path,
        Path("worker_env"),
        "",
        agi_version_missing_on_pypi_fn=lambda _p: False,
        run_fn=_fake_run,
        set_env_var_fn=lambda *_a, **_k: None,
        log=mock.Mock(),
    )

    assert copy_calls == [(archive, wenv_abs / "src" / "demo_worker" / "Trajectory.7z")]


@pytest.mark.asyncio
async def test_deploy_local_worker_sorts_trajectory_archives_before_copy(
    tmp_path, monkeypatch
):
    app_path = tmp_path / "app"
    active_src = app_path / "src"
    first_dir = active_src / "zeta"
    second_dir = active_src / "alpha"
    first_dir.mkdir(parents=True, exist_ok=True)
    second_dir.mkdir(parents=True, exist_ok=True)
    first_archive = first_dir / "Trajectory.7z"
    second_archive = second_dir / "Trajectory.7z"
    first_archive.write_text("z", encoding="utf-8")
    second_archive.write_text("a", encoding="utf-8")
    (app_path / "pyproject.toml").write_text(
        "[project]\nname='demo-app'\n", encoding="utf-8"
    )

    agi_env_root = tmp_path / "agi_env"
    (agi_env_root / "src" / "agi_env" / "resources").mkdir(parents=True, exist_ok=True)
    (agi_env_root / "src" / "agi_env" / "resources" / "sample.txt").write_text(
        "x", encoding="utf-8"
    )
    agi_node_root = tmp_path / "agi_node"
    agi_node_root.mkdir(parents=True, exist_ok=True)
    cluster_pck = tmp_path / "cluster_pck"
    (cluster_pck / "agi_distributor").mkdir(parents=True, exist_ok=True)
    (cluster_pck / "agi_distributor" / "cli.py").write_text(
        "print('cli')", encoding="utf-8"
    )
    wenv_abs = tmp_path / "worker_env"
    wenv_abs.mkdir(parents=True, exist_ok=True)
    (wenv_abs / "pyproject.toml").write_text(
        "[project]\nname='worker-app'\n", encoding="utf-8"
    )

    env = SimpleNamespace(
        is_source_env=False,
        is_worker_env=False,
        install_type=1,
        agi_env=agi_env_root,
        agi_node=agi_node_root,
        active_app=app_path,
        wenv_abs=wenv_abs,
        wenv_rel=Path("worker_env"),
        uv="uv",
        uv_worker="uv",
        python_version="3.13",
        pyvers_worker="3.13",
        envars={},
        verbose=1,
        env_pck=agi_env_root / "src" / "agi_env",
        dataset_archive=tmp_path / "missing.7z",
        target_worker="demo_worker",
        post_install_rel="demo.post_install",
        user=getpass.getuser(),
        cluster_pck=cluster_pck,
        logger=SimpleNamespace(warn=lambda *_a, **_k: None),
        share_root_path=lambda: tmp_path / "share",
    )

    async def _fake_run(_cmd, _cwd):
        return ""

    async def _fake_build():
        return None

    async def _fake_uninstall():
        return None

    original_rglob = Path.rglob
    copy_calls: list[tuple[Path, Path]] = []

    def _patched_rglob(self, pattern):
        if self == active_src and pattern == "Trajectory.7z":
            return iter([first_archive, second_archive])
        return original_rglob(self, pattern)

    monkeypatch.setattr(Path, "rglob", _patched_rglob)
    monkeypatch.setattr(
        deployment_local_support.shutil,
        "copy2",
        lambda src, dst, *args, **kwargs: copy_calls.append((Path(src), Path(dst))),
    )

    agi_cls = SimpleNamespace(
        env=env,
        _run_type="sync",
        _rapids_enabled=False,
        _install_done_local=False,
        _hardware_supports_rapids=lambda: False,
        _build_lib_local=_fake_build,
        _uninstall_modules=_fake_uninstall,
    )

    await _call_deploy_local_worker(
        agi_cls,
        app_path,
        Path("worker_env"),
        "",
        agi_version_missing_on_pypi_fn=lambda _p: False,
        run_fn=_fake_run,
        set_env_var_fn=lambda *_a, **_k: None,
        log=mock.Mock(),
    )

    copied_archives = [src for src, _dst in copy_calls if src.name == "Trajectory.7z"]
    assert copied_archives == [second_archive, first_archive]


def test_copy_package_resources_uses_stamp_for_unchanged_inputs(monkeypatch, tmp_path):
    resources_src = tmp_path / "resources_src"
    resources_src.mkdir()
    (resources_src / "nested").mkdir()
    (resources_src / "nested" / "sample.txt").write_text("first", encoding="utf-8")
    resources_dest = tmp_path / "dest" / "resources"

    deployment_local_support._copy_package_resources(resources_src, resources_dest)

    assert (resources_dest / "nested" / "sample.txt").read_text(
        encoding="utf-8"
    ) == "first"
    assert (
        resources_dest / deployment_local_support.DEPLOY_COPY_STAMP_FILENAME
    ).exists()

    def _unexpected_copytree(*_args, **_kwargs):
        raise AssertionError("unchanged resources should not be copied")

    with monkeypatch.context() as blocked:
        blocked.setattr(
            deployment_local_support.shutil, "copytree", _unexpected_copytree
        )
        deployment_local_support._copy_package_resources(resources_src, resources_dest)

    (resources_src / "nested" / "sample.txt").write_text("second", encoding="utf-8")
    deployment_local_support._copy_package_resources(resources_src, resources_dest)

    assert (resources_dest / "nested" / "sample.txt").read_text(
        encoding="utf-8"
    ) == "second"


def test_copy_archive_with_stamp_uses_stamp_for_unchanged_inputs(monkeypatch, tmp_path):
    archive_path = tmp_path / "dataset.7z"
    archive_path.write_text("first", encoding="utf-8")
    destination = tmp_path / "worker" / "dataset.7z"

    assert (
        deployment_local_support._copy_archive_with_stamp(archive_path, destination)
        is True
    )
    assert destination.read_text(encoding="utf-8") == "first"
    assert (
        destination.with_name(f".{destination.name}.agilab-copy-stamp.json")
    ).exists()

    def _unexpected_copy2(*_args, **_kwargs):
        raise AssertionError("unchanged archive should not be copied")

    with monkeypatch.context() as blocked:
        blocked.setattr(deployment_local_support.shutil, "copy2", _unexpected_copy2)
        assert (
            deployment_local_support._copy_archive_with_stamp(
                archive_path, destination
            )
            is False
        )

    archive_path.write_text("second", encoding="utf-8")
    assert (
        deployment_local_support._copy_archive_with_stamp(archive_path, destination)
        is True
    )
    assert destination.read_text(encoding="utf-8") == "second"


def test_deployment_local_small_helper_edges(monkeypatch, tmp_path):
    assert deployment_local_support._python_version_tuple(None) is None
    assert deployment_local_support._python_version_tuple("python") is None
    assert (
        deployment_local_support._project_venv_cfg_version(tmp_path / "missing") is None
    )

    cfg_project = tmp_path / "cfg"
    (cfg_project / ".venv").mkdir(parents=True)
    (cfg_project / ".venv" / "pyvenv.cfg").write_text(
        "home=/tmp\nversion = 3.13.2\n", encoding="utf-8"
    )
    assert deployment_local_support._project_venv_cfg_version(cfg_project) == (3, 13, 2)
    assert (
        deployment_local_support._project_venv_matches(
            cfg_project, python_version="3.13"
        )
        is False
    )
    _write_venv_python(cfg_project)
    assert (
        deployment_local_support._project_venv_matches(
            cfg_project, python_version="3.13"
        )
        is True
    )

    class _BrokenEnvars:
        def get(self, _key):
            raise RuntimeError("broken")

    monkeypatch.delenv("AGILAB_SHARED_WORKER_VENV_DIR", raising=False)
    assert (
        deployment_local_support._env_value(
            _BrokenEnvars(), "AGILAB_SHARED_WORKER_VENV_DIR"
        )
        is None
    )

    active_app = tmp_path / "app"
    wenv = tmp_path / "wenv"
    active_app.mkdir()
    wenv.mkdir()
    shared_project = deployment_local_support._shared_worker_venv_project(
        {
            deployment_local_support.SHARED_WORKER_VENV_ENV: "1",
            deployment_local_support.SHARED_WORKER_VENV_DIR_ENV: "relative-cache",
        },
        active_app=active_app,
        wenv_abs=wenv,
        python_version="3.13",
        run_type="uv run",
        options_worker="",
        worker_core_add_specs=[],
        hw_rapids_capable=False,
    )
    assert shared_project is not None
    assert shared_project.parent == wenv.parent / "relative-cache"

    resources_dest = tmp_path / "dest" / "resources"
    deployment_local_support._copy_package_resources(
        tmp_path / "missing-resources", resources_dest
    )
    assert not resources_dest.exists()

    legacy = tmp_path / "legacy_app" / "agilab/core/agi-env/src/agi_env/resources"
    legacy.mkdir(parents=True)
    blocker = legacy.parent / "blocker.txt"
    blocker.write_text("keep parent non-empty", encoding="utf-8")
    deployment_local_support._remove_legacy_app_resource_copy(tmp_path / "legacy_app")
    assert not legacy.exists()
    assert blocker.exists()
