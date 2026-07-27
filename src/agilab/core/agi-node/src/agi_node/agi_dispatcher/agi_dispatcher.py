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

"""Dispatch helpers for coordinating AGILab worker execution."""

######################################################
# Agi Framework call back functions
######################################################
# Internal Libraries:
import importlib
import os
import re
import sys
import stat
import json
from contextvars import ContextVar
from itertools import zip_longest
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# External Libraries:
import numpy as np
import datetime
import logging

from agi_env import AgiEnv
from agi_env.runtime.atomic_write_support import atomic_write_text

from .distribution_cache_support import (
    DISTRIBUTION_CACHE_SCHEMA,
    build_cache_context,
)

logger = logging.getLogger(__name__)
workers_default = {"127.0.0.1": 1}
RUN_STAGES_KEY = "_agilab_run_stages"
_ACTIVE_DISTRIBUTION_CAPACITIES: ContextVar[tuple[float, ...] | None] = ContextVar(
    "agilab_distribution_capacities",
    default=None,
)

# Conservative module/distribution name allow-list for runtime auto-install.
# The auto-install command is executed through a shell, so the name must not
# contain metacharacters that could be routed by the shell.
_SAFE_MODULE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")

# Import names and PyPI distribution names differ for common packages. Runtime
# auto-install receives the *import* name from ModuleNotFoundError, so it must
# be resolved to the distribution name before being handed to `uv add`.
_IMPORT_TO_DISTRIBUTION = {
    "PIL": "pillow",
    "cv2": "opencv-python",
    "dotenv": "python-dotenv",
    "sklearn": "scikit-learn",
    "yaml": "pyyaml",
}


