import asyncio
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv

SSH_HOST = "192.168.20.111"
SSH_CMD = """        cd ~/PycharmProjects/agilab
        export PATH="~/.local/bin:$PATH"
        uv run python - <<'PY'
        import asyncio
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv

APPS_DIR = "/Users/jpm/PycharmProjects/agilab/src/agilab/apps"
APP = "flight_trajectory_project"

async def main():
    app_env = AgiEnv(apps_dir=APPS_DIR, app=APP, verbose=1)
    res = await AGI.install(app_env,
                            modes_enabled=15,
                            scheduler="192.168.20.111",
                            workers={'192.168.20.130': 1})
    print(res)
    return res

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
        PY"""

async def main():
    app_env = AgiEnv(apps_dir="/Users/jpm/PycharmProjects/agilab/src/agilab/apps", app="flight_trajectory_project", verbose=1)
    AGI.env = app_env
    app_env.user = "agi"
    app_env.password = None
    result = await AGI.exec_ssh(SSH_HOST, SSH_CMD)
    print(result)
    return result

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())