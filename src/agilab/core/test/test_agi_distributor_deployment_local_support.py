from __future__ import annotations

import getpass
import os
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
import tomlkit

from agi_cluster.agi_distributor import deployment_local_support, uv_source_support


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


def test_force_remove_falls_back_to_subprocess_when_path_survives(monkeypatch, tmp_path):
    target = tmp_path / "stubborn"
    target.mkdir(parents=True, exist_ok=True)
    calls = []
    env_logger = mock.Mock()

    monkeypatch.setattr(deployment_local_support.shutil, "rmtree", lambda *_a, **_k: None)
    monkeypatch.setattr(
        deployment_local_support.subprocess,
        "run",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    deployment_local_support._force_remove(target, env_logger=env_logger)

    assert calls
    assert calls[0][0][0] == ["cmd", "/c", "rmdir", "/s", "/q", str(target)]
    assert env_logger.warn.called


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


def test_force_remove_onerror_handles_oserror_and_skips_logger_when_missing(monkeypatch, tmp_path):
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


def test_force_remove_swallows_filesystem_error_and_uses_subprocess(monkeypatch, tmp_path):
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
            f'uv pip install --python "{tmp_path / ".venv" / "bin" / "python"}" '
            f'--upgrade --no-deps "{package_path}"',
            tmp_path,
        ),
    ]


def test_project_venv_python_uses_windows_layout(tmp_path):
    assert deployment_local_support._project_venv_python(tmp_path, os_name="nt") == (
        tmp_path / ".venv" / "Scripts" / "python.exe"
    )


def test_resolve_install_spec_prefers_project_path_over_distribution_metadata(tmp_path, monkeypatch):
    project_path = tmp_path / "agi-env"
    project_path.mkdir()
    (project_path / "pyproject.toml").write_text("[project]\nname='agi-env'\n", encoding="utf-8")
    monkeypatch.setattr(
        deployment_local_support,
        "_resolve_distribution_install_spec",
        lambda _name: "agi-env==0.0.0",
    )

    assert deployment_local_support._resolve_install_spec(project_path, "agi-env") == str(project_path)


def test_resolve_install_spec_falls_back_to_distribution_metadata_for_non_project_path(tmp_path, monkeypatch):
    project_path = tmp_path / "agi-env"
    project_path.mkdir()
    monkeypatch.setattr(
        deployment_local_support,
        "_resolve_distribution_install_spec",
        lambda _name: "agi-env==0.0.0",
    )

    assert deployment_local_support._resolve_install_spec(project_path, "agi-env") == "agi-env==0.0.0"


def test_resolve_distribution_install_spec_returns_none_when_distribution_is_missing(monkeypatch):
    def _missing(_name):
        raise deployment_local_support.PackageNotFoundError

    monkeypatch.setattr(deployment_local_support, "pkg_distribution", _missing)

    assert deployment_local_support._resolve_distribution_install_spec("agi-env") is None


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

    monkeypatch.setattr(deployment_local_support, "pkg_distribution", lambda _name: _Dist())

    assert (
        deployment_local_support._resolve_distribution_install_spec("agi-env")
        == "agi-env @ git+https://github.com/ThalesGroup/agilab.git@main#subdirectory=src/agilab/core/agi-env"
    )


def test_resolve_distribution_install_spec_uses_direct_url_with_subdirectory_without_vcs(monkeypatch):
    class _Dist:
        version = "2026.4.20"

        @staticmethod
        def read_text(name):
            assert name == "direct_url.json"
            return '{"url":"https://example.com/agi-env.tar.gz","subdirectory":"src/agi-env"}'

    monkeypatch.setattr(deployment_local_support, "pkg_distribution", lambda _name: _Dist())

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

    monkeypatch.setattr(deployment_local_support, "pkg_distribution", lambda _name: _Dist())

    assert deployment_local_support._resolve_distribution_install_spec("agi-env") == "agi-env==2026.4.20"


def test_resolve_distribution_install_spec_ignores_invalid_direct_url_json(monkeypatch):
    class _Dist:
        version = "2026.4.20"

        @staticmethod
        def read_text(_name):
            return "{invalid-json"

    monkeypatch.setattr(deployment_local_support, "pkg_distribution", lambda _name: _Dist())

    assert deployment_local_support._resolve_distribution_install_spec("agi-env") == "agi-env==2026.4.20"


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
    assert deployment_local_support._parse_dependency_names(["numpy>=1.26", 3, None, "not["]) == {"numpy"}


def test_manager_dependency_names_returns_empty_for_missing_or_invalid_pyproject(tmp_path):
    missing = tmp_path / "missing.toml"
    invalid = tmp_path / "invalid.toml"
    invalid.write_text("[project\nname = 'broken'\n", encoding="utf-8")

    assert deployment_local_support._manager_dependency_names(missing) == set()
    assert deployment_local_support._manager_dependency_names(invalid) == set()


def test_manager_overlay_core_sources_recovers_when_second_parse_fails(tmp_path, monkeypatch):
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

    assert deployment_local_support._manager_overlay_core_sources(
        pyproject,
        {"agi-env": agi_env_path},
    ) == {"agi-env": str(agi_env_path.resolve(strict=False))}


