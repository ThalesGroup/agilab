# BSD 3-Clause License
#
# [License Text Remains Unchanged]
#
# (Include the full BSD 3-Clause License text here)

"""Shared in-worker pool engine for the dataframe worker families.

This module centralises the ``works()`` orchestration that used to be
copy-pasted across :class:`PandasWorker`, :class:`PolarsWorker` and
:class:`FireducksWorker`:

* mode dispatch (pool vs mono) via one named mask,
* one warm executor per ``works()`` call (instead of one per chunk),
* a module-level pool entry point so the worker instance is shipped to each
  pool child exactly once (through the initializer) instead of being pickled
  per task,
* batched submission with per-item error context,
* unified result normalisation, ``worker_id`` labelling and ``work_done``
  cadence (one call per plan chunk).

Worker families plug in via :class:`PoolFrameHooks` (frame type, executor
kind, concat/empty semantics).
"""

from __future__ import annotations

import logging
import math
import multiprocessing
import os
import sys
import time
import traceback
from concurrent.futures import BrokenExecutor, ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from dataclasses import dataclass
from typing import Any, Callable, Sequence

logger = logging.getLogger(__name__)

# In-worker pooling is requested via the pool bit (1). The dask bit (4) is
# also included because it keeps its historical behavior of pooling inside
# each dask worker; changing that semantics is deliberately deferred (the UI
# documents it), so the mask lives here as the single source of truth.
_POOL_MODE_BIT = 0b0001
_DASK_MODE_BIT = 0b0100
IN_WORKER_POOL_MASK = _POOL_MODE_BIT | _DASK_MODE_BIT

#: Environment variable capping the in-worker pool width (processes/threads).
POOL_MAX_WORKERS_ENV = "AGILAB_POOL_MAX_WORKERS"

#: Optional per-app override read from ``worker.args`` when present.
POOL_MAX_WORKERS_ARG = "pool_max_workers"

#: Per-work-item time budget in seconds (float). Opt-in: unset means no
#: timeout, preserving historical behavior. Read from ``worker.args`` first,
#: then the environment.
POOL_ITEM_TIMEOUT_ENV = "AGILAB_POOL_ITEM_TIMEOUT"
POOL_ITEM_TIMEOUT_ARG = "pool_item_timeout"

#: Executor backend override: ``process``/``thread`` force a backend,
#: ``auto`` (default) keeps the family default except on free-threaded
#: interpreters (a free-threaded build with the GIL disabled), where
#: process-pool families switch to a thread pool — same parallelism without
#: spawn/pickling costs.
POOL_EXECUTOR_ENV = "AGILAB_POOL_EXECUTOR"

#: Process-pool start method. ``spawn`` (default) re-imports and pickles per
#: child — deterministic across platforms. ``forkserver`` (POSIX only) warms a
#: single clean server process once and forks children from it: no per-child
#: interpreter cold start and none of the fork+threads deadlock hazards of raw
#: ``fork`` (which is deliberately not offered). Ignored by thread pools.
POOL_START_METHOD_ENV = "AGILAB_POOL_START_METHOD"
_DEFAULT_START_METHOD = "spawn"
SUPPORTED_START_METHODS = ("spawn", "forkserver")


def available_start_methods() -> tuple[str, ...]:
    """Supported start methods that this platform actually provides.

    ``forkserver`` is POSIX-only, so on Windows this collapses to ``spawn``.
    """
    provided = set(multiprocessing.get_all_start_methods())
    return tuple(method for method in SUPPORTED_START_METHODS if method in provided)


def resolve_pool_start_method() -> str:
    """Resolve the process-pool start method from the environment.

    ``AGILAB_POOL_START_METHOD=spawn|forkserver`` selects the method; unset (or
    any unsupported/unavailable value) falls back to ``spawn``. ``forkserver``
    silently degrades to ``spawn`` on platforms that do not provide it so a
    cross-platform run never fails on this knob.
    """
    choice = os.environ.get(POOL_START_METHOD_ENV, _DEFAULT_START_METHOD).strip().lower()
    if not choice:
        return _DEFAULT_START_METHOD
    if choice not in SUPPORTED_START_METHODS:
        logger.warning(
            "Ignoring invalid %s value %r (expected spawn or forkserver)",
            POOL_START_METHOD_ENV,
            choice,
        )
        return _DEFAULT_START_METHOD
    if choice not in available_start_methods():
        logger.warning(
            "%s=%s is not available on this platform; falling back to spawn",
            POOL_START_METHOD_ENV,
            choice,
        )
        return _DEFAULT_START_METHOD
    return choice


