"""Tests for the per-project [tool.agilab.cython] config channel (plan items 10/12)."""

import asyncio
import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from agi_env.cython_build_config import (
    CYTHON_DIRECTIVES_ENV,
    parse_cython_directive_overrides,
    read_project_cython_config,
    resolve_cython_directives_spec,
    validate_cython_directives_spec,
)
from agi_cluster.agi_distributor import deployment_remote_support, uv_source_support
import agi_cluster.agi_distributor.deployment_build_support as deployment_build_support
from agi_node.agi_dispatcher import build as build_mod


REPO_ROOT = Path(__file__).resolve().parents[4]
INSTALLER_PATH = REPO_ROOT / "src" / "agilab" / "apps" / "install.py"


def _write_pyproject(project_dir: Path, body: str) -> Path:
    project_dir.mkdir(parents=True, exist_ok=True)
    pyproject = project_dir / "pyproject.toml"
    pyproject.write_text(body, encoding="utf-8")
    return pyproject


# ---------------------------------------------------------------------------
# Project config reader
# ---------------------------------------------------------------------------


def test_read_project_cython_config_missing_pyproject_means_undeclared(tmp_path):
    config = read_project_cython_config(tmp_path / "absent_project")

    assert config.enabled is None
    assert config.directives is None
    assert config.pyproject_path is None
    assert read_project_cython_config(None) == (None, None, None)


def test_read_project_cython_config_reads_enabled_and_directives(tmp_path):
    pyproject = _write_pyproject(
        tmp_path / "app",
        "[project]\nname='demo'\n\n[tool.agilab.cython]\n"
        "enabled = false\ndirectives = 'unchecked,cdivision=true'\n",
    )

    config = read_project_cython_config(tmp_path / "app")

    assert config.enabled is False
    assert config.directives == "unchecked,cdivision=true"
    assert config.pyproject_path == pyproject


def test_read_project_cython_config_rejects_bad_types_naming_file(tmp_path):
    pyproject = _write_pyproject(
        tmp_path / "app",
        "[tool.agilab.cython]\nenabled = 'yes'\n",
    )
    with pytest.raises(ValueError, match=r"enabled must be a boolean"):
        read_project_cython_config(tmp_path / "app")
    with pytest.raises(ValueError, match=str(pyproject).replace("\\", "\\\\")):
        read_project_cython_config(tmp_path / "app")

    _write_pyproject(tmp_path / "app2", "[tool.agilab.cython]\ndirectives = true\n")
    with pytest.raises(ValueError, match=r"directives must be a string"):
        read_project_cython_config(tmp_path / "app2")


def test_read_project_cython_config_rejects_unknown_keys_naming_file(tmp_path):
    pyproject = _write_pyproject(
        tmp_path / "app",
        "[tool.agilab.cython]\nenable = true\n",
    )

    with pytest.raises(ValueError) as excinfo:
        read_project_cython_config(tmp_path / "app")

    assert "enable" in str(excinfo.value)
    assert str(pyproject) in str(excinfo.value)


def test_read_project_cython_config_rejects_invalid_toml_naming_file(tmp_path):
    pyproject = _write_pyproject(tmp_path / "app", "not toml [\n")

    with pytest.raises(ValueError, match="Invalid TOML") as excinfo:
        read_project_cython_config(tmp_path / "app")

    assert str(pyproject) in str(excinfo.value)


# ---------------------------------------------------------------------------
# Spec resolution precedence: env var > project pyproject > framework default
# ---------------------------------------------------------------------------


def test_resolve_directives_spec_env_beats_pyproject_beats_default(tmp_path):
    project = tmp_path / "app"
    _write_pyproject(project, "[tool.agilab.cython]\ndirectives = 'unchecked'\n")

    spec, source = resolve_cython_directives_spec(
        environ={CYTHON_DIRECTIVES_ENV: "cdivision=true"},
        project_dir=project,
    )
    assert (spec, source) == ("cdivision=true", CYTHON_DIRECTIVES_ENV)

    spec, source = resolve_cython_directives_spec(environ={}, project_dir=project)
    assert spec == "unchecked"
    assert source == str(project / "pyproject.toml")

    spec, source = resolve_cython_directives_spec(
        environ={}, project_dir=tmp_path / "undeclared"
    )
    assert (spec, source) == (None, None)


