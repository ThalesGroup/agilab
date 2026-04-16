from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from agi_cluster.agi_distributor import deployment_remote_support, uv_source_support


async def _call_deploy_remote_worker(
    agi_cls,
    ip: str,
    env,
    wenv_rel: Path,
    option: str,
    *,
    set_env_var_fn,
    log,
) -> None:
    await deployment_remote_support.deploy_remote_worker(
        agi_cls,
        ip,
        env,
        wenv_rel,
        option,
        worker_site_packages_dir_fn=uv_source_support.worker_site_packages_dir,
        staged_uv_sources_pth_content_fn=uv_source_support.staged_uv_sources_pth_content,
        set_env_var_fn=set_env_var_fn,
        log=log,
    )


@pytest.mark.asyncio
async def test_deploy_remote_worker_non_source_flow(monkeypatch, tmp_path):
    dist_abs = tmp_path / "dist"
    dist_abs.mkdir(parents=True, exist_ok=True)
    (dist_abs / "demo_worker-0.0.1.egg").write_text("x", encoding="utf-8")

    env = SimpleNamespace(
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
    )
    ssh_calls = []
    send_calls = []

    async def _fake_exec_ssh(_ip, cmd):
        ssh_calls.append(cmd)
        return "ok"

    async def _fake_send(_env, ip, files, remote_path, user=None, password=None):
        del user, password
        send_calls.append((ip, [Path(f).name for f in files], str(remote_path)))

    async def _fake_send_file(_env, ip, local_path, remote_path, user=None, password=None):
        del user, password
        send_calls.append((ip, [Path(local_path).name], str(remote_path.parent)))

    agi_cls = SimpleNamespace(
        _rapids_enabled=False,
        _workers_data_path=None,
        exec_ssh=_fake_exec_ssh,
        send_files=_fake_send,
        send_file=_fake_send_file,
    )

    await _call_deploy_remote_worker(
        agi_cls,
        "10.0.0.2",
        env,
        Path("worker_env"),
        " --extra pandas-worker",
        set_env_var_fn=lambda *_a, **_k: None,
        log=deployment_remote_support.logger,
    )

    assert any("demo_worker-0.0.1.egg" in names for _, names, _ in send_calls)
    assert any("ensurepip" in cmd for cmd in ssh_calls)
    assert any("python -m demo.post_install" in cmd for cmd in ssh_calls)


@pytest.mark.asyncio
async def test_deploy_remote_worker_source_env_with_rapids(monkeypatch, tmp_path):
    dist_abs = tmp_path / "dist"
    dist_abs.mkdir(parents=True, exist_ok=True)
    (dist_abs / "demo_worker-0.0.1.egg").write_text("egg", encoding="utf-8")
    agi_env = tmp_path / "agi_env"
    agi_node = tmp_path / "agi_node"
    for p, name in ((agi_env, "agi_env"), (agi_node, "agi_node")):
        (p / "dist").mkdir(parents=True, exist_ok=True)
        (p / "dist" / f"{name}-0.0.1-py3-none-any.whl").write_text("whl", encoding="utf-8")

    env = SimpleNamespace(
        wenv_abs=tmp_path / "wenv",
        wenv_rel=Path("wenv"),
        dist_rel=Path("wenv/dist"),
        dist_abs=dist_abs,
        pyvers_worker="3.13",
        envars={},
        uv_worker="uv",
        is_source_env=True,
        app="demo_app",
        target_worker="demo_worker",
        agi_env=agi_env,
        agi_node=agi_node,
        post_install_rel="demo.post_install",
        verbose=2,
    )
    sent = []
    ssh = []

    async def _fake_send(_env, ip, files, remote_path, user=None, password=None):
        del user, password
        payload = []
        for file in files:
            p = Path(file)
            entry = {"name": p.name}
            if p.suffix == ".pth":
                entry["content"] = p.read_text(encoding="utf-8")
            payload.append(entry)
        sent.append((ip, payload, str(remote_path)))

    async def _fake_send_file(_env, ip, local_path, remote_path, user=None, password=None):
        del user, password
        p = Path(local_path)
        payload = [{"name": p.name, "content": p.read_text(encoding="utf-8")}]
        sent.append((ip, payload, str(remote_path.parent)))

    async def _fake_exec(ip, cmd):
        ssh.append((ip, cmd))
        if cmd.strip() == "nvidia-smi":
            return "NVIDIA-SMI"
        return "ok"

    agi_cls = SimpleNamespace(
        _rapids_enabled=True,
        _workers_data_path=str(tmp_path / "share"),
        exec_ssh=_fake_exec,
        send_files=_fake_send,
        send_file=_fake_send_file,
    )

    await _call_deploy_remote_worker(
        agi_cls,
        "10.0.0.2",
        env,
        Path("wenv"),
        " --extra pandas-worker",
        set_env_var_fn=lambda *_a, **_k: None,
        log=deployment_remote_support.logger,
    )

    assert any(".agilab/.env" in cmd for _, cmd in ssh)
    assert any("nvidia-smi" == cmd for _, cmd in ssh)
    assert any(any(item["name"] == "agi_env-0.0.1-py3-none-any.whl" for item in payload) for _, payload, _ in sent)
    assert any(any(item["name"] == "agi_node-0.0.1-py3-none-any.whl" for item in payload) for _, payload, _ in sent)
    assert any("python -m demo.post_install" in cmd for _, cmd in ssh)


