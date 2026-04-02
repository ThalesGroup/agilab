import inspect
import os
import socket
from pathlib import Path

import pytest

from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv

_LAN_CLUSTER_ENABLED = os.environ.get("AGILAB_RUN_LAN_CLUSTER_TESTS", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
_LAN_CLUSTER_IPS = [
    ip.strip()
    for ip in os.environ.get("AGILAB_LAN_CLUSTER_IPS", "192.168.20.111,192.168.20.130").split(",")
    if ip.strip()
]
_LAN_CLUSTER_CREDENTIALS = os.environ.get("AGILAB_LAN_CLUSTER_CREDENTIALS", "").strip()
_LAN_CLUSTER_SSH_KEY_PATH = os.environ.get("AGILAB_LAN_CLUSTER_SSH_KEY_PATH", "").strip()


def _apply_live_credentials(env: AgiEnv) -> None:
    """Override cluster auth from process env for manual LAN regressions."""

    if _LAN_CLUSTER_CREDENTIALS:
        user, sep, password = _LAN_CLUSTER_CREDENTIALS.partition(":")
        env.user = user.strip() or env.user
        env.password = password if sep else None

    if _LAN_CLUSTER_SSH_KEY_PATH:
        env.ssh_key_path = str(Path(_LAN_CLUSTER_SSH_KEY_PATH).expanduser())


async def _scheduler_info_workers():
    info = AGI._dask_client.scheduler_info()
    if inspect.isawaitable(info):
        info = await info
    return info.get("workers", {})


async def _client_run(fn):
    result = AGI._dask_client.run(fn)
    if inspect.isawaitable(result):
        result = await result
    return result


async def _assert_remote_ssh_ready(ip: str) -> None:
    if AgiEnv.is_local(ip):
        return
    try:
        probe = await AGI.exec_ssh(ip, "echo agi-cluster-ready")
    except Exception as exc:  # pragma: no cover - exercised only on live LAN runs
        pytest.fail(
            f"SSH access to {ip} is required for the LAN cluster regression: {exc}"
        )
    assert probe.strip() == "agi-cluster-ready"


@pytest.mark.asyncio
@pytest.mark.skipif(
    not _LAN_CLUSTER_ENABLED,
    reason="Set AGILAB_RUN_LAN_CLUSTER_TESTS=1 to exercise the live LAN cluster regression.",
)
@pytest.mark.parametrize("scheduler_ip", _LAN_CLUSTER_IPS)
async def test_lan_cluster_scheduler_rotation_smoke(scheduler_ip):
    workers = {ip: 1 for ip in _LAN_CLUSTER_IPS}
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=1)
    _apply_live_credentials(env)

    AGI.env = env
    AGI._ssh_connections = {}
    AGI._dask_client = None

    for ip in workers:
        await _assert_remote_ssh_ready(ip)

    await AGI.install(env, scheduler=scheduler_ip, workers=workers, verbose=1)

    started = False
    try:
        await AGI._start(scheduler_ip)
        started = AGI._dask_client is not None
        assert started
        await AGI._sync()

        connected_workers = await _scheduler_info_workers()
        assert len(connected_workers) >= sum(workers.values())

        hostnames = await _client_run(socket.gethostname)
        assert len(hostnames) >= sum(workers.values())
        assert all(isinstance(host, str) and host for host in hostnames.values())
    finally:
        if started and AGI._dask_client is not None:
            await AGI._stop()
