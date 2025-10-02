import sys
from pathlib import Path
import pytest
from datetime import date
from agi_env import AgiEnv

script_path = Path(__file__).resolve()
apps_dir = script_path.parents[2]
active_app_path = script_path.parents[1]
path = str(active_app_path / "src")
if path not in sys.path:
    sys.path.append(path)
from mycode import Mycode

@pytest.mark.asyncio
async def test_mycode_build_distribution():
    env = AgiEnv(apps_dir=apps_dir, active_app=active_app_path.name, verbose=True)

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
