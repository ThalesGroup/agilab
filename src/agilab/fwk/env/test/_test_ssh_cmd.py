import asyncio
from agi_env import AgiEnv, normalize_path

async def test_ssh_cmd(env, ip, usr, cmd):
    env.user = usr
    return await env.exec_ssh(ip, cmd)

async def main():
    env = AgiEnv(install_type=1, verbose=1)

    cmd = (
        'python3 -c "import getpass, os, psutil;'
        'me = getpass.getuser();\n'
        'for p in psutil.process_iter(["name", "username", "cmdline"]):\n'
        '    try:\n'
        '        if p.info["username"] and me in p.info["username"]\n'
        '            and ("dask" in p.info["name"] or (p.info["cmdline"]\n'
        '            and any("dask" in s.lower() for s in p.info["cmdline"])))'
        '                p.kill()\n'
        '    except (psutil.NoSuchProcess, psutil.AccessDenied):\n'
        '        pass"'
    )
    # Safe quoting for remote shell execution:
    #cmd = f"cd {env.wenv_rel} && uv run python -c \"import os; print(os.getcwd())\""
    ip = '192.168.20.222'
    usr = 'nsbl'

    res = await test_ssh_cmd(env, ip, usr, cmd)
    print(res)

if __name__ == '__main__':
    asyncio.run(main())
