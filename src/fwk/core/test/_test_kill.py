import runpy
from agi_env import AgiEnv

env = AgiEnv(active_app="flight", install_type=1, verbose=1)
runpy.run_path(env.cluster_root / "src/cluster/cli.py")
