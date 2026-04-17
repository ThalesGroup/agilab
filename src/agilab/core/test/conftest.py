from __future__ import annotations

import pytest

from agi_env import AgiEnv


@pytest.fixture(autouse=True)
def reset_agienv_singleton():
    """Keep AgiEnv singleton state from leaking across core tests."""
    AgiEnv.reset()
    yield
    AgiEnv.reset()
