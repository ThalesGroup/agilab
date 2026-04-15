from pathlib import Path
from types import SimpleNamespace

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
