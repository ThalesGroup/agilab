import py7zr
import os
import subprocess
import sys
from pathlib import Path


def exec(cmd, cwd=".", timeout=None):
    """Execute a command within a subprocess

    Args:
      cmd: the str of the command
      path: the path where to launch the command
      timeout: the maximum time to wait for execution to complete (Default value = None)
      cwd: (Default value = '.')

    Returns:

    """
    with subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        shell=True,
        cwd=os.path.abspath(cwd),
        text=True,
    ) as proc:
        # CAUTION: shell = True is mandatory for Linux
        try:
            outs, _ = proc.communicate(timeout=timeout)

            if proc.returncode or "failed" in outs or "error" in outs:
                raise RuntimeError(f"error: {cmd}\n{outs}")

        except subprocess.TimeoutExpired:
            proc.kill()
            outs, _ = proc.communicate()

        except subprocess.CalledProcessError as err:
            raise RuntimeError(f"error: {cmd}\n{outs}") from err

    return outs


def unzip_data(archive_path: str, extract_to: str):
    if not os.path.exists(archive_path):
        print(f"Archive '{archive_path}' does not exist.")
        sys.exit(1)

    os.makedirs(extract_to, exist_ok=True)

    try:
        with py7zr.SevenZipFile(archive_path, mode="r") as archive:
            archive.extractall(path=extract_to)
        print(f"Successfully extracted '{archive_path}' to '{extract_to}'.")
    except Exception as e:
        print(f"Failed to extract '{archive_path}': {e}")
        sys.exit(1)


def print_usage(script_name):
    print(f"Usage: python {script_name} <extraction_destination>")
    print("Example:")
    print(f"  python {script_name} /path/to/destination")


if __name__ == "__main__":
    # Ensure the correct number of arguments are provided
    if len(sys.argv) != 2:
        print("Error: Incorrect number of arguments.")
        print_usage(sys.argv[0])
        sys.exit(1)

    # Define the archive path (you can modify this or make it another argument if needed)
    archive = Path(__file__).parent /"dataset.7z"

    # Get the extraction destination from the first argument
    extraction_destination = sys.argv[1]

    # Optionally, resolve the absolute path
    extraction_destination = str(Path(extraction_destination).resolve())
    unzip_data(archive, extraction_destination)