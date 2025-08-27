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

from IPython.core.ultratb import FormattedTB
import ast
import asyncio
import getpass
import os
import re
import shutil
import psutil
import socket
import subprocess
import sys
import traceback
from pathlib import Path, PureWindowsPath, PurePosixPath
from dotenv import dotenv_values, set_key
import tomlkit
import logging
import astor
from pathspec import PathSpec
from pathspec.patterns import GitWildMatchPattern
import py7zr
import urllib.request
import inspect
from concurrent.futures import ThreadPoolExecutor

# Get constructor parameters of FormattedTB
_sig = inspect.signature(FormattedTB.__init__).parameters

_tb_kwargs = dict(mode='Verbose', call_pdb=True)
if 'color_scheme' in _sig:
    _tb_kwargs['color_scheme'] = 'NoColor'
else:
    _tb_kwargs['theme_name'] = 'NoColor'

sys.excepthook = FormattedTB(**_tb_kwargs)


# Compile regex once globally
LOG_LEVEL_RE = re.compile(r'\b(INFO|ERROR|WARNING|DEBUG|CRITICAL)\b')

logger = logging.getLogger(__name__)

def normalize_path(path):
    return (
        str(PureWindowsPath(Path(path)))
        if os.name == "nt"
        else str(PurePosixPath(Path(path)))
    )


