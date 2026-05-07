from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from agi_cluster.agi_distributor import deployment_prepare_support, deployment_remote_support, uv_source_support


def _truthy(envars: dict, key: str) -> bool:
    return str(envars.get(key, "")).strip().lower() in {"1", "true", "yes", "on"}


def _build_local_env(
    tmp_path: Path,
    *,
    internet_on: str,
    is_worker_env: bool,
    uv: str = "uv",
    verbose: int = 1,
) -> SimpleNamespace:
    return SimpleNamespace(
        wenv_abs=tmp_path / "wenv_local",
        python_version="3.13",
        verbose=verbose,
        envars={"AGI_INTERNET_ON": internet_on},
        uv=uv,
        is_worker_env=is_worker_env,
        hw_rapids_capable=None,
    )


def _build_cluster_env(
    tmp_path: Path,
    *,
    internet_on: str = "1",
    verbose: int = 0,
) -> SimpleNamespace:
    cluster_pck = tmp_path / "cluster_pck"
    (cluster_pck / "agi_distributor").mkdir(parents=True, exist_ok=True)
    (cluster_pck / "agi_distributor" / "cli.py").write_text("print('cli')", encoding="utf-8")

    worker_pyproject = tmp_path / "worker_pyproject.toml"
    worker_pyproject.write_text("[project]\nname='demo-worker'\n", encoding="utf-8")
    manager_pyproject = tmp_path / "manager_pyproject.toml"
    manager_pyproject.write_text("[project]\nname='demo-manager'\n", encoding="utf-8")
    uvproject = tmp_path / "uv.toml"
    uvproject.write_text("[tool.uv]\n", encoding="utf-8")

    return SimpleNamespace(
        dist_rel=Path("wenv/dist"),
        wenv_rel=Path("wenv"),
        pyvers_worker="3.13",
        is_local=lambda ip: ip == "127.0.0.1",
        envars={"AGI_INTERNET_ON": internet_on},
        uv="uv",
        cluster_pck=cluster_pck,
        worker_pyproject=worker_pyproject,
        manager_pyproject=manager_pyproject,
        uvproject=uvproject,
        target_worker="demo_worker",
        verbose=verbose,
    )


def _build_agi(
    env: SimpleNamespace,
    *,
    workers: dict[str, int] | None = None,
    agi_workers: dict[str, str] | None = None,
    rapids_enabled: bool = True,
    supports_rapids=lambda: True,
) -> SimpleNamespace:
    return SimpleNamespace(
        env=env,
        _workers=workers or {"10.0.0.2": 1},
        agi_workers=agi_workers or {"pandas": "pandas-worker"},
        _rapids_enabled=rapids_enabled,
        _hardware_supports_rapids=supports_rapids,
        _get_scheduler=lambda _scheduler: ("127.0.0.1", 8786),
        _module_to_clean=[],
    )


def _recording_send(sent: list):
    async def _fake_send(_env, ip, files, remote_path, user=None, password=None):
        items = []
        for file_path in files:
            path = Path(file_path)
            item = {"name": path.name, "is_dir": path.is_dir()}
            if path.is_file():
                item["content"] = path.read_text(encoding="utf-8")
            elif path.is_dir():
                item["children"] = sorted(child.relative_to(path).as_posix() for child in path.rglob("*"))
            items.append(item)
        sent.append((ip, items, str(remote_path)))

    return _fake_send


@pytest.mark.asyncio
async def test_prepare_local_env_offline_worker_env_initializes_project(tmp_path):
    env = _build_local_env(tmp_path, internet_on="0", is_worker_env=True)
    agi_cls = _build_agi(env, supports_rapids=lambda: False)
    captured_set_env = []
    run_calls = []

    async def _fake_detect(_ip):
        return 'export PATH="$HOME/.local/bin:$PATH"; '

    async def _fake_run(cmd, cwd):
        run_calls.append((cmd, str(cwd)))
        return ""

    await deployment_prepare_support.prepare_local_env(
        agi_cls,
        envar_truthy_fn=_truthy,
        detect_export_cmd_fn=_fake_detect,
        set_env_var_fn=lambda *args: captured_set_env.append(args),
        run_fn=_fake_run,
        python_version_fn=lambda: "3.13.12",
        log=mock.Mock(),
    )

    assert env.wenv_abs.exists()
    assert any(entry[0] == "127.0.0.1_CMD_PREFIX" for entry in captured_set_env)
    assert any(entry[0] == "127.0.0.1_PYTHON_VERSION" for entry in captured_set_env)
    assert any("no_rapids_hw" in entry for entry in captured_set_env)
    assert len(run_calls) == 1
    assert "--project" in run_calls[0][0]
    assert "init --bare --no-workspace" in run_calls[0][0]


