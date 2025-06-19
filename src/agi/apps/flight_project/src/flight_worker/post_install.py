import sys
from pathlib import Path
import py7zr
import shutil
import traceback
from agi_env import AgiEnv

def unzip_data(env, archive_path: Path, extract_to: Path | str = None):
    archive_path = Path(archive_path)
    if not archive_path.exists():
        print(f"Warning: Archive '{archive_path}' does not exist. Skipping extraction.")
        return  # Do not exit, just warn

    # Normalize extract_to to a Path relative to cwd or absolute
    if not extract_to:
        extract_to = Path("data")
    dest = env.home_abs / Path(extract_to)
    dataset = dest / "dataset"

    # Clear existing folder if not empty to avoid extraction errors on second call
    if dataset.exists() and any(dataset.iterdir()):
        print(f"Destination '{dataset}' exists and is not empty. Clearing it before extraction.")
        shutil.rmtree(dataset)
    dest.mkdir(parents=True, exist_ok=True)

    try:
        with py7zr.SevenZipFile(archive_path, mode="r") as archive:
            archive.extractall(path=dest)
        print(f"Successfully extracted '{archive_path}' to '{dest}'.")
    except Exception as e:
        print(f"Failed to extract '{archive_path}': {e}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        print("Usage: python post_install.py <app> <install_type> [destination]")
        sys.exit(1)

    env = AgiEnv(active_app=sys.argv[1], install_type=sys.argv[2])
    archive = Path(__file__).parent / "dataset.7z"
    dest_arg = sys.argv[3] if len(sys.argv) == 4 else None
    unzip_data(env, archive, dest_arg)
