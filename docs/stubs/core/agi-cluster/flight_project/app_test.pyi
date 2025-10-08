"""Run manager/worker test suites. Coverage is DISABLED by default.
Enable it with --with-cov (then XML + optional badge will be produced)."""

import os
import asyncio
import sys
from pathlib import Path
from agi_env import AgiEnv
from typing import Any

def main(*args: Any, **kwargs: Any) -> Any: ...