@pytest.mark.asyncio
async def test_prepare_local_env_online_handles_python_download_warning(tmp_path):
    env = _build_local_env(tmp_path, internet_on="1", is_worker_env=False)
    agi_cls = _build_agi(env, supports_rapids=lambda: True)
    run_calls = []

    async def _fake_detect(_ip):
        return ""

    async def _fake_run(cmd, _cwd):
        run_calls.append(cmd)
        if "python install" in cmd:
            raise RuntimeError("No download found for request")
        return ""

    await deployment_prepare_support.prepare_local_env(
        agi_cls,
        envar_truthy_fn=_truthy,
        detect_export_cmd_fn=_fake_detect,
        set_env_var_fn=lambda *_a, **_k: None,
        run_fn=_fake_run,
        python_version_fn=lambda: "3.13.12",
        log=mock.Mock(),
    )

    assert any("self update" in cmd for cmd in run_calls)
    assert any("python install 3.13" in cmd for cmd in run_calls)


@pytest.mark.asyncio
async def test_prepare_local_env_online_ignores_uv_self_update_failure(tmp_path):
    env = _build_local_env(tmp_path, internet_on="1", is_worker_env=False)
    agi_cls = _build_agi(env, supports_rapids=lambda: True)
    run_calls = []

    async def _fake_detect(_ip):
        return ""

    async def _fake_run(cmd, _cwd):
        run_calls.append(cmd)
        if "self update" in cmd:
            raise RuntimeError("Self-update is only available for standalone installs")
        return ""

    await deployment_prepare_support.prepare_local_env(
        agi_cls,
        envar_truthy_fn=_truthy,
        detect_export_cmd_fn=_fake_detect,
        set_env_var_fn=lambda *_a, **_k: None,
        run_fn=_fake_run,
        python_version_fn=lambda: "3.13.12",
        log=mock.Mock(),
    )

    assert any("self update" in cmd for cmd in run_calls)
    assert any("python install 3.13" in cmd for cmd in run_calls)


@pytest.mark.asyncio
async def test_prepare_local_env_windows_skips_self_update_when_standalone_uv_missing(monkeypatch, tmp_path):
    env = _build_local_env(tmp_path, internet_on="1", is_worker_env=False, uv="uv --quiet")
    agi_cls = _build_agi(env, supports_rapids=lambda: True)
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    run_calls = []
    log = mock.Mock()

    async def _fake_detect(_ip):
        return "set PATH=%USERPROFILE%\\\\.local\\\\bin;%PATH% && "

    async def _fake_run(cmd, _cwd):
        run_calls.append(cmd)
        return ""

    monkeypatch.setattr(deployment_prepare_support.os, "name", "nt", raising=False)
    monkeypatch.setattr(deployment_prepare_support.Path, "home", classmethod(lambda cls: fake_home))

    await deployment_prepare_support.prepare_local_env(
        agi_cls,
        envar_truthy_fn=_truthy,
        detect_export_cmd_fn=_fake_detect,
        set_env_var_fn=lambda *_a, **_k: None,
        run_fn=_fake_run,
        python_version_fn=lambda: "3.13.12",
        log=log,
    )

    standalone_uv = fake_home / ".local" / "bin" / "uv.exe"
    assert not any("self update" in cmd for cmd in run_calls)
    assert any("python install 3.13" in cmd for cmd in run_calls)
    assert any(str(standalone_uv) in str(call) for call in log.warning.call_args_list)


@pytest.mark.asyncio
async def test_prepare_local_env_windows_uses_standalone_uv_when_available(monkeypatch, tmp_path):
    env = _build_local_env(tmp_path, internet_on="1", is_worker_env=False, uv="uv --quiet")
    agi_cls = _build_agi(env, supports_rapids=lambda: True)
    fake_home = tmp_path / "home"
    standalone_uv = fake_home / ".local" / "bin" / "uv.exe"
    standalone_uv.parent.mkdir(parents=True, exist_ok=True)
    standalone_uv.write_text("", encoding="utf-8")
    run_calls = []

    async def _fake_detect(_ip):
        return "set PATH=%USERPROFILE%\\\\.local\\\\bin;%PATH% && "

    async def _fake_run(cmd, _cwd):
        run_calls.append(cmd)
        return ""

    monkeypatch.setattr(deployment_prepare_support.os, "name", "nt", raising=False)
    monkeypatch.setattr(deployment_prepare_support.Path, "home", classmethod(lambda cls: fake_home))

    await deployment_prepare_support.prepare_local_env(
        agi_cls,
        envar_truthy_fn=_truthy,
        detect_export_cmd_fn=_fake_detect,
        set_env_var_fn=lambda *_a, **_k: None,
        run_fn=_fake_run,
        python_version_fn=lambda: "3.13.12",
        log=mock.Mock(),
    )

    assert any(str(standalone_uv) in cmd and "self update" in cmd for cmd in run_calls)
    assert any("uv --quiet python install 3.13" in cmd for cmd in run_calls)


