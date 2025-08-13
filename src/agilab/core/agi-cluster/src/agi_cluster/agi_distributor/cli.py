import os
import sys
import signal
import logging
from pathlib import Path
from tempfile import gettempdir
import shutil
import subprocess
import zipfile
import platform
import threading
import time
import faulthandler

faulthandler.enable()

USAGE = """
Usage: python cli.py <cmd> [arg]

Commands:
  kill [exclude_pids]      Kill processes, excluding comma-separated PIDs (optional)
  clean <wenv_path>        Clean the given wenv directory
  unzip <wenv_path>        Unzip resources into the given wenv directory
  threaded                 Run the Python threads test
  platform                 Show Python platform/version info

Examples:
  python cli.py kill
  python cli.py kill 1234,5678
  python cli.py clean /path/to/wenv
  python cli.py unzip /path/to/wenv
  python cli.py threaded
  python cli.py platform
"""

# --- Tunables for speed ---
PS_TIMEOUT = float(os.environ.get("CLI_PS_TIMEOUT", "0.35"))
TASKLIST_TIMEOUT = float(os.environ.get("CLI_TASKLIST_TIMEOUT", "0.6"))
POLL_INTERVAL = float(os.environ.get("CLI_POLL_INTERVAL", "0.02"))
GRACE_TOTAL = float(os.environ.get("CLI_GRACE_TOTAL", "0.30"))
FREETHREADED_THRESHOLD = float(os.environ.get("CLI_FREETHREADED_THRESHOLD", "0.80"))
BASELINE_TARGET_S = float(os.environ.get("CLI_BASELINE_TARGET_S", "0.15"))  # target single-thread work

logging.basicConfig(level=os.environ.get("CLI_LOGLEVEL", "INFO").upper())
logger = logging.getLogger(__name__)

# ---------------- helpers ----------------
def clean(wenv=None):
    try:
        scratch = Path(gettempdir()) / 'dask-scratch-space'
        logger.info(f"Cleaning {scratch}")
        shutil.rmtree(scratch, ignore_errors=True)
        logger.info(f"Removed {scratch}")
        if wenv:
            logger.info(f"Cleaning {wenv}")
            shutil.rmtree(wenv, ignore_errors=True)
            logger.info(f"Removed {wenv}")
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")

def get_processes_containing(substring: str):
    substring = substring.lower()
    pids = set()
    if os.name != "nt":
        try:
            logger.debug("Running ps to find matching processes...")
            # Headerless, faster to parse
            output = subprocess.check_output(
                ["ps", "-A", "-o", "pid=", "-o", "command="],
                text=True, timeout=PS_TIMEOUT
            )
            for line in output.splitlines():
                try:
                    pid_str, cmd = line.strip().split(None, 1)
                    if substring in cmd.lower():
                        pids.add(int(pid_str))
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"Unix ps failed: {e}")
    else:
        try:
            logger.debug("Running tasklist to find matching processes...")
            output = subprocess.check_output(
                ["tasklist", "/fo", "csv", "/nh"], text=True, timeout=TASKLIST_TIMEOUT
            )
            for line in output.strip().splitlines():
                parts = [p.strip('"') for p in line.split('","')]
                if len(parts) >= 2:
                    name, pid_str = parts[0], parts[1]
                    if substring in name.lower():
                        try:
                            pids.add(int(pid_str))
                        except Exception:
                            continue
        except Exception as e:
            logger.warning(f"Windows tasklist failed: {e}")
    return pids

def get_child_pids(parent_pids):
    children = set()
    if not parent_pids:
        return children
    if os.name != "nt":
        try:
            logger.debug("Finding child PIDs...")
            output = subprocess.check_output(
                ["ps", "-A", "-o", "pid=", "-o", "ppid="], text=True, timeout=PS_TIMEOUT
            )
            for line in output.strip().splitlines():
                try:
                    pid_str, ppid_str = line.strip().split(None, 1)
                    pid = int(pid_str); ppid = int(ppid_str)
                    if ppid in parent_pids:
                        children.add(pid)
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"ps for child processes failed: {e}")
    return children

def _is_alive(pid: int) -> bool:
    try:
        # On Unix, signal 0 checks existence; on Windows raises if invalid.
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Probably alive but not permitted; assume alive so we attempt SIGKILL next.
        return True
    except Exception:
        # Unknown; be conservative.
        return True

def kill_pids(pids, sig):
    survivors = set()
    for pid in pids:
        try:
            os.kill(pid, sig)
            logger.info(f"Sent signal {sig} to PID {pid}")
        except ProcessLookupError:
            logger.info(f"Process {pid} not found (already stopped)")
        except PermissionError:
            logger.warning(f"No permission to kill process {pid}")
            survivors.add(pid)
        except Exception as e:
            logger.warning(f"Failed to kill PID {pid} with signal {sig}: {e}")
            survivors.add(pid)
    return survivors

def _poll_until_dead(pids, total=GRACE_TOTAL, interval=POLL_INTERVAL):
    deadline = time.monotonic() + total
    remaining = set(pids)
    while remaining and time.monotonic() < deadline:
        remaining = {pid for pid in remaining if _is_alive(pid)}
        if remaining:
            time.sleep(interval)
    return remaining

