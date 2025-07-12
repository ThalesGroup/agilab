import pytest
from datetime import date
from agi_env import AgiEnv
from link_sim import LinkSim

@pytest.fixture
def flight():
    env = AgiEnv(active_app='link_sim', verbose=True)
    return LinkSim(
        env=env,
        verbose=True,
        path='~/data/link_sim',
        data_out='~/data/link_sim/dataframe',
        data_dir='~/data/link_sim/dataset',
        data_flight='flights',
        data_sat='sat',
        plane_conf_path=('plane_conf.json',),
    )

@pytest.mark.asyncio
async def test_build_distribution(flight):
    workers = {'worker1': 2, 'worker2': 3}
    result = flight.build_distribution(workers)
    print(result)  # Optionnel, à retirer en prod
    assert result is not None
    # Ajoute d'autres assert selon ce que tu attends de `result`
