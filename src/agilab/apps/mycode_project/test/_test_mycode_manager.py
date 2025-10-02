import asyncio
from agi_env import AgiEnv
from mycode import Mycode  # assuming your Mycode class is here
from pathlib import Path


async def main():
    script_path = Path(__file__).resolve()
    env = AgiEnv(apps_dir=script_path.parents[2], active_app=script_path.parents[1].name, verbose=True)

    # Instantiate Mycode with your parameters
    mycode = Mycode(
        env=env,
        verbose=True,
    )

    # Example list of workers to pass to build_distribution
    workers = {'worker1': 2, 'worker2': 3}

    # Call build_distribution (await if async)
    result = mycode.build_distribution(workers)

    print(result)


if __name__ == '__main__':
    asyncio.run(main())
