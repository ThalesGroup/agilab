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

def kill():
    current_pid = os.getpid()
    # DASK pid files
    dask_pids_to_kill = []
    for pid_file in (Path(__file__).parent).glob("*.pid"):
        try:
            text = pid_file.read_text().strip()
            pid = int(text)
            if pid != current_pid:
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
            if pid != current_pid:
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
            if ppid in pids_to_kill:
                child_pids.append(pid)
        pids_to_kill.extend(child_pids)
    except Exception as e:
        logger.warning(f"Error listing child processes: {e}")
    # Merge, deduplicate, never kill self
    all_pids_to_kill = set(dask_pids_to_kill + pids_to_kill)
    all_pids_to_kill.discard(current_pid)
    # SIGTERM
    for pid in all_pids_to_kill:
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception as e:
            logger.warning(f"Failed to send SIGTERM to {pid}: {e}")
    time.sleep(2)
    # SIGKILL
    for pid in all_pids_to_kill:
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception as e:
            logger.warning(f"Failed to send SIGKILL to {pid}: {e}")

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "kill"
    wenv = sys.argv[2] if len(sys.argv) > 2 else None
    if cmd == "kill":
        kill()
    elif cmd == "clean":
        clean(wenv)
    else:
        logger.error(f"Unknown command: {cmd}. Use 'kill' or 'clean'.")
