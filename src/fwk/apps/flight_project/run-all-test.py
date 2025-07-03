#!/usr/bin/env python3
import os
from pathlib import Path
import subprocess

def exec(cmd, path, worker):
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

def print_emoticon(result, label="flight", success_check=None):
    GREEN = "\033[1;32m"
    RED = "\033[1;31m"
    RESET = "\033[0m"
    if success_check is None:
        success_check = lambda result: (result.returncode == 0)
    if result.stderr.strip():
        print(result.stderr.strip())
    if success_check(result):
        print(f"{GREEN}✅ {label} is working{RESET}")
    else:
        print(f"{RED}❌ {label} fail to run{RESET}")

def main():
    os.chdir(Path(__file__).parent)
    wenv = str(Path("~/wenv/flight_worker").expanduser())

    # Change the labels here as you wish
    tests = [
        ("uv -q run test/test_flight_manager.py", "flight (manager)"),
        ("uv -q run test/test_flight_worker.py", "flight_worker"),
    ]

    for cmd, label in tests:
        res = exec(cmd, ".", label)
        print_emoticon(res, label=label)

if __name__ == "__main__":
    main()
