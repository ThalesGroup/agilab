import sys
from agi_manager import BaseWorker
from agi_env import AgiEnv, normalize_path

args = {
    'param1': 0,
    'param2': "some text",
    'param3': 3.14,
    'param4': True
}

sys.path.insert(0,'/home/pcm/PycharmProjects/agilab/src/agi/apps/mycode_project/src')
sys.path.insert(0,'/home/pcm/wenv/mycode_worker/dist')


# BaseWorker.run flight command
for i in  range(4):
    env = AgiEnv(install_type=1,active_app="mycode_project",verbose=True)
    BaseWorker.new('mycode', mode=i, env=env, verbose=3, args=args)
    result = BaseWorker.run(workers={"192.168.20.222":2}, mode=i, args=args)

print(result)