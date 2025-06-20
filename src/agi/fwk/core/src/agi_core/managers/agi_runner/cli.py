import os
import sys
import signal
import time
from pathlib import Path
import logging
from tempfile import gettempdir
import shutil

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def clean(wenv=None):
    try:
        # Remove dask-scratch-space
        scratch = Path(gettempdir()) / 'dask-scratch-space'
        shutil.rmtree(scratch, ignore_errors=True)
        logger.info(f"Removed {scratch}")
        # Remove wenv if specified
        if wenv:
            shutil.rmtree(wenv, ignore_errors=True)
            logger.info(f"Removed {wenv}")
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")

def kill(exclude_pids=None):
    if exclude_pids is None:
        exclude_pids = set()
    current_pid = os.getpid()
    exclude_pids.add(current_pid)

    logger.info(f"Excluding PIDs from kill: {exclude_pids}")

    dask_pids_to_kill = []
    for pid_file in (Path(__file__).parent).glob("*.pid"):
        try:
            text = pid_file.read_text().strip()
            pid = int(text)
            if pid in exclude_pids:
                logger.info(f"Skipping excluded pid {pid} from {pid_file}")
                continue
            dask_pids_to_kill.append(pid)
        except Exception:
            logger.warning(f"Could not read PID from {pid_file}, skipping")
        try:
            pid_file.unlink()
        except Exception as e:
            logger.warning(f"Failed to remove pid file {pid_file}: {e}")

    # managed process *.pid files
    pid_files = list(Path(".").glob("*.pid"))
    pids_to_kill = []
    for pid_file in pid_files:
        try:
            with open(pid_file) as f:
                pid = int(f.read())
            if pid in exclude_pids:
                logger.info(f"Skipping excluded pid {pid} from {pid_file}")
                continue
            pids_to_kill.append(pid)
        except Exception as e:
            logger.warning(f"Cannot read pid from {pid_file}: {e}")
        try:
            os.remove(pid_file)
        except Exception as e:
            logger.warning(f"Cannot remove pid file {pid_file}: {e}")

    # Find child processes from ps output (Unix only)
    try:
        import subprocess
        output = subprocess.check_output(["ps", "-e", "-o", "pid,ppid"]).decode()
        child_pids = []
        for line in output.splitlines()[1:]:
            pid, ppid = map(int, line.strip().split())
            if ppid in pids_to_kill and pid not in exclude_pids:
                child_pids.append(pid)
        pids_to_kill.extend(child_pids)
    except Exception as e:
        logger.warning(f"Error listing child processes: {e}")

    all_pids_to_kill = set(dask_pids_to_kill + pids_to_kill)
    all_pids_to_kill.difference_update(exclude_pids)

    if not all_pids_to_kill:
        logger.info("No PIDs to kill after exclusions.")
        return

    logger.info(f"Sending SIGTERM to PIDs: {all_pids_to_kill}")
    for pid in all_pids_to_kill:
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception as e:
            logger.warning(f"Failed to send SIGTERM to {pid}: {e}")

    time.sleep(2)

    logger.info(f"Sending SIGKILL to PIDs: {all_pids_to_kill}")
    for pid in all_pids_to_kill:
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception as e:
            logger.warning(f"Failed to send SIGKILL to {pid}: {e}")

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "kill"
    arg = sys.argv[2] if len(sys.argv) > 2 else None
    exclude_pids = set()
    if len(sys.argv) > 2:
        for pid_str in arg.split(","):
            try:
                exclude_pids.add(int(pid_str))
            except Exception:
                logger.warning(f"Invalid PID to exclude: {pid_str}")

    if cmd == "kill":
        kill(exclude_pids=exclude_pids)
    elif cmd == "clean":
        clean(wenv=arg)
    else:
        logger.error(f"Unknown command: {cmd}. Use 'kill' or 'clean'.")
