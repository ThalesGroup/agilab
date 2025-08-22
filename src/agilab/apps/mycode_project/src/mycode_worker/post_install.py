import sys
from pathlib import Path
import py7zr
import shutil
import traceback
from agi_env import AgiEnv

if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        print("Usage: python post_install.py <app> <install_type> [destination]")
        sys.exit(1)

    env = AgiEnv(active_app=Path(sys.argv[1]), install_type=sys.argv[2])
    archive = Path(__file__).parent / "dataset.7z"
    dest_arg = sys.argv[3] if len(sys.argv) == 4 else None
    env.unzip_data(archive, dest_arg)
