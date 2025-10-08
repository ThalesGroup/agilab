import asyncio
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv, normalize_path
from pathlib import Path
from typing import Any

APPS_DIR = "/Users/example/agilab/src/agilab/apps"

APP = "flight_project"

def main(*args: Any, **kwargs: Any) -> Any: ...
