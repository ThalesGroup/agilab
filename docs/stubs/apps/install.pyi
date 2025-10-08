import os
import sys
import asyncio
from pathlib import Path
import argparse
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv
from typing import Any

node_src = str(Path(__file__).parents[1] / 'core/node/src')

def main(*args: Any, **kwargs: Any) -> Any: ...
