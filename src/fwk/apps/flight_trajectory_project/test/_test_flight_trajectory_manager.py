# import asyncio
# import sys
# from agi-core.managers import AGI
#
#
# async def main(method_name):
#     try:
#         method = getattr(AGI, method_name)
#     except AttributeError:
#         print(f"AGI has no method named '{method_name}'")
#         exit(1)
#     if method_name == 'install':
#         res = await method('flight_trajectory', verbose=3, modes_enabled=7,
#             list_ip=None)
#     elif method_name == 'distribute':
#         res = await method('flight_trajectory', verbose=True, data_source='file',
#             path='~/data/flight_trajectory/dataset', files='csv/*', nfile=1,
#             nskip=0, nread=0, sampling_rate=10.0, datemin='2020-01-01',
#             datemax='2021-01-01', output_format='parquet')
#     elif method_name == 'run':
#         res = await method('flight_trajectory', mode=3, verbose=True,
#             data_source='file', path='~/data/flight_trajectory/dataset', files=
#             'csv/*', nfile=1, nskip=0, nread=0, sampling_rate=10.0, datemin
#             ='2020-01-01', datemax='2021-01-01', output_format='parquet')
#     else:
#         raise ValueError('Unknown method name')
#     print(res)
#
#
# if __name__ == '__main__':
#     if len(sys.argv) < 2:
#         print('Usage: test_flight_trajectory_manager.py <method_name>')
#         sys.exit(1)
#     method_name = sys.argv[1]
#     asyncio.run(main(method_name))

import asyncio
from agi_env import AgiEnv
from flight_trajectory import FlightTrajectory
from datetime import date

async def main():
    env = AgiEnv(active_app='flight_trajectory', verbose=True)

    # Instantiate Flight with your parameters
    flight_trajectory = FlightTrajectory(
        env=env,
        verbose=True,
        path = '~/data/flight_trajectory',
        data_out = "~/data/flight_trajectory/dataframe",
        data_dir = "~/data/flight_trajectory/dataset",
        waypoints = 'waypoints.geojson'
    )

    # Example list of workers to pass to build_distribution
    workers = {'worker1':2, 'worker2':3}

    # Call build_distribution (await if async)
    result = flight_trajectory.build_distribution(workers)

    print(result)

if __name__ == '__main__':
    asyncio.run(main())