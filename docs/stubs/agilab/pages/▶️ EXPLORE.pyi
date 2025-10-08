from __future__ import annotations
import os
import sys
import socket
import time
import hashlib
from pathlib import Path
from typing import Union
import asyncio
import streamlit as st
import streamlit.components.v1 as components
from IPython.lib import backgroundjobs as bg
import logging
import subprocess
import tomli
import tomli_w
from agi_env.pagelib import get_about_content, render_logo, select_project, inject_theme
from agi_env import AgiEnv, normalize_path
from typing import Any

logger = logging.getLogger(__name__)

resources_path = Path(__file__).resolve().parents[1] / "resources"

def _is_port_open(*args: Any, **kwargs: Any) -> Any: ...

def _python_in_venv(*args: Any, **kwargs: Any) -> Any: ...

def _find_venv_for(*args: Any, **kwargs: Any) -> Any: ...

def _port_for(*args: Any, **kwargs: Any) -> Any: ...

jobs = bg.BackgroundJobManager()

def exec_bg(*args: Any, **kwargs: Any) -> Any: ...

def _ensure_sidecar(*args: Any, **kwargs: Any) -> Any: ...

def discover_views(*args: Any, **kwargs: Any) -> Any: ...

def _hide_parent_sidebar(*args: Any, **kwargs: Any) -> Any: ...

def _read_config(*args: Any, **kwargs: Any) -> Any: ...

def _write_config(*args: Any, **kwargs: Any) -> Any: ...

def main(*args: Any, **kwargs: Any) -> Any: ...

def render_view_page(*args: Any, **kwargs: Any) -> Any: ...
