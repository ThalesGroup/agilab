import sys
import os
import logging
from pathlib import Path
from tempfile import gettempdir
import shutil

logger = logging.getLogger(__name__)

def cleanup_wenv(wenv_rel=None):
    try:
        # Use wenv_rel if provided, else fallback to script directory
        if wenv:
            wenv_path = Path(wenv)
        else:
            return None
        # List of directories to remove
        dirs = [Path(gettempdir()) / 'dask-scratch-space', wenv_path]
        for directory in dirs:
            shutil.rmtree(directory, ignore_errors=True)
        # Ensure 'src' directory exists under wenv_path
        (wenv_path / 'src').mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")

if __name__ == "__main__":
    wenv = sys.argv[1] if len(sys.argv) > 1 else None
    cleanup_wenv(wenv)


