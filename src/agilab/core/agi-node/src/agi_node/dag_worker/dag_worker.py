# BSD 3-Clause License
#
# Copyright (c) 2025, Jean-Pierre Morard, THALES SIX GTS France SAS
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
# 3. Neither the name of Jean-Pierre Morard nor the names of its contributors, or THALES SIX GTS France SAS, may be used to endorse or promote products derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.


######################################################
# Agi Framework call back functions
######################################################

# dag_worker.py
from __future__ import annotations

import inspect
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Iterable, List, Mapping

# Import BaseWorker from agi_dispatcher.py (as you requested)
from agi_node.agi_dispatcher import BaseWorker


class DagWorker(BaseWorker):
    """
    Minimal-change DAG worker:
      - Keeps your existing structure
      - Adds a tiny signature-aware _invoke() so custom methods can vary in signature
      - Uses _invoke() at the single call site in ._exec_multi_process()
    """

    # inside class DagWorker(BaseWorker):

    def get_work(self, fn_name, args, prev_result):
        """Back-compat: delegate to the signature-aware invoker."""
        return self._invoke(fn_name, args, prev_result)

    # -----------------------------
    # Generic: signature-aware invocation
    # -----------------------------
    def _invoke(self, fn_name: str, args: Any, prev_result: Any) -> Any:
        """
        Call a worker method with whatever parameters it actually accepts.

        Supported shapes (bound methods; 'self' already bound):
            def algo()
            def algo(args)
            def algo(prev_result)
            def algo(args, prev_result)
            def algo(*, args=None, prev_result=None)
            def algo(*, args=None, previous_result=None)
        """
        method = getattr(self, fn_name)
        try:
            sig = inspect.signature(method)
            params = [
                p for p in sig.parameters.values()
                if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
            ]

            accepts_args = any(p.name == "args" for p in params)
            accepts_prev = any(p.name == "prev_result" for p in params)
            accepts_prev_alt = any(p.name == "previous_result" for p in params)
            has_kwonly = any(p.kind is p.KEYWORD_ONLY for p in params)

            # Prefer name-aware kwargs if declared (or keyword-only present)
            if has_kwonly or accepts_args or accepts_prev or accepts_prev_alt:
                kw = {}
                if accepts_args:
                    kw["args"] = args
                if accepts_prev:
                    kw["prev_result"] = prev_result
                if accepts_prev_alt:
                    kw["previous_result"] = prev_result
                return method(**kw)

            # Otherwise decide by arity (bound method: 'self' not included)
            arity = len(params)
            if arity == 0:
                return method()
            elif arity == 1:
                # We don't know the param name; prefer args, fallback to prev_result
                return method(args if args is not None else prev_result)
            else:
                # Pass both positionally
                return method(args, prev_result)

        except Exception:
            # Preserve legacy behavior as a final fallback
            logging.exception(f"_invoke: error calling {fn_name}; falling back to (args, prev_result)")
            return method(args, prev_result)

    # -----------------------------
    # Your existing methods (kept minimal)
    # -----------------------------
    def works(self, workers_plan, workers_plan_metadata):
        """
        Your existing entry point; keep as-is, just call multiprocess path for mode 4, etc.
        """
        # If you had mode checks, keep them. Here we directly call the multi-process variant.
        self._exec_multi_process(workers_plan, workers_plan_metadata)

    def _exec_mono_process(self, workers_plan, workers_plan_metadata):
        """Sequential fallback kept for compatibility; reuses the multi-process pipeline."""
        return self._exec_multi_process(workers_plan, workers_plan_metadata)

    @staticmethod
    def _topological_sort(graph):
        """
        Kahn's algorithm.
        `graph` is { node: [dependencies...] }.
        Build edges (dep -> node) and count indegree(node) as #prereqs.
        """
        from collections import deque

        # all nodes = keys + anything appearing only as a dep
        nodes = set(graph.keys())
        for deps in graph.values():
            for d in deps:
                nodes.add(d)

        # dep -> [nodes depending on dep], indegree(node)
        adj = {n: [] for n in nodes}
        indeg = {n: 0 for n in nodes}
        for node, deps in graph.items():
            for dep in deps:
                adj[dep].append(node)
                indeg[node] += 1

        # deterministic order helps tests
        zero = deque(sorted(n for n, d in indeg.items() if d == 0))
        order = []
        while zero:
            u = zero.popleft()
            order.append(u)
            for v in sorted(adj[u]):
                indeg[v] -= 1
                if indeg[v] == 0:
                    zero.append(v)

        if len(order) != len(nodes):
            raise ValueError("Cycle detected in dependency graph")
        return order

    def _exec_multi_process(self, workers_plan, workers_plan_metadata):
        """
        Execute tasks in multiple threads, distributing branches to workers by
        round‑robin, then honoring dependencies per worker.
        """
        import logging
        from concurrent.futures import ThreadPoolExecutor
        import os

        workers_plan = workers_plan or []
        workers_plan_metadata = workers_plan_metadata or []

        num_partitions = max(1, len(workers_plan))
        worker_id = getattr(self, "worker_id", 0) % num_partitions

        # gather tasks for this worker by round‑robin
        assigned = []
        for idx, (tree, info) in enumerate(zip(workers_plan, workers_plan_metadata)):
            if idx % num_partitions != worker_id:
                continue
            for (fn_dict, deps), (pname, weight) in zip(tree, info):
                assigned.append((fn_dict, deps, pname, weight))

        if not assigned:
            logging.info(f"No tasks for worker {worker_id}")
            return 0.0

        def _name(x):
            return x["functions name"] if isinstance(x, dict) else x

        # normalize: everything keyed by function name (string)
        fargs = {fn["functions name"]: fn.get("args", ())
                 for (fn, _, _, _) in assigned}

        dependency_graph = {
            fn["functions name"]: [_name(d) for d in deps]
            for (fn, deps, _, _) in assigned
        }

        function_info = {
            fn["functions name"]: {"partition_name": pname, "weight": weight}
            for (fn, _, pname, weight) in assigned
        }

        # helpful logs (optional)
        logging.info(f"Complete dependency graph for worker {worker_id}:")
        for fn, deps in dependency_graph.items():
            logging.info(f"  {fn} -> {deps}")

        # topo order over string names
        topo = self._topological_sort(dependency_graph)

        results = {}
        futures = {}

        max_workers = min(max(2, os.cpu_count() or 2), len(topo))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for fn in topo:
                # wait for deps & collect their outputs
                pipeline_result = {}
                for dep in dependency_graph.get(fn, []):
                    if dep in futures:
                        dep_val = futures[dep][0].result()
                        results[dep] = dep_val
                        pipeline_result[dep] = dep_val

                # forward (fn_name, args, pipeline_result) to get_work
                future = executor.submit(
                    self.get_work,
                    fn,
                    fargs.get(fn, ()),
                    pipeline_result,
                )
                futures[fn] = (future, function_info[fn]["partition_name"])

        # finalize (log exceptions)
        for fn, (future, pname) in futures.items():
            try:
                results[fn] = future.result()
                logging.info(f"Method {fn} for partition {pname} completed.")
            except Exception as exc:
                logging.error(f"Method {fn} for partition {pname} generated an exception: {exc}")

        # ._exec_multi_process doesn't need to return anything specific
        return 0.0
