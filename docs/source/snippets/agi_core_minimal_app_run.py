from agilab.notebook_demo import install_if_needed

await install_if_needed(app_env, request=request)
result = await AGI.run(app_env, request=request)
result
