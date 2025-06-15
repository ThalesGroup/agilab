import shutil
import sys
import os
from pathlib import Path
from tempfile import gettempdir


try:
    wenv_path = Path(__file__).parent
    dirs = [os.path.join(gettempdir(), 'dask-scratch-space'), wenv_path]
    for d in dirs:
        shutil.rmtree(d, ignore_errors=True)
    os.makedirs(os.path.join(wenv_path, 'src'))

except Exception as e:
    print(f"Error removing {directory}: {e}")
