"""Package your_code

    mycode: module mycode
    Auteur: Jean-Pierre Morard
    Copyright: Thales SIX GTS France SAS"""

from numba import njit, prange
import json
import os
import re
import shutil
import subprocess
import warnings
from pathlib import Path
from typing import Any
import py7zr
from agi_node.agi_dispatcher import WorkDispatcher, BaseWorker
import logging
from .mycode_args import (
    MycodeArgs,
)

logger = logging.getLogger(__name__)

class Mycode(BaseWorker):
    def __init__(self, *args: Any, **kwargs: Any) -> Any: ...
    def build_distribution(self, *args: Any, **kwargs: Any) -> Any: ...
