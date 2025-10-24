import runpy
from agi_env import AgiEnv

# Prefer modern module invocation over filesystem paths
apps_dir = AgiEnv.locate_agi_installation(verbose=0) / "apps"
env = AgiEnv(apps_dir=apps_dir, app="flight_project", verbose=1)

# Execute the distributor CLI via its module entrypoint
runpy.run_module("agi_cluster.agi_distributor.cli", run_name="__main__")
