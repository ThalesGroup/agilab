from __future__ import annotations

import pytest

from agi_env import AgiEnv


@pytest.fixture(autouse=True)
def reset_agienv_singleton():
    """Keep singleton state from leaking across tests."""
    AgiEnv.reset()
    yield
    AgiEnv.reset()
