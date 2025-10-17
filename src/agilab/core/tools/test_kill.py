import runpy
from agi_env import AgiEnv

apps_dir = AgiEnv.locate_agi_installation(verbose=0) / "apps"
env = AgiEnv(apps_dir=apps_dir, app="flight_project", verbose=1)
runpy.run_path(env.agi_cluster / "src/cluster/cli.py")
