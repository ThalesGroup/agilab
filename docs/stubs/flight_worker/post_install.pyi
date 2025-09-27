import sys
from pathlib import Path
import py7zr
from agi_env import AgiEnv

install_type = sys.argv[2]

archive = Path(__file__).parent / "dataset.7z"

dest_arg = sys.argv[3] if len(sys.argv) == 4 else None
