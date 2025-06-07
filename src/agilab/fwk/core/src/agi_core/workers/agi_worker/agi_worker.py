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
agi_worker module

    Auteur: Jean-Pierre Morard

"""

######################################################
# Agi Framework call back functions
######################################################
# Internal Libraries:
import getpass
import io
import os
import shutil
import sys
import stat
import tempfile
import time
import sysconfig
import subprocess
import warnings
import abc
import traceback

# External Libraries:
from contextlib import redirect_stdout
from distutils.sysconfig import get_python_lib
from pathlib import Path, PureWindowsPath, PurePosixPath
from zipfile import ZipFile
import psutil
import parso
import humanize
from datetime import timedelta
from agi_env import AgiEnv, normalize_path
from agi_core.managers.agi_manager import AgiManager
import logging

warnings.filterwarnings("ignore")
logger = logging.getLogger(__name__)

class AgiWorker(abc.ABC):
    """
    class AgiWorker v1.0
    """

    _insts = {}
    _built = None
    _pool_init = None
    _work_pool = None
    share_path = None
    verbose = 1
    mode = None
    env = None
    worker_id = None
    worker = None
    home_dir = None
    logs = None
    dask_home = None
    worker = None
    t0 = None
    is_managed_pc = getpass.getuser().startswith("T0")
    cython_decorators = ["njit"]

    def start(self):
        """
        Start the worker and print out a message if verbose mode is enabled.

        Args:
            None

        Returns:
            None
        """
        """ """
        logging.info(
            f"AgiWorker.start - worker #{AgiWorker.worker_id}: {AgiWorker.worker} - mode: {self.mode}")
        self.start()

    def stop(self):
        """
        Returns:
        """
        logging.info(f"stop - worker #{self.worker_id}: {self.worker} - mode: {self.mode}"
                        )

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
        if os.name == "nt" and not AgiWorker.is_managed_pc:
            path = Path(path1)
            parts = path.parts
            if "Users" in parts:
                index = parts.index("Users") + 2
                path = Path(*parts[index:])
            net_path = AgiWorker.normalize_path("\\\\127.0.0.1\\" + str(path))
            try:
                # your nfs account in order to mount it as net drive on windows
                cmd = f'net use Z: "{net_path}" /user:your-name your-password'
                logging.info(cmd)
                subprocess.run(cmd, shell=True, check=True)
            except Exception as e:
                logging.error(f"Mount failed: {e}")
        return AgiWorker.join(AgiWorker.expand(path1), path2)

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
    def join(path1, path2):
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
        path = os.path.join(AgiWorker.expand(path1), path2)

        if os.name != "nt":
            path = path.replace("\\", "/")
        return path

       # dans agi_worker.py (en dehors de la classe AgiWorker)
    def get_logs_and_result(func, *args, verbosity=logging.CRITICAL, **kwargs):
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
    def exec(cmd, path, worker):
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
                    f"error on agi_worker {worker} - {cmd} {result.stderr}"
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
        module = __import__(module_name, fromlist=[module_class])
        return getattr(module, module_class)

    @staticmethod
    def _load_manager():
        env = AgiWorker.env
        module_name = env.module
        module_class = env.target_class
        module_name += '.' + module_name
        if module_name in sys.modules:
            del sys.modules[module_name]
        return AgiWorker._load_module(module_name, module_class)

    @staticmethod
    def _load_worker(mode):
        env = AgiWorker.env
        module_name = env.target_worker
        module_class = env.target_worker_class
        if module_name in sys.modules:
            del sys.modules[module_name]
        if mode & 2:
            module_name += "_cy"
        else:
            module_name += '.' + module_name

        return AgiWorker._load_module(module_name, module_class)

    @staticmethod
    def run(workers={"127.0.0.1": 1}, mode=0, env=None, verbose=None, args=None):
        """
        :param app:
        :param workers:
        :param mode:
        :param verbose:
        :param args:
        :return:
        """
        if not env:
            env = AgiWorker.env
        else:
            AgiWorker.env = env

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
                exit(0)

        target_class = AgiWorker._load_manager()

        # Instantiate the class with arguments
        target_inst = target_class(env, **args)

        try:
            workers, workers_tree, workers_tree_info = AgiManager.do_distrib(
                target_inst, env, workers
            )
        except Exception as err:
            logging.error(traceback.format_exc())
            sys.exit(1)

        if mode == 48:
            return workers_tree

        t = time.time()
        AgiWorker.do_works(workers_tree, workers_tree_info)
        runtime = time.time() - t
        env._run_time = runtime

        return f"{env.mode2str(mode)} {humanize.precisedelta(timedelta(seconds=runtime))}"

    @staticmethod
    def onerror(func, path, exc_info):
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
    def new(
            app,
            mode=mode,
            env=None,
            verbose=0,
            worker_id=0,
            worker="localhost",
            args=None,
    ):
        """new worker instance
        Args:
          module: instanciate and load target my_code_worker module
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
            if not env:
                install_type = 1 if worker.startswith("localhost") or worker.startswith("127.0.0.1") else 2
                AgiWorker.env = AgiEnv(active_app=app, install_type=install_type, verbose=verbose)
            else:
                AgiWorker.env = env

            logging.info(f"venv: {sys.prefix}")
            logging.info(f"AgiWorker.new - worker #{worker_id}: {worker} from: {os.path.relpath(__file__)}")

            # import of derived Class of AgiManager, name target_inst which is typically an instance of MyCode
            worker_class = AgiWorker._load_worker(mode)

            # Instantiate the class with arguments
            worker_inst = worker_class()
            worker_inst.mode = mode
            worker_inst.args = args
            worker_inst.verbose = verbose

            # Instantiate the base class
            AgiWorker.verbose = verbose
            # AgiWorker._pool_init = worker_inst.pool_init
            # AgiWorker._work_pool = worker_inst.work_pool
            AgiWorker._insts[worker_id] = worker_inst
            AgiWorker._built = False
            AgiWorker.worker = Path(worker).name
            AgiWorker.worker_id = worker_id
            AgiWorker.t0 = time.time()
            AgiWorker.start(worker_inst)

        except Exception as e:
            traceback.print_exc()
            raise

    @staticmethod
    def get_worker_info(worker_id):
        """def get_worker_info():

        Args:
          worker_id:
        Returns:
        """

        worker = AgiWorker.worker

        # Informations sur la RAM
        ram = psutil.virtual_memory()
        ram_total = [ram.total / 10 ** 9]
        ram_available = [ram.available / 10 ** 9]

        # Nombre de CPU
        cpu_count = [psutil.cpu_count()]

        # Fréquence de l'horloge du CPU
        cpu_frequency = [psutil.cpu_freq().current / 10 ** 3]

        # Vitesse du réseau
        # path = AgiWorker.share_path
        if not AgiWorker.share_path:
            path = tempfile.gettempdir()
        else:
            path = normalize_path(AgiWorker.share_path)
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
    def build(target_worker, dask_home, worker, mode=0, verbose=0):
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
        AgiWorker.home_dir = Path(prefix).expanduser().absolute()
        AgiWorker.logs = AgiWorker.home_dir / f"{target_worker}_trace.txt"
        AgiWorker.dask_home = dask_home
        AgiWorker.worker = worker

        logging.info(
            f"build - worker #{AgiWorker.worker_id}: {worker} from: {os.path.relpath(__file__)}"
        )

        try:
            logging.info("set verbose=3 to see something in this trace file ...")

            if verbose > 2:
                logging.info("starting worker_build ...")
                logging.info(f"home_dir: {AgiWorker.home_dir}")
                logging.info(
                    f"worker_build(target_worker={target_worker}, dask_home={dask_home}, mode={mode}, verbose={verbose}, worker={worker})"
                )
                for x in Path(dask_home).glob("*"):
                    logging.info(f"{x}")

            # Exemple supposé : définir egg_src (non défini dans ton code)
            egg_src = dask_home + "/some_egg_file"  # adapte selon contexte réel

            extract_path = AgiWorker.home_dir / "wenv" / target_worker
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
                f"worker<{worker}> - fail to build {target_worker} from {dask_home}, see {AgiWorker.logs} for details"
            )
            raise err

    @staticmethod
    def do_works(workers_tree, workers_tree_info):
        """run of workers

        Args:
          chunk: distribution tree
          chunks:
        Returns:
        """
        try:
            worker_id = AgiWorker.worker_id
            if worker_id is not None:
                logging.info(f"do_works - worker #{worker_id}: {AgiWorker.worker} from {os.path.relpath(__file__)}")
                logging.info(f"AgiWorker.work - #{worker_id + 1} / {len(workers_tree)}")
                AgiWorker._insts[worker_id].works(workers_tree, workers_tree_info)
            else:
                logging.error(f"this worker is not initialized")
                raise Exception(f"failed to do_works")

        except Exception as e:
            import traceback
            traceback.print_exc()
            raise