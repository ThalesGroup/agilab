import asyncio

from agi_cluster.agi_distributor import AGI


async def main():
    result = await AGI.run(
        app_env,
        scheduler="127.0.0.1",
        workers={"127.0.0.1": 1},
        mode=0,  # plain local Python execution
    )
    print(result)
    return result


if __name__ == "__main__":
    asyncio.run(main())