def resolve_process_pool_context(preload: Sequence[str] = ()) -> Any:
    """Return the multiprocessing context for the process pool.

    ``preload`` is applied only for ``forkserver`` (it pre-imports the named
    modules into the warm server so forked children skip that import cost); it
    is best-effort — a preload failure must never abort the run.
    """
    method = resolve_pool_start_method()
    context = multiprocessing.get_context(method)
    if method == "forkserver" and preload:
        try:
            context.set_forkserver_preload(list(preload))
        # Defensive: preload is a pure optimization; never let it break a run.
        except Exception:
            logger.warning("Could not set forkserver preload %r", tuple(preload))
    return context

#: Grace added on top of the derived chunk deadline so a timeout reflects a
#: genuinely stuck item rather than scheduling jitter.
_POOL_TIMEOUT_GRACE_SECONDS = 5.0

_MAP_CHUNKSIZE_CAP = 32

# Worker code boundary: pool children execute app work_pool implementations;
# each failure is captured with its work item and re-raised in the parent
# with full context instead of aborting the surviving siblings.
_POOL_ITEM_BOUNDARY_EXCEPTIONS: tuple[type[Exception], ...] = (Exception,)

# Per pool-child worker instance installed by :func:`_pool_child_init`.
# One in-worker pool runs at a time per process, so a module global is safe.
_POOL_RUNTIME_WORKER: Any = None


@dataclass(frozen=True)
class PoolFrameHooks:
    """Per worker-family hooks used by the shared pool engine."""

    family: str
    executor_kind: str  # "process" or "thread" (logging/diagnostics only)
    executor_factory: Callable[..., Any]
    is_frame: Callable[[Any], bool]
    is_empty: Callable[[Any], bool]
    concat_labeled: Callable[[Sequence[Any], Sequence[str]], Any]
    empty_frame: Callable[[], Any]


def pool_mode_requested(mode: Any) -> bool:
    """Return True when the run mode requests in-worker pooling."""
    try:
        return bool(mode & IN_WORKER_POOL_MASK)
    except TypeError:
        # Defensive: tests and ad-hoc callers may leave ``_mode`` unset (None);
        # treat that as mono execution rather than crashing on the bit test.
        return False


def resolve_pool_width(chunk_lengths: Sequence[int], args: Any = None) -> int:
    """Resolve the pool width once per ``works()`` call.

    The width is bounded by the largest chunk (extra workers would idle), the
    machine's CPU count (guarding ``os.cpu_count()`` returning ``None``), and
    an optional cap from ``args[pool_max_workers]`` or
    ``AGILAB_POOL_MAX_WORKERS``.
    """
    largest_chunk = max((int(length) for length in chunk_lengths), default=0)
    cpu_count = os.cpu_count() or 1
    width = max(min(largest_chunk, cpu_count), 1)
    cap = _resolve_pool_cap(args)
    if cap is not None:
        width = max(min(width, cap), 1)
    return width


def _resolve_pool_cap(args: Any) -> int | None:
    """Read the optional pool-width cap from args, then the environment."""
    candidates = []
    getter = getattr(args, "get", None)
    if callable(getter):
        candidates.append(getter(POOL_MAX_WORKERS_ARG))
    candidates.append(os.environ.get(POOL_MAX_WORKERS_ENV))
    for raw in candidates:
        if raw is None or raw == "":
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError):
            logger.warning(
                "Ignoring invalid pool max workers value %r (expected an integer)",
                raw,
            )
            continue
        if value > 0:
            return value
        logger.warning("Ignoring non-positive pool max workers value %r", raw)
    return None


def resolve_pool_item_timeout(args: Any = None) -> float | None:
    """Read the optional per-item time budget from args, then the environment."""
    candidates = []
    getter = getattr(args, "get", None)
    if callable(getter):
        candidates.append(getter(POOL_ITEM_TIMEOUT_ARG))
    candidates.append(os.environ.get(POOL_ITEM_TIMEOUT_ENV))
    for raw in candidates:
        if raw is None or raw == "":
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            logger.warning(
                "Ignoring invalid pool item timeout value %r (expected seconds)",
                raw,
            )
            continue
        if value > 0:
            return value
        logger.warning("Ignoring non-positive pool item timeout value %r", raw)
    return None


