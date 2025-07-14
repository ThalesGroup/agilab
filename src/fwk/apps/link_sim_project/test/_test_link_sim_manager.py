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
#         res = await method('link_sim', verbose=3, modes_enabled=7, list_ip=None)
#     elif method_name == 'distribute':
#         res = await method('link_sim', verbose=True, data_source='file',
#             path='data/link_sim/dataset', files='csv/*', nfile=1, nskip=0,
#             nread=0, sampling_rate=10.0, datemin='2020-01-01', datemax=
#             '2021-01-01', output_format='parquet', flight_id=0, data_flight
#             ='data', plane_conf_path='plane_conf.json', data_dir=
#             '~/data/link_sim/dataset', data_out='~/data/link_sim/dataframe')
#     elif method_name == 'run':
#         res = await method('link_sim', mode=3, verbose=True, data_source=
#             'file', path='data/link_sim/dataset', files='csv/*', nfile=1,
#             nskip=0, nread=0, sampling_rate=10.0, datemin='2020-01-01',
#             datemax='2021-01-01', output_format='parquet', flight_id=0,
#             data_flight='data', plane_conf_path='plane_conf.json', data_dir
#             ='~/data/link_sim/dataset', data_out='~/data/link_sim/dataframe')
#     else:
#         raise ValueError('Unknown method name')
#     print(res)
#
#
# if __name__ == '__main__':
#     if len(sys.argv) < 2:
#         print('Usage: test_link_sim_manager.py <method_name>')
#         sys.exit(1)
#     method_name = sys.argv[1]
#     asyncio.run(main(method_name))

import asyncio
from agi_env import AgiEnv
from link_sim import LinkSim
from datetime import date

async def main():
    env = AgiEnv(active_app='link_sim', verbose=True)

    # Instantiate Flight with your parameters
    link_sim = LinkSim(
        env=env,
        verbose=True,
        path = '~/data/link_sim',
        data_out = '~/data/link_sim/dataframe',
        data_dir = '~/data/link_sim/dataset',
        data_flight = 'flights',
        data_sat = 'sat',
        plane_conf_path = ('plane_conf.json',),
    )

    # Example list of workers to pass to build_distribution
    workers = {'worker1':2, 'worker2':3}

    # Call build_distribution (await if async)
    result = link_sim.build_distribution(workers)

    print(result)

if __name__ == '__main__':
    asyncio.run(main())
