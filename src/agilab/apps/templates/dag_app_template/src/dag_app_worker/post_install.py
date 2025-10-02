import sys
from pathlib import Path
import py7zr
import shutil
import traceback
from agi_env import AgiEnv

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python post_install.py <app> [destination]")
        sys.exit(1)

    args = sys.argv[1:]
    app_arg = Path(args[0]).expanduser()
    apps_dir = app_arg.parent if app_arg.parent != Path('.') else Path.cwd()

    dest_arg = None
    if len(args) >= 2:
        candidate = args[1]
        if candidate.isdigit():
            if len(args) >= 3:
                dest_arg = args[2]
        else:
            dest_arg = candidate

    env = AgiEnv(apps_dir=apps_dir, active_app=app_arg.name)
    archive = Path(__file__).parent / "dataset.7z"
    env.unzip_data(archive, dest_arg)
