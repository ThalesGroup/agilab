import os
import sys
import getpass
import signal
import subprocess
import platform
import logging

logger = logging.getLogger("clean_dask")
logging.basicConfig(level=logging.INFO)

def get_ancestry_pids():
    """Return a set of own pid and ancestors up to init."""
    pids = set()
    try:
        pid = os.getpid()
        while True:
            pids.add(pid)
            ppid = os.getppid()
            if ppid == 0 or ppid == pid:
                break
            pid = ppid
    except Exception:
        pass
    return pids

def get_processes_unix(user):
    """Yield dicts of {'pid', 'user', 'name', 'cmd'} for user's processes (Unix)."""
    try:
        out = subprocess.check_output(
            ["ps", "-eo", "pid,user,comm,args"], text=True, stderr=subprocess.DEVNULL
        )
        for line in out.splitlines()[1:]:
            parts = line.strip().split(None, 3)
            if len(parts) < 4:
                continue
            pid_str, u, name, cmd = parts
            try:
                pid = int(pid_str)
            except Exception:
                continue
            if u == user:
                yield {"pid": pid, "user": u, "name": name, "cmd": cmd}
    except Exception as e:
        logger.error(f"ps failed: {e}")

def get_processes_windows(user):
    """Yield dicts of {'pid', 'user', 'name', 'cmd'} for user's processes (Windows)."""
    try:
        out = subprocess.check_output(
            ["wmic", "process", "get", "ProcessId,CommandLine,Name,UserModeTime", "/FORMAT:csv"],
            text=True, stderr=subprocess.DEVNULL
        )
        for line in out.splitlines()[1:]:
            if not line.strip():
                continue
            parts = line.strip().split(",")
            if len(parts) < 4:
                continue
            _, cmd, name, pid_str = parts
            try:
                pid = int(pid_str)
            except Exception:
                continue
            # WMIC doesn't return user easily, so only match our own session
            yield {"pid": pid, "user": user, "name": name or "", "cmd": cmd or ""}
    except Exception as e:
        logger.error(f"wmic failed: {e}")

def get_child_pids(parent_pid, all_procs):
    """Find child pids recursively from the all_procs list."""
    children = []
    to_search = [parent_pid]
    seen = set(to_search)
    while to_search:
        pid = to_search.pop()
        for proc in all_procs:
            try:
                if int(proc.get("ppid", -1)) == pid:
                    cpid = proc["pid"]
                    if cpid not in seen:
                        children.append(cpid)
                        to_search.append(cpid)
                        seen.add(cpid)
            except Exception:
                continue
    return children

def kill_pid(pid):
    try:
        if platform.system() == "Windows":
            subprocess.call(['taskkill', '/PID', str(pid), '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            os.kill(pid, signal.SIGTERM)
    except Exception as e:
        logger.info(f"Failed to kill {pid}: {e}")

def main():
    me = getpass.getuser()
    ancestry = get_ancestry_pids()
    system = platform.system()
    # On Unix, get ppid for each process (needed for recursive kill)
    all_procs = []

    if system in ("Linux", "Darwin"):
        # Use "ps -eo pid,ppid,user,comm,args" for full ancestry
        out = subprocess.check_output(
            ["ps", "-eo", "pid,ppid,user,comm,args"], text=True, stderr=subprocess.DEVNULL
        )
        for line in out.splitlines()[1:]:
            parts = line.strip().split(None, 4)
            if len(parts) < 5:
                continue
            pid_str, ppid_str, u, name, cmd = parts
            try:
                pid = int(pid_str)
                ppid = int(ppid_str)
            except Exception:
                continue
            if u == me:
                all_procs.append({"pid": pid, "ppid": ppid, "user": u, "name": name, "cmd": cmd})
        procs = all_procs
    else:  # Windows
        procs = list(get_processes_windows(me))

    for proc in procs:
        pid = proc["pid"]
        if pid in ancestry:
            continue
        name = proc.get("name", "")
        cmd = proc.get("cmd", "")
        # Look for dask in name or command
        if ("dask" in name.lower()) or ("dask" in cmd.lower()):
            logger.info(f"Killing PID {pid}: {name} {cmd}")
            # First try to kill children (if possible)
            if system in ("Linux", "Darwin"):
                children = get_child_pids(pid, all_procs)
                for cpid in children:
                    kill_pid(cpid)
            kill_pid(pid)

if __name__ == "__main__":
    main()
