import asyncio
from pathlib import Path
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv

async def main():
    env = AgiEnv(active_app=Path('/Users/jpm/agi-space/apps/flight_project'), install_type=0, verbose=1)
    return await AGI.install(
        env,
        modes_enabled=4,
        scheduler='127.0.0.1',
        workers={'127.0.0.1': 2},
    )

if __name__ == '__main__':
    print(asyncio.run(main()))
