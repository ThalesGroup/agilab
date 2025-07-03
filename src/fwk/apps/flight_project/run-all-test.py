#!/usr/bin/env python3
import os
from pathlib import Path
import subprocess

def exec(cmd, path, worker):
    """
    Execute a command within a subprocess.
    Args:
      cmd: the str of the command.
      path: the path where to launch the command.
      worker: worker identifier.
    Returns:
      A CompletedProcess object.
    """
    path = str(Path(path).expanduser().absolute())
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, cwd=path
    )
    print(f"\n--- Command: {cmd} (worker: {worker}) ---")
    print("---- STDOUT ----")
    print(result.stdout)
    print("---- STDERR ----")
    print(result.stderr)
    if result.returncode != 0:
        if result.stderr.strip().startswith("WARNING"):
            print(f"warning: worker {worker} - {cmd}")
            print(result.stderr)
        else:
            print(f"error: worker {worker} - {cmd}\n{result.stderr}")
    return result

def print_emoticon(result, success_check=None):
    GREEN = "\033[1;32m"
    RED = "\033[1;31m"
    RESET = "\033[0m"
    if success_check is None:
        success_check = lambda result: (result.returncode == 0)
    if result.stderr.strip():
        print(result.stderr.strip())
    if success_check(result):
        print(f"{GREEN}✅ flight is working{RESET}")
    else:
        print(f"{RED}❌ flight fail to run{RESET}")


def main():
    # Always start in the script's directory
    os.chdir(Path(__file__).parent)
    # Where is your wenv? (not actually used here but can be passed if needed)
    wenv = str(Path("~/wenv/flight_worker").expanduser())

    # List of (command, worker_label)
    tests = [
        ("uv -q run test/test_flight_manager.py", "flight_manager"),
        ("uv -q run test/test_flight_worker.py", "flight_worker"),
    ]

    for cmd, worker in tests:
        res = exec(cmd, ".", worker)
        print_emoticon(res)

if __name__ == "__main__":
    main()
