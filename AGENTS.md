# AGILab Run & Troubleshooting Checklist

Use this runbook to launch, validate, and troubleshoot AGILab flows from a single
place. The sections mirror the IDE run configurations so you can copy commands
directly into a shell or Streamlit page. After changing anything under
`.idea/runConfigurations`, regenerate the table below so everyone executes the
same instructions.

> **Tip**
> Update this document whenever a run config, environment variable, or Streamlit
> control changes. CI, reviewers, and support rely on it for reproduction steps.
>
> **Model compatibility check**
> When reviewing or updating flows with GPT-5 Codex agents, confirm they do **not** rely on
> deprecated Streamlit APIs such as `st.experimental_rerun()`. Upgrade callers to the
> supported replacement (`st.rerun`) before merging.

<details>
<summary><strong>Launch matrix (auto-sorted from .idea/runConfigurations)</strong></summary>

| Group | Config name | Entry | Args | Workdir | Env | How to run | Interpreter |
|---|---|---|---|---|---|---|---|
| apps | **Flight** |  |  |  |  |  |  |
| apps | flight AGI.get_distrib | $ProjectFileDir$/src/agilab/examples/flight/AGI.get_distrib_flight.py |  | $ProjectFileDir$/src/agilab/examples/flight | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/examples/flight && uv run python $ProjectFileDir$/src/agilab/examples/flight/AGI.get_distrib_flight.py | uv (flight_project) |
| apps | flight AGI.run | $ProjectFileDir$/src/agilab/examples/flight/AGI.run_flight.py |  | $ProjectFileDir$/src/agilab/apps/flight_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_project && uv run python $ProjectFileDir$/src/agilab/examples/flight/AGI.run_flight.py | uv (flight_project) |
| apps | flight call worker | $ProjectFileDir$/src/agilab/apps/flight_project/test/_test_call_worker.py |  | $ProjectFileDir$/src/agilab/apps/flight_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_project && uv run python $ProjectFileDir$/src/agilab/apps/flight_project/test/_test_call_worker.py | uv (flight_project) |
| apps | flight test manager | $ProjectFileDir$/src/agilab/apps/flight_project/test/_test_flight_manager.py |  | $ProjectFileDir$/src/agilab/apps/flight_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_project && uv run python $ProjectFileDir$/src/agilab/apps/flight_project/test/_test_flight_manager.py | uv (flight_project) |
| apps | flight test worker | $ProjectFileDir$/src/agilab/apps/flight_project/test/_test_flight_worker.py |  | $ProjectFileDir$/src/agilab/apps/flight_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_project && uv run python $ProjectFileDir$/src/agilab/apps/flight_project/test/_test_flight_worker.py | uv (flight_worker) |
| apps | flight tests | $ProjectFileDir$/src/agilab/apps/flight_project/app_test.py |  | $ProjectFileDir$/src/agilab/apps/flight_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_project && uv run python $ProjectFileDir$/src/agilab/apps/flight_project/app_test.py | uv (flight_project) |
| apps | **Flight Trajectory** |  |  |  |  |  |  |
| apps | flight_trajectory AGI.get_distrib | $ProjectFileDir$/src/agilab/examples/flight_trajectory/AGI.get_distrib_flight_trajectory.py |  | $ProjectFileDir$/src/agilab/examples/flight_trajectory | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/examples/flight_trajectory && uv run python $ProjectFileDir$/src/agilab/examples/flight_trajectory/AGI.get_distrib_flight_trajectory.py | uv (flight_trajectory_project) |
| apps | flight_trajectory AGI.run | $ProjectFileDir$/src/agilab/examples/flight_trajectory/AGI.run_flight_trajectory.py |  | $ProjectFileDir$/src/agilab/apps/flight_trajectory_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_trajectory_project && uv run python $ProjectFileDir$/src/agilab/examples/flight_trajectory/AGI.run_flight_trajectory.py | uv (flight_trajectory_project) |
| apps | flight_trajectory call worker | $ProjectFileDir$/src/agilab/apps/flight_trajectory_project/test/_test_call_worker.py |  | $ProjectFileDir$/src/agilab/apps/flight_trajectory_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_trajectory_project && uv run python $ProjectFileDir$/src/agilab/apps/flight_trajectory_project/test/_test_call_worker.py | uv (flight_trajectory_project) |
| apps | flight_trajectory test manager | $ProjectFileDir$/src/agilab/apps/flight_trajectory_project/test/_test_flight_trajectory_manager.py |  | $ProjectFileDir$/src/agilab/apps/flight_trajectory_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_trajectory_project && uv run python $ProjectFileDir$/src/agilab/apps/flight_trajectory_project/test/_test_flight_trajectory_manager.py | uv (flight_trajectory_project) |
| apps | flight_trajectory test worker | $ProjectFileDir$/src/agilab/apps/flight_trajectory_project/test/_test_flight_trajectory_worker.py |  | $ProjectFileDir$/src/agilab/apps/flight_trajectory_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_trajectory_project && uv run python $ProjectFileDir$/src/agilab/apps/flight_trajectory_project/test/_test_flight_trajectory_worker.py | uv (flight_trajectory_worker) |
| apps | flight_trajectory tests | $ProjectFileDir$/src/agilab/apps/flight_trajectory_project/app_test.py |  | $ProjectFileDir$/src/agilab/apps/flight_trajectory_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_trajectory_project && uv run python $ProjectFileDir$/src/agilab/apps/flight_trajectory_project/app_test.py | uv (flight_trajectory_project) |
| apps | **Link Sim** |  |  |  |  |  |  |
| apps | link_sim AGI.get_distrib | $ProjectFileDir$/src/agilab/examples/link_sim/AGI.get_distrib_link_sim.py |  | $ProjectFileDir$/src/agilab/examples/link_sim | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/examples/link_sim && uv run python $ProjectFileDir$/src/agilab/examples/link_sim/AGI.get_distrib_link_sim.py | uv (link_sim_project) |
| apps | link_sim AGI.run | $ProjectFileDir$/src/agilab/examples/link_sim/AGI.run_link_sim.py |  | $ProjectFileDir$/src/agilab/apps/link_sim_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/link_sim_project && uv run python $ProjectFileDir$/src/agilab/examples/link_sim/AGI.run_link_sim.py | uv (link_sim_project) |
| apps | link_sim call worker | $ProjectFileDir$/src/agilab/apps/link_sim_project/test/_test_call_worker.py |  | $ProjectFileDir$/src/agilab/apps/link_sim_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/link_sim_project && uv run python $ProjectFileDir$/src/agilab/apps/link_sim_project/test/_test_call_worker.py | uv (link_sim_project) |
| apps | link_sim test manager | $ProjectFileDir$/src/agilab/apps/link_sim_project/test/_test_link_sim_manager.py |  | $ProjectFileDir$/src/agilab/apps/link_sim_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/link_sim_project && uv run python $ProjectFileDir$/src/agilab/apps/link_sim_project/test/_test_link_sim_manager.py | uv (link_sim_project) |
| apps | link_sim test worker | $ProjectFileDir$/src/agilab/apps/link_sim_project/test/_test_link_sim_worker.py |  | $ProjectFileDir$/src/agilab/apps/link_sim_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/link_sim_project && uv run python $ProjectFileDir$/src/agilab/apps/link_sim_project/test/_test_link_sim_worker.py | uv (link_sim_worker) |
| apps | link_sim tests | $ProjectFileDir$/src/agilab/apps/link_sim_project/app_test.py |  | $ProjectFileDir$/src/agilab/apps/link_sim_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/link_sim_project && uv run python $ProjectFileDir$/src/agilab/apps/link_sim_project/app_test.py | uv (link_sim_project) |
| apps | **MyCode** |  |  |  |  |  |  |
| apps | mycode AGI.get_distrib | $ProjectFileDir$/src/agilab/examples/mycode/AGI.get_distrib_mycode.py |  | $ProjectFileDir$/src/agilab/examples | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/examples && uv run python $ProjectFileDir$/src/agilab/examples/mycode/AGI.get_distrib_mycode.py | uv (mycode_project) |
| apps | mycode AGI.get_distrib | $ProjectFileDir$/src/agilab/examples/mycode/AGI.get_distrib_mycode.py |  | $ProjectFileDir$/src/agilab/examples/mycode | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/examples/mycode && uv run python $ProjectFileDir$/src/agilab/examples/mycode/AGI.get_distrib_mycode.py | uv (mycode_project) |
| apps | mycode AGI.run | $ProjectFileDir$/src/agilab/examples/mycode/AGI.run_mycode.py |  | $ProjectFileDir$/src/agilab/apps/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/mycode_project && uv run python $ProjectFileDir$/src/agilab/examples/mycode/AGI.run_mycode.py | uv (mycode_project) |
| apps | mycode call worker | $ProjectFileDir$/src/agilab/apps/mycode_project/test/_test_call_worker.py |  | $ProjectFileDir$/src/agilab/apps/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/mycode_project && uv run python $ProjectFileDir$/src/agilab/apps/mycode_project/test/_test_call_worker.py | uv (mycode_project) |
| apps | mycode test manager | $ProjectFileDir$/src/agilab/apps/mycode_project/test/_test_mycode_manager.py |  | $ProjectFileDir$/src/agilab/apps/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/mycode_project && uv run python $ProjectFileDir$/src/agilab/apps/mycode_project/test/_test_mycode_manager.py | uv (mycode_project) |
| apps | mycode test worker | $ProjectFileDir$/src/agilab/apps/mycode_project/test/_test_mycode_worker.py |  | $ProjectFileDir$/src/agilab/apps/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/mycode_project && uv run python $ProjectFileDir$/src/agilab/apps/mycode_project/test/_test_mycode_worker.py | uv (mycode_worker) |
| apps | mycode tests | $ProjectFileDir$/src/agilab/apps/mycode_project/app_test.py |  | $ProjectFileDir$/src/agilab/apps/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/mycode_project && uv run python $ProjectFileDir$/src/agilab/apps/mycode_project/app_test.py | uv (mycode_project) |
| apps | **Sat Trajectory** |  |  |  |  |  |  |
| apps | sat_trajectory AGI.get_distrib | $ProjectFileDir$/src/agilab/examples/sat_trajectory/AGI.get_distrib_sat_trajectory.py |  | $ProjectFileDir$/src/agilab/examples/sat_trajectory | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/examples/sat_trajectory && uv run python $ProjectFileDir$/src/agilab/examples/sat_trajectory/AGI.get_distrib_sat_trajectory.py | uv (sat_trajectory_project) |
| apps | sat_trajectory AGI.run | $ProjectFileDir$/src/agilab/examples/sat_trajectory/AGI.run_sat_trajectory.py |  | $ProjectFileDir$/src/agilab/apps/sat_trajectory_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/sat_trajectory_project && uv run python $ProjectFileDir$/src/agilab/examples/sat_trajectory/AGI.run_sat_trajectory.py | uv (sat_trajectory_project) |
| apps | sat_trajectory call worker | $ProjectFileDir$/src/agilab/apps/sat_trajectory_project/test/_test_call_worker.py |  | $ProjectFileDir$/src/agilab/apps/sat_trajectory_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/sat_trajectory_project && uv run python $ProjectFileDir$/src/agilab/apps/sat_trajectory_project/test/_test_call_worker.py | uv (sat_trajectory_project) |
| apps | sat_trajectory test manager | $ProjectFileDir$/src/agilab/apps/sat_trajectory_project/test/_test_sat_trajectory_manager.py |  | $ProjectFileDir$/src/agilab/apps/sat_trajectory_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/sat_trajectory_project && uv run python $ProjectFileDir$/src/agilab/apps/sat_trajectory_project/test/_test_sat_trajectory_manager.py | uv (sat_trajectory_project) |
| apps | sat_trajectory test worker | $ProjectFileDir$/src/agilab/apps/sat_trajectory_project/test/_test_sat_trajectory_worker.py |  | $ProjectFileDir$/src/agilab/apps/sat_trajectory_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/sat_trajectory_project && uv run python $ProjectFileDir$/src/agilab/apps/sat_trajectory_project/test/_test_sat_trajectory_worker.py | uv (sat_trajectory_worker) |
| apps | sat_trajectory tests | $ProjectFileDir$/src/agilab/apps/sat_trajectory_project/app_test.py |  | $ProjectFileDir$/src/agilab/apps/sat_trajectory_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/sat_trajectory_project && uv run python $ProjectFileDir$/src/agilab/apps/sat_trajectory_project/app_test.py | uv (sat_trajectory_project) |
| apps | **SB3 Trainer** |  |  |  |  |  |  |
| apps | sb3_trainer AGI.get_distrib | $ProjectFileDir$/src/agilab/examples/sb3_trainer/AGI.get_distrib_sb3_trainer.py |  | $ProjectFileDir$/src/agilab/examples/sb3_trainer | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/examples/sb3_trainer && uv run python $ProjectFileDir$/src/agilab/examples/sb3_trainer/AGI.get_distrib_sb3_trainer.py | uv (sb3_trainer_project) |
| apps | sb3_trainer AGI.run | $ProjectFileDir$/src/agilab/examples/sb3_trainer/AGI.run_sb3_trainer.py |  | $ProjectFileDir$/src/agilab/apps/sb3_trainer_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/sb3_trainer_project && uv run python $ProjectFileDir$/src/agilab/examples/sb3_trainer/AGI.run_sb3_trainer.py | uv (sb3_trainer_project) |
| apps | sb3_trainer call worker | $ProjectFileDir$/src/agilab/apps/sb3_trainer_project/test/_test_call_worker.py |  | $ProjectFileDir$/src/agilab/apps/sb3_trainer_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/sb3_trainer_project && uv run python $ProjectFileDir$/src/agilab/apps/sb3_trainer_project/test/_test_call_worker.py | uv (sb3_trainer_project) |
| apps | sb3_trainer test manager | $ProjectFileDir$/src/agilab/apps/sb3_trainer_project/test/_test_sb3_trainer_manager.py |  | $ProjectFileDir$/src/agilab/apps/sb3_trainer_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/sb3_trainer_project && uv run python $ProjectFileDir$/src/agilab/apps/sb3_trainer_project/test/_test_sb3_trainer_manager.py | uv (sb3_trainer_project) |
| apps | sb3_trainer test worker | $ProjectFileDir$/src/agilab/apps/sb3_trainer_project/test/_test_sb3_trainer_worker.py |  | $ProjectFileDir$/src/agilab/apps/sb3_trainer_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/sb3_trainer_project && uv run python $ProjectFileDir$/src/agilab/apps/sb3_trainer_project/test/_test_sb3_trainer_worker.py | uv (sb3_trainer_worker) |
| apps | sb3_trainer tests | $ProjectFileDir$/src/agilab/apps/sb3_trainer_project/app_test.py |  | $ProjectFileDir$/src/agilab/apps/sb3_trainer_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/sb3_trainer_project && uv run python $ProjectFileDir$/src/agilab/apps/sb3_trainer_project/app_test.py | uv (sb3_trainer_project) |
| apps | **Other Apps** |  |  |  |  |  |  |
| apps | **Apps** |  |  |  |  |  |  |
| apps | app install | $ProjectFileDir$/src/agilab/snippets/AGI.install_$Prompt:Enter app manager name:flight$.py |  | $ProjectFileDir$ | PYTHONUNBUFFERED=1 PYDEVD_USE_FRAME_EVAL=NO;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/src/agilab/snippets/AGI.install_$Prompt:Enter app manager name:flight$.py | uv (agi-cluster) |
| apps | app-test | $ProjectFileDir$/src/agilab/apps/$Prompt:Enter app manager name:flight$_project/app_test.py |  |  | PYTHONUNBUFFERED=1 | uv run python $ProjectFileDir$/src/agilab/apps/$Prompt:Enter app manager name:flight$_project/app_test.py | uv (agi-cluster) |
| apps | **Flight** |  |  |  |  |  |  |
| apps | **Flight Trajectory** |  |  |  |  |  |  |
| apps | **Link Sim** |  |  |  |  |  |  |
| apps | **MyCode** |  |  |  |  |  |  |
| apps | **Sat Trajectory** |  |  |  |  |  |  |
| apps | **SB3 Trainer** |  |  |  |  |  |  |
| agilab | agilab run (dev) | streamlit | run $ProjectFileDir$/src/agilab/AGILAB.py -- --install-type 1 --openai-api-key "your-key" --apps-dir $ProjectFileDir$/src/agilab/apps | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run streamlit run $ProjectFileDir$/src/agilab/AGILAB.py -- --install-type 1 --openai-api-key "your-key" --apps-dir $ProjectFileDir$/src/agilab/apps | uv (agilab) |
| agilab | agilab run (enduser) | streamlit | run .venv/lib/python3.13/site-packages/agilab/AGILAB.py -- --openai-api-key "your-key" --install 0 | $ProjectFileDir$/../agi-space | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/../agi-space && uv run streamlit run .venv/lib/python3.13/site-packages/agilab/AGILAB.py -- --openai-api-key "your-key" --install 0 | uv (agi-space) |
| agilab | app install (local) | $ProjectFileDir$/src/agilab/apps/install.py | $Prompt:selected app:~/agilab/src/agilab/apps/flight_project$ --install-type "1" --verbose 1 | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/src/agilab/apps/install.py $Prompt:selected app:~/agilab/src/agilab/apps/flight_project$ --install-type "1" --verbose 1 | uv (agi-cluster) |
| agilab | app_script gen | $ProjectFileDir$/pycharm/gen_app_script.py | $Prompt:Enter app manager name:flight$ |  | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | uv run python $ProjectFileDir$/pycharm/gen_app_script.py $Prompt:Enter app manager name:flight$ |  |
| agilab | install-agilab-dev | bash | $PROJECT_DIR$/setup_pycharm.sh | $PROJECT_DIR$ |  | cd $PROJECT_DIR$ && /bin/bash $PROJECT_DIR$/setup_pycharm.sh |  |
| agilab | install-agilab-enduser | bash | $PROJECT_DIR$/tools/install_enduser.sh --source testpypi | $PROJECT_DIR$/test |  | cd $PROJECT_DIR$/test && /bin/bash $PROJECT_DIR$/tools/install_enduser.sh --source testpypi |  |
| agilab | lab_run test | $USER_HOME$/agi-workspace/.venv/lib/python3.12/site-packages/agilab/lab_run.py | --openai-api-key "your-key" | $USER_HOME$/agi-workspace/ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/agi-workspace/ && uv run python $USER_HOME$/agi-workspace/.venv/lib/python3.12/site-packages/agilab/lab_run.py --openai-api-key "your-key" | uv (agilab) |
| agilab | pypi publish | $ProjectFileDir$/test/_pypi_publish.py | --repo testpypi --user agilab --clean --user agilab --regex ^\d+\.\d+\.\d+\.post\d+$ | $ProjectFileDir$ | PYTHONUNBUFFERED=1 PYDEVD_USE_FRAME_EVAL=NO;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/test/_pypi_publish.py --repo testpypi --user agilab --clean --user agilab --regex ^\d+\.\d+\.\d+\.post\d+$ | uv (agilab) |
| agilab | run ssh cmd | $ProjectFileDir$/src/agilab/core/agi-env/test/_test_ssh_cmd.py |  |  | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | uv run python $ProjectFileDir$/src/agilab/core/agi-env/test/_test_ssh_cmd.py |  |
| agilab | show depencencies | $ProjectFileDir$/tools/show_dependencies.py | --repo testpypi | $ProjectFileDir$ | PYTHONUNBUFFERED=1 PYDEVD_USE_FRAME_EVAL=NO;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/tools/show_dependencies.py --repo testpypi | uv (agilab) |
| agilab | test agi_distributor | pytest | $PROJECT_DIR$/src/agilab/core/test/test_agi_distributor.py | $PROJECT_DIR$/src/agilab/core/agi-cluster |  | cd $PROJECT_DIR$/src/agilab/core/agi-cluster && uv run pytest $PROJECT_DIR$/src/agilab/core/test/test_agi_distributor.py | uv (agi-cluster) |
| agilab | test agi_env | pytest | -q --cov\u003dagi_env test_agi_env.py $PROJECT_DIR$/src/agilab/core/agi-env/test/test_agi_env.py | $ProjectFileDir$/src/agilab/core/agi-env/test |  | cd $ProjectFileDir$/src/agilab/core/agi-env/test && uv run pytest -q --cov\u003dagi_env test_agi_env.py $PROJECT_DIR$/src/agilab/core/agi-env/test/test_agi_env.py | uv (agi-env) |
| agilab | test base_worker | pytest | $PROJECT_DIR$/src/agilab/core/test/test_base_worker.py |  |  | uv run pytest $PROJECT_DIR$/src/agilab/core/test/test_base_worker.py | uv (agi-cluster) |
| agilab | test dag_worker | pytest | $PROJECT_DIR$/src/agilab/core/test/test_dag_worker.py |  |  | uv run pytest $PROJECT_DIR$/src/agilab/core/test/test_dag_worker.py | uv (agi-cluster) |
| agilab | test pandas_worker | pytest | $PROJECT_DIR$/src/agilab/core/test/test_pandas_worker.py | $PROJECT_DIR$/src/agilab/core/agi-cluster |  | cd $PROJECT_DIR$/src/agilab/core/agi-cluster && uv run pytest $PROJECT_DIR$/src/agilab/core/test/test_pandas_worker.py | uv (agi-cluster) |
| agilab | test polars_worker | pytest | $PROJECT_DIR$/src/agilab/core/test/test_polars_worker.py | $PROJECT_DIR$/src/agilab/core/agi-cluster |  | cd $PROJECT_DIR$/src/agilab/core/agi-cluster && uv run pytest $PROJECT_DIR$/src/agilab/core/test/test_polars_worker.py | uv (agi-cluster) |
| agilab | test work_dispatcher | pytest | $PROJECT_DIR$/src/agilab/core/test/test_work_dispatcher.py |  |  | uv run pytest $PROJECT_DIR$/src/agilab/core/test/test_work_dispatcher.py | uv (agi-cluster) |
| agilab | zip_all gen | $ProjectFileDir$/../../tools/zip_all.py | --dir2zip src --zipfile src.zip | $ProjectFileDir$/../../tools | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/../../tools && uv run python $ProjectFileDir$/../../tools/zip_all.py --dir2zip src --zipfile src.zip |  |
| components | flight_egg gen | $PROJECT_DIR$/src/agilab/apps/flight_project/build.py | bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/flight_worker | $ProjectFileDir$/src/agilab/apps/flight_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_project && uv run python $PROJECT_DIR$/src/agilab/apps/flight_project/build.py bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/flight_worker | uv (flight_project) |
| components | flight_lib gen | $USER_HOME$/wenv/flight_worker/build.py | build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/flight_worker | $USER_HOME$/wenv/flight_worker | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/wenv/flight_worker && uv run python $USER_HOME$/wenv/flight_worker/build.py build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/flight_worker | uv (flight_worker) |
| components | flight_postinstall test | $USER_HOME$/wenv/flight_worker/src/flight_worker/post_install.py | $ProjectFileDir$/src/agilab/apps/flight_project 1 $USER_HOME$/data/flight | $ProjectFileDir$/src/agilab/apps/flight_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_project && uv run python $USER_HOME$/wenv/flight_worker/src/flight_worker/post_install.py $ProjectFileDir$/src/agilab/apps/flight_project 1 $USER_HOME$/data/flight | uv (flight_worker) |
| components | flight_preinstall test | $PROJECT_DIR$/src/agilab/apps/flight_project/src/flight_worker/pre_install.py | remove_decorators --verbose --worker_path $USER_HOME$/wenv/flight_worker/src/flight_worker/flight_worker.py | $ProjectFileDir$/src/agilab/apps/flight_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_project && uv run python $PROJECT_DIR$/src/agilab/apps/flight_project/src/flight_worker/pre_install.py remove_decorators --verbose --worker_path $USER_HOME$/wenv/flight_worker/src/flight_worker/flight_worker.py | uv (flight_project) |
| components | flight_trajectory_egg gen | $PROJECT_DIR$/src/agilab/apps/flight_trajectory_project/build.py | bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/flight_trajectory_worker | $ProjectFileDir$/src/agilab/apps/flight_trajectory_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_trajectory_project && uv run python $PROJECT_DIR$/src/agilab/apps/flight_trajectory_project/build.py bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/flight_trajectory_worker | uv (flight_trajectory_project) |
| components | flight_trajectory_lib gen | $USER_HOME$/wenv/flight_trajectory_worker/build.py | build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/flight_trajectory_worker | $USER_HOME$/wenv/flight_trajectory_worker | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/wenv/flight_trajectory_worker && uv run python $USER_HOME$/wenv/flight_trajectory_worker/build.py build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/flight_trajectory_worker | uv (flight_trajectory_worker) |
| components | flight_trajectory_postinstall test | $USER_HOME$/wenv/flight_trajectory_worker/src/flight_trajectory_worker/post_install.py | $ProjectFileDir$/src/agilab/apps/flight_trajectory_project 1 $USER_HOME$/data/flight_trajectory | $ProjectFileDir$/src/agilab/apps/flight_trajectory_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_trajectory_project && uv run python $USER_HOME$/wenv/flight_trajectory_worker/src/flight_trajectory_worker/post_install.py $ProjectFileDir$/src/agilab/apps/flight_trajectory_project 1 $USER_HOME$/data/flight_trajectory | uv (flight_trajectory_worker) |
| components | flight_trajectory_preinstall test | $PROJECT_DIR$/src/agilab/apps/flight_trajectory_project/src/flight_trajectory_worker/pre_install.py | remove_decorators --verbose --worker_path $USER_HOME$/wenv/flight_trajectory_worker/src/flight_trajectory_worker/flight_trajectory_worker.py | $ProjectFileDir$/src/agilab/apps/flight_trajectory_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_trajectory_project && uv run python $PROJECT_DIR$/src/agilab/apps/flight_trajectory_project/src/flight_trajectory_worker/pre_install.py remove_decorators --verbose --worker_path $USER_HOME$/wenv/flight_trajectory_worker/src/flight_trajectory_worker/flight_trajectory_worker.py | uv (flight_trajectory_project) |
| components | link_sim_egg gen | $PROJECT_DIR$/src/agilab/apps/link_sim_project/build.py | bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/link_sim_worker | $ProjectFileDir$/src/agilab/apps/link_sim_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/link_sim_project && uv run python $PROJECT_DIR$/src/agilab/apps/link_sim_project/build.py bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/link_sim_worker | uv (link_sim_project) |
| components | link_sim_lib gen | $USER_HOME$/wenv/link_sim_worker/build.py | build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/link_sim_worker | $USER_HOME$/wenv/link_sim_worker | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/wenv/link_sim_worker && uv run python $USER_HOME$/wenv/link_sim_worker/build.py build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/link_sim_worker | uv (link_sim_worker) |
| components | link_sim_postinstall test | $USER_HOME$/wenv/link_sim_worker/src/link_sim_worker/post_install.py | $ProjectFileDir$/src/agilab/apps/link_sim_project 1 $USER_HOME$/data/link_sim | $ProjectFileDir$/src/agilab/apps/link_sim_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/link_sim_project && uv run python $USER_HOME$/wenv/link_sim_worker/src/link_sim_worker/post_install.py $ProjectFileDir$/src/agilab/apps/link_sim_project 1 $USER_HOME$/data/link_sim | uv (link_sim_worker) |
| components | link_sim_preinstall test | $PROJECT_DIR$/src/agilab/apps/link_sim_project/src/link_sim_worker/pre_install.py | remove_decorators --verbose --worker_path $USER_HOME$/wenv/link_sim_worker/src/link_sim_worker/link_sim_worker.py | $ProjectFileDir$/src/agilab/apps/link_sim_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/link_sim_project && uv run python $PROJECT_DIR$/src/agilab/apps/link_sim_project/src/link_sim_worker/pre_install.py remove_decorators --verbose --worker_path $USER_HOME$/wenv/link_sim_worker/src/link_sim_worker/link_sim_worker.py | uv (link_sim_project) |
| components | mycode_egg gen | $PROJECT_DIR$/src/agilab/apps/mycode_project/build.py | bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/mycode_worker | $ProjectFileDir$/src/agilab/apps/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/mycode_project && uv run python $PROJECT_DIR$/src/agilab/apps/mycode_project/build.py bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/mycode_worker | uv (mycode_project) |
| components | mycode_lib gen | $USER_HOME$/wenv/mycode_worker/build.py | build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/mycode_worker | $USER_HOME$/wenv/mycode_worker | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/wenv/mycode_worker && uv run python $USER_HOME$/wenv/mycode_worker/build.py build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/mycode_worker | uv (mycode_worker) |
| components | mycode_postinstall test | $USER_HOME$/wenv/mycode_worker/src/mycode_worker/post_install.py | $ProjectFileDir$/src/agilab/apps/mycode_project 1 $USER_HOME$/data/mycode | $ProjectFileDir$/src/agilab/apps/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/mycode_project && uv run python $USER_HOME$/wenv/mycode_worker/src/mycode_worker/post_install.py $ProjectFileDir$/src/agilab/apps/mycode_project 1 $USER_HOME$/data/mycode | uv (mycode_worker) |
| components | mycode_preinstall test | $PROJECT_DIR$/src/agilab/apps/mycode_project/src/mycode_worker/pre_install.py | remove_decorators --verbose --worker_path $USER_HOME$/wenv/mycode_worker/src/mycode_worker/mycode_worker.py | $ProjectFileDir$/src/agilab/apps/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/mycode_project && uv run python $PROJECT_DIR$/src/agilab/apps/mycode_project/src/mycode_worker/pre_install.py remove_decorators --verbose --worker_path $USER_HOME$/wenv/mycode_worker/src/mycode_worker/mycode_worker.py | uv (mycode_project) |
| components | sat_trajectory_egg gen | $PROJECT_DIR$/src/agilab/apps/sat_trajectory_project/build.py | bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/sat_trajectory_worker | $ProjectFileDir$/src/agilab/apps/sat_trajectory_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/sat_trajectory_project && uv run python $PROJECT_DIR$/src/agilab/apps/sat_trajectory_project/build.py bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/sat_trajectory_worker | uv (sat_trajectory_project) |
| components | sat_trajectory_lib gen | $USER_HOME$/wenv/sat_trajectory_worker/build.py | build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/sat_trajectory_worker | $USER_HOME$/wenv/sat_trajectory_worker | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/wenv/sat_trajectory_worker && uv run python $USER_HOME$/wenv/sat_trajectory_worker/build.py build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/sat_trajectory_worker | uv (sat_trajectory_worker) |
| components | sat_trajectory_postinstall test | $USER_HOME$/wenv/sat_trajectory_worker/src/sat_trajectory_worker/post_install.py | $ProjectFileDir$/src/agilab/apps/sat_trajectory_project 1 $USER_HOME$/data/sat_trajectory | $ProjectFileDir$/src/agilab/apps/sat_trajectory_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/sat_trajectory_project && uv run python $USER_HOME$/wenv/sat_trajectory_worker/src/sat_trajectory_worker/post_install.py $ProjectFileDir$/src/agilab/apps/sat_trajectory_project 1 $USER_HOME$/data/sat_trajectory | uv (sat_trajectory_worker) |
| components | sat_trajectory_preinstall test | $PROJECT_DIR$/src/agilab/apps/sat_trajectory_project/src/sat_trajectory_worker/pre_install.py | remove_decorators --verbose --worker_path $USER_HOME$/wenv/sat_trajectory_worker/src/sat_trajectory_worker/sat_trajectory_worker.py | $ProjectFileDir$/src/agilab/apps/sat_trajectory_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/sat_trajectory_project && uv run python $PROJECT_DIR$/src/agilab/apps/sat_trajectory_project/src/sat_trajectory_worker/pre_install.py remove_decorators --verbose --worker_path $USER_HOME$/wenv/sat_trajectory_worker/src/sat_trajectory_worker/sat_trajectory_worker.py | uv (sat_trajectory_project) |
| components | sb3_trainer_egg gen | $PROJECT_DIR$/src/agilab/apps/sb3_trainer_project/build.py | bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/sb3_trainer_worker | $ProjectFileDir$/src/agilab/apps/sb3_trainer_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/sb3_trainer_project && uv run python $PROJECT_DIR$/src/agilab/apps/sb3_trainer_project/build.py bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/sb3_trainer_worker | uv (sb3_trainer_project) |
| components | sb3_trainer_lib gen | $USER_HOME$/wenv/sb3_trainer_worker/build.py | build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/sb3_trainer_worker | $USER_HOME$/wenv/sb3_trainer_worker | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/wenv/sb3_trainer_worker && uv run python $USER_HOME$/wenv/sb3_trainer_worker/build.py build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/sb3_trainer_worker | uv (sb3_trainer_worker) |
| components | sb3_trainer_postinstall test | $USER_HOME$/wenv/sb3_trainer_worker/src/sb3_trainer_worker/post_install.py | $ProjectFileDir$/src/agilab/apps/sb3_trainer_project 1 $USER_HOME$/data/sb3_trainer | $ProjectFileDir$/src/agilab/apps/sb3_trainer_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/sb3_trainer_project && uv run python $USER_HOME$/wenv/sb3_trainer_worker/src/sb3_trainer_worker/post_install.py $ProjectFileDir$/src/agilab/apps/sb3_trainer_project 1 $USER_HOME$/data/sb3_trainer | uv (sb3_trainer_worker) |
| components | sb3_trainer_preinstall test | $PROJECT_DIR$/src/agilab/apps/sb3_trainer_project/src/sb3_trainer_worker/pre_install.py | remove_decorators --verbose --worker_path $USER_HOME$/wenv/sb3_trainer_worker/src/sb3_trainer_worker/sb3_trainer_worker.py | $ProjectFileDir$/src/agilab/apps/sb3_trainer_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/sb3_trainer_project && uv run python $PROJECT_DIR$/src/agilab/apps/sb3_trainer_project/src/sb3_trainer_worker/pre_install.py remove_decorators --verbose --worker_path $USER_HOME$/wenv/sb3_trainer_worker/src/sb3_trainer_worker/sb3_trainer_worker.py | uv (sb3_trainer_project) |
| views | view_autoencoder_latenspace | streamlit | run $ProjectFileDir$/src/agilab/apps-pages/view_autoencoder_latenspace/src/view_autoencoder_latentspace/view_autoencoder_latentspace.py -- --install-type 1 --active-app $ProjectFileDir$/src/agilab/apps/flight_project |  | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | uv run streamlit run $ProjectFileDir$/src/agilab/apps-pages/view_autoencoder_latenspace/src/view_autoencoder_latentspace/view_autoencoder_latentspace.py -- --install-type 1 --active-app $ProjectFileDir$/src/agilab/apps/flight_project |  |
| views | view_barycentric | streamlit | run $ProjectFileDir$/src/agilab/apps-pages/view_barycentric/src/view_barycentric/view_barycentric.py -- --install-type 1 --active-app $ProjectFileDir$/src/agilab/apps/flight_project |  | PYTHONUNBUFFERED=1 | uv run streamlit run $ProjectFileDir$/src/agilab/apps-pages/view_barycentric/src/view_barycentric/view_barycentric.py -- --install-type 1 --active-app $ProjectFileDir$/src/agilab/apps/flight_project | uv (view_barycentric) |
| views | view_maps | streamlit | run $ProjectFileDir$/src/agilab/apps-pages/view_maps/src/view_maps/view_maps.py -- --install-type 1 --active-app $ProjectFileDir$/src/agilab/apps/flight_project |  | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | uv run streamlit run $ProjectFileDir$/src/agilab/apps-pages/view_maps/src/view_maps/view_maps.py -- --install-type 1 --active-app $ProjectFileDir$/src/agilab/apps/flight_project | uv (view_maps) |
| views | view_maps_3d | streamlit | run $ProjectFileDir$/src/agilab/apps-pages/view_maps_3d/src/view_maps_3d/view_maps_3d.py -- --install-type 1 --active-app $ProjectFileDir$/src/agilab/apps/flight_project |  | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | uv run streamlit run $ProjectFileDir$/src/agilab/apps-pages/view_maps_3d/src/view_maps_3d/view_maps_3d.py -- --install-type 1 --active-app $ProjectFileDir$/src/agilab/apps/flight_project | uv (view_maps_3d) |
| views | view_maps_network | streamlit | run $ProjectFileDir$/src/agilab/apps-pages/view_maps_network/src/view_maps_network/view_maps_network.py -- --install-type 1 --active-app $ProjectFileDir$/src/agilab/apps/flight_project |  | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | uv run streamlit run $ProjectFileDir$/src/agilab/apps-pages/view_maps_network/src/view_maps_network/view_maps_network.py -- --install-type 1 --active-app $ProjectFileDir$/src/agilab/apps/flight_project | uv (view_maps_network) |
| docs | gen-docs | /Users/jpm/PycharmProjects/thales_agilab/docs/gen-docs.py |  | /Users/jpm/PycharmProjects/thales_agilab | PYTHONUNBUFFERED=1 | cd /Users/jpm/PycharmProjects/thales_agilab && uv run python /Users/jpm/PycharmProjects/thales_agilab/docs/gen-docs.py | uv (thales_agilab) |

