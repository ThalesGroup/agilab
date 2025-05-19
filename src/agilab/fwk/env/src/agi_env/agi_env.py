import ast
import asyncio
import getpass
import os
import re
import shutil
import subprocess
import sys
import traceback
from pathlib import Path, PureWindowsPath, PurePosixPath
from dotenv import dotenv_values, set_key
from pathspec import PathSpec
import tomlkit
import logging


class AgiEnv:
    install_type = None
    apps_dir = None
    app = None
    module = None
    GUI_NROW = None
    GUI_SAMPLING = None
    init_done = False

    def __init__(self, install_type: int = None, apps_dir: Path = None,
                 active_app: Path | str = None, active_module: Path = None, verbose: int = 0):
        self.verbose = verbose
        AgiEnv.init_logging(verbose)  # Initialize logging here

        self.is_managed_pc = getpass.getuser().startswith("T0")
        self.agi_resources = Path("resources/.agilab")
        self.home_abs = Path.home() / "MyApp" if self.is_managed_pc else Path.home()

        self.resource_path = self.home_abs / self.agi_resources.name
        env_path = self.resource_path / ".env"
        self.envars = dotenv_values(dotenv_path=env_path, verbose=verbose)
        envars = self.envars

        if install_type:
            if isinstance(install_type, str):
                install_type = int(install_type)
            self.install_type = install_type
        else:
            install_type = 1 if ("site-packages" not in __file__ or sys.prefix.endswith("gui/.venv")) else 0
            self.install_type = install_type

        logging.info(f"install_type: {}install_type}")

        self.agi_root = AgiEnv.locate_agi_installation(verbose)

        if install_type:
            self.agi_fwk_env_path = self.agi_root / "fwk/env"
            resource_path = self.agi_fwk_env_path / "src/agi_env" / self.agi_resources
        else:
            head, sep, _ = __file__.partition("site-packages")
            if not sep:
                raise ValueError("site-packages not in", __file__)
            self.agi_fwk_env_path = Path(head + sep)
            resource_path = self.agi_fwk_env_path / "agi_env" / self.agi_resources

        if install_type == 2:
            return

        if not self.agi_fwk_env_path.exists():
            raise RuntimeError("Your Agilab installation is not valid")

        self._init_resources(resource_path)

        if active_module:
            if isinstance(active_module, Path):
                self.module = active_module.stem
                appsdir = self._determine_apps_dir(active_module)
                if apps_dir:
                    logging.info("Warning: apps_dir will be determined from active_module path")
                apps_dir = appsdir
                app = apps_dir.name
                if active_app:
                    logging.info("Warning: active_app will be determined from active_module path")
                active_app = app
            else:
                logging.info("active_module must be of type 'Path'")
                exit(1)
        else:
            self.module = None

        if not apps_dir:
            apps_dir = envars.get("APPS_DIR", 'apps')
        else:
            set_key(dotenv_path=env_path, key_to_set="APPS_DIR", value_to_set=str(apps_dir))

        apps_dir = Path(apps_dir)

        try:
            if apps_dir.exists():
                self.apps_dir = apps_dir
            elif install_type:
                self.apps_dir = self.agi_root / apps_dir
            else:
                os.makedirs(str(apps_dir), exist_ok=True)
        except FileNotFoundError:
            logging.err("apps_dir not found:", apps_dir)
            exit(1)

        self.GUI_NROW = int(envars.get("GUI_NROW", 1000))
        self.GUI_SAMPLING = int(envars.get("GUI_SAMPLING", 20))

        if not active_app:
            active_app = envars.get("APP_DEFAULT", 'flight_project')

        if isinstance(active_app, str):
            if not active_app.endswith('_project'):
                active_app = active_app + '_project'
            app_path = apps_dir / active_app
            if app_path.exists():
                self.app = active_app
            src_apps = self.agi_root / "apps"
            if not install_type:
                if not apps_dir.exists():
                    shutil.copytree(src_apps, apps_dir)
                else:
                    self.copy_missing(src_apps, Path(os.getcwd()) / apps_dir)
            module = active_app.replace("_project", "").replace("-", "_")
        else:
            apps_dir = self._determine_apps_dir(active_app)
            module = apps_dir.name.replace("_project", "").replace("-", "_")

        if not self.module:
            self.module = module

        AgiEnv.apps_dir = self.apps_dir
        self.app_path = self.apps_dir / active_app
        self.app_src = self.app_path / "src"
        self.target_worker = f"{self.module}_worker"
        self.worker_path = self.app_src / self.target_worker / f"{self.target_worker}.py"
        self.module_path = self.app_src / self.module / f"{self.module}.py"
        self.pyproject = self.worker_path.parent / "pyproject.toml"
        self.uvproject = self.worker_path.parent / "uv.toml"

        self.agi_core = self.resolve_packages_path_in_toml()

        self.projects = self.get_projects(self.apps_dir)

        if not self.projects:
            logging.info(f"Could not find any target project app in {self.agi_root / 'apps'}.")

        envars = self.envars
        self.credantials = envars.get("CLUSTER_CREDENTIALS", getpass.getuser())
        credantials = self.credantials.split(":")
        self.user = credantials[0]
        self.password = credantials[1] if len(credantials) > 1 else None
        self.python_version = envars.get("AGI_PYTHON_VERSION", "3.12.9")

        os.makedirs(AgiEnv.apps_dir, exist_ok=True)
        if self.install_type:
            self.core_src = self.agi_root / "fwk/core/src"
        else:
            self.core_src = self.agi_root
        self.core_root = self.core_src.parent
        self.env_src = self.core_root.parent / "env/src"
        self.agi_core = self.core_src / "agi_core"
        self.workers_root = self.agi_core / "workers"
        self.manager_root = self.agi_core / "managers"
        self.setup_app = self.app_path / "setup"
        self.setup_core_rel = "agi_worker/setup"
        self.setup_core = self.workers_root / self.setup_core_rel

        path = str(self.core_src)
        if path not in sys.path:
            sys.path.insert(0, path)

        if isinstance(self.module, Path):
            self.module_path = self.module.expanduser().resolve()
        else:
            self.module_path = self._determine_module_path(self.module)
        self.target = self.module_path.stem

        self.AGILAB_SHARE = Path(envars.get("AGI_SHARE_DIR", "data"))
        self.data_dir = self.AGILAB_SHARE / self.target
        self.dataframes_path = self.data_dir / "dataframes"

        self._init_projects()

        self.scheduler_ip = envars.get("AGI_SCHEDULER_IP", "127.0.0.1")
        if not self.is_valid_ip(self.scheduler_ip):
            raise ValueError(f"Invalid scheduler IP address: {self.scheduler_ip}")

        if self.install_type:
            self.help_path = str(self.agi_root / "../docs/html")
        else:
            self.help_path = "https://thalesgroup.github.io/agilab"

        self.AGILAB_SHARE = Path(envars.get("AGI_SHARE_DIR", self.home_abs / "data"))

        target_class = "".join(x.title() for x in self.target.split("_"))
        worker_class = target_class + "Worker"
        self.target_class = target_class
        self.target_worker_class = worker_class

        self.base_worker_cls, self.base_worker_module = self.get_base_worker_cls(
            self.worker_path, worker_class
        )
        self.workers_packages_prefix = "agi_core.workers."

        if not self.worker_path.exists():
            logging.info(f"Missing {self.target_worker_class} definition; should be in {self.worker_path} but it does not exist")
            exit(1)

        app_src_path = self.app_src
        app_src = str(app_src_path)
        if app_src not in sys.path:
            sys.path.insert(0, app_src)
        app_src_path.mkdir(parents=True, exist_ok=True)
        self.app_src_path = self.core_root.parent.parent / app_src_path

        wenv_rel = Path("wenv") / self.target_worker
        self.wenv_rel = wenv_rel
        self.wenv_abs = self.home_abs / wenv_rel
        self.wenv_target_worker = self.wenv_abs
        distribution_tree = self.wenv_abs / "distribution_tree.json"
        self.post_install = Path("src") / self.target_worker / "post_install.py"
        self.pre_install = Path("src") / self.target_worker / "pre_install.py"
        if distribution_tree.exists():
            distribution_tree.unlink()
        self.distribution_tree = distribution_tree

        if AgiEnv.install_type != 3:
            self.init_envars_app(self.envars)
            self._init_apps()

        if not self.wenv_abs.exists():
            os.makedirs(self.wenv_abs)

        if os.name == "nt":
            self.export_local_bin = 'set PATH=%USERPROFILE%\\.local\\bin;%PATH% &&'
        else:
            self.export_local_bin = 'export PATH="$HOME/.local/bin:$PATH";'

    @staticmethod
    def init_logging(verbosity: int = 0):
        """
        Initialize logging based on verbosity:
        0 = WARNING (default),
        1 = INFO,
        2 or more = DEBUG
        """
        level = logging.WARNING
        if verbosity >= 2:
            level = logging.DEBUG
        elif verbosity == 1:
            level = logging.INFO

        logging.basicConfig(
            level=level,
            format="%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%H:%M:%S"
        )
        logging.debug(f"Logging initialized at level {logging.getLevelName(level)}")

    def active(self, target, install_type):
        if self.module != target:
            self.change_active_app(target + '_project', install_type)

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
            user_message += f"\n*Error Type:* `{error_type}`\n"
            formatted_errors.append(user_message)
        return formatted_errors

    def set_env_var(self, key: str, value: str):
        self.envars[key] = value
        os.environ[key] = str(value)
        self._update_env_file({key: value})

    @staticmethod
    def locate_agi_installation(verbose=False):
        if os.name == "nt":
            where_is_agi = Path(os.getenv("LOCALAPPDATA", "")) / "agilab/.agi-path"
        else:
            where_is_agi = Path.home() / ".local/share/agilab/.agi-path"

        if where_is_agi.exists():
            try:
                with where_is_agi.open("r", encoding="utf-8-sig") as f:
                    install_path = f.read().strip()
                    agilab_path = Path(install_path)
                    if install_path and agilab_path.exists():
                        if verbose:
                            logging.info(f"Run Agilab: {install_path}")
                        return agilab_path
                    else:
                        raise ValueError("Installation path file is empty or invalid.")
            except FileNotFoundError:
                logging.err(f"File {where_is_agi} does not exist.")
            except PermissionError:
                logging.err(f"Permission denied when accessing {where_is_agi}.")
            except Exception as e:
                logging.err(f"An error occurred: {e}")

        for p in sys.path_importer_cache:
            if p.endswith("AGILAB.py"):
                base_dir = os.path.dirname(p).replace('_gui', 'lab')
                if verbose:
                    logging.info(f"Fallback agilab path found: {base_dir}")
                return Path(base_dir)
        logging.info("Falling back to current working directory")
        return Path(os.getcwd())

    def copy_missing(self, src: Path, dst: Path):
        dst.mkdir(parents=True, exist_ok=True)
        for item in src.iterdir():
            src_item = item
            dst_item = dst / item.name
            if src_item.is_dir():
                self.copy_missing(src_item, dst_item)
            else:
                if not dst_item.exists():
                    shutil.copy2(src_item, dst_item)

    def _update_env_file(self, updates: dict):
        env_file = self.resource_path / ".env"
        os.makedirs(env_file.parent, exist_ok=True)
        env_file.touch(exist_ok=True)
        for k, v in updates.items():
            set_key(str(env_file), k, str(v), quote_mode="never")

    def _init_resources(self, resources_path):
        src_env_path = resources_path / ".env"
        dest_env_file = self.resource_path / ".env"
        if not src_env_path.exists():
            msg = f"Installation issue: {src_env_path} is missing!"
            logging.info(msg)
            raise RuntimeError(msg)
        if not dest_env_file.exists():
            os.makedirs(dest_env_file.parent, exist_ok=True)
            shutil.copy(src_env_path, dest_env_file)
        for root, dirs, files in os.walk(resources_path):
            for file in files:
                src_file = Path(root) / file
                relative_path = src_file.relative_to(resources_path)
                dest_file = self.resource_path / relative_path
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                if not dest_file.exists():
                    shutil.copy(src_file, dest_file)


    def _init_projects(self):
        self.projects = self.get_projects(self.apps_dir)
        for idx, project in enumerate(self.projects):
            if self.target == project[:-8].replace("-", "_"):
                self.app_path = AgiEnv.apps_dir / project
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
        module_path = self.apps_dir / project_name / "src" / module_name / (module_name + ".py")
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
            logging.err(f"Error reading module file {module_path}: {e}")
            return []

        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            if self.verbose:
                logging.err(f"Syntax error parsing {module_path}: {e}")
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
            if self.verbose:
                logging.err(f"Syntax error during import mapping: {e}")
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
        self.AGILAB_VIEWS_ABS = Path(envars.get("AGI_VIEWS_DIR", self.agi_root / "views"))
        self.AGILAB_VIEWS_REL = Path(envars.get("AGI_VIEWS_DIR", "agi/_"))
        if self.install_type == 0:
            self.copilot_file = self.agi_root / "agi_gui/agi_copilot.py"
        else:
            self.copilot_file = self.agi_root / "fwk/gui/src/agi_gui/agi_copilot.py"

    def resolve_packages_path_in_toml(self):
        agi_root = self.agi_root
        pyproject_file = self.pyproject
        if not pyproject_file.exists():
            raise FileNotFoundError(f"pyproject.toml not found in {self.app_path}")

        text = pyproject_file.read_text(encoding="utf-8")
        doc = tomlkit.parse(text)

        try:
            uv = doc["tool"]["uv"]
        except KeyError:
            raise RuntimeError("Could not find [tool.uv] section in the TOML")

        if "sources" not in uv or not isinstance(uv["sources"], tomlkit.items.Table):
            raise RuntimeError("Could not find [tool.uv.sources] in the TOML")

        sources = uv["sources"]

        agi_core_path = str((agi_root / "fwk" / "core").resolve())
        tbl = tomlkit.inline_table()
        tbl["path"] = agi_core_path
        tbl["editable"] = True

        sources["agi-core"] = tbl

        pyproject_file.write_text(tomlkit.dumps(doc), encoding="utf-8")

        if self.verbose:
            logging.info(f"Update: {pyproject_file}")

        return agi_root / "fwk" / "core"

    def copy_missing(self, src: Path, dst: Path):
        dst.mkdir(parents=True, exist_ok=True)
        for item in src.iterdir():
            src_item = item
            dst_item = dst / item.name
            if src_item.is_dir():
                self.copy_missing(src_item, dst_item)
            else:
                if not dst_item.exists():
                    shutil.copy2(src_item, dst_item)

    def _init_apps(self):
        app_settings_file = self.app_src_path / "app_settings.toml"
        app_settings_file.touch(exist_ok=True)
        self.app_settings_file = app_settings_file

        args_ui_snippet = self.app_src_path / "args_ui_snippet.py"
        args_ui_snippet.touch(exist_ok=True)
        self.args_ui_snippet = args_ui_snippet

        self.gitignore_file = self.app_path / ".gitignore"
        dest = self.resource_path
        if self.install_type:
            shutil.copytree(self.core_root.parent / "gui/src/agi_gui" / self.agi_resources, dest, dirs_exist_ok=True)
        else:
            shutil.copytree(self.agi_root.parent / "agi_gui" / self.agi_resources, dest, dirs_exist_ok=True)

    @staticmethod
    def normalize_path(path):
        from pathlib import Path, PureWindowsPath, PurePosixPath
        import os

        p = Path(path)
        if os.name == "nt":
            return str(PureWindowsPath(p))
        else:
            return str(PurePosixPath(p))

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
    def run(cmd, venv, cwd=None, timeout=None, wait=True, log_callback=None):
        """
        Run a shell command synchronously inside a virtual environment.

        Args:
            cmd (str or list): Command to run.
            venv (str or Path): Path to the virtual environment or project root.
            cwd (str or Path): Working directory.
            timeout (float): Timeout in seconds.
            wait (bool): Wait for process to finish.
            log_callback (callable): Function to receive stdout/stderr lines.

        Returns:
            str: Captured stdout if wait=True, else empty string.
        """
        if not cwd:
            cwd = venv
        process_env = os.environ.copy()
        venv_path = Path(venv)
        if not (venv_path / "bin").exists() and venv_path.name != ".venv":
            venv_path = venv_path / ".venv"

        process_env["VIRTUAL_ENV"] = str(venv_path)
        bin_dir = "Scripts" if os.name == "nt" else "bin""bin"
        venv_bin = venv_path / bin_dir
        process_env["PATH"] = str(venv_bin) + os.pathsep + process_env.get("PATH", "")

        shell_executable = "/bin/bash" if os.name != "nt" else None

        if wait:
            try:
                logging.info(f"Executing locally:\n{cmd}\nvenv{venv}", level=2)
                process = subprocess.Popen(
                    cmd,
                    shell=True,
                    cwd=str(cwd),
                    env=process_env,
                    text=True,
                    executable=shell_executable,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                # Read stderr line by line and call log_callback or logging.info
                while True:
                    if process.stderr:
                        line = process.stderr.readline().rstrip()
                        if line:
                            if log_callback:
                                log_callback(line)
                            else:
                                logging.info(line)
                        if line == '' and process.poll() is not None:
                            break
                    else:
                        break
                process.wait(timeout=timeout)
                result = process.stdout.read() if process.stdout else ""
                AgiEnv._handle_result(result)
            except Exception as e:
                logging.error(traceback.format_exc())
                raise RuntimeError(f"Command execution error: {e}") from e

    @staticmethod
    def _handle_result(result):
        """Handle the result of a command execution.

        Args:
            result (dict or str): A dictionary with keys "stdout" (standard output)
                                  and "stdin" (standard input), or a string.
        """
        # ANSI escape codes for colors
        GREEN = "\033[32m"
        BLUE = "\033[34m"
        RESET = "\033[0m"
        if result:
            if isinstance(result, dict):
                stdout_output = result.get("stdout", "")
                logging.info(f"{GREEN}{stdout_output}{RESET}")
                stdin_output = result.get("stdin", "")
                logging.info(f"{BLUE}{stdin_output}{RESET}")
            elif isinstance(result, str):
                logging.info(result)


    @staticmethod
    def create_symlink(source: Path, dest: Path):
        """
        Create a symlink from dest to source if not already existing.

        Args:
            source (Path): Source path.
            dest (Path): Destination symlink path.
        """
        try:
            source_resolved = source.resolve(strict=True)
        except FileNotFoundError as e:
            raise FileNotFoundError(f"Source path does not exist: {source}\n{e}") from e

        if dest.exists() or dest.is_symlink():
            if dest.is_symlink():
                try:
                    existing_target = dest.resolve(strict=True)
                    if existing_target == source_resolved:
                        logging.info(f"Symlink already exists and is correct: {dest} -> {source_resolved}")
                        return
                    else:
                        logging.info(f"Warning: Symlink at {dest} points to {existing_target}, expected {source_resolved}.")
                        return
                except RecursionError:
                    raise RecursionError(f"Detected symlink loop while resolving {dest}.")
                except FileNotFoundError:
                    logging.info(f"Warning: Symlink at {dest} is broken.")
                    return
            else:
                logging.info(f"Warning: Destination already exists and is not a symlink: {dest}")
                return

        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                is_dir = source_resolved.is_dir()
                os.symlink(str(source_resolved), str(dest), target_is_directory=is_dir)
            else:
                os.symlink(str(source_resolved), str(dest))
            logging.info(f"Symlink created: {dest} -> {source_resolved}")
        except OSError as e:
            if os.name == "nt":
                raise OSError(
                    "Failed to create symlink on Windows. Ensure admin rights or Developer Mode enabled."
                ) from e
            else:
                raise OSError(f"Failed to create symlink: {e}") from e

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
                decoded_line = line.decode().rstrip()
                if callback:
                    callback(decoded_line)
                else:
                    print(decoded_line)

        tasks = []
        if proc.stdout:
            tasks.append(asyncio.create_task(
                read_stream(proc.stdout, lambda msg: log_callback(msg) if log_callback else print(msg))
            ))
        if proc.stderr:
            tasks.append(asyncio.create_task(
                read_stream(proc.stderr, lambda msg: log_callback(msg) if log_callback else print(msg))
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
                print(message)
            return "", ""
        snippet_file = os.path.join(self.runenv, f"{matches[0]}-{self.target}.py")
        with open(snippet_file, "w") as file:
            file.write(code)
        cmd = f"uv run --project {str(venv)} python {snippet_file}"
        # Await _run_bg directly without asyncio.run()
        result = await AgiEnv._run_bg(cmd, venv=venv, log_callback=log_callback)
        if log_callback:
            log_callback(f"Process finished with output: {result}")
        else:
            print("test")
        return result


    @staticmethod
    async def run_async(cmd, venv=None, cwd=None, timeout=None, log_callback=None):
        """
        Run a shell command asynchronously inside a virtual environment.

        Args:
            cmd (str or list): Command to run.
            venv (str or Path): Virtual environment or project root.
            cwd (str or Path): Working directory.
            timeout (float): Timeout in seconds.
            log_callback (callable): Function to receive stdout/stderr lines.
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

        async def read_stream(stream, callback):
            while True:
                line = await stream.readline()
                if not line:
                    break
                decoded_line = line.decode().rstrip()
                callback(decoded_line)

        stdout_task = asyncio.create_task(
            read_stream(process.stdout, log_callback if log_callback else print)
        )
        stderr_task = asyncio.create_task(
            read_stream(process.stderr, log_callback if log_callback else print)
        )

        try:
            await asyncio.wait_for(process.wait(), timeout=timeout)
        except asyncio.TimeoutError as err:
            process.kill()
            raise RuntimeError(f"Timeout expired for command: {cmd}") from err

        await asyncio.gather(stdout_task, stderr_task)