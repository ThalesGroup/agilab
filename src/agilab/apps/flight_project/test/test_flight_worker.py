import sys
from agi_core.workers.agi_worker import AgiWorker
from agi_env import AgiEnv, normalize_path

args = {
    'data_source': "file",
    'path': "data/flight/dataset",
    'files': "csv/*",
    'nfile': 1,
    'nskip': 0,
    'nread': 0,
    'sampling_rate': 10.0,
    'datemin': "2020-01-01",
    'datemax': "2021-01-01",
    'output_format': "csv"
}

sys.path.insert(0,'/home/pcm/PycharmProjects/agilab/src/agilab/apps/flight_project/src')
sys.path.insert(0,'/home/pcm/wenv/flight_worker/dist')

# AgiWorker.run flight command
for i in  range(4):
    env = AgiEnv(install_type=1,active_app="flight_project",verbose=True)
    AgiWorker.new("flight_project", mode=i, env=env, verbose=3, args=args)
    result = AgiWorker.run(workers={"192.168.20.123":2}, mode=i, args=args)
    print(result)