</details>

## Progressive test plan

### Tier A — Quick checks (fast sanity)
- UI smoke: `cd $ProjectFileDir$ && uv run streamlit run src/agilab/AGILAB.py -- --install-type 1 --openai-api-key "your-key" --apps-dir src/agilab/apps` (agilab run dev)
- Dependencies: `cd $ProjectFileDir$ && uv run python tools/show_dependencies.py --repo testpypi`
- App skeleton: `uv run python src/agilab/apps/$Prompt:Enter app manager name:flight$_project/app_test.py`

### Tier B — Component/app flows
- Flight: run → test manager/worker → distribute → call → pre/postinstall
  - `cd src/agilab/apps/flight_project && uv run python ../../snippets/AGI.run_flight.py`
  - `cd src/agilab/apps/flight_project && uv run python test/_test_flight_manager.py`
  - `cd src/agilab/apps/flight_project && uv run python test/_test_flight_worker.py`
  - `cd src/agilab/snippets && uv run python AGI.get_distrib_flight.py`
  - `cd src/agilab/apps/flight_project && uv run python test/_test_call_worker.py`
  - `cd src/agilab/apps/flight_project && uv run python src/flight_worker/pre_install.py remove_decorators --verbose --worker_path $USER_HOME$/wenv/flight_worker/src/flight_worker/flight_worker.py`
  - `cd src/agilab/apps/flight_project && uv run python $USER_HOME$/wenv/flight_worker/src/flight_worker/post_install.py src/agilab/apps/flight_project 1 $USER_HOME$/data/flight`