@pytest.mark.asyncio
async def test_prepare_local_env_windows_handles_empty_uv_and_self_update_failure(monkeypatch, tmp_path):
    env = _build_local_env(tmp_path, internet_on="1", is_worker_env=False, uv="")
    agi_cls = _build_agi(env, supports_rapids=lambda: True)
    fake_home = tmp_path / "home"
    standalone_uv = fake_home / ".local" / "bin" / "uv.exe"
    standalone_uv.parent.mkdir(parents=True, exist_ok=True)
    standalone_uv.write_text("", encoding="utf-8")
    run_calls = []
    log = mock.Mock()

    async def _fake_detect(_ip):
        return ""

    async def _fake_run(cmd, _cwd):
        run_calls.append(cmd)
        if "self update" in cmd:
            raise RuntimeError("standalone update failed")
        return ""

    monkeypatch.setattr(deployment_prepare_support.os, "name", "nt", raising=False)
    monkeypatch.setattr(deployment_prepare_support.Path, "home", classmethod(lambda cls: fake_home))

    await deployment_prepare_support.prepare_local_env(
        agi_cls,
        envar_truthy_fn=_truthy,
        detect_export_cmd_fn=_fake_detect,
        set_env_var_fn=lambda *_a, **_k: None,
        run_fn=_fake_run,
        python_version_fn=lambda: "3.13.12",
        log=log,
    )

    assert any(cmd.startswith(f"{standalone_uv} self update") for cmd in run_calls)
    assert any("python install 3.13" in cmd for cmd in run_calls)
    log.warning.assert_called()


@pytest.mark.asyncio
async def test_prepare_local_env_online_re_raises_unexpected_python_install_error(tmp_path):
    env = _build_local_env(tmp_path, internet_on="1", is_worker_env=False)
    agi_cls = _build_agi(env, supports_rapids=lambda: True)

    async def _fake_detect(_ip):
        return ""

    async def _fake_run(cmd, _cwd):
        if "python install" in cmd:
            raise RuntimeError("unexpected install failure")
        return ""

    with pytest.raises(RuntimeError, match="unexpected install failure"):
        await deployment_prepare_support.prepare_local_env(
            agi_cls,
            envar_truthy_fn=_truthy,
            detect_export_cmd_fn=_fake_detect,
            set_env_var_fn=lambda *_a, **_k: None,
            run_fn=_fake_run,
            python_version_fn=lambda: "3.13.12",
            log=mock.Mock(),
        )


@pytest.mark.asyncio
async def test_prepare_cluster_env_happy_path_sends_files(tmp_path):
    env = _build_cluster_env(tmp_path)
    agi_cls = _build_agi(env)
    sent = []
    remote_cmds = []

    async def _fake_detect(_ip):
        return 'export PATH="$HOME/.local/bin:$PATH"; '

    async def _fake_exec(ip, cmd):
        remote_cmds.append((ip, cmd))
        if "--version" in cmd:
            return "uv 0.6.0"
        return "ok"

    async def _noop(*_args, **_kwargs):
        return None

    await deployment_prepare_support.prepare_cluster_env(
        agi_cls,
        "127.0.0.1",
        envar_truthy_fn=_truthy,
        detect_export_cmd_fn=_fake_detect,
        ensure_optional_extras_fn=lambda *_a, **_k: None,
        stage_uv_sources_fn=lambda **_kwargs: [],
        run_exec_ssh_fn=_fake_exec,
        send_files_fn=_recording_send(sent),
        kill_fn=_noop,
        clean_dirs_fn=_noop,
        set_env_var_fn=lambda key, value=None: env.envars.__setitem__(key, value),
        log=mock.Mock(),
    )

    assert any("self update" in cmd for _, cmd in remote_cmds)
    assert any(item[2] == "wenv" for item in sent)
    assert any(any(file["name"] == "cli.py" for file in items) for _, items, _ in sent)


@pytest.mark.asyncio
async def test_prepare_cluster_env_legacy_intel_macos_selects_python_311(tmp_path):
    env = _build_cluster_env(tmp_path)
    env.python_version = "3.13"
    env.uv_worker = "PYTHON_GIL=0 uv"
    agi_cls = _build_agi(env)
    sent = []
    remote_cmds = []

    async def _fake_detect(_ip):
        return 'export PATH="$HOME/.local/bin:$PATH"; '

    async def _fake_exec(ip, cmd):
        remote_cmds.append((ip, cmd))
        if cmd == deployment_remote_support._remote_platform_probe_command():
            return "Darwin\nx86_64\n10.15.8"
        if "--version" in cmd:
            return "uv 0.6.0"
        return "ok"

    async def _noop(*_args, **_kwargs):
        return None

    await deployment_prepare_support.prepare_cluster_env(
        agi_cls,
        "127.0.0.1",
        envar_truthy_fn=_truthy,
        detect_export_cmd_fn=_fake_detect,
        ensure_optional_extras_fn=lambda *_a, **_k: None,
        stage_uv_sources_fn=lambda **_kwargs: [],
        run_exec_ssh_fn=_fake_exec,
        send_files_fn=_recording_send(sent),
        kill_fn=_noop,
        clean_dirs_fn=_noop,
        set_env_var_fn=lambda key, value=None: env.envars.__setitem__(key, value),
        log=mock.Mock(),
    )

    assert env.pyvers_worker == "3.11"
    assert env.python_version == "3.11"
    assert env.uv_worker == "uv"
    assert any("python install 3.11" in cmd for _, cmd in remote_cmds)
    assert not any("python install 3.13" in cmd for _, cmd in remote_cmds)
    assert any(item[2] == "wenv" for item in sent)


