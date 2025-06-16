import shutil
import sys
import os
from pathlib import Path
from tempfile import gettempdir
from logging import getLogger
logger = logging.getLogger(__name__)


try:
    wenv_path = Path(__file__).parent
    dirs = [os.path.join(gettempdir(), 'dask-scratch-space'), wenv_path]
    for d in dirs:
        shutil.rmtree(d, ignore_errors=True)
    os.makedirs(os.path.join(wenv_path, 'src'))

except Exception as e:
    logging.error(f"Error removing {directory}: {e}")
