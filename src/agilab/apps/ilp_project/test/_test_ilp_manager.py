from __future__ import annotations

import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from ilp import IlpApp
from ilp.ilp_args import IlpArgs


@pytest.fixture()
def dummy_env() -> SimpleNamespace:
    return SimpleNamespace(logger=logging.getLogger("ilp-test"))


def test_simulate_produces_results(dummy_env, tmp_path):
    args = IlpArgs(data_uri=tmp_path)
    app = IlpApp(dummy_env, args=args)

    results = app.simulate()

    assert results, "Expected at least one routed demand"
    assert {
        "source",
        "destination",
        "bandwidth",
        "delivered_bandwidth",
        "routed",
        "path",
        "bearers",
        "latency",
    } <= results[0].keys()
    assert all(result["bandwidth"] > 0 for result in results)
    assert all(result["delivered_bandwidth"] <= result["bandwidth"] for result in results)
