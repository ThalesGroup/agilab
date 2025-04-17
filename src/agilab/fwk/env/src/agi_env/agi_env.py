# BSD 3-Clause License
#
# Copyright (c) 2025, Jean-Pierre Morard, THALES SIX GTS France SAS
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the
# following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this list of conditions and the
#    following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the
#    following disclaimer in the documentation and/or other materials provided with the distribution.
# 3. Neither the name of Jean-Pierre Morard nor the names of its contributors, or THALES SIX GTS France SAS,
#    may be used to endorse or promote products derived from this software without specific prior written permission.
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
import re
import sys
from pathlib import Path, PureWindowsPath, PurePosixPath
from dotenv import dotenv_values, set_key
from pathspec import PathSpec


class JumpToMain(Exception):
    """
    Custom exception to jump back to the main execution flow.
    """
    pass

class ContentRenamer(ast.NodeTransformer):
    """
    A class that renames identifiers in an abstract syntax tree (AST).
    Attributes:
        rename_map (dict): A mapping of old identifiers to new identifiers.
    """
    def __init__(self, rename_map):
        self.rename_map = rename_map
    # ... (all visit_* methods unchanged) ...

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
        self.set_env_var("INSTALL_TYPE", install_type)

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
            elif install_type:
                self.apps_dir = self.agi_root / apps_dir

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
                app_path = self.apps_dir / active_app
                if app_path.exists():
                    self.app = active_app
                src_apps = self.agi_root / "apps"
                if not install_type:
                    if not apps_dir.exists():
                        shutil.copytree(src_apps, self.apps_dir)
                    else:
                        self.copy_missing(src_apps, self.apps_dir)
                module = active_app.replace("_project", "").replace("-", "_")
            else:
                apps_dir = self._determine_apps_dir(active_app)
                module = apps_dir.name.replace("_project", "").replace("-", "_")
        else:
            module = "my_code"

        self.projects = self.get_projects(self.apps_dir)

        if not self.projects:
            print(f"Could not find any target project app in {self.agi_root / "apps"}.")

        if not self.module:
            self.module = module

        AgiEnv.apps_dir = self.apps_dir

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

    def clone_directory(self,
                        source_dir: Path,
                        dest_dir: Path,
                        rename_map: dict,
                        spec: "PathSpec",  # ← quoted
                        source_root: Path):
        """
        Recursively copy + rename:
         - explicit src/<mod> and src/<mod>_worker directory swaps
         - then generic old→new on paths
         - then AST/text content rewriting
        """
        import shutil, os, ast, astor

        tm = source_root.name[:-8]
        dp = dest_dir.name[:-8]
        tm_mod = tm.replace("-", "_")
        dp_mod = dp.replace("-", "_")

        for item in source_dir.iterdir():
            rel = item.relative_to(source_root).as_posix()
            if spec.match_file(rel + ("/" if item.is_dir() else "")):
                continue

            # 1) folder swap
            parts = rel.split("/")
            if len(parts) >= 2 and parts[0] == "src":
                if parts[1] == tm_mod:
                    parts[1] = dp_mod
                elif parts[1] == f"{tm_mod}_worker":
                    parts[1] = f"{dp_mod}_worker"
            new_rel = "/".join(parts)

            # 2) generic map
            for old, new in sorted(rename_map.items(), key=lambda kv: len(kv[0]), reverse=True):
                new_rel = new_rel.replace(old, new)

            dest_item = dest_dir / Path(new_rel)

            if item.is_dir() and item.name == ".venv":
                self.handle_venv_directory(item, dest_item)
                continue

            if item.is_dir():
                dest_item.mkdir(parents=True, exist_ok=True)
                self.clone_directory(item, dest_dir, rename_map, spec, source_root)

            elif item.is_file():
                if dest_item.exists():
                    continue
                suf = item.suffix.lower()
                if suf in (".7z", ".zip"): shutil.copy2(item, dest_item)
                elif suf == ".py":
                    src = item.read_text(encoding="utf-8")
                    try:
                        tree = ast.parse(src)
                        renamer = ContentRenamer(rename_map)
                        new_t = renamer.visit(tree)
                        ast.fix_missing_locations(new_t)
                        dest_item.write_text(astor.to_source(new_t), encoding="utf-8")
                    except SyntaxError:
                        shutil.copy2(item, dest_item)
                else:
                    txt = item.read_text(encoding="utf-8")
                    for old, new in rename_map.items(): txt = txt.replace(old, new)
                    dest_item.write_text(txt, encoding="utf-8")

            elif item.is_symlink():
                os.symlink(os.readlink(item), dest_item, target_is_directory=item.is_dir())

    def _cleanup_rename(self, root: Path, rename_map: dict):
        """
        1) Rename any leftover file/dir names containing old keys.
        2) Rewrite text files to replace any leftover old→new in contents.
        """
        # filesystem names
        for old, new in sorted(rename_map.items(), key=lambda kv: len(kv[0]), reverse=True):
            for path in list(root.rglob(f"*{old}*")):
                path.rename(path.with_name(path.name.replace(old, new)))

        # contents
        exts = {".py", ".toml", ".md", ".txt", ".json", ".yaml", ".yml"}
        for file in root.rglob("*"):
            if not file.is_file() or file.suffix.lower() not in exts: continue
            text = file.read_text(encoding="utf-8")
            newt = text
            for old, new in rename_map.items(): newt = newt.replace(old, new)
            if newt != text: file.write_text(newt, encoding="utf-8")

    def read_gitignore(self, gitignore_path: Path) -> 'PathSpec':
        from pathspec import PathSpec
        from pathspec.patterns import GitWildMatchPattern
        lines = gitignore_path.read_text(encoding="utf-8").splitlines()
        return PathSpec.from_lines(GitWildMatchPattern, lines)

    # ... (remaining methods unchanged) ...