class AgiEnv:
    install_type = None
    apps_dir = None
    app = None
    module = None
    GUI_NROW = None
    GUI_SAMPLING = None
    init_done = False
    has_rapids_hw = None
    is_worker_env = False
    debug = False
    uv = None
    benchmark = None
    verbose = None
    pyvers_worker = None
    _ip_local_cache: set = set({"127.0.0.1", "::1"})


    def init_logging(self, verbosity: int = None):
        """
        Initialize logging with a level based on verbosity:
        0 = WARNING, 1 = INFO, 2 or more = DEBUG
        INFO and DEBUG levels go to stdout; WARNING and above go to stderr.
        """

        self.uv = "uv"
        if verbosity is None:
            verbosity = 0
        elif verbosity > 1:
            self.uv = "uv -q"


        # Root logger level based on verbosity
        root_level = logging.DEBUG if verbosity >= 2 else logging.INFO if verbosity == 1 else logging.WARNING

        # Cap distributed logs at CRITICAL (silent)
        sys_level = logging.ERROR if verbosity < 2 else logging.INFO if verbosity > 3 else logging.DEBUG

        # Use root_level for your app-specific loggers as well
        app_level = root_level

        root = logging.getLogger()
        root.setLevel(root_level)

        # Set distributed logger levels explicitly to suppress debug/info noise
        logging.getLogger("distributed").setLevel(sys_level)
        logging.getLogger("distributed.worker").setLevel(sys_level)
        logging.getLogger("distributed.scheduler").setLevel(sys_level)
        logging.getLogger("distributed.comm").setLevel(sys_level)
        logging.getLogger("distributed.comm.tcp").setLevel(sys_level)
        logging.getLogger("distributed.active_memory_manager").setLevel(sys_level)

        # Set asyncssh and other custom loggers to app_level (verbosity controlled)
        logging.getLogger('asyncssh').setLevel(sys_level)

        # agilab core
        logging.getLogger("agi_cluster").setLevel(app_level)
        logging.getLogger("agi_node").setLevel(app_level)
        logging.getLogger("agi_env").setLevel(app_level)


        # Remove existing handlers to avoid duplicate logs
        for handler in root.handlers[:]:
            root.removeHandler(handler)

        class ClassNameFilter(logging.Filter):
            def filter(self, record):
                # Try to find the class name from the frame where the log call was made
                try:
                    # Walk up frames starting from current to find frame matching record
                    frame = sys._getframe(0)
                    while frame:
                        code = frame.f_code
                        if code.co_filename == record.pathname and code.co_name == record.funcName:
                            # Found the frame of the caller
                            # Check if 'self' is in locals to get class name
                            if 'self' in frame.f_locals:
                                record.classname = frame.f_locals['self'].__class__.__name__
                            else:
                                record.classname = record.module or record.pathname
                            break
                        frame = frame.f_back
                    else:
                        record.classname = '<no-class>'
                except Exception:
                    record.classname = '<no-class>'
                return True

        fmt_std = logging.Formatter(
            "%(asctime)s %(levelname)s %(message)s",
            datefmt="%H:%M:%S"
        )

        fmt_err = logging.Formatter(
            "%(asctime)s %(levelname)s %(classname)s %(funcName)s %(message)s",
            datefmt="%H:%M:%S"
        )

        if verbosity > 1:
            fmt_std = fmt_err

        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setLevel(logging.DEBUG)
        stdout_handler.setFormatter(fmt_std)
        stdout_handler.addFilter(ClassNameFilter())

        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setLevel(logging.WARNING)
        stderr_handler.setFormatter(fmt_err)
        stderr_handler.addFilter(ClassNameFilter())

        root.addHandler(stdout_handler)
        root.addHandler(stderr_handler)

        root.setLevel(logging.DEBUG if verbosity and verbosity >= 2 else logging.INFO if verbosity == 1 else logging.WARNING)

        logging.debug(f"Logging initialized at level {logging.getLevelName(root.level)}")

    def __init__(self,
                 active_app: Path | str = None,
                 install_type: int = None,
                 verbose: int = None,
                 debug=False,
                 python_variante: str = ''):

        AgiEnv.is_managed_pc = getpass.getuser().startswith("T0")
        self.agi_resources = Path("resources/.agilab")
        home_abs = Path.home() / "MyApp" if AgiEnv.is_managed_pc else Path.home()
        self.home_abs = home_abs

        AgiEnv.resources_path = home_abs / self.agi_resources.name
        env_path = AgiEnv.resources_path / ".env"
        self.benchmark = AgiEnv.resources_path / "benchmark.json"
        AgiEnv.envars = dotenv_values(dotenv_path=env_path, verbose=verbose)
        envars = AgiEnv.envars

        if isinstance(active_app, str):
            # case only worker_env
            self.is_worker_env = True
            active_app = Path(active_app).resolve()
            module = active_app.name.replace("_project", "").replace("-", "_")

        else:
            if not active_app:
                before, sep, after = __file__.rpartition(".venv")
                active_app = Path(before) / "apps" / envars.get("APP_DEFAULT", 'flight_project')
            if not active_app.name.endswith('_project'):
                raise ValueError(f"{active_app} must end with '_project'")

        self.active_app = active_app
        module = active_app.name.replace("_project", "").replace("-", "_")

        AgiEnv.verbose = verbose
        self.verbose = verbose
        AgiEnv.python_variante = python_variante
        self.init_logging(verbose)
        AgiEnv.debug = debug

        if install_type is None:
            install_type = 1 if ("site-packages" not in __file__ or sys.prefix.endswith("agilab/.venv")) else 0
        elif isinstance(install_type, str):
            install_type = int(install_type)

        AgiEnv.install_type = install_type

        if install_type == 0:
            # remote case
            self.agilab_src = AgiEnv.locate_agilab_installation(verbose)
            agilab_src_parent = self.agilab_src.parent
            self.src_cluster = agilab_src_parent / "agi_cluster"
            self.node_root = agilab_src_parent / "agi_node"
            self.env_root = agilab_src_parent / "agi_env"
            self.cluster_root = self.active_app.parent

            if not active_app.exists():
                src_apps = self.agilab_src / "apps"
                if not active_app.exists():
                    if src_apps.exists():
                        self.copy_existing_projects(src_apps, active_app.parent)
                    else:
                        print(f"Warning: {src_apps} does not exist, nothing to copy!")
                else:
                    self.copy_missing(src_apps, active_app.parent)
            resources_src = self.env_root / self.agi_resources

        elif install_type == 1:
            # dev case for manager
            self.agilab_src = AgiEnv.read_agilab_path(verbose)
            if not self.agilab_src:
                self.agilab_src = AgiEnv.locate_agilab_installation(verbose)
            self.env_root = self.agilab_src / "core/agi-env"
            self.cluster_root = self.agilab_src / "core/agi-cluster"
            self.src_cluster = self.cluster_root / "src/agi_cluster"
            self.node_root = self.agilab_src / "core/agi-node"
            resources_src = self.env_root / "src/agi_env" / self.agi_resources

        elif install_type == 2:
            # enduser case
            self.agilab_src = AgiEnv.locate_agilab_installation(verbose)
            self.env_root = self.agilab_src / "../agi-env"
            self.node_root = self.agilab_src / "../agi-node"
            self.cluster_root = self.agilab_src / "../agi-cluster"
            self.src_cluster = self.cluster_root / "src/agi_cluster"
            resources_src = self.env_root / "src/agi_env" / self.agi_resources
            if not self.env_root.exists():
                raise RuntimeError(f"{self.env_root} do not exist\nYour Agilab installation is not valid")

        self._init_resources(resources_src)
        self.st_resources = self.agilab_src / "resources"
        self.GUI_NROW = int(envars.get("GUI_NROW", 1000))
        self.GUI_SAMPLING = int(envars.get("GUI_SAMPLING", 20))

        self.module = module
        wenv_root = Path("wenv")
        target_worker = f"{module}_worker"
        self.target_worker = target_worker
        wenv_rel = wenv_root / target_worker
        target_class = "".join(x.title() for x in module.split("_"))
        self.target_class = target_class
        worker_class = target_class + "Worker"
        self.target_worker_class = worker_class

        self.wenv_rel = wenv_rel
        self.dist_rel = wenv_rel / 'dist'
        wenv_abs = home_abs / wenv_rel
        self.wenv_abs = wenv_abs
        os.makedirs(self.wenv_abs, exist_ok=True)

        dist_abs = wenv_abs / 'dist'
        dist = normalize_path(dist_abs)
        if not dist in sys.path:
            sys.path.append(dist)
        self.dist_abs = dist_abs
        self.wenv_target_worker = self.wenv_abs

        if install_type == 0:
            app_src = active_app / "src"
            self.app_pyproject = active_app / "pyproject.toml"
            self.worker_path = app_src / target_worker / f"{target_worker}.py"
            self.worker_pyproject = self.worker_path.parent / "pyproject.toml"
            self.module_path = app_src / module / f"{self.module}.py"
            worker_module_path = self.worker_path.parent
            self.setup_core = self.node_root / "agi_dispatcher/build.py"

        elif install_type == 1:
            app_src = active_app / "src"
            self.app_pyproject = active_app / "pyproject.toml"
            self.worker_path = app_src / target_worker / f"{target_worker}.py"
            self.worker_pyproject = self.worker_path.parent / "pyproject.toml"
            self.module_path = app_src / module / f"{self.module}.py"
            worker_module_path = self.worker_path.parent
            self.setup_core = self.agilab_src / "core/agi-node/src/agi_node/agi_dispatcher/build.py"

        elif install_type == 2:
            active_app = self.agilab_src
            app_src = self.agilab_src / "src"
            self.worker_path = self.wenv_rel / 'src' / target_worker / f"{target_worker}.py"
            self.module_path = self.wenv_rel / 'src' / module / f"{self.module}.py"
            worker_module_path = self.worker_path.parent
            self.setup_core = self.wenv_rel / "src/agi_dispatcher/build.py"

        self.app_abs = active_app
        self.uvproject = active_app / "uv_config.toml"
        self.post_install = worker_module_path / "post_install.py"
        self.pre_install = worker_module_path / "pre_install.py"
        self.post_install_rel = self.wenv_rel / 'src' / target_worker / "post_install.py"

        src_path = normalize_path(app_src)
        if not src_path in sys.path:
            sys.path.append(src_path)

        AgiEnv.apps_dir = active_app.parent
        distribution_tree = self.wenv_abs / "distribution_tree.json"
        if distribution_tree.exists():
            distribution_tree.unlink()
        self.distribution_tree = distribution_tree

        if install_type == 2:
            return

        self.base_worker_cls, self.base_worker_module = self.get_base_worker_cls(
            self.worker_path, worker_class
        )
        self.workers_packages_prefix = "workers."
        if not self.worker_path.exists():
            logging.info(f"Missing {self.target_worker_class} definition; should be in {self.worker_path} but it does not exist")
            sys.exit(1)

        envars = AgiEnv.envars
        self.credantials = envars.get("CLUSTER_CREDENTIALS", getpass.getuser())
        credantials = self.credantials.split(":")
        self.user = credantials[0]
        self.password = credantials[1] if len(credantials) > 1 else None
        self.python_version = envars.get("AGI_PYTHON_VERSION", "3.13")

        self.is_free_threading_available = envars.get("AGI_PYTHON_FREE_THREADED", 0)
        with open(self.worker_pyproject, "r") as f:
            data = tomlkit.parse(f.read())
        try:
            use_freethread = data["tool"]["freethread_info"]["is_app_freethreaded"]
            if use_freethread and self.is_free_threading_available:
                self.uv_worker = "PYTHON_GIL=0 " + self.uv
                self.pyvers_worker = self.python_version + "t"
            else:
                self.uv_worker = self.uv
                self.pyvers_worker = self.python_version
        except KeyError as e:
            use_freethread = False
            self.uv_worker = self.uv
            self.pyvers_worker = self.python_version

        self.update_pyproject()

        self.projects = self.get_projects(AgiEnv.apps_dir)
        if not self.projects:
            logging.info(f"Could not find any target project app in {self.agilab_src / 'apps'}.")

        self.setup_app = active_app / "build.py"

        if isinstance(module, Path):
            module_path = module.expanduser().resolve()
        else:
            module_path = self._determine_module_path(module)

        self.target = module_path.stem
        self.module_path = module_path
        self.AGILAB_SHARE = Path(envars.get("AGI_SHARE_DIR", "data"))
        data_rel = self.AGILAB_SHARE / self.target
        self.dataframe_path = data_rel / "dataframe"
        self.data_rel = data_rel
        self._init_projects()

        self.scheduler_ip = envars.get("AGI_SCHEDULER_IP", "127.0.0.1")
        if not self.is_valid_ip(self.scheduler_ip):
            raise ValueError(f"Invalid scheduler IP address: {self.scheduler_ip}")

        if AgiEnv.install_type:
            self.help_path = str(self.agilab_src / "../docs/html")
        else:
            self.help_path = "https://thalesgroup.github.io/agilab"
        self.AGILAB_SHARE = Path(envars.get("AGI_SHARE_DIR", home_abs / "data"))

        app_src.mkdir(parents=True, exist_ok=True)
        app_src_str = str(app_src)
        if app_src_str not in sys.path:
            sys.path.append(app_src_str)
        self.app_src = app_src
        self.app_abs = active_app

        # type 3: only core install
        if AgiEnv.install_type != 3:
            self.init_envars_app(AgiEnv.envars)
            self._init_apps()

        if os.name == "nt":
            AgiEnv.export_local_bin = None
        else:
            AgiEnv.export_local_bin = 'export PATH="$HOME/.local/bin:$PATH";'

    def active(self, target, install_type):
        if str(self.active_app) != target:
            self.change_active_app(target, install_type)

    def check_args(self, target_args_class, target_args):
        try:
            validated_args = target_args_class.parse_obj(target_args)
            validation_errors = None
        except Exception as e:
            import humanize
            validation_errors = self.humanize_validation_errors(e)
        return validation_errors

    def humanize_validation_errors(self, error):
        formatted_errors = []
        for err in error.errors():
            field = ".".join(str(loc) for loc in err["loc"])
            message = err["msg"]
            error_type = err.get("type", "unknown_error")
            input_value = err.get("ctx", {}).get("input_value", None)
            user_message = f"❌ **{field}**: {message}"
            if input_value is not None:
                user_message += f" (Received: `{input_value}`)"
            user_message += f"*Error Type:* `{error_type}`"
            formatted_errors.append(user_message)
        return formatted_errors

    def set_env_var(key: str, value: str):
        AgiEnv.envars[key] = value
        os.environ[key] = str(value)
        AgiEnv._update_env_file({key: value})

    @staticmethod
    def read_agilab_path(verbose=False):
        if os.name == "nt":
            where_is_agi = Path(os.getenv("LOCALAPPDATA", "")) / "agilab/.agilab-path"
        else:
            where_is_agi = Path.home() / ".local/share/agilab/.agilab-path"

        if where_is_agi.exists():
            try:
                with where_is_agi.open("r", encoding="utf-8-sig") as f:
                    install_path = f.read().strip()
                    agilab_path = Path(install_path)
                    if install_path and agilab_path.exists():
                        return agilab_path
                    else:
                        raise ValueError("Installation path file is empty or invalid.")
            except FileNotFoundError:
                logging.error(f"File {where_is_agi} does not exist.")
            except PermissionError:
                logging.error(f"Permission denied when accessing {where_is_agi}.")
            except Exception as e:
                logging.error(f"An error occurred: {e}")

    @staticmethod
    def locate_agilab_installation(verbose=False):
        for p in sys.path_importer_cache:
            if p.endswith("agi_env"):
                base_dir = p.replace('_env', 'lab')
                if verbose:
                    logging.info(f"Fallback agilab path found: {base_dir}")
                if AgiEnv.install_type == 0:
                    return Path(base_dir)
                else:
                    before, sep, after = p.rpartition("agilab")
                    return Path(before) / sep
        logging.info("Falling back to current working directory")
        return Path(os.getcwd())

    def copy_existing_projects(self, src_apps: Path, dst_apps: Path):
        dst_apps.mkdir(parents=True, exist_ok=True)

        # match every nested directory ending with "_project"
        for item in src_apps.rglob("*_project"):
            if not item.is_dir():
                continue

            rel = item.relative_to(src_apps)  # keep nested structure
            dst_item = dst_apps / rel
            try:
                shutil.copytree(
                    item,
                    dst_item,
                    dirs_exist_ok=True,  # merge into existing tree
                    symlinks=True,  # keep symlinks as symlinks
                    ignore=shutil.ignore_patterns(  # skip bulky/ephemeral stuff
                        ".venv", "build", "dist", "__pycache__", ".pytest_cache",
                        ".idea", ".mypy_cache", ".ruff_cache", "*.egg-info"
                    ),
                )
            except Exception as e:
                print(f"Warning: Could not copy {item} → {dst_item}: {e}")
    def copy_missing(self, src: Path, dst: Path, max_workers=8):
        """
        Copy missing files/directories from src to dst, skipping files/dirs that already exist at dst.
        Robust: skips any missing src_item, logs a warning, never crashes.
        """
        dst.mkdir(parents=True, exist_ok=True)
        to_copy = []
        dirs = []

        for item in src.iterdir():
            src_item = item
            dst_item = dst / item.name
            if not src_item.exists():
                print(f"[WARN] Source item missing: {src_item}, skipping")
                continue
            if src_item.is_dir():
                dirs.append((src_item, dst_item))
            else:
                to_copy.append((src_item, dst_item))

        def safe_copy(args):
            src_item, dst_item = args
            if src_item.exists():
                try:
                    shutil.copy2(src_item, dst_item)
                except Exception as e:
                    print(f"[WARN] Could not copy {src_item} → {dst_item}: {e}")
            else:
                print(f"[WARN] Source file missing (skipped): {src_item}")

        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            list(executor.map(safe_copy, to_copy))

        for src_dir, dst_dir in dirs:
            if src_dir.exists():
                self.copy_missing(src_dir, dst_dir, max_workers=max_workers)
            else:
                print(f"[WARN] Source dir missing (skipped): {src_dir}")

    def _update_env_file(updates: dict):
        env_file = AgiEnv.resources_path / ".env"
        for k, v in updates.items():
            set_key(str(env_file), k, str(v), quote_mode="never")

    def _init_resources(self, resources_src):
        src_env_path = resources_src / ".env"
        dest_env_file = AgiEnv.resources_path / ".env"
        if not src_env_path.exists():
            msg = f"Installation issue: {src_env_path} is missing!"
            logging.info(msg)
            raise RuntimeError(msg)
        if not dest_env_file.exists():
            os.makedirs(dest_env_file.parent, exist_ok=True)
            shutil.copy(src_env_path, dest_env_file)
        for root, dirs, files in os.walk(resources_src):
            for file in files:
                src_file = Path(root) / file
                relative_path = src_file.relative_to(resources_src)
                dest_file = AgiEnv.resources_path / relative_path
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                if not dest_file.exists():
                    shutil.copy(src_file, dest_file)

    def _init_projects(self):
        self.projects = self.get_projects(self.apps_dir)
        for idx, project in enumerate(self.projects):
            if self.target == project[:-8].replace("-", "_"):
                self.app_abs = AgiEnv.apps_dir / project
                self.project_index = idx
                self.app = project
                break

    def _determine_apps_dir(self, module_path):
        path_str = str(module_path)
        index = path_str.index("_project")
        return Path(path_str[:index]).parent

    def _determine_module_path(self, project_or_module_name):
        parts = project_or_module_name.rsplit("-", 1)
        suffix = parts[-1]
        name = parts[0].split(os.sep)[-1]
        module_name = name.replace("-", "_")
        if suffix.startswith("project"):
            name = name.replace("-" + suffix, "")
            project_name = name + "_project"
        else:
            project_name = name.replace("_", "-") + "_project"
        module_path = AgiEnv.apps_dir / project_name / "src" / module_name / (module_name + ".py")
        return module_path.resolve()

    def get_projects(self, path: Path):
        return [p.name for p in path.glob("*project")]

    def get_modules(self, target=None):
        pattern = "_project"
        modules = [
            re.sub(f"^{pattern}|{pattern}$", "", project).replace("-", "_")
            for project in self.get_projects(AgiEnv.apps_dir)
        ]
        return modules

    def get_base_worker_cls(self, module_path, class_name):
        base_info_list = self.get_base_classes(module_path, class_name)
        try:
            base_class, module_name = next((base, mod) for base, mod in base_info_list if base.endswith("Worker"))
            return base_class, module_name
        except StopIteration:
            return None, None

    def get_base_classes(self, module_path, class_name):
        try:
            with open(module_path, "r", encoding="utf-8") as file:
                source = file.read()
        except (IOError, FileNotFoundError) as e:
            logging.error(f"Error reading module file {module_path}: {e}")
            return []

        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            logging.error(f"Syntax error parsing {module_path}: {e}")
            raise RuntimeError(f"Syntax error parsing {module_path}: {e}")

        import_mapping = self.get_import_mapping(source)
        base_classes = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for base in node.bases:
                    base_info = self.extract_base_info(base, import_mapping)
                    if base_info:
                        base_classes.append(base_info)
                break
        return base_classes

    def get_import_mapping(self, source):
        mapping = {}
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            logging.error(f"Syntax error during import mapping: {e}")
            raise
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mapping[alias.asname or alias.name] = alias.name
            elif isinstance(node, ast.ImportFrom):
                module = node.module
                for alias in node.names:
                    mapping[alias.asname or alias.name] = module
        return mapping

    def extract_base_info(self, base, import_mapping):
        if isinstance(base, ast.Name):
            module_name = import_mapping.get(base.id)
            return base.id, module_name
        elif isinstance(base, ast.Attribute):
            full_name = self.get_full_attribute_name(base)
            parts = full_name.split(".")
            if len(parts) > 1:
                alias = parts[0]
                module_name = import_mapping.get(alias, alias)
                return parts[-1], module_name
            return base.attr, None
        return None

    def get_full_attribute_name(self, node):
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return self.get_full_attribute_name(node.value) + "." + node.attr
        return ""

    def mode2str(self, mode):

        chars = ["p", "c", "d", "r"]
        reversed_chars = reversed(list(enumerate(chars)))

        if self.has_rapids_hw:
            mode += 8
        mode_str = "".join(
            "_" if (mode & (1 << i)) == 0 else v for i, v in reversed_chars
        )
        return mode_str

    @staticmethod
    def mode2int(mode):
        mode_int = 0
        set_rm = set(mode)
        for i, v in enumerate(["p", "c", "d"]):
            if v in set_rm:
                mode_int += 2 ** (len(["p", "c", "d"]) - 1 - i)
        return mode_int

    def is_valid_ip(self, ip: str) -> bool:
        pattern = re.compile(r"^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$")
        if pattern.match(ip):
            parts = ip.split(".")
            return all(0 <= int(part) <= 255 for part in parts)
        return False

    def init_envars_app(self, envars):
        self.CLUSTER_CREDENTIALS = envars.get("CLUSTER_CREDENTIALS", None)
        self.OPENAI_API_KEY = envars.get("OPENAI_API_KEY", None)
        AGILAB_LOG_ABS = Path(envars.get("AGI_LOG_DIR", self.home_abs / "log"))
        if not AGILAB_LOG_ABS.exists():
            AGILAB_LOG_ABS.mkdir(parents=True)
        self.AGILAB_LOG_ABS = AGILAB_LOG_ABS
        self.runenv = self.AGILAB_LOG_ABS
        AGILAB_EXPORT_ABS = Path(envars.get("AGI_EXPORT_DIR", self.home_abs / "export"))
        if not AGILAB_EXPORT_ABS.exists():
            AGILAB_EXPORT_ABS.mkdir(parents=True)
        self.AGILAB_EXPORT_ABS = AGILAB_EXPORT_ABS
        self.export_apps = AGILAB_EXPORT_ABS / "apps"
        if not self.export_apps.exists():
            os.makedirs(str(self.export_apps), exist_ok=True)
        self.MLFLOW_TRACKING_DIR = Path(envars.get("MLFLOW_TRACKING_DIR", self.home_abs / ".mlflow"))
        self.AGILAB_VIEWS_ABS = Path(envars.get("AGI_VIEWS_DIR", self.agilab_src / "views"))
        self.AGILAB_VIEWS_REL = Path(envars.get("AGI_VIEWS_DIR", "agilab/_"))
        if AgiEnv.install_type == 0:
            self.copilot_file = self.agilab_src / "agi_copilot.py" # WTF ?
        else:
            self.copilot_file = self.agilab_src / "agi_copilot.py"

    def update_pyproject_enduser(self):
        agilab_src = self.agilab_src
        for file in [self.worker_pyproject, self.app_pyproject]:
            if not file.exists():
                raise FileNotFoundError(f"{file} not found in {self.app_abs}")

            text = file.read_text(encoding="utf-8")
            doc = tomlkit.parse(text)

            try:
                uv = doc["tool"]["uv"]
            except KeyError:
                continue

            if "sources" not in uv or not isinstance(uv["sources"], tomlkit.items.Table):
                continue

            sources = uv["sources"]

            if "site-packages" in agilab_src.parts:
                for package in ["agi-env", "agi-node", "agi-cluster"]:
                    if package in sources:
                        sources[package] = {
                            "path": "../../.venv/lib/python3.13/site-packages/" + package.replace("-", "_"),
                            "editable": True
                        }

            file.write_text(tomlkit.dumps(doc), encoding="utf-8")

    def update_pyproject(self):
        agilab_src = self.agilab_src
        for file in [self.worker_pyproject, self.app_pyproject]: #, self.core_root / "src/agilab/core/pyproject.toml"]:
            if not file.exists():
                raise FileNotFoundError(f"{file} not found in {self.app_abs}")

            text = file.read_text(encoding="utf-8")
            doc = tomlkit.parse(text)

            try:
                uv = doc["tool"]["uv"]
            except KeyError:
                continue

            if "sources" not in uv or not isinstance(uv["sources"], tomlkit.items.Table):
                continue

            sources = uv["sources"]

            if "site-packages" in agilab_src.parts:
                for package in ["agi-env", "agi-node", "agi-cluster"]:
                    if package in sources:
                        del sources[package]
                        if not sources:
                            del uv["sources"]
                        if not uv:
                            del doc["tool"]["uv"]
                        if not doc["tool"]:
                            del doc["tool"]
                    deps = doc["project"].get("dependencies", [])
                    if not any(dep.split()[0] == package for dep in deps):
                        deps.append(package)
                        doc["project"]["dependencies"] = deps

            file.write_text(tomlkit.dumps(doc), encoding="utf-8")

    @staticmethod
    def _copy_file(src_item, dst_item):
        if not dst_item.exists():
            if not src_item.exists():
                print(f"[WARN] Source file missing (skipped): {src_item}")
                return
            try:
                shutil.copy2(src_item, dst_item)
            except Exception as e:
                print(f"[WARN] Could not copy {src_item} → {dst_item}: {e}")

    def copy_missing(self, src: Path, dst: Path, max_workers=8):
        dst.mkdir(parents=True, exist_ok=True)
        to_copy = []
        dirs = []

        for item in src.iterdir():
            src_item = item
            dst_item = dst / item.name
            if src_item.is_dir():
                dirs.append((src_item, dst_item))
            else:
                to_copy.append((src_item, dst_item))

        # Parallel file copy
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            list(executor.map(lambda args: AgiEnv._copy_file(*args), to_copy))

        # Recurse into directories
        for src_dir, dst_dir in dirs:
            self.copy_missing(src_dir, dst_dir, max_workers=max_workers)


    def _init_apps(self):
        app_settings_file = self.app_src / "app_settings.toml"
        app_settings_file.touch(exist_ok=True)
        self.app_settings_file = app_settings_file

        args_ui_snippet = self.app_src / "args_ui_snippet.py"
        args_ui_snippet.touch(exist_ok=True)
        self.args_ui_snippet = args_ui_snippet

        self.gitignore_file = self.app_abs / ".gitignore"
        dest = AgiEnv.resources_path
        src = self.agilab_src / "resources"
        if src.exists():
            for file in src.iterdir():
                if not file.is_file():
                    continue
                dest_file = dest / file.name
                if dest_file.exists():
                    continue
                shutil.copy2(file, dest_file)
        # shutil.copytree(self.agilab_src / "resources", dest, dirs_exist_ok=True)


    @staticmethod
    def _build_env(venv=None):
        """Build environment dict for subprocesses, with activated virtualenv paths."""
        proc_env = os.environ.copy()
        if venv is not None:
            venv_path = Path(venv) / ".venv"
            proc_env["VIRTUAL_ENV"] = str(venv_path)
            bin_path = "Scripts" if os.name == "nt" else "bin"
            venv_bin = venv_path / bin_path
            proc_env["PATH"] = str(venv_bin) + os.pathsep + proc_env.get("PATH", "")
        return proc_env

    @staticmethod
    def log_info(line):
        GREEN = "\033[32m"
        RESET = "\033[0m"

        if not isinstance(line, str):
            line = str(line)

        msg = f"{GREEN}{line}{RESET}" if sys.stdout.isatty() else line
        logging.info(msg)


    @staticmethod
    def log_error(line):
        RED = "\033[31m"
        RESET = "\033[0m"

        if not isinstance(line, str):
            line = str(line)

        msg = f"{RED}{line}{RESET}" if sys.stdout.isatty() else line
        logging.info(msg)

    @staticmethod
    async def run(cmd, venv, cwd=None, timeout=None, wait=True, log_callback=None):
        """
        Run a shell command inside a virtual environment.
        Streams stdout/stderr live without blocking (Windows-safe).
        Returns the full stdout string.
        """
        if AgiEnv.verbose > 1:
            logging.info(f"Executing in {venv}: {cmd}")

        if not cwd:
            cwd = venv
        process_env = os.environ.copy()
        venv_path = Path(venv)
        if not (venv_path / "bin").exists() and venv_path.name != ".venv":
            venv_path = venv_path / ".venv"

        process_env["VIRTUAL_ENV"] = str(venv_path)
        bin_dir = "Scripts" if sys.platform == "win32" else "bin"
        venv_bin = venv_path / bin_dir
        process_env["PATH"] = str(venv_bin) + os.pathsep + process_env.get("PATH", "")

        shell_executable = None if sys.platform == "win32" else "/bin/bash"

        if wait:
            try:
                process = await asyncio.create_subprocess_shell(
                    cmd,
                    cwd=str(cwd),
                    env=process_env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    executable=shell_executable
                )

                result = []

                async def read_stream(stream, callback):
                    encoding = sys.stdout.encoding or "utf-8"

                    while True:
                        line = await stream.readline()
                        if not line:
                            break

                        # Decode from UTF-8 (most CLI tools default to this)
                        decoded_line = line.decode("utf-8", errors="replace").rstrip()

                        if decoded_line:
                            # Ensure the string can be encoded in the console's encoding
                            safe_line = decoded_line.encode(encoding, errors="replace").decode(encoding)
                            result.append(safe_line)
                            callback(safe_line)

                # Read stdout and stderr concurrently
                await asyncio.wait_for(
                    asyncio.gather(
                        read_stream(process.stdout, log_callback if log_callback else logging.info),
                        read_stream(process.stderr, log_callback if log_callback else logging.error)
                    ),
                    timeout=timeout
                )

                returncode = await process.wait()
                if AgiEnv.verbose > 1 or AgiEnv.debug:
                    logging.info(f"Command completed with exit code {returncode}")

                return "\n".join(result)

            except asyncio.TimeoutError:
                process.kill()
                raise RuntimeError(f"Command timed out after {timeout} seconds: {cmd}")
            except Exception as e:
                logging.error(traceback.format_exc())
                raise RuntimeError(f"Command execution error: {e}") from e

        else:
            asyncio.create_task(asyncio.create_subprocess_shell(
                cmd,
                cwd=str(cwd),
                env=process_env,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                executable=shell_executable
            ))
            return 0

    @staticmethod
    async def _run_bg(cmd, cwd=".", venv=None, timeout=None, log_callback=None):
        """
        Run the given command asynchronously, reading stdout and stderr line by line
        and passing them to the log_callback.
        """
        proc_env = AgiEnv._build_env(venv)
        proc_env["PYTHONUNBUFFERED"] = "1"
        proc = await asyncio.create_subprocess_shell(
            cmd,
            cwd=os.path.abspath(cwd),
            env=proc_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        async def read_stream(stream, callback):
            while True:
                line = await stream.readline()
                if not line:
                    break
                decoded_line = line.decode('utf-8', errors='replace').rstrip()
                if decoded_line:
                    callback(decoded_line)

        tasks = []
        if proc.stdout:
            tasks.append(asyncio.create_task(
                read_stream(proc.stdout, log_callback if log_callback else logging.info)
            ))
        if proc.stderr:
            tasks.append(asyncio.create_task(
                read_stream(proc.stderr, log_callback if log_callback else logging.error)
            ))

        try:
            await asyncio.wait_for(proc.wait(), timeout=timeout)
        except asyncio.TimeoutError as err:
            proc.kill()
            raise RuntimeError(f"Timeout expired for command: {cmd}") from err

        await asyncio.gather(*tasks)
        stdout, stderr = await proc.communicate()
        return stdout.decode(), stderr.decode()

    async def run_agi(self, code, log_callback=None, venv: Path = None, type=None):
        """
        Asynchronous version of run_agi for use within an async context.
        """
        pattern = r"await\s+(?:Agi\.)?([^\(]+)\("
        matches = re.findall(pattern, code)
        if not matches:
            message = "Could not determine snippet name from code."
            if log_callback:
                log_callback(message)
            else:
                logging.info(message)
            return "", ""
        snippet_file = os.path.join(self.runenv, f"{matches[0]}-{self.target}.py")
        with open(snippet_file, "w") as file:
            file.write(code)
        cmd = f"uv -q run --no-sync --project {str(venv)} python {snippet_file}"
        result = await AgiEnv._run_bg(cmd, cwd=venv, log_callback=log_callback)
        if log_callback:
            log_callback(f"Process finished with output: {result}")
        else:
            logging.info("Process finished")
        return result

    @staticmethod
    async def run_async(cmd, venv=None, cwd=None, timeout=None, log_callback=None):
        """
        Run a shell command asynchronously inside a virtual environment.
        Returns the last line of combined stdout and stderr outputs.
        """
        if not cwd:
            cwd = venv
        process_env = os.environ.copy()
        venv_path = Path(venv) / ".venv"
        process_env["VIRTUAL_ENV"] = str(venv_path)
        bin_dir = "Scripts" if os.name == "nt" else "bin"
        venv_bin = venv_path / bin_dir
        process_env["PATH"] = str(venv_bin) + os.pathsep + process_env.get("PATH", "")
        shell_executable = "/bin/bash" if os.name != "nt" else None

        if isinstance(cmd, list):
            cmd = " ".join(cmd)

        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd),
            env=process_env,
            executable=shell_executable
        )

        stdout_lines = []
        stderr_lines = []

        async def read_stream(stream, lines, callback):
            while True:
                line = await stream.readline()
                if not line:
                    break
                decoded_line = line.decode().rstrip()
                lines.append(decoded_line)
                if callback:
                    callback(decoded_line)

        stdout_task = asyncio.create_task(
            read_stream(process.stdout, stdout_lines, log_callback if log_callback else logging.info)
        )
        stderr_task = asyncio.create_task(
            read_stream(process.stderr, stderr_lines, log_callback if log_callback else logging.error)
        )

        try:
            await asyncio.wait_for(process.wait(), timeout=timeout)
        except asyncio.TimeoutError as err:
            process.kill()
            raise RuntimeError(f"Timeout expired for command: {cmd}") from err

        await asyncio.gather(stdout_task, stderr_task)

        # Find last non-empty line from stderr first (usually errors), else stdout
        last_line = None
        for line in reversed(stderr_lines):
            if line.strip():
                last_line = line
                break
        if not last_line:
            for line in reversed(stdout_lines):
                if line.strip():
                    last_line = line
                    break

        return last_line

    @staticmethod
    def create_symlink(src: Path, dest: Path):
        try:
            if dest.exists() or dest.is_symlink():
                if dest.is_symlink() and dest.resolve() == src.resolve():
                    logger.info(f"Symlink already exists and is correct: {dest} -> {src}")
                    return
                logger.warning(f"Warning: Destination already exists and is not a symlink: {dest}")
                dest.unlink()
            dest.symlink_to(src, target_is_directory=src.is_dir())
            logger.info(f"Symlink created: {dest} -> {src}")
        except Exception as e:
            logger.error(f"Failed to create symlink {dest} -> {src}: {e}")

    def change_active_app(self, app, install_type=1):
        if app != str(self.active_app.name):
            self.__init__(active_app=app, install_type=install_type, verbose=AgiEnv.verbose)

    @staticmethod
    def is_local(ip):
        """

        Args:
          ip:

        Returns:

        """
        if (
                not ip or ip in AgiEnv._ip_local_cache
        ):  # Check if IP is None, empty, or cached
            return True

        for _, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == socket.AF_INET and ip == addr.address:
                    AgiEnv._ip_local_cache.add(ip)  # Cache the local IP found
                    return True

        return False


    @staticmethod
    def log_remote_line(ip: str, line: str):
        """
        Log a line from remote SSH output with the proper log level.

        Args:
            ip (str): IP address of remote host.
            line (str): One line of output from remote process.
        """
        match = LOG_LEVEL_RE.search(line)
        if match:
            level_name = match.group(1)
            level = getattr(logging, level_name, logging.INFO)
        else:
            # Default to INFO if no level found
            level = logging.INFO

        logging.info(level, f"[{ip}] {line}")

    def set_cluster_credentials(self, credentials: str):
        """Set the AGI_CREDENTIALS environment variable."""
        self.CLUSTER_CREDENTIALS = credentials  # maintain internal state
        self.set_env_var("CLUSTER_CREDENTIALS", credentials)

    def set_openai_api_key(self, api_key: str):
        """Set the OPENAI_API_KEY environment variable."""
        self.OPENAI_API_KEY = api_key
        self.set_env_var("OPENAI_API_KEY", api_key)

    def set_install_type(install_type: int):
        AgiEnv.install_type = install_type
        AgiEnv.set_env_var("INSTALL_TYPE", str(install_type))

    def set_apps_dir(self, apps_dir: Path):
        self.apps_dir = apps_dir
        self.set_env_var("APPS_DIR", apps_dir)

    def has_admin_rights():
        """
        Check if the current process has administrative rights on Windows.

        Returns:
            bool: True if admin, False otherwise.
        """
        try:
            return ctypes.windll.shell32.IsUserAnAdmin()
        except:
            return False

    def create_junction_windows(source: Path, dest: Path):
        """
        Create a directory junction on Windows.

        Args:
            source (Path): The target directory path.
            dest (Path): The destination junction path.
        """
        try:
            # Using the mklink command to create a junction (/J) which doesn't require admin rights.
            subprocess.check_call(['cmd', '/c', 'mklink', '/J', str(dest), str(source)])
            print(f"Created junction: {dest} -> {source}")
        except subprocess.CalledProcessError as e:
            print(f"Failed to create junction. Error: {e}")

    def create_symlink_windows(source: Path, dest: Path):
        """
        Create a symbolic link on Windows, handling permissions and types.

        Args:
            source (Path): Source directory path.
            dest (Path): Destination symlink path.
        """
        # Define necessary Windows API functions and constants
        CreateSymbolicLink = ctypes.windll.kernel32.CreateSymbolicLinkW
        CreateSymbolicLink.restype = wintypes.BOOL
        CreateSymbolicLink.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]

        SYMBOLIC_LINK_FLAG_DIRECTORY = 0x1

        # Check if Developer Mode is enabled or if the process has admin rights
        if not has_admin_rights():
            print(
                "Creating symbolic links on Windows requires administrative privileges or Developer Mode enabled."
            )
            return

        flags = SYMBOLIC_LINK_FLAG_DIRECTORY

        success = CreateSymbolicLink(str(dest), str(source), flags)
        if success:
            print(f"Created symbolic link for .venv: {dest} -> {source}")
        else:
            error_code = ctypes.GetLastError()
            print(
                f"Failed to create symbolic link for .venv. Error code: {error_code}"
            )

    def handle_venv_directory(self, source_venv: Path, dest_venv: Path):
        """
        Create a symbolic link for the .venv directory instead of copying it.

        Args:
            source_venv (Path): Source .venv directory path.
            dest_venv (Path): Destination .venv symbolic link path.
        """
        try:
            if os.name == "nt":
                create_symlink_windows(source_venv, dest_venv)
            else:
                # For Unix-like systems
                os.symlink(source_venv, dest_venv, target_is_directory=True)
                print(f"Created symbolic link for .venv: {dest_venv} -> {source_venv}")
        except OSError as e:
            print(f"Failed to create symbolic link for .venv: {e}")

    def create_rename_map(self, target_project: Path, dest_project: Path) -> dict:
        """
        Create a mapping of old → new names for cloning.
        Includes project names, top-level src folders, worker folders,
        in-file identifiers and class names.
        """
        def cap(s: str) -> str:
            return "".join(p.capitalize() for p in s.split("_"))

        name_tp = target_project.name      # e.g. "flight_project"
        name_dp = dest_project.name        # e.g. "tata_project"
        tp = name_tp[:-8]                  # strip "_project" → "flight"
        dp = name_dp[:-8]                  # → "tata"

        tm = tp.replace("-", "_")
        dm = dp.replace("-", "_")
        tc = cap(tm)                       # "Flight"
        dc = cap(dm)                       # "Tata"

        return {
            # project-level
            name_tp:              name_dp,

            # folder-level (longest keys first)
            f"src/{tm}_worker": f"src/{dm}_worker",
            f"src/{tm}":        f"src/{dm}",

            # sibling-level
            f"{tm}_worker":      f"{dm}_worker",
            tm:                    dm,

            # class-level
            f"{tc}Worker":       f"{dc}Worker",
            f"{tc}Args":         f"{dc}Args",
            tc:                    dc,
        }

    def clone_project(self, target_project: Path, dest_project: Path):
        """
        Clone a project by copying files and directories, applying renaming,
        then cleaning up any leftovers.

        Args:
            target_project: Path under self.apps_dir (e.g. Path("flight_project"))
            dest_project:   Path under self.apps_dir (e.g. Path("tata_project"))
        """

        # normalize names
        if not target_project.name.endswith("_project"):
            target_project = target_project.with_name(target_project.name + "_project")
        if not dest_project.name.endswith("_project"):
            dest_project = dest_project.with_name(dest_project.name + "_project")

        rename_map  = self.create_rename_map(target_project, dest_project)
        source_root = AgiEnv.apps_dir / target_project
        dest_root   = AgiEnv.apps_dir / dest_project

        if not source_root.exists():
            print(f"Source project '{target_project}' does not exist.")
            return
        if dest_root.exists():
            print(f"Destination project '{dest_project}' already exists.")
            return

        gitignore = source_root / ".gitignore"
        if not gitignore.exists():
            print(f"No .gitignore at '{gitignore}'.")
            return
        spec = PathSpec.from_lines(GitWildMatchPattern, gitignore.read_text().splitlines())

        try:
            dest_root.mkdir(parents=True, exist_ok=False)
        except Exception as e:
            print(f"Could not create '{dest_root}': {e}")
            return

        # 1) Recursive clone
        self.clone_directory(source_root, dest_root, rename_map, spec, source_root)

        # 2) Final cleanup
        self._cleanup_rename(dest_root, rename_map)
        self.projects.insert(0, dest_project)

    def clone_directory(self,
                        source_dir: Path,
                        dest_dir: Path,
                        rename_map: dict,
                        spec: PathSpec,
                        source_root: Path):
        """
        Recursively copy + rename directories, files, and contents,
        applying renaming only on exact path segments.
        """
        for item in source_dir.iterdir():
            rel = item.relative_to(source_root).as_posix()

            # Skip files/directories matched by .gitignore spec
            if spec.match_file(rel + ("/" if item.is_dir() else "")):
                continue

            # Rename only full segments of the relative path
            parts = rel.split("/")
            for i, seg in enumerate(parts):
                # Sort rename_map by key length descending to avoid partial conflicts
                for old, new in sorted(rename_map.items(), key=lambda kv: -len(kv[0])):
                    if seg == old:
                        parts[i] = new
                        break

            new_rel = "/".join(parts)
            dst = dest_dir / new_rel
            dst.parent.mkdir(parents=True, exist_ok=True)

            if item.is_dir():
                if item.name == ".venv":
                    # Keep virtual env directory as a symlink
                    os.symlink(item, dst, target_is_directory=True)
                else:
                    self.clone_directory(item, dest_dir, rename_map, spec, source_root)

            elif item.is_file():
                suf = item.suffix.lower()
                base = item.stem

                # Rename file if its basename is in rename_map
                if base in rename_map:
                    dst = dst.with_name(rename_map[base] + item.suffix)

                if suf in (".7z", ".zip"):
                    shutil.copy2(item, dst)

                elif suf == ".py":
                    src = item.read_text(encoding="utf-8")
                    try:
                        tree = ast.parse(src)
                        renamer = ContentRenamer(rename_map)
                        new_tree = renamer.visit(tree)
                        ast.fix_missing_locations(new_tree)
                        out = astor.to_source(new_tree)
                    except SyntaxError:
                        out = src
                    # Whole word replacements in Python source text
                    for old, new in rename_map.items():
                        out = re.sub(rf"\b{re.escape(old)}\b", new, out)
                    dst.write_text(out, encoding="utf-8")

                elif suf in (".toml", ".md", ".txt", ".json", ".yaml", ".yml"):
                    txt = item.read_text(encoding="utf-8")
                    for old, new in rename_map.items():
                        txt = re.sub(rf"\b{re.escape(old)}\b", new, txt)
                    dst.write_text(txt, encoding="utf-8")

                else:
                    shutil.copy2(item, dst)

            elif item.is_symlink():
                target = os.readlink(item)
                os.symlink(target, dst, target_is_directory=item.is_dir())

    def _cleanup_rename(self, root: Path, rename_map: dict):
        """
        1) Rename any leftover file/dir basenames (including .py) that exactly match a key.
        2) Rewrite text files for any straggler content references.
        """
        # build simple name→new map (no slashes)
        simple_map = {old: new for old, new in rename_map.items() if "/" not in old}
        # sort longest first
        sorted_simple = sorted(simple_map.items(), key=lambda kv: len(kv[0]), reverse=True)

        # -- step 1: rename basenames (dirs & files) bottom‑up --
        for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            old = path.name
            for o, n in sorted_simple:
                # directory exactly "flight" → "truc", or "flight_worker" → "truc_worker"
                if old == o or old == f"{o}_worker" or old == f"{o}_project":
                    new_name = old.replace(o, n, 1)
                    path.rename(path.with_name(new_name))
                    break
                # file like "flight.py" → "truc.py"
                if path.is_file() and old.startswith(o + "."):
                    new_name = n + old[len(o):]
                    path.rename(path.with_name(new_name))
                    break

        # -- step 2: rewrite any lingering text references --
        exts = {".py", ".toml", ".md", ".txt", ".json", ".yaml", ".yml"}
        for file in root.rglob("*"):
            if not file.is_file() or file.suffix.lower() not in exts:
                continue
            txt = file.read_text(encoding="utf-8")
            new_txt = txt
            for old, new in rename_map.items():
                new_txt = re.sub(rf"\b{re.escape(old)}\b", new, new_txt)
            if new_txt != txt:
                file.write_text(new_txt, encoding="utf-8")

    def replace_content(self, txt: str, rename_map: dict) -> str:
        for old, new in sorted(rename_map.items(), key=lambda kv: len(kv[0]), reverse=True):
            # only match whole‐word occurrences of `old`
            pattern = re.compile(rf"\b{re.escape(old)}\b")
            txt = pattern.sub(new, txt)
        return txt

    def read_gitignore(self, gitignore_path: Path) -> 'PathSpec':
        from pathspec import PathSpec
        from pathspec.patterns import GitWildMatchPattern
        lines = gitignore_path.read_text(encoding="utf-8").splitlines()
        return PathSpec.from_lines(GitWildMatchPattern, lines)

    def is_valid_ip(self, ip: str) -> bool:
        pattern = re.compile(r"^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$")
        if pattern.match(ip):
            parts = ip.split(".")
            return all(0 <= int(part) <= 255 for part in parts)
        return False

    @property
    def scheduler_ip_address(self):
        return self.scheduler_ip

    def log_remote_line(self, ip, line):
        print(f"[{ip}] {line}")  # Replace with your real remote line logger

    def unzip_data(self, archive_path: Path, extract_to: Path | str = None):
        archive_path = Path(archive_path)
        if not archive_path.exists():
            print(f"Warning: Archive '{archive_path}' does not exist. Skipping extraction.")
            return  # Do not exit, just warn

        # Normalize extract_to to a Path relative to cwd or absolute
        if not extract_to:
            extract_to = Path("data")
        dest = self.home_abs / Path(extract_to)
        dataset = dest / "dataset"

        # Clear existing folder if not empty to avoid extraction errors on second call
        if dataset.exists() and any(dataset.iterdir()):
            print(f"Destination '{dataset}' exists and is not empty. Clearing it before extraction.")
            shutil.rmtree(dataset)
        dest.mkdir(parents=True, exist_ok=True)

        try:
            with py7zr.SevenZipFile(archive_path, mode="r") as archive:
                archive.extractall(path=dest)
            print(f"Successfully extracted '{archive_path}' to '{dest}'.")
        except Exception as e:
            print(f"Failed to extract '{archive_path}': {e}")
            traceback.print_exc()
            sys.exit(1)

    @staticmethod
    def check_internet():
        logging.info(f"Checking internet connectivity...")
        try:
            # HEAD request to Google
            req = urllib.request.Request("https://www.google.com", method="HEAD")
            with urllib.request.urlopen(req, timeout=3) as resp:
                pass  # Success if no exception
        except Exception:
            logging.error(f"No internet connection detected. Aborting.")
            return False
        logging.info(f"Internet connection is OK.")
        return True



