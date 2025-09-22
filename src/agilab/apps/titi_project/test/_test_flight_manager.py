import asyncio
from agi_env import AgiEnv
from titi import Titi
from datetime import date
from pathlib import Path


async def main():
    env = AgiEnv(active_app=Path(__file__).expanduser().parents[1], verbose
        =True)
    titi = Titi(env=env, data_source='file', data_uri='data/titi/dataset',
        files='csv/*', nfile=1, nskip=0, nread=0, sampling_rate=10.0,
        datemin=date(2020, 1, 1), datemax=date(2021, 1, 1), output_format=
        'parquet')
    workers = {'worker1': 2, 'worker2': 3}
    result = titi.build_distribution(workers)
    print(result)


if __name__ == '__main__':
    asyncio.run(main())