- FlightTrajectory:
  - `cd src/agilab/apps/flight_trajectory_project && uv run python ../../snippets/AGI.run_flight_trajectory.py`
  - `cd src/agilab/apps/flight_trajectory_project && uv run python test/_test_flight_trajectory_manager.py`
  - `cd src/agilab/apps/flight_trajectory_project && uv run python test/_test_flight_trajectory_worker.py`
  - `cd src/agilab/snippets && uv run python AGI.get_distrib_flight_trajectory.py`
  - `cd src/agilab/apps/flight_trajectory_project && uv run python test/_test_call_worker.py`
  - Workers load the exact `<data_uri>/<filename>` paths defined in app settings; missing files halt distribution.
- LinkSim:
  - `cd src/agilab/apps/link_sim_project && uv run python ../../snippets/AGI.run_link_sim.py`
  - `cd src/agilab/apps/link_sim_project && uv run python test/_test_link_sim_manager.py`
  - `cd src/agilab/apps/link_sim_project && uv run python test/_test_link_sim_worker.py`
  - `cd src/agilab/snippets && uv run python AGI.get_distrib_link_sim.py`
  - `cd src/agilab/apps/link_sim_project && uv run python test/_test_call_worker.py`
- MyCode:
  - `cd src/agilab/apps/mycode_project && uv run python ../../snippets/AGI.run_mycode.py`
  - `cd src/agilab/apps/mycode_project && uv run python test/_test_mycode_manager.py`
  - `cd src/agilab/apps/mycode_project && uv run python test/_test_mycode_worker.py`
  - `cd src/agilab/snippets && uv run python AGI.get_distrib_mycode.py`
  - `cd src/agilab/apps/mycode_project && uv run python test/_test_call_worker.py`