@pytest.mark.asyncio
async def test_prepare_cluster_env_stages_uv_source_payload(tmp_path):
    cluster_pck = tmp_path / "cluster_pck"
    (cluster_pck / "agi_distributor").mkdir(parents=True, exist_ok=True)
    (cluster_pck / "agi_distributor" / "cli.py").write_text("print('cli')", encoding="utf-8")

    deps_root = tmp_path / "deps" / "ilp_worker"
    deps_root.mkdir(parents=True, exist_ok=True)
    (deps_root / "pyproject.toml").write_text("[project]\nname='ilp_worker'\n", encoding="utf-8")
    (deps_root / "milp.py").write_text("class MILP: pass\n", encoding="utf-8")

    worker_dir = tmp_path / "worker_src"
    worker_dir.mkdir(parents=True, exist_ok=True)
    worker_pyproject = worker_dir / "pyproject.toml"
    worker_pyproject.write_text(
        """
[project]
name='demo-worker'
[tool.uv.sources]
ilp_worker = { path = "../deps/ilp_worker" }
""".strip(),
        encoding="utf-8",
    )

    env = SimpleNamespace(
        dist_rel=Path("wenv/dist"),
        wenv_rel=Path("wenv"),
        pyvers_worker="3.13",
        is_local=lambda ip: ip == "127.0.0.1",
        envars={"AGI_INTERNET_ON": "1"},
        uv="uv",
        cluster_pck=cluster_pck,
        worker_pyproject=worker_pyproject,
        manager_pyproject=tmp_path / "manager_pyproject.toml",
        uvproject=tmp_path / "uv.toml",
        target_worker="demo_worker",
        verbose=1,
    )
    env.manager_pyproject.write_text("[project]\nname='demo-manager'\n", encoding="utf-8")
    env.uvproject.write_text("[tool.uv]\n", encoding="utf-8")
    agi_cls = _build_agi(env, agi_workers={"dag": "dag-worker"})
    sent = []

    async def _fake_detect(_ip):
        return 'export PATH="$HOME/.local/bin:$PATH"; '

    async def _fake_exec(_ip, cmd):
        if "--version" in cmd:
            return "uv 0.6.0"
        return "ok"

    async def _noop(*_args, **_kwargs):
        return None

    await deployment_prepare_support.prepare_cluster_env(
        agi_cls,
        "127.0.0.1",
        envar_truthy_fn=_truthy,
        detect_export_cmd_fn=_fake_detect,
        ensure_optional_extras_fn=uv_source_support.ensure_optional_extras,
        stage_uv_sources_fn=uv_source_support.stage_uv_sources_for_copied_pyproject,
        run_exec_ssh_fn=_fake_exec,
        send_files_fn=_recording_send(sent),
        kill_fn=_noop,
        clean_dirs_fn=_noop,
        set_env_var_fn=lambda key, value=None: env.envars.__setitem__(key, value),
        log=mock.Mock(),
    )

    sent_to_wenv = [items for _ip, items, remote_path in sent if remote_path == "wenv"]
    assert sent_to_wenv
    payload = sent_to_wenv[0]
    pyproject_item = next(item for item in payload if item["name"] == "pyproject.toml")
    assert "_uv_sources/ilp_worker" in pyproject_item["content"]
    staged_item = next(item for item in payload if item["name"] == "_uv_sources")
    assert staged_item["is_dir"] is True
    assert "ilp_worker/milp.py" in staged_item["children"]


@pytest.mark.asyncio
async def test_prepare_cluster_env_ignores_uv_self_update_failure(tmp_path):
    env = _build_cluster_env(tmp_path)
    agi_cls = _build_agi(env)
    sent = []
    remote_cmds = []

    async def _fake_detect(_ip):
        return 'export PATH="$HOME/.local/bin:$PATH"; '

    async def _fake_exec(ip, cmd):
        remote_cmds.append((ip, cmd))
        if "--version" in cmd:
            return "uv 0.6.0"
        if "self update" in cmd:
            raise RuntimeError("Self-update is only available for standalone installs")
        return "ok"

    async def _noop(*_args, **_kwargs):
        return None

    await deployment_prepare_support.prepare_cluster_env(
        agi_cls,
        "127.0.0.1",
        envar_truthy_fn=_truthy,
        detect_export_cmd_fn=_fake_detect,
        ensure_optional_extras_fn=lambda *_a, **_k: None,
        stage_uv_sources_fn=lambda **_kwargs: [],
        run_exec_ssh_fn=_fake_exec,
        send_files_fn=_recording_send(sent),
        kill_fn=_noop,
        clean_dirs_fn=_noop,
        set_env_var_fn=lambda key, value=None: env.envars.__setitem__(key, value),
        log=mock.Mock(),
    )

    assert any("self update" in cmd for _, cmd in remote_cmds)
    assert any("python install 3.13" in cmd for _, cmd in remote_cmds)
    assert any(item[2] == "wenv" for item in sent)


