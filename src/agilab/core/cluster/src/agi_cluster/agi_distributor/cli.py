import os
import sys
import signal
import time
import logging
from pathlib import Path
from tempfile import gettempdir
import shutil
import subprocess
import zipfile
import platform


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
    pid_files = set(Path("").glob("*.pid")) | set(Path(__file__).parent.glob("*.pid"))
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

def unzip(wenv=None):
    root = Path(wenv)
    root_src = root / 'src'
    if not root_src.exists():
        os.makedirs(root_src, exist_ok=True)
    eggs = root.glob('*.egg')

    for e in eggs:
          zipfile.ZipFile(str(e)).extractall(str(root_src))

    logger.info(f"Unzipped: {eggs}")

import threading
import time

def cpu_task():
    x = 0
    for _ in range(10**8):
        x += 1

def run_threads(n):
    threads = [threading.Thread(target=cpu_task) for _ in range(n)]
    start = time.time()
    for t in threads: t.start()
    for t in threads: t.join()
    return time.time() - start

def test_python_threads():
    t1 = run_threads(1)
    t2 = run_threads(2)

    logger.info(f"Time with 1 thread: {t1:.2f} s")
    logger.info(f"Time with 2 threads: {t2:.2f} s")

    if t2 < t1 * 1.5:
        logger.info("Likely freethreaded (true parallelism!)")
    else:
        logger.info("Likely normal Python (GIL active)")

def python_version():
    arch = platform.machine().lower().replace('arm64', 'aarch64').replace('amd64', 'x86_64')
    sys_name = platform.system().lower()
    # Map system name to pip tag
    if sys_name == 'darwin':
        os_tag = 'macos'
    elif sys_name == 'windows':
        os_tag = 'windows'
    elif sys_name == 'linux':
        os_tag = 'linux'
    else:
        os_tag = sys_name  # fallback

    version = platform.python_version()
    cache_tag = getattr(sys.implementation, "cache_tag", "")
    # Detect free-threaded (works for 3.13+)
    freethreaded = "+freethreaded"  #if "freethreaded" in cache_tag else ""

    # Build the tag
    tag = f"{sys.implementation.name}-{version}{freethreaded}-{os_tag}-{arch}-none"
    logger.info(tag)



if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "kill"
    arg = sys.argv[2] if len(sys.argv) > 2 else None
    exclude_pids = set()
    if arg and cmd == "kill":
        for pid_str in arg.split(","):
            try:
                exclude_pids.add(int(pid_str))
            except Exception:
                logging.warning(f"Invalid PID to exclude: {pid_str}")

    # Usage: python cli.py unzip <arg>
    if len(sys.argv) < 2:
        logger.error("Usage: python cli.py cmd <arg>")
        sys.exit(1)

    if cmd == "kill":
        kill(exclude_pids=exclude_pids)
    elif cmd == "clean":
        clean(wenv=arg)
    elif cmd == "unzip":
        unzip(wenv=arg)
    elif cmd == "threaded":
        test_python_threads()
    elif cmd == "platform":
        python_version()
    else:
        logger.error(f"Unknown command: {cmd}. Use 'kill', 'clean', 'unzip', 'threaded' or 'plateform'.")

