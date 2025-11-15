import asyncio
from agi_env import AgiEnv
from flight_clone import FlightClone, FlightCloneArgs
from pathlib import Path


async def main():
    active_app = Path(__file__).expanduser().parents[1]
    env = AgiEnv(active_app=active_app, verbose=True)
    flight_clone = FlightClone(env=env, args=FlightCloneArgs(data_in=
        'flight_clone/dataset', waypoints='waypoints.geojson'))
    workers = {'worker1': 2, 'worker2': 3}
    result = flight_clone.build_distribution(workers)
    print(result)


if __name__ == '__main__':
    asyncio.run(main())