def test_resolve_directives_spec_accepts_prefetched_env_value(tmp_path):
    project = tmp_path / "app"
    _write_pyproject(project, "[tool.agilab.cython]\ndirectives = 'unchecked'\n")

    spec, source = resolve_cython_directives_spec(env_value="off", project_dir=project)

    assert (spec, source) == ("off", CYTHON_DIRECTIVES_ENV)


def test_parse_and_validate_spec_name_their_source():
    with pytest.raises(ValueError, match=r"boundschek.*demo/pyproject.toml"):
        parse_cython_directive_overrides(
            "boundschek=false", source="demo/pyproject.toml"
        )
    # 'off' is a legacy opt-out, not a directive list; it must validate.
    validate_cython_directives_spec("off", source="demo/pyproject.toml")
    with pytest.raises(ValueError, match="Unknown Cython compiler directive"):
        validate_cython_directives_spec("nochecks", source="demo/pyproject.toml")


# ---------------------------------------------------------------------------
# build.py resolution against the project pyproject
# ---------------------------------------------------------------------------


def test_build_resolves_project_directives_with_env_precedence(tmp_path):
    project = tmp_path / "app"
    _write_pyproject(project, "[tool.agilab.cython]\ndirectives = 'cdivision=true'\n")

    directives = build_mod._resolve_cython_compiler_directives(
        pyvers_worker="3.13",
        environ={},
        project_dir=project,
    )
    assert directives["cdivision"] is True
    # Framework safe defaults stay applied underneath project overrides.
    assert directives["boundscheck"] is False
    assert directives["embedsignature"] is True

    directives = build_mod._resolve_cython_compiler_directives(
        pyvers_worker="3.13",
        environ={CYTHON_DIRECTIVES_ENV: "boundscheck=true"},
        project_dir=project,
    )
    assert directives["boundscheck"] is True
    assert "cdivision" not in directives


def test_build_project_off_spec_drops_framework_defaults(tmp_path):
    project = tmp_path / "app"
    _write_pyproject(project, "[tool.agilab.cython]\ndirectives = 'off'\n")

    assert (
        build_mod._resolve_cython_compiler_directives(
            pyvers_worker="3.13",
            environ={},
            project_dir=project,
        )
        == {}
    )


def test_build_unknown_project_directive_errors_with_pyproject_path(tmp_path):
    project = tmp_path / "app"
    pyproject = _write_pyproject(
        project, "[tool.agilab.cython]\ndirectives = 'boundschek=false'\n"
    )

    with pytest.raises(ValueError) as excinfo:
        build_mod._resolve_cython_compiler_directives(
            pyvers_worker="3.13",
            environ={},
            project_dir=project,
        )

    assert "Unknown Cython compiler directive" in str(excinfo.value)
    assert str(pyproject) in str(excinfo.value)


def test_build_ext_compile_config_threads_project_dir(tmp_path):
    project = tmp_path / "app"
    _write_pyproject(project, "[tool.agilab.cython]\ndirectives = 'unchecked'\n")

    _, _, directives = build_mod._build_ext_compile_config(
        sys_platform="linux",
        pyvers_worker="3.13",
        environ={},
        project_dir=project,
    )

    assert directives["boundscheck"] is False
    assert directives["nonecheck"] is False


# ---------------------------------------------------------------------------
# --compiler-directives argv override in build.py main()
# ---------------------------------------------------------------------------


def test_resolve_main_inputs_compiler_directives_argv_overrides_env(tmp_path, monkeypatch):
    app_dir = tmp_path / "demo_project"
    app_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv(CYTHON_DIRECTIVES_ENV, "unchecked")

    build_mod._resolve_main_inputs(
        [
            "--app-path",
            str(app_dir),
            "--compiler-directives",
            "cdivision=true",
            "build_ext",
            "-b",
            str(tmp_path / "out"),
        ],
        chdir_fn=lambda _path: None,
    )

    assert os.environ[CYTHON_DIRECTIVES_ENV] == "cdivision=true"
    # The override wins the env slot, so every later resolution sees it.
    directives = build_mod._resolve_cython_compiler_directives(
        pyvers_worker="3.13",
        project_dir=app_dir,
    )
    assert directives["cdivision"] is True


def test_resolve_main_inputs_rejects_bad_compiler_directives_eagerly(tmp_path, monkeypatch):
    app_dir = tmp_path / "demo_project"
    app_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv(CYTHON_DIRECTIVES_ENV, "")

    with pytest.raises(ValueError, match=r"boundschek.*--compiler-directives"):
        build_mod._resolve_main_inputs(
            [
                "--app-path",
                str(app_dir),
                "--compiler-directives",
                "boundschek=false",
                "build_ext",
                "-b",
                str(tmp_path / "out"),
            ],
            chdir_fn=lambda _path: None,
        )


