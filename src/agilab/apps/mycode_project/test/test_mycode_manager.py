import sys
from pathlib import Path
import pytest
from agi_env import AgiEnv
path = str(Path(__file__).expanduser().parents[1]  / "src")
if path not in sys.path:
    sys.path.append(path)
from mycode import Mycode
from mycode.mycode_args import MycodeArgs

@pytest.mark.asyncio
async def test_mycode_build_distribution():
    active_app = Path(__file__).expanduser().parents[1]
    env = AgiEnv(active_app=active_app, verbose=True)

    mycode = Mycode(
        env=env,
        args=MycodeArgs(),
    )

    workers = {'worker1': 2, 'worker2': 3}

    # If build_distribution is asynchronous
    result = mycode.build_distribution(workers)

    print(result)  # For debug; remove in production tests

    # Minimal assertion; adapt as needed
    assert result is not None
