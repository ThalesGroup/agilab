import getpass
import os
import signal
import platform
import psutil

try:
    me = getpass.getuser()
    my_pid = os.getpid()

    # Collect own ancestry PIDs to avoid killing self or parents
    ancestor_pids = set()
    try:
        p = psutil.Process(my_pid)
        while p:
            ancestor_pids.add(p.pid)
            p = p.parent()
    except Exception:
        pass

    for p in psutil.process_iter(['pid', 'name', 'username', 'cmdline']):
        try:
            pid = p.info.get('pid')
            if pid in ancestor_pids:
                continue

            username = p.info.get('username') or ""
            if me not in username:
                continue

            name = p.info.get('name') or ""
            cmdline = p.info.get('cmdline') or []

            if ('dask' in name.lower()) or any('dask' in s.lower() for s in cmdline):
                print(f"Killing PID {pid}: {name} {' '.join(cmdline)}")

                proc = psutil.Process(pid)
                children = proc.children(recursive=True)

                # First try graceful termination on Unix/macOS, terminate on Windows
                for child in children:
                    if platform.system() == "Windows":
                        child.terminate()
                    else:
                        child.send_signal(signal.SIGTERM)

                if platform.system() == "Windows":
                    proc.terminate()
                else:
                    proc.send_signal(signal.SIGTERM)

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

except ImportError:
    print("psutil is required for this script.")