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
      - Uses _invoke() at the single call site in exec_multi_process()
    """

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
    def works(self, workers_tree, workers_tree_info):
        """
        Your existing entry point; keep as-is, just call multiprocess path for mode 4, etc.
        """
        # If you had mode checks, keep them. Here we directly call the multi-process variant.
        self.exec_multi_process(workers_tree, workers_tree_info)

    @staticmethod
    def topological_sort(graph: Mapping[str, Iterable[str]]) -> List[str]:
        """
        Kahn's algorithm for topological sort.
        Raises ValueError if a cycle exists.
        """
        from collections import defaultdict, deque

        indeg = defaultdict(int)
        adj: Dict[str, List[str]] = {k: list(v) for k, v in graph.items()}

        # Ensure all nodes appear in the maps
        for u, deps in list(adj.items()):
            indeg.setdefault(u, 0)
            for v in deps:
                indeg[v] += 1
                adj.setdefault(v, [])

        q = deque([n for n, d in indeg.items() if d == 0])
        order: List[str] = []

        while q:
            u = q.popleft()
            order.append(u)
            for v in adj[u]:
                indeg[v] -= 1
                if indeg[v] == 0:
                    q.append(v)

        if len(order) != len(adj):
            raise ValueError("Cycle detected in dependency graph")
        return order

    def exec_multi_process(self, workers_tree, workers_tree_info):
        """
        Execute tasks across a thread pool, respecting dependencies,
        for the partitions assigned to this worker (round-robin by index).
        """
        logger = getattr(self, "logger", logging.getLogger(self.__class__.__name__))

        workers_tree = workers_tree or []
        workers_tree_info = workers_tree_info or []

        num_partitions = max(1, len(workers_tree))
        worker_id = getattr(self, "worker_id", 0)

        # collect tasks assigned to this worker by round-robin
        assigned = []
        for idx, (tree, info) in enumerate(zip(workers_tree, workers_tree_info)):
            if idx % num_partitions != worker_id:
                continue
            for (fn, deps), (pname, weight) in zip(tree, info):
                assigned.append((fn, deps, pname, weight))

        if not assigned:
            logger.info(f"No tasks for worker {worker_id}")
            return

        # ---- normalize to hashable keys (function names) ----
        def _dep_name(d):
            # deps might already be strings; if dicts slipped in, extract their name
            return d["functions name"] if isinstance(d, dict) else d

        fargs = {
            fn_dict["functions name"]: fn_dict.get("args", {})
            for (fn_dict, _, _, _) in assigned
        }

        dependency_graph = {
            fn_dict["functions name"]: [_dep_name(d) for d in deps]
            for (fn_dict, deps, _, _) in assigned
        }

        function_info = {
            fn_dict["functions name"]: {"partition_name": pname, "weight": weight}
            for (fn_dict, _, pname, weight) in assigned
        }

        # debug logs (kept identical in spirit to your previous logs)
        logger.info(f"Complete dependency graph for worker {worker_id}:")
        for fn, deps in dependency_graph.items():
            logger.info(f"  {fn} -> {deps}")
        logger.info("Function metadata:")
        for fn, meta in function_info.items():
            logger.info(f"  {fn}: algo={meta['partition_name']}, sequence={meta['weight']}")

        # topological sort
        try:
            topo_order = self.topological_sort(dependency_graph)
            logger.info(f"Topological order: {topo_order}")
        except ValueError as e:
            logger.error(f"Error in dependency graph: {e}")
            return

        results = {}
        futures = {}

        max_workers = min(max(2, os.cpu_count() or 2), len(topo_order))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for fn in topo_order:
                # ensure dependencies finished & collect their outputs
                pipeline_result = {}
                for dep in dependency_graph.get(fn, []):
                    if dep in futures:
                        dep_result = futures[dep][0].result()
                        results[dep] = dep_result
                        pipeline_result[dep] = dep_result

                # *** Minimal change here: call _invoke instead of a fixed get_work ***
                future = executor.submit(self._invoke, fn, fargs.get(fn, {}), pipeline_result)
                futures[fn] = (future, function_info[fn]["partition_name"])

        # collect results
        for fn, (future, pname) in futures.items():
            try:
                results[fn] = future.result()
                logger.info(f"Method {fn} for partition {pname} completed.")
            except Exception as exc:
                logger.error(f"Method {fn} for partition {pname} generated an exception: {exc}")
