"""AGI app setup
Author: Jean-Pierre Morard
Tested on Windows, Linux and MacOS"""

import getpass
import sys
import os
import shutil
import logging
from pathlib import Path
from zipfile import ZipFile
import argparse
import subprocess
from setuptools import setup, find_packages, Extension, SetuptoolsDeprecationWarning
from Cython.Build import cythonize
from agi_env import AgiEnv, normalize_path
from agi_env import AgiLogger
import warnings
from typing import Any

def _inject_shared_site_packages(*args: Any, **kwargs: Any) -> Any: ...

def _relative_to_home(*args: Any, **kwargs: Any) -> Any: ...

def parse_custom_args(*args: Any, **kwargs: Any) -> Any: ...

def truncate_path_at_segment(*args: Any, **kwargs: Any) -> Any: ...

def find_sys_prefix(*args: Any, **kwargs: Any) -> Any: ...

def create_symlink_for_module(*args: Any, **kwargs: Any) -> Any: ...

def cleanup_links(*args: Any, **kwargs: Any) -> Any: ...

def _keep_lflag(*args: Any, **kwargs: Any) -> Any: ...

def main(*args: Any, **kwargs: Any) -> Any: ...
