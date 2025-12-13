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
import uuid
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

from agi_env.agi_logger import AgiLogger

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
        env = env or cls.env
        if env is None or not env._is_managed_pc:
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
        if env is None:
            return
        if not env._is_managed_pc:
            return

        home = Path.home()
        managed_root = home / cls.managed_pc_home_suffix

        agi_share_path = env.agi_share_path
        if agi_share_path is None:
            return

        try:
            env.agi_share_path = Path(
                str(Path(agi_share_path)).replace(str(home), str(managed_root))
            )
        except Exception:  # pragma: no cover - defensive guard
            logger.debug(
                "Failed to remap agi_share_path for managed PC", exc_info=True
            )

    @classmethod
    def _normalized_path(cls, value: Path | str) -> Path:
        path_obj = Path(value)
        try:
            return Path(normalize_path(path_obj)).expanduser()
        except Exception:
            return path_obj.expanduser()

    @staticmethod
    def _share_root_path(env: AgiEnv | None) -> Path | None:
        if env is None:
            return None

        try:
            base = Path(env.share_root_path()).expanduser()
            if base:
                return base
        except Exception:  # pragma: no cover - defensive guard
            logger.debug("share_root_path() failed; falling back to legacy resolution", exc_info=True)

        candidates = (
            env.agi_share_path_abs,
            env.agi_share_path,
        )
        for candidate in candidates:
            if candidate:
                base = Path(candidate).expanduser()
                if not base.is_absolute():
                    home = Path(env.home_abs).expanduser()
                    base = (home / base).expanduser()
                return base
        return Path(env.home_abs).expanduser()

    @classmethod
    def _resolve_data_dir(
        cls,
        env: AgiEnv | None,
        data_path: Path | str | None,
    ) -> Path:
        """Resolve ``data_in`` style values relative to the current environment."""

        if data_path is None:
            raise ValueError("data_path must be provided to resolve a dataset directory")

        raw = Path(str(data_path)).expanduser()
        if not raw.is_absolute():
            base = cls._share_root_path(env) or Path.home()
            raw = Path(base).expanduser() / raw

        remapped = cls._remap_managed_pc_path(raw, env=env)
        try:
            resolved = cls._normalized_path(remapped)
        except Exception:
            resolved = remapped.expanduser()

        try:
            return resolved.resolve(strict=False)
        except Exception:
            return Path(os.path.normpath(str(resolved)))

    @staticmethod
    def _relative_to_user_home(path: Path) -> Path | None:
        parts = path.parts
        if len(parts) >= 3 and parts[1].lower() in {"users", "home"}:
            return Path(*parts[3:]) if len(parts) > 3 else Path()
        return None

    @staticmethod
    def _remap_user_home(path: Path, *, username: str) -> Path | None:
        parts = path.parts
        if len(parts) < 3:
            return None
        root_marker = parts[1].lower()
        if root_marker not in {"users", "home"}:
            return None
        root = Path(parts[0]) if parts[0] else Path("/")
        base = root / parts[1] / username
        remainder = Path(*parts[3:]) if len(parts) > 3 else Path()
        candidate = base / remainder if remainder else base
        return candidate

    @staticmethod
    def _strip_share_prefix(path: Path, aliases: set[str]) -> Path:
        parts = path.parts
        if parts and parts[0] in aliases:
            return Path(*parts[1:]) if len(parts) > 1 else Path()
        return path

    @staticmethod
    def _can_create_path(path: Path) -> bool:
        target_dir = path
        if target_dir.suffix:
            target_dir = target_dir.parent
        probe = target_dir / f".agi_perm_{uuid.uuid4().hex}"
        try:
            logger.info(f"mkdir {target_dir}")
            target_dir.mkdir(parents=True, exist_ok=True)
            probe.touch(exist_ok=False)
        except (PermissionError, FileNotFoundError, OSError):
            return False
        else:
            return True
        finally:
            with suppress(Exception):
                probe.unlink()

    @staticmethod
    def _collect_share_aliases(
        env: AgiEnv | None, share_base: Path
    ) -> set[str]:
        aliases = {share_base.name, "data", "clustershare", "datashare"}
        if env:
            if env.AGILAB_SHARE_HINT:
                hint_path = Path(str(env.AGILAB_SHARE_HINT))
                parts = [p for p in hint_path.parts if p not in {"", "."}]
                aliases.update(parts[-2:])
            if env.AGILAB_SHARE_REL:
                try:
                    aliases.add(Path(env.AGILAB_SHARE_REL).name)
                except Exception:
                    pass
            if env.agi_share_path:
                try:
                    aliases.add(Path(env.agi_share_path).name)
                except Exception:
                    pass
        return {alias for alias in aliases if alias}


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
            logger.info(f"mkdir {target}")
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
            except Exception:
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
                logger.info(cmd)
                subprocess.run(cmd, shell=True, check=True)
            except Exception as e:
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
            except Exception:
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
            except Exception as exc:
                raise OSError(f"Failed to create output directory {path_obj}: {exc}") from exc

        try:
            if reset_target:
                try:
                    shutil.rmtree(normalized_output, ignore_errors=True, onerror=self._onerror)
                except Exception as exc:
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
            except Exception as exc:
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
        import io
        import logging

        log_stream = io.StringIO()
        handler = logging.StreamHandler(log_stream)
        root_logger = logging.getLogger()

        # Set level according to verbosity
        if verbosity >= 2:
            level = logging.DEBUG
        elif verbosity == 1:
            level = logging.INFO
        else:
            level = logging.WARNING

        root_logger.setLevel(level)
        root_logger.addHandler(handler)

        try:
            result = func(*args, **kwargs)
        finally:
            root_logger.removeHandler(handler)

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
                logger.error(f"warning: worker {worker} - {cmd}")
                logger.error(result.stderr)
            else:
                raise RuntimeError(
                    f"error on node {worker} - {cmd} {result.stderr}"
                )

        return result

    @staticmethod
    def _log_import_error(module, target_class, target_module):
        logger.error(f"file:  {__file__}")
        logger.error(f"__import__('{module}', fromlist=['{target_class}'])")
        logger.error(f"getattr('{target_module} {target_class}')")
        logger.error(f"sys.path: {sys.path}")

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
                logger.info(f"warning: no cython library found at {lib_path}")
                raise RuntimeError("Cython mode requested but no compiled library found")

            # Some workers rely on sibling worker distributions when loading optional
            # Cython helpers. Ensure those dist folders are importable so helper imports
            # succeed even if the package is only present as a sibling wenv.
            sibling_root = wenv_abs.parent
            if sibling_root.is_dir():
                for extra_dist in sibling_root.glob("*_worker/dist"):
                    try:
                        extra_path = str(extra_dist.resolve())
                    except FileNotFoundError:
                        continue
                    if extra_path and extra_path not in sys.path:
                        sys.path.append(extra_path)


        try:
            from .agi_dispatcher import WorkDispatcher  # Local import to avoid circular dependency

            workers, workers_plan, workers_plan_metadata = await WorkDispatcher._do_distrib(env, workers, args)
        except Exception as err:
            logger.error(traceback.format_exc())
            if isinstance(err, RuntimeError):
                raise
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
        try:

            logger.info(f"venv: {sys.prefix}")
            logger.info(f"worker #{worker_id}: {worker} from: {Path(__file__)}")

            if env:
                BaseWorker.env = env
            else:
                BaseWorker.env = AgiEnv(app=app, verbose=verbose)
            BaseWorker._ensure_managed_pc_share_dir(BaseWorker.env)

            # import of derived Class of WorkDispatcher, name target_inst which is typically an instance of MyCode
            worker_class = BaseWorker._load_worker(mode)

            # Instantiate the class with arguments
            worker_inst = worker_class()
            worker_inst._mode = mode
            args_namespace = ArgsNamespace(**(args or {}))
            worker_inst.args = args_namespace
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
            logger.info(f"worker #{worker_id}: {worker} starting...")
            BaseWorker.start(worker_inst)

        except Exception as e:
            logger.error(traceback.format_exc())
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
            logger.info(f"mkdir {path}")
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

        logger.info(
            f"worker #{BaseWorker._worker_id}: {worker} from: {Path(__file__)}"
        )

        try:
            logger.info("set verbose=3 to see something in this trace file ...")

            if verbose > 2:
                logger.info(f"home_dir: {BaseWorker._home_dir}")
                logger.info(
                    f"target_worker={target_worker}, dask_home={dask_home}, mode={mode}, verbose={verbose}, worker={worker})"
                )
                for x in Path(dask_home).glob("*"):
                    logger.info(f"{x}")

            # Exemple supposé : définir egg_src (non défini dans ton code)
            egg_src = dask_home + "/some_egg_file"  # adapte selon contexte réel

            extract_path = BaseWorker._home_dir / "wenv" / target_worker
            extract_src = extract_path / "src"

            if not mode & 2:
                egg_dest = extract_path / (os.path.basename(egg_src) + ".egg")

                logger.info(f"copy: {egg_src} to {egg_dest}")
                shutil.copyfile(egg_src, egg_dest)

                if str(egg_dest) in sys.path:
                    sys.path.remove(str(egg_dest))
                sys.path.insert(0, str(egg_dest))

                logger.info("sys.path:")
                for x in sys.path:
                    logger.info(f"{x}")

                logger.info("done!")

        except Exception as err:
            logger.error(
                f"worker<{worker}> - fail to build {target_worker} from {dask_home}, see {BaseWorker._logs} for details"
            )
            raise err

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
        import logging as py_logging

        log_stream = io.StringIO()
        handler = py_logging.StreamHandler(log_stream)
        root_logger = py_logging.getLogger()

        # Avoid adding duplicate handlers
        already_has_handler = any(
            isinstance(h, py_logging.StreamHandler) and getattr(h, "stream", None) is log_stream
            for h in root_logger.handlers
        )
        if not already_has_handler:
            root_logger.addHandler(handler)

        try:
            worker_id = BaseWorker._worker_id
            if worker_id is not None:
                expanded_plan, plan_chunk_len, plan_total_workers = BaseWorker._expand_chunk(
                    workers_plan, worker_id
                )
                expanded_meta, meta_chunk_len, _ = BaseWorker._expand_chunk(
                    workers_plan_metadata, worker_id
                )

                if expanded_plan is None:
                    expanded_plan = workers_plan
                if expanded_meta is None:
                    expanded_meta = workers_plan_metadata

                plan_entry = (
                    expanded_plan[worker_id]
                    if isinstance(expanded_plan, list)
                    and len(expanded_plan) > worker_id
                    else []
                )
                metadata_entry = (
                    expanded_meta[worker_id]
                    if isinstance(expanded_meta, list)
                    and len(expanded_meta) > worker_id
                    else []
                )

                logger.info(
                    f"worker #{worker_id}: {BaseWorker._worker} from {Path(__file__)}"
                )
                logger.info(
                    "work #%s / %s - plan batches=%s metadata batches=%s",
                    worker_id + 1,
                    plan_total_workers
                    if plan_total_workers is not None
                    else (len(expanded_plan) if isinstance(expanded_plan, list) else "?"),
                    plan_chunk_len if plan_chunk_len is not None else len(plan_entry),
                    meta_chunk_len if meta_chunk_len is not None else len(metadata_entry),
                )

                BaseWorker._insts[worker_id].works(expanded_plan, expanded_meta)

                logger.info(
                    "worker #%s completed %s plan batches",
                    worker_id,
                    plan_chunk_len if plan_chunk_len is not None else len(plan_entry),
                )
            else:
                logger.error("this worker is not initialized")
                raise Exception("failed to do_works")

        except Exception as e:
            logger.error(traceback.format_exc())
            raise
        finally:
            root_logger.removeHandler(handler)

        # Return the logs
        return log_stream.getvalue()



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
