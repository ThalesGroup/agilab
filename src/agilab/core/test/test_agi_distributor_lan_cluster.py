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


async def _scheduler_info_workers():
    info = AGI._dask_client.scheduler_info()
    if inspect.isawaitable(info):
        info = await info
    return info.get("workers", {})


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

    AGI.env = env
    AGI._ssh_connections = {}
    AGI._dask_client = None

    for ip in workers:
        await _assert_remote_ssh_ready(ip)

    await AGI.install(env, scheduler=scheduler_ip, workers=workers, verbose=1)

    started = False
    try:
        started = await AGI._start(scheduler_ip)
        assert started is True
        await AGI._sync()

        connected_workers = await _scheduler_info_workers()
        assert len(connected_workers) >= sum(workers.values())

        hostnames = await AGI._dask_client.run(socket.gethostname)
        assert len(hostnames) >= sum(workers.values())
        assert all(isinstance(host, str) and host for host in hostnames.values())
    finally:
        if started and AGI._dask_client is not None:
            await AGI._stop()
