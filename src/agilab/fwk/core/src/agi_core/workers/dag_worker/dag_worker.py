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
import os
import warnings

# External Libraries:
from concurrent.futures import ThreadPoolExecutor
from agi_core.workers.agi_worker import AgiWorker

warnings.filterwarnings("ignore")


class AgiDagWorker(AgiWorker):
    """
    AgiDagWorker Class

    Inherits from:
        AgiWorker: Provides foundational worker functionalities.
    """

    def works(self, workers_tree, workers_tree_info):
        """Run the worker tasks."""
        if workers_tree:
            if self.mode % 2 == 1:
                self.exec_multi_process(workers_tree, workers_tree_info)
            else:
                self.exec_mono_process(workers_tree, workers_tree_info)
        self.stop()
        return time.time() - AgiWorker.t0

    def exec_mono_process(self, workers_tree, workers_tree_info):
        """Execute tasks in a single process, respecting dependencies."""

        for work_id, work in enumerate(workers_tree):
            # Validate worker_id
            if self.worker_id >= len(workers_tree):
                print(
                    f"Error: worker_id {self.worker_id} is out of range for workers_tree."
                )
                return

            current_worker_tasks = workers_tree[work_id]
            current_worker_info = workers_tree_info[work_id]

            # Build the complete dependency_graph for the current worker
            dependency_graph = {}
            function_info = {}

            for (function, dependencies), (partition_name, weight) in zip(
                current_worker_tasks, current_worker_info
            ):
                dependency_graph[function] = dependencies
                function_info[function] = {
                    "partition_name": partition_name,
                    "weight": weight,
                }

            # Debug: Print the complete dependency graph and function info
            if self.verbose > 0:
                print(f"Complete dependency graph for worker {self.worker_id}:")
                for func, deps in dependency_graph.items():
                    dep_names = [dep for dep in deps]
                    print(f"  {func}: {dep_names}")
                print(f"Function info:")
                for func, info in function_info.items():
                    print(
                        f"  {func}: algo={info['partition_name']}, sequence={info['weight']}"
                    )

            # Perform topological sort on the complete dependency graph
            try:
                topo_order = self.topological_sort(dependency_graph)
                if self.verbose > 0:
                    sorted_funcs = [func for func in topo_order]
                    print(f"Topological order: {sorted_funcs}")
            except (KeyError, ValueError) as e:
                raise Exception(
                    f"Error during topological sort for worker_id {self.worker_id}: {e}"
                )

            # Execute functions in topologically sorted order
            for func in topo_order:
                partition = function_info[func]["partition_name"]
                if self.verbose > 0:
                    print(
                        f"Executing {func} for partition {partition}",
                        flush=True,
                    )
                try:
                    self.exec(func)
                except Exception as e:
                    print(f"Error executing function {func}: {e}")
                    continue  # Continue with the next function

    def topological_sort(self, dependency_graph):
        """
        Perform a topological sort on the dependency graph.

        Args:
            dependency_graph (dict): A dictionary where keys are functions and values are lists of dependent functions.

        Returns:
            list: A list of functions in topologically sorted order.

        Raises:
            ValueError: If a cycle is detected in the dependencies.
        """
        # Calculate in-degrees and adjacency list
        in_degree = defaultdict(int)
        adj_list = defaultdict(list)
        for func, deps in dependency_graph.items():
            for dep in deps:
                adj_list[dep].append(func)
                in_degree[func] += 1

        # Initialize queue with nodes of in-degree 0
        queue = deque([func for func in dependency_graph if in_degree[func] == 0])

        topo_order = []
        while queue:
            current = queue.popleft()
            topo_order.append(current)

            for neighbor in adj_list[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(topo_order) != len(dependency_graph):
            # For debugging, identify the cycle
            remaining = set(dependency_graph.keys()) - set(topo_order)
            cycle_funcs = ", ".join([func.__name__ for func in remaining])
            raise ValueError(f"Circular dependency detected involving: {cycle_funcs}")

        return topo_order

    def exec_multi_process(self, workers_tree, workers_tree_info):
        """Execute tasks in multiple threads, respecting dependencies."""
        if workers_tree is None:
            workers_tree = []

        worker_tree = workers_tree[self.worker_id]
        worker_tree_info = workers_tree_info[self.worker_id]

        dependency_graph = {}
        function_info = {}

        for (function, dependencies), (partition_name, weight) in zip(
            worker_tree, worker_tree_info
        ):
            dependency_graph[function] = dependencies
            function_info[function] = {
                "partition_name": partition_name,
                "weight": weight,
            }

        # Perform topological sort
        try:
            topo_order = self.topological_sort(dependency_graph)
        except ValueError as e:
            print(f"Error: {e}")
            return

        futures = {}
        with ThreadPoolExecutor() as executor:
            for function in topo_order:
                dependencies = dependency_graph[function]
                # Wait for dependencies to complete
                for dep in dependencies:
                    if dep in futures:
                        future_dep, _ = futures[dep]  # Extract the future
                        future_dep.result()
                # Submit the function to be executed
                partition_name = function_info[function]["partition_name"]
                future = executor.submit(self.exec, (function))
                futures[function] = (future, partition_name)

        # Collect results
        for function, (future, partition_name) in futures.items():
            try:
                result = future.result()
                if self.verbose > 0:
                    print(
                        f"Method {function} for partition {partition_name} completed."
                    )
            except Exception as exc:
                print(
                    f"Method {function} for partition {partition_name} generated an exception: {exc}"
                )