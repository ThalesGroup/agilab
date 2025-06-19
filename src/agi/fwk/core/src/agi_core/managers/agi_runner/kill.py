import os
import sys
import signal
import time
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

def main():
    current_pid = os.getpid()

    # --- [BEGIN: DASK PID FILES KILL LOGIC] ---
    dask_pids_to_kill: list[int] = []
    for pid_file in Path(os.getcwd()).glob("dask_pid*"):
        try:
            text = pid_file.read_text().strip()
            pid = int(text)
            if pid != current_pid:
                dask_pids_to_kill.append(pid)
        except Exception:
            logging.warning(f"Could not read PID from {pid_file}, skipping")
        try:
            pid_file.unlink()
        except Exception as e:
           logging.warning(f"Failed to remove pid file {pid_file}: {e}")
    # --- [END: DASK PID FILES KILL LOGIC] ---

    # --- [BEGIN: YOUR ORIGINAL LOGIC] ---
    pid_files = list(Path(".").glob("*.pid"))
    pids_to_kill = []

    for pid_file in pid_files:
        try:
            with open(pid_file) as f:
                pid = int(f.read())
            if pid != current_pid:
                pids_to_kill.append(pid)
        except Exception as e:
            logging.warning(f"Cannot read pid from {pid_file}: {e}")

        try:
            os.remove(pid_file)
        except Exception as e:
            logging.warning(f"Cannot remove pid file {pid_file}: {e}")

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
        logging.warning(f"Error listing child processes: {e}")
    # --- [END: YOUR ORIGINAL LOGIC] ---

    # Merge all PID sources, deduplicate, never kill self
    all_pids_to_kill = set(dask_pids_to_kill + pids_to_kill)
    all_pids_to_kill.discard(current_pid)

    # Give processes a chance to terminate gracefully
    for pid in all_pids_to_kill:
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception as e:
            logging.warning(f"Failed to send SIGTERM to {pid}: {e}")

    time.sleep(2)  # Wait a bit

    # Force kill any remaining
    for pid in all_pids_to_kill:
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception as e:
            logging.warning(f"Failed to send SIGKILL to {pid}: {e}")

if __name__ == "__main__":
    main()
