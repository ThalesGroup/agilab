import asyncio
import logging
import os
import runpy
import warnings
from IPython.lib import backgroundjobs as bg
from dask.distributed import Client

# Project Libraries:
from agi_env import AgiEnv, normalize_path
from managers import AGI

warnings.filterwarnings("ignore")
logger = logging.getLogger(__name__)

async def main():
    ip_worker1 = "192.168.3.24"
    scheduler_addr = "192.168.3.86"

    agipath = AgiEnv.locate_agi_installation(verbose=0)
    env = AgiEnv(active_app="flight", apps_dir=agipath / "apps", install_type=1, verbose=1)
    env.user = "nsbl"

    # Kill dask process on worker
    cmd_prefix = await AGI._detect_export_cmd(ip_worker1)
    AgiEnv.set_env_var(f"{ip_worker1}_CMD_PREFIX", cmd_prefix)
    AGI.env = env
    env.user = "nsbl"
    await AGI._kill(ip_worker1, current_pid=os.getpid(), force=True)

    runpy.run_path(env.cluster_root / "src/cluster/cli.py")

    # Start scheduler locally
    cmd = (
        f"uv run --project '/Users/nsbl/wenv/flight/worker' dask scheduler --port 8786 "
        f"--host '{scheduler_addr}' --pid-file scheduler_pid"
    )
    logger.info(f"Starting dask scheduler locally: {cmd}")
    AGI._jobs = bg.BackgroundJobManager()
    result = AGI._exec_bg(cmd, env.app_abs)
    logger.info(f"Scheduler start result: {result}")

    await asyncio.sleep(2)  # Give scheduler time to start

    # Connect Dask client asynchronously
    try:
        client = await Client(f"tcp://{scheduler_addr}:8786",
                              heartbeat_interval="5s",
                              timeout=AGI.TIMEOUT,
                              asynchronous=True)
        client.forward_logging()
        AGI._dask_client = client
        logger.info("Dask client connected to scheduler.")
    except Exception as e:
        logger.error(f"Failed to connect Dask client: {e}")
        return

    # Start worker remotely via SSH
    worker_cmd = (
        f"export PATH=\"$HOME/.local/bin:$PATH\"; "
        f"uv run --project 'wenv/flight_worker' run dask worker tcp://{scheduler_addr}:8786 "
        f"--no-nanny --pid-file worker_pid"
    )
    await asyncio.sleep(5)  # Wait before starting worker
    await env.exec_ssh(ip_worker1, worker_cmd)
    logger.info(f"Started dask worker on {ip_worker1}")

    # Wait for workers to register
    await asyncio.sleep(5)
    workers = [
        worker.split("/")[-1]
        for worker in client.scheduler_info()["workers"].keys()
    ]
    logger.info(f"Workers connected: {workers}")

    # Test: Run os.getcwd() remotely on all workers
    res = client.run(os.getcwd, workers=workers)
    logger.info(f"worker.getcwd() return: {res}")

    # Validate results
    if not isinstance(res, dict) or len(res) != len(workers):
        logger.error("Unexpected result from client.run(os.getcwd)")
    else:
        for w, cwd in res.items():
            if not isinstance(cwd, str) or not cwd:
                logger.error(f"Invalid cwd from worker {w}: {cwd}")

    # Additional distributed test: map and gather squares
    try:
        futures = client.map(lambda x: x ** 2, range(5))
        results_list = await client.gather(futures)
        assert results_list == [0, 1, 4, 9, 16], "Distributed computation failed"
        logger.info("Distributed map/gather test succeeded.")
    except Exception as e:
        logger.error(f"Distributed computation test failed: {e}")

    # Send cleaning script and run on worker matching ip_worker1
    local_dirs = {w: info['local_directory'] for w, info in client.scheduler_info()['workers'].items()}
    await env.send_file(ip_worker1, env.cluster_root / "src/cluster/clean.py", env.wenv_rel)

    for ipc, d in local_dirs.items():
        ip = ipc.split('/')[-1].split(":")[0]
        if ip == ip_worker1:
            clean_cmd = (
                "export PATH='$HOME/.local/bin:$PATH'; "
                "uv run --project 'wenv/flight_worker' run python 'wenv/flight_worker/clean.py'"
            )
            await env.exec_ssh(ip, clean_cmd)
            logger.info(f"Cleanup script run on worker {ip}")

    AGI._stop()
    AGI._jobs.flush()

if __name__ == "__main__":
    asyncio.run(main())
