import pytest
from agi_env import AgiEnv
from mycode import Mycode

@pytest.mark.asyncio
async def test_mycode_build_distribution():
    env = AgiEnv(active_app='mycode', verbose=True)

    mycode = Mycode(
        env=env,
        verbose=True,
    )

    workers = {'worker1': 2, 'worker2': 3}

    # If build_distribution is asynchronous
    result = mycode.build_distribution(workers)

    print(result)  # For debug; remove in production tests

    # Minimal assertion; adapt as needed
    assert result is not None
