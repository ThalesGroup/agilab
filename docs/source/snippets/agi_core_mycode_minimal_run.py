from agi_cluster.agi_distributor import AGI, RunRequest

request = RunRequest(
    scheduler="127.0.0.1",
    workers={"127.0.0.1": 1},
    mode=AGI.PYTHON_MODE,
)
result = await AGI.run(app_env, request=request)
result