- SatTrajectory:
  - `cd src/agilab/apps/sat_trajectory_project && uv run python ../../snippets/AGI.run_sat_trajectory.py`
  - `cd src/agilab/apps/sat_trajectory_project && uv run python test/_test_sat_trajectory_manager.py`
  - `cd src/agilab/apps/sat_trajectory_project && uv run python test/_test_sat_trajectory_worker.py`
  - `cd src/agilab/snippets && uv run python AGI.get_distrib_sat_trajectory.py`
  - `cd src/agilab/apps/sat_trajectory_project && uv run python test/_test_call_worker.py`
  - Worker expects TLE data under the configured `data_uri` and returns task payloads as `(satellite_id, csv)` tuples; ensure those files exist before distributing.
- Sb3Trainer:
  - `cd src/agilab/apps/sb3_trainer_project && uv run python ../../snippets/AGI.run_sb3_trainer.py`
  - `cd src/agilab/apps/sb3_trainer_project && uv run python test/_test_sb3_trainer_manager.py`
  - `cd src/agilab/apps/sb3_trainer_project && uv run python test/_test_sb3_trainer_worker.py`
  - `cd src/agilab/snippets && uv run python AGI.get_distrib_sb3_trainer.py`
  - `cd src/agilab/apps/sb3_trainer_project && uv run python test/_test_call_worker.py`