def test_manager_overlay_core_sources_preserves_existing_paths_and_adds_missing_ones(tmp_path):
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

    assert deployment_local_support._manager_overlay_core_sources(
        pyproject,
        {
            "agi-env": agi_env_path,
            "agi-node": agi_node_path,
        },
    ) == {"agi-node": str(agi_node_path.resolve(strict=False))}


def test_write_manager_sync_overlay_bootstraps_missing_tables(tmp_path):
    source_pyproject = tmp_path / "pyproject.toml"
    source_pyproject.write_text("", encoding="utf-8")
    overlay_dir = tmp_path / "overlay"

    deployment_local_support._write_manager_sync_overlay(
        source_pyproject,
        overlay_dir,
        local_core_sources={"agi-env": str((tmp_path / "agi-env").resolve(strict=False))},
    )

    overlay_doc = tomlkit.parse((overlay_dir / "pyproject.toml").read_text(encoding="utf-8"))
    assert overlay_doc["tool"]["uv"]["sources"]["agi-env"]["path"] == str(
        (tmp_path / "agi-env").resolve(strict=False)
    )


def test_write_manager_sync_overlay_normalizes_paths_and_skips_invalid_entries(tmp_path):
    source_dir = tmp_path / "apps" / "demo"
    source_dir.mkdir(parents=True, exist_ok=True)
    abs_dep = tmp_path / "abs-dep"
    abs_dep.mkdir()
    source_pyproject = source_dir / "pyproject.toml"
    source_pyproject.write_text(
        f"""
[project]
name = "demo"

[tool.uv.sources]
demo = {{ workspace = true }}
non_dict = "skip-me"
blank = {{ path = "   " }}
rel = {{ path = "../shared" }}
abs = {{ path = "{abs_dep}" }}
""".strip(),
        encoding="utf-8",
    )
    overlay_dir = tmp_path / "overlay"

    deployment_local_support._write_manager_sync_overlay(
        source_pyproject,
        overlay_dir,
        local_core_sources={},
    )

    overlay_doc = tomlkit.parse((overlay_dir / "pyproject.toml").read_text(encoding="utf-8"))
    sources = overlay_doc["tool"]["uv"]["sources"]
    assert "demo" not in sources
    assert sources["non_dict"] == "skip-me"
    assert sources["blank"]["path"] == "   "
    assert sources["rel"]["path"] == str((source_dir / "../shared").resolve(strict=False))
    assert sources["abs"]["path"] == str(abs_dep.resolve(strict=False))


def test_shell_env_prefix_returns_empty_for_no_overrides():
    assert deployment_local_support._shell_env_prefix({}) == ""


def test_uv_offline_flag_handles_failing_lookup_false_and_nan(monkeypatch):
    monkeypatch.delenv("AGI_INTERNET_ON", raising=False)

    class _BrokenEnvars:
        def get(self, _key):
            raise RuntimeError("boom")

    assert deployment_local_support._uv_offline_flag(_BrokenEnvars()) == ""
    assert deployment_local_support._uv_offline_flag({"AGI_INTERNET_ON": False}) == "--offline "
    assert deployment_local_support._uv_offline_flag({"AGI_INTERNET_ON": float("nan")}) == "--offline "


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
    assert deployment_local_support._infer_repo_root_from_runtime("too-short.py") is None


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


def test_update_pyproject_dependencies_bootstraps_missing_file_and_pinned_extras(tmp_path):
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