class WorkDispatcher:
    """Builds and runs distribution plans for target applications."""

    verbose = None

    def __init__(self, args=None):
        """Store ``args`` for later use when evaluating distribution plans."""
        self.args = args or {}

    @staticmethod
    def _split_dispatch_args(args):
        target_args = dict(args or {})
        if "_agilab_run_steps" in target_args:
            raise TypeError("Legacy dispatch key '_agilab_run_steps' is no longer supported; use '_agilab_run_stages'.")
        run_stages = target_args.pop(RUN_STAGES_KEY, [])
        if run_stages is None:
            run_stages = []
        if not isinstance(run_stages, list):
            raise TypeError(f"{RUN_STAGES_KEY} must be a list of workflow stage payloads")
        return target_args, run_stages

    @staticmethod
    def _apply_run_stages(target_inst, run_stages):
        if not run_stages:
            return

        args_obj = getattr(target_inst, "args", None)
        if isinstance(args_obj, dict):
            if "args" not in args_obj:
                raise TypeError(f"{type(target_inst).__name__} does not accept RunRequest.stages")
            args_obj["args"] = run_stages
        elif hasattr(args_obj, "args"):
            setattr(args_obj, "args", run_stages)
        else:
            raise TypeError(f"{type(target_inst).__name__} does not accept RunRequest.stages")

    @staticmethod
    def _convert_functions_to_names(workers_plan):
        """Recursively replace callables in ``workers_plan`` by their ``__name__``."""
        def _convert(val):
            if isinstance(val, list):
                return [_convert(item) for item in val]
            elif isinstance(val, tuple):
                return tuple(_convert(item) for item in val)
            elif isinstance(val, dict):
                return {key: _convert(value) for key, value in val.items()}
            elif callable(val):
                return val.__name__
            else:
                return val

        return _convert(workers_plan)

    @staticmethod
    def _cache_json_default(obj):
        if isinstance(obj, (datetime.date, datetime.datetime)):
            return obj.isoformat()
        if isinstance(obj, Path):
            return str(obj)
        raise TypeError(f"Type {type(obj)} not serializable")

    @staticmethod
    def _normalize_cache_value(value):
        return json.loads(
            json.dumps(
                value,
                default=WorkDispatcher._cache_json_default,
                sort_keys=True,
            )
        )

    @staticmethod
    def _worker_slots(workers):
        return [
            str(worker)
            for worker, count in workers.items()
            for _ in range(int(count))
        ]

    @staticmethod
    def _load_cached_distribution(
        file,
        *,
        workers,
        worker_slots,
        cache_args,
        cache_context,
    ):
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            logger.warning("Ignoring unreadable distribution cache %s: %s", file, exc)
            return None

        if not isinstance(data, dict):
            logger.warning("Ignoring malformed distribution cache %s: expected an object", file)
            return None
        if data.get("schema") != DISTRIBUTION_CACHE_SCHEMA:
            return None
        if (
            data.get("workers") != workers
            or data.get("worker_slots") != worker_slots
            or data.get("target_args") != cache_args
            or data.get("cache_context") != cache_context
        ):
            return None

        workers_plan = data.get("work_plan")
        workers_plan_metadata = data.get("work_plan_metadata", [])
        if not isinstance(workers_plan, list) or not isinstance(
            workers_plan_metadata, list
        ):
            logger.warning(
                "Ignoring malformed distribution cache %s: work plan payloads must be lists",
                file,
            )
            return None
        return workers_plan, workers_plan_metadata

    @staticmethod
    def _write_distribution_cache(file, data):
        serialized = json.dumps(
            data,
            default=WorkDispatcher._cache_json_default,
            indent=2,
            sort_keys=True,
        )
        atomic_write_text(file, f"{serialized}\n", encoding="utf-8")

    @staticmethod
    async def _do_distrib(env, workers, args, *, capacities=None):
        """Build the distribution plan for ``env`` given worker layout and args."""
        target_args, run_stages = WorkDispatcher._split_dispatch_args(args)
        cache_args = dict(target_args)
        if run_stages:
            cache_args[RUN_STAGES_KEY] = run_stages
        normalized_cache_args = WorkDispatcher._normalize_cache_value(cache_args)
        normalized_workers = WorkDispatcher._normalize_cache_value(workers)
        worker_slots = WorkDispatcher._worker_slots(workers)

        active_capacities = None
        if capacities is not None:
            active_capacities = tuple(
                float(value)
                for value in WorkDispatcher._normalize_worker_capacities(
                    capacities,
                    workers,
                )
            )

        target_module = await WorkDispatcher._load_module(
            env.target,
            env.target,
            path=env.app_src,
            env=env,
        )
        if not target_module:
            raise RuntimeError(f"failed to load {env.target}")

        target_class = getattr(target_module, env.target_class)
        target_inst = target_class(env, **target_args)
        WorkDispatcher._apply_run_stages(target_inst, run_stages)

        file = env.distribution_tree
        cache_context = build_cache_context(
            target_inst,
            capacities=active_capacities,
        )
        cached_distribution = None
        if file.exists():
            cached_distribution = WorkDispatcher._load_cached_distribution(
                file,
                workers=normalized_workers,
                worker_slots=worker_slots,
                cache_args=normalized_cache_args,
                cache_context=cache_context,
            )

        if cached_distribution is not None:
            workers_plan, workers_plan_metadata = cached_distribution
        else:
            capacity_token = _ACTIVE_DISTRIBUTION_CAPACITIES.set(active_capacities)
            try:
                (
                    workers_plan,
                    workers_plan_metadata,
                    part,
                    nb_unit,
                    weight_unit,
                ) = target_inst.build_distribution(workers)
            finally:
                _ACTIVE_DISTRIBUTION_CAPACITIES.reset(capacity_token)

            cache_context_after = build_cache_context(
                target_inst,
                capacities=active_capacities,
            )
            if cache_context != cache_context_after:
                raise RuntimeError(
                    "distribution inputs changed while the work plan was being built"
                )
            cache_context = cache_context_after

            data = {
                "schema": DISTRIBUTION_CACHE_SCHEMA,
                "cache_context": cache_context,
                "target_args": normalized_cache_args,
                "workers": normalized_workers,
                "worker_slots": worker_slots,
                "work_plan_metadata": workers_plan_metadata,
                "work_plan": WorkDispatcher._convert_functions_to_names(workers_plan),
                "partition_key": part,
                "nb_unit": nb_unit,
                "weights_unit": weight_unit,
            }

            WorkDispatcher._write_distribution_cache(file, data)

            # Normalize the in-memory plan exactly like the cached copy
            # (callables -> names, tuples -> lists, datetimes -> isoformat)
            # so cache-miss and cache-hit runs dispatch identical payloads.
            normalized = WorkDispatcher._normalize_cache_value(
                {
                    "work_plan": data["work_plan"],
                    "work_plan_metadata": workers_plan_metadata,
                }
            )
            workers_plan = normalized["work_plan"]
            workers_plan_metadata = normalized["work_plan_metadata"]

        loaded_workers = {}
        workers_work_item_tree_iter = iter(workers_plan)
        for ip, nb_workers in workers.items():
            for _ in range(nb_workers):
                try:
                    chunks = next(workers_work_item_tree_iter)
                except StopIteration:
                    break
                if ip not in loaded_workers:
                    loaded_workers[ip] = 0
                if chunks:
                    loaded_workers[ip] += 1

        # Drop empty chunks from the plan and its metadata in lockstep so the
        # per-worker index alignment between the two lists is preserved.
        kept = [
            (plan_chunk, metadata_chunk)
            for plan_chunk, metadata_chunk in zip_longest(
                workers_plan, workers_plan_metadata or [], fillvalue=[]
            )
            if plan_chunk
        ]
        workers_plan = [plan_chunk for plan_chunk, _ in kept]
        workers_plan_metadata = [metadata_chunk for _, metadata_chunk in kept]

        return loaded_workers.copy(), workers_plan, workers_plan_metadata

    @staticmethod
    def _onerror(func, path, exc_info):
        """
        Error handler for `shutil.rmtree`.

        If the error is due to an access error (read-only file),
        it attempts to add write permission and then retries.

        If the error is for another reason, it re-raises the error.

        Usage: `shutil.rmtree(path, onerror=onerror)`

        Args:
            func (function): The function that raised the error.
            path (str): The path name passed to the function.
            exc_info (tuple): The exception information returned by `sys.exc_info()`.

        Returns:
            None
        """
        # Check if file access issue
        if not os.access(path, os.W_OK):
            # Try to change the permissions of the file to writable
            os.chmod(path, stat.S_IWUSR)
            # Try the operation again
            func(path)
            return

        exc_value = exc_info[1] if len(exc_info) > 1 else None
        if isinstance(exc_value, BaseException):
            traceback_obj = exc_info[2] if len(exc_info) > 2 else None
            raise exc_value.with_traceback(traceback_obj)
        raise RuntimeError(f"failed to remove {path!r}")

    @staticmethod
    def make_chunks(
        nchunk2: int,
        weights: List[Any],
        capacities: Optional[List[Any]] = None,
        workers: Dict = None,  # ty: ignore[invalid-parameter-default]
        verbose: int = 0,
        threshold: int = 12,
    ) -> List[List[List[Any]]]:
        """Partitions the nchunk2 weighted into n chuncks, in a smart way
        chunks and chunks_sizes must be left to None

        Args:
          nchunk2: list of number of chunks level 2
          weights: the list of weight level2
          capacities: the list of workers capacity (Default value = None)
          verbose: whether to display run detail or not (Default value = 0)
          threshold: the number of nchunk2 max to run the optimal algo otherwise downgrade to suboptimal one (Default value = 12)
          weights: list:


        Returns:
          : list of chunk per your_worker containing list of works per your_worker containing list of chunks level 1

        """
        if not workers:
            workers = workers_default
        if capacities is None:
            capacities = _ACTIVE_DISTRIBUTION_CAPACITIES.get()
        capacities = WorkDispatcher._normalize_worker_capacities(capacities, workers)  # ty: ignore[invalid-assignment]

        if len(weights) > 1:
            if nchunk2 < threshold:
                logging.info(f"optimal - workers capacities {capacities} - {nchunk2} works to be done")
                chunks = WorkDispatcher._make_chunks_optimal(weights, capacities)  # ty: ignore[invalid-argument-type]
            else:
                logging.info(f"fastest - workers capacities {capacities} - {nchunk2} works to be done")
                chunks = WorkDispatcher._make_chunks_fastest(weights, capacities)  # ty: ignore[invalid-argument-type]

            return chunks

        else:
            # Return the same per-worker shape as the multi-weight branches:
            # one chunk (list of (label, size) tuples) for the single worker.
            return [list(weights)]

    @staticmethod
    def _normalize_worker_capacities(capacities: Optional[List[Any]], workers: Dict) -> np.ndarray:
        capacity_values = [] if capacities is None else list(capacities)
        if not capacity_values:
            capacity_values = [
                1.0
                for worker_count in workers.values()
                for _ in range(worker_count)
            ]

        normalized = np.array(capacity_values, dtype=float)
        if normalized.size == 0:
            raise ValueError("worker capacities must contain at least one worker slot")
        if not np.all(np.isfinite(normalized)) or np.any(normalized <= 0):
            raise ValueError("worker capacities must be finite positive values")
        return normalized

    @staticmethod
    def _make_chunks_optimal(
    subsets: List[Any],
    chkweights: List[Any],
    chunks: Optional[List[Any]] = None,
    chunks_sizes: Optional[Any] = None
) -> Any:
        """Partitions subsets in nchk non-weighted chunks, in a slower but optimal recursive way.

        The search is exponential, so callers should keep using ``make_chunks``'
        threshold gate for larger work plans.  This implementation mutates one
        working assignment in place and undoes each recursive branch instead of
        deep-copying every candidate tree.

        Args:
          subsets: list of tuples ('label', size)
          chkweights: list containing the relative size of each chunk
          chunks: internal usage must be None (Default value = None)
          chunks_sizes: internal must be None (Default value = None)

        Returns:
          : list of chunks weighted

        """
        nchk = len(chkweights)
        capacities = np.array(chkweights, dtype=float)
        root_call = chunks is None
        working_chunks = [[] for _ in range(nchk)] if chunks is None else chunks
        working_sizes = (
            np.zeros(nchk, dtype=float)
            if chunks_sizes is None
            else np.array(chunks_sizes, dtype=float)
        )
        ordered_subsets = list(subsets)
        if root_call:
            ordered_subsets.sort(reverse=True, key=lambda i: i[1])

        def _snapshot() -> tuple[list[list[Any]], float]:
            return [list(chunk) for chunk in working_chunks], float(max(working_sizes))

        def _search(start: int) -> tuple[list[list[Any]], float]:
            if start >= len(ordered_subsets):
                return _snapshot()

            remaining = ordered_subsets[start:]
            remaining_weight = sum(item[1] for item in remaining)

            # Optimisation: if even putting all remaining work on the least-loaded
            # worker cannot improve the current maximum load, finish this branch.
            if max(working_sizes) > min(working_sizes + remaining_weight / capacities):
                smallest_chunk_index = int(
                    np.argmin(working_sizes + remaining_weight / capacities)
                )
                previous_size = float(working_sizes[smallest_chunk_index])
                previous_len = len(working_chunks[smallest_chunk_index])
                working_chunks[smallest_chunk_index].extend(remaining)
                working_sizes[smallest_chunk_index] = (
                    previous_size + remaining_weight / capacities[smallest_chunk_index]
                )
                result = _snapshot()
                del working_chunks[smallest_chunk_index][previous_len:]
                working_sizes[smallest_chunk_index] = previous_size
                return result

            subset = ordered_subsets[start]
            best: tuple[list[list[Any]], float] | None = None
            inserted_chunk_sizes = set()
            for i in range(nchk):
                # Add the next subset to the ith chunk if we have not already
                # tried an equivalent chunk/capacity state.
                state_key = (float(working_sizes[i]), float(capacities[i]))
                if state_key in inserted_chunk_sizes:
                    continue
                inserted_chunk_sizes.add(state_key)

                normalized_weight = subset[1] / capacities[i]
                working_chunks[i].append(subset)
                working_sizes[i] += normalized_weight
                candidate = _search(start + 1)
                working_chunks[i].pop()
                working_sizes[i] -= normalized_weight

                if best is None or candidate[1] < best[1]:
                    best = candidate

            if best is None:  # pragma: no cover - defensive guard
                return _snapshot()
            return best

        best_chunks, best_size = _search(0)
        if root_call:
            return best_chunks
        return [best_chunks, best_size]

    @staticmethod
    def _make_chunks_fastest(subsets: List[Any], chk_weights: List[Any]) -> List[List[Any]]:
        """Partitions subsets using capacity-normalized LPT scheduling.

        Args:
          subsets: list of tuples ('label', size)
          chk_weights: list containing the relative capacity of each worker

        Returns:
          : list of chunk weighted

        """
        capacities = WorkDispatcher._normalize_worker_capacities(chk_weights, {})
        nchk = len(capacities)

        # Sort a copy so callers keep their original ``subsets`` ordering.
        subsets = sorted(subsets, reverse=True, key=lambda j: j[1])
        chunks = [[] for _ in range(nchk)]
        normalized_loads = np.zeros(nchk, dtype=float)

        for subset in subsets:
            subset_weight = float(subset[1])
            if not np.isfinite(subset_weight) or subset_weight < 0:
                raise ValueError("work item weights must be finite non-negative values")
            projected_loads = normalized_loads + (subset_weight / capacities)
            smallest_chunk = int(np.argmin(projected_loads))
            chunks[smallest_chunk].append(subset)
            normalized_loads[smallest_chunk] = projected_loads[smallest_chunk]

        return chunks

    @staticmethod
    async def _load_module(
            module: str,
            package: Optional[str] = None,
            path: Optional[Union[str, Path]] = None,
            env: Optional[AgiEnv] = None,
            attempted_install: bool = False,
    ) -> Any:
        """load a module

        Args:
          env: the current Agi environment (used for fallback install)
          module: the name of the Agi apps module
          package: the package name where the module lives (Default value = None)
          path: the path where the package lives (Default value = None)

        Returns:
          : the instance of the module

        """
        logging.info(f"import {module} from {package} located in {path}")
        if path:
            try:
                candidate = Path(path)
                if candidate.is_file():
                    candidate = candidate.parent
                candidate = candidate.resolve()
                # Ensure both src path and repository root are in sys.path
                paths_to_add = [candidate]
                repo_root = candidate.parent.parent if candidate.name == "src" else None
                if repo_root:
                    paths_to_add.append(repo_root)
                for entry in paths_to_add:
                    try:
                        entry_str = str(entry)
                        if entry_str not in sys.path:
                            sys.path.insert(0, entry_str)
                    except OSError:
                        pass
            except OSError:
                pass

        try:
            if package:
                # Import module from a package
                return importlib.import_module(f"{package}.{module}")
            else:
                # Import module directly
                return importlib.import_module(module)

        except ModuleNotFoundError as e:
            # Only attempt install if an environment is provided
            if env is None or attempted_install:
                raise
            if not WorkDispatcher._runtime_auto_install_enabled(env):
                logger.error(
                    "runtime dependency auto-install refused for missing module %s; "
                    "declare the dependency in the app or set AGILAB_RUNTIME_AUTO_INSTALL=1",
                    getattr(e, "name", None) or str(e),
                )
                raise
            module_to_install = WorkDispatcher._missing_module_name(e)
            if not module_to_install:
                raise
            module_to_install = _IMPORT_TO_DISTRIBUTION.get(
                module_to_install, module_to_install
            )
            if not _SAFE_MODULE_NAME_RE.match(module_to_install):
                logger.error(
                    "runtime dependency auto-install refused for unsafe module name %r; "
                    "only [A-Za-z0-9._-] are allowed",
                    module_to_install,
                )
                raise
            app_path = env.active_app
            cmd = f"{env.uv} add --upgrade {module_to_install}"
            await WorkDispatcher._record_runtime_auto_install_event(env, module_to_install, cmd, app_path)
            logger.warning("runtime dependency auto-install: %s from %s", cmd, app_path)
            await AgiEnv.run(cmd, app_path)
            return await WorkDispatcher._load_module(
                module,
                package,
                path,
                env=env,
                attempted_install=True,
            )

    @staticmethod
    def _runtime_auto_install_enabled(env) -> bool:
        value = getattr(env, "runtime_auto_install", None)
        if value is None:
            value = os.environ.get("AGILAB_RUNTIME_AUTO_INSTALL", "")
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _missing_module_name(exc: ModuleNotFoundError) -> str:
        # Preserve the original module/dist name casing: PyPI names passed to
        # ``uv add`` are case-sensitive, so lowercasing can request the wrong
        # distribution.
        name = getattr(exc, "name", None)
        if name:
            return str(name).strip()
        return str(exc).replace("No module named ", "").replace("'", "").strip()

    @staticmethod
    async def _record_runtime_auto_install_event(env, module_name: str, cmd: str, app_path: Path) -> None:
        event = {
            "event": "runtime_dependency_auto_install",
            "module": module_name,
            "command": cmd,
            "app_path": str(app_path),
        }
        recorder = getattr(env, "record_provenance_event", None)
        if not callable(recorder):
            return
        result = recorder(event)
        if hasattr(result, "__await__"):
            await result