- FireDucks worker (core):
  - `cd src/agilab/core/agi-cluster && uv run pytest src/agilab/core/test/test_fireducks_worker.py`

### Tier C — Apps-pages and end-user
- Apps-pages: launch Streamlit pages bound to an active app
- `uv run streamlit run src/agilab/apps-pages/view_maps/src/view_maps/view_maps.py -- --install-type 1 --active-app src/agilab/apps/flight_project`
- `uv run streamlit run src/agilab/apps-pages/view_barycentric/src/view_barycentric/view_barycentric.py -- --install-type 1 --active-app src/agilab/apps/flight_project`
- `▶️ EXECUTE` page tips:
  - Use the sidebar `Verbosity level` select to choose AgiEnv verbosity (0–3). The value propagates to the generated install/distribute/run snippets and appears in the install log header.
  - Install output now streams inside the dedicated **Install logs** expander. Keep it open to watch live progress even if the snippet expander is collapsed.
- End-user mode: `cd ../agi-space && uv run streamlit run .venv/lib/python3.13/site-packages/agilab/AGILAB.py -- --openai-api-key "your-key" --install 0`

For each tier, capture: command, expected output, and pitfalls (CWD, env vars, interpreter).

## Troubleshooting & environment

- **Interpreter/SDK**: prefer the project environment (`uv`). Otherwise point to the full interpreter path or call through `uv run`.
- **Environment variables**: inspect `<envs/>` in the XML and mirror them in a `.env.example` (use placeholders, never secrets).
- **Common errors**:
  - `ModuleNotFoundError`: ensure the working directory matches `WORKING_DIRECTORY` and that `PYTHONPATH` carries the project roots.
  - Streamlit logs missing: set `PYTHONUNBUFFERED=1`.
  - Slow iterative runs: add `UV_NO_SYNC=1` in dev environments.