@pytest.mark.asyncio
async def test_prepare_cluster_env_uses_manager_pyproject_when_worker_missing(tmp_path):
    env = _build_cluster_env(tmp_path)
    env.worker_pyproject = tmp_path / "missing_worker.toml"
    agi_cls = _build_agi(env)
    sent = []

    async def _fake_detect(_ip):
        return 'export PATH="$HOME/.local/bin:$PATH"; '

    async def _fake_exec(_ip, cmd):
        if "--version" in cmd:
            return "uv 0.6.0"
        return "ok"

    async def _noop(*_args, **_kwargs):
        return None

    await deployment_prepare_support.prepare_cluster_env(
        agi_cls,
        "127.0.0.1",
        envar_truthy_fn=_truthy,
        detect_export_cmd_fn=_fake_detect,
        ensure_optional_extras_fn=lambda *_a, **_k: None,
        stage_uv_sources_fn=lambda **_kwargs: [],
        run_exec_ssh_fn=_fake_exec,
        send_files_fn=_recording_send(sent),
        kill_fn=_noop,
        clean_dirs_fn=_noop,
        set_env_var_fn=lambda key, value=None: env.envars.__setitem__(key, value),
        log=mock.Mock(),
    )

    sent_to_wenv = [items for _ip, items, remote_path in sent if remote_path == "wenv"]
    assert sent_to_wenv
    assert any(
        any(item["name"] == "pyproject.toml" and "demo-manager" in item["content"] for item in items)
        for items in sent_to_wenv
    )
    assert any(any(item["name"] == "uv.toml" for item in items) for items in sent_to_wenv)


@pytest.mark.asyncio
async def test_prepare_cluster_env_uses_unique_stage_dir_and_cleans_it(tmp_path):
    env = _build_cluster_env(tmp_path)
    agi_cls = _build_agi(env)
    sent = []
    staged_roots = []

    async def _fake_detect(_ip):
        return 'export PATH="$HOME/.local/bin:$PATH"; '

    async def _fake_exec(_ip, cmd):
        if "--version" in cmd:
            return "uv 0.6.0"
        return "ok"

    async def _noop(*_args, **_kwargs):
        return None

    def _fake_mkdtemp(prefix):
        stage_root = tmp_path / f"{prefix}stage"
        stage_root.mkdir(parents=True, exist_ok=False)
        staged_roots.append(stage_root)
        return str(stage_root)

    def _fake_stage_sources(src_pyproject, dest_pyproject, stage_root, log_rewrites):
        assert src_pyproject == env.worker_pyproject
        assert dest_pyproject == stage_root / "pyproject.toml"
        assert stage_root == staged_roots[0]
        assert log_rewrites is False
        staged_source = stage_root / "staged-source.txt"
        staged_source.write_text("staged", encoding="utf-8")
        return [staged_source]

    await deployment_prepare_support.prepare_cluster_env(
        agi_cls,
        "127.0.0.1",
        envar_truthy_fn=_truthy,
        detect_export_cmd_fn=_fake_detect,
        ensure_optional_extras_fn=lambda *_a, **_k: None,
        stage_uv_sources_fn=_fake_stage_sources,
        run_exec_ssh_fn=_fake_exec,
        send_files_fn=_recording_send(sent),
        kill_fn=_noop,
        clean_dirs_fn=_noop,
        mkdtemp_fn=_fake_mkdtemp,
        set_env_var_fn=lambda key, value=None: env.envars.__setitem__(key, value),
        log=mock.Mock(),
    )

    assert staged_roots
    assert staged_roots[0].name.startswith("agilab_demo_worker_pyproject_")
    assert staged_roots[0].exists() is False
    sent_to_wenv = [items for _ip, items, remote_path in sent if remote_path == "wenv"]
    assert sent_to_wenv
    assert any(item["name"] == "pyproject.toml" for item in sent_to_wenv[0])
    assert any(item["name"] == "staged-source.txt" for item in sent_to_wenv[0])
    assert any(item["name"] == "uv.toml" for item in sent_to_wenv[0])


@pytest.mark.asyncio
async def test_prepare_cluster_env_rejects_invalid_remote_ip(tmp_path):
    env = _build_cluster_env(tmp_path)
    env.is_local = lambda _ip: False
    agi_cls = _build_agi(env, workers={"not-an-ip": 1})

    with pytest.raises(ValueError, match="Invalid IP address"):
        await deployment_prepare_support.prepare_cluster_env(
            agi_cls,
            "127.0.0.1",
            envar_truthy_fn=_truthy,
            detect_export_cmd_fn=lambda *_a, **_k: None,
            ensure_optional_extras_fn=lambda *_a, **_k: None,
            stage_uv_sources_fn=lambda **_kwargs: [],
            run_exec_ssh_fn=lambda *_a, **_k: None,
            send_files_fn=lambda *_a, **_k: None,
            kill_fn=lambda *_a, **_k: None,
            clean_dirs_fn=lambda *_a, **_k: None,
            log=mock.Mock(),
        )


