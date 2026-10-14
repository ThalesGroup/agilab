import time
import pytest

# Import the real package
from agi_node.dag_worker import DagWorker
import agi_node.dag_worker.dag_worker as dag_module
from agi_node.agi_dispatcher import BaseWorker
from agi_node.agi_dispatcher.base_worker_execution_support import _collapse_plan_for_single_worker


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


class InvokeDagWorker(DagWorker):
    def zero(self):
        return "zero"

    def one(self, payload):
        return payload

    def pair(self, left, right):
        return left, right

    def kw(self, *, args=None, prev_result=None):
        return args, prev_result

    def kw_alt(self, *, args=None, previous_result=None):
        return args, previous_result

    def positional_only(self, args, prev_result, /):
        return args, prev_result

    def mixed_positional_and_keyword(self, args, /, *, prev_result):
        return args, prev_result

    def positional_args_only(self, args, /):
        return args

    def fallback_pair(self, left, right):
        return left, right

    def boom(self, args, prev_result):
        raise RuntimeError("boom")

    def missing_artifact(self, payload):
        raise FileNotFoundError(f"missing {payload}")


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
        called.append("mono")
        return 0.0

    def fake_multi(self, workers_tree, workers_tree_info):
        called.append("multi")
        return 0.0

    # New design always dispatches to multi; just patch that
    monkeypatch.setattr(DagWorker, "_exec_multi_process", fake_multi, raising=True)

    w = _cfg(DagWorker(), 0, 0, 0)
    w.works([[]], [[]])  # non-empty triggers dispatch
    assert called == ["multi"]


def test_works_dispatches_to_multi_when_mode_flag_set(monkeypatch):
    called = []

    def fake_mono(self, workers_tree, workers_tree_info):
        called.append("mono")
        return 0.0

    def fake_multi(self, workers_tree, workers_tree_info):
        called.append("multi")
        return 0.0

    monkeypatch.setattr(DagWorker, "_exec_multi_process", fake_multi, raising=True)

    # Mode bit 0b100 (4) triggers multi-process path in works()
    w = _cfg(DagWorker(), 4, 0, 0)
    w.works([[]], [[]])  # non-empty triggers dispatch
    assert called == ["multi"]


def test_get_work_delegates_to_invoke():
    w = _cfg(InvokeDagWorker(), 0, 0, 0)
    assert w.get_work("pair", "l", "r") == ("l", "r")


def test_invoke_supports_zero_arity_method():
    w = _cfg(InvokeDagWorker(), 0, 0, 0)
    assert w._invoke("zero", args=("unused",), prev_result={"p": 1}) == "zero"


def test_invoke_one_parameter_prefers_args_then_prev_result():
    w = _cfg(InvokeDagWorker(), 0, 0, 0)
    assert w._invoke("one", args="arg-value", prev_result="prev-value") == "arg-value"
    assert w._invoke("one", args=None, prev_result="prev-value") == "prev-value"


def test_invoke_supports_keyword_args_and_prev_result():
    w = _cfg(InvokeDagWorker(), 0, 0, 0)
    assert w._invoke("kw", args=("a",), prev_result={"dep": 1}) == (("a",), {"dep": 1})


def test_invoke_supports_previous_result_alias():
    w = _cfg(InvokeDagWorker(), 0, 0, 0)
    assert w._invoke("kw_alt", args=1, prev_result=2) == (1, 2)


@pytest.mark.parametrize("method", ["positional_only", "mixed_positional_and_keyword"])
def test_invoke_binds_positional_only_parameters_before_the_method_call(method):
    worker = _cfg(InvokeDagWorker(), 0, 0, 0)

    assert worker._invoke(method, args=("payload",), prev_result={"source": 1}) == (
        ("payload",),
        {"source": 1},
    )


def test_invoke_supports_a_single_positional_only_args_parameter():
    worker = _cfg(InvokeDagWorker(), 0, 0, 0)

    assert (
        worker._invoke("positional_args_only", args="payload", prev_result={})
        == "payload"
    )


def test_invoke_exception_falls_back_to_positional_call(monkeypatch):
    def _raise_signature(_):
        raise ValueError("signature unavailable")

    monkeypatch.setattr(dag_module.inspect, "signature", _raise_signature)
    w = _cfg(InvokeDagWorker(), 0, 0, 0)
    assert w._invoke("fallback_pair", args="x", prev_result="y") == ("x", "y")


def test_invoke_propagates_method_exceptions_without_positional_retry():
    w = _cfg(InvokeDagWorker(), 0, 0, 0)
    with pytest.raises(FileNotFoundError, match="missing dataset"):
        w._invoke("missing_artifact", args="dataset", prev_result={"dep": 1})


def test_exec_mono_process_delegates_to_multi(monkeypatch):
    def fake_multi(self, workers_tree, workers_tree_info):
        return 123.0

    monkeypatch.setattr(DagWorker, "_exec_multi_process", fake_multi, raising=True)
    w = _cfg(DagWorker(), 0, 0, 0)
    assert w._exec_mono_process([[]], [[]]) == 123.0