@pytest.mark.asyncio
async def test_deploy_remote_worker_rapids_probe_propagates_unexpected_value_error(tmp_path):
    dist_abs = tmp_path / "dist"
    dist_abs.mkdir(parents=True, exist_ok=True)
    (dist_abs / "demo_worker-0.0.1.egg").write_text("egg", encoding="utf-8")
    agi_env = tmp_path / "agi_env"
    agi_node = tmp_path / "agi_node"
    for p, name in ((agi_env, "agi_env"), (agi_node, "agi_node")):
        (p / "dist").mkdir(parents=True, exist_ok=True)
        (p / "dist" / f"{name}-0.0.1-py3-none-any.whl").write_text("whl", encoding="utf-8")

    env = SimpleNamespace(
        wenv_abs=tmp_path / "wenv",
        wenv_rel=Path("wenv"),
        dist_rel=Path("wenv/dist"),
        dist_abs=dist_abs,
        pyvers_worker="3.13",
        envars={},
        uv_worker="uv",
        is_source_env=True,
        app="demo_app",
        target_worker="demo_worker",
        agi_env=agi_env,
        agi_node=agi_node,
        post_install_rel="demo.post_install",
        verbose=0,
    )

    async def _fake_exec(ip, cmd):
        if cmd.strip() == "nvidia-smi":
            raise ValueError("unexpected rapids probe bug")
        return "ok"

    async def _fake_send(_env, ip, files, remote_path, user=None, password=None):
        del _env, ip, files, remote_path, user, password

    async def _fake_send_file(_env, ip, local_path, remote_path, user=None, password=None):
        del _env, ip, local_path, remote_path, user, password

    agi_cls = SimpleNamespace(
        _rapids_enabled=True,
        _workers_data_path=None,
        exec_ssh=_fake_exec,
        send_files=_fake_send,
        send_file=_fake_send_file,
    )

    with pytest.raises(ValueError, match="unexpected rapids probe bug"):
        await _call_deploy_remote_worker(
            agi_cls,
            "10.0.0.2",
            env,
            Path("wenv"),
            " --extra pandas-worker",
            set_env_var_fn=lambda *_a, **_k: None,
            log=deployment_remote_support.logger,
        )


@pytest.mark.asyncio
async def test_deploy_remote_worker_source_env_missing_egg_logs_and_raises(tmp_path):
    dist_abs = tmp_path / "dist"
    dist_abs.mkdir(parents=True, exist_ok=True)
    agi_env = tmp_path / "agi_env"
    agi_node = tmp_path / "agi_node"
    for p, name in ((agi_env, "agi_env"), (agi_node, "agi_node")):
        (p / "dist").mkdir(parents=True, exist_ok=True)
        (p / "dist" / f"{name}-0.0.1-py3-none-any.whl").write_text("whl", encoding="utf-8")

    env = SimpleNamespace(
        wenv_abs=tmp_path / "wenv",
        wenv_rel=Path("wenv"),
        dist_rel=Path("wenv/dist"),
        dist_abs=dist_abs,
        pyvers_worker="3.13",
        envars={},
        uv_worker="uv",
        is_source_env=True,
        app="demo_app",
        target_worker="demo_worker",
        agi_env=agi_env,
        agi_node=agi_node,
        post_install_rel="demo.post_install",
        verbose=0,
    )
    agi_cls = SimpleNamespace(
        _rapids_enabled=False,
        _workers_data_path=None,
        exec_ssh=lambda *_a, **_k: None,
        send_files=lambda *_a, **_k: None,
        send_file=lambda *_a, **_k: None,
    )
    log = mock.Mock()

    with pytest.raises(FileNotFoundError, match="no existing egg file"):
        await _call_deploy_remote_worker(
            agi_cls,
            "10.0.0.2",
            env,
            Path("wenv"),
            "",
            set_env_var_fn=lambda *_a, **_k: None,
            log=log,
        )

    log.error.assert_called_once()


