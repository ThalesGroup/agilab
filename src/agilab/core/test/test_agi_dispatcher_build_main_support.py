from __future__ import annotations

from pathlib import Path

import pytest

from agi_node.agi_dispatcher import build as build_mod
import agi_node.agi_dispatcher.bootstrap_source_paths as bootstrap_mod


def test_bootstrap_core_source_paths_prefers_repo_layout(tmp_path, monkeypatch):
    source_file = (
        tmp_path
        / "repo"
        / "src"
        / "agilab"
        / "core"
        / "agi-node"
        / "src"
        / "agi_node"
        / "agi_dispatcher"
        / "build.py"
    )
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text("", encoding="utf-8")

    core_root = source_file.parents[4]
    env_src = core_root / "agi-env" / "src"
    node_src = core_root / "agi-node" / "src"
    cluster_src = core_root / "agi-cluster" / "src"
    for path in (env_src, node_src, cluster_src):
        path.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(bootstrap_mod.sys, "path", [], raising=False)
    added = bootstrap_mod.bootstrap_core_source_paths(source_file=source_file)

    assert added == (env_src, node_src, cluster_src)
    assert bootstrap_mod.sys.path[:3] == [str(env_src), str(node_src), str(cluster_src)]


def test_bootstrap_core_source_paths_moves_existing_editable_sources_before_site_packages(
    tmp_path,
    monkeypatch,
):
    source_file = (
        tmp_path
        / "repo"
        / "src"
        / "agilab"
        / "core"
        / "agi-node"
        / "src"
        / "agi_node"
        / "agi_dispatcher"
        / "build.py"
    )
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text("", encoding="utf-8")

    core_root = source_file.parents[4]
    env_src = core_root / "agi-env" / "src"
    node_src = core_root / "agi-node" / "src"
    cluster_src = core_root / "agi-cluster" / "src"
    site_packages = tmp_path / "app" / ".venv" / "lib" / "python3.13" / "site-packages"
    for path in (env_src, node_src, cluster_src, site_packages):
        path.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        bootstrap_mod.sys,
        "path",
        [str(site_packages), str(env_src), str(node_src), str(cluster_src)],
        raising=False,
    )

    added = bootstrap_mod.bootstrap_core_source_paths(source_file=source_file)

    assert added == (env_src, node_src, cluster_src)
    assert bootstrap_mod.sys.path[:3] == [str(env_src), str(node_src), str(cluster_src)]
    assert bootstrap_mod.sys.path[3] == str(site_packages)
    assert bootstrap_mod.sys.path.count(str(env_src)) == 1


def test_resolve_main_inputs_uses_explicit_app_path_and_normalizes_windows_style_outdirs(tmp_path):
    app_dir = tmp_path / "demo_project"
    app_dir.mkdir(parents=True, exist_ok=True)
    chdir_calls = []

    prog_name, active_app, opts, quiet, cmd, packages, raw_outdir = build_mod._resolve_main_inputs(
        [
            "--app-path",
            str(app_dir),
            "build_ext",
            "-b",
            "C:exports\\demo_worker",
            "--packages",
            "pkg_a,pkg_b",
            "--quiet",
        ],
        argv0="build.py",
        chdir_fn=lambda path: chdir_calls.append(path),
    )

    assert prog_name == "build.py"
    assert active_app == app_dir.resolve()
    assert chdir_calls == [app_dir.resolve()]
    assert cmd == "build_ext"
    assert quiet is True
    assert packages == ["pkg_a", "pkg_b"]
    assert str(opts.build_dir) == build_mod._fix_windows_drive("C:exports\\demo_worker")
    assert raw_outdir == opts.build_dir


def test_resolve_main_inputs_defaults_to_script_dir_for_bdist_egg(tmp_path):
    script_dir = tmp_path / "scripts"
    script_dir.mkdir(parents=True, exist_ok=True)
    chdir_calls = []

    prog_name, active_app, opts, quiet, cmd, packages, raw_outdir = build_mod._resolve_main_inputs(
        [
            "bdist_egg",
            "-d",
            str(tmp_path / "dist-out"),
            "--packages",
            "agi_env.tools",
        ],
        file_path=script_dir / "build.py",
        argv0="build.py",
        chdir_fn=lambda path: chdir_calls.append(path),
    )

    assert prog_name == "build.py"
    assert active_app == script_dir.resolve()
    assert chdir_calls == [script_dir.resolve()]
    assert cmd == "bdist_egg"
    assert quiet is False
    assert packages == ["agi_env.tools"]
    assert Path(opts.dist_dir) == tmp_path / "dist-out"
    assert raw_outdir == opts.dist_dir


