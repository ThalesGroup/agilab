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
from agi_env import AgiEnv
from agi_core.managers.agi_manager import AgiManager

warnings.filterwarnings("ignore")


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
        if self.verbose:
            print(
                f"AgiWorker.start - worker #{AgiWorker.worker_id}: {AgiWorker.worker} - mode: {self.mode}\n",
                end="",
                flush=True,
            )
        self.start()

    def stop(self):
        """
        Returns:
        """
        if self.verbose:
            print(
                f"stop - worker #{self.worker_id}: {self.worker} - mode: {self.mode}\n",
                end="",
                flush=True,
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
            net_path = AgiEnv.normalize_path("//127.0.0.1" + path1[6:])
            try:
                # your nfs account in order to mount it as net drive on windows
                cmd = f"net use 'Z:' '{net_path}' /user:nsbl 2633"
                print(cmd)
                subprocess.run(cmd, check=True)
            except:
                pass

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
            return AgiEnv.normalize_path(expanded_path)

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

    @staticmethod
    def _get_stdout(func, *args, **kwargs):
        """

        Args:
          func:
          *args:
          **kwargs:
        Returns:
        """
        f = io.StringIO()
        with redirect_stdout(f):
            result = func(*args, **kwargs)
        return f.getvalue(), result

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

        path = AgiEnv.normalize_path(path)

        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, check=True, cwd=path
        )
        if result.returncode != 0:
            if result.stderr.startswith("WARNING"):
                print(f"warning: worker {worker} - {cmd}")
                print(result.stderr)
            else:
                raise RuntimeError(
                    f"error on agi_worker {worker} - {cmd}\n{result.stderr}"
                )

        return result

    @staticmethod
    def _class_loader(module, target_class, mode, pck, env):
        """load_target

        Args:
          module:
          target_class:
          mode:
          pck:
        Returns:
        """
        if module in sys.modules:
            del sys.modules[module]
        if mode & 2 and module.endswith("_worker"):
            # raise ImportError(f'trying to load {module} in cython but it is already loaded in python')
            module += "_cy"
            pass
        else:
            # raise ImportError(f'trying to load {module} in python but it is already loaded in cython')
            # module = f"{pck}.{module}"
            module = f"{pck}.{module}"

        target_module = None
        try:
            # Dynamically import the target class from the module
            target_module = __import__(module, fromlist=[target_class])
            return getattr(target_module, target_class)

        except ModuleNotFoundError as err:
            # Raise a more descriptive ImportError if the target class cannot be imported
            print("file: ", __file__)
            print(f"\t__import__('{module}', fromlist=['{target_class}'])")
            print(f"\tgetattr('{target_module}', '{target_class}')")
            print("sys.path:\n\t", sys.path)
            raise ImportError(
                f"from {module} import {target_class} failed due to: {err}"
            ) from err

        except Exception as err:
            print("file: ", __file__)
            print(f"\t__import__('{module}', fromlist=['{target_class}'])")
            print(f"\tgetattr('{target_module}', '{target_class}')")
            print("sys.path:\n\t", sys.path)
            raise RuntimeError("something wrong happened in _class_loader") from err

    def onerror(func, path, exc_info):
        """Error handler for `shutil.rmtree`.

        If the error is due to an access error (read only file)
        it attempts to add write permission and then retries.

        If the error is for another reason it re-raises the error.

        Usage : `shutil.rmtree(path, onerror=onerror)`

        Args:
          func:
          path:
          exc_info:
        Returns:
        """
        try:
            # Check if file access issue
            if not os.access(path, os.W_OK):
                # Try to change the permissions of the file to writable
                os.chmod(path, stat.S_IWUSR)
                # Try the operation again
                func(path)
        except:
            print(f"warning failed to grant write access to {path}")
        # else:
        # Reraise the error if it's not a permission issue
        # raise

    @staticmethod
    def run(app, workers={"127.0.0.1": 1}, mode=0, verbose=3, args=None):

        env = AgiEnv(active_app=app, verbose=verbose)
        module = env.module

        if mode & 2:
            wenv_abs = env.wenv_abs

            # Look for any files or directories in the Cython lib path that match the "*cy*" pattern.
            cython_libs = list(wenv_abs.glob("*cy*"))

            # If a Cython library is found, normalize its path and set it as lib_path.
            lib_path = (
                str(Path(cython_libs[0].parent).resolve()) if cython_libs else None
            )

            if lib_path:
                if lib_path not in sys.path:
                    sys.path.insert(0, lib_path)
            else:
                print(f"warning: no cython library found at {lib_path}")
                exit(0)

        target_worker = env.target_worker
        try:
            AgiWorker.new(
                target_worker,
                env.target_worker_class,
                target_worker,
                mode=mode,
                verbose=verbose,
                env=env,
                args=args,
            )

        except Exception as err:
            print(traceback.format_exc())
            print(f"error: {err}")
            exit(1)

        target_class = AgiWorker._class_loader(
            module, env.target_class, mode, module, env
        )

        # Instantiate the class with arguments
        target_inst = target_class(env, **args)

        try:
            workers, workers_tree, workers_tree_info = AgiManager.do_distrib(
                target_inst, env, workers
            )
        except Exception as err:
            print(traceback.format_exc())
            exit(1)

        if mode == 48:
            return workers_tree

        t = time.time()
        AgiWorker.do_works(workers_tree, workers_tree_info)
        runtime = time.time() - t
        env._run_time = runtime

        return f"{env.mode2str(mode)} {humanize.precisedelta(timedelta(seconds=runtime))}"

    @staticmethod
    def new(
            target_module,
            target_class,
            target_package,
            mode=mode,
            verbose=0,
            worker_id=0,
            worker="localhost",
            env=None,
            args=None,
    ):
        """new worker instance
        Args:
          module: instanciate and load target my_code_worker module
          target_module:
          target_class:
          target_package:
          mode: (Default value = mode)
          verbose: (Default value = 0)
          worker_id: (Default value = 0)
          worker: (Default value = 'localhost')
          args: (Default value = None)
        Returns:
        """
        if verbose:
            print("venv:", sys.prefix)
            print(
                f"AgiWorker.new - worker #{worker_id}: {worker} from: {os.path.relpath(__file__)}\n",
                end="",
                flush=True,
            )

        # import of derived Class of AgiManager, name target_inst which is typically an instance of MyCode
        worker_class = AgiWorker._class_loader(
            target_module, target_class, mode, target_package, env
        )

        # Instantiate the class with arguments
        worker_inst = worker_class()
        worker_inst.mode = mode
        worker_inst.args = args
        worker_inst.verbose = verbose
        worker_inst.target = target_package

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

        return

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
            path = AgiEnv.normalize_path(AgiWorker.share_path)
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
    def build(app, target_worker, dask_home, worker, mode=0, verbose=0):
        """Function to build target code on a my_code_AgiWorker.

        Args:
          app(str): app to build
          target_worker(str): module to build
          dask_home(str): path to dask home
          worker: current worker
          mode: (Default value = 0)
          verbose: (Default value = 0)
        Returns:
        """
        if verbose > 1:
            sys.verbose = True
            print(
                f"build - worker #{AgiWorker.worker_id}: {worker} from: {os.path.relpath(__file__)}\n",
                end="",
                flush=True,
            )

        if str(getpass.getuser()).startswith("T0"):
            prefix = "~/MyApp/"
        else:
            prefix = "~/"
        AgiWorker.home_dir = Path(prefix).expanduser().absolute()
        AgiWorker.logs = os.path.join(
            AgiWorker.home_dir,
            f"{target_worker}_trace.txt",
        )
        AgiWorker.dask_home = dask_home
        AgiWorker.worker = worker

        try:
            with open(AgiWorker.logs, "w") as f:
                f.write("set verbose=3 to see something in this trace file ...\n")
                if verbose > 2:
                    f.write("starting worker_built ...\n")
                    f.write(f"home_dir: {AgiWorker.home_dir}\n")
                    f.write(
                        f"worker_build(target_worker={target_worker},\n\t"
                        f"dask_home={dask_home},\n\t"
                        f"mode={mode},\n\t"
                        f"verbose={verbose},\n\t"
                        f"worker={worker})\n"
                    )

                    for x in Path(dask_home).glob("*"):
                        f.write(f"\t\t{x}\n")

                # enabling to launch the build on another user account than the agi-core one
                extract_path = Path(AgiWorker.home_dir) / "wenv" / target_worker
                extract_src = extract_path / "src"

                if verbose > 2:
                    f.write(f"extract_path: {extract_path} \n")

                os.makedirs(extract_path, exist_ok=True)

                if verbose > 2:
                    f.write("sys.path:\n")
                    for x in sys.path:
                        f.write(f"\t{x}\n")

                # retrieve the egg file name without extension from the dask-scratch-space
                egg_src = next(
                    (x for x in Path(dask_home).glob(f"*{app.replace('-', '_')}*.src")),
                    None
                )
                if egg_src is None:
                    raise FileNotFoundError(
                        f"No file starting with '{app}' and not having suffix '.src' was found in {dask_home}"
                    )

                if verbose > 2:
                    f.write(f"worker_egg: {egg_src}\n")

                if mode & 2:
                    # case cython requested
                    if AgiWorker._built:
                        # case cython already built
                        return

                    if verbose > 2:
                        f.write(f"unzip: {egg_src}\nto: {extract_path}\n")

                    # unzip it into the wenv
                    with ZipFile(egg_src, "r") as zip_ref:
                        zip_ref.extractall(extract_src)

                    if verbose > 2:
                        f.write(f" done!\n")
                        f.write(f"copyfile: 'setup' to {extract_path}")

                    shutil.copyfile(
                        os.path.join(extract_path, "src/agi_core/workers/agi_worker/setup"),
                        os.path.join(extract_path, "setup"),
                    )

                    if verbose > 2:
                        f.write(f" done!\n")

                    sys_prefix = Path(get_python_lib())

                    # clean the target lib if any
                    ext = "pyd" if os.name == "nt" else "so"
                    target_lib_iter = sys_prefix.glob(f"*{target_worker}*.{ext}")
                    for lib in target_lib_iter:
                        if verbose > 2:
                            f.write(f" removing:  {lib}")
                        os.remove(lib)
                        if verbose > 2:
                            f.write(f" done!\n")

                    if verbose > 2:
                        f.write(f"sys_prefix: {sys_prefix}\n")
                    # build the target extension
                    cmd = [
                        "cd",
                        str(extract_path),
                        "&&",
                        "uv",
                        "run",
                        "python",
                        "setup",
                        "build_ext",
                        "--debug",
                        "-d",
                        str(extract_path)
                    ]

                    # Fixing side effect: add extract_path as a string
                    extract_path_str = str(extract_path)
                    if extract_path_str not in sys.path:
                        sys.path.append(extract_path_str)

                    target_lib = next(
                        (p for p in extract_path.iterdir() if p.suffix == f".{ext}"),
                        None
                    )
                    if target_lib is None:
                        raise FileNotFoundError(f"No file with extension '.{ext}' found in {extract_path}")

                    lib_dir =os.path.join(sysconfig.get_path("platlib"), target_lib.name)
                    shutil.copyfile(target_lib, lib_dir)

                    if verbose > 2:
                        f.write(f"copy {target_lib}\n tp {lib_dir}\n")
                        f.write(f"running cmd: {cmd}\nfrom path: {extract_path}\n")

                    res = AgiWorker.exec(cmd, extract_path, worker)

                    if verbose > 2:
                        f.write(f"stdout: {res.stdout}")
                        f.write("\n")
                        f.write(f"stderr: {res.stderr}")
                        f.write("\n")
                        f.write(f" done!\n")

                    AgiWorker._built = True

                else:
                    # case worker egg need to be added to sys.path
                    egg_dest = os.path.join(
                        extract_path, os.path.basename(egg_src) + ".egg"
                    )

                    if verbose > 2:
                        f.write(f"copy:\n{egg_src}\nto:\n{egg_dest}\n")
                    shutil.copyfile(egg_src, egg_dest)

                    if egg_dest in sys.path:
                        sys.path.remove(egg_dest)
                    sys.path.insert(0, egg_dest)

                    if verbose > 2:
                        f.write("sys.path:\n")
                        for x in sys.path:
                            f.write(f"\t{x}\n")

                    if verbose > 2:
                        f.write(f" done!\n")
            # os.remove(AgiWorker.logs)

        except Exception as err:
            print(
                f"worker<{worker}> - fail to build {target_worker} from {dask_home}, see {AgiWorker.logs} for details")
            raise err

        return

    @staticmethod
    def do_works(workers_tree, workers_tree_info):
        """run of workers

        Args:
          chunk: distribution tree
          chunks:
        Returns:
        """
        worker_id = AgiWorker.worker_id
        if AgiWorker.verbose > 0:
            print(
                f"do_works - worker #{worker_id}: {AgiWorker.worker} from {os.path.relpath(__file__)}\n",
                end="",
                flush=True,
            )
            print(
                f"AgiWorker.work - #{worker_id + 1} / {len(workers_tree)}\n",
                end="",
                flush=True,
            )

        AgiWorker._insts[worker_id].works(workers_tree, workers_tree_info)

        return

    @staticmethod
    def normalize_path(path):
        return (
            str(PureWindowsPath(Path(path)))
            if os.name == "nt"
            else str(PurePosixPath(Path(path)))
        )