**`.env.example` (template)**
```dotenv
OPENAI_API_KEY=__set_me__
AGI_CLUSTER_URL=__set_me__
```

## Automate with Codex (safe write with approvals)

```bash
codex --model gpt-5-codex --approvals ask "
Update AGENTS.md: refresh the 'Run matrix' and 'Progressive test plan' under 'How to work on this repository'
by parsing .idea/runConfigurations/*.xml:
- Extract: name, SCRIPT_NAME, PARAMETERS, WORKING_DIRECTORY, envs, interpreter
- Group rows by app/component/app-pages heuristics (agilab/, agi-*/, apps/, apps-pages/, apps/templates/)
- Render a markdown table with copy-pasteable commands (cd + python/uv run)
- Keep edits scoped to this section; show a unified diff before saving"
```

## Keeping run configs in sync
- When you create or rename workflows, clone an existing XML, tweak script/workdir/interpreter, and keep the grouping tidy.
- Treat `.idea/runConfigurations/` as the canonical “how do I repro this?” checklist and regenerate the matrix whenever something changes.
- Important: when renaming or relocating scripts/entries, update both:
  - The concrete launchers in `.idea/runConfigurations/*.xml` (names, `SCRIPT_NAME`, `WORKING_DIRECTORY`, envs).
  - The PyCharm templates and helpers under `pycharm/` and related generators, for example:
    - `pycharm/app_scripts/_template_app_*.xml`
    - `pycharm/setup_pycharm.py`
    - `pycharm/gen_app_script.py`
    - `src/agilab/core/gen_app_script.py` (if you rely on the core helper)
  - After changes, re-run the “Run matrix” refresh to keep docs aligned.