class ContentRenamer(ast.NodeTransformer):
    """
    A class that renames identifiers in an abstract syntax tree (AST).
    Attributes:
        rename_map (dict): A mapping of old identifiers to new identifiers.
    """
    def __init__(self, rename_map):
        """
        Initialize the ContentRenamer with the rename_map.

        Args:
            rename_map (dict): Mapping of old names to new names.
        """
        self.rename_map = rename_map

    def visit_Name(self, node):
        # Rename variable and function names
        """
        Visit and potentially rename a Name node in the abstract syntax tree.

        Args:
            self: The current object instance.
            node: The Name node in the abstract syntax tree.

        Returns:
            ast.Node: The modified Name node after potential renaming.

        Note:
            This function modifies the Name node in place.

        Raises:
            None
        """
        if node.id in self.rename_map:
            print(f"Renaming Name: {node.id} ➔ {self.rename_map[node.id]}")
            node.id = self.rename_map[node.id]
        self.generic_visit(node)  # Ensure child nodes are visited
        return node

    def visit_Attribute(self, node):
        # Rename attributes
        """
        Visit and potentially rename an attribute in a node.

        Args:
            node: A node representing an attribute.

        Returns:
            node: The visited node with potential attribute renamed.

        Raises:
            None.
        """
        if node.attr in self.rename_map:
            print(f"Renaming Attribute: {node.attr} ➔ {self.rename_map[node.attr]}")
            node.attr = self.rename_map[node.attr]
        self.generic_visit(node)
        return node

    def visit_FunctionDef(self, node):
        # Rename function names
        """
        Rename a function node based on a provided mapping.

        Args:
            node (ast.FunctionDef): The function node to be processed.

        Returns:
            ast.FunctionDef: The function node with potential name change.
        """
        if node.name in self.rename_map:
            print(f"Renaming Function: {node.name} ➔ {self.rename_map[node.name]}")
            node.name = self.rename_map[node.name]
        self.generic_visit(node)
        return node

    def visit_ClassDef(self, node):
        # Rename class names
        """
        Visit and potentially rename a ClassDef node.

        Args:
            node (ast.ClassDef): The ClassDef node to visit.

        Returns:
            ast.ClassDef: The potentially modified ClassDef node.
        """
        if node.name in self.rename_map:
            print(f"Renaming Class: {node.name} ➔ {self.rename_map[node.name]}")
            node.name = self.rename_map[node.name]
        self.generic_visit(node)
        return node

    def visit_arg(self, node):
        # Rename function argument names
        """
        Visit and potentially rename an argument node.

        Args:
            self: The instance of the class.
            node: The argument node to visit and possibly rename.

        Returns:
            ast.AST: The modified argument node.

        Notes:
            Modifies the argument node in place if its name is found in the rename map.

        Raises:
            None.
        """
        if node.arg in self.rename_map:
            print(f"Renaming Argument: {node.arg} ➔ {self.rename_map[node.arg]}")
            node.arg = self.rename_map[node.arg]
        self.generic_visit(node)
        return node

    def visit_Global(self, node):
        # Rename global variable names
        """
        Visit and potentially rename global variables in the AST node.

        Args:
            self: The instance of the class that contains the renaming logic.
            node: The AST node to visit and potentially rename global variables.

        Returns:
            AST node: The modified AST node with global variable names potentially renamed.
        """
        new_names = []
        for name in node.names:
            if name in self.rename_map:
                print(f"Renaming Global Variable: {name} ➔ {self.rename_map[name]}")
                new_names.append(self.rename_map[name])
            else:
                new_names.append(name)
        node.names = new_names
        self.generic_visit(node)
        return node

    def visit_nonlocal(self, node):
        # Rename nonlocal variable names
        """
        Visit and potentially rename nonlocal variables in the AST node.

        Args:
            self: An instance of the class containing the visit_nonlocal method.
            node: The AST node to visit and potentially modify.

        Returns:
            ast.AST: The modified AST node after visiting and potentially renaming nonlocal variables.
        """
        new_names = []
        for name in node.names:
            if name in self.rename_map:
                print(
                    f"Renaming Nonlocal Variable: {name} ➔ {self.rename_map[name]}"
                )
                new_names.append(self.rename_map[name])
            else:
                new_names.append(name)
        node.names = new_names
        self.generic_visit(node)
        return node

    def visit_Assign(self, node):
        # Rename assigned variable names
        """
        Visit and process an assignment node.

        Args:
            self: The instance of the visitor class.
            node: The assignment node to be visited.

        Returns:
            ast.Node: The visited assignment node.
        """
        self.generic_visit(node)
        return node

    def visit_AnnAssign(self, node):
        # Rename annotated assignments
        """
        Visit and process an AnnAssign node in an abstract syntax tree.

        Args:
            self: The AST visitor object.
            node: The AnnAssign node to be visited.

        Returns:
            AnnAssign: The visited AnnAssign node.
        """
        self.generic_visit(node)
        return node

    def visit_For(self, node):
        # Rename loop variable names
        """
        Visit and potentially rename the target variable in a For loop node.

        Args:
            node (ast.For): The For loop node to visit.

        Returns:
            ast.For: The modified For loop node.

        Note:
            This function may modify the target variable in the For loop node if it exists in the rename map.
        """
        if isinstance(node.target, ast.Name) and node.target.id in self.rename_map:
            print(
                f"Renaming For Loop Variable: {node.target.id} ➔ {self.rename_map[node.target.id]}"
            )
            node.target.id = self.rename_map[node.target.id]
        self.generic_visit(node)
        return node

    def visit_Import(self, node):
        """
        Rename imported modules in 'import module' statements.

        Args:
            node (ast.Import): The import node.
        """
        for alias in node.names:
            original_name = alias.name
            if original_name in self.rename_map:
                print(
                    f"Renaming Import Module: {original_name} ➔ {self.rename_map[original_name]}"
                )
                alias.name = self.rename_map[original_name]
            else:
                # Handle compound module names if necessary
                for old, new in self.rename_map.items():
                    if original_name.startswith(old):
                        print(
                            f"Renaming Import Module: {original_name} ➔ {original_name.replace(old, new, 1)}"
                        )
                        alias.name = original_name.replace(old, new, 1)
                        break
        self.generic_visit(node)
        return node

    def visit_ImportFrom(self, node):
        """
        Rename modules and imported names in 'from module import name' statements.

        Args:
            node (ast.ImportFrom): The import from node.
        """
        # Rename the module being imported from
        if node.module in self.rename_map:
            print(
                f"Renaming ImportFrom Module: {node.module} ➔ {self.rename_map[node.module]}"
            )
            node.module = self.rename_map[node.module]
        else:
            for old, new in self.rename_map.items():
                if node.module and node.module.startswith(old):
                    new_module = node.module.replace(old, new, 1)
                    print(
                        f"Renaming ImportFrom Module: {node.module} ➔ {new_module}"
                    )
                    node.module = new_module
                    break

        # Rename the imported names
        for alias in node.names:
            if alias.name in self.rename_map:
                print(
                    f"Renaming Imported Name: {alias.name} ➔ {self.rename_map[alias.name]}"
                )
                alias.name = self.rename_map[alias.name]
            else:
                for old, new in self.rename_map.items():
                    if alias.name.startswith(old):
                        print(
                            f"Renaming Imported Name: {alias.name} ➔ {alias.name.replace(old, new, 1)}"
                        )
                        alias.name = alias.name.replace(old, new, 1)
                        break
        self.generic_visit(node)
        return node

        import getpass, os, sys, subprocess, signal

        me = getpass.getuser()
        my_pid = os.getpid()