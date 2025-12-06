from agi_env import AgiEnv
from agi_cluster.agi_distributor import cli as distributor_cli

# Ensure environment resolves, but avoid invoking the CLI with no args
apps_path = AgiEnv.locate_agi_installation(verbose=0) / "apps"
env = AgiEnv(apps_path=apps_path, app="flight_project", verbose=1)

# Call a harmless function to validate importability
_ = distributor_cli.python_version()