def _chunk_deadline_seconds(item_timeout: float, item_count: int, width: int) -> float:
    """Whole-chunk deadline: serial item budget per pool slot plus grace."""
    waves = math.ceil(item_count / max(width, 1))
    return item_timeout * max(waves, 1) + _POOL_TIMEOUT_GRACE_SECONDS


def _free_threading_active() -> bool:
    """Return True when this interpreter runs with the GIL disabled."""
    checker = getattr(sys, "_is_gil_enabled", None)
    if callable(checker):
        try:
            return not bool(checker())
        # Defensive: a probe failure must never change executor selection.
        except Exception:
            return False
    return False


def resolve_executor(hooks: PoolFrameHooks) -> tuple[Callable[..., Any], str]:
    """Resolve the executor backend for this run.

    ``AGILAB_POOL_EXECUTOR=process|thread`` forces a backend; ``auto`` (or
    unset) keeps the family default, except that process-pool families run a
    thread pool on free-threaded interpreters where threads deliver the same
    parallelism without spawn and pickling costs.
    """
    choice = os.environ.get(POOL_EXECUTOR_ENV, "auto").strip().lower() or "auto"
    if choice not in ("auto", "process", "thread"):
        logger.warning(
            "Ignoring invalid %s value %r (expected auto, process or thread)",
            POOL_EXECUTOR_ENV,
            choice,
        )
        choice = "auto"
    if choice == "thread" and hooks.executor_kind != "thread":
        return ThreadPoolExecutor, "thread (forced by env)"
    if choice in ("process", "thread"):
        # "process" pins process families to their default (disables the
        # free-threading auto-switch); it cannot convert a thread family,
        # whose workers are not required to be picklable.
        return hooks.executor_factory, hooks.executor_kind
    if hooks.executor_kind == "process" and _free_threading_active():
        return ThreadPoolExecutor, "thread (free-threaded interpreter)"
    return hooks.executor_factory, hooks.executor_kind


