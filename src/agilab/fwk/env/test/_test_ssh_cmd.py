import asyncio
from pathlib import Path
import os
from agi_env import AgiEnv, normalize_path

async def test_ssh_cmd(env, ip, usr, cmd):
    env.user = usr
    return await env.exec_ssh(ip, cmd)

async def main():
    env = AgiEnv(install_type=1, verbose=1)

    cwd = Path().home()
    os.chdir(cwd)
    module='flight'
    wenv =  env.wenv_rel
    dist = wenv / "dist"
    cmd = (
        f"uv -q --project {wenv} run python -c "
        f"\"from pathlib import Path; "
        f"whl = list((Path().home() / '{dist}').glob('{module}*.whl')); "
        f"print(whl)\""
    )
    # Safe quoting for remote shell execution:
    #cmd = f"cd {env.wenv_rel} && uv run python -c \"import os; print(os.getcwd())\""
    ip = '192.168.20.222'
    usr = 'nsbl'

    res = await test_ssh_cmd(env, ip, usr, cmd)
    print(res)

if __name__ == '__main__':
    asyncio.run(main())