def test_prepare_main_execution_orchestrates_build_ext_runtime(tmp_path):
    active_app = tmp_path / "demo_project"
    active_app.mkdir(parents=True, exist_ok=True)
    build_env_inits = []
    preflight_calls = []
    argv_calls = []
    artifact_calls = []

    class DummyEnv:
        def __init__(self, *, active_app, verbose):
            build_env_inits.append((active_app, verbose))
            self.home_abs = str(tmp_path / "home")
            self.pyvers_worker = "3.13t"
            self.active_app = active_app
            self.is_worker_env = False

    env, out_arg, worker_module, ext_modules, links_created = build_mod._prepare_main_execution(
        prog_name="build.py",
        active_app=active_app,
        quiet=False,
        cmd="build_ext",
        raw_outdir=str(tmp_path / "exports" / "demo_worker"),
        build_dir=str(tmp_path / "exports" / "demo_worker"),
        remaining_args=["--quiet"],
        packages=["pkg_a"],
        build_env_cls=DummyEnv,
        resolve_build_output_fn=lambda outdir, home_abs: (Path(outdir), "exports/demo_worker", "demo_worker"),
        prepare_build_ext_command_fn=lambda **kwargs: preflight_calls.append(kwargs),
        build_setuptools_argv_fn=lambda **kwargs: ["build.py", "build_ext", "-b", Path(kwargs["home_abs"]) / "exports/demo_worker" / "dist"],
        prepare_setup_artifacts_fn=lambda **kwargs: (artifact_calls.append(kwargs) or (["ext_mod"], [tmp_path / "pkg_a"])),
        set_argv_fn=lambda argv: argv_calls.append(argv),
    )

    assert build_env_inits == [(active_app, 2)]
    assert preflight_calls == [{"env": env, "build_dir": str(tmp_path / "exports" / "demo_worker")}]
    assert argv_calls == [["build.py", "build_ext", "-b", tmp_path / "home" / "exports/demo_worker" / "dist"]]
    assert out_arg == "exports/demo_worker"
    assert worker_module == "demo_worker_worker"
    assert ext_modules == ["ext_mod"]
    assert links_created == [tmp_path / "pkg_a"]
    assert artifact_calls == [
        {
            "env": env,
            "cmd": "build_ext",
            "active_app": active_app,
            "build_dir": str(tmp_path / "exports" / "demo_worker"),
            "remaining_args": ["--quiet"],
            "packages": ["pkg_a"],
            "worker_module": "demo_worker_worker",
        }
    ]


def test_prepare_main_execution_skips_build_ext_preflight_for_bdist_egg(tmp_path):
    active_app = tmp_path / "demo_project"
    active_app.mkdir(parents=True, exist_ok=True)
    preflight_calls = []
    argv_calls = []

    class DummyEnv:
        def __init__(self, *, active_app, verbose):
            self.home_abs = str(tmp_path / "home")
            self.pyvers_worker = "3.13"
            self.active_app = active_app
            self.is_worker_env = False

    env, out_arg, worker_module, ext_modules, links_created = build_mod._prepare_main_execution(
        prog_name="build.py",
        active_app=active_app,
        quiet=True,
        cmd="bdist_egg",
        raw_outdir=str(tmp_path / "dist-out"),
        build_dir=str(tmp_path / "unused-build-dir"),
        remaining_args=[],
        packages=["agi_env.tools"],
        build_env_cls=DummyEnv,
        resolve_build_output_fn=lambda outdir, home_abs: (Path(outdir), "dist-out", "demo"),
        prepare_build_ext_command_fn=lambda **kwargs: preflight_calls.append(kwargs),
        build_setuptools_argv_fn=lambda **kwargs: ["build.py", "bdist_egg", "-d", Path(kwargs["home_abs"]) / "dist-out" / "dist"],
        prepare_setup_artifacts_fn=lambda **kwargs: ([], [tmp_path / "pkg_link"]),
        set_argv_fn=lambda argv: argv_calls.append(argv),
    )

    assert preflight_calls == []
    assert argv_calls == [["build.py", "bdist_egg", "-d", tmp_path / "home" / "dist-out" / "dist"]]
    assert out_arg == "dist-out"
    assert worker_module == "demo_worker"
    assert ext_modules == []
    assert links_created == [tmp_path / "pkg_link"]


def test_execute_main_setup_orchestrates_readme_setup_and_finalize(tmp_path):
    env = object()
    call_order = []
    setup_kwargs_calls = []
    setup_calls = []
    finalize_calls = []

    build_mod._execute_main_setup(
        env=env,
        cmd="bdist_egg",
        out_arg="exports/demo_worker",
        worker_module="demo_worker",
        ext_modules=["ext_mod"],
        links_created=[tmp_path / "pkg_link"],
        ensure_build_readme_fn=lambda: call_order.append("readme"),
        build_setup_kwargs_fn=lambda **kwargs: (
            call_order.append("kwargs") or setup_kwargs_calls.append(kwargs) or {"name": "demo_worker", "ext_modules": ["ext_mod"]}
        ),
        setup_fn=lambda **kwargs: call_order.append("setup") or setup_calls.append(kwargs),
        finalize_setup_artifacts_fn=lambda **kwargs: call_order.append("finalize") or finalize_calls.append(kwargs),
    )

    assert call_order == ["readme", "kwargs", "setup", "finalize"]
    assert setup_kwargs_calls == [{"worker_module": "demo_worker", "ext_modules": ["ext_mod"]}]
    assert setup_calls == [{"name": "demo_worker", "ext_modules": ["ext_mod"]}]
    assert finalize_calls == [
        {
            "env": env,
            "cmd": "bdist_egg",
            "out_arg": "exports/demo_worker",
            "links_created": [tmp_path / "pkg_link"],
        }
    ]
