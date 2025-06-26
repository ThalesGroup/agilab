from agi_env import AgiEnv
import runpy
import os
import asyncio
import warnings
from IPython.lib import backgroundjobs as bg
from dask.distributed import Client
import logging

# Project Libraries:
from agi_env import AgiEnv, normalize_path
from managers import AGI

# os.environ["DASK_DISTRIBUTED__LOGGING__DISTRIBUTED__LEVEL"] = "INFO"
logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore")

async def main():
    ip_worker1= "192.168.3.24"
    ip_scheduler = "192.168.3.86"
    agipath = AgiEnv.locate_agi_installation(verbose=0)
    env = AgiEnv(active_app="flight", apps_dir=agipath / "apps", install_type=1, verbose=1)
    env.user = "nsbl"

    # kill dask process
    cmd_prefix = await AGI._detect_export_cmd(ip_worker1)
    env.set_env_var(f"{ip_worker1}_CMD_PREFIX", cmd_prefix)
    AGI.env = env
    env.user = "nsbl"
    await AGI._kill(ip_worker1 , current_pid=os.getpid(), force=True)
    runpy.run_path(env.manager_root / "agi_runner/cli.py")

    # start scheduler
    cmd = (
        f"uv run --project '/Users/nsbl/wenv/flight/worker' dask scheduler --port 8786 "
        f"--host '{ip_scheduler}' --pid-file scheduler_pid"
    )
    logging.info(f"Starting dask scheduler locally: {cmd}")
    AGI._jobs = bg.BackgroundJobManager()
    result =AGI._exec_bg(cmd, env.app_abs)  # assuming _exec_bg is sync
    logging.info(result)

    asyncio.sleep(2)  # Give scheduler a moment to start
    client = Client(AGI._scheduler,
                    heartbeat_interval=5000,
                    timeout=AGI.TIMEOUT)
    client.forward_logging()
    AGI._dask_client = client

    # start worker
    cmd = (
        # f'{export_cmd} '
        f'export PATH="$HOME/.local/bin:$PATH"; uv run --project "wenv/flight_worker" run dask worker tcp://{ip_scheduler}:8786 --no-nanny '
        f'--pid-file worker_pid'
    )
    asyncio.sleep(5)
    # Run locally in background (non-blocking)
    await env.exec_ssh(ip_worker1, cmd)

    workers = [
        worker.split("/")[-1]
        for worker in list(client.scheduler_info()["workers"].keys())
    ]

    # test dask
    res = client.run(
        os.getcwd,
        workers=workers,
    )

    logging.info(f"worker.getcwd() return: {res}")
    local_dirs = {w: info['local_directory'] for w, info in client.scheduler_info()['workers'].items()}
    await env.send_file(ip_worker1,  env.manager_root / "agi_runner/clean.py", env.wenv_rel)

    for ipc, d in local_dirs.items():
        ip = ipc.split('/')[-1].split(":")[0]
        if ip == ip_worker1:
            cmd = ("export PATH='$HOME/.local/bin:$PATH'; uv run --project 'wenv/flight_worker' "
                   "run python 'wenv/flight_worker/clean.py'")
            env.exec_ssh(ip, cmd)

    AGI._stop()
    AGI._jobs.flush()

if __name__ == '__main__':
    asyncio.run(main())