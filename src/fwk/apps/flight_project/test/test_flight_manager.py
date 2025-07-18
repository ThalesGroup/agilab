import pytest
from datetime import date
from agi_env import AgiEnv
from flight import Flight

@pytest.fixture
def flight():
    env = AgiEnv(active_app='flight', verbose=True)
    return Flight(
        env=env,
        verbose=True,
        data_source="file",
        path="data/flight/dataset",
        files="csv/*",
        nfile=1,
        nskip=0,
        nread=0,
        sampling_rate=10.0,
        datemin=date(2020, 1, 1),
        datemax=date(2021, 1, 1),
        output_format="parquet"
    )

@pytest.mark.asyncio
async def test_build_distribution(flight):
    workers = {'worker1': 2, 'worker2': 3}
    result = flight.build_distribution(workers)
    print(result)  # Optionnel, à retirer en prod
    assert result is not None
    # Ajoute d'autres assert selon ce que tu attends de `result`
