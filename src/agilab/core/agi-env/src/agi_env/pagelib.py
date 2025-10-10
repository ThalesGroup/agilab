# BSD 3-Clause License
#
# Copyright (c) 2025, Jean-Pierre Morard, THALES SIX GTS France SAS
# All rights reserved.
# Co-author: Codex 0.42.0
#
# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
# 3. Neither the name of Jean-Pierre Morard nor the names of its contributors, or THALES SIX GTS France SAS, may be used to endorse or promote products derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import re
import json
import glob
from pathlib import Path
from functools import lru_cache
import pandas as pd
import os
import subprocess
import streamlit as st
import random
import socket
import base64
import runpy
from typing import Dict, Optional
import sys
import logging
import webbrowser
import shlex
try:
    # Python 3.8+
    from importlib import metadata as _importlib_metadata  # type: ignore
except Exception:  # pragma: no cover
    _importlib_metadata = None  # type: ignore
try:
    import tomli  # type: ignore
except Exception:  # pragma: no cover
    tomli = None  # type: ignore

from sqlalchemy import false



# Apply the custom CSS
custom_css = (
    "<style> .stButton > button { max-width: 150px;  /* Adjust the max-width as needed */"
    "font-size: 14px;  /* Adjust the font-size as needed */)"
    "white-space: nowrap;  /* Prevent text from wrapping */"
    "overflow: hidden;  /* Hide overflow text */"
    "text-overflow: ellipsis;  /* Show ellipsis for overflow text */} "
    " .stToggleSwitch label {"
    "max-width: 150px;  /* Adjust the max-width as needed */"
    "font-size: 14px;  /* Adjust the font-size as needed */"
    "white-space: nowrap;  /* Prevent text from wrapping */"
    "overflow: hidden;  /* Hide overflow text */"
    "text-overflow: ellipsis;  /* Show ellipsis for overflow text */"
    "display: inline-block;} </style>"
)


class JumpToMain(Exception):
    """
    Custom exception to jump back to the main execution flow.
    """

    pass


def log(message):
    """
    Log an informational message.
    """
    logging.info(message)