@pytest.mark.asyncio
async def test_deploy_remote_worker_source_env_missing_wheels_raise(tmp_path):
    dist_abs = tmp_path / "dist"
    dist_abs.mkdir(parents=True, exist_ok=True)
    (dist_abs / "demo_worker-0.0.1.egg").write_text("egg", encoding="utf-8")
    agi_env = tmp_path / "agi_env"
    agi_node = tmp_path / "agi_node"
    (agi_env / "dist").mkdir(parents=True, exist_ok=True)
    (agi_node / "dist").mkdir(parents=True, exist_ok=True)
    (agi_node / "dist" / "agi_node-0.0.1-py3-none-any.whl").write_text("whl", encoding="utf-8")

    env = SimpleNamespace(
        wenv_abs=tmp_path / "wenv",
        wenv_rel=Path("wenv"),
        dist_rel=Path("wenv/dist"),
        dist_abs=dist_abs,
        pyvers_worker="3.13",
        envars={},
        uv_worker="uv",
        is_source_env=True,
        app="demo_app",
        target_worker="demo_worker",
        agi_env=agi_env,
        agi_node=agi_node,
        post_install_rel="demo.post_install",
        verbose=0,
    )

    async def _fake_send(*_args, **_kwargs):
        return None

    agi_cls = SimpleNamespace(
        _rapids_enabled=False,
        _workers_data_path=None,
        exec_ssh=_fake_send,
        send_files=_fake_send,
        send_file=_fake_send,
    )

    with pytest.raises(FileNotFoundError, match="agi_env"):
        await _call_deploy_remote_worker(
            agi_cls,
            "10.0.0.2",
            env,
            Path("wenv"),
            "",
            set_env_var_fn=lambda *_a, **_k: None,
            log=mock.Mock(),
        )

    (agi_env / "dist" / "agi_env-0.0.1-py3-none-any.whl").write_text("whl", encoding="utf-8")
    (agi_node / "dist" / "agi_node-0.0.1-py3-none-any.whl").unlink()
    with pytest.raises(FileNotFoundError, match="agi_node"):
        await _call_deploy_remote_worker(
            agi_cls,
            "10.0.0.2",
            env,
            Path("wenv"),
            "",
            set_env_var_fn=lambda *_a, **_k: None,
            log=mock.Mock(),
        )


@pytest.mark.asyncio
async def test_deploy_remote_worker_non_source_missing_egg_raises(tmp_path):
    dist_abs = tmp_path / "dist"
    dist_abs.mkdir(parents=True, exist_ok=True)
    env = SimpleNamespace(
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
    )
    agi_cls = SimpleNamespace(
        _rapids_enabled=False,
        _workers_data_path=None,
        exec_ssh=lambda *_a, **_k: None,
        send_files=lambda *_a, **_k: None,
        send_file=lambda *_a, **_k: None,
    )
    log = mock.Mock()

    with pytest.raises(FileNotFoundError, match="no existing egg file"):
        await _call_deploy_remote_worker(
            agi_cls,
            "10.0.0.2",
            env,
            Path("worker_env"),
            "",
            set_env_var_fn=lambda *_a, **_k: None,
            log=log,
        )

    log.error.assert_called_once()


@pytest.mark.asyncio
async def test_deploy_remote_worker_rapids_false_and_temp_pth_cleanup_missing(monkeypatch, tmp_path):
    dist_abs = tmp_path / "dist"
    dist_abs.mkdir(parents=True, exist_ok=True)
    (dist_abs / "demo_worker-0.0.1.egg").write_text("egg", encoding="utf-8")

    env = SimpleNamespace(
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
        hw_rapids_capable=None,
    )
    ssh_calls = []
    env_vars = []

    async def _fake_exec(ip, cmd):
        ssh_calls.append((ip, cmd))
        if cmd.strip() == "nvidia-smi":
            return ""
        return "ok"

    async def _fake_send(_env, ip, files, remote_path, user=None, password=None):
        del _env, ip, files, remote_path, user, password

    original_unlink = Path.unlink

    def _patched_unlink(self, *args, **kwargs):
        if self.name.startswith("agilab_uv_sources_"):
            raise FileNotFoundError(self)
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", _patched_unlink)

    agi_cls = SimpleNamespace(
        _rapids_enabled=True,
        _workers_data_path=None,
        exec_ssh=_fake_exec,
        send_files=_fake_send,
        send_file=_fake_send,
    )

    await _call_deploy_remote_worker(
        agi_cls,
        "10.0.0.2",
        env,
        Path("worker_env"),
        "",
        set_env_var_fn=lambda *args: env_vars.append(args),
        log=mock.Mock(),
    )

    assert any(cmd == "nvidia-smi" for _ip, cmd in ssh_calls)
    assert env.hw_rapids_capable is False
    assert env_vars == []


@pytest.mark.asyncio
async def test_deploy_remote_worker_rapids_runtime_error_is_logged(tmp_path):
    dist_abs = tmp_path / "dist"
    dist_abs.mkdir(parents=True, exist_ok=True)
    (dist_abs / "demo_worker-0.0.1.egg").write_text("egg", encoding="utf-8")

    env = SimpleNamespace(
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
    )

    async def _fake_exec(_ip, cmd):
        if cmd.strip() == "nvidia-smi":
            raise RuntimeError("nvidia-smi unavailable")
        return "ok"

    async def _fake_send(*_args, **_kwargs):
        return None

    agi_cls = SimpleNamespace(
        _rapids_enabled=True,
        _workers_data_path=None,
        exec_ssh=_fake_exec,
        send_files=_fake_send,
        send_file=_fake_send,
    )
    log = mock.Mock()

    with pytest.raises(RuntimeError, match="nvidia-smi unavailable"):
        await _call_deploy_remote_worker(
            agi_cls,
            "10.0.0.2",
            env,
            Path("worker_env"),
            "",
            set_env_var_fn=lambda *_a, **_k: None,
            log=log,
        )

    log.error.assert_called_once()