def test_update_pyproject_dependencies_normalizes_non_array_dependencies(monkeypatch, tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname='worker'\n", encoding="utf-8")
    project_doc = tomlkit.document()
    project_tbl = tomlkit.table()
    project_tbl["dependencies"] = ("numpy>=1",)
    project_doc["project"] = project_tbl

    monkeypatch.setattr(deployment_local_support.tomlkit, "parse", lambda _text: project_doc)

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


def test_update_pyproject_dependencies_normalizes_plain_sequence_dependencies(monkeypatch, tmp_path):
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


def test_update_pyproject_dependencies_propagates_unexpected_requirement_bug(monkeypatch, tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname='worker'\ndependencies=['numpy>=1']\n", encoding="utf-8")

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

    dependency_info, worker_pyprojects = deployment_local_support._gather_dependency_specs([first, second])

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

    dependency_info, _worker_pyprojects = deployment_local_support._gather_dependency_specs(
        [exact, ranged]
    )

    assert dependency_info["scipy"]["has_exact"] is True
    assert dependency_info["scipy"]["specifiers"] == ["==1.16.1"]


def test_gather_dependency_specs_skips_invalid_pyproject_and_dependency_entries(tmp_path):
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

    dependency_info, worker_pyprojects = deployment_local_support._gather_dependency_specs([good, bad, weird])

    assert str((good / "pyproject.toml").resolve()) in worker_pyprojects
    assert str((bad / "pyproject.toml").resolve()) not in worker_pyprojects
    assert str((weird / "pyproject.toml").resolve()) in worker_pyprojects
    assert set(dependency_info) == {"numpy"}


def test_gather_dependency_specs_propagates_unexpected_parse_bug(monkeypatch, tmp_path):
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    (project / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

    def _boom(_text):
        raise ValueError("unexpected parse bug")

    monkeypatch.setattr(deployment_local_support.tomlkit, "parse", _boom)

    with pytest.raises(ValueError, match="unexpected parse bug"):
        deployment_local_support._gather_dependency_specs([project])


def test_gather_dependency_specs_skips_none_missing_duplicate_and_false_marker_entries(tmp_path):
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

    dependency_info, worker_pyprojects = deployment_local_support._gather_dependency_specs(
        [None, project, tmp_path / "missing", project]
    )

    assert worker_pyprojects == {str((project / "pyproject.toml").resolve())}
    assert set(dependency_info) == {"numpy"}


@pytest.mark.asyncio
async def test_deploy_local_worker_non_source_flow(tmp_path):
    app_path = tmp_path / "app"
    app_path.mkdir(parents=True, exist_ok=True)
    (app_path / "pyproject.toml").write_text("[project]\nname='demo-app'\n", encoding="utf-8")

    agi_env_root = tmp_path / "agi_env"
    (agi_env_root / "src" / "agi_env" / "resources").mkdir(parents=True, exist_ok=True)
    (agi_env_root / "src" / "agi_env" / "resources" / "sample.txt").write_text("x", encoding="utf-8")
    agi_node_root = tmp_path / "agi_node"
    agi_node_root.mkdir(parents=True, exist_ok=True)

    cluster_pck = tmp_path / "cluster_pck"
    (cluster_pck / "agi_distributor").mkdir(parents=True, exist_ok=True)
    (cluster_pck / "agi_distributor" / "cli.py").write_text("print('cli')", encoding="utf-8")

    wenv_abs = tmp_path / "worker_env"
    wenv_abs.mkdir(parents=True, exist_ok=True)
    (wenv_abs / "pyproject.toml").write_text("[project]\nname='worker-app'\n", encoding="utf-8")

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
    assert any("AGI_CLUSTER_ENABLED=0" in cmd and "demo.post_install" in cmd for cmd, _ in commands)
    assert any(f'"{app_path}"' in cmd and "demo.post_install" in cmd for cmd, _ in commands)
    assert any("threaded" in cmd for cmd, _ in commands)


@pytest.mark.asyncio
async def test_deploy_local_worker_rapids_reuses_cli_and_falls_back_from_localhost_ssh(tmp_path):
    app_path = tmp_path / "app"
    app_path.mkdir(parents=True, exist_ok=True)
    (app_path / "pyproject.toml").write_text("[project]\nname='demo-app'\n", encoding="utf-8")

    agi_env_root = tmp_path / "agi_env"
    (agi_env_root / "src" / "agi_env" / "resources").mkdir(parents=True, exist_ok=True)
    (agi_env_root / "src" / "agi_env" / "resources" / "sample.txt").write_text("x", encoding="utf-8")
    agi_node_root = tmp_path / "agi_node"
    agi_node_root.mkdir(parents=True, exist_ok=True)

    cluster_pck = tmp_path / "cluster_pck"
    (cluster_pck / "agi_distributor").mkdir(parents=True, exist_ok=True)
    (cluster_pck / "agi_distributor" / "cli.py").write_text("print('cli')", encoding="utf-8")

    wenv_abs = tmp_path / "worker_env"
    wenv_abs.mkdir(parents=True, exist_ok=True)
    (wenv_abs / "pyproject.toml").write_text("[project]\nname='worker-app'\n", encoding="utf-8")
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
    assert not any("AGI_CLUSTER_ENABLED=0" in cmd and "demo.post_install" in cmd for cmd, _ in commands)
    assert any(
        "uv sync --config-file uv_config.toml --project" in cmd and str(app_path) in cmd
        for cmd, _ in commands
    )
    assert any(
        "uv sync --python 3.13 --config-file uv_config.toml --project" in cmd
        and str(wenv_abs) in cmd
        for cmd, _ in commands
    )
    assert not any(
        "uv sync" in cmd and str(wenv_abs) in cmd and "--extra pandas-worker" in cmd
        for cmd, _ in commands
    )
    assert any(f'python "{existing_cli}" threaded' in cmd for cmd, _ in commands)


@pytest.mark.asyncio
async def test_deploy_local_worker_install_type_zero_non_source_covers_dependency_flow(tmp_path, monkeypatch):
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
    (env_project / "src" / "agi_env" / "resources" / "resource.txt").write_text("x", encoding="utf-8")

    app_path = tmp_path / "app"
    app_path.mkdir(parents=True, exist_ok=True)
    (app_path / "pyproject.toml").write_text("[project]\nname='app'\n", encoding="utf-8")
    (app_path / "src").mkdir(parents=True, exist_ok=True)
    (app_path / "src" / "Trajectory.7z").write_text("traj", encoding="utf-8")
    (app_path / ".venv").mkdir(parents=True, exist_ok=True)
    (app_path / "uv.lock").write_text("lock", encoding="utf-8")

    wenv_abs = tmp_path / "wenv"
    wenv_abs.mkdir(parents=True, exist_ok=True)
    (wenv_abs / "pyproject.toml").write_text("[project]\nname='worker'\n", encoding="utf-8")
    (wenv_abs / ".venv").mkdir(parents=True, exist_ok=True)
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
    (cluster_pck / "agi_distributor" / "cli.py").write_text("print('cli')", encoding="utf-8")

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

    monkeypatch.setattr(deployment_local_support.AgiEnv, "read_agilab_path", staticmethod(lambda: repo_root))

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
    assert "pip" in manager_toml
    assert (wenv_abs / "src" / "demo_worker" / "dataset.7z").exists()
    assert (wenv_abs / "src" / "demo_worker" / "Trajectory.7z").exists() is False
    assert (
        wenv_abs / ".venv" / "lib" / "python3.13" / "site-packages" / "agilab_uv_sources.pth"
    ).read_text(encoding="utf-8") == "../../../../_uv_sources\n"
    assert agi_cls._install_done_local is True
    assert any(
        f'add "{env_project}" "{node_project}"' in cmd and str(wenv_abs) in cmd
        for cmd, _ in commands
    )
    assert not any("add agi-env" in cmd and str(wenv_abs) in cmd for cmd, _ in commands)
    assert any("config-file uv_config.toml" in cmd for cmd, _ in commands)
    assert any("pip install --python" in cmd and str(wenv_abs / ".venv") in cmd for cmd, _ in commands)
    assert any("demo.post_install" in cmd for cmd in ssh_calls)


@pytest.mark.asyncio
async def test_deploy_local_worker_install_type_zero_non_source_uses_distribution_specs_for_non_project_paths(
    tmp_path,
    monkeypatch,
):
    app_path = tmp_path / "app"
    app_path.mkdir(parents=True, exist_ok=True)
    (app_path / "pyproject.toml").write_text("[project]\nname='app'\n", encoding="utf-8")
    (app_path / ".venv").mkdir(parents=True, exist_ok=True)
    (app_path / "uv.lock").write_text("lock", encoding="utf-8")

    wenv_abs = tmp_path / "wenv"
    wenv_abs.mkdir(parents=True, exist_ok=True)
    (wenv_abs / "pyproject.toml").write_text("[project]\nname='worker'\n", encoding="utf-8")
    (wenv_abs / ".venv").mkdir(parents=True, exist_ok=True)

    env_pck = tmp_path / "site-packages" / "agi_env"
    env_pck.mkdir(parents=True, exist_ok=True)
    (env_pck / "resources").mkdir(parents=True, exist_ok=True)

    node_pck = tmp_path / "site-packages" / "agi_node"
    node_pck.mkdir(parents=True, exist_ok=True)

    cluster_pck = tmp_path / "site-packages" / "agi_cluster"
    (cluster_pck / "agi_distributor").mkdir(parents=True, exist_ok=True)
    (cluster_pck / "agi_distributor" / "cli.py").write_text("print('cli')", encoding="utf-8")

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

    monkeypatch.setattr(deployment_local_support.AgiEnv, "read_agilab_path", staticmethod(lambda: None))
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
    assert any("agi-env @ git+https://example.invalid/repo.git@main#subdirectory=agi-env" in cmd for cmd, _ in commands)
    assert any("agi-node @ git+https://example.invalid/repo.git@main#subdirectory=agi-node" in cmd for cmd, _ in commands)


@pytest.mark.asyncio
async def test_deploy_local_worker_preserves_existing_dependency_ranges(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo" / "src" / "agilab"
    env_project = repo_root / "core" / "agi-env"
    node_project = repo_root / "core" / "agi-node"
    core_project = repo_root / "core" / "agi-core"
    cluster_project = repo_root / "core" / "agi-cluster"
    for project in (env_project, node_project, core_project, cluster_project):
        project.mkdir(parents=True, exist_ok=True)
    (env_project / "src" / "agi_env" / "resources").mkdir(parents=True, exist_ok=True)
    (env_project / "src" / "agi_env" / "resources" / "resource.txt").write_text("x", encoding="utf-8")
    (env_project / "pyproject.toml").write_text("[project]\nname='agi-env'\ndependencies=['pip>=1']\n", encoding="utf-8")
    (node_project / "pyproject.toml").write_text(
        "[project]\nname='agi-node'\ndependencies=['scipy==1.16.1']\n",
        encoding="utf-8",
    )
    (core_project / "pyproject.toml").write_text("[project]\nname='agi-core'\ndependencies=[]\n", encoding="utf-8")
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
    (wenv_abs / "pyproject.toml").write_text("[project]\nname='worker'\n", encoding="utf-8")
    (wenv_abs / ".venv").mkdir(parents=True, exist_ok=True)
    (wenv_abs / "_uv_sources" / "ilp_worker").mkdir(parents=True, exist_ok=True)

    env_pck = tmp_path / "env_pck" / "agi_env"
    env_pck.mkdir(parents=True, exist_ok=True)
    (env_pck.parent / "__editable__.agi_env-demo.pth").write_text("x", encoding="utf-8")

    cluster_pck = tmp_path / "cluster_pck"
    (cluster_pck / "agi_distributor").mkdir(parents=True, exist_ok=True)
    (cluster_pck / "agi_distributor" / "cli.py").write_text("print('cli')", encoding="utf-8")

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

    monkeypatch.setattr(deployment_local_support.AgiEnv, "read_agilab_path", staticmethod(lambda: repo_root))

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
    assert 'scipy>=1.15.2,<1.17' in manager_toml
    assert 'scipy==1.16.1' not in manager_toml
    assert any(
        f'add "{env_project}" "{node_project}"' in cmd and str(wenv_abs) in cmd
        for cmd, _ in commands
    )
    assert any("sync --project" in cmd for cmd, _ in commands)


@pytest.mark.asyncio
async def test_deploy_local_worker_infers_repo_root_to_avoid_rewriting_source_app(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo" / "src" / "agilab"
    env_project = repo_root / "core" / "agi-env"
    node_project = repo_root / "core" / "agi-node"
    core_project = repo_root / "core" / "agi-core"
    cluster_project = repo_root / "core" / "agi-cluster"
    for project in (env_project, node_project, core_project, cluster_project):
        project.mkdir(parents=True, exist_ok=True)
    (env_project / "src" / "agi_env" / "resources").mkdir(parents=True, exist_ok=True)
    (env_project / "src" / "agi_env" / "resources" / "resource.txt").write_text("x", encoding="utf-8")
    (env_project / "pyproject.toml").write_text("[project]\nname='agi-env'\ndependencies=['pip>=1']\n", encoding="utf-8")
    (node_project / "pyproject.toml").write_text(
        "[project]\nname='agi-node'\ndependencies=['scipy==1.16.1']\n",
        encoding="utf-8",
    )
    (core_project / "pyproject.toml").write_text("[project]\nname='agi-core'\ndependencies=[]\n", encoding="utf-8")
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
    fake_module_file.write_text("# fake module path for repo inference\n", encoding="utf-8")

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
    (wenv_abs / "pyproject.toml").write_text("[project]\nname='worker'\n", encoding="utf-8")
    (wenv_abs / ".venv").mkdir(parents=True, exist_ok=True)
    (wenv_abs / "_uv_sources" / "ilp_worker").mkdir(parents=True, exist_ok=True)

    env_pck = tmp_path / "env_pck" / "agi_env"
    env_pck.mkdir(parents=True, exist_ok=True)
    (env_pck.parent / "__editable__.agi_env-demo.pth").write_text("x", encoding="utf-8")

    cluster_pck = tmp_path / "cluster_pck"
    (cluster_pck / "agi_distributor").mkdir(parents=True, exist_ok=True)
    (cluster_pck / "agi_distributor" / "cli.py").write_text("print('cli')", encoding="utf-8")

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

    monkeypatch.setattr(deployment_local_support.AgiEnv, "read_agilab_path", staticmethod(lambda: None))

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
        f'add "{env_project}" "{node_project}"' in cmd and str(wenv_abs) in cmd
        for cmd, _ in commands
    )


@pytest.mark.asyncio
async def test_deploy_local_worker_source_env_branch(tmp_path):
    app_path = tmp_path / "app"
    app_path.mkdir(parents=True, exist_ok=True)
    (app_path / "pyproject.toml").write_text("[project]\nname='app'\n", encoding="utf-8")
    wenv_abs = tmp_path / "wenv"
    wenv_abs.mkdir(parents=True, exist_ok=True)
    (wenv_abs / "pyproject.toml").write_text("[project]\nname='worker'\n", encoding="utf-8")
    agi_env = tmp_path / "agi_env"
    agi_node = tmp_path / "agi_node"
    agi_cluster = tmp_path / "agi_cluster"
    for project in (agi_env, agi_node, agi_cluster):
        project.mkdir(parents=True, exist_ok=True)
        (project / "dist").mkdir(parents=True, exist_ok=True)
    (agi_env / "dist" / "agi_env-0.0.1-py3-none-any.whl").write_text("whl", encoding="utf-8")
    old_node_whl = agi_node / "dist" / "agi_node-0.0.1-py3-none-any.whl"
    new_node_whl = agi_node / "dist" / "agi_node-0.0.2-py3-none-any.whl"
    old_node_whl.write_text("old-whl", encoding="utf-8")
    new_node_whl.write_text("new-whl", encoding="utf-8")
    os.utime(old_node_whl, (1, 1))
    os.utime(new_node_whl, (2, 2))
    cluster_pck = tmp_path / "cluster_pck"
    (cluster_pck / "agi_distributor").mkdir(parents=True, exist_ok=True)
    (cluster_pck / "agi_distributor" / "cli.py").write_text("print('cli')", encoding="utf-8")

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
    assert any("uv --offline sync" in cmd and str(app_path) in cmd for cmd, _ in commands)
    assert any(f"uv --offline pip install -e '{agi_env}'" in cmd for cmd, _ in commands)
    assert any(f"uv --offline pip install -e '{agi_node}'" in cmd for cmd, _ in commands)
    assert any(f"uv --offline pip install -e '{agi_cluster}'" in cmd for cmd, _ in commands)
    assert any(f'uv --offline --project "{agi_env}" build --wheel' in cmd for cmd, _ in commands)
    assert any(f'uv --offline --project "{agi_node}" build --wheel' in cmd for cmd, _ in commands)
    assert any(f'uv --offline pip install --project "{wenv_abs}" --no-deps -e "{agi_env}"' in cmd for cmd, _ in commands)
    assert any(f'uv --offline pip install --project "{wenv_abs}" --no-deps -e "{agi_node}"' in cmd for cmd, _ in commands)
    assert any(f'pip install --project "{wenv_abs}" --no-deps -e "{app_path}"' in cmd for cmd, _ in commands)
    assert (wenv_abs / "agi_node-0.0.2-py3-none-any.whl").exists()
    assert not (wenv_abs / "agi_node-0.0.1-py3-none-any.whl").exists()


@pytest.mark.asyncio
async def test_deploy_local_worker_source_env_offline_manager_overlay_for_external_app(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo" / "src" / "agilab"
    env_project = repo_root / "core" / "agi-env"
    node_project = repo_root / "core" / "agi-node"
    cluster_project = repo_root / "core" / "agi-cluster"
    for project, name in (
        (env_project, "agi-env"),
        (node_project, "agi-node"),
        (cluster_project, "agi-cluster"),
    ):
        project.mkdir(parents=True, exist_ok=True)
        (project / "pyproject.toml").write_text(f"[project]\nname='{name}'\n", encoding="utf-8")
        (project / "dist").mkdir(parents=True, exist_ok=True)
    (env_project / "dist" / "agi_env-0.0.1-py3-none-any.whl").write_text("whl", encoding="utf-8")
    (node_project / "dist" / "agi_node-0.0.1-py3-none-any.whl").write_text("whl", encoding="utf-8")

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
    fake_module_file.write_text("# fake module path for repo inference\n", encoding="utf-8")

    external_apps_root = tmp_path / "external_apps"
    app_path = external_apps_root / "sb3_trainer_project"
    sat_project = external_apps_root / "sat_trajectory_project"
    app_path.mkdir(parents=True, exist_ok=True)
    sat_project.mkdir(parents=True, exist_ok=True)
    (sat_project / "pyproject.toml").write_text("[project]\nname='sat-trajectory-project'\n", encoding="utf-8")
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
    (wenv_abs / "pyproject.toml").write_text("[project]\nname='worker'\n", encoding="utf-8")
    (wenv_abs / ".venv").mkdir(parents=True, exist_ok=True)
    (wenv_abs / "_uv_sources" / "demo_worker").mkdir(parents=True, exist_ok=True)

    cluster_pck = tmp_path / "cluster_pck"
    (cluster_pck / "agi_distributor").mkdir(parents=True, exist_ok=True)
    (cluster_pck / "agi_distributor" / "cli.py").write_text("print('cli')", encoding="utf-8")

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

    monkeypatch.setattr(deployment_local_support.AgiEnv, "read_agilab_path", staticmethod(lambda: None))
    monkeypatch.setattr(deployment_local_support, "TemporaryDirectory", _FakeTemporaryDirectory)

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

    overlay_doc = tomlkit.parse((staged_overlay_root / "pyproject.toml").read_text(encoding="utf-8"))
    overlay_sources = overlay_doc["tool"]["uv"]["sources"]
    assert str(overlay_sources["agi-env"]["path"]) == str(env_project.resolve(strict=False))
    assert str(overlay_sources["agi-node"]["path"]) == str(node_project.resolve(strict=False))
    assert str(overlay_sources["sat-trajectory-project"]["path"]) == str(sat_project.resolve(strict=False))
    assert "sb3_trainer_project" not in overlay_sources
    assert any(
        "--project" in cmd
        and "--active --no-install-project" in cmd
        and str(staged_overlay_root) in cmd
        for cmd, _ in commands
    )
    assert any(f"uv --offline pip install -e '{env_project}'" in cmd for cmd, _ in commands)
    assert any(f"uv --offline pip install -e '{node_project}'" in cmd for cmd, _ in commands)
    assert any(f"uv --offline pip install -e '{cluster_project}'" in cmd for cmd, _ in commands)


@pytest.mark.asyncio
async def test_deploy_local_worker_offline_manager_overlay_preserves_local_sources(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo" / "src" / "agilab"
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
        (project / "pyproject.toml").write_text(f"[project]\nname='{name}'\n", encoding="utf-8")
    (env_project / "src" / "agi_env" / "resources").mkdir(parents=True, exist_ok=True)
    (env_project / "src" / "agi_env" / "resources" / "resource.txt").write_text("x", encoding="utf-8")

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
    fake_module_file.write_text("# fake module path for repo inference\n", encoding="utf-8")

    external_apps_root = tmp_path / "external_apps"
    app_path = external_apps_root / "sb3_trainer_project"
    sat_project = external_apps_root / "sat_trajectory_project"
    app_path.mkdir(parents=True, exist_ok=True)
    sat_project.mkdir(parents=True, exist_ok=True)
    (sat_project / "pyproject.toml").write_text("[project]\nname='sat-trajectory-project'\n", encoding="utf-8")
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
    (wenv_abs / "pyproject.toml").write_text("[project]\nname='worker'\n", encoding="utf-8")
    (wenv_abs / ".venv").mkdir(parents=True, exist_ok=True)
    (wenv_abs / "_uv_sources" / "demo_worker").mkdir(parents=True, exist_ok=True)

    env_pck = tmp_path / "env_pck" / "agi_env"
    env_pck.mkdir(parents=True, exist_ok=True)
    cluster_pck = tmp_path / "cluster_pck"
    (cluster_pck / "agi_distributor").mkdir(parents=True, exist_ok=True)
    (cluster_pck / "agi_distributor" / "cli.py").write_text("print('cli')", encoding="utf-8")

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

    monkeypatch.setattr(deployment_local_support.AgiEnv, "read_agilab_path", staticmethod(lambda: None))
    monkeypatch.setattr(deployment_local_support, "TemporaryDirectory", _FakeTemporaryDirectory)

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

    overlay_doc = tomlkit.parse((staged_overlay_root / "pyproject.toml").read_text(encoding="utf-8"))
    overlay_sources = overlay_doc["tool"]["uv"]["sources"]
    assert str(overlay_sources["agi-env"]["path"]) == str(env_project.resolve(strict=False))
    assert str(overlay_sources["agi-node"]["path"]) == str(node_project.resolve(strict=False))
    assert str(overlay_sources["sat-trajectory-project"]["path"]) == str(sat_project.resolve(strict=False))
    assert "sb3_trainer_project" not in overlay_sources
    assert any(
        "sync --project" in cmd
        and "--active --no-install-project" in cmd
        and str(staged_overlay_root) in cmd
        for cmd, _ in commands
    )
    assert any(
        f'pip install --python "{app_path / ".venv" / "bin" / "python"}" --upgrade --no-deps -e "{app_path}"' in cmd
        for cmd, _ in commands
    )
    assert any(
        f'add "{env_project}" "{node_project}"' in cmd and str(wenv_abs) in cmd
        for cmd, _ in commands
    )


@pytest.mark.asyncio
async def test_deploy_local_worker_install_type_zero_uses_resource_fallbacks_and_free_threaded_python(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo" / "src" / "agilab"
    env_project = repo_root / "core" / "agi-env"
    node_project = repo_root / "core" / "agi-node"
    core_project = repo_root / "core" / "agi-core"
    cluster_project = repo_root / "core" / "agi-cluster"
    for project in (env_project, node_project, core_project, cluster_project):
        project.mkdir(parents=True, exist_ok=True)
    (env_project / "pyproject.toml").write_text("[project]\nname='agi-env'\ndependencies=['pip>=1']\n", encoding="utf-8")
    (node_project / "pyproject.toml").write_text("[project]\nname='agi-node'\ndependencies=['scipy>=1']\n", encoding="utf-8")
    (core_project / "pyproject.toml").write_text("[project]\nname='agi-core'\ndependencies=[]\n", encoding="utf-8")
    (cluster_project / "pyproject.toml").write_text("[project]\nname='agi-cluster'\ndependencies=[]\n", encoding="utf-8")

    app_path = tmp_path / "app"
    app_path.mkdir(parents=True, exist_ok=True)
    (app_path / "pyproject.toml").write_text("[project]\nname='app'\n", encoding="utf-8")
    (app_path / ".venv").mkdir(parents=True, exist_ok=True)
    (app_path / "uv.lock").write_text("lock", encoding="utf-8")
    manager_resources = app_path / "agilab/core/agi-env/src/agi_env/resources"
    manager_resources.mkdir(parents=True, exist_ok=True)
    (manager_resources / "old.txt").write_text("old", encoding="utf-8")

    wenv_abs = tmp_path / "wenv"
    wenv_abs.mkdir(parents=True, exist_ok=True)
    (wenv_abs / "pyproject.toml").write_text("[project]\nname='worker'\n", encoding="utf-8")
    (wenv_abs / ".venv" / "lib" / "python3.13t" / "site-packages").mkdir(parents=True, exist_ok=True)
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
    (cluster_pck / "agi_distributor" / "cli.py").write_text("print('cli')", encoding="utf-8")

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

    monkeypatch.setattr(deployment_local_support.AgiEnv, "read_agilab_path", staticmethod(lambda: repo_root))
    monkeypatch.setattr(
        deployment_local_support,
        "pkg_version",
        lambda name: (_ for _ in ()).throw(deployment_local_support.PackageNotFoundError(name))
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
    assert (resources_dest / "resource.txt").exists()
    assert (
        wenv_abs / ".venv" / "lib" / "python3.13t" / "site-packages" / "agilab_uv_sources.pth"
    ).exists()
    log.debug.assert_called()


@pytest.mark.asyncio
async def test_deploy_local_worker_source_env_missing_agi_env_wheel_raises(tmp_path):
    app_path = tmp_path / "app"
    app_path.mkdir(parents=True, exist_ok=True)
    (app_path / "pyproject.toml").write_text("[project]\nname='app'\n", encoding="utf-8")
    wenv_abs = tmp_path / "wenv"
    wenv_abs.mkdir(parents=True, exist_ok=True)
    (wenv_abs / "pyproject.toml").write_text("[project]\nname='worker'\n", encoding="utf-8")
    agi_env = tmp_path / "agi_env"
    agi_node = tmp_path / "agi_node"
    agi_cluster = tmp_path / "agi_cluster"
    for project in (agi_env, agi_node, agi_cluster):
        (project / "dist").mkdir(parents=True, exist_ok=True)
    (agi_node / "dist" / "agi_node-0.0.1-py3-none-any.whl").write_text("whl", encoding="utf-8")

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
    (app_path / "pyproject.toml").write_text("[project]\nname='app'\n", encoding="utf-8")
    wenv_abs = tmp_path / "wenv"
    wenv_abs.mkdir(parents=True, exist_ok=True)
    (wenv_abs / "pyproject.toml").write_text("[project]\nname='worker'\n", encoding="utf-8")
    agi_env = tmp_path / "agi_env"
    agi_node = tmp_path / "agi_node"
    agi_cluster = tmp_path / "agi_cluster"
    for project in (agi_env, agi_node, agi_cluster):
        (project / "dist").mkdir(parents=True, exist_ok=True)
    (agi_env / "dist" / "agi_env-0.0.1-py3-none-any.whl").write_text("whl", encoding="utf-8")

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
async def test_deploy_local_worker_handles_archive_copy_edge_cases_and_missing_cli(tmp_path, monkeypatch):
    app_path = tmp_path / "app"
    active_src = app_path / "src"
    active_src.mkdir(parents=True, exist_ok=True)
    archive = active_src / "Trajectory.7z"
    archive.write_text("traj", encoding="utf-8")
    (app_path / "pyproject.toml").write_text("[project]\nname='demo-app'\n", encoding="utf-8")

    agi_env_root = tmp_path / "agi_env"
    (agi_env_root / "src" / "agi_env" / "resources").mkdir(parents=True, exist_ok=True)
    (agi_env_root / "src" / "agi_env" / "resources" / "sample.txt").write_text("x", encoding="utf-8")
    agi_node_root = tmp_path / "agi_node"
    agi_node_root.mkdir(parents=True, exist_ok=True)

    wenv_abs = tmp_path / "worker_env"
    wenv_abs.mkdir(parents=True, exist_ok=True)
    (wenv_abs / "pyproject.toml").write_text("[project]\nname='worker-app'\n", encoding="utf-8")

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
async def test_deploy_local_worker_handles_shallow_repo_root_and_rglob_oserror(tmp_path, monkeypatch):
    app_path = tmp_path / "app"
    active_src = app_path / "src"
    active_src.mkdir(parents=True, exist_ok=True)
    (app_path / "pyproject.toml").write_text("[project]\nname='demo-app'\n", encoding="utf-8")

    agi_env_root = tmp_path / "agi_env"
    (agi_env_root / "src" / "agi_env" / "resources").mkdir(parents=True, exist_ok=True)
    (agi_env_root / "src" / "agi_env" / "resources" / "sample.txt").write_text("x", encoding="utf-8")
    agi_node_root = tmp_path / "agi_node"
    agi_node_root.mkdir(parents=True, exist_ok=True)

    cluster_pck = tmp_path / "cluster_pck"
    (cluster_pck / "agi_distributor").mkdir(parents=True, exist_ok=True)
    (cluster_pck / "agi_distributor" / "cli.py").write_text("print('cli')", encoding="utf-8")

    wenv_abs = tmp_path / "worker_env"
    wenv_abs.mkdir(parents=True, exist_ok=True)
    (wenv_abs / "pyproject.toml").write_text("[project]\nname='worker-app'\n", encoding="utf-8")

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

    monkeypatch.setattr(deployment_local_support.AgiEnv, "read_agilab_path", staticmethod(lambda: Path("/repo")))
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
    (app_path / "pyproject.toml").write_text("[project]\nname='demo-app'\n", encoding="utf-8")

    agi_env_root = tmp_path / "agi_env"
    (agi_env_root / "src" / "agi_env" / "resources").mkdir(parents=True, exist_ok=True)
    (agi_env_root / "src" / "agi_env" / "resources" / "sample.txt").write_text("x", encoding="utf-8")
    agi_node_root = tmp_path / "agi_node"
    agi_node_root.mkdir(parents=True, exist_ok=True)

    cluster_pck = tmp_path / "cluster_pck"
    (cluster_pck / "agi_distributor").mkdir(parents=True, exist_ok=True)
    (cluster_pck / "agi_distributor" / "cli.py").write_text("print('cli')", encoding="utf-8")

    wenv_abs = tmp_path / "worker_env"
    wenv_abs.mkdir(parents=True, exist_ok=True)
    (wenv_abs / "pyproject.toml").write_text("[project]\nname='worker-app'\n", encoding="utf-8")

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
async def test_deploy_local_worker_sorts_trajectory_archives_before_copy(tmp_path, monkeypatch):
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
    (app_path / "pyproject.toml").write_text("[project]\nname='demo-app'\n", encoding="utf-8")

    agi_env_root = tmp_path / "agi_env"
    (agi_env_root / "src" / "agi_env" / "resources").mkdir(parents=True, exist_ok=True)
    (agi_env_root / "src" / "agi_env" / "resources" / "sample.txt").write_text("x", encoding="utf-8")
    agi_node_root = tmp_path / "agi_node"
    agi_node_root.mkdir(parents=True, exist_ok=True)
    cluster_pck = tmp_path / "cluster_pck"
    (cluster_pck / "agi_distributor").mkdir(parents=True, exist_ok=True)
    (cluster_pck / "agi_distributor" / "cli.py").write_text("print('cli')", encoding="utf-8")
    wenv_abs = tmp_path / "worker_env"
    wenv_abs.mkdir(parents=True, exist_ok=True)
    (wenv_abs / "pyproject.toml").write_text("[project]\nname='worker-app'\n", encoding="utf-8")

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