@pytest.mark.asyncio
async def test_prepare_cluster_env_version_connection_error_bubbles(tmp_path):
    env = _build_cluster_env(tmp_path)
    agi_cls = _build_agi(env)

    async def _fake_detect(_ip):
        return ""

    async def _fake_exec(_ip, _cmd):
        raise ConnectionError("network down")

    with pytest.raises(ConnectionError, match="network down"):
        await deployment_prepare_support.prepare_cluster_env(
            agi_cls,
            "127.0.0.1",
            envar_truthy_fn=_truthy,
            detect_export_cmd_fn=_fake_detect,
            ensure_optional_extras_fn=lambda *_a, **_k: None,
            stage_uv_sources_fn=lambda **_kwargs: [],
            run_exec_ssh_fn=_fake_exec,
            send_files_fn=lambda *_a, **_k: None,
            kill_fn=lambda *_a, **_k: None,
            clean_dirs_fn=lambda *_a, **_k: None,
            log=mock.Mock(),
        )


@pytest.mark.asyncio
async def test_prepare_cluster_env_offline_missing_uv_raises_environment_error(tmp_path):
    env = _build_cluster_env(tmp_path, internet_on="0")
    agi_cls = _build_agi(env)
    log = mock.Mock()

    async def _fake_detect(_ip):
        return ""

    async def _fake_exec(_ip, cmd):
        if "--version" in cmd:
            raise RuntimeError("uv missing")
        return "ok"

    with pytest.raises(EnvironmentError, match="Uv binary is not installed"):
        await deployment_prepare_support.prepare_cluster_env(
            agi_cls,
            "127.0.0.1",
            envar_truthy_fn=_truthy,
            detect_export_cmd_fn=_fake_detect,
            ensure_optional_extras_fn=lambda *_a, **_k: None,
            stage_uv_sources_fn=lambda **_kwargs: [],
            run_exec_ssh_fn=_fake_exec,
            send_files_fn=lambda *_a, **_k: None,
            kill_fn=lambda *_a, **_k: None,
            clean_dirs_fn=lambda *_a, **_k: None,
            log=log,
        )

    log.error.assert_called_once()


@pytest.mark.asyncio
async def test_prepare_cluster_env_uses_powershell_installer_before_continuing(tmp_path):
    env = _build_cluster_env(tmp_path)
    agi_cls = _build_agi(env)
    remote_cmds = []

    async def _fake_detect(_ip):
        return ""

    async def _fake_exec(ip, cmd):
        remote_cmds.append((ip, cmd))
        if "--version" in cmd:
            raise RuntimeError("uv missing")
        return "ok"

    async def _noop(*_args, **_kwargs):
        return None

    await deployment_prepare_support.prepare_cluster_env(
        agi_cls,
        "127.0.0.1",
        envar_truthy_fn=_truthy,
        detect_export_cmd_fn=_fake_detect,
        ensure_optional_extras_fn=lambda *_a, **_k: None,
        stage_uv_sources_fn=lambda **_kwargs: [],
        run_exec_ssh_fn=_fake_exec,
        send_files_fn=_noop,
        kill_fn=_noop,
        clean_dirs_fn=_noop,
        set_env_var_fn=lambda key, value=None: env.envars.__setitem__(key, value),
        log=mock.Mock(),
    )

    assert any("install.ps1" in cmd for _ip, cmd in remote_cmds)
    assert not any("curl -LsSf https://astral.sh/uv/install.sh | sh" in cmd for _ip, cmd in remote_cmds)
    assert not any("irm https://astral.sh/uv/install.ps1 | iex" in cmd for _ip, cmd in remote_cmds)


@pytest.mark.asyncio
async def test_prepare_cluster_env_powershell_connection_error_bubbles(tmp_path):
    env = _build_cluster_env(tmp_path)
    agi_cls = _build_agi(env)

    async def _fake_detect(_ip):
        return ""

    async def _fake_exec(_ip, cmd):
        if "--version" in cmd:
            raise RuntimeError("uv missing")
        if "install.ps1" in cmd:
            raise ConnectionError("ssh lost")
        return "ok"

    with pytest.raises(ConnectionError, match="ssh lost"):
        await deployment_prepare_support.prepare_cluster_env(
            agi_cls,
            "127.0.0.1",
            envar_truthy_fn=_truthy,
            detect_export_cmd_fn=_fake_detect,
            ensure_optional_extras_fn=lambda *_a, **_k: None,
            stage_uv_sources_fn=lambda **_kwargs: [],
            run_exec_ssh_fn=_fake_exec,
            send_files_fn=lambda *_a, **_k: None,
            kill_fn=lambda *_a, **_k: None,
            clean_dirs_fn=lambda *_a, **_k: None,
            log=mock.Mock(),
        )


