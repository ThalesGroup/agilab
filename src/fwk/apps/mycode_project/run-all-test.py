from pathlib import Path
import subprocess


def exec(cmd, path, worker):
    path = str(Path(path).expanduser().absolute())
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, cwd=path
    )
    print("---- STDOUT ----")
    print(result.stdout)
    print("---- STDERR ----")
    print(result.stderr)
    if result.returncode != 0:
        if result.stderr.startswith("WARNING"):
            print(f"warning: worker {worker} - {cmd}")
            print(result.stderr)
        else:
            raise RuntimeError(
                f"error on worker {worker} - {cmd}\n{result.stderr}"
            )
    return result


def print_emoticon(result, success_check=lambda r: r.strip().lower() == "ok"):
    # Check and display any warnings or errors
    if result.stderr.strip():
        print(result.stderr.strip())
    output = result.stdout
    print("😀 mycode is working" if success_check(output) else "😞 mycode fail to run")

wenv = str(Path("~/wenv/mycode_worker").expanduser())

# uv run test/_test_flight_worker.py
cmd = "uv -q run test/test_mycdoe_manager.py"
res = exec(cmd, wenv, "localhost")
print_emoticon(res)

# uv run test/_test_flight_worker.py
cmd = "uv -q run test/test_code_worker.py"
res = exec(cmd, wenv, "localhost")
print_emoticon(res)
