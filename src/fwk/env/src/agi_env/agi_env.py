# BSD 3-Clause License
#
# Copyright (c) 2025, Jean-Pierre Morard, THALES SIX GTS France SAS
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the
# following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this list of conditions and the
# following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the
# following disclaimer in the documentation and/or other materials provided with the distribution.
# 3. Neither the name of Jean-Pierre Morard nor the names of its contributors, or THALES SIX GTS France SAS,
# may be used to endorse or promote products derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES,
# INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
# WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE
# USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import ast
import cmd
import asyncio
import getpass
import os
import subprocess
import threading
import queue
import time

if os.name == "nt":
    import winreg
import re
import shutil
import sys
from pathlib import Path, PureWindowsPath, PurePosixPath
from dotenv import dotenv_values


class JumpToMain(Exception):
    """
    Custom exception to jump back to the main execution flow.
    """
    pass


class AgiEnv:
    """
    AgiEnv manages paths and environment variables within the agiFramework.
    """

    def __init__(self, module, with_lab=True, verbose=False):
        """
        Initialize the AgiEnv instance.
        """

        if not module:
            print("no module specified")
            exit(1)

        self.with_lab = with_lab
        self.verbose = verbose
        self.is_managed_pc = getpass.getuser().startswith("T0")
        self.agi_root = AgiEnv.locate_agi_installation()
        self.agi_resources = Path("resources/.agilab")
        self.agi_env_path = Path(__file__).parent
        self.home_abs = Path.home() / "MyApp" if self.is_managed_pc else Path.home()

        # Initialize .agilab resources
        self._init_resources(self.agi_env_path / self.agi_resources)

        # Initialize environment variables
        self._init_envars(self.deployed_resources_abs / ".env")

        # Determine module path and set target.
        if isinstance(module, Path):
            self.module_path = module.expanduser().resolve()
        else:
            self.module_path = self._determine_module_path(module)
        self.target = self.module_path.stem  # Define self.target here
        self.dataframes_path = self.AGILAB_SHARE_ABS / self.target / "dataframes"

        # Now that target is defined, we can use it for further assignments.
        self._init_projects()
        self.app = self.app_path.name
        self.setup_app = self.app_path / "setup"
        self.setup_core = self.core_src / "agi_core/workers/agi_worker/setup"
        target_package_path = self.module_path.parent
        self.target_package = target_package_path.name
        self.target_worker = f"{self.target}_worker"
        self.worker_path = (
                target_package_path.parent / self.target_worker / f"{self.target_worker}.py"
        )
        self.worker_pyproject = self.worker_path.parent / "pyproject.toml"

        target_class = "".join(x.title() for x in self.target.split("_"))
        worker_class = target_class + "Worker"
        self.target_class = target_class
        self.target_worker_class = worker_class

        # Call the new base class parser to get both class name and module name.
        self.base_worker_cls, self.base_worker_module = self.get_base_worker_cls(
            self.worker_path, worker_class
        )
        self.workers_packages_prefix = "agi_core.workers."
        if not self.worker_path.exists():
            print(
                f"Missing {self.target_worker_class} definition; should be in {self.worker_path} but it does not exist"
            )
            exit(1)

        app_src_path = self.app_path / "src"
        app_src = str(app_src_path)
        if app_src not in sys.path:
            sys.path.insert(0, app_src)
        app_src_path.mkdir(parents=True, exist_ok=True)
        self.app_src_path = app_src_path

        # Initialize worker environment
        self._init_worker_env()

        # Initialize projects and LAB if required
        if with_lab:
            self.init_envars_app(self.envars)
            self._init_apps()

        if not self.wenv_abs.exists():
            os.makedirs(self.wenv_abs)

        # Set export_local_bin based on the OS
        if os.name == "nt":
            self.export_local_bin = 'set PATH=%USERPROFILE%\\.local\\bin;%PATH% &&'
        else:
            self.export_local_bin = 'export PATH="$HOME/.local/bin:$PATH";'

    # ----------------------------------------------
    # Base class parsing methods (integrated)
    # ----------------------------------------------

    def get_base_worker_cls(self, module_path, class_name):
        """
        Retrieves the first base class ending with 'Worker' from the specified module.
        Returns a tuple: (base_class_name, module_name)
        """
        base_info_list = self.get_base_classes(module_path, class_name)
        try:
            # Retrieve the first base whose name ends with 'Worker'
            base_class, module_name = next(
                (base, mod) for base, mod in base_info_list if base.endswith("Worker")
            )
            return base_class, module_name
        except StopIteration:
            raise ValueError(
                f"class {class_name}([Dag|Data|Agent]Worker): not found in {module_path}."
            )

    def get_base_classes(self, module_path, class_name):
        """
        Parses the module at module_path and returns a list of tuples for the base classes
        of the specified class. Each tuple is (base_class_name, module_name).
        """
        try:
            with open(module_path, "r", encoding="utf-8") as file:
                source = file.read()
        except (IOError, FileNotFoundError) as e:
            if self.verbose:
                print(f"Error reading module file {module_path}: {e}")
            return []

        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            if self.verbose:
                print(f"Syntax error parsing {module_path}: {e}")
            raise RuntimeError(f"Syntax error parsing {module_path}: {e}")

        # Build mapping of imported names/aliases to modules
        import_mapping = self.get_import_mapping(source)

        base_classes = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for base in node.bases:
                    base_info = self.extract_base_info(base, import_mapping)
                    if base_info:
                        base_classes.append(base_info)
                break  # Found our target class
        return base_classes

    def get_import_mapping(self, source):
        """
        Parses the source code and builds a mapping of imported names/aliases to module names.
        """
        mapping = {}
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            if self.verbose:
                print(f"Syntax error during import mapping: {e}")
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
        """
        Extracts the base class name and attempts to determine the module name from the import mapping.
        Returns:
            Tuple[str, Optional[str]]: (base_class_name, module_name)
        """
        if isinstance(base, ast.Name):
            # For a simple name like "MyClassFoo", try to get the module from the import mapping.
            module_name = import_mapping.get(base.id)
            return base.id, module_name
        elif isinstance(base, ast.Attribute):
            # For an attribute like dag_worker.DagWorker, reconstruct the full dotted name.
            full_name = self.get_full_attribute_name(base)
            parts = full_name.split(".")
            if len(parts) > 1:
                # Assume the first part is the alias from the import
                alias = parts[0]
                module_name = import_mapping.get(alias, alias)
                return parts[-1], module_name
            return base.attr, None
        return None

    def get_full_attribute_name(self, node):
        """
        Recursively retrieves the full dotted name from an attribute node.
        """
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return self.get_full_attribute_name(node.value) + "." + node.attr
        return ""

    # ----------------------------------------------
    # Updated method using tomli instead of toml
    # ----------------------------------------------
    def mode2str(self, mode):
        import tomli  # Use tomli for reading TOML files

        chars = ["p", "c", "d", "r"]
        reversed_chars = reversed(list(enumerate(chars)))
        # Open in binary mode for tomli
        with open(self.app_path / "pyproject.toml", "rb") as file:
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

    @staticmethod
    def locate_agi_installation():
        if AgiEnv.is_installed_file(__file__):
            return Path(__file__).parent.parent
        where_is_agi = Path.home() / ".local/share/agilab/.agi-path"
        if where_is_agi.exists():
            try:
                with where_is_agi.open("r") as f:
                    install_path = f.read().strip()
                    if install_path:
                        return Path(install_path)
                    else:
                        raise ValueError("Installation path file is empty.")
                where_is_agi.unlink()
                print(f"Installation path set to: {self.home_abs}")
            except FileNotFoundError:
                print(f"File {where_is_agi} does not exist.")
            except PermissionError:
                print(f"Permission denied when accessing {where_is_agi}.")
            except Exception as e:
                print(f"An error occurred: {e}")
        else:
            try:
                if os.name == "nt":
                    import winreg
                    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment")
                    value, _ = winreg.QueryValueEx(key, "AGI_ROOT")
                    winreg.CloseKey(key)
                    return Path(value)
            except FileNotFoundError:
                print(
                    "Warning AGI_ROOT is not defined in Windows user system environment variables"
                )
            return Path.home()

    def _check_module_path(self, module: Path):
        module = module.expanduser()
        if not module.exists():
            print(f"Module source '{module}' does not exist")
            sys.exit(1)
        return module

    def _determine_module_path(self, project_or_module_name):
        parts = project_or_module_name.rsplit("-", 1)
        suffix = parts[-1]
        name = parts[0].split(os.sep)[-1]
        module_name = name.replace("-", "_")  # Moved this up
        if suffix.startswith("project"):
            name = name.replace("-" + suffix, "")
            project_name = name + "-project"
        else:
            project_name = name.replace("_", "-") + "-project"
        module_path = (
                self.apps_root / project_name / "src" / module_name / (module_name + ".py")
        ).resolve()
        if self._check_module_path(module_path):
            return module_path

    def _init_apps(self):
        app_settings_file = self.app_src_path / "app_settings.toml"
        app_settings_file.touch(exist_ok=True)
        self.app_settings_file = app_settings_file

        args_ui_snippet = self.app_src_path / "args_ui_snippet.py"
        args_ui_snippet.touch(exist_ok=True)
        self.args_ui_snippet = args_ui_snippet

        self.gitignore_file = self.app_path / ".gitignore"
        dest = self.deployed_resources_abs
        if AgiEnv.is_installed_file(__file__):
            AGI_GUI_ABS = self.agi_root /  "agi_gui"
        else:
            AGI_GUI_ABS = self.agi_root / "fwk/gui/src/agi_gui"
        shutil.copytree(AGI_GUI_ABS / self.agi_resources, dest, dirs_exist_ok=True)

    def _update_env_file(self, updates: dict):
        """
        Updates the .agilab/.env file with the key/value pairs from updates.
        Reads the current file (if any), updates the keys, and writes back all key/value pairs.
        """
        env_file = self.deployed_resources_abs / ".env"
        env_data = {}
        if env_file.exists():
            with env_file.open("r") as f:
                for line in f:
                    if '=' in line:
                        k, v = line.strip().split("=", 1)
                        env_data[k] = v
        # Update with the new key/value pairs.
        env_data.update(updates)
        with env_file.open("w") as f:
            for k, v in env_data.items():
                f.write(f"{k}={v}\n")

    def set_env_var(self, key: str, value: str):
        """
        General setter: Updates the AgiEnv internal environment dictionary, the process environment,
        and persists the change in the .agilab/.env file.
        """
        self.envars[key] = value
        os.environ[key] = value
        self._update_env_file({key: value})

    def set_agi_credentials(self, credentials: str):
        """Set the AGI_CREDENTIALS environment variable."""
        self.AGI_CREDENTIALS = credentials  # maintain internal state
        self.set_env_var("AGI_CREDENTIALS", credentials)

    def set_openai_api_key(self, api_key: str):
        """Set the OPENAI_API_KEY environment variable."""
        self.OPENAI_API_KEY
        self.set_env_var("OPENAI_API_KEY", api_key)

    @staticmethod
    def is_installed_file(file_path):
        # Convert both paths to their absolute (and normalized) forms.
        file_abs = os.path.abspath(file_path)
        prefix_abs = os.path.abspath(sys.prefix)
        # Check if file_abs starts with prefix_abs.
        return file_abs.startswith(prefix_abs)

    def _init_envars(self, env_path):
        envars = dotenv_values(dotenv_path=env_path, verbose=self.verbose)
        self.envars = envars
        self.credantials = envars.get("AGI_CREDENTIALS", getpass.getuser())
        credantials = self.credantials.split(":")
        self.user = credantials[0]
        if len(credantials) > 1:
            self.password = credantials[1]
        else:
            self.password = None
        self.python_version = envars.get("AGI_PYTHON_VERSION", "3.12.9")
        if AgiEnv.is_installed_file(__file__):
            self.core_src = self.agi_root
        else:
            self.core_src = self.agi_root / "fwk/core/src"
        self.core_root = self.core_src

        self.workers_root = self.core_src / "agi_core/workers"
        self.manager_root = self.core_src / "agi_core/managers/"
        path = str(self.core_src)
        if path not in sys.path:
            sys.path.insert(0, path)
        AGI_DEFAULT_APPS_DIR = str(self.agi_root / "apps")
        AGI_APPS_ABS = envars.get("AGI_APPS_DIR", AGI_DEFAULT_APPS_DIR)
        self.AGI_APPS_ABS = Path(AGI_APPS_ABS)
        self.apps_root = self.AGI_APPS_ABS
        self.projects = self.get_projects(self.apps_root)
        if not self.projects:
            raise FileNotFoundError(
                f"Could not find any target project app source in {self.apps_root}. Verify that AGI_APPS_DIR is correctly set in the .env file."
            )
        self.WORKER_VENV_REL = Path(envars.get("WORKER_VENV_DIR", "wenv"))
        self.scheduler_ip = envars.get("AGI_SCHEDULER_IP", "127.0.0.1")
        if not self.is_valid_ip(self.scheduler_ip):
            raise ValueError(f"Invalid scheduler IP address: {self.scheduler_ip}")
        if AgiEnv.is_installed_file(__file__):
            self.AGI_SRC_ABS = self.agi_root
            self.help_path = "https://thalesgroup.github.io/agilab"
            self.gui_env = os.getcwd()
        else:
            self.gui_env = self.agi_root / "fwk/gui"
            self.AGI_SRC_ABS = str(self.gui_env / "src")
            self.help_path = str(self.agi_root / "../docs/html")

        self.AGILAB_SHARE_ABS = Path(
            envars.get("AGI_SHARE_DIR", self.home_abs / "data")
        )

    def is_valid_ip(self, ip: str) -> bool:
        pattern = re.compile(r"^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$")
        if pattern.match(ip):
            parts = ip.split(".")
            return all(0 <= int(part) <= 255 for part in parts)
        return False

    def init_envars_app(self, envars):
        self.AGI_CREDENTIALS = envars.get("AGI_CREDENTIALS", None)
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
        self.AGILAB_MLFLOW_ABS = Path(
            envars.get("AGI_MLFLOW_DIR", self.home_abs / ".mlflow")
        )
        self.AGILAB_VIEWS_ABS = Path(
            envars.get("AGI_VIEWS_DIR", self.agi_root / "views")
        )
        self.AGILAB_VIEWS_REL = Path(envars.get("AGI_VIEWS_DIR", "agi/_"))

        self.AGILAB_DATA_NROW = int(envars.get("AGI_GUI_NROW", 1000))
        self.copilot_file = Path(self.AGI_SRC_ABS) / "agi/agi_copilot.py"

    def _init_resources(self, resources_path):
        self.deployed_resources_abs = self.home_abs / self.agi_resources.name
        src_env_path = resources_path / ".env"
        dest_env_file = self.deployed_resources_abs / ".env"
        if not src_env_path.exists():
            raise RuntimeError(f"Installation issue: {src_env_path} is missing!")
        if not dest_env_file.exists():
            os.makedirs(dest_env_file.parent, exist_ok=True)
            shutil.copy(src_env_path, dest_env_file)
        for root, dirs, files in os.walk(resources_path):
            for file in files:
                src_file = Path(root) / file
                relative_path = src_file.relative_to(resources_path)
                dest_file = self.deployed_resources_abs / relative_path
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                if not dest_file.exists():
                    os.makedirs(dest_env_file.parent, exist_ok=True)
                    shutil.copy(src_file, dest_file)

    def _init_worker_env(self):
        self.wenv_rel = self.WORKER_VENV_REL / self.target_worker
        self.wenv_abs = self.home_abs / self.wenv_rel
        self.wenv_target_worker = self.wenv_abs
        distribution_tree = self.wenv_abs / "distribution_tree.json"
        self.cyprepro = self.core_src / "agi_core/workers/agi_worker/cyprepro.py"
        self.post_install_script = self.wenv_abs / "src" / self.target_worker / "post_install.py"
        if distribution_tree.exists():
            distribution_tree.unlink()
        self.distribution_tree = distribution_tree

    def _init_projects(self):
        for idx, project in enumerate(self.projects):
            if self.target == project[:-8].replace("-", "_"):
                self.app_path = self.apps_root / project
                self.project_index = idx
                break

    def get_projects(self, path):
        return [p.name for p in path.glob("*project")]


    def get_modules(self, target=None):
        pattern = "-project"
        modules = [
            re.sub(f"^{pattern}|{pattern}$", "", project).replace("-", "_")
            for project in self.get_projects(self.apps_root)
        ]
        return modules

    @property
    def scheduler_ip_address(self):
        return self.scheduler_ip

    def change_app(self, module_path, with_lab=False):
        if module_path != self.module_path:
            self.__init__(module_path, with_lab=with_lab, verbose=self.verbose)

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

    @staticmethod
    def _build_env(venv=None):
        proc_env = os.environ.copy()
        if venv is not None:
            venv_path = Path(venv) / ".venv"
            proc_env["VIRTUAL_ENV"] = str(venv_path)
            bin_path = "Scripts" if os.name == "nt" else "bin"
            venv_bin = venv_path / bin_path
            proc_env["PATH"] = str(venv_bin) + os.pathsep + proc_env.get("PATH", "")
        return proc_env

    class JumpToMain(Exception):
        pass

    def run_agi_sync(self, code, log_callback=None, venv: Path = None, type=None):
        pattern = r"await\s+(?:Agi\.)?([^\(]+)\("
        matches = re.findall(pattern, code)
        if not matches:
            if log_callback:
                log_callback("Could not determine snippet name from code.")
            else:
                print("Could not determine snippet name from code.")
            return ""
        snippet_file = os.path.join(self.runenv, f"{matches[0]}-{self.target}.py")
        with open(snippet_file, "w") as file:
            file.write(code)
        cmd = f"uv run python {snippet_file}"
        result = asyncio.run(AgiEnv.run_agi_bg(cmd, venv=venv))
        if log_callback:
            log_callback(result)
        return result

    @staticmethod
    async def run_agi_bg(cmd, cwd=".", venv=None, timeout=None, merge_stderr=True):
        proc_env = AgiEnv._build_env(venv)
        proc_env["PYTHONUNBUFFERED"] = "1"
        proc = await asyncio.create_subprocess_shell(
            cmd,
            cwd=os.path.abspath(cwd),
            env=proc_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError as err:
            proc.kill()
            stdout, stderr = await proc.communicate()
            raise RuntimeError(
                f"Timeout expired for command: {cmd}\nfrom: {cwd}\nOutput:\n{stdout.decode()}\nErrors:\n{stderr.decode() if stderr else ''}"
            ) from err
        if proc.returncode:
            proc.kill()
            stdout, stderr = await proc.communicate()
            if not (Path("cwd/.venv")).exists():
                print("no .venv found at",cwd)
                exit(1)
        return stdout.decode(), stderr.decode()

    @staticmethod
    async def run_async(cmd, venv=None, cwd=None, timeout=None, log_callback=None):
        if not cwd:
            cwd = venv
        process_env = os.environ.copy()
        venv_path = Path(venv) / ".venv"
        process_env["VIRTUAL_ENV"] = str(venv_path)
        bin_dir = "Scripts" if os.name == "nt" else "bin"
        venv_bin = venv_path / bin_dir
        process_env["PATH"] = str(venv_bin) + os.pathsep + process_env.get("PATH", "")
        shell_executable = "/bin/bash" if os.name != "nt" else None

        # If cmd is a list, join it for shell=True.
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

        # Start a task for reading stderr concurrently.
        stderr_task = asyncio.create_task(
            read_stream(process.stderr, log_callback if log_callback else print)
        )

    @staticmethod
    def run(cmd, venv=None, cwd=None, timeout=None, wait=True, log_callback=None):
        if not cwd:
            cwd = venv
        process_env = os.environ.copy()
        venv_path = Path(venv) / ".venv"
        process_env["VIRTUAL_ENV"] = str(venv_path)
        bin_dir = "Scripts" if os.name == "nt" else "bin"
        venv_bin = venv_path / bin_dir
        process_env["PATH"] = str(venv_bin) + os.pathsep + process_env.get("PATH", "")
        shell_executable = "/bin/bash" if os.name != "nt" else None

        if wait:
            try:
                process = subprocess.Popen(
                    cmd,
                    shell=True,
                    cwd=str(venv) if not cwd else str(cwd),
                    env=process_env,
                    text=True,
                    executable=shell_executable
                )
                output_lines = []
                while True:
                    if process.stderr:
                        line = process.stderr.readline()
                        if line:
                            if log_callback:
                                log_callback(line)
                            else:
                                print(line)
                        if line == '' and process.poll() is not None:
                            break
                    else:
                        break
                process.wait(timeout=timeout)
                return process.stdout.read() if process.stdout else ""
            except Exception as e:
                raise RuntimeError(f"Command execution error: {e}") from e
        else:
            return ""

    @staticmethod
    def create_symlink(source: Path, dest: Path):
        try:
            source_resolved = source.resolve(strict=True)
        except FileNotFoundError as e:
            raise FileNotFoundError(
                f"Error: Source path does not exist: {source}\n{e}"
            ) from e
        if dest.exists() or dest.is_symlink():
            if dest.is_symlink():
                try:
                    existing_target = dest.resolve(strict=True)
                    if existing_target == source_resolved:
                        print(f"Symlink already exists and is correct: {dest} -> {source_resolved}")
                        return
                    else:
                        print(f"Warning: Symlink at {dest} points to {existing_target}, expected {source_resolved}.")
                        return
                except RecursionError:
                    raise RecursionError(f"Error: Detected a symlink loop while resolving existing symlink at {dest}.")
                except FileNotFoundError:
                    print(f"Warning: Symlink at {dest} is broken.")
                    return
            else:
                print(f"Warning: Destination already exists and is not a symlink: {dest}")
                return
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise OSError(f"Error: Failed to create parent directories for {dest}: {e}") from e
        try:
            if os.name == "nt":
                is_dir = source_resolved.is_dir()
                os.symlink(str(source_resolved), str(dest), target_is_directory=is_dir)
            else:
                os.symlink(str(source_resolved), str(dest))
            print(f"Symlink created: {dest} -> {source_resolved}")
        except OSError as e:
            if os.name == "nt":
                raise OSError(
                    "Error: Failed to create symlink on Windows.\nEnsure you have the necessary permissions or Developer Mode is enabled."
                ) from e
            else:
                raise OSError(f"Error: Failed to create symlink: {e}") from e

    @staticmethod
    def normalize_path(path):
        return (
            str(PureWindowsPath(Path(path)))
            if os.name == "nt"
            else str(PurePosixPath(Path(path)))
        )