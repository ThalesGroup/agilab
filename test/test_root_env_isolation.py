from __future__ import annotations

import os


def test_root_tests_start_without_ambient_secret_env_vars():
    assert os.environ.get("CLUSTER_CREDENTIALS") is None
    assert os.environ.get("OPENAI_API_KEY") is None
    assert os.environ.get("AZURE_OPENAI_API_KEY") is None