# ---------------------------------------------------------------------------
# Deployment propagation: local command, cache payload, remote command
# ---------------------------------------------------------------------------


def test_build_ext_command_appends_resolved_directives():
    cmd = deployment_build_support._build_ext_command(
        uv="uv",
        module_cmd="python -m agi_node.agi_dispatcher.build",
        app_path_arg='"/apps/demo_project"',
        wenv_arg='"/wenv/demo_worker"',
        verbose=0,
        compiler_directives_spec="unchecked,cdivision=true",
    )

    # shlex.quote leaves comma/equals specs bare; they are shell-safe.
    assert "--compiler-directives unchecked,cdivision=true " in cmd
    assert cmd.index("--compiler-directives") < cmd.index("build_ext")

    bare = deployment_build_support._build_ext_command(
        uv="uv",
        module_cmd="python -m agi_node.agi_dispatcher.build",
        app_path_arg='"/apps/demo_project"',
        wenv_arg='"/wenv/demo_worker"',
        verbose=0,
    )
    assert "--compiler-directives" not in bare


def test_resolved_cython_directives_spec_prefers_envars_then_pyproject(tmp_path, monkeypatch):
    monkeypatch.delenv(CYTHON_DIRECTIVES_ENV, raising=False)
    project = tmp_path / "app"
    _write_pyproject(project, "[tool.agilab.cython]\ndirectives = 'unchecked'\n")
    env = SimpleNamespace(envars={}, active_app=project)

    assert deployment_build_support._resolved_cython_directives_spec(env) == "unchecked"

    env.envars = {CYTHON_DIRECTIVES_ENV: "cdivision=true"}
    assert (
        deployment_build_support._resolved_cython_directives_spec(env)
        == "cdivision=true"
    )

    bare_env = SimpleNamespace(envars={}, active_app=tmp_path / "undeclared")
    assert deployment_build_support._resolved_cython_directives_spec(bare_env) is None


def test_resolved_cython_directives_spec_rejects_bad_project_spec(tmp_path, monkeypatch):
    monkeypatch.delenv(CYTHON_DIRECTIVES_ENV, raising=False)
    project = tmp_path / "app"
    pyproject = _write_pyproject(
        project, "[tool.agilab.cython]\ndirectives = 'boundschek=false'\n"
    )
    env = SimpleNamespace(envars={}, active_app=project)

    with pytest.raises(ValueError) as excinfo:
        deployment_build_support._resolved_cython_directives_spec(env)

    assert str(pyproject) in str(excinfo.value)


def test_worker_build_cache_payload_includes_resolved_directives(tmp_path, monkeypatch):
    monkeypatch.delenv(CYTHON_DIRECTIVES_ENV, raising=False)
    app_path = tmp_path / "app"
    app_src = app_path / "src" / "demo_worker"
    app_src.mkdir(parents=True, exist_ok=True)
    (app_src / "demo_worker.py").write_text("VALUE = 1\n", encoding="utf-8")
    _write_pyproject(app_path, "[tool.agilab.cython]\ndirectives = 'unchecked'\n")
    worker_pyproject = tmp_path / "worker_pyproject.toml"
    worker_pyproject.write_text("[project]\nname='worker'\n", encoding="utf-8")
    env = SimpleNamespace(
        active_app=app_path,
        envars={},
        worker_pyproject=worker_pyproject,
        manager_pyproject=worker_pyproject,
        uvproject=tmp_path / "uv.toml",
        base_worker_cls="PandasWorker",
        pyvers_worker="3.13",
    )

    payload = deployment_build_support._worker_build_cache_payload(
        env=env,
        packages="agi_dispatcher, pandas_worker",
        worker_group="pandas-worker",
        is_cy=True,
        module_cmd="python -m build",
        core_install_commands=[],
    )

    assert payload["cython_directives_resolved"] == "unchecked"


