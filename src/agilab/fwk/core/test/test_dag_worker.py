import time
import pytest

from agi_core.workers.agi_worker import AgiWorker
from agi_core.workers.dag_worker import AgiDagWorker

# --- Dummy functions for testing ---
def f1():
    f1.executed.append("f1")
f1.executed = []

def f2():
    f2.executed.append("f2")
f2.executed = []

def f3():
    f3.executed.append("f3")
f3.executed = []

# --- Dummy subclass of AgiDagWorker for testing ---
class DummyAgiDagWorker(AgiDagWorker):
    """
    A dummy subclass of AgiDagWorker for testing purposes.
    We override the exec method to simulate function execution.
    """
    def __init__(self, mode=0, verbose=0, worker_id=0):
        self.mode = mode
        self.verbose = verbose
        self.worker_id = worker_id
        # Override exec to simply call the function and record its name.
        self.execution_order = []
    def exec(self, func):
        # Record that the function was "executed"
        self.execution_order.append(func.__name__)
        # Call the function to simulate side effects.
        return func()

# --- Pytest Fixture for resetting state ---
@pytest.fixture(autouse=True)
def reset_state():
    # Reset the executed lists for the dummy functions before each test.
    f1.executed = []
    f2.executed = []
    f3.executed = []
    # Ensure AgiWorker.t0 is set.
    AgiWorker.t0 = time.time()
    yield
    # No teardown required.

# --- Test functions ---

def test_topological_sort_normal():
    # Create a dependency graph without cycles.
    dependency_graph = {
        f1: [],       # f1 has no dependencies.
        f2: [f1],     # f2 depends on f1.
        f3: [f1, f2]  # f3 depends on f1 and f2.
    }
    worker = DummyAgiDagWorker(verbose=0)
    topo_order = worker.topological_sort(dependency_graph)
    # The first function must be f1; f2 must come before f3.
    assert topo_order[0] == f1
    assert topo_order.index(f2) < topo_order.index(f3)

def test_topological_sort_cycle():
    # Create a cyclic dependency: f1 -> f2 -> f1.
    dependency_graph = {
        f1: [f2],
        f2: [f1]
    }
    worker = DummyAgiDagWorker(verbose=0)
    with pytest.raises(ValueError, match="Circular dependency detected"):
        worker.topological_sort(dependency_graph)

def test_exec_mono_process():
    # Build a workers_tree for mono-process execution.
    # For worker 0, simulate two tasks.
    workers_tree = [
        [
            (f1, []),
            (f2, [f1])
        ]
    ]
    workers_tree_info = [
        [
            ("p1", 0),
            ("p2", 0)
        ]
    ]
    worker = DummyAgiDagWorker(mode=0, verbose=0, worker_id=0)
    worker.exec_mono_process(workers_tree, workers_tree_info)
    # Expected topological order: f1 then f2.
    assert worker.execution_order == ["f1", "f2"]

def test_exec_multi_process():
    # Build a workers_tree for multi-process (or threaded) execution.
    workers_tree = [
        [
            (f1, []),
            (f2, [f1])
        ]
    ]
    workers_tree_info = [
        [
            ("p1", 0),
            ("p2", 0)
        ]
    ]
    worker = DummyAgiDagWorker(mode=1, verbose=0, worker_id=0)
    worker.exec_multi_process(workers_tree, workers_tree_info)
    # Even with threading, the implementation waits for dependencies.
    assert worker.execution_order == ["f1", "f2"]

def test_works_method():
    # Test that works() returns a positive execution time.
    # Build a simple workers_tree that does nothing.
    workers_tree = [
        []  # Worker 0 tasks: empty list simulating no tasks.
    ]
    workers_tree_info = [
        []  # Worker 0 info: empty.
    ]
    worker = DummyAgiDagWorker(mode=0, verbose=0, worker_id=0)
    exec_time = worker.works(workers_tree, workers_tree_info)
    assert isinstance(exec_time, float)
    assert exec_time >= 0