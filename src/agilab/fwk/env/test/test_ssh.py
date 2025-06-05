import pytest
from agi_env import AgiEnv

@pytest.fixture(scope="module")
def env():
    agipath = AgiEnv.locate_agi_installation(verbose=0)
    return AgiEnv(active_app="flight", apps_dir=agipath / "apps", install_type=1, verbose=1)

async def exec_ssh_cmd(env, ip, cmd):
    return await env.exec_ssh(ip, cmd)

@pytest.mark.asyncio
async def test_exec_ssh_1(env):
    # Safe quoting for remote shell execution:
    cmd = f"cd {env.wenv_rel} && python3 -c \"import os; print(os.getcwd())\""
    ip = '192.168.20.224'

    res = await exec_ssh_cmd(env, ip,cmd)
    print(res)
