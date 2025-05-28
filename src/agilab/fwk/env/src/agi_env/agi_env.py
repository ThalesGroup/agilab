from IPython.core.ultratb import FormattedTB
import ast
import asyncio
import getpass
import os
import re
import shutil
import subprocess
import sys
import asyncssh
from asyncssh.process import ProcessError
from contextlib import asynccontextmanager
import traceback
from pathlib import Path, PureWindowsPath, PurePosixPath
from dotenv import dotenv_values, set_key
import tomlkit
import logging
import inspect
import errno

# Compile regex once globally
LOG_LEVEL_RE = re.compile(r'\b(INFO|ERROR|WARNING|DEBUG|CRITICAL)\b')

# Patch for IPython ≥8.37 (theme_name) vs ≤8.36 (color_scheme)
_sig = inspect.signature(FormattedTB.__init__).parameters
_tb_kwargs = dict(mode='Verbose', call_pdb=True)
if 'color_scheme' in _sig:
    _tb_kwargs['color_scheme'] = 'Linux'
else:
    _tb_kwargs['theme_name'] = 'Linux'

sys.excepthook = FormattedTB(**_tb_kwargs)

logger = logging.getLogger(__name__)


class AgiEnv:
    install_type = None
    apps_dir = None
    app = None
    module = None
    GUI_NROW = None
    GUI_SAMPLING = None
    init_done = False

    def init_logging(self, verbosity: int = None):
        """
        Initialize logging with a level based on verbosity:
        0 = WARNING, 1 = INFO, 2 or more = DEBUG
        INFO and DEBUG levels go to stdout; WARNING and above go to stderr.
        """
        if verbosity is None:
            verbosity = 0


        # Root logger level based on verbosity
        root_level = logging.DEBUG if verbosity >= 2 else logging.INFO if verbosity == 1 else logging.WARNING

        # Cap distributed logs at CRITICAL (silent)
        sys_level = logging.INFO

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

        # agilab fwk
        logging.getLogger("agi_runner").setLevel(app_level)
        logging.getLogger("agi_worker").setLevel(app_level)
        logging.getLogger("agi_manager").setLevel(app_level)
        logging.getLogger("agi_env").setLevel(app_level)
        logging.getLogger("dag_worker").setLevel(app_level)
        logging.getLogger("pandas_worker").setLevel(app_level)
        logging.getLogger("polars_worker").setLevel(app_level)
        logging.getLogger("agent_worker").setLevel(app_level)

        # Remove existing handlers to avoid duplicate logs
        for handler in root.handlers[:]:
            root.removeHandler(handler)

        fmt = logging.Formatter(
            "%(asctime)s %(levelname)s %(message)s",
            datefmt="%H:%M:%S"
        )

        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setLevel(logging.DEBUG)  # always capture debug and above on stdout
        stdout_handler.setFormatter(fmt)

        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setLevel(logging.WARNING)  # warnings and errors on stderr
        stderr_handler.setFormatter(fmt)

        root.addHandler(stdout_handler)
        root.addHandler(stderr_handler)

        logging.debug(f"Logging initialized at level {logging.getLevelName(root_level)}")

    def __init__(self, install_type: int = None, apps_dir: Path = None,
                 active_app: Path | str = None, active_module: Path = None, verbose: int = None):

        AgiEnv.verbose = verbose
        self.init_logging(verbose)

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
            if active_app:
                self.module = active_app.replace("_project", "")
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
            logging.error("apps_dir not found: %s", apps_dir)
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
            self.module = module.replace('-', '_')

        AgiEnv.apps_dir = self.apps_dir
        self.app_abs = self.apps_dir / active_app
        self.app_src = self.app_abs / "src"
        self.target_worker = f"{self.module}_worker"
        self.app_pyproject = self.app_abs / "pyproject.toml"
        self.worker_path = self.app_src / self.target_worker / f"{self.target_worker}.py"
        self.module_path = self.app_src / self.module / f"{self.module}.py"
        self.worker_pyproject = self.worker_path.parent / "pyproject.toml"
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
        self.setup_app = self.app_abs / "setup"
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

        app_src = self.app_src
        app_src.mkdir(parents=True, exist_ok=True)
        app_src_str = str(app_src)
        if app_src_str not in sys.path:
            sys.path.insert(0, app_src_str)
        self.app_src = self.core_root.parent.parent / app_src
        self.app_abs = self.app_src.parent

        wenv_rel = Path("wenv") / self.target_worker
        self.wenv_rel = wenv_rel
        self.wenv_abs = self.home_abs / wenv_rel
        if not self.wenv_abs.exists():
            os.makedirs(self.wenv_abs, exist_ok=True)
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

        if os.name == "nt":
            self.export_local_bin = 'set PATH=%USERPROFILE%\\.local\\bin;%PATH% &&'
        else:
            self.export_local_bin = 'export PATH="$HOME/.local/bin:$PATH";'
        self._ssh_connections = {}

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
            user_message += f"*Error Type:* `{error_type}`"
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
                        return agilab_path
                    else:
                        raise ValueError("Installation path file is empty or invalid.")
            except FileNotFoundError:
                logging.error(f"File {where_is_agi} does not exist.")
            except PermissionError:
                logging.error(f"Permission denied when accessing {where_is_agi}.")
            except Exception as e:
                logging.error(f"An error occurred: {e}")

        for p in sys.path_importer_cache:
            if p.endswith("agi_env"):
                base_dir = os.path.dirname(p).replace('_env', 'lab')
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
            logging.error(f"Error reading module file {module_path}: {e}")
            return []

        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            if self.verbose:
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
            if self.verbose:
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
        import tomli  # Use tomli for reading TOML files

        chars = ["p", "c", "d", "r"]
        reversed_chars = reversed(list(enumerate(chars)))
        with open(self.worker_pyproject, "rb") as file:
            pyproject_data = tomli.load(file)

        dependencies = pyproject_data.get("project", {}).get("dependencies", [])
        if len([dep for dep in dependencies if dep.lower().startswith("cu")]) > 0:
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
        self.AGILAB_VIEWS_ABS = Path(envars.get("AGI_VIEWS_DIR", self.agi_root / "views"))
        self.AGILAB_VIEWS_REL = Path(envars.get("AGI_VIEWS_DIR", "agi/_"))
        if self.install_type == 0:
            self.copilot_file = self.agi_root / "agi_gui/agi_copilot.py"
        else:
            self.copilot_file = self.agi_root / "fwk/gui/src/agi_gui/agi_copilot.py"

    def resolve_packages_path_in_toml(self):
        agi_root = self.agi_root
        for file in [self.worker_pyproject, self.app_pyproject]:
            if not file.exists():
                raise FileNotFoundError(f"{file} not found in {self.app_abs}")

            text = file.read_text(encoding="utf-8")
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

            try:
                file.write_text(tomlkit.dumps(doc), encoding="utf-8")
            except Exception as e:
                print(f"Error writing file: {e}")
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
        app_settings_file = self.app_src / "app_settings.toml"
        app_settings_file.touch(exist_ok=True)
        self.app_settings_file = app_settings_file

        args_ui_snippet = self.app_src / "args_ui_snippet.py"
        args_ui_snippet.touch(exist_ok=True)
        self.args_ui_snippet = args_ui_snippet

        self.gitignore_file = self.app_abs / ".gitignore"
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
        logging.error(msg)

    @staticmethod
    async def run(cmd, venv, cwd=None, timeout=None, wait=True, log_callback=None):
        """
        Run a shell command synchronously inside a virtual environment.
        Log stdout lines as info, stderr lines as error.

        Returns full stdout string.
        """
        AgiEnv.log_info(f"Executing in {venv}: {cmd}")

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
                process = subprocess.Popen(
                    cmd,
                    shell=True,
                    cwd=str(cwd),
                    env=process_env,
                    text=True,
                    executable=shell_executable,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=1,
                    universal_newlines=True,
                )

                result = ""
                while True:
                    out_line = process.stdout.readline()
                    err_line = process.stderr.readline()

                    result += out_line

                    if out_line:
                        line = out_line.rstrip("\n")
                        if log_callback:
                            log_callback(line)
                        else:
                            AgiEnv.log_info(line)

                    if err_line:
                        line = err_line.rstrip("\n")
                        msg_type = line[:4]
                        if log_callback:
                            log_callback(line)
                        elif msg_type == "INFO":
                            AgiEnv.log_info(line)
                        else:
                            AgiEnv.log_error(line)

                    if out_line == '' and err_line == '' and process.poll() is not None:
                        break

                process.wait(timeout=timeout)
                AgiEnv.log_info(f"Command completed with exit code {process.returncode}")
                return result

            except subprocess.TimeoutExpired:
                process.kill()
                raise RuntimeError(f"Command timed out after {timeout} seconds: {cmd}")
            except Exception as e:
                logging.error(traceback.format_exc())
                raise RuntimeError(f"Command execution error: {e}") from e
        else:
            subprocess.Popen(
                cmd,
                shell=True,
                cwd=str(cwd),
                env=process_env,
                executable=shell_executable,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
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
                decoded_line = line.decode().rstrip()
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
        cmd = f"uv -q run --project {str(venv)} python {snippet_file}"
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
            read_stream(process.stdout, log_callback if log_callback else logging.info)
        )
        stderr_task = asyncio.create_task(
            read_stream(process.stderr, log_callback if log_callback else logging.error)
        )

        try:
            await asyncio.wait_for(process.wait(), timeout=timeout)
        except asyncio.TimeoutError as err:
            process.kill()
            raise RuntimeError(f"Timeout expired for command: {cmd}") from err

        await asyncio.gather(stdout_task, stderr_task)

    @staticmethod
    def create_symlink(source: Path, dest: Path):
        """
        Create a symlink from dest to source if not already existing.
        """
        try:
            source_resolved = source.resolve(strict=True)
        except FileNotFoundError as e:
            raise FileNotFoundError(f"Source path does not exist: {source} {e}") from e

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

    def change_active_app(self, app, install_type=1):
        if isinstance(app, str):
            app_name = app
        elif isinstance(app, Path):
            app_name = app.name
        else:
            raise TypeError(f"Invalid app type (<str>|<Path>): {type(app)}")

        if app_name != self.app:
            self.__init__(active_app=app_name, install_type=install_type, verbose=self.verbose)

    @asynccontextmanager
    async def get_ssh_connection(self, ip: str, timeout_sec: int = 5):
        if not self.user:
            raise ValueError("SSH username is not configured. Please set 'user' in your .env file.")

        conn = self._ssh_connections.get(ip)
        if conn and not conn.is_closed():
            yield conn
            return

        try:
            conn = await asyncio.wait_for(
                asyncssh.connect(
                    ip,
                    username=self.user,
                    password=self.password,
                    known_hosts=None,
                    client_keys=None,
                ),
                timeout=timeout_sec
            )
            self._ssh_connections[ip] = conn
            yield conn

        except asyncio.TimeoutError:
            err_msg = f"Connection to {ip} timed out after {timeout_sec} seconds."
            self.log_error(err_msg)
            raise ConnectionError(err_msg)

        except asyncssh.PermissionDenied:
            err_msg = f"Authentication failed for SSH user '{self.user}' on host {ip}."
            self.log_error(err_msg)
            raise ConnectionError(err_msg)

        except OSError as e:
            if e.errno in (errno.EHOSTUNREACH, 113):
                err_msg = (
                    f"Unable to connect to {ip} on SSH port 22. "
                    "Please check that the device is powered on, network cable connected, and SSH service running."
                )
                self.log_error(err_msg)
                raise ConnectionError(err_msg)
            else:
                raise

        except asyncssh.Error:
            err_msg = (
                f"Could not connect to {ip}. Please check device is reachable, network cable connected, and SSH service running."
            )
            self.log_error(err_msg)
            raise ConnectionError(err_msg)

    async def exec_ssh(self, ip: str, cmd: str) -> str:
        try:
            async with self.get_ssh_connection(ip) as conn:
                result = await conn.run(cmd, check=True)
                stdout = result.stdout
                if isinstance(stdout, bytes):
                    stdout = stdout.decode('utf-8', errors='replace')
                self.log_info(f"[{ip}] {cmd}: {stdout.strip()}")
                return stdout.strip()

        except ProcessError as e:
            stdout = e.stdout
            stderr = e.stderr
            if isinstance(stdout, bytes):
                stdout = stdout.decode('utf-8', errors='replace')
            if isinstance(stderr, bytes):
                stderr = stderr.decode('utf-8', errors='replace')
            self.log_error(f"[{ip}] SSH command stdout: {stdout.strip()}")
            self.log_error(f"[{ip}] SSH command stderr: {stderr.strip()}")
            raise

        except (asyncssh.Error, OSError) as e:
            self.log_error(f"[{ip}] SSH command failed: {e}")
            raise

    async def exec_ssh_async(self, ip: str, cmd: str):
        async with self.get_ssh_connection(ip) as conn:
            process = await conn.create_process(cmd)

        async def read_stream(stream):
            async for line in stream:
                if isinstance(line, bytes):
                    decoded_line = line.decode('utf-8', errors='replace').rstrip()
                else:
                    decoded_line = line.rstrip()
                if decoded_line:
                    self.log_remote_line(ip, decoded_line)

            await asyncio.gather(
                read_stream(process.stdout, self.log_info),
                read_stream(process.stderr, self.log_error)
            )

    async def send_file(
            self,
            ip: str,
            local_path: Path,
            remote_path: Path,
            user: str = None,
            password: str = None
    ):
        if not user:
            user = self.user
        if not password:
            password = self.password

        user_at_ip = f"{user}@{ip}" if user else ip
        remote = f"{user_at_ip}:{remote_path}"

        cmd = []

        if password and os.name != "nt":
            cmd += ["sshpass", "-p", password]

        cmd += ["scp", str(local_path), remote]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                self.log_error(f"SCP failed sending {local_path} to {remote}: {stderr.decode().strip()}")
                raise ConnectionError(f"SCP error: {stderr.decode().strip()}")

            self.log_info(f"Sent file {local_path} to {remote}")

        except Exception as e:
            self.log_error(f"Unexpected error during SCP of {local_path} to {remote}: {e}")
            raise

    async def send_files(self, ip: str, files: list[Path], remote_dir: Path, user: str = None):
        tasks = []
        for f in files:
            remote_path = f"{remote_dir}/{f.name}"
            tasks.append(self.send_file(ip, f, remote_path, user=user))
        await asyncio.gather(*tasks)
        self.log_info(f"Sent {len(files)} files to {user}@{ip}:{remote_dir}")

    def remove_dir_forcefully(self, path):
        import shutil
        import os
        import time

        def onerror(func, path, exc_info):
            import stat
            if not os.access(path, os.W_OK):
                os.chmod(path, stat.S_IWUSR)
                func(path)
            else:
                logging.info(f"{path} not removed due to {exc_info[1]}")

        try:
            shutil.rmtree(path, onerror=onerror)
        except Exception as e:
            logging.error(f"Exception while deleting {path}: {e}")
            time.sleep(1)
            try:
                shutil.rmtree(path, onerror=onerror)
            except Exception as e2:
                logging.error(f"Second failure deleting {path}: {e2}")
                raise

    async def close_all_connections(self):
        """
        Ferme proprement toutes les connexions SSH ouvertes.
        À appeler à la fin de ton programme ou avant arrêt.
        """
        for conn in self._ssh_connections.values():
            conn.close()
            await conn.wait_closed()
        self._ssh_connections.clear()


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

        logging.log(level, f"[{ip}] {line}")


    def clone_project(self, target_project: Path, dest_project: Path):
        """
        Clone a project by copying files and directories, applying renaming,
        then cleaning up any leftovers.

        Args:
            target_project: Path under self.apps_dir (e.g. Path("flight_project"))
            dest_project:   Path under self.apps_dir (e.g. Path("tata_project"))
        """
        # Lazy import heavy deps
        import shutil, ast, os, astor
        from pathspec import PathSpec
        from pathspec.patterns import GitWildMatchPattern

        # normalize names
        if not target_project.name.endswith("_project"):
            target_project = target_project.with_name(target_project.name + "_project")
        if not dest_project.name.endswith("_project"):
            dest_project = dest_project.with_name(dest_project.name + "_project")

        rename_map  = self.create_rename_map(target_project, dest_project)
        source_root = self.apps_dir / target_project
        dest_root   = self.apps_dir / dest_project

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
        Recursively copy + rename directories, files, and contents.
        """
        import astor

        for item in source_dir.iterdir():
            # inside your clone_directory loop, after you've computed `rel`
            rel = item.relative_to(source_root).as_posix()
            if spec.match_file(rel + ("/" if item.is_dir() else "")):
                continue

            # split into segments
            parts = rel.split("/")

            # map each segment exactly via your rename_map (falling back to itself)
            parts = [rename_map.get(seg, seg) for seg in parts]

            # now reconstruct the destination path
            dst_item = dest_dir.joinpath(*parts)
            dst_item.parent.mkdir(parents=True, exist_ok=True)

            if item.is_dir():
                if item.name == ".venv":
                    # keep venv as a symlink
                    os.symlink(item, dst_item, target_is_directory=True)
                else:
                    self.clone_directory(item, dest_dir, rename_map, spec, source_root)

            elif item.is_file():
                suf = item.suffix.lower()

                # first, if the **basename** matches an old→new, rename the file itself
                base = item.stem
                if base in rename_map:
                    dst_item = dst_item.with_name(rename_map[base] + item.suffix)

                # archives
                if suf in (".7z", ".zip"):
                    shutil.copy2(item, dst_item)

                # Python → AST rename + whole‑word replace
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
                    # apply any leftover whole‑word replaces
                    for old, new in rename_map.items():
                        out = re.sub(rf"\b{re.escape(old)}\b", new, out)
                    dst_item.write_text(out, encoding="utf-8")

                # text files → whole‑word replace
                elif suf in (".toml", ".md", ".txt", ".json", ".yaml", ".yml"):
                    txt = item.read_text(encoding="utf-8")
                    for old, new in rename_map.items():
                        txt = re.sub(rf"\b{re.escape(old)}\b", new, txt)
                    dst_item.write_text(txt, encoding="utf-8")

                # everything else
                else:
                    shutil.copy2(item, dst_item)

            elif item.is_symlink():
                target = os.readlink(item)
                os.symlink(target, dst_item, target_is_directory=item.is_dir())


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
