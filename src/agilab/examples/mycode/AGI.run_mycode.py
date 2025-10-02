
import asyncio
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv, normalize_path
from pathlib import Path

APPS_ROOT = Path(__file__).resolve().parents[2] / "apps"

async def main():
    app_env = AgiEnv(apps_dir=APPS_ROOT, active_app='mycode_project', verbose=True)
    res = await AGI.run(app_env, 
                        mode=None,
                        scheduler="127.0.0.1", 
                        workers={'127.0.0.1': 2}, 
                        param1=0, param2="some text", param3=3.14, param4=True)
    print(res)
    return res

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
