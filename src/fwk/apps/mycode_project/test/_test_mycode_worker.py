import sys
from pathlib import Path
from agi_manager import BaseWorker
from agi_env import AgiEnv


with open(Path().home() / ".local/share/agilab/.core-path",'r') as f:
    fwk_path = Path(f.read().strip())

path = str(fwk_path / "core/node/src")
if path not in sys.path:
    sys.path.insert(0, path)

path = str(fwk_path / "core/env/src")
if path not in sys.path:
    sys.path.insert(0, path)

args = {
    'param1': 0,
    'param2': "some text",
    'param3': 3.14,
    'param4': True
}

sys.path.insert(0,'/home/pcm/PycharmProjects/agilab/src/fwk/apps/mycode_project/src')
sys.path.insert(0,'/home/pcm/wenv/mycode_worker/dist')


# BaseWorker.run flight command
for i in  [0,1,3]: # 2 is working only if you have generate the cython lib before
    env = AgiEnv(install_type=1,active_app="mycode_project",verbose=True)
    BaseWorker.new('mycode', mode=i, env=env, verbose=3, args=args)
    result = BaseWorker.run(mode=i, args=args)

print(result)