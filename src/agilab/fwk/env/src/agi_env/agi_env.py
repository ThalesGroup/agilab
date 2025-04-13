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
import traceback

import time

if os.name == "nt":
    import winreg
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import re
import shutil
import sys
from pathlib import Path, PureWindowsPath, PurePosixPath
from dotenv import dotenv_values, set_key
from pathspec import PathSpec
from pathspec.patterns import GitWildMatchPattern

class JumpToMain(Exception):
    """
    Custom exception to jump back to the main execution flow.
    """
    pass


class AgiEnv:
    """
    AgiEnv manages paths and environment variables within the agiFramework.
    """
    install_type = None
    apps_dir = None
    app = None
    module = None

    def __init__(self, install_type: int=None, apps_dir: Path = None, active_app: Path | str = None,
              active_module: Path = None, verbose: int = 0):
        """
        Initialize the AgiEnv instance

        parameters:
        - install_type: 0: end-user, 1: dev, 2: api
        - apps_dir: path to apps directory
        - active_app: name or path of the active app
        - active_module: path of the active module
        - verbose: verbosity level
        """
        self.verbose = verbose
        self.is_managed_pc = getpass.getuser().startswith("T0")
        self.agi_resources = Path("resources/.agilab")
        self.home_abs = Path.home() / "MyApp" if self.is_managed_pc else Path.home()

        self.resource_path = self.home_abs / self.agi_resources.name
        env_path = self.resource_path / ".env"
        self.envars = dotenv_values(dotenv_path=env_path, verbose=verbose)
        envars = self.envars
        if install_type:
            install_type = int(install_type)
        else:
            install_type = int(envars.get("INSTALL_TYPE", 0))
        self.set_env_var("INSTALL_TYPE", install_type)

        if install_type:
            self.agi_root = AgiEnv.locate_agi_installation()
            self.agi_fwk_env_path = self.agi_root / "fwk/env"
            if not self.agi_fwk_env_path.exists():
                raise JumpToMain("Please check if you have correctly installed Agilab ")
        else:
            head, sep, _ = __file__.partition("site-packages")
            if not sep:
                raise ValueError("site-packages not in", __file__)
            self.agi_root = Path(head + sep) / "agilab"
            self.agi_fwk_env_path = self.agi_root.parent

        # check validity of active_module if any and set the apps_dir
        if active_module:
            if isinstance(active_module, Path):
                self.module = active_module.stem
                appsdir = self._determine_apps_dir(active_module)
                if apps_dir:
                    print("warning apps_dir will be determine from active_module path")
                apps_dir = appsdir
                app = apps_dir.name
                if active_app:
                    print("app will be determined from active_module path")
                active_app = app
            else:
                print("active_module must be of type 'Path'")
                exit(1)
        else:
            self.module = None


        if install_type:
            self.install_type = install_type
            resource_path = self.agi_root / "fwk/env/src/agi_env" / self.agi_resources
        else:
            self.install_type = install_type
            resource_path = self.agi_fwk_env_path / "agi_env" / self.agi_resources

        # Initialize .agilab resources
        self._init_resources(resource_path)

        # if apps_dir is not provided or can't be guess from modul_path then take from envars
        if not apps_dir:
            apps_dir = envars.get("APPS_DIR", '.')
        else:
            set_key(dotenv_path=env_path, key_to_set="APPS_DIR", value_to_set=str(apps_dir))

        apps_dir = Path(apps_dir)

        # check validity of apps_dir if any
        try:
            if apps_dir.exists():
                self.apps_dir = apps_dir

        except FileNotFoundError:
            print("app_dir not found:/n", apps_dir)
            exit(1)

        if not active_app:
            active_app = envars.get("APP_DEFAULT", 'flight_project')

        # check validity of active_app and set module
        if active_app:
            if isinstance(active_app, str):
                active_app = active_app
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
                        self.copy_missing(src_apps, apps_dir)
                module = active_app.replace("_project", "").replace("-", "_")
            else:
                apps_dir = self._determine_apps_dir(active_app)
                module = apps_dir.name.replace("_project", "").replace("-", "_")
        else:
            module = "my_code"

        self.projects = self.get_projects(apps_dir)

        if not self.projects:
            print(f"Could not find any target project app in {self.agi_root / "apps"}.")

        if not self.module:
            self.module = module

        AgiEnv.apps_dir = apps_dir

        # Initialize environment variables
        self._init_envars()

        self.app_path = self.apps_dir / active_app
        self.setup_app =  self.app_path / "setup"
        self.setup_core = self.core_src / "agi_core/workers/agi_worker/setup"
        self.target_worker = f"{self.module}_worker"
        self.worker_path = (
                self.app_path / "src" / self.target_worker / f"{self.target_worker}.py"
        )
        self.module_path = self.app_path / "src" / self.module / f"{self.module}.py"
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
        self.app_src_path = self.agi_root / app_src_path

        # Initialize worker environment
        self._init_worker_env()

        # Initialize projects and LAB if required
        if AgiEnv.install_type != 3:
            self.init_envars_app(self.envars)
            self._init_apps()

        if not self.wenv_abs.exists():
            os.makedirs(self.wenv_abs)

        # Set export_local_bin based on the OS
        if os.name == "nt":
            self.export_local_bin = 'set PATH=%USERPROFILE%\\.local\\bin;%PATH% &&'
        else:
            self.export_local_bin = 'export PATH="$HOME/.local/bin:$PATH";'

    def copy_missing(self, src: Path, dst: Path):
        # Ensure the destination directory exists
        dst.mkdir(parents=True, exist_ok=True)

        for item in src.iterdir():
            src_item = item
            dst_item = dst / item.name

            if src_item.is_dir():
                # Recursively copy the directory if it's missing entirely,
                # or copy missing files inside it
                self.copy_missing(src_item, dst_item)
            else:
                # Copy file if it does not exist in destination
                if not dst_item.exists():
                    shutil.copy2(src_item, dst_item)


    def active(self, target, install_type):
        if self.module != target:
            self.change_active_app(target + '_project', install_type)

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
            # workaroud
            # todo change logic for AgiEnv instanciation into wenv
            #raise ValueError(
            #    f"class {class_name}([Dag|Data|Agent]Worker): not found in {module_path}."
            #)
            return None, None

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
        if os.name == "nt":
            where_is_agi = Path(os.getenv("LOCALAPPDATA")) / "agilab/.agi-path"
        else:
            where_is_agi = Path.home() / ".local/share/agilab/.agi-path"

        if where_is_agi.exists():
            try:
                with where_is_agi.open("r", encoding="utf-8-sig") as f:
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
            raise RuntimeError("agilab dir not found in local folder (.local on posix and %LOCALAPPDATA% on Windows).")

    def _check_module_path(self, module: Path):
        module = module.expanduser()
        if not module.exists():
            print(f"Warning Module source '{module}' does not exist")
        return module

    def _determine_module_path(self, project_or_module_name):
        parts = project_or_module_name.rsplit("-", 1)
        suffix = parts[-1]
        name = parts[0].split(os.sep)[-1]
        module_name = name.replace("-", "_")  # Moved this up
        if suffix.startswith("project"):
            name = name.replace("-" + suffix, "")
            project_name = name + "_project"
        else:
            project_name = name.replace("_", "-") + "_project"
        module_path = (
                self.apps_dir / project_name / "src" / module_name / (module_name + ".py")
        ).resolve()
        return module_path

    def _determine_apps_dir(self, module_path):
        path_str = str(module_path)
        index = path_str.index("_project")
        return Path(path_str[:index]).parent

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
            shutil.copytree(self.agi_root / "fwk/gui/src/agi_gui" / self.agi_resources, dest, dirs_exist_ok=True)
        else:
            shutil.copytree(self.agi_root.parent / "agi_gui" / self.agi_resources, dest, dirs_exist_ok=True)

    def _update_env_file(self, updates: dict):
        """
        Updates the .agilab/.env file with the key/value pairs from updates.
        Reads the current file (if any), updates the keys, and writes back all key/value pairs.
        """
        env_file = self.resource_path / ".env"
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
        os.environ[key] = str(value)
        self._update_env_file({key: value})

    def set_cluster_credentials(self, credentials: str):
        """Set the AGI_CREDENTIALS environment variable."""
        self.CLUSTER_CREDENTIALS = credentials  # maintain internal state
        self.set_env_var("CLUSTER_CREDENTIALS", credentials)

    def set_openai_api_key(self, api_key: str):
        """Set the OPENAI_API_KEY environment variable."""
        self.OPENAI_API_KEY = api_key
        self.set_env_var("OPENAI_API_KEY", api_key)

    def set_install_type(self, install_type: int):
        self.install_type = install_type
        self.set_env_var("INSTALL_TYPE", str(install_type))

    def set_apps_dir(self, apps_dir: Path):
        self.apps_dir =apps_dir
        self.set_env_var("APPS_DIR", apps_dir)



    @staticmethod
    def get_venv_root():
        p = Path(sys.prefix).resolve()
        # If .venv exists in the path parts, slice the path up to it
        if ".venv" in p.parts:
            index = p.parts.index(".venv")
            return Path(*p.parts[:index])
        return p

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

    # -------------------- Handling .venv Directory -------------------- #

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

    # -------------------- Rename Map Creator -------------------- #

    def create_rename_map(self, target_project, dest_project):
        """
        Create a mapping of old names to new names for renaming during project cloning.
        """

        def capitalize(name):
            """
            Capitalize each word in a given string separated by underscores.

            Args:
                name (str): A string containing words separated by underscores.

            Returns:
                str: The input string with each word capitalized.
            """
            return "".join(part.capitalize() for part in name.split("_"))

        target_package = target_project[:-8].replace("-template", "")
        target_module = target_package.replace("-", "_")
        target_class = capitalize(target_module)

        dest_package = dest_project[:-8]
        dest_module = dest_package.replace("-", "_")
        dest_class = capitalize(dest_module)

        return {
            target_project: dest_project,
            target_package: dest_package,
            target_module: dest_module,
            target_class + "Worker": dest_class + "Worker",
            target_class + "Args": dest_class + "Args",
            target_class: dest_class,
        }

    def clone_project(self, target_project, dest_project):
        """
        Clone a project by recursively copying files and directories, applying renaming.
        For the .venv directory, create a symbolic link instead of copying if it's not ignored.

        Args:
            target_project (str): Name of the target project.
            dest_project (str): Name of the destination project.
        """
        rename_map = self.create_rename_map(str(target_project), str(dest_project))
        source_root = AgiEnv.apps_dir / target_project
        dest_root = AgiEnv.apps_dir / dest_project

        # Check if source project exists
        if not source_root.exists():
            print(f"Source project '{target_project}' does not exist.")
            return

        # Check if destination project already exists
        if dest_root.exists():
            print(f"Destination project '{dest_project}' already exists.")
            return

        gitignore_path = source_root / ".gitignore"

        if not gitignore_path.exists():
            print(f"No .gitignore file found at '{gitignore_path}'.")
            return

        spec = self.read_gitignore(self, gitignore_path)

        # Create the destination directory
        try:
            dest_root.mkdir(parents=True, exist_ok=False)
        except Exception as e:
            print(f"Failed to create destination directory '{dest_root}': {e}")
            return

        # Start recursive cloning
        self.clone_directory(source_root, dest_root, rename_map, spec, source_root)

    import ast
    import astor

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

    def clone_directory(self, source_dir, dest_dir, rename_map, spec, source_root):
        """
        Recursively clone directories and files from source to destination,
        applying renaming and respecting .gitignore patterns.
        Creates a symbolic link for the .venv directory if it's not ignored.

        Args:
            source_dir (Path): Source directory path.
            dest_dir (Path): Destination directory path.
            rename_map (dict): Mapping of old relative paths to new relative paths.
            spec (PathSpec): Compiled PathSpec object to filter files/directories.
            source_root (Path): The root directory of the source project.
        """
        for item in source_dir.iterdir():
            try:
                relative_path = item.relative_to(source_root).as_posix()
            except ValueError as ve:
                print(
                    f"Item '{item}' is not under the source root '{source_root}'. Skipping."
                )
                continue

            print(f"Processing item: **{relative_path}**")

            if spec.match_file(relative_path):
                print(f"Skipping ignored item: {relative_path}")
                continue

            # Apply renaming for the entire relative path
            new_relative_path = relative_path
            for old, new in sorted(
                    rename_map.items(), key=lambda x: len(x[0]), reverse=True
            ):
                new_relative_path = new_relative_path.replace(old, new)

            if relative_path != new_relative_path:
                print(f"Renaming '{relative_path}' to '{new_relative_path}'")
            else:
                print(f"No renaming needed for: {relative_path}")

            # Log the old and new paths
            print(f"Old Path: {item}")
            print(f"New Path: {dest_dir / Path(new_relative_path)}")

            # **Fixed Line**: Removed .relative_to(source_root)
            dest_item = dest_dir / Path(new_relative_path)

            # Handle the .venv directory specially
            if item.is_dir() and item.name == ".venv":
                self.handle_venv_directory(item, dest_item)
                continue  # Skip further processing for .venv

            if item.is_dir():
                try:
                    dest_item.mkdir(parents=True, exist_ok=True)
                    print(f"Created directory: {dest_item}")
                except Exception as e:
                    print(f"Failed to create directory '{dest_item}': {e}")
                    continue  # Skip cloning this directory

                # Recursive call for subdirectories
                self.clone_directory(item, dest_dir, rename_map, spec, source_root)

            elif item.is_file():
                # Apply renaming based on rename_map
                dest_file = dest_item

                if dest_file.exists():
                    print(f"Destination file '{dest_file}' already exists. Skipping.")
                    continue

                try:
                    if dest_file.suffix in [".7z", ".zip"]:
                        shutil.copy2(item, dest_file)
                        print(f"Copied archive file: {dest_file}")
                    elif dest_file.suffix == ".py":
                        # Handle Python files with AST-based renaming
                        content = item.read_text(encoding="utf-8")
                        try:
                            parsed_ast = ast.parse(content)
                            renamer = ContentRenamer(rename_map)
                            updated_ast = renamer.visit(parsed_ast)
                            ast.fix_missing_locations(updated_ast)
                            updated_content = astor.to_source(updated_ast)
                            dest_file.write_text(updated_content, encoding="utf-8")
                            print(f"Cloned and renamed Python file: {dest_file}")
                        except SyntaxError as se:
                            print(
                                f"Syntax error while parsing '{item}': {se}. Skipping content renaming."
                            )
                            # Optionally, copy the file without renaming content
                            shutil.copy2(item, dest_file)
                            print(
                                f"Copied Python file without content renaming: {dest_file}"
                            )
                    elif dest_file.suffix in [
                        ".toml",
                        ".md",
                        ".txt",
                        ".json",
                        ".yaml",
                        ".yml",
                    ]:
                        # Handle other text-based files with string replacement
                        content = item.read_text(encoding="utf-8")
                        updated_content = content
                        for old, new in rename_map.items():
                            if old in updated_content:
                                print(f"Renaming '{old}' to '{new}' in {dest_file.name}")
                                updated_content = updated_content.replace(old, new)
                        dest_file.write_text(updated_content, encoding="utf-8")
                        print(f"Cloned and renamed text file: {dest_file}")
                    else:
                        # For binary or unsupported file types, copy without modification
                        shutil.copy2(item, dest_file)
                        print(f"Copied file without modification: {dest_file}")
                except Exception as e:
                    print(f"Error processing file '{item}': {e}")

            elif item.is_symlink():
                # Handle symbolic links if necessary
                target = os.readlink(item)
                try:
                    os.symlink(target, dest_item, target_is_directory=item.is_dir())
                    print(f"Cloned symlink: {dest_item} -> {target}")
                except Exception as e:
                    print(f"Failed to clone symlink '{item}': {e}")

    @staticmethod
    def read_gitignore(self, gitignore_path):
        """
        Read patterns from a .gitignore file and compile them into a PathSpec.

        Args:
            gitignore_path (Path): Path to the .gitignore file.

        Returns:
            PathSpec: Compiled PathSpec object.
        """
        with open(gitignore_path, "r") as f:
            patterns = f.read().splitlines()
        return PathSpec.from_lines(GitWildMatchPattern, patterns)


    def _init_envars(self):
        envars = self.envars
        self.credantials = envars.get("CLUSTER_CREDENTIALS", getpass.getuser())
        credantials = self.credantials.split(":")
        self.user = credantials[0]
        if len(credantials) > 1:
            self.password = credantials[1]
        else:
            self.password = None
        self.python_version = envars.get("AGI_PYTHON_VERSION", "3.12.9")

        os.makedirs(AgiEnv.apps_dir, exist_ok=True)
        if self.install_type:
            self.core_src = self.agi_root / "fwk/core/src"
        else:
            self.core_src = self.agi_root
        self.core_root = self.core_src.parent

        self.workers_root = self.core_src / "agi_core/workers"
        self.manager_root = self.core_src / "agi_core/managers/"
        path = str(self.core_src)
        if path not in sys.path:
            sys.path.insert(0, path)

        # Determine module path and set target.
        if isinstance(self.module, Path):
            self.module_path = self.module.expanduser().resolve()
        else:
            self.module_path = self._determine_module_path(self.module)
        self.target = self.module_path.stem  # Define self.target here

        self.AGILAB_SHARE_ABS = Path(
            envars.get("AGI_SHARE_DIR", self.home_abs / "data")
        )

        self.dataframes_path = self.AGILAB_SHARE_ABS / self.target / "dataframes"

        # Now that target is defined, we can use it for further assignments.
        self._init_projects()

        self.WORKER_VENV_REL = Path(envars.get("WORKER_VENV_DIR", "wenv"))
        self.scheduler_ip = envars.get("AGI_SCHEDULER_IP", "127.0.0.1")
        if not self.is_valid_ip(self.scheduler_ip):
            raise ValueError(f"Invalid scheduler IP address: {self.scheduler_ip}")

        if self.install_type:
            self.help_path = str(self.agi_root / "../docs/html")
        else:
            self.help_path = "https://thalesgroup.github.io/agilab"

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
        self.MLFLOW_TRACKING_DIR = Path(
            envars.get("MLFLOW_TRACKING_DIR", self.home_abs / ".mlflow")
        )
        self.AGILAB_VIEWS_ABS = Path(
            envars.get("AGI_VIEWS_DIR", self.agi_root / "views")
        )
        self.AGILAB_VIEWS_REL = Path(envars.get("AGI_VIEWS_DIR", "agi/_"))

        self.AGILAB_DATA_NROW = int(envars.get("AGI_GUI_NROW", 1000000))
        if self.install_type == 0:
            self.copilot_file = self.agi_root / "fwk/gui/src/agi_gui/agi_copilot.py"
        else:
            self.copilot_file = self.agi_root / "agi_gui/agi_copilot.py"

    def _init_resources(self, resources_path):
        src_env_path = resources_path / ".env"
        dest_env_file = self.resource_path / ".env"
        if not src_env_path.exists():
            msg = f"Installation issue: {src_env_path} is missing!"
            print(msg)
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
                self.app_path = AgiEnv.apps_dir / project
                self.project_index = idx
                self.app = project
                break

    def get_projects(self, path:Path):
        return [p.name for p in path.glob("*project")]


    def get_modules(self, target=None):
        pattern = "_project"
        modules = [
            re.sub(f"^{pattern}|{pattern}$", "", project).replace("-", "_")
            for project in self.get_projects(AgiEnv.apps_dir)
        ]
        return modules

    @property
    def scheduler_ip_address(self):
        return self.scheduler_ip

    def change_active_module(self, module_path, install_type):
        if module_path != self.module_path:
            self.__init__(active_module=module_path, install_type=install_type, verbose=self.verbose)

    def change_active_app(self, app, install_type):
        if isinstance(app, str):
            app_name = app
        elif isinstance(app, Path):
            app_name = app.name
        else:
            raise TypeError(f"Invalid app type: {type(app)}\nSupported type are <str> and <Path>")

        if app_name != self.app:
            self.__init__(active_app=app_name, install_type=install_type, verbose=self.verbose)

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
        cmd = f"uv run python {snippet_file}"
        # Await _run_bg directly without asyncio.run()
        result = await AgiEnv._run_bg(cmd, venv=venv, log_callback=log_callback)
        if log_callback:
            log_callback(f"Process finished with output: {result}")
        return result

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
                    executable=shell_executable,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                output_lines = []
                while True:
                    if process.stderr:
                        line = process.stderr.readline().rstrip()
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
                print(traceback.format_exc())
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