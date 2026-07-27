from __future__ import annotations

import os
import sys
from types import SimpleNamespace

from tools.testing import pytest_entrypoint


def test_cleaned_environment_removes_only_uv_target_controls() -> None:
    cleaned = pytest_entrypoint.cleaned_test_environment(
        {
            "UV_PROJECT_ENVIRONMENT": "/unsafe/shared-venv",
            "UV_RUN_RECURSION_DEPTH": "1",
            "VIRTUAL_ENV": "/unsafe/active-venv",
            "AGILAB_TEST_SENTINEL": "preserved",
        }
    )

    assert "UV_PROJECT_ENVIRONMENT" not in cleaned
    assert "UV_RUN_RECURSION_DEPTH" not in cleaned
    assert "VIRTUAL_ENV" not in cleaned
    assert cleaned["AGILAB_TEST_SENTINEL"] == "preserved"


def test_main_clears_uv_target_before_pytest_runs(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def _pytest_main(argv):
        seen["argv"] = list(argv)
        seen["environment"] = dict(os.environ)
        return 0

    monkeypatch.setitem(sys.modules, "pytest", SimpleNamespace(main=_pytest_main))
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", "/unsafe/shared-venv")
    monkeypatch.setenv("UV_RUN_RECURSION_DEPTH", "1")
    monkeypatch.setenv("VIRTUAL_ENV", "/unsafe/active-venv")
    monkeypatch.setenv("AGILAB_TEST_SENTINEL", "preserved")

    assert pytest_entrypoint.main(["-q", "test/example.py"]) == 0

    assert seen["argv"] == ["-q", "test/example.py"]
    environment = seen["environment"]
    assert isinstance(environment, dict)
    assert "UV_PROJECT_ENVIRONMENT" not in environment
    assert "UV_RUN_RECURSION_DEPTH" not in environment
    assert "VIRTUAL_ENV" not in environment
    assert environment["AGILAB_TEST_SENTINEL"] == "preserved"
