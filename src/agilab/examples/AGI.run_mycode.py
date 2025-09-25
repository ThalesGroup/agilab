
import asyncio
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv, normalize_path
from pathlib import Path

async def main():
    app_env = AgiEnv(active_app=Path('/Users/jpm/agilab/src/agilab/apps/mycode_project'), install_type=1, verbose=1) 
    res = await AGI.run(app_env, 
                        mode=0, 
                        scheduler=None, 
                        workers=None, 
                        param1=0, param2="some text", param3=3.14, param4=True)
    print(res)
    return res

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())