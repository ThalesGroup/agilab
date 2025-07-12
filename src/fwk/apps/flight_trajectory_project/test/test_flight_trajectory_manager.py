import pytest
from datetime import date
from agi_env import AgiEnv
from flight_trajectory import FlightTrajectory

@pytest.fixture
def flight():
    env = AgiEnv(active_app='flight_trajectory', verbose=True)
    return FlightTrajectory(
        env=env,
        verbose=True,
        path='~/data/flight_trajectory',
        data_out="~/data/flight_trajectory/dataframe",
        data_dir="~/data/flight_trajectory/dataset",
        waypoints='waypoints.geojson'
    )

@pytest.mark.asyncio
async def test_build_distribution(flight):
    workers = {'worker1': 2, 'worker2': 3}
    result = flight.build_distribution(workers)
    print(result)  # Optionnel, à retirer en prod
    assert result is not None
    # Ajoute d'autres assert selon ce que tu attends de `result`
