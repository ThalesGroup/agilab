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
import getpass
import inspect
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import warnings
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
from typing import Any, Callable, ClassVar, Dict, List, Optional, Union

# External Libraries:
import numpy as np
from distutils.sysconfig import get_python_lib
import psutil
import humanize
import datetime
import logging
from copy import deepcopy

from agi_env import AgiEnv, normalize_path

logger = logging.getLogger(__name__)
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
        env = env or getattr(cls, "env", None)
        if not getattr(env, "_is_managed_pc", AgiEnv._is_managed_pc):
            return Path(value)

        home = Path.home()
        managed_root = home / cls.managed_pc_home_suffix

        try:
            return Path(str(Path(value)).replace(str(home), str(managed_root)))
        except Exception:  # pragma: no cover - defensive guard
            logger.debug("Failed to remap path %s for managed PC", value, exc_info=True)
            return Path(value)

    @classmethod
    def _apply_managed_pc_path_overrides(
        cls,
        args: Any,
        *,
        env: AgiEnv | None = None,
    ) -> Any:
        fields = getattr(cls, "managed_pc_path_fields", ())
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
            except Exception as exc:  # pragma: no cover - defensive guard
                logger.warning(
                    "Issue while cleaning output directory %s: %s", target, exc
                )

        try:
            target.mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # pragma: no cover - defensive guard
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
            logging.info(
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
            logging.error("Worker start hook failed:\n%s", traceback.format_exc())
            raise

    def stop(self):
        """
        Returns:
        """
        logging.info(f"worker #{self._worker_id}: {self._worker} - mode: {self._mode}"
                        )
        with BaseWorker._service_lock:
            is_active = BaseWorker._service_active.get(self._worker_id)
        if is_active:
            try:
                BaseWorker.break_loop()
            except Exception:
                logging.debug("break_loop raised", exc_info=True)

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

        poll = BaseWorker._service_poll_default if poll_interval is None else max(poll_interval, 0.0)
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

        start_time = time.time()
        logger.info(
            "worker #%s: %s entering service loop (poll %.3fs)",
            worker_id,
            BaseWorker._worker,
            poll,
        )

        try:
            if not callable(loop_fn):
                # No custom loop provided; block until break is requested.
                stop_event.wait()
                return {"status": "idle", "runtime": 0.0}

            def _run_once() -> Any:
                if accepts_event:
                    return loop_fn(stop_event)
                return loop_fn()

            while not stop_event.is_set():
                result = _run_once()
                if inspect.isawaitable(result):
                    try:
                        asyncio.run(result)
                    except RuntimeError:
                        loop = asyncio.new_event_loop()
                        try:
                            loop.run_until_complete(result)
                        finally:
                            loop.close()

                if result is False:
                    break

                if accepts_event:
                    # Worker manages its own waiting when it handles the stop event.
                    continue

                if poll > 0:
                    stop_event.wait(poll)

            return {"status": "stopped", "runtime": time.time() - start_time}

        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("Service loop failed: %s", exc)
            raise

        finally:
            with BaseWorker._service_lock:
                BaseWorker._service_active.pop(worker_id, None)
                BaseWorker._service_stop_events.pop(worker_id, None)

            stop_hook = getattr(worker_inst, "stop", None)
            if callable(stop_hook):
                try:
                    stop_hook()
                except Exception:  # pragma: no cover - defensive logging
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
                logging.info(cmd)
                subprocess.run(cmd, shell=True, check=True)
            except Exception as e:
                logging.error(f"Mount failed: {e}")
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
    def normalize_data_uri(data_uri: Union[str, Path]) -> str:
        """Normalise a data URI so workers can rely on consistent paths."""

        data_uri_str = str(data_uri)

        if os.name == "nt" and data_uri_str.startswith("\\\\"):
            candidate = Path(PureWindowsPath(data_uri_str))
        else:
            candidate = Path(data_uri_str).expanduser()
            if not candidate.is_absolute():
                candidate = (Path.home() / candidate).expanduser()
            try:
                candidate = candidate.resolve(strict=False)
            except Exception:
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
                except Exception as exc:
                    logger.info("Failed to map network drive: %s", exc)
            return resolved_str

        return candidate.as_posix()

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
        import io
        import logging

        log_stream = io.StringIO()
        handler = logging.StreamHandler(log_stream)
        logger = logging.getLogger()

        if verbosity >= 2:
            level = logging.DEBUG
        elif verbosity == 1:
            level = logging.INFO
        else:
            level = logging.WARNING

        logger.setLevel(level)
        logger.addHandler(handler)

        try:
            result = func(*args, **kwargs)
        finally:
            logger.removeHandler(handler)

        return log_stream.getvalue(), result


    @staticmethod
    def _exec(cmd, path, worker):
        """execute a command within a subprocess

        Args:
          cmd: the str of the command
          path: the path where to lunch the command
          worker:
        Returns:
        """
        import subprocess

        path = normalize_path(path)

        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, check=True, cwd=path
        )
        if result.returncode != 0:
            if result.stderr.startswith("WARNING"):
                logging.error(f"warning: worker {worker} - {cmd}")
                logging.error(result.stderr)
            else:
                raise RuntimeError(
                    f"error on node {worker} - {cmd} {result.stderr}"
                )

        return result

    @staticmethod
    def _log_import_error(module, target_class, target_module):
        logging.error(f"file:  {__file__}")
        logging.error(f"__import__('{module}', fromlist=['{target_class}'])")
        logging.error(f"getattr('{target_module} {target_class}')")
        logging.error(f"sys.path: {sys.path}")

    @staticmethod
    def _load_module(module_name, module_class):
        try:
            module = __import__(module_name, fromlist=[module_class])
        except ModuleNotFoundError:
            raise ModuleNotFoundError(f"module {module_name} is not installed")
        return getattr(module, module_class)

    @staticmethod
    def _load_manager():
        env = BaseWorker.env
        module_name = env.module
        module_class = env.target_class
        module_name += '.' + module_name
        if module_name in sys.modules:
            del sys.modules[module_name]
        return BaseWorker._load_module(module_name, module_class)

    @staticmethod
    def _load_worker(mode):
        env = BaseWorker.env
        module_name = env.target_worker
        module_class = env.target_worker_class
        if module_name in sys.modules:
            del sys.modules[module_name]
        if mode & 2:
            module_name += "_cy"
        else:
            module_name += '.' + module_name

        return BaseWorker._load_module(module_name, module_class)

    @staticmethod
    def _is_cython_installed(env):
        module_class = env.target_worker_class
        module_name = env.target_worker + "_cy"

        try:
           __import__(module_name, fromlist=[module_class])

        except ModuleNotFoundError:
            return False

        return True

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

        if mode & 2:
            wenv_abs = env.wenv_abs

            # Look for any files or directories in the Cython lib path that match the "*cy*" pattern.
            cython_libs = list((wenv_abs / "dist").glob("*cy*"))

            # If a Cython library is found, normalize its path and set it as lib_path.
            lib_path = (
                str(Path(cython_libs[0].parent).resolve()) if cython_libs else None
            )

            if lib_path:
                if lib_path not in sys.path:
                    sys.path.insert(0, lib_path)
            else:
                logging.info(f"warning: no cython library found at {lib_path}")
                raise RuntimeError("Cython mode requested but no compiled library found")


        try:
            from .agi_dispatcher import WorkDispatcher  # Local import to avoid circular dependency

            workers, workers_plan, workers_plan_metadata = await WorkDispatcher._do_distrib(env, workers, args)
        except Exception as err:
            logging.error(traceback.format_exc())
            raise RuntimeError("Failed to build distribution plan") from err

        if mode == 48:
            return workers_plan

        t = time.time()
        BaseWorker._do_works(workers_plan, workers_plan_metadata)
        runtime = time.time() - t
        env._run_time = runtime

        return f"{env.mode2str(mode)} {humanize.precisedelta(datetime.timedelta(seconds=runtime))}"

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
            except Exception as e:
                logging.error(f"warning failed to grant write access to {path}: {e}")
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
        try:

            logging.info(f"venv: {sys.prefix}")
            logging.info(f"worker #{worker_id}: {worker} from: {Path(__file__)}")

            if env:
                BaseWorker.env = env
            else:
                BaseWorker.env = AgiEnv(app=app, verbose=verbose)

            # import of derived Class of WorkDispatcher, name target_inst which is typically an instance of MyCode
            worker_class = BaseWorker._load_worker(mode)

            # Instantiate the class with arguments
            worker_inst = worker_class()
            worker_inst._mode = mode
            worker_inst.args = SimpleNamespace(**args)
            worker_inst.verbose = verbose

            # Instantiate the base class
            BaseWorker.verbose = verbose
            # BaseWorker._pool_init = worker_inst.pool_init
            # BaseWorker._work_pool = worker_inst.work_pool
            BaseWorker._insts[worker_id] = worker_inst
            BaseWorker._built = False
            BaseWorker._worker = Path(worker).name
            BaseWorker._worker_id = worker_id
            BaseWorker._t0 = time.time()
            logging.info(f"worker #{worker_id}: {worker} starting...")
            BaseWorker.start(worker_inst)

        except Exception as e:
            logging.error(traceback.format_exc())
            raise

    @staticmethod
    def _get_worker_info(worker_id):
        """def get_worker_info():

        Args:
          worker_id:
        Returns:
        """

        worker = BaseWorker._worker

        # Informations sur la RAM
        ram = psutil.virtual_memory()
        ram_total = [ram.total / 10 ** 9]
        ram_available = [ram.available / 10 ** 9]

        # Nombre de CPU
        cpu_count = [psutil.cpu_count()]

        # Fréquence de l'horloge du CPU
        cpu_frequency = [psutil.cpu_freq().current / 10 ** 3]

        # path = BaseWorker.share_path
        if not BaseWorker._share_path:
            path = tempfile.gettempdir()
        else:
            path = normalize_path(BaseWorker._share_path)
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)

        size = 10 * 1024 * 1024
        file = os.path.join(path, f"{worker}".replace(":", "_"))
        # start timer
        start = time.time()
        with open(file, "w") as af:
            af.write("\x00" * size)

        # how much time it took
        elapsed = time.time() - start
        time.sleep(1)
        write_speed = [size / elapsed]

        # delete the output-data file
        os.remove(file)

        # Retourner les informations sous forme de dictionnaire
        system_info = {
            "ram_total": ram_total,
            "ram_available": ram_available,
            "cpu_count": cpu_count,
            "cpu_frequency": cpu_frequency,
            "network_speed": write_speed,
        }

        return system_info

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

        # Log file dans le home_dir + nom du target_worker_trace.txt
        if str(getpass.getuser()).startswith("T0"):
            prefix = "~/MyApp/"
        else:
            prefix = "~/"
        BaseWorker._home_dir = Path(prefix).expanduser().absolute()
        BaseWorker._logs = BaseWorker._home_dir / f"{target_worker}_trace.txt"
        BaseWorker._dask_home = dask_home
        BaseWorker._worker = worker

        logging.info(
            f"worker #{BaseWorker._worker_id}: {worker} from: {Path(__file__)}"
        )

        try:
            logging.info("set verbose=3 to see something in this trace file ...")

            if verbose > 2:
                logging.info(f"home_dir: {BaseWorker._home_dir}")
                logging.info(
                    f"target_worker={target_worker}, dask_home={dask_home}, mode={mode}, verbose={verbose}, worker={worker})"
                )
                for x in Path(dask_home).glob("*"):
                    logging.info(f"{x}")

            # Exemple supposé : définir egg_src (non défini dans ton code)
            egg_src = dask_home + "/some_egg_file"  # adapte selon contexte réel

            extract_path = BaseWorker._home_dir / "wenv" / target_worker
            extract_src = extract_path / "src"

            if not mode & 2:
                egg_dest = extract_path / (os.path.basename(egg_src) + ".egg")

                logging.info(f"copy: {egg_src} to {egg_dest}")
                shutil.copyfile(egg_src, egg_dest)

                if str(egg_dest) in sys.path:
                    sys.path.remove(str(egg_dest))
                sys.path.insert(0, str(egg_dest))

                logging.info("sys.path:")
                for x in sys.path:
                    logging.info(f"{x}")

                logging.info("done!")

        except Exception as err:
            logging.error(
                f"worker<{worker}> - fail to build {target_worker} from {dask_home}, see {BaseWorker._logs} for details"
            )
            raise err

    @staticmethod
    def _do_works(workers_plan, workers_plan_metadata):
        """run of workers

        Args:
          workers_plan: distribution tree
          workers_plan_metadata:
        Returns:
            logs: str, the log output from this worker
        """
        log_stream = io.StringIO()
        handler = logging.StreamHandler(log_stream)
        logger = logging.getLogger()  # root logger; adjust if you use a named logger

        # Optionally, only add if not already present (avoid duplicate logs)
        already_has_handler = any(isinstance(h, logging.StreamHandler) and h.stream == log_stream for h in logger.handlers)
        if not already_has_handler:
            logger.addHandler(handler)

        try:
            worker_id = BaseWorker._worker_id
            if worker_id is not None:
                logging.info(f"worker #{worker_id}: {BaseWorker._worker} from {Path(__file__)}")
                logging.info(f"work #{worker_id + 1} / {len(workers_plan)}")
                BaseWorker._insts[worker_id].works(workers_plan, workers_plan_metadata)
            else:
                logging.error(f"this worker is not initialized")
                raise Exception(f"failed to do_works")

        except Exception as e:
            import traceback
            logging.error(traceback.format_exc())
            raise
        finally:
            logger.removeHandler(handler)

        # Return the logs
        return log_stream.getvalue()


# enable dotted access ``BaseWorker.break()`` even though ``break`` is a keyword
setattr(BaseWorker, "break", BaseWorker.break_loop)
