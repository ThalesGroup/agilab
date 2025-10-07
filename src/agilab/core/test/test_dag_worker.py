import time
import pytest

# Import the real package
from agi_node.dag_worker import DagWorker
from agi_node.agi_dispatcher import BaseWorker


# Helper to configure DagWorker attributes since its __init__ takes no args
def _cfg(w, mode, verbose, worker_id):
    setattr(w, "mode", mode)
    setattr(w, "verbose", verbose)
    setattr(w, "worker_id", worker_id)
    return w


# Ensure BaseWorker.t0 is set when tests call works() directly (not via run())
@pytest.fixture(autouse=True)
def _init_baseworker_t0():
    BaseWorker._t0 = time.time()
    yield
    BaseWorker._t0 = None


# --- Helpers to build DAG payloads expected by DagWorker.exec_* ---

def make_fn(name, args=(), kwargs=None):
    if kwargs is None:
        kwargs = {}
    return {"functions name": name, "args": args, "kwargs": kwargs}


def branch(pname, entries):
    """
    entries: list of tuples (fn_name, deps[, args])
    returns (tree, info) where:
      tree = [(fn_dict, deps), ...]
      info = [(partition_name, weight), ...]  # weight not used -> 1
    """
    tree = []
    info = []
    for e in entries:
        if len(e) == 2:
            fn, deps = e
            args = ()
        else:
            fn, deps, args = e
        tree.append((make_fn(fn, args=args), deps))
        info.append((pname, 1))
    return tree, info


# --- Dummy worker that only records the order DagWorker schedules functions ---

class DummyDagWorker(DagWorker):
    def __init__(self):
        # DagWorker has no-arg __init__; be tolerant if absent
        try:
            super().__init__()
        except TypeError:
            pass
        self.execution_order = []
        self.recorded_args = {}

    # New: make tests robust to DagWorker calling _invoke instead of get_work
    # This simply forwards to the existing get_work so we keep instrumentation.
    def _invoke(self, fn_name, args, prev_result):
        return self.get_work(fn_name, args, prev_result)

    # Match DagWorker usage: get_work(fn, fargs[fn], pipeline_result)
    def get_work(self, fn_name, args, pipeline_result):
        self.execution_order.append(fn_name)
        # record positional args as a tuple
        self.recorded_args[fn_name] = tuple(args) if isinstance(args, (list, tuple)) else (args,)
        # simulate a bit of work; return a value to allow dependency passing
        time.sleep(0.001)
        return {"ok": True, "deps": dict(pipeline_result)}


# -------------------- Core ordering tests --------------------

def test_linear_dependencies_topological_order():
    # One branch; worker_id=0 should pick it (round-robin on index)
    # f1 -> f2
    tree, info = branch("P0", [("f1", []), ("f2", ["f1"])])
    workers_tree = [tree]
    workers_tree_info = [info]

    w = _cfg(DummyDagWorker(), 0, 0, 0)
    t0 = time.time()
    w.works(workers_tree, workers_tree_info)
    exec_time = time.time() - t0
    assert isinstance(exec_time, float) and exec_time >= 0

    assert isinstance(exec_time, float) and exec_time >= 0
    assert w.execution_order == ["f1", "f2"]


def test_fan_out_and_fan_in_dependencies():
    # DAG:
    #   a -> b
    #   a -> c
    #   b -> d
    #   c -> d
    entries = [
        ("a", []),
        ("b", ["a"]),
        ("c", ["a"]),
        ("d", ["b", "c"]),
    ]
    tree, info = branch("P1", entries)
    workers_tree = [tree]
    workers_tree_info = [info]

    w = _cfg(DummyDagWorker(), 0, 0, 0)
    w.works(workers_tree, workers_tree_info)

    order = w.execution_order
    assert order.index("a") < order.index("b")
    assert order.index("a") < order.index("c")
    assert order.index("b") < order.index("d")
    assert order.index("c") < order.index("d")


def test_no_tasks_returns_quickly():
    workers_tree = []         # no branches at all
    workers_tree_info = []
    w = _cfg(DummyDagWorker(), 0, 0, 0)
    t0 = time.time()
    w.works(workers_tree, workers_tree_info)
    t = time.time() - t0
    assert isinstance(t, float) and t >= 0


# -------------------- Args forwarding & cycle handling --------------------

def test_args_are_forwarded_to_get_work():
    # Ensure the positional args collected in fargs[...] are passed into get_work
    tree, info = branch("P2", [("f", [], (1, 2, 3))])
    workers_tree = [tree]
    workers_tree_info = [info]
    w = _cfg(DummyDagWorker(), 0, 0, 0)
    _ = w.works(workers_tree, workers_tree_info)
    assert w.recorded_args.get("f") == (1, 2, 3)


def test_topological_sort_cycle_raises():
    # Directly test topological_sort for a simple cycle a->b->a
    g = {"a": ["b"], "b": ["a"]}
    with pytest.raises(ValueError):
        _cfg(DagWorker(), 0, 0, 0)._topological_sort(g)


# -------------------- Round-robin branch assignment --------------------

def test_round_robin_assigns_only_branch_with_matching_index():
    """
    With N branches and worker_id=k, current implementation selects the branch
    at index k (idx % num_workers == worker_id with num_workers=len(workers_tree)).
    """
    b0_tree, b0_info = branch("B0", [("a0", []), ("b0", ["a0"])])
    b1_tree, b1_info = branch("B1", [("a1", []), ("b1", ["a1"])])
    b2_tree, b2_info = branch("B2", [("a2", []), ("b2", ["a2"])])

    workers_tree = [b0_tree, b1_tree, b2_tree]
    workers_tree_info = [b0_info, b1_info, b2_info]

    # Choose worker_id=1 -> should execute only branch index 1
    w = _cfg(DummyDagWorker(), 0, 0, 1)
    w.works(workers_tree, workers_tree_info)

    assert w.execution_order == ["a1", "b1"]
    assert not any(fn in w.execution_order for fn in ["a0", "b0", "a2", "b2"])


# -------------------- Dispatch: mono vs. multi --------------------

def test_works_dispatches_to_mono_when_mode_0(monkeypatch):
    called = []

    def fake_mono(self, workers_tree, workers_tree_info):
        called.append("mono"); return 0.0

    def fake_multi(self, workers_tree, workers_tree_info):
        called.append("multi"); return 0.0

    # New design always dispatches to multi; just patch that
    monkeypatch.setattr(DagWorker, "_exec_multi_process", fake_multi, raising=True)

    w = _cfg(DagWorker(), 0, 0, 0)
    w.works([[]], [[]])  # non-empty triggers dispatch
    assert called == ["multi"]


def test_works_dispatches_to_multi_when_mode_flag_set(monkeypatch):
    called = []

    def fake_mono(self, workers_tree, workers_tree_info):
        called.append("mono"); return 0.0

    def fake_multi(self, workers_tree, workers_tree_info):
        called.append("multi"); return 0.0

    monkeypatch.setattr(DagWorker, "_exec_multi_process", fake_multi, raising=True)

    # Mode bit 0b100 (4) triggers multi-process path in works()
    w = _cfg(DagWorker(), 4, 0, 0)
    w.works([[]], [[]])  # non-empty triggers dispatch
    assert called == ["multi"]

# New: make tests robust to DagWorker calling _invoke instead of get_work
def _invoke(self, fn_name, args, prev_result):
    return self.get_work(fn_name, args, prev_result)
