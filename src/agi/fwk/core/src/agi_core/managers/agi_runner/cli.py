import os
import sys
import signal
import time
import logging
from pathlib import Path
from tempfile import gettempdir
import shutil
import subprocess

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def clean(wenv=None):
    try:
        scratch = Path(gettempdir()) / 'dask-scratch-space'
        shutil.rmtree(scratch, ignore_errors=True)
        logger.info(f"Removed {scratch}")
        if wenv:
            shutil.rmtree(wenv, ignore_errors=True)
            logger.info(f"Removed {wenv}")
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")

def get_processes_containing(substring):
    """Cross-platform: finds PIDs where command or name contains substring."""
    substring = substring.lower()
    pids = set()
    if os.name != "nt":
        # Unix-like: ps
        try:
            output = subprocess.check_output(["ps", "-eo", "pid,command"], text=True)
            for line in output.strip().splitlines()[1:]:
                try:
                    pid_str, cmd = line.strip().split(None, 1)
                    if substring in cmd.lower():
                        pids.add(int(pid_str))
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"Unix ps failed: {e}")
    else:
        # Windows: tasklist
        try:
            output = subprocess.check_output(["tasklist", "/fo", "csv", "/nh"], text=True)
            for line in output.strip().splitlines():
                parts = [p.strip('"') for p in line.split('","')]
                if len(parts) < 2:
                    continue
                name, pid_str = parts[0], parts[1]
                if substring in name.lower():
                    try:
                        pids.add(int(pid_str))
                    except:
                        continue
        except Exception as e:
            logger.warning(f"Windows tasklist failed: {e}")
    return pids

def get_child_pids(parent_pids):
    """Unix-only: find direct child PIDs."""
    children = set()
    if os.name != "nt":
        try:
            output = subprocess.check_output(["ps", "-eo", "pid,ppid"], text=True)
            for line in output.strip().splitlines()[1:]:
                try:
                    pid_str, ppid_str = line.strip().split(None, 1)
                    pid = int(pid_str)
                    ppid = int(ppid_str)
                    if ppid in parent_pids:
                        children.add(pid)
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"ps for child processes failed: {e}")
    return children

def kill_pids(pids, sig):
    for pid in pids:
        try:
            os.kill(pid, sig)
            logger.info(f"Sent signal {sig} to PID {pid}")
        except ProcessLookupError:
            logger.info(f"Process {pid} not found (already stopped)")
        except PermissionError:
            logger.warning(f"No permission to kill process {pid}")
        except Exception as e:
            logger.warning(f"Failed to kill PID {pid} with signal {sig}: {e}")

def kill(exclude_pids=None):
    if exclude_pids is None:
        exclude_pids = set()
    current_pid = os.getpid()
    exclude_pids.add(current_pid)
    dask_pids = get_processes_containing("dask")
    dask_pids -= exclude_pids

    if dask_pids:
        logger.info(f"Found 'dask' processes to kill: {dask_pids}")

    kill_pids(dask_pids, signal.SIGTERM)
    time.sleep(2)
    # SIGKILL may not exist on Windows!
    if hasattr(signal, "SIGKILL"):
        kill_pids(dask_pids, signal.SIGKILL)

    # Collect PID files (dedup)
    pid_files = set(Path(".").glob("*.pid")) | set(Path(__file__).parent.glob("*.pid"))
    file_pids = set()
    for pid_file in pid_files:
        try:
            text = pid_file.read_text().strip()
            pid = int(text)
            if pid not in exclude_pids:
                file_pids.add(pid)
            else:
                logger.info(f"Skipping excluded pid {pid} from file {pid_file}")
        except Exception as e:
            logger.warning(f"Could not read pid from {pid_file}: {e}")
        try:
            pid_file.unlink()
        except Exception as e:
            logger.warning(f"Could not remove pid file {pid_file}: {e}")

    # Only works on Unix
    child_pids = get_child_pids(file_pids)
    file_pids.update(child_pids)
    file_pids -= exclude_pids

    if file_pids:
        logger.info(f"PIDs from pid files and their children to kill: {file_pids}")
        kill_pids(file_pids, signal.SIGTERM)
        time.sleep(2)
        if hasattr(signal, "SIGKILL"):
            kill_pids(file_pids, signal.SIGKILL)
    else:
        logger.info("No Dask process running.")

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "kill"
    arg = sys.argv[2] if len(sys.argv) > 2 else None
    exclude_pids = set()
    if arg and cmd == "kill":
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