def map_chunksize(item_count: int, width: int) -> int:
    """Batch size for submitting ``item_count`` items to ``width`` workers."""
    return max(1, min(_MAP_CHUNKSIZE_CAP, item_count // max(width, 1)))


def select_worker_chunks(worker: Any, workers_plan: Any) -> Any:
    """Return this worker's chunk list from the plan with a clear error.

    Guards the historical bare ``workers_plan[worker_id]`` IndexError when a
    list plan has fewer partitions than the worker id. Non-list indexable
    plans (e.g. dict-shaped test payloads) are indexed as-is.
    """
    worker_id = worker._worker_id
    if isinstance(workers_plan, list) and not (
        isinstance(worker_id, int) and 0 <= worker_id < len(workers_plan)
    ):
        raise RuntimeError(
            f"workers_plan has {len(workers_plan)} partition(s) but this worker's "
            f"worker_id is {worker_id!r}; the dispatcher must provide one plan "
            "partition per worker."
        )
    return workers_plan[worker_id]


def run_works(worker: Any, workers_plan: Any, workers_plan_metadata: Any) -> float:
    """Template ``works()`` shared by the dataframe worker families.

    Dispatches on the pool mask, resets the per-run ``work_done`` chunk
    counter (long-lived service workers reuse the same instance across runs),
    calls ``stop()`` and returns the execution time of THIS call in seconds
    (measured with ``time.perf_counter``, not the class-level registration
    timestamp).
    """
    start = time.perf_counter()
    # Reset the work_done chunk suffix counter for every run so service-mode
    # instance reuse does not leak suffixes across works() invocations.
    worker._work_done_chunk = 0
    if workers_plan:
        if pool_mode_requested(worker._mode):
            worker._exec_multi_process(workers_plan, workers_plan_metadata)
        else:
            worker._exec_mono_process(workers_plan, workers_plan_metadata)

    worker.stop()
    return time.perf_counter() - start


def _pool_child_init(worker: Any, pool_vars: Any) -> None:
    """Initializer run once per pool child (process or thread).

    For process pools this is where the worker instance lands in the child
    (pickled once per child via ``initargs`` instead of once per task), and
    where child-side logging is configured so initializer/work_pool failures
    are at least visible on stderr (the parent's StringIO log capture cannot
    see child processes).
    """
    global _POOL_RUNTIME_WORKER
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(
            stream=sys.stderr,
            level=logging.INFO,
            format="[pool-child pid=%(process)d] %(levelname)s %(name)s: %(message)s",
        )
    _POOL_RUNTIME_WORKER = worker
    worker.pool_init(pool_vars)


def _pool_run_batch(batch: Sequence[tuple[int, Any]]) -> list[tuple[int, Any, str | None]]:
    """Module-level pool entry: run a batch of (index, item) work items.

    Returns ``(index, result, error)`` triples; errors are stringified so they
    cross the process boundary even when the original exception does not
    pickle.
    """
    worker = _POOL_RUNTIME_WORKER
    out: list[tuple[int, Any, str | None]] = []
    for idx, item in batch:
        try:
            out.append((idx, worker.work_pool(item), None))
        # Worker code boundary: keep processing sibling items and report the
        # failure with its work item instead of losing completed results.
        except _POOL_ITEM_BOUNDARY_EXCEPTIONS:
            out.append((idx, None, traceback.format_exc()))
    return out


def exec_multi_process(
    worker: Any,
    workers_plan: Any,
    workers_plan_metadata: Any,
    hooks: PoolFrameHooks,
) -> None:
    """Pool execution path shared by the dataframe worker families.

    One warm executor serves every chunk of this ``works()`` call; futures are
    grouped per chunk so the per-chunk ``work_done`` cadence is preserved.
    """
    chunks = select_worker_chunks(worker, workers_plan)
    chunk_lengths = [len(chunk) for chunk in chunks]
    args = getattr(worker, "args", None)
    width = resolve_pool_width(chunk_lengths, args)
    item_timeout = resolve_pool_item_timeout(args)
    executor_factory, executor_kind = resolve_executor(hooks)
    executor_detail = (
        f"process ({resolve_pool_start_method()})"
        if executor_kind == "process"
        else executor_kind
    )
    logging.info(
        f"{hooks.family}.works - {executor_detail} pool width {width}"
        f" - worker #{worker._worker_id}"
        f" - work_pool x {sum(chunk_lengths)} across {len(chunk_lengths)} chunk(s)"
        + (f" - item timeout {item_timeout}s" if item_timeout else "")
    )

    worker.work_init()
    with executor_factory(
        max_workers=width,
        initializer=_pool_child_init,
        initargs=(worker, worker.pool_vars),
    ) as executor:
        for work_id, work in enumerate(chunks):
            results = _run_chunk(
                executor, worker, hooks, work_id, list(work), width, item_timeout
            )
            _finish_chunk(worker, hooks, results)


def _batches(indexed: list[tuple[int, Any]], chunksize: int) -> list[list[tuple[int, Any]]]:
    """Mirror the submission batching of :func:`_run_chunk` for reporting."""
    return [indexed[offset : offset + chunksize] for offset in range(0, len(indexed), chunksize)]


def _abandon_stuck_pool(executor: Any) -> None:
    """Unblock a pool whose tasks blew their deadline.

    Cancels queued work and, for process pools, terminates the children
    (best-effort via the executor's process table — without it the enclosing
    ``with`` block would hang in ``shutdown(wait=True)`` behind the stuck
    task). Thread pools cannot be force-stopped; their stragglers are left
    running and the caller's error message says so.
    """
    try:
        executor.shutdown(wait=False, cancel_futures=True)
    # Defensive: a stuck pool must not be able to mask the timeout error.
    except Exception:
        pass
    processes = getattr(executor, "_processes", None)
    if isinstance(processes, dict):
        for process in list(processes.values()):
            terminate = getattr(process, "terminate", None)
            if callable(terminate):
                try:
                    terminate()
                # Defensive: child reaping is best-effort during abandonment.
                except Exception:
                    pass


def _run_chunk(
    executor: Any,
    worker: Any,
    hooks: PoolFrameHooks,
    work_id: int,
    work: list[Any],
    width: int,
    item_timeout: float | None = None,
) -> list[tuple[int, Any]]:
    """Submit one chunk to the warm pool and collect (index, result) pairs."""
    if not work:
        return []

    chunksize = map_chunksize(len(work), width)
    indexed = list(enumerate(work))
    futures = [
        executor.submit(_pool_run_batch, indexed[offset : offset + chunksize])
        for offset in range(0, len(indexed), chunksize)
    ]
    deadline = (
        _chunk_deadline_seconds(item_timeout, len(work), width)
        if item_timeout is not None
        else None
    )

    results: list[tuple[int, Any]] = []
    failures: list[tuple[Any, str]] = []
    try:
        for future in as_completed(futures, timeout=deadline):
            for idx, result, error in future.result():
                if error is None:
                    results.append((idx, result))
                else:
                    failures.append((work[idx], error))
    except FuturesTimeoutError as exc:
        _abandon_stuck_pool(executor)
        pending = [item for f, batch in zip(futures, _batches(indexed, chunksize)) if not f.done() for _, item in batch]
        preview = ", ".join(repr(item) for item in pending[:3])
        if len(pending) > 3:
            preview += ", ..."
        raise RuntimeError(
            f"{hooks.family}.work_pool exceeded the {item_timeout}s per-item time "
            f"budget on chunk #{work_id} ({deadline:.1f}s chunk deadline); "
            f"{len(pending)} item(s) still pending: {preview}. Process-pool "
            "children are terminated; thread-pool stragglers cannot be stopped "
            "and may keep running in the background."
        ) from exc
    except BrokenExecutor as exc:
        raise RuntimeError(
            f"{hooks.family} {hooks.executor_kind} pool broke while running chunk "
            f"#{work_id} (items: {work[:3]!r}{'...' if len(work) > 3 else ''}). "
            "A pool child died or failed to start; likely causes: out-of-memory "
            "kill or segfault in worker code, an exception raised by pool_init "
            "in the child, or unpicklable worker state (self/pool_vars must "
            "pickle for process pools). Child-side tracebacks are written to "
            "the child's stderr."
        ) from exc

    if failures:
        for item, error in failures:
            logging.error(
                f"{hooks.family}.work_pool failed for work item {item!r} "
                f"(chunk #{work_id}):\n{error}"
            )
        failed_items = [item for item, _ in failures]
        preview = ", ".join(repr(item) for item in failed_items[:3])
        if len(failed_items) > 3:
            preview += ", ..."
        raise RuntimeError(
            f"{hooks.family}.work_pool failed for {len(failed_items)} of "
            f"{len(work)} work item(s) in chunk #{work_id}: {preview} "
            "(every failure is logged above with its traceback)."
        )

    results.sort(key=lambda pair: pair[0])
    return results


def exec_mono_process(
    worker: Any,
    workers_plan: Any,
    workers_plan_metadata: Any,
    hooks: PoolFrameHooks,
) -> None:
    """Sequential execution path sharing normalisation/labelling with the pool path."""
    chunks = select_worker_chunks(worker, workers_plan)
    worker.work_init()
    for work_id, work in enumerate(chunks):
        logging.info(
            f"{hooks.family}.works - monoprocess work #{work_id} - work_pool x {len(work)}"
        )
        # Preserve the historical gate: a falsy plan object still drives the
        # chunk loop but yields no work items (pinned by worker tests).
        items = list(work) if workers_plan else []
        results = [(idx, worker.work_pool(item)) for idx, item in enumerate(items)]
        _finish_chunk(worker, hooks, results)


def _finish_chunk(
    worker: Any,
    hooks: PoolFrameHooks,
    results: Sequence[tuple[int, Any]],
) -> None:
    """Normalise, label and persist one chunk's results.

    ``None`` and non-frame results are treated as empty (consistently in mono
    and pool modes). Surviving frames are labelled ``str((worker_id, idx))``
    where ``idx`` is the ORIGINAL work-item index within the chunk, identical
    in both modes, so provenance survives empty-result filtering.
    """
    frames: list[Any] = []
    labels: list[str] = []
    for idx, result in results:
        if result is None:
            continue
        if not hooks.is_frame(result):
            logging.warning(
                f"{hooks.family}.work_pool returned {type(result).__name__!s} "
                f"for work item index {idx}; treating it as an empty result."
            )
            continue
        if hooks.is_empty(result):
            continue
        frames.append(result)
        labels.append(str((worker._worker_id, idx)))

    if frames:
        df = hooks.concat_labeled(frames, labels)
    else:
        df = hooks.empty_frame()
    worker.work_done(df)