def _remote_deploy_env(tmp_path, *, active_app=None):
    dist_abs = tmp_path / "dist"
    dist_abs.mkdir(parents=True, exist_ok=True)
    (dist_abs / "demo_worker-0.0.1.egg").write_text("x", encoding="utf-8")
    return SimpleNamespace(
        wenv_abs=tmp_path / "worker_env",
        wenv_rel=Path("worker_env"),
        dist_rel=Path("worker_env/dist"),
        dist_abs=dist_abs,
        pyvers_worker="3.13",
        envars={},
        uv_worker="uv",
        is_source_env=False,
        app="demo_app",
        target_worker="demo_worker",
        post_install_rel="demo.post_install",
        verbose=0,
        **({"active_app": active_app} if active_app is not None else {}),
    )


def _remote_deploy_agi_cls(ssh_calls, *, mode):
    async def _fake_exec_ssh(_ip, cmd):
        ssh_calls.append(cmd)
        return "ok"

    async def _fake_send(_env, _ip, _files, _remote_path, user=None, password=None):
        del user, password

    async def _fake_send_file(
        _env, _ip, _local_path, _remote_path, user=None, password=None
    ):
        del user, password

    return SimpleNamespace(
        _mode=mode,
        CYTHON_MODE=2,
        DASK_MODE=4,
        _rapids_enabled=False,
        _workers_data_path=None,
        exec_ssh=_fake_exec_ssh,
        send_files=_fake_send,
        send_file=_fake_send_file,
    )


async def _run_deploy_remote_worker(agi_cls, env):
    await deployment_remote_support.deploy_remote_worker(
        agi_cls,
        "10.0.0.2",
        env,
        worker_site_packages_dir_fn=uv_source_support.worker_site_packages_dir,
        staged_uv_sources_pth_content_fn=uv_source_support.staged_uv_sources_pth_content,
        set_env_var_fn=lambda *_a, **_k: None,
        log=deployment_remote_support.logger,
    )


@pytest.mark.asyncio
async def test_remote_build_command_carries_resolved_project_directives(
    tmp_path, monkeypatch
):
    monkeypatch.delenv(CYTHON_DIRECTIVES_ENV, raising=False)
    project = tmp_path / "app"
    _write_pyproject(project, "[tool.agilab.cython]\ndirectives = 'unchecked'\n")
    env = _remote_deploy_env(tmp_path, active_app=project)
    ssh_calls: list[str] = []
    agi_cls = _remote_deploy_agi_cls(ssh_calls, mode=2)

    await _run_deploy_remote_worker(agi_cls, env)

    build_commands = [
        cmd
        for cmd in ssh_calls
        if "agi_node.agi_dispatcher.build" in cmd and "build_ext" in cmd
    ]
    assert len(build_commands) == 1
    assert "--compiler-directives unchecked" in build_commands[0]


@pytest.mark.asyncio
async def test_remote_build_ext_skipped_when_cython_bit_unset(tmp_path, monkeypatch):
    monkeypatch.delenv(CYTHON_DIRECTIVES_ENV, raising=False)
    env = _remote_deploy_env(tmp_path)
    ssh_calls: list[str] = []
    agi_cls = _remote_deploy_agi_cls(ssh_calls, mode=4)

    await _run_deploy_remote_worker(agi_cls, env)

    assert not any(
        "agi_node.agi_dispatcher.build" in cmd and "build_ext" in cmd
        for cmd in ssh_calls
    )
    # The rest of the deployment still runs.
    assert any("python -m demo.post_install" in cmd for cmd in ssh_calls)
    assert any("threaded" in cmd for cmd in ssh_calls)


# ---------------------------------------------------------------------------
# install.py: CYTHON_MODE composition (plan item 12)
# ---------------------------------------------------------------------------


