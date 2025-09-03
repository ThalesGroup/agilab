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

# Internal Libraries:
from collections import defaultdict, deque
import time
import warnings

# External Libraries:
from concurrent.futures import ThreadPoolExecutor
from agi_env import AgiEnv, normalize_path
from agi_node.agi_dispatcher import BaseWorker
import logging
warnings.filterwarnings("ignore")
logger = logging.getLogger(__name__)

class DagWorker(BaseWorker):
    """
    DagWorker Class

    Inherits from:
        BaseWorker: Provides foundational worker functionalities.
    """

    def works(self, workers_tree, workers_tree_info):
        """Run the worker tasks."""
        if workers_tree:
            if self.mode & 4:
                self.exec_multi_process(workers_tree, workers_tree_info)
            else:
                self.exec_mono_process(workers_tree, workers_tree_info)
        self.stop()
        return time.time() - BaseWorker.t0

    def exec_mono_process(self, workers_tree, workers_tree_info):
        """
        Execute tasks in a single process, respecting dependencies,
        but only for branches assigned to this worker via round-robin.
        """
        # guard against None
        workers_tree      = workers_tree      or []
        workers_tree_info = workers_tree_info or []
        num_workers       = len(workers_tree)
        worker_id         = self.worker_id

        # collect only branches for this worker
        assigned = [
            (tree, info)
            for idx, (tree, info) in enumerate(zip(workers_tree, workers_tree_info))
            if idx % num_workers == worker_id
        ]
        if not assigned:
            logging.info(f"No tasks for worker {worker_id}")
            return
        # execute each branch sequentially
        for tree, info in assigned:
            fargs = {t[0]["functions name"]:t[0]["args"] for t in tree}
            # build dependency graph & function metadata
            dependency_graph = {fn["functions name"]: deps for fn, deps in tree}
            print(dependency_graph)
            function_info    = {
                fn["functions name"]: {"partition_name": pname, "weight": weight}
                for (fn, _), (pname, weight) in zip(tree, info)
            }
            # debug
            logging.info(f"Complete dependency graph for worker {worker_id}:")
            for fn, deps in dependency_graph.items():
                logging.info(f"  {fn}: {deps}")
            logging.info("Function info:")
            for fn, meta in function_info.items():
                logging.info(
                    f"  {fn}: algo={meta['partition_name']}, sequence={meta['weight']}"
                )

            # topological sort
            try:
                topo_order = self.topological_sort(dependency_graph)
                logging.info(f"Topological order: {topo_order}")
            except (KeyError, ValueError) as e:
                logging.error(f"Error during topological sort: {e}")
                continue
            prev_result={}
            # execute in order
            for fn in topo_order:
                pname = function_info[fn]["partition_name"]
                logging.info(f"Executing {fn} for partition {pname}")
                pipeline_result = {}
                for dependency in dependency_graph[fn]:
                    pipeline_result[dependency] = prev_result[dependency]
                try:
                    prev_result[fn] = self.get_work(fn,fargs[fn],pipeline_result)
                except Exception as e:
                    logging.error(f"Error executing {fn}: {e}")

    def topological_sort(self, dependency_graph):
        """
        Perform a topological sort on the dependency graph.
        Raises ValueError on cycles.
        """
        in_degree = defaultdict(int)
        adj_list  = defaultdict(list)
        for fn, deps in dependency_graph.items():
            for dep in deps:
                adj_list[dep].append(fn)
                in_degree[fn] += 1

        queue = deque([fn for fn in dependency_graph if in_degree[fn] == 0])
        topo_order = []
        while queue:
            current = queue.popleft()
            topo_order.append(current)
            for nbr in adj_list[current]:
                in_degree[nbr] -= 1
                if in_degree[nbr] == 0:
                    queue.append(nbr)

        if len(topo_order) != len(dependency_graph):
            remaining = set(dependency_graph) - set(topo_order)
            raise ValueError(f"Circular dependency detected: {remaining}")
        return topo_order

    def exec_multi_process(self, workers_tree, workers_tree_info):
        """
        Execute tasks across a thread pool, respecting dependencies,
        but only for branches assigned to this worker via round-robin.
        """
        # guard against None
        workers_tree = workers_tree or []
        workers_tree_info = workers_tree_info or []
        num_workers = len(workers_tree)
        worker_id = self.worker_id

        # collect tasks assigned to this worker by round-robin
        assigned = []
        for idx, (tree, info) in enumerate(zip(workers_tree, workers_tree_info)):
            if idx % num_workers != worker_id:
                continue
            for (fn, deps), (pname, weight) in zip(tree, info):
                assigned.append((fn, deps, pname, weight))

        if not assigned:
            logging.info(f"No tasks for worker {worker_id}")
            return

        # ---- normalize to hashable keys (function names), like mono-process path ----
        # fn is a dict with keys: "functions name", "args"
        fargs = {fn_dict["functions name"]: fn_dict.get("args", {})
                 for (fn_dict, _, _, _) in assigned}

        def _dep_name(d):
            # deps might already be strings; if dicts slipped in, extract their name
            return d["functions name"] if isinstance(d, dict) else d

        dependency_graph = {
            fn_dict["functions name"]: [_dep_name(d) for d in deps]
            for (fn_dict, deps, _, _) in assigned
        }
        function_info = {
            fn_dict["functions name"]: {"partition_name": pname, "weight": weight}
            for (fn_dict, _, pname, weight) in assigned
        }

        # debug
        logging.info(f"Complete dependency graph for worker {worker_id}:")
        for fn, deps in dependency_graph.items():
            logging.info(f"  {fn} -> {deps}")
        logging.info("Function metadata:")
        for fn, meta in function_info.items():
            logging.info(f"  {fn}: algo={meta['partition_name']}, sequence={meta['weight']}")

        # topological sort
        try:
            topo_order = self.topological_sort(dependency_graph)
            logging.info(f"Topological order: {topo_order}")
        except ValueError as e:
            logging.error(f"Error in dependency graph: {e}")
            return

        from concurrent.futures import ThreadPoolExecutor
        import os

        results = {}  # fn_name -> return value from get_work
        futures = {}  # fn_name -> (future, partition_name)

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

                # schedule this task with args + pipeline_result (matches mono-process)
                future = executor.submit(self.get_work, fn, fargs.get(fn, {}), pipeline_result)
                futures[fn] = (future, function_info[fn]["partition_name"])

        # collect results
        for fn, (future, pname) in futures.items():
            try:
                results[fn] = future.result()
                logging.info(f"Method {fn} for partition {pname} completed.")
            except Exception as exc:
                logging.error(f"Method {fn} for partition {pname} generated an exception: {exc}")


