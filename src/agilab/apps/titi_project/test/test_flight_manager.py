import sys
from pathlib import Path
import pytest
from datetime import date
from agi_env import AgiEnv
active_app = Path(__file__).expanduser().parents[1]
path = str(active_app / 'src')
if path not in sys.path:
    sys.path.append(path)
from titi import Titi


@pytest.fixture
def titi():
    env = AgiEnv(active_app=active_app, verbose=True)
    return Titi(env=env, verbose=True, data_source='file', data_uri=
        'data/titi/dataset', files='csv/*', nfile=1, nskip=0, nread=0,
        sampling_rate=10.0, datemin=date(2020, 1, 1), datemax=date(2021, 1,
        1), output_format='parquet')


@pytest.mark.asyncio
async def test_build_distribution(titi):
    workers = {'worker1': 2, 'worker2': 3}
    result = titi.build_distribution(workers)
    print(result)
    assert result is not None
