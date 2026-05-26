from agi_cluster.agi_distributor import AGI
from agilab.notebook_demo import (
    notebook_app_env,
    notebook_local_request,
    notebook_log_root,
)

APP = "mycode_project"  # built-in MyCode example app
app_env = notebook_app_env(APP, verbose=1)
request = notebook_local_request()
print("App:", app_env.app)
print("Log root:", notebook_log_root(app_env))
