from __future__ import annotations

import os
from pathlib import Path

import pytest

from agi_env import AgiEnv


_CORE_TEST_REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def reset_agienv_singleton():
    """Keep AgiEnv singleton state from leaking across core tests."""
    os.chdir(_CORE_TEST_REPO_ROOT)
    AgiEnv.reset()
    yield
    os.chdir(_CORE_TEST_REPO_ROOT)
    AgiEnv.reset()
