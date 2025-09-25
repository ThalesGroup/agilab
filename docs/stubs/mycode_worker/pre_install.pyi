import os
import sys
import argparse
from pathlib import Path
import parso
from agi_env import AgiEnv, normalize_path
import logging
from typing import Any

logger = logging.getLogger(__name__)

def get_decorator_name(*args: Any, **kwargs: Any) -> Any: ...

def process_decorators(*args: Any, **kwargs: Any) -> Any: ...

def remove_decorators(*args: Any, **kwargs: Any) -> Any: ...

def prepare_for_cython(*args: Any, **kwargs: Any) -> Any: ...

def main(*args: Any, **kwargs: Any) -> Any: ...