def _load_installer(monkeypatch, app_path: Path):
    module_name = "agilab_cython_config_installer_test_module"
    sys.modules.pop(module_name, None)
    app_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(sys, "argv", ["install.py", str(app_path)])
    spec = importlib.util.spec_from_file_location(module_name, INSTALLER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_install_resolve_cython_mode_precedence(tmp_path, monkeypatch):
    installer = _load_installer(monkeypatch, tmp_path / "demo_project")

    # Default (nothing declared anywhere): preserved always-cython behavior.
    bare = tmp_path / "bare_project"
    bare.mkdir()
    assert installer.resolve_cython_mode_enabled(bare) is True

    # app_settings [cluster].cython is honored when the pyproject is silent.
    settings_app = tmp_path / "settings_project"
    (settings_app / "src").mkdir(parents=True)
    (settings_app / "src" / "app_settings.toml").write_text(
        "[cluster]\ncython = false\n", encoding="utf-8"
    )
    assert installer.resolve_cython_mode_enabled(settings_app) is False

    # Project pyproject beats app_settings.
    project_app = tmp_path / "project_project"
    (project_app / "src").mkdir(parents=True)
    (project_app / "src" / "app_settings.toml").write_text(
        "[cluster]\ncython = false\n", encoding="utf-8"
    )
    _write_pyproject(project_app, "[tool.agilab.cython]\nenabled = true\n")
    assert installer.resolve_cython_mode_enabled(project_app) is True

    # CLI override beats everything.
    assert (
        installer.resolve_cython_mode_enabled(project_app, cli_override=False) is False
    )
    disabled_app = tmp_path / "disabled_project"
    _write_pyproject(disabled_app, "[tool.agilab.cython]\nenabled = false\n")
    assert installer.resolve_cython_mode_enabled(disabled_app) is False
    assert (
        installer.resolve_cython_mode_enabled(disabled_app, cli_override=True) is True
    )


def _run_installer_main(monkeypatch, installer, app_path: Path, *, extra_argv=()):
    captured: dict[str, object] = {}

    class FakeAGI:
        DASK_MODE = 4
        CYTHON_MODE = 2

        @staticmethod
        async def install(**kwargs):
            captured.update(kwargs)

    env = SimpleNamespace(
        active_app=app_path,
        wenv_abs=app_path / "wenv",
        user="",
    )
    monkeypatch.setattr(sys, "argv", ["install.py", str(app_path), *extra_argv])
    monkeypatch.setattr(installer, "AgiEnv", lambda **_kwargs: env)
    monkeypatch.setattr(installer, "AGI", FakeAGI)
    monkeypatch.setattr(installer, "ensure_data_storage", lambda _env: None)
    monkeypatch.setattr(installer, "validate_app_definition", lambda _env: None)
    monkeypatch.setattr(
        installer, "_install_state_matches", lambda *_a, **_k: (False, "test miss")
    )
    monkeypatch.setattr(installer, "_write_install_state", lambda *_a, **_k: None)

    assert asyncio.run(installer.main()) == 0
    return captured


def test_install_main_modes_composition_per_source(tmp_path, monkeypatch):
    installer = _load_installer(monkeypatch, tmp_path / "demo_project")

    # Default: nothing declared -> DASK | CYTHON (today's behavior).
    default_app = tmp_path / "default_project"
    default_app.mkdir()
    captured = _run_installer_main(monkeypatch, installer, default_app)
    assert captured["modes_enabled"] == 4 | 2

    # Project declares enabled = false -> cython bit dropped.
    declined_app = tmp_path / "declined_project"
    _write_pyproject(declined_app, "[tool.agilab.cython]\nenabled = false\n")
    captured = _run_installer_main(monkeypatch, installer, declined_app)
    assert captured["modes_enabled"] == 4

    # app_settings cluster.cython = false -> cython bit dropped.
    settings_app = tmp_path / "settings_project"
    (settings_app / "src").mkdir(parents=True)
    (settings_app / "src" / "app_settings.toml").write_text(
        "[cluster]\ncython = false\n", encoding="utf-8"
    )
    captured = _run_installer_main(monkeypatch, installer, settings_app)
    assert captured["modes_enabled"] == 4

    # CLI --with-cython overrides the project opt-out.
    captured = _run_installer_main(
        monkeypatch, installer, declined_app, extra_argv=["--with-cython"]
    )
    assert captured["modes_enabled"] == 4 | 2

    # CLI --no-cython overrides the default.
    captured = _run_installer_main(
        monkeypatch, installer, default_app, extra_argv=["--no-cython"]
    )
    assert captured["modes_enabled"] == 4


def test_install_main_reports_misdeclared_cython_table(tmp_path, monkeypatch, capsys):
    installer = _load_installer(monkeypatch, tmp_path / "demo_project")
    broken_app = tmp_path / "broken_project"
    _write_pyproject(broken_app, "[tool.agilab.cython]\nenabled = 'yes'\n")

    env = SimpleNamespace(active_app=broken_app, wenv_abs=broken_app / "wenv", user="")
    monkeypatch.setattr(sys, "argv", ["install.py", str(broken_app)])
    monkeypatch.setattr(installer, "AgiEnv", lambda **_kwargs: env)
    monkeypatch.setattr(installer, "ensure_data_storage", lambda _env: None)
    monkeypatch.setattr(installer, "validate_app_definition", lambda _env: None)

    assert asyncio.run(installer.main()) == 1
    assert "enabled must be a boolean" in capsys.readouterr().err
