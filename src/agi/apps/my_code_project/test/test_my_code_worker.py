import sys
from agi_core.workers.agi_worker import AgiWorker
from agi_env import AgiEnv, normalize_path

args = {
    'param1': 0,
    'param2': "some text",
    'param3': 3.14,
    'param4': True
}

sys.path.insert(0,'/home/pcm/PycharmProjects/agilab/src/agilab/apps/my_code_project/src')
sys.path.insert(0,'/home/pcm/wenv/my_code_worker/dist')


# AgiWorker.run flight command
for i in  range(4):
    env = AgiEnv(install_type=1,active_app="my_code_project",verbose=True)
    AgiWorker.new('my_code', mode=i, env=env, verbose=3, args=args)
    result = AgiWorker.run(workers={"192.168.20.222":2}, mode=i, args=args)

print(result)