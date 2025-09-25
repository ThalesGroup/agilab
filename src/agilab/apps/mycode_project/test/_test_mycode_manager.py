import asyncio
from agi_env import AgiEnv
from mycode import Mycode  # assuming your Mycode class is here
from mycode.mycode_args import MycodeArgs
from pathlib import Path

async def main():
    env = AgiEnv(active_app=Path(__file__).expanduser().parents[1], verbose=True)

    # Instantiate Mycode with your parameters
    mycode = Mycode(
        env=env,
        args=MycodeArgs(),
    )

    # Example list of workers to pass to build_distribution
    workers = {'worker1': 2, 'worker2': 3}

    # Call build_distribution (await if async)
    result = mycode.build_distribution(workers)

    print(result)


if __name__ == '__main__':
    asyncio.run(main())