### Regenerate run configs (step-by-step)

1. Update templates (if needed)
   - Edit `pycharm/app_scripts/_template_app_*.xml` to reflect new script names/paths (e.g., `AGI.get_distrib_*`).

2. Sync PyCharm modules + registered SDKs
   - `uv run python pycharm/setup_pycharm.py`

3. Re-generate per‑app launchers (one per app)
   - Examples:
     - `uv run python pycharm/gen_app_script.py flight`
     - `uv run python pycharm/gen_app_script.py link_sim`
     - `uv run python pycharm/gen_app_script.py mycode`
     - `uv run python pycharm/gen_app_script.py sat_trajectory`
     - `uv run python pycharm/gen_app_script.py sb3_trainer`

4) Verify
   - Inspect `.idea/runConfigurations/*.xml` for updated `SCRIPT_NAME`, names, and `folderName` grouping.

5) Refresh the Run Matrix in this doc
   - Use the snippet under “How to refresh this matrix” to re-print rows and paste in place.

---

## Coding Standards

- Follow **PEP8** with project-specific exceptions documented in `pyproject.toml`.
- Type hints are **required** for public functions; enforce with `mypy`.
- Prefer composition over inheritance; interfaces live in `agilab/core/`.
- Break cycles; respect clear layering (core → components → apps → pages).