@pytest.mark.asyncio
async def test_prepare_cluster_env_offline_warns_without_self_update(tmp_path):
    env = _build_cluster_env(tmp_path, internet_on="0")
    agi_cls = _build_agi(env)
    remote_cmds = []
    log = mock.Mock()

    async def _fake_detect(_ip):
        return ""

    async def _fake_exec(ip, cmd):
        remote_cmds.append((ip, cmd))
        if "--version" in cmd:
            return "uv 0.6.0"
        return "ok"

    async def _noop(*_args, **_kwargs):
        return None

    await deployment_prepare_support.prepare_cluster_env(
        agi_cls,
        "127.0.0.1",
        envar_truthy_fn=_truthy,
        detect_export_cmd_fn=_fake_detect,
        ensure_optional_extras_fn=lambda *_a, **_k: None,
        stage_uv_sources_fn=lambda **_kwargs: [],
        run_exec_ssh_fn=_fake_exec,
        send_files_fn=_noop,
        kill_fn=_noop,
        clean_dirs_fn=_noop,
        set_env_var_fn=lambda key, value=None: env.envars.__setitem__(key, value),
        log=log,
    )

    assert not any("self update" in cmd for _ip, cmd in remote_cmds)
    log.warning.assert_called()


@pytest.mark.asyncio
async def test_prepare_cluster_env_python_install_unknown_error_bubbles(tmp_path):
    env = _build_cluster_env(tmp_path)
    agi_cls = _build_agi(env)

    class _ProcError(RuntimeError):
        pass

    async def _fake_detect(_ip):
        return ""

    async def _fake_exec(_ip, cmd):
        if "--version" in cmd:
            return "uv 0.6.0"
        if "python install" in cmd:
            raise _ProcError("unexpected install failure")
        return "ok"

    with pytest.raises(_ProcError, match="unexpected install failure"):
        await deployment_prepare_support.prepare_cluster_env(
            agi_cls,
            "127.0.0.1",
            envar_truthy_fn=_truthy,
            detect_export_cmd_fn=_fake_detect,
            ensure_optional_extras_fn=lambda *_a, **_k: None,
            stage_uv_sources_fn=lambda **_kwargs: [],
            run_exec_ssh_fn=_fake_exec,
            send_files_fn=lambda *_a, **_k: None,
            kill_fn=lambda *_a, **_k: None,
            clean_dirs_fn=lambda *_a, **_k: None,
            process_error_type=_ProcError,
            log=mock.Mock(),
        )


@pytest.mark.asyncio
async def test_prepare_cluster_env_falls_back_to_original_pyproject_when_extra_seed_fails(tmp_path):
    env = _build_cluster_env(tmp_path)
    agi_cls = _build_agi(env)
    sent = []

    async def _fake_detect(_ip):
        return 'export PATH="$HOME/.local/bin:$PATH"; '

    async def _fake_exec(_ip, cmd):
        if "--version" in cmd:
            return "uv 0.6.0"
        return "ok"

    async def _noop(*_args, **_kwargs):
        return None

    await deployment_prepare_support.prepare_cluster_env(
        agi_cls,
        "127.0.0.1",
        envar_truthy_fn=_truthy,
        detect_export_cmd_fn=_fake_detect,
        ensure_optional_extras_fn=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
        stage_uv_sources_fn=lambda **_kwargs: [],
        run_exec_ssh_fn=_fake_exec,
        send_files_fn=_recording_send(sent),
        kill_fn=_noop,
        clean_dirs_fn=_noop,
        set_env_var_fn=lambda key, value=None: env.envars.__setitem__(key, value),
        log=mock.Mock(),
    )

    sent_to_wenv = [items for _ip, items, remote_path in sent if remote_path == "wenv"]
    assert sent_to_wenv
    assert any("worker_pyproject.toml" == item["name"] for item in sent_to_wenv[0])
    assert not any(item["name"] == "pyproject.toml" for item in sent_to_wenv[0])


@pytest.mark.asyncio
async def test_prepare_cluster_env_propagates_unexpected_stage_bug(tmp_path):
    env = _build_cluster_env(tmp_path)
    agi_cls = _build_agi(env)
    staged_roots = []

    async def _fake_detect(_ip):
        return 'export PATH="$HOME/.local/bin:$PATH"; '

    async def _fake_exec(_ip, cmd):
        if "--version" in cmd:
            return "uv 0.6.0"
        return "ok"

    async def _noop(*_args, **_kwargs):
        return None

    def _fake_mkdtemp(prefix):
        stage_root = tmp_path / f"{prefix}stage"
        stage_root.mkdir(parents=True, exist_ok=False)
        staged_roots.append(stage_root)
        return str(stage_root)

    def _broken_stage_sources(**_kwargs):
        raise TypeError("bad stage helper")

    with pytest.raises(TypeError, match="bad stage helper"):
        await deployment_prepare_support.prepare_cluster_env(
            agi_cls,
            "127.0.0.1",
            envar_truthy_fn=_truthy,
            detect_export_cmd_fn=_fake_detect,
            ensure_optional_extras_fn=lambda *_a, **_k: None,
            stage_uv_sources_fn=_broken_stage_sources,
            run_exec_ssh_fn=_fake_exec,
            send_files_fn=_recording_send([]),
            kill_fn=_noop,
            clean_dirs_fn=_noop,
            mkdtemp_fn=_fake_mkdtemp,
            set_env_var_fn=lambda key, value=None: env.envars.__setitem__(key, value),
            log=mock.Mock(),
        )

    assert staged_roots
    assert staged_roots[0].exists() is False