def run(command, cwd=None):
    """
    Execute a shell command.

    Args:
        command (str): The command to execute.
        cwd (str, optional): The working directory to execute the command in.

    Raises:
        subprocess.CalledProcessError: If the command exits with a non-zero status.
    """
    try:
        subprocess.run(
            command,
            shell=True,
            check=True,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        log(f"Executed: {command}")
    except subprocess.CalledProcessError as e:
        log(f"Error executing command: {command}")
        log(f"Exit Code: {e.returncode}")
        log(f"Output: {e.output.decode().strip()}")
        log(f"Error Output: {e.stderr.decode().strip()}")
        sys.exit(e.returncode)


import webbrowser

# Track whether docs have been opened during the session to avoid reopening
_DOCS_ALREADY_OPENED = False
_LAST_DOCS_URL: Optional[str] = None

def _resolve_docs_path(env, html_file: str) -> Path | None:
    """Return the first docs HTML path that exists for the requested file."""
    candidates = [
        env.agilab_src.parent / "docs" / "build",
        env.agilab_src.parent / "docs" / "html",
        env.agilab_src / "docs" / "build",
        env.agilab_src / "docs" / "html",
    ]

    for base in candidates:
        candidate = base / html_file
        if candidate.exists():
            return candidate

    docs_root = env.agilab_src.parent / "docs"
    if docs_root.exists():
        matches = list(docs_root.rglob(html_file))
        if matches:
            return matches[0]

    return None


def open_docs(env, html_file="index.html", anchor=""):
    """
    Opens the local Sphinx docs in a new browser tab.
    If the local documentation file is not found, it opens the online docs.

    Args:
        env: An environment object that helps locate the docs directory.
        html_file (str): Which HTML file within the docs/build/ folder to open (default 'index.html').
        anchor (str, optional): Optional hash anchor (e.g. '#project-editor').
    """
    global _DOCS_ALREADY_OPENED, _LAST_DOCS_URL

    target_url: Optional[str] = None
    docs_path = _resolve_docs_path(env, html_file)

    if docs_path is None:
        print("Documentation file not found locally. Opening online docs instead.")
        online_url = "https://thalesgroup.github.io/agilab/"
        if anchor:
            # Ensure the anchor starts with '#'
            if not anchor.startswith("#"):
                anchor = "#" + anchor
            online_url += anchor
        target_url = online_url
    else:
        # Construct a file:// URL with an optional anchor
        docs_url = docs_path.as_uri()
        if anchor:
            if not anchor.startswith("#"):
                anchor = "#" + anchor
            docs_url += anchor
        target_url = docs_url

    if _DOCS_ALREADY_OPENED and _LAST_DOCS_URL == target_url:
        # If we can focus an existing tab, do so. Otherwise, fall back to opening a new tab
        # to handle cases where the previous tab was closed or focus is not permitted.
        if _focus_existing_docs_tab(target_url):
            return
        # Fallback: open a fresh tab so users can reopen docs after closing them.
        webbrowser.open_new_tab(target_url)
        _DOCS_ALREADY_OPENED = True
        _LAST_DOCS_URL = target_url
        return

    # Either first open, or navigating to different doc target -> open in new tab.
    webbrowser.open_new_tab(target_url)
    _DOCS_ALREADY_OPENED = True
    _LAST_DOCS_URL = target_url



def get_base64_of_image(image_path):
    """
    Reads an image file and encodes it to a Base64 string.

    Returns:
        str: The Base64 encoded string of the image file.

    Raises:
        FileNotFoundError: If the image file cannot be found.
        IOError: If an error occurs during file reading or encoding.
    """
    try:
        with open(image_path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode()
    except Exception as e:
        st.error(f"Error loading {image_path}: {e}")
        return ""

@st.cache_data
def get_css_text():
    env = st.session_state["env"]
    with open(env.st_resources / "code_editor.scss") as file:
        return file.read()

@st.cache_resource
def inject_theme(base_path: Path | None = None) -> None:
    """Apply the AGILAB theme CSS from the given resources directory."""
    import streamlit as st

    if base_path is None:
        base_path = Path(__file__).resolve().parents[1] / "resources"
    css_path = Path(base_path) / "theme.css"
    if css_path.exists():
        css = css_path.read_text()
        st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)

def _read_version_from_pyproject(env) -> str | None:
    """Read version from pyproject.toml when running from source checkout.

    Returns version string or None.
    """
    try:
        if tomli is None:
            return None
        root = getattr(env, "agilab_src", None)
        py_paths: list[Path] = []
        if root:
            py_paths.append(Path(root) / "pyproject.toml")
        # Fallback: look for a repo pyproject.toml from current working dir upwards (dev runs)
        try:
            here = Path.cwd().resolve()
            for _ in range(4):  # limit upward search
                py = here / "pyproject.toml"
                if py.exists():
                    py_paths.append(py)
                    break
                if here.parent == here:
                    break
                here = here.parent
        except Exception:
            pass
        for py in py_paths:
            try:
                if not py.exists():
                    continue
                with py.open("rb") as f:
                    data = tomli.load(f)
                proj = (data.get("project") or {})
                name = str(proj.get("name") or "").strip().lower()
                if name and name != "agilab":
                    # Not our project file; continue searching
                    continue
                ver = str(proj.get("version") or "").strip()
                if ver:
                    return ver
            except Exception:
                continue
        return None
    except Exception:
        return None


def _detect_agilab_version(env) -> str:
    """Determine AGILab version for sidebar display.

    - Prefer pyproject version in source env.
    - Fallback to installed distribution metadata.
    - Return empty string if unavailable.
    """
    if getattr(env, "is_source_env", False):
        v = _read_version_from_pyproject(env)
        if v:
            # Append a dev suffix with git metadata when available
            suffix = ""
            try:
                repo = Path(getattr(env, "agilab_src", "."))
                # Short SHA
                sha = subprocess.run(
                    ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                ).stdout.strip()
                # Dirty marker
                dirty = subprocess.run(
                    ["git", "-C", str(repo), "status", "--porcelain"],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                ).stdout
                dirty_mark = "*" if dirty.strip() else ""
                suffix = f"+dev.{sha}{dirty_mark}" if sha else "+dev"
            except Exception:
                suffix = "+dev"
            return f"{v}{suffix}"
    if _importlib_metadata is not None:
        try:
            return _importlib_metadata.version("agilab")
        except Exception:
            pass
    return ""


def render_logo(edit_text):
    if "env" in st.session_state:
        env = st.session_state["env"]
    else:
        return

    agilab_logo_path = env.st_resources / "agilab_logo.png"  # Replace with your logo filename
    agilab_logo_base64 = get_base64_of_image(agilab_logo_path)
    if agilab_logo_base64:
        version = _detect_agilab_version(env)
        version_css = f"v{version}" if version else ""
        st.markdown(
            f"""
            <style>
            /* Ensure the sidebar container is positioned relative */
            [data-testid="stSidebar"] {{
                position: relative;
            }}
            /* Display the AGILab logo using the ::after pseudo-element */
            [data-testid="stSidebar"]::after {{
                content: "";
                display: block;
                background-image: url("data:image/png;base64,{agilab_logo_base64}");
                background-size: contain;
                background-repeat: no-repeat;
                background-position: left top;
                position: absolute;
                top: 10px;       /* adjust vertical position as needed */
                left: 18px;      /* adjust horizontal position as needed */
                width: 70%;
                height: 48px;
            }}
            /* Remove extra margin/padding from the h1 title */
            h1.page-title {{
                margin-top: 0 !important;
                padding-top: 0 !important;
            }}
            /* Display the version text on the right side using the ::before pseudo-element */
            [data-testid="stSidebar"]::before {{
                content: "{version_css}";
                position: absolute;
                bottom: 10px;       /* align vertically with the logo */
                right: 18px;     /* position on the right side */
                font-size: 0.8em;
                color: gray;
            }}
            </style>
            """,
            unsafe_allow_html=True,
        )

    else:
        st.sidebar.warning("Logo could not be loaded. Please check the logo path.")


def subproc(command, cwd):
    """
    Execute a command in the background.

    Args:
        command (str): The command to be executed.
        cwd (str): The current working directory where the command will be executed.

    Returns:
        None
    """
    return subprocess.Popen(
        command,
        shell=True,
        cwd=os.path.abspath(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    ).stdout


def get_projects_zip():
    """
    Get a list of zip file names for projects.

    Returns:
        list: A list of zip file names for projects found in the env export_apps directory.
    """
    env = st.session_state["env"]
    return [p.name for p in env.export_apps.glob("*.zip")]


def get_templates():
    """
    Get a list of template names.

    Returns:
        list: A list of template names (strings).
    """
    env = st.session_state["env"]
    candidates = []
    templates_root = env.apps_dir / "templates"
    if templates_root.exists():
        candidates.extend(p.name for p in templates_root.iterdir() if p.is_dir())

    agilab_templates = getattr(env, "agilab_src", None)
    if agilab_templates:
        agilab_templates = Path(agilab_templates) / "agilab/templates"
        if agilab_templates.exists():
            candidates.extend(p.name for p in agilab_templates.iterdir() if p.is_dir())

    if not candidates:
        candidates.extend(p.stem for p in env.apps_dir.glob("*template"))

    return sorted(dict.fromkeys(candidates))


def get_about_content():
    """
    Get the content of the 'About' section.

    Returns:
        dict: A dictionary containing information about the Agi&trade; agilab.

            'About': str
                A string containing information about the Agi&trade; agilab.

                    ':blue[Agi&trade;] V5\n\n:blue[S]peedy :blue[Py]thon :blue[D]istributed  agilab for Data Science  2020-2024 \n\nThales SIX GTS France SAS \n\nsupport:  focus@thalesgroup.com'
    """
    return {
        "About": (
            ":blue[AGILab&trade;]\n\n"
            "An IDE for Data Science in Engineering\n\n"
            "Thales SIX GTS France SAS \n\n"
            "support:  focus@thalesgroup.com"
        )
    }


def init_custom_ui(render_generic_ui):
    """Ensure the custom app-args form toggle reflects the snippet state."""
    env = st.session_state["env"]
    form_path = env.app_args_form
    if "toggle_custom" not in st.session_state:
        st.session_state["toggle_custom"] = form_path.stat().st_size > 0
    return


def on_project_change(project, switch_to_select=False):
    """
    Callback function to handle project changes.

    This function is optimized for speed and efficiency by minimizing attribute lookups, using tuples for fixed key collections, and leveraging 'del' for key removal.
    """
    env = st.session_state["env"]
    # Define the keys to clear as a tuple for immutability and minor performance gains
    keys_to_clear = (
        "is_args_from_ui",
        "args_default",
        "toggle_custom",
        "df_file_selectbox",
        "app_settings",
        "input_datadir",
        "preview_tree",
        "loaded_df",
        "wenv_abs",
        "projects",
    )

    # Define the prefixes as a tuple for efficient checking
    prefixes = ("arg_name", "arg_value", "view_checkbox")

    # Assign st.session_state to a local variable to minimize attribute lookups
    session_state = st.session_state

    # Clear specific session state variables using 'del' within a try-except block
    for key in keys_to_clear:
        try:
            del session_state[key]
        except KeyError:
            pass  # If the key doesn't exist, do nothing

    # Collect keys to delete that start with specified prefixes
    keys_to_delete = [key for key in session_state if key.startswith(prefixes)]

    # Delete the collected keys using 'del' for better performance
    for key in keys_to_delete:
        del session_state[key]

    try:

        # Change the app/project
        env.change_app(env.apps_dir / project)
        

        module = env.target

        # Update session state with new module and data directory paths
        session_state.module_rel = Path(module)
        session_state.datadir = env.AGILAB_EXPORT_ABS / module
        session_state.datadir_str = str(session_state.datadir)
        st.session_state.df_export_file = str(session_state.datadir / "export.csv")

        # Optional: Set a flag to switch the sidebar tab if needed
        session_state.switch_to_select = switch_to_select
        session_state.project_changed = True

    except Exception as e:
        st.error(f"An error occurred while changing the project: {e}")

    section_labels = (
        "PYTHON‑ENV",
        "PYTHON-ENV-EXTRA",
        "MANAGER",
        "WORKER",
        "EXPORT‑APP‑FILTER",
        "APP‑SETTINGS",
        "ARGS‑UI",
        "PRE‑PROMPT",
    )
    for label in section_labels:
        session_state[label] = False




def is_port_in_use(target_port):
    """
    Check if a port is in use.

    Args:
        target_port: Port number to check.

    Returns:
        bool: True if the port is in use, False otherwise.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", target_port)) == 0


def get_random_port():
    """
    Generate a random port number between 8800 and 9900.

    Returns:
        int: A random port number between 8800 and 9900.
    """
    return random.randint(8800, 9900)



@st.cache_data
def find_files(directory, ext=".csv", recursive=True):
    """
    Finds all files with a specific extension in a directory and its subdirectories.

    Args:
        directory (Path): Root directory to search.
        ext (str): The file extension to search for.

    Returns:
        List[Path]: List of Path objects that match the given extension.
    """
    directory = Path(directory)
    if not directory.is_dir():
        raise NotADirectoryError(f"{directory} is not a valid directory.")

    # Normalize the extension to handle cases like 'csv' or '.csv'
    ext = f".{ext.lstrip('.')}"
    if recursive:
        return list(directory.rglob(f"*{ext}"))
    else:
        return list(directory.glob(f"*/*{ext}"))



@st.cache_data
def get_custom_buttons():
    """
    Retrieve custom buttons data from a JSON file and cache the data.

    Returns:
        dict: Custom buttons data loaded from the JSON file.

    Notes:
        This function uses Streamlit's caching mechanism to avoid reloading the data each time it is called.
    """
    env = st.session_state["env"]
    with open(env.st_resources / "custom_buttons.json") as file:
        return json.load(file)


@st.cache_data
def get_info_bar():
    """
    Retrieve information from the 'info_bar.json' file and return the data as a dictionary.

    :return: Data read from the 'info_bar.json' file.
    :rtype: dict

    :note: This function is cached using Streamlit's st.cache_data decorator to prevent unnecessary file reads.

    :raise FileNotFoundError: If the 'info_bar.json' file cannot be found.
    """
    env = st.session_state["env"]
    with open(env.st_resources / "info_bar.json") as file:
        return json.load(file)


def export_df():
    """
    Export the loaded DataFrame to a CSV file.

    Checks if the loaded DataFrame exists in the session state and exports it to a CSV file specified in the session state. If the DataFrame is empty, a warning message is displayed.

    Args:
        None

    Returns:
        None

    Raises:
        None
    """
    df = st.session_state.get("loaded_df")
    target = st.session_state.get("df_file_out", "")

    if df is None:
        st.warning("DataFrame is empty. Nothing to export.")
        return

    if save_csv(df, target):
        st.success(f"Saved to {target}!")
    else:
        st.warning("Export failed; please check the filename and dataframe content.")

# Remove ANSI escape codes
import ast
from pathlib import Path
from typing import List, Optional, Union


def get_fcts_and_attrs_name(
        src_path: Union[str, Path], class_name: Optional[str] = None
) -> Dict[str, List[str]]:
    """
    Extract function (or method) and attribute names from a Python source file.
    If a class name is provided, extract method and attribute names from that class.
    Otherwise, extract top-level function and attribute names.

    Args:
        src_path (str or Path): The path to the source file.
        class_name (str, optional): The name of the class to extract methods and attributes from.

    Returns:
        Dict[str, List[str]]: Dictionary with keys 'functions' and 'attributes' mapping to lists of names.

    Raises:
        FileNotFoundError: If the source file does not exist.
        SyntaxError: If the source file contains invalid Python syntax.
        ValueError: If the specified class name does not exist in the source file.
    """
    src_path = Path(src_path)

    if not src_path.exists():
        raise FileNotFoundError(f"The file {src_path} does not exist.")

    try:
        with src_path.open("r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        raise IOError(f"Error reading the file {src_path}: {e}")

    try:
        tree = ast.parse(content, filename=str(src_path))
    except SyntaxError as e:
        raise SyntaxError(f"Syntax error in the file {src_path}: {e}")

    function_names = []
    attribute_names = []
    target_class = None

    # Helper function to set parent references
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child.parent = node

    if class_name:
        # Find the class definition
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                target_class = node
                break

        if not target_class:
            raise ValueError(f"Class '{class_name}' not found in {src_path}.")

        # Extract method and attribute names from the target class
        for item in target_class.body:
            if isinstance(item, ast.FunctionDef):
                function_names.append(item.name)
            elif isinstance(item, (ast.Assign, ast.AnnAssign)):
                if isinstance(item, ast.Assign):
                    targets = item.targets
                else:  # ast.AnnAssign
                    targets = [item.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        attribute_names.append(target.id)
                    elif isinstance(target, ast.Tuple):
                        for elt in target.elts:
                            if isinstance(elt, ast.Name):
                                attribute_names.append(elt.id)
    else:
        # Extract top-level function and attribute names
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                # Ensure the function is not nested within another function or class
                if not isinstance(
                        getattr(node, "parent", None), (ast.FunctionDef, ast.ClassDef)
                ):
                    function_names.append(node.name)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                # Ensure the assignment is at the module level
                if isinstance(getattr(node, "parent", None), ast.Module):
                    if isinstance(node, ast.Assign):
                        targets = node.targets
                    else:  # ast.AnnAssign
                        targets = [node.target]
                    for target in targets:
                        if isinstance(target, ast.Name):
                            attribute_names.append(target.id)
                        elif isinstance(target, ast.Tuple):
                            for elt in target.elts:
                                if isinstance(elt, ast.Name):
                                    attribute_names.append(elt.id)

    return {"functions": function_names, "attributes": attribute_names}


def get_classes_name(src_path):
    """
    Extract function names from a Python source file.

    Args:
        src_path (Path): The path to the source file.

    Returns:
        list: List of function names.
    """
    with open(src_path, "r") as f:
        content = f.read()
    pattern = re.compile(r"class\s+(\w+)\(")
    return pattern.findall(content)


def get_class_methods(src_path: Path, class_name: str) -> List[str]:
    """
    Extract method names from a specific class in a Python source file.

    Args:
        src_path (Path): The path to the Python source file.
        class_name (str): The name of the class whose methods are to be extracted.

    Returns:
        List[str]: A list of method names belonging to the specified class.

    Raises:
        FileNotFoundError: If the source file does not exist.
        ValueError: If the specified class is not found in the source file.
    """

    if not src_path.is_file():
        raise FileNotFoundError(f"The file {src_path} does not exist.")

    with src_path.open("r", encoding="utf-8") as file:
        source = file.read()

    # Parse the source code into an AST
    try:
        tree = ast.parse(source, filename=str(src_path))
    except SyntaxError as e:
        raise SyntaxError(f"Syntax error in source file: {e}")

    # Initialize an empty list to store method names
    method_names = []

    # Traverse the AST to find the class definition
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            # Iterate through the class body to find method definitions
            for class_body_item in node.body:
                if isinstance(class_body_item, ast.FunctionDef):
                    method_names.append(class_body_item.name)
            break
    else:
        # If the class is not found, raise an error
        raise ValueError(f"Class '{class_name}' not found in {src_path}.")

    return method_names


def run_agi(code, path="."):
    """
    Run code in the core environment.

    Args:
        code (str): The code to execute.
        env: The environment configuration object.
        id_core (int): Core identifier.
        path (str): The working directory.
    """
    env = st.session_state["env"]
    # Regular expression pattern to match the string between "await" and "("
    pattern = r"await\s+(?:Agi\.)?([^\(]+)\("

    # Find all matches in the code
    matches = re.findall(pattern, code)
    if not matches:
        st.warning("Could not determine snippet name from code.")
        return None

    snippet_name = matches[0]
    snippet_prefix = re.sub(r"[^0-9A-Za-z_]+", "_", str(snippet_name)).strip("_") or "AGI_unknown_command"
    target_slug = re.sub(r"[^0-9A-Za-z_]+", "_", str(env.target)).strip("_") or "unknown_app_name"

    runenv_path = Path(env.runenv)
    runenv_path.mkdir(parents=True, exist_ok=True)
    snippet_file = runenv_path / f"{snippet_prefix}_{target_slug}.py"
    with open(snippet_file, "w") as file:
        file.write(code)

    if (path == env.env_root) or (env.app_abs / ".venv").exists():
        return run_with_output(env, f"uv -q run python {snippet_file}", path)
    else:
        st.info("Please do an install first")
        st.stop()


def run_lab(query, snippet, copilot):
    """
    Run gui code.

    Args:
        query: The query data.
        snippet: The snippet file path.
        copilot: The copilot script path.
    """
    if not query:
        return
    with open(snippet, "w") as file:
        file.write(query[2])
    try:
        runpy.run_path(copilot)
    except Exception as e:
        st.warning(f"Error: {e}")


@st.cache_data
def cached_load_df(path, with_index=True, nrows=None):
    """Convenience wrapper that honors TABLE_MAX_ROWS for lightweight previews."""
    if nrows is None:
        df_max_rows = st.session_state.get("TABLE_MAX_ROWS") if "TABLE_MAX_ROWS" in st.session_state else None
    else:
        df_max_rows = nrows

    if df_max_rows is not None:
        try:
            df_max_rows = int(df_max_rows)
        except (TypeError, ValueError):
            df_max_rows = None
    if df_max_rows == 0:
        df_max_rows = None

    return load_df(path, with_index=with_index, nrows=df_max_rows)

def get_first_match_and_keyword(string_list, keywords_to_find):
    """
    Finds the first occurrence of any keyword in any string.
    Returns a tuple: (actual_matched_substring, found_keyword_pattern)
    - actual_matched_substring: The segment from the string that matched.
    - found_keyword_pattern: The keyword from keywords_to_find that matched.

    Search is case-insensitive.
    Returns (None, None) if no keyword is found in any string.
    """
    # Ensure inputs are iterable, though the loops will handle empty lists
    if not string_list or not keywords_to_find:
        return None, None

    for text_string in string_list:
        if not isinstance(text_string, str):
            print(f"Warning: Item in string_list is not a string: {text_string}")
        for keyword_pattern in keywords_to_find:
            if not isinstance(keyword_pattern, str) or not keyword_pattern:
                print(f"Warning: Item in keywords_to_find is not a valid string: {keyword_pattern}")
            try:
                match = re.search(re.escape(keyword_pattern), text_string, re.IGNORECASE)
                if match:
                    return text_string, keyword_pattern
            except re.error:
                print(f"Warning: Could not compile regex for keyword: {keyword_pattern}")
                pass # Try the next keyword
    # If we've gone through everything and found nothing...
    return None, None
@st.cache_data
def load_df(path: Path, nrows=None, with_index=True):
    """
    Load data from a specified path. Supports loading from CSV and Parquet files.

    Args:
        path (Path): The path to the file or directory.
        nrows (int, optional): Number of rows to read from the file (for CSV files only).
        with_index (bool): Whether to set the "date" column as the DataFrame's index.

    Returns:
        pd.DataFrame or None: The loaded DataFrame or None if no valid files are found.
    """
    path = Path(path)
    if not path.exists():
        return None

    df = None

    if path.is_dir():
        # Collect all CSV and Parquet files in the directory
        files = list(path.rglob("*.csv")) + list(path.rglob("*.parquet"))
        if not files:
            return None

        # Separate Parquet and CSV files
        parquet_files = [f for f in files if f.suffix == ".parquet"]
        csv_files = [f for f in files if f.suffix == ".csv"]

        if parquet_files:
            # Concatenate all Parquet files with a default RangeIndex.
            df = pd.concat([pd.read_parquet(f) for f in parquet_files], ignore_index=True)
        elif csv_files:
            # Concatenate all CSV files.
            df = pd.concat([
                pd.read_csv(f, nrows=nrows, encoding="utf-8", index_col=None)
                for f in csv_files
            ], ignore_index=True)
    elif path.is_file():
        if path.suffix == ".csv":
            df = pd.read_csv(path, nrows=nrows, encoding="utf-8", index_col=None)
        elif path.suffix == ".parquet":
            df = pd.read_parquet(path)
        else:
            return None
    else:
        return None

    # Remove any extra "index" column that might have been written from CSV files.
    if "index" in df.columns:
        df.drop(columns=["index"], inplace=True)

    # Optionally, set the "date" column as the DataFrame's index.
    if with_index and not df.empty:
        col_name,keyword = get_first_match_and_keyword(df.columns.tolist(),["time","date"])
        if col_name:
            if keyword == "time":
                df["index"] = pd.to_timedelta(df[col_name], unit='s')
            elif keyword == "date":
                df["index"] = pd.to_datetime(df[col_name], errors="coerce")
            df.set_index("index", inplace=True,drop=True)
        else:
            df.set_index(df.columns[0], inplace=True, drop=False)
        # ---------------- OLD CODE FOR INDEX ------------------
        # if "date" in df.columns:
        #     # Convert "date" column to datetime (if not already) and set it as index.
        #     df["date"] = pd.to_datetime(df["date"], errors="coerce")
        # else:
        #     # Fallback: use the first column as the index if "date" is not present.
        #     df.set_index(df.columns[0], inplace=True)
        # if "date" in df.columns:
        #     df.set_index("date", inplace=True)
        # elif "datetime" in df.columns:
        #     df.set_index("datetime", inplace=True)

    return df



def save_csv(df, path: Path, sep=",") -> bool:
    """
    Save a DataFrame to a CSV file.

    Args:
        df (DataFrame): The DataFrame to save.
        path (Path): The file path to save the CSV.
        sep (str): The separator to use in the CSV file.
    """
    # Allow users to pass shortcuts like "~/file.csv" or "$HOME/file.csv".
    path_str = str(path).strip()
    if not path_str:
        st.error("Please provide a filename for the export.")
        return False

    expanded_path = os.path.expanduser(os.path.expandvars(path_str))
    path = Path(expanded_path)

    if path.is_dir():
        st.error(f"{path} is a directory instead of a filename.")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    if df.shape[1] > 0:
        df.to_csv(path, sep=sep, index=False)
        return True
    return False


def get_df_index(df_files, df_file):
    """
    Get the index of a DataFrame file in a list of files.

    Args:
        df_files (list): List of DataFrame file paths.
        df_file (Path): The DataFrame file to find.

    Returns:
        int or None: The index if found, else None.
    """
    df_file = Path(df_file) if df_file else None
    if df_file and df_file.exists():
        try:
            return df_files.index(str(df_file))
        except ValueError:
            return None
    elif df_files:
        return 0
    return None


@lru_cache(maxsize=None)
def list_views(views_root):
    """
    List all view Python files in the pages directory.

    Args:
        views_root (Path): The root directory of pages.

    Returns:
        list: Sorted list of view file paths.
    """
    pattern = os.path.join(views_root, "**", "*.py")
    pages = [
        py_file
        for py_file in glob.glob(pattern, recursive=True)
        if not py_file.endswith("__init__.py")
    ]
    return sorted(pages)


def read_file_lines(filepath):
    """
    Read lines from a file.

    Args:
        filepath (Path): The path to the file.

    Returns:
        generator: Generator yielding lines from the file.
    """
    with open(filepath, "r") as file:
        for line in file:
            yield line.rstrip("\n")


def handle_go_action(view_module, view_path):
    """
    Handle the action when a "Go" button is clicked for a specific view.

    Args:
        view_module (str): The name of the view module.
        view_path (Path): The path to the view.
    """
    st.success(f"'Go' button clicked for view: {view_module}")
    st.write(f"View Path: {view_path}")
    # Implement your desired functionality here.


def update_views(project, pages):
    """
    Create and remove hard links according to pages checkbox.

    Args:
        project (str): The project name.
        pages (list): The currently selected pages.

    Returns:
        bool: True if an update was required, False otherwise.
    """
    update_required = False
    env = st.session_state._env
    env.change_app(project)
    st.session_state.preview_tree = False

    pages_root = Path(os.getcwd()) / "src/gui/pages"
    existing_pages = set(os.listdir(pages_root))

    expected_pages = set()
    for view_abs in pages:
        view_abs_path = Path(view_abs)
        view = view_abs_path.parts[-2]
        prefix = "📈"
        if "carto" in view:
            prefix = "🌎"
        elif "network" in view:
            prefix = "🗺️"
        page_name = prefix + str(view_abs_path.stem).capitalize() + ".py"
        expected_pages.add(page_name)

        page_link = pages_root / page_name
        if not page_link.exists():
            update_required = True
            os.link(view_abs_path, page_link)

    for page in existing_pages:
        page_abs = pages_root / page
        try:
            if page not in expected_pages and os.stat(page_abs).st_nlink > 1:
                os.remove(page_abs)
                update_required = True
        except FileNotFoundError:
            continue

    return update_required


def initialize_csv_files():
    """
    Initialize CSV files in the data directory.
    """
    if "csv_files" not in st.session_state or not st.session_state["csv_files"]:
        st.session_state["csv_files"] = find_files(st.session_state.datadir)
    if "df_file" not in st.session_state or not st.session_state["df_file"]:
        csv_files_rel = [
            Path(file).relative_to(st.session_state.datadir).as_posix()
            for file in st.session_state.csv_files
        ]
        st.session_state["df_file"] = csv_files_rel[0] if csv_files_rel else None


def update_var(var_key, widget_key):
    """
    Args:
        var_key: Description of var_key.
        widget_key: Description of widget_key.

    Returns:
        Description of the return value.
    """
    st.session_state[var_key] = st.session_state[widget_key]


def update_datadir(var_key, widget_key):
    """
    Update the data directory and reinitialize CSV files.

    Args:
        var_key: The key of the variable to update.
        widget_key: The key of the widget whose value will be used.
    """
    if "df_file" in st.session_state:
        del st.session_state["df_file"]
    if "csv_files" in st.session_state:
        del st.session_state["csv_files"]
    update_var(var_key, widget_key)
    initialize_csv_files()


def select_project(projects, current_project):
    """
    Render the project selection sidebar. Provides a lightweight filter so we
    never ship thousands of entries to the browser at once.

    :param projects: List of available projects.
    :type projects: list[str]
    :param current_project: Currently selected project.
    :type current_project: str
    """
    search_term = st.sidebar.text_input("Filter projects", key="project_filter").strip().lower()

    if search_term:
        filtered_projects = [p for p in projects if search_term in p.lower()]
        total_matches = len(filtered_projects)
    else:
        filtered_projects = projects
        total_matches = len(projects)

    shortlist = list(filtered_projects[:50])

    if current_project and current_project in filtered_projects and current_project not in shortlist:
        shortlist = [current_project] + [p for p in shortlist if p != current_project]

    if not shortlist:
        st.sidebar.info("No projects match that filter.")
        return

    if search_term and total_matches > len(shortlist):
        st.sidebar.caption(f"Showing first {len(shortlist)} of {total_matches} matches")

    try:
        default_index = shortlist.index(current_project)
    except ValueError:
        default_index = 0

    selection = st.sidebar.selectbox(
        "Project name",
        shortlist,
        index=default_index,
        key="project_selectbox",
    )

    if selection != current_project:
        on_project_change(selection)


def open_new_tab(url):
    # JavaScript to open a new tab
    """
    Open a new tab in the browser with the given URL.

    Args:
        url (str): The URL of the page to be opened in a new tab.

    Returns:
        None

    Note:
        This function uses Streamlit's `st.markdown` function and HTML
        to execute JavaScript code to open a new tab.

    Example:
        open_new_tab('http://www.example.com')
    """
    js = f"window.open('{url}');"
    # Inject the JavaScript into the Streamlit app
    st.markdown(f"<script>{js}</script>", unsafe_allow_html=True)


def scan_dir(path):
    """
    Scan a directory and list its subdirectories.

    Args:
        path (Path): The directory path.

    Returns:
        list: List of subdirectory names.
    """
    return (
        [entry.name for entry in os.scandir(path) if entry.is_dir()]
        if os.path.exists(path)
        else []
    )


def sidebar_views():
    """
    Create sidebar controls for selecting modules and DataFrames.
    """
    # Set module and paths
    env = st.session_state["env"]
    Agi_export_abs = Path(env.AGILAB_EXPORT_ABS)
    modules = st.session_state.get(
        "modules", scan_dir(Agi_export_abs)
    )  # Use the target from Agienv
    # st.session_state.setdefault("index_page", str(module_path.relative_to(env.AGILAB_EXPORT_ABS)))
    # index_page = st.session_state.get("index_page", env.target)

    st.session_state["lab_dir"] = st.sidebar.selectbox(
        "Lab directory",
        modules,
        index=modules.index(
            st.session_state["lab_dir"]
            if "lab_dir" in st.session_state
            else env.target
        ),
        on_change=lambda: on_lab_change(st.session_state.lab_dir_selectbox),
        key="lab_dir_selectbox",
    )

    lab_dir = Agi_export_abs / st.session_state["lab_dir_selectbox"]
    st.session_state.df_dir = Agi_export_abs / lab_dir

    df_files = find_files(lab_dir)
    st.session_state.df_files = df_files

    df_files_rel = sorted(
        (Path(file).relative_to(Agi_export_abs) for file in df_files),
        key=str,
    )
    if "index_page" not in st.session_state:
        index_page = df_files_rel[0] if df_files_rel else env.target
        st.session_state["index_page"] = index_page
    else:
        index_page = st.session_state["index_page"]
    index_page_str = str(index_page)
    key_df = index_page_str + "df"
    index = next(
        (i for i, f in enumerate(df_files_rel) if f.name == "default_df"),
        0,
    )
    module_path = lab_dir.relative_to(Agi_export_abs)
    st.session_state["module_path"] = module_path
    st.sidebar.selectbox(
        "Dataframe",
        df_files_rel,
        key=key_df,
        index=index,
        on_change=lambda: on_df_change(
            module_path,
            st.session_state["df_file"],
            index_page_str,
        ),
    )
    if st.session_state[key_df]:
        st.session_state["df_file"] = Agi_export_abs / st.session_state[key_df]
    else:
        st.session_state["df_file"] = None


def on_df_change(module_dir, index_page, df_file, steps_file=None):
    """
    Handle DataFrame selection.

    Args:
        module_dir (Path): The module path.
        df_file (Path): The DataFrame file path.
        index_page (str): The index page identifier.
        steps_file (Path): The steps file path.
    """
    st.session_state[index_page + "df_file"] = st.session_state[
        index_page + "select_df"
        ]
    if steps_file:
        steps_file.parent.mkdir(parents=True, exist_ok=True)
        load_last_step(module_dir, steps_file, index_page)
    st.session_state.pop(index_page, None)
    st.session_state.page_broken = True


def activate_mlflow(env=None):

    if not env:
        return

    st.session_state["rapids_default"] = True
    os.makedirs(env.MLFLOW_TRACKING_DIR, exist_ok=True)

    port = get_random_port()
    while is_port_in_use(port):
        port = get_random_port()

    cmd = f"uv -q run mlflow ui --backend-store-uri file://{env.MLFLOW_TRACKING_DIR} --port {port}"
    try:
        res = subproc(cmd, os.getcwd())
        st.session_state.server_started = True
        st.session_state["mlflow_port"] = port
    except RuntimeError as e:
        st.error(f"Failed to start the server: {e}")


def activate_gpt_oss(env=None):
    """Spin up a local GPT-OSS responses server (stub backend) if available."""

    if not env:
        return False

    if st.session_state.get("gpt_oss_server_started"):
        return True

    st.session_state.pop("gpt_oss_autostart_failed", None)
    try:
        import gpt_oss  # noqa: F401
    except ImportError:
        st.warning("Install `gpt-oss` (`pip install gpt-oss`) to enable the offline assistant.")
        st.session_state["gpt_oss_autostart_failed"] = True
        return False

    backend = (
        st.session_state.get("gpt_oss_backend")
        or env.envars.get("GPT_OSS_BACKEND")
        or os.getenv("GPT_OSS_BACKEND")
        or "stub"
    ).strip() or "stub"
    checkpoint = (
        st.session_state.get("gpt_oss_checkpoint")
        or env.envars.get("GPT_OSS_CHECKPOINT")
        or os.getenv("GPT_OSS_CHECKPOINT")
        or ("gpt2" if backend == "transformers" else "")
    ).strip()
    extra_args = (
        st.session_state.get("gpt_oss_extra_args")
        or env.envars.get("GPT_OSS_EXTRA_ARGS")
        or os.getenv("GPT_OSS_EXTRA_ARGS")
        or ""
    ).strip()
    python_exec = (
        env.envars.get("GPT_OSS_PYTHON")
        or os.getenv("GPT_OSS_PYTHON")
        or sys.executable
    )
    requires_checkpoint = backend in {"transformers", "metal", "triton", "vllm"}
    if requires_checkpoint and not checkpoint:
        st.warning(
            "GPT-OSS backend requires a checkpoint. Set `GPT_OSS_CHECKPOINT` in the sidebar or environment."
        )
        st.session_state["gpt_oss_autostart_failed"] = True
        return False

    env.envars["GPT_OSS_BACKEND"] = backend
    if checkpoint:
        env.envars["GPT_OSS_CHECKPOINT"] = checkpoint
    elif "GPT_OSS_CHECKPOINT" in env.envars:
        del env.envars["GPT_OSS_CHECKPOINT"]
    if extra_args:
        env.envars["GPT_OSS_EXTRA_ARGS"] = extra_args

    port = get_random_port()
    while is_port_in_use(port):
        port = get_random_port()

    cmd = (
        f"{shlex.quote(python_exec)} -m gpt_oss.responses_api.serve "
        f"--inference-backend {shlex.quote(backend)} --port {int(port)}"
    )
    if checkpoint and backend != "stub":
        cmd += f" --checkpoint {shlex.quote(checkpoint)}"
    if extra_args:
        cmd = f"{cmd} {extra_args}"

    try:
        subproc(cmd, os.getcwd())
    except RuntimeError as e:
        st.error(f"Failed to start GPT-OSS server: {e}")
        return False

    endpoint = f"http://127.0.0.1:{port}/v1/responses"
    st.session_state["gpt_oss_server_started"] = True
    st.session_state["gpt_oss_port"] = port
    st.session_state["gpt_oss_endpoint"] = endpoint
    env.envars["GPT_OSS_ENDPOINT"] = endpoint
    st.session_state["gpt_oss_backend_active"] = backend
    if checkpoint:
        st.session_state["gpt_oss_checkpoint_active"] = checkpoint
    else:
        st.session_state.pop("gpt_oss_checkpoint_active", None)
    if extra_args:
        st.session_state["gpt_oss_extra_args_active"] = extra_args
    else:
        st.session_state.pop("gpt_oss_extra_args_active", None)
    st.session_state.pop("gpt_oss_autostart_failed", None)
    return True
def _focus_existing_docs_tab(target_url: str) -> bool:
    """Best-effort attempt to focus an existing docs tab instead of opening a new one."""
    if sys.platform != "darwin":
        return False

    escaped = target_url.replace("\\", "\\\\").replace("\"", "\\\"")
    script = f'''
on chrome_activate(targetUrl)
    tell application "Google Chrome"
        repeat with w in windows
            set tabIndex to 0
            repeat with t in tabs of w
                set tabIndex to tabIndex + 1
                if (URL of t is targetUrl) then
                    set active tab index of w to tabIndex
                    set index of w to 1
                    activate
                    return true
                end if
            end repeat
        end repeat
    end tell
    return false
end chrome_activate

on safari_activate(targetUrl)
    tell application "Safari"
        repeat with w in windows
            repeat with t in tabs of w
                if (URL of t is targetUrl) then
                    set current tab of w to t
                    set index of w to 1
                    activate
                    return true
                end if
            end repeat
        end repeat
    end tell
    return false
end safari_activate

tell application "System Events"
    set chromeRunning to (exists process "Google Chrome")
    set safariRunning to (exists process "Safari")
end tell

if chromeRunning then
    if chrome_activate("{escaped}") then return true
end if

if safariRunning then
    if safari_activate("{escaped}") then return true
end if

return false
'''

    try:
        result = subprocess.run(
            ["osascript", "-"],
            input=script,
            text=True,
            capture_output=True,
            timeout=2,
        )
        if result.returncode == 0:
            return result.stdout.strip().lower().endswith("true")
    except Exception:
        pass
    return False
