import asyncio
import sys
from agi_core.managers import AGI



async def main(method_name):
    # Get the method from Agi based on the string
    try:
        method = getattr(AGI, method_name)
    except AttributeError:
        print(f"AGI has no method named '{method_name}'")
        exit(1)

    if method_name == "install":
        res = await method('flight', verbose=3, modes_enabled=0b0111, list_ip=None)
    elif method_name == "distribute":
        res = await method(
            'flight',
            verbose=True,
            data_source="file",
            path="~/data/flight/dataset",
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
            mode=3,
            verbose=True,
            data_source="file",
            path="~/data/flight/dataset",
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
    if len(sys.argv) < 2:
        print("Usage: test_flight_manager.py <method_name>")
        sys.exit(1)
    method_name = sys.argv[1]
    asyncio.run(main(method_name))