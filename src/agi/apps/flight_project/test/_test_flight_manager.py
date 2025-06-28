import asyncio
import sys
from agi_runner import AGI
from agi_env import AgiEnv


async def main(method_name):
    # Get the method from Agi based on the string
    try:
        method = getattr(AGI, method_name)
    except AttributeError:
        print(f"AGI has no method named '{method_name}'")
        exit(1)
    env = AgiEnv(active_app="flight", install_type=1, verbose=True)
    cmd = f"{env.uv} run python build.py build_ext --packages 'base_worker, polars_worker' -b {env.wenv_abs}"
    await AgiEnv.run(cmd, env.wenv_abs)

    if method_name == "install":
        res = await method('flight', verbose=3, modes_enabled=0b0111, list_ip=None)
    elif method_name == "distribute":
        res = await method(
            'flight',
            env=env,
            verbose=True,
            data_source="file",
            path="data/flight/dataset",
            files="csv/*",
            nfile=1, nskip=0, nread=0,
            sampling_rate=10.0,
            datemin="2020-01-01",
            datemax="2021-01-01",
            output_format="parquet"
        )
    elif method_name == "run":
        res = await method(
            'flight',
            env=env,
            mode=3,
            verbose=True,
            data_source="file",
            path="data/flight/dataset",
            files="csv/*",
            nfile=1, nskip=0, nread=0,
            sampling_rate=10.0,
            datemin="2020-01-01",
            datemax="2021-01-01",
            output_format="parquet"
        )
    else:
        raise ValueError("Unknown method name")

    print(res)

if __name__ == '__main__':
    method_name = None
    if len(sys.argv) < 2:
        print("Usage: _test_flight_manager.py <method_name>")
    else:
        method_name = sys.argv[1]
    if not method_name:
        method_name = "run"
    asyncio.run(main(method_name))