def test_exec_multi_process_future_exception_is_logged_and_raised(caplog):
    # Stage failures must be logged per partition and then propagated so the
    # manager does not report a silent success.
    w = _cfg(InvokeDagWorker(), 0, 0, 0)
    workers_tree = [[(make_fn("boom"), [])]]
    workers_tree_info = [[("P0", 1)]]

    with caplog.at_level("ERROR"):
        with pytest.raises(RuntimeError, match="boom"):
            w._exec_multi_process(workers_tree, workers_tree_info)

    assert any("generated an exception" in record.message for record in caplog.records)


@pytest.mark.parametrize("error_type", [TypeError, ValueError])
def test_stage_body_error_is_propagated_without_repeating_side_effect(error_type):
    class FailingWorker(DagWorker):
        def __init__(self):
            self.worker_id = 0
            self.calls = []

        def fail(self, args, prev_result):
            self.calls.append(args)
            raise error_type("stage body failed")

    worker = FailingWorker()
    tree, metadata = branch("P0", [("fail", [], ("side effect",))])

    with pytest.raises(error_type, match="stage body failed"):
        worker._exec_multi_process([tree], [metadata])

    assert worker.calls == [("side effect",)]


@pytest.mark.parametrize("error_type", [TypeError, ValueError])
def test_positional_only_stage_body_error_is_not_retried(error_type):
    class FailingWorker(DagWorker):
        def __init__(self):
            self.worker_id = 0
            self.calls = []

        def fail(self, args, prev_result, /):
            self.calls.append(args)
            raise error_type("positional stage body failed")

    worker = FailingWorker()
    tree, metadata = branch("P0", [("fail", [], ("side effect",))])

    with pytest.raises(error_type, match="positional stage body failed"):
        worker._exec_multi_process([tree], [metadata])

    assert worker.calls == [("side effect",)]


def test_collapsed_partitions_preserve_repeated_method_invocations():
    class PartitionWorker(DagWorker):
        def __init__(self):
            self.worker_id = 0
            self.calls = []

        def transform(self, args):
            self.calls.append(args)
            return args

    trees, metadata = zip(
        branch("P0", [("transform", [], ("A",))]),
        branch("P1", [("transform", [], ("B",))]),
    )
    plan, info = _collapse_plan_for_single_worker(list(trees), list(metadata))
    worker = PartitionWorker()

    worker.works(plan, info)

    assert sorted(worker.calls) == [("A",), ("B",)]


def test_collapsed_repeated_dags_keep_dependencies_in_their_original_tree():
    class PartitionWorker(DagWorker):
        def __init__(self):
            self.worker_id = 0
            self.results = []

        def produce(self, args):
            return args

        def consume(self, args, prev_result):
            self.results.append((args, prev_result["produce"]))

    trees, metadata = zip(
        branch("P0", [("produce", [], ("A",)), ("consume", ["produce"], ("A",))]),
        branch(
            "P1", [("produce", [], ("B",)), ("consume", [make_fn("produce")], ("B",))]
        ),
    )
    # Metadata labels describe individual tasks; they do not identify a tree.
    metadata = [
        [
            (f"{partition}-{index}", weight)
            for index, (partition, weight) in enumerate(info)
        ]
        for info in metadata
    ]
    plan, info = _collapse_plan_for_single_worker(list(trees), metadata)
    worker = PartitionWorker()

    worker.works(plan, info)

    assert sorted(worker.results) == [(("A",), ("A",)), (("B",), ("B",))]


def test_collapsed_unique_dependency_can_cross_original_trees():
    trees, metadata = zip(
        branch("P0", [("source", [])]),
        branch("P1", [("consumer", ["source"])]),
    )
    plan, info = _collapse_plan_for_single_worker(list(trees), list(metadata))
    worker = _cfg(DummyDagWorker(), 0, 0, 0)

    worker.works(plan, info)

    assert worker.execution_order == ["source", "consumer"]


def test_ambiguous_repeated_dependency_is_rejected_before_any_stage_runs():
    tree, info = branch(
        "P0",
        [
            ("transform", [], ("A",)),
            ("transform", [], ("B",)),
            ("consume", ["transform"]),
        ],
    )
    worker = _cfg(DummyDagWorker(), 0, 0, 0)

    with pytest.raises(ValueError, match="Ambiguous DAG dependency on repeated method"):
        worker.works([tree], [info])

    assert worker.execution_order == []


def test_ambiguous_dependency_across_collapsed_trees_is_rejected():
    trees, metadata = zip(
        branch("P0", [("transform", [], ("A",))]),
        branch("P1", [("transform", [], ("B",))]),
        branch("P2", [("consume", ["transform"])]),
    )
    plan, info = _collapse_plan_for_single_worker(list(trees), list(metadata))
    worker = _cfg(DummyDagWorker(), 0, 0, 0)

    with pytest.raises(ValueError, match="Ambiguous DAG dependency on repeated method"):
        worker.works(plan, info)

    assert worker.execution_order == []