@pytest.mark.asyncio
async def test_prepare_cluster_env_raises_when_uv_missing_offline():
    env = SimpleNamespace(
        dist_rel=Path("wenv/dist"),
        wenv_rel=Path("wenv"),
        pyvers_worker="3.13",
        is_local=lambda ip: False,
        envars={"AGI_INTERNET_ON": "0"},
        uv="uv",
        cluster_pck=Path("."),
        worker_pyproject=Path("worker_pyproject.toml"),
        manager_pyproject=Path("manager_pyproject.toml"),
        uvproject=Path("uv.toml"),
        target_worker="demo_worker",
    )
    agi_cls = _build_agi(env)

    async def _fake_exec(_ip, _cmd):
        raise RuntimeError("uv missing")

    async def _fake_detect(_ip):
        return ""

    with pytest.raises(EnvironmentError, match="Uv binary is not installed"):
        await deployment_prepare_support.prepare_cluster_env(
            agi_cls,
            "127.0.0.1",
            envar_truthy_fn=_truthy,
            detect_export_cmd_fn=_fake_detect,
            ensure_optional_extras_fn=lambda *_a, **_k: None,
            stage_uv_sources_fn=lambda **_kwargs: [],
            run_exec_ssh_fn=_fake_exec,
            send_files_fn=_recording_send([]),
            kill_fn=lambda *_a, **_k: None,
            clean_dirs_fn=lambda *_a, **_k: None,
            set_env_var_fn=lambda *_a, **_k: None,
            log=mock.Mock(),
        )


@pytest.mark.asyncio
async def test_uninstall_modules_and_venv_todo_cover_cleanup_and_logging(monkeypatch):
    commands = []
    log = mock.Mock()
    env = SimpleNamespace(uv="uv", agi_env=Path("/tmp/agi-env"), verbose=1)
    agi_cls = SimpleNamespace(
        env=env,
        _module_to_clean=["demo-one", "demo-two"],
    )

    async def _fake_run(cmd, cwd):
        commands.append((cmd, cwd))
        return ""

    monkeypatch.setattr(deployment_prepare_support.AgiEnv, "is_local", staticmethod(lambda ip: ip == "127.0.0.1"))

    await deployment_prepare_support.uninstall_modules(agi_cls, env, run_fn=_fake_run, log=log)
    deployment_prepare_support.venv_todo(agi_cls, {"127.0.0.1", "10.0.0.2"}, log=log)

    assert commands == [
        ("uv pip uninstall demo-one -y", Path("/tmp/agi-env")),
        ("uv pip uninstall demo-two -y", Path("/tmp/agi-env")),
    ]
    assert agi_cls._module_to_clean == []
    assert agi_cls._local_ip == ["127.0.0.1"]
    assert agi_cls._remote_ip == ["10.0.0.2"]
    assert agi_cls._install_todo == 2
    assert log.info.called


@pytest.mark.asyncio
async def test_prepare_cluster_env_fallback_installer_and_no_download(tmp_path):
    env = _build_cluster_env(tmp_path)
    agi_cls = _build_agi(env)
    sent = []
    cmds = []

    class _FakeProcessError(Exception):
        pass

    async def _fake_detect(_ip):
        return 'export PATH="$HOME/.local/bin:$PATH"; '

    async def _fake_exec(ip, cmd):
        cmds.append((ip, cmd))
        if "--version" in cmd:
            raise RuntimeError("uv missing")
        if "install.ps1" in cmd:
            raise RuntimeError("windows installer failed")
        if "curl --proto '=https' --tlsv1.2 -LsSf https://astral.sh/uv/install.sh -o" in cmd:
            return "ok"
        if "python install" in cmd:
            raise _FakeProcessError("No download found for request")
        return "ok"

    async def _noop(*_args, **_kwargs):
        return None

    await deployment_prepare_support.prepare_cluster_env(
        agi_cls,
        "127.0.0.1",
        envar_truthy_fn=_truthy,
        detect_export_cmd_fn=_fake_detect,
        ensure_optional_extras_fn=lambda *_a, **_k: None,
        stage_uv_sources_fn=lambda **_kwargs: [],
        run_exec_ssh_fn=_fake_exec,
        send_files_fn=_recording_send(sent),
        kill_fn=_noop,
        clean_dirs_fn=_noop,
        process_error_type=_FakeProcessError,
        set_env_var_fn=lambda key, value=None: env.envars.__setitem__(key, value),
        log=mock.Mock(),
    )

    joined = "\n".join(cmd for _, cmd in cmds)
    assert "install.ps1" in joined
    assert "install.sh | sh" not in joined
    assert "irm https://astral.sh/uv/install.ps1 | iex" not in joined
    assert "curl --proto '=https' --tlsv1.2 -LsSf https://astral.sh/uv/install.sh -o" in joined
    assert 'sh "$tmp"' in joined
    assert any("python install 3.13" in cmd for _, cmd in cmds)
    assert any(item[2] == "wenv" for item in sent)
    assert any(any(file["name"] == "cli.py" for file in items) for _, items, _ in sent)
