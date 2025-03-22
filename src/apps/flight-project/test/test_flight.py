from pathlib import Path
import subprocess


def exec(cmd, path, worker):
    """Execute a command within a subprocess.

    Args:
      cmd: the str of the command.
      path: the path where to launch the command.
      worker: worker identifier.
    Returns:
      A CompletedProcess object.
    """
    path = str(Path(path).absolute())

    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, check=True, cwd=path
    )
    if result.returncode != 0:
        if result.stderr.startswith("WARNING"):
            print(f"warning: Agi_worker {worker} - {cmd}")
            print(result.stderr)
        else:
            raise RuntimeError(
                f"error on Agi_worker {worker} - {cmd}\n{result.stderr}"
            )
    return result


def print_emoticon(result, success_check=lambda r: r.strip().lower() == "ok"):
    # Check and display any warnings or errors
    if result.stderr.strip():
        print(result.stderr.strip())
    output = result.stdout
    print("😀 flight installed" if success_check(output) else "😞 flight fail to install")


# uv sync
cmd = "uv sync"
res = exec(cmd, ".", "localhost")
print_emoticon(res)

test_manager = "uv run test/test_flight_manager.py "

# uv run test/test_flight_manager.py install
cmd = test_manager + "install"
res = exec(cmd, ".", "localhost")
print_emoticon(res)

# uv run test/test_flight_manager.py distribute
cmd = test_manager + "distribute"
res = exec(cmd, ".", "localhost")
print_emoticon(res)

# uv pip list from current directory (.venv)
cmd = "uv pip list"
res = exec(cmd, ".", "localhost")
# Count lines containing "agilab-"
lines = sum(1 for line in res.stdout.splitlines() if "agi-" in line)
print("😀 venv installed" if lines >= 4 else "😞 venv fail to install")
if res.stderr.strip():
    print(res.stderr.strip())

wenv = "../../wenv/flight_worker"

# uv pip list from ../../wenv/flight_worker
cmd = "uv pip list"
res = exec(cmd, wenv, "localhost")
# Count lines containing "agi-"
lines2 = sum(1 for line in res.stdout.splitlines() if "agi-" in line)
print("😀 wenv installed" if lines2 >= 4 else "😞 wenv fail to install")
if res.stderr.strip():
    print(res.stderr.strip())

# uv build
cmd = "uv build"
res = exec(cmd, ".", "localhost")
print_emoticon(res)

# uv run test/test_flight_worker.py
cmd = "uv run test/test_flight_worker.py"
res = exec(cmd, wenv, "localhost")
print_emoticon(res)