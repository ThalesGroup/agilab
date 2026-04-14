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

"""
node module

    Auteur: Jean-Pierre Morard

"""

######################################################
# Agi Framework call back functions
######################################################
# Internal Libraries:
import abc
import asyncio
from contextlib import suppress
import getpass
import inspect
import json
import os
import pickle
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import traceback
import warnings
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
from typing import Any, Callable, ClassVar, Dict, Iterable, List, Optional, Union

# External Libraries:
import numpy as np
from distutils.sysconfig import get_python_lib
import psutil
import humanize
import datetime
import logging
from copy import deepcopy

from agi_env import AgiEnv, normalize_path

from agi_env.agi_logger import AgiLogger
from . import base_worker_execution_support as execution_support
from . import base_worker_path_support as path_support
from . import base_worker_runtime_support as runtime_support
from . import base_worker_service_support as service_support

logger = AgiLogger.get_logger(__name__)

warnings.filterwarnings("ignore")
class BaseWorker(abc.ABC):
    """
    class BaseWorker v1.0
    """

    _insts = {}
    _built = None
    _pool_init = None
    _work_pool = None
    _share_path = None
    verbose = 1
    _mode = None
    env = None
    _worker_id = None
    _worker = None
    _home_dir = None
    _logs = None
    _dask_home = None
    _worker = None
    _t0 = None
    _is_managed_pc = getpass.getuser().startswith("T0")
    _cython_decorators = ["njit"]
    env: Optional[AgiEnv] = None
    default_settings_path: ClassVar[str] = "app_settings.toml"
    default_settings_section: ClassVar[str] = "args"
    args_loader: ClassVar[Callable[..., Any] | None] = None
    args_merger: ClassVar[Callable[[Any, Optional[Any]], Any] | None] = None
    args_ensure_defaults: ClassVar[Callable[..., Any] | None] = None
    args_dumper: ClassVar[Callable[..., None] | None] = None
    args_dump_mode: ClassVar[str] = "json"
    managed_pc_home_suffix: ClassVar[str] = "MyApp"
    managed_pc_path_fields: ClassVar[tuple[str, ...]] = ()
    _service_stop_events: ClassVar[Dict[int, threading.Event]] = {}
    _service_active: ClassVar[Dict[int, bool]] = {}
    _service_lock: ClassVar[threading.Lock] = threading.Lock()
    _service_poll_default: ClassVar[float] = 1.0

    @classmethod
    def _require_args_helper(cls, attr_name: str) -> Callable[..., Any]:
        helper = getattr(cls, attr_name, None)
        if helper is None:
            raise AttributeError(
                f"{cls.__name__} must define `{attr_name}` to use argument helpers"
            )
        return helper

    @classmethod
    def _remap_managed_pc_path(
        cls,
        value: Path | str,
        *,
        env: AgiEnv | None = None,
    ) -> Path:
        return path_support.remap_managed_pc_path(
            value,
            env=env or cls.env,
            managed_pc_home_suffix=cls.managed_pc_home_suffix,
            path_cls=Path,
            home_factory=Path.home,
        )

    @classmethod
    def _apply_managed_pc_path_overrides(
        cls,
        args: Any,
        *,
        env: AgiEnv | None = None,
    ) -> Any:
        cls._ensure_managed_pc_share_dir(env)
        fields = cls.managed_pc_path_fields
        if not fields:
            return args

        for field in fields:
            if not hasattr(args, field):
                continue
            value = getattr(args, field)
            try:
                remapped = cls._remap_managed_pc_path(value, env=env)
            except (TypeError, ValueError):
                continue
            setattr(args, field, remapped)
        return args

    def _apply_managed_pc_paths(self, args: Any) -> Any:
        return type(self)._apply_managed_pc_path_overrides(args, env=self.env)

    @classmethod
    def _ensure_managed_pc_share_dir(cls, env: AgiEnv | None) -> None:
        path_support.ensure_managed_pc_share_dir(
            env,
            managed_pc_home_suffix=cls.managed_pc_home_suffix,
            path_cls=Path,
            home_factory=Path.home,
        )

    @classmethod
    def _normalized_path(cls, value: Path | str) -> Path:
        return path_support.normalized_path(
            value,
            normalize_path_fn=normalize_path,
            path_cls=Path,
        )

    @staticmethod
    def _share_root_path(env: AgiEnv | None) -> Path | None:
        return path_support.share_root_path(env, path_cls=Path)

    @classmethod
    def _resolve_data_dir(
        cls,
        env: AgiEnv | None,
        data_path: Path | str | None,
    ) -> Path:
        """Resolve ``data_in`` style values relative to the current environment."""
        return path_support.resolve_data_dir(
            env,
            data_path,
            share_root_path_fn=cls._share_root_path,
            remap_managed_pc_path_fn=lambda value: cls._remap_managed_pc_path(value, env=env),
            normalized_path_fn=cls._normalized_path,
            path_cls=Path,
            home_factory=Path.home,
        )

    @staticmethod
    def _relative_to_user_home(path: Path) -> Path | None:
        return path_support.relative_to_user_home(path, path_cls=Path)

    @staticmethod
    def _remap_user_home(path: Path, *, username: str) -> Path | None:
        return path_support.remap_user_home(path, username=username, path_cls=Path)

    @staticmethod
    def _strip_share_prefix(path: Path, aliases: set[str]) -> Path:
        return path_support.strip_share_prefix(path, aliases, path_cls=Path)

    @staticmethod
    def _can_create_path(path: Path) -> bool:
        return path_support.can_create_path(path, path_cls=Path)

    @staticmethod
    def _collect_share_aliases(
        env: AgiEnv | None, share_base: Path
    ) -> set[str]:
        return path_support.collect_share_aliases(env, share_base, path_cls=Path)

    @staticmethod
    def _iter_input_files(
        folder: Path,
        *,
        patterns: Iterable[str] | None = None,
    ) -> list[Path]:
        return path_support.iter_input_files(folder, patterns=patterns)

    @classmethod
    def _has_min_input_files(
        cls,
        folder: Path,
        *,
        min_files: int = 1,
        patterns: Iterable[str] | None = None,
    ) -> bool:
        return path_support.has_min_input_files(
            folder,
            min_files=min_files,
            patterns=patterns,
            iter_input_files_fn=cls._iter_input_files,
        )

    @classmethod
    def _candidate_named_dataset_roots(
        cls,
        env: AgiEnv | None,
        dataset_root: Path | str,
        *,
        namespace: str | None = None,
        parent_levels: int = 4,
    ) -> list[Path]:
        return path_support.candidate_named_dataset_roots(
            env,
            dataset_root,
            namespace=namespace,
            parent_levels=parent_levels,
            normalized_path_fn=cls._normalized_path,
            share_root_path_fn=cls._share_root_path,
            path_cls=Path,
        )

    @classmethod
    def resolve_input_folder(
        cls,
        env: AgiEnv | None,
        dataset_root: Path | str,
        relative_dir: Path | str,
        *,
        descriptor: str,
        fallback_subdirs: Iterable[str] = (),
        dataset_namespace: str | None = None,
        min_files: int = 1,
        patterns: Iterable[str] | None = None,
        required_label: str = "data files",
    ) -> Path:
        return path_support.resolve_input_folder(
            env,
            dataset_root,
            relative_dir,
            descriptor=descriptor,
            fallback_subdirs=fallback_subdirs,
            dataset_namespace=dataset_namespace,
            min_files=min_files,
            patterns=patterns,
            required_label=required_label,
            normalized_path_fn=cls._normalized_path,
            has_min_input_files_fn=cls._has_min_input_files,
            candidate_named_dataset_roots_fn=lambda current_env, root, namespace=None: cls._candidate_named_dataset_roots(
                current_env,
                root,
                namespace=namespace,
            ),
            warn_fn=logger.warning,
            path_cls=Path,
        )


    def prepare_output_dir(
        self,
        root: Path | str,
        *,
        subdir: str = "dataframe",
        attribute: str = "data_out",
        clean: bool = True,
    ) -> Path:
        """Create (and optionally reset) a deterministic output directory."""

        target = Path(normalize_path(Path(root) / subdir))

        if clean and target.exists():
            try:
                shutil.rmtree(target, ignore_errors=True, onerror=self._onerror)
            except (OSError, RuntimeError) as exc:  # pragma: no cover - defensive guard
                logger.warning(
                    "Issue while cleaning output directory %s: %s", target, exc
                )

        try:
            logger.info(f"mkdir {target}")
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:  # pragma: no cover - defensive guard
            logger.warning(
                "Issue while ensuring output directory %s exists: %s", target, exc
            )

        setattr(self, attribute, target)
        return target

    def setup_args(
        self,
        args: Any,
        *,
        env: AgiEnv | None = None,
        error: str | None = None,
        output_field: str | None = None,
        output_subdir: str = "dataframe",
        output_attr: str = "data_out",
        output_clean: bool = True,
        output_parents_up: int = 0,
    ) -> Any:
        env = env or getattr(self, "env", None)
        if args is None:
            raise ValueError(
                error or f"{type(self).__name__} requires an initialized arguments object"
            )

        ensure_fn = getattr(type(self), "args_ensure_defaults", None)
        if ensure_fn is not None:
            args = ensure_fn(args, env=env)

        processed = type(self)._apply_managed_pc_path_overrides(args, env=env)
        self.args = processed

        if output_field:
            root = Path(getattr(processed, output_field))
            for _ in range(max(output_parents_up, 0)):
                root = root.parent
            self.prepare_output_dir(
                root,
                subdir=output_subdir,
                attribute=output_attr,
                clean=output_clean,
            )

        return processed

    @classmethod
    def from_toml(
        cls,
        env: AgiEnv,
        settings_path: str | Path | None = None,
        section: str | None = None,
        **overrides: Any,
    ) -> "BaseWorker":
        settings_path = settings_path or cls.default_settings_path
        section = section or cls.default_settings_section

        loader = cls._require_args_helper("args_loader")
        merger = cls._require_args_helper("args_merger")

        base_args = loader(settings_path, section=section)
        merged_args = merger(base_args, overrides or None)

        ensure_fn = getattr(cls, "args_ensure_defaults", None)
        if ensure_fn is not None:
            merged_args = ensure_fn(merged_args, env=env)

        merged_args = cls._apply_managed_pc_path_overrides(merged_args, env=env)

        return cls(env, args=merged_args)

    def to_toml(
        self,
        settings_path: str | Path | None = None,
        section: str | None = None,
        create_missing: bool = True,
    ) -> None:
        _cls = type(self)
        settings_path = settings_path or _cls.default_settings_path
        section = section or _cls.default_settings_section

        dumper = _cls._require_args_helper("args_dumper")
        dumper(self.args, settings_path, section=section, create_missing=create_missing)

    def as_dict(self, mode: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any]
        if hasattr(self, "args"):
            dump_mode = mode or type(self).args_dump_mode
            payload = self.args.model_dump(mode=dump_mode)
        else:
            payload = {}
        return self._extend_payload(payload)

    def _extend_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        return payload

    @staticmethod
    def start(worker_inst):
        """Invoke the concrete worker's ``start`` hook once initialised."""
        try:
            logger.info(
                "worker #%s: %s - mode: %s",
                BaseWorker._worker_id,
                BaseWorker._worker,
                getattr(worker_inst, "_mode", None),
            )
            method = getattr(worker_inst, "start", None)
            base_method = BaseWorker.start
            if method and method is not base_method:
                method()
        except Exception:  # pragma: no cover - log and rethrow for visibility
            logger.error("Worker start hook failed:\n%s", traceback.format_exc())
            raise

    def stop(self):
        """
        Returns:
        """
        logger.info(f"worker #{self._worker_id}: {self._worker} - mode: {self._mode}"
                        )
        with BaseWorker._service_lock:
            is_active = BaseWorker._service_active.get(self._worker_id)
        if is_active:
            try:
                BaseWorker.break_loop()
            except RuntimeError:
                logger.debug("break_loop raised", exc_info=True)

    @staticmethod
    def loop(*, poll_interval: Optional[float] = None) -> Dict[str, Any]:
        """Run a long-lived service loop on this worker until signalled to stop.

        The derived worker can implement a ``loop`` method accepting either zero
        arguments or a single ``stop_event`` argument. When the method signature
        accepts ``stop_event`` (keyword ``stop_event`` or ``should_stop``), the
        worker implementation is responsible for honouring the event. Otherwise
        the base implementation repeatedly invokes the method and sleeps for the
        configured poll interval between calls. Returning ``False`` from the
        worker method requests termination of the loop.
        """

        worker_id = BaseWorker._worker_id
        worker_inst = BaseWorker._insts.get(worker_id)
        if worker_id is None or worker_inst is None:
            raise RuntimeError("BaseWorker.loop called before worker initialisation")

        with BaseWorker._service_lock:
            stop_event = threading.Event()
            BaseWorker._service_stop_events[worker_id] = stop_event
            BaseWorker._service_active[worker_id] = True

        poll = BaseWorker._service_poll_default if poll_interval is None else max(
            poll_interval, 0.0
        )
        # Only invoke a worker-defined loop implementation. If the worker
        # relies on BaseWorker.loop (default), block on stop_event instead of
        # recursively calling this method again.
        worker_loop = getattr(type(worker_inst), "loop", None)
        loop_fn = None
        if callable(worker_loop) and worker_loop is not BaseWorker.loop:
            loop_fn = getattr(worker_inst, "loop", None)
        accepts_event = False
        if callable(loop_fn):
            try:
                signature = inspect.signature(loop_fn)
                accepts_event = any(
                    param.kind in (param.POSITIONAL_OR_KEYWORD, param.KEYWORD_ONLY)
                    and param.name in {"stop_event", "should_stop"}
                    for param in signature.parameters.values()
                )
            except (TypeError, ValueError):
                # Some builtins don't expose signatures; fall back to simple mode
                accepts_event = False

        worker_args = getattr(worker_inst, "args", None)
        queue_root = service_support.resolve_service_queue_root(
            worker_args,
            path_cls=Path,
        )

        def _write_heartbeat(_state: str) -> None:
            return

        if queue_root is not None:
            _write_heartbeat = service_support.make_heartbeat_writer(
                queue_root,
                worker_id=worker_id,
                worker_name=BaseWorker._worker,
                logger_obj=logger,
                path_cls=Path,
                open_fn=open,
                json_module=json,
                os_module=os,
                time_module=time,
            )

        start_time = time.time()
        logger.info(
            "worker #%s: %s entering service loop (poll %.3fs)",
            worker_id,
            BaseWorker._worker,
            poll,
        )

        try:
            if not callable(loop_fn):
                if queue_root is not None:
                    payload = service_support.run_service_queue(
                        stop_event=stop_event,
                        queue_root=queue_root,
                        worker_id=worker_id,
                        worker_name=BaseWorker._worker,
                        poll=poll,
                        do_works_fn=BaseWorker._do_works,
                        write_heartbeat=_write_heartbeat,
                        logger_obj=logger,
                        path_cls=Path,
                        open_fn=open,
                        pickle_module=pickle,
                        os_module=os,
                        time_module=time,
                        traceback_module=traceback,
                    )
                    payload["runtime"] = time.time() - start_time
                    return payload

                # No custom loop provided; block until break is requested.
                stop_event.wait()
                return {"status": "stopped", "runtime": time.time() - start_time}

            def _run_once() -> Any:
                if accepts_event:
                    return loop_fn(stop_event)
                return loop_fn()

            while not stop_event.is_set():
                _write_heartbeat("running")
                result = _run_once()
                if inspect.isawaitable(result):
                    try:
                        result = asyncio.run(result)
                    except RuntimeError:
                        loop = asyncio.new_event_loop()
                        try:
                            result = loop.run_until_complete(result)
                        finally:
                            loop.close()

                if result is False:
                    break

                if accepts_event:
                    # Worker manages its own waiting when it handles the stop event.
                    continue

                if poll > 0:
                    stop_event.wait(poll)

            _write_heartbeat("stopped")
            return {"status": "stopped", "runtime": time.time() - start_time}

        except Exception as exc:  # pragma: no cover - worker loop is app-defined
            logger.exception("Service loop failed: %s", exc)
            raise

        finally:
            _write_heartbeat("stopped")
            with BaseWorker._service_lock:
                BaseWorker._service_active.pop(worker_id, None)
                BaseWorker._service_stop_events.pop(worker_id, None)

            stop_hook = getattr(worker_inst, "stop", None)
            if callable(stop_hook):
                try:
                    stop_hook()
                except Exception:  # pragma: no cover - worker stop hook is app-defined
                    logger.exception("Worker stop hook raised inside service loop", exc_info=True)

            logger.info(
                "worker #%s: %s leaving service loop (elapsed %.3fs)",
                worker_id,
                BaseWorker._worker,
                time.time() - start_time,
            )

    @staticmethod
    def break_loop() -> bool:
        """Signal the service loop to exit on this worker."""

        worker_id = BaseWorker._worker_id
        if worker_id is None:
            logger.warning("break_loop called without worker context")
            return False

        with BaseWorker._service_lock:
            stop_event = BaseWorker._service_stop_events.get(worker_id)

        if stop_event is None:
            logger.info("worker #%s: no active service loop to break", worker_id)
            return False

        stop_event.set()
        logger.info("worker #%s: service loop break requested", worker_id)
        return True

    @staticmethod
    def expand_and_join(path1, path2):
        """
        Join two paths after expanding the first path.

        Args:
            path1 (str): The first path to expand and join.
            path2 (str): The second path to join with the expanded first path.

        Returns:
            str: The joined path.
        """
        if os.name == "nt" and not BaseWorker._is_managed_pc:
            path = Path(path1)
            parts = path.parts
            if "Users" in parts:
                index = parts.index("Users") + 2
                path = Path(*parts[index:])
            net_path = normalize_path("\\\\127.0.0.1\\" + str(path))
            try:
                # your nfs account in order to mount it as net drive on windows
                cmd = f'net use Z: "{net_path}" /user:your-name your-password'
                logger.info(cmd)
                subprocess.run(cmd, shell=True, check=True)
            except (OSError, subprocess.CalledProcessError) as e:
                logger.error(f"Mount failed: {e}")
        return BaseWorker._join(BaseWorker.expand(path1), path2)

    @staticmethod
    def expand(path, base_directory=None):
        # Normalize Windows-style backslashes to POSIX forward slashes
        """
        Expand a given path to an absolute path.
        Args:
            path (str): The path to expand.
            base_directory (str, optional): The base directory to use for expanding the path. Defaults to None.

        Returns:
            str: The expanded absolute path.

        Raises:
            None

        Note:
            This method handles both Unix and Windows paths and expands '~' notation to the user's home directory.
        """
        normalized_path = path.replace("\\", "/")

        # Check if the path starts with `~`, expand to home directory only in that case
        if normalized_path.startswith("~"):
            expanded_path = Path(normalized_path).expanduser()
        else:
            # Use base_directory if provided; otherwise, assume current working directory
            base_directory = (
                Path(base_directory).expanduser()
                if base_directory
                else Path("~/").expanduser()
            )
            expanded_path = (base_directory / normalized_path).resolve()

        if os.name != "nt":
            return str(expanded_path)
        else:
            return normalize_path(expanded_path)

    @staticmethod
    def normalize_dataset_path(data_path: Union[str, Path]) -> str:
        """Normalise any dataset directory input so workers rely on consistent paths."""

        data_in_str = str(data_path)

        if os.name == "nt" and data_in_str.startswith("\\\\"):
            candidate = Path(PureWindowsPath(data_in_str))
        else:
            candidate = Path(data_in_str).expanduser()
            if not candidate.is_absolute():
                candidate = (Path.home() / candidate).expanduser()
            try:
                candidate = candidate.resolve(strict=False)
            except OSError:
                candidate = Path(os.path.normpath(str(candidate)))

        if os.name == "nt":
            resolved_str = os.path.normpath(str(candidate))
            if not BaseWorker._is_managed_pc:
                parts = Path(resolved_str).parts
                if "Users" in parts:
                    mapped = Path(*parts[parts.index("Users") + 2 :])
                else:
                    mapped = Path(resolved_str)
                net_path = normalize_path(f"\\\\127.0.0.1\\{mapped}")
                try:
                    cmd = f'net use Z: "{net_path}" /user:your-credentials'
                    logger.info(cmd)
                    subprocess.run(cmd, shell=True, check=True)
                except (OSError, subprocess.CalledProcessError) as exc:
                    logger.info("Failed to map network drive: %s", exc)
            return resolved_str

        return candidate.as_posix()

    def setup_data_directories(
        self,
        *,
        source_path: str | Path,
        target_path: str | Path | None = None,
        target_subdir: str = "dataframe",
        reset_target: bool = False,
    ) -> SimpleNamespace:
        """Prepare normalised input/output dataset paths without relying on worker args.

        Returns a namespace with the resolved input path (`input_path`), the normalised
        string used by downstream readers (`normalized_input`), the output directory
        as a ``Path`` (`output_path`), and its normalised string representation
        (`normalized_output`). Optionally clears and recreates the output directory.
        """

        if source_path is None:
            raise ValueError("setup_data_directories requires a source_path value")

        env = self.env
        input_path = type(self)._resolve_data_dir(env, source_path)

        normalized_input = self.normalize_dataset_path(input_path)

        base_parent = input_path.parent
        if target_path is None:
            output_path = base_parent / target_subdir
        else:
            candidate = Path(str(target_path)).expanduser()
            if not candidate.is_absolute():
                share_root = type(self)._share_root_path(env)
                has_nested_segments = len(candidate.parts) > 1
                if has_nested_segments:
                    anchor = share_root or base_parent.parent or base_parent
                else:
                    anchor = base_parent
                candidate = (Path(anchor) / candidate).expanduser()
            try:
                output_path = candidate.resolve(strict=False)
            except (OSError, RuntimeError):
                output_path = Path(os.path.normpath(str(candidate)))

        normalized_output = normalize_path(output_path)
        if os.name != "nt":
            normalized_output = normalized_output.replace("\\", "/")

        def _ensure_output_dir(path: str | Path) -> Path:
            path_obj = Path(path).expanduser()
            try:
                logger.info(f"mkdir {path_obj}")
                path_obj.mkdir(parents=True, exist_ok=True)
                return path_obj
            except (OSError, TypeError, ValueError) as exc:
                raise OSError(f"Failed to create output directory {path_obj}: {exc}") from exc

        try:
            if reset_target:
                try:
                    shutil.rmtree(normalized_output, ignore_errors=True, onerror=self._onerror)
                except (OSError, RuntimeError) as exc:
                    logger.info("Error removing directory: %s", exc)
            output_path = _ensure_output_dir(normalized_output)
            normalized_output = normalize_path(output_path)
            if os.name != "nt":
                normalized_output = normalized_output.replace("\\", "/")
        except OSError:
            fallback_base = None
            if env:
                if env.AGI_LOCAL_SHARE:
                    fallback_base = Path(env.AGI_LOCAL_SHARE).expanduser()
                else:
                    fallback_base = Path(env.home_abs)
            if fallback_base is None:
                fallback_base = Path.home()
            fallback_target = env.target if env else Path(normalized_output).name
            fallback = fallback_base / fallback_target
            try:
                fallback = _ensure_output_dir(fallback / target_subdir)
                normalized_output = normalize_path(fallback)
                if os.name != "nt":
                    normalized_output = normalized_output.replace("\\", "/")
                logger.warning(
                    "Output path %s unavailable; using fallback %s",
                    output_path if 'output_path' in locals() else normalized_output,
                    normalized_output,
                )
            except OSError as exc:
                logger.error("Fallback output directory failed: %s", exc)
                raise

        # Preserve compatibility with workers that rely on these attributes.
        self.home_rel = input_path
        self.data_out = normalized_output

        return SimpleNamespace(
            input_path=input_path,
            normalized_input=normalized_input,
            output_path=output_path,
            normalized_output=normalized_output,
        )

    @staticmethod
    def _join(path1, path2):
        # path to data base on symlink Path.home()/data(symlink)
        """
        Join two file paths.

        Args:
            path1 (str): The first file path.
            path2 (str): The second file path.

        Returns:
            str: The combined file path.

        Raises:
            None
        """
        path = os.path.join(BaseWorker.expand(path1), path2)

        if os.name != "nt":
            path = path.replace("\\", "/")
        return path

    @staticmethod
    def _get_logs_and_result(func, *args, verbosity=logging.CRITICAL, **kwargs):
        return runtime_support.capture_logs_and_result(
            func,
            *args,
            verbosity=verbosity,
            **kwargs,
        )

    @staticmethod
    def _exec(cmd, path, worker):
        """execute a command within a subprocess

        Args:
          cmd: the str of the command
          path: the path where to lunch the command
          worker:
        Returns:
        """
        return runtime_support.exec_command(
            cmd,
            path,
            worker,
            normalize_path_fn=normalize_path,
            logger_obj=logger,
        )

    @staticmethod
    def _log_import_error(module, target_class, target_module):
        runtime_support.log_import_error(
            module,
            target_class,
            target_module,
            logger_obj=logger,
            file_path=__file__,
            sys_path=sys.path,
        )

    @staticmethod
    def _load_module(module_name, module_class):
        return runtime_support.load_module(module_name, module_class)

    @staticmethod
    def _load_manager():
        return runtime_support.load_manager(
            BaseWorker.env,
            load_module_fn=BaseWorker._load_module,
            sys_modules=sys.modules,
        )

    @staticmethod
    def _load_worker(mode):
        return runtime_support.load_worker(
            BaseWorker.env,
            mode,
            load_module_fn=BaseWorker._load_module,
            sys_modules=sys.modules,
        )

    @staticmethod
    def _is_cython_installed(env):
        return runtime_support.is_cython_installed(env)

    @staticmethod
    async def _run(env=None, workers={"127.0.0.1": 1}, mode=0, verbose=None, args=None):
        """
        :param app:
        :param workers:
        :param mode:
        :param verbose:
        :param args:
        :return:
        """
        if not env:
            env = BaseWorker.env
        else:
            BaseWorker.env

        def _load_dispatcher():
            from .agi_dispatcher import WorkDispatcher  # Local import to avoid circular dependency

            return WorkDispatcher

        return await execution_support.run_worker(
            env=env,
            workers=workers,
            mode=mode,
            args=args,
            do_works_fn=BaseWorker._do_works,
            dispatcher_loader=_load_dispatcher,
            sys_path=sys.path,
            logger_obj=logger,
            traceback_module=traceback,
            time_module=time,
            humanize_module=humanize,
            datetime_module=datetime,
            path_cls=Path,
        )

    @staticmethod
    def _onerror(func, path, exc_info):
        """
        Error handler for `shutil.rmtree`.
        If it’s a permission error, make it writable and retry.
        Otherwise re-raise.
        """
        exc_type, exc_value, _ = exc_info

        # handle permission errors or any non-writable path
        if exc_type is PermissionError or not os.access(path, os.W_OK):
            try:
                os.chmod(path, stat.S_IWUSR | stat.S_IREAD)
                func(path)
            except OSError as e:
                logger.error(f"warning failed to grant write access to {path}: {e}")
        else:
            # not a permission problem—re-raise so you see real errors
            raise exc_value

    @staticmethod
    def _new(
            env: AgiEnv=None,
            app: str=None,
            mode: int=0,
            verbose: int=0,
            worker_id: int=0,
            worker: str="localhost",
            args: dict=None,
    ):
        """new worker instance
        Args:
          module: instanciate and load target mycode_worker module
          target_worker:
          target_worker_class:
          target_package:
          mode: (Default value = mode)
          verbose: (Default value = 0)
          worker_id: (Default value = 0)
          worker: (Default value = 'localhost')
          args: (Default value = None)
        Returns:
        """
        execution_support.initialize_worker(
            env=env,
            app=app,
            mode=mode,
            verbose=verbose,
            worker_id=worker_id,
            worker=worker,
            args=args,
            base_worker_cls=BaseWorker,
            agi_env_factory=AgiEnv,
            ensure_managed_pc_share_dir_fn=BaseWorker._ensure_managed_pc_share_dir,
            load_worker_fn=BaseWorker._load_worker,
            start_fn=BaseWorker.start,
            args_namespace_cls=ArgsNamespace,
            logger_obj=logger,
            time_module=time,
            traceback_module=traceback,
            sys_module=sys,
            file_path=__file__,
            path_cls=Path,
        )

    @staticmethod
    def _get_worker_info(worker_id):
        """def get_worker_info():

        Args:
          worker_id:
        Returns:
        """
        return execution_support.collect_worker_info(
            share_path=BaseWorker._share_path,
            worker=BaseWorker._worker,
            normalize_path_fn=normalize_path,
            logger_obj=logger,
            psutil_module=psutil,
            tempfile_module=tempfile,
            os_module=os,
            time_module=time,
        )

    @staticmethod
    def _build(target_worker, dask_home, worker, mode=0, verbose=0):
        """
        Function to build target code on a target Worker.

        Args:
            target_worker (str): module to build
            dask_home (str): path to dask home
            worker: current worker
            mode: (Default value = 0)
            verbose: (Default value = 0)
        """
        execution_support.build_worker_artifacts(
            target_worker=target_worker,
            dask_home=dask_home,
            worker=worker,
            mode=mode,
            verbose=verbose,
            base_worker_cls=BaseWorker,
            logger_obj=logger,
            getuser_fn=getpass.getuser,
            file_path=__file__,
            sys_path=sys.path,
            path_cls=Path,
            os_module=os,
            shutil_module=shutil,
        )

    @staticmethod
    def _expand_chunk(payload, worker_id):
        """Unwrap per-worker payload chunk back into legacy list form."""

        if not isinstance(payload, dict) or not payload.get("__agi_worker_chunk__"):
            return payload, None, None

        chunk = payload.get("chunk", [])
        total_workers = payload.get("total_workers")
        worker_idx = payload.get("worker_idx", worker_id if worker_id is not None else 0)

        if isinstance(total_workers, int) and total_workers > 0:
            reconstructed_len = max(total_workers, worker_idx + 1)
        else:
            reconstructed_len = worker_idx + 1

        def _placeholder():
            if isinstance(chunk, list):
                return []
            if isinstance(chunk, dict):
                return {}
            return None

        reconstructed = [_placeholder() for _ in range(reconstructed_len)]
        if worker_idx >= len(reconstructed):
            reconstructed.extend(
                _placeholder() for _ in range(worker_idx - len(reconstructed) + 1)
            )
        reconstructed[worker_idx] = chunk

        chunk_len = len(chunk) if hasattr(chunk, "__len__") else (1 if chunk else 0)
        return reconstructed, chunk_len, reconstructed_len

    @staticmethod
    def _do_works(workers_plan, workers_plan_metadata):
        """run of workers

        Args:
          workers_plan: distribution tree
          workers_plan_metadata:
        Returns:
            logs: str, the log output from this worker
        """
        return execution_support.execute_worker_plan(
            workers_plan=workers_plan,
            workers_plan_metadata=workers_plan_metadata,
            worker_id=BaseWorker._worker_id,
            worker_name=BaseWorker._worker,
            insts=BaseWorker._insts,
            expand_chunk_fn=BaseWorker._expand_chunk,
            logger_obj=logger,
            traceback_module=traceback,
            file_path=__file__,
            path_cls=Path,
        )



# enable dotted access ``BaseWorker.break()`` even though ``break`` is a keyword
setattr(BaseWorker, "break", BaseWorker.break_loop)
class ArgsNamespace(SimpleNamespace):
    """Namespace that supports both attribute and key-style access."""

    def __getitem__(self, key):
        try:
            return getattr(self, key)
        except AttributeError as exc:
            raise KeyError(key) from exc

    def get(self, key, default=None):
        return getattr(self, key, default)

    def __contains__(self, key):
        return hasattr(self, key)

    def to_dict(self):
        return dict(self.__dict__)
