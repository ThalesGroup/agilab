import asyncio
import sys
from agi_core.managers.agi_runner import AGI


async def main(method_name):
    # Retrieve the method using getattr
    try:
        method = getattr(AGI, method_name)
    except AttributeError:
        raise ValueError(f"AGI has no method named '{method_name}'")

    if method_name == "install":
        res = await method('my_code', verbose=3, modes_enabled=0b0111, list_ip=None)
    elif method_name == "distribute":
        res = await method('my_code', verbose=True)
    elif method_name == "run":
        res = await method('my_code', mode=3, verbose=True)
    else:
        raise ValueError("Unknown method name")
    print(res)

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: script.py <method_name>")
        sys.exit(1)
    method_name = sys.argv[1]
    asyncio.run(main(method_name))