---

## Contribution Workflow

1. **Create a feature branch**: `feat/<area>-<short-desc>`
2. **Small, reviewable PRs** — keep changes focused and add context in the description.
3. **Tests** — write/adjust unit tests; add an integration path when touching orchestration.
4. **Docs** — update `AGENTS.md` and component READMEs when behavior changes.
5. **CI** — ensure lint, type-check, and tests pass before requesting review.

---

## Release & Deployment (if applicable)

- Tag version in `pyproject.toml`
- Changelog entries required for user-facing changes
- Automated packaging with `uv build` and release notes in GitHub

---

## Security & Secrets

- Never commit secrets; use `.env` or your secret manager.
- Use restricted API keys for local dev.
- Validate inputs and sanitize file paths.
- Log only non-sensitive metadata.

---

## FAQ

**Q: My run configuration fails with `ModuleNotFoundError`.**  
A: Ensure your working directory matches the config’s `WORKING_DIRECTORY` and your interpreter matches the project’s SDK.

**Q: Streamlit app doesn’t hot-reload.**  
A: Start it with `uv run streamlit run ...` and check `PYTHONUNBUFFERED`.

**Q: Where do I add a new component?**  
A: Create `agi-<name>/` under the repo root with its own README and tests; wire it into the run matrix via a new JetBrains XML.

---

## Appendix: Useful Commands

```bash
# Create & activate venv
uv venv && source .venv/bin/activate

# Install editable
uv --preview-features extra-build-dependencies pip install -e .

# Run Streamlit
uv run streamlit run src/agilab/AGILAB.py

# Run a component script
uv run python agilab/tools/show_dependencies.py

# Lint & type-check
uv run ruff check .
uv run mypy .

# Tests
uv run pytest -q
```
