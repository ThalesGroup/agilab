
import asyncio
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv, normalize_path
from pathlib import Path

async def main():
    app_env = AgiEnv(active_app=Path('/Users/jpm/agilab/src/agilab/apps/mycode_project'), install_type=1, verbose=True)
    res = await AGI.distribute(app_env, verbose=True, 
                                scheduler="127.0.0.1", workers={'127.0.0.1': 2}, param1=0, param2="some text", param3=3.14, param4=True)