def kill(exclude_pids=None):
    if exclude_pids is None:
        exclude_pids = set()
    current_pid = os.getpid()
    exclude_pids.add(current_pid)

    # 1) Match by name
    dask_pids = get_processes_containing("dask")
    dask_pids -= exclude_pids

    sent = kill_pids(dask_pids, signal.SIGTERM)
    remaining = _poll_until_dead(dask_pids)

    if remaining and hasattr(signal, "SIGKILL"):
        kill_pids(remaining, signal.SIGKILL)

    # 2) Match by *.pid files
    pid_files = set(Path("").glob("*.pid")) | set(Path(__file__).parent.glob("*.pid"))
    file_pids = set()
    for pid_file in pid_files:
        try:
            pid = int(pid_file.read_text().strip())
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

    if file_pids:
        file_pids |= get_child_pids(file_pids)
        file_pids -= exclude_pids
        if file_pids:
            logger.info(f"PIDs from pid files/children to kill: {file_pids}")
            kill_pids(file_pids, signal.SIGTERM)
            survivors = _poll_until_dead(file_pids)
            if survivors and hasattr(signal, "SIGKILL"):
                kill_pids(survivors, signal.SIGKILL)
    else:
        logger.info("No Dask process running.")

def unzip(wenv=None):
    try:
        root = Path(wenv)
        root_src = root / 'src'
        logger.info(f"Ensuring src directory exists at {root_src}")
        root_src.mkdir(parents=True, exist_ok=True)
        eggs = list(root.glob('*.egg'))
        for e in eggs:
            logger.info(f"Extracting {e}")
            with zipfile.ZipFile(e) as zf:
                zf.extractall(root_src)
        logger.info(f"Unzipped: {eggs}")
    except Exception as e:
        logger.error(f"Error during unzip: {e}")

# ---------------- fast threaded test ----------------
def _busy_work(iters: int) -> int:
    # Pure Python arithmetic to keep the GIL busy.
    x = 0
    for _ in range(iters):
        x = (x * 1664525 + 1013904223) & 0xFFFFFFFF
    return x

def _time_busy(iters: int) -> float:
    start = time.perf_counter()
    _busy_work(iters)
    return time.perf_counter() - start

def _choose_iters(target_s: float = BASELINE_TARGET_S) -> int:
    # Quick single-shot calibration to hit ~target_s for 1 thread.
    iters = 200_000
    t = _time_busy(iters)
    if t <= 0:
        return 5_000_000
    scale = target_s / t
    # Keep within reasonable bounds
    return max(50_000, min(20_000_000, int(iters * scale)))

def threaded(nthreads=2, iters=None) -> float:
    """Run a CPU-bound workload across n threads; return wall time."""
    if iters is None:
        iters = _choose_iters()
    logger.debug(f"threaded: nthreads={nthreads}, iters={iters} per thread")

    def worker():
        _busy_work(iters)

    threads = [threading.Thread(target=worker, name=f"Worker-{i}") for i in range(nthreads)]
    start = time.perf_counter()
    for t in threads: t.start()
    for t in threads: t.join()
    dt = time.perf_counter() - start
    logger.info(f"Threads={nthreads} wall={dt:.3f}s")
    return dt

def test_python_threads():
    logger.info("Testing Python threads for true parallelism")
    t1 = threaded(nthreads=1)
    t2 = threaded(nthreads=2)

    logger.info(f"Time with 1 thread: {t1:.3f} s")
    logger.info(f"Time with 2 threads: {t2:.3f} s")

    # If free-threaded, CPU-bound threads should reduce wall time noticeably.
    if t2 <= t1 * FREETHREADED_THRESHOLD:
        logger.info("Likely freethreaded (true parallelism!)")
    else:
        logger.info("Likely normal Python (GIL active)")

def python_version():
    arch = platform.machine().lower().replace('arm64', 'aarch64').replace('amd64', 'x86_64')
    sys_name = platform.system().lower()
    if sys_name == 'darwin':
        os_tag = 'macos'
    elif sys_name == 'windows':
        os_tag = 'windows'
    elif sys_name == 'linux':
        os_tag = 'linux'
    else:
        os_tag = sys_name

    version = platform.python_version()
    cache_tag = getattr(sys.implementation, "cache_tag", "")
    freethreaded = "+freethreaded" if "freethreaded" in cache_tag else ""
    tag = f"{sys.implementation.name}-{version}{freethreaded}-{os_tag}-{arch}-none"
    logger.info(tag)

# ---------------- main ----------------
if __name__ == "__main__":
    if len(sys.argv) == 1:
        print(USAGE)
        sys.exit(1)

    cmd = sys.argv[1]
    arg = sys.argv[2] if len(sys.argv) > 2 else None
    exclude_pids = set()

    if cmd == "kill":
        if arg:
            for pid_str in arg.split(","):
                try:
                    exclude_pids.add(int(pid_str))
                except Exception:
                    logger.warning(f"Invalid PID to exclude: {pid_str}")
        kill(exclude_pids=exclude_pids)

    elif cmd == "clean":
        if not arg:
            print("Missing argument for 'clean'\n" + USAGE)
            sys.exit(1)
        clean(wenv=arg)

    elif cmd == "unzip":
        if not arg:
            print("Missing argument for 'unzip'\n" + USAGE)
            sys.exit(1)
        unzip(wenv=arg)

    elif cmd == "threaded":
        test_python_threads()

    elif cmd == "platform":
        python_version()

    else:
        print(f"Unknown command: {cmd}\n{USAGE}")
        sys.exit(1)
