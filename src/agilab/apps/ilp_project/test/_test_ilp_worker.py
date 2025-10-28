from __future__ import annotations

import sys
from pathlib import Path

PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from ilp_worker import Demand, Flyenv, MILP


def test_milp_allocates_single_demand():
    env = Flyenv()
    env.seed(0)
    solver = MILP(env)

    demand = Demand(0, 1, 1000)
    results = solver.solve([demand])

    assert len(results) == 1
    assert results[0].routed is True
    assert results[0].path, "Expected solver to return a non-empty path"
    assert results[0].available_capacity >= demand.bw
    assert results[0].delivered_bandwidth == demand.bw
    assert results[0].bearers
    assert results[0].latency > 0


def test_solver_prefers_high_capacity_bearer():
    env = Flyenv()
    env.seed(0)
    solver = MILP(env)

    demand = Demand(0, 1, 8000)
    result = solver.solve([demand])[0]

    assert result.routed is True
    assert result.bearers[0] == "SAT"


def test_solver_respects_latency_constraint():
    env = Flyenv()
    env.seed(0)
    solver = MILP(env)

    demand = Demand(0, 1, 6000, max_latency=100)
    result = solver.solve([demand])[0]

    assert result.routed is True
    assert result.bearers[0] == "IVDL"
    assert result.latency <= demand.max_latency
