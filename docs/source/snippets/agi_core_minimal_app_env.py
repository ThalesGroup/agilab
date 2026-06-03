from agi_cluster.agi_distributor import AGI
from agilab.notebook_demo import notebook_agi_core_context

APP = "minimal_app_project"  # built-in Minimal App example app
context = notebook_agi_core_context(APP, verbose=1)
app_env = context.app_env
request = context.request
print("App:", context.app)
print("Log root:", context.log_root)
