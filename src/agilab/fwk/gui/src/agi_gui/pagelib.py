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
from typing import Dict
import sys
import logging
import webbrowser

from sqlalchemy import false

# project_root = Path(__file__).parent.parent.parent.parent.parent
#
# for proj in [
#     "*project",
#     "fwk/core",
#     "fwk/env",
# ]:
#     for src in project_root.rglob(f"{proj}/src"):
#         path = str(src)
#         if not src.exists():
#             print(path, "does not exist")
#             exit(1)
#         elif path not in sys.path:
#             print(f"Adding {path} to sys.path")
#             sys.path.insert(0, path)

from agi_env import AgiEnv

env=None

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


# Define a module-level flag
_DOCS_ALREADY_OPENED = False


import webbrowser

def open_docs(env, html_file="index.html", anchor=""):
    """
    Opens the local Sphinx docs in a new browser tab.
    If the local documentation file is not found, it opens the online docs.

    Args:
        env: An environment object that helps locate the docs directory.
        html_file (str): Which HTML file within the docs/build/ folder to open (default 'index.html').
        anchor (str, optional): Optional hash anchor (e.g. '#project-editor').
    """
    global _DOCS_ALREADY_OPENED

    if _DOCS_ALREADY_OPENED:
        print("Documentation is already opened in this session.")
        return

    _DOCS_ALREADY_OPENED = True

    # Build the path to the local file, e.g. gui.html
    docs_path = env.agi_root / "docs" / "build" / html_file

    # Check if the local documentation file exists
    if not docs_path.exists():
        print(f"Documentation file not found: {docs_path.resolve()}.\nOpening online docs instead.")
        online_url = "https://thalesgroup.github.io/agilab/"
        if anchor:
            # Ensure the anchor starts with '#'
            if not anchor.startswith("#"):
                anchor = "#" + anchor
            online_url += anchor
        webbrowser.open_new_tab(online_url)
        return

    # Construct a file:// URL with an optional anchor
    docs_url = f"file://{docs_path}"
    if anchor:
        if not anchor.startswith("#"):
            anchor = "#" + anchor
        docs_url += anchor

    webbrowser.open_new_tab(docs_url)



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
        st.error(f"Error loading {file_path}: {e}")
        return ""

@st.cache_data
def get_css_text():
    global env
    with open(env.resource_path / "code_editor.scss") as file:
        return file.read()

@st.cache_resource
def render_logo(edit_text, _env_=None):
    global env
    if _env_:
        env = _env_
    agilab_logo_path = env.resource_path / "agilab_logo.png"  # Replace with your logo filename
    agilab_logo_base64 = get_base64_of_image(agilab_logo_path)
    if agilab_logo_base64:
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
                content: "v{2025.1}";
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
    global env
    return [p.name for p in env.export_apps.glob("*.zip")]


def get_templates():
    """
    Get a list of template names.

    Returns:
        list: A list of template names (strings).
    """
    global env
    return [p.stem for p in env.apps_dir.glob("*template")]


def get_about_content():
    """
    Get the content of the 'About' section.

    Returns:
        dict: A dictionary containing information about the Agi&trade; fwk.

            'About': str
                A string containing information about the Agi&trade; fwk.

                    ':blue[Agi&trade;] V5\n\n:blue[S]peedy :blue[Py]thon :blue[D]istributed  fwk for Data Science  2020-2024 \n\nThales SIX GTS France SAS \n\nsupport:  focus@thalesgroup.com'
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
    global env
    """
    Initialize a custom user interface based on an input UI snippet.

    Args:
        args_ui_snippet (str): A snippet of UI content to customize the interface.

    Returns:
        None

    Session State Modifiers:
        - 'toggle_custom': The state of the custom toggle based on UI snippet size.
    """
    if "toggle_custom" not in st.session_state:
        st.session_state["toggle_custom"] = env.args_ui_snippet.stat().st_size > 0
    return


def on_project_change(project, switch_to_select=True):
    """
    Callback function to handle project changes.

    This function is optimized for speed and efficiency by minimizing attribute lookups, using tuples for fixed key collections, and leveraging 'del' for key removal.
    """
    global env
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
        env.change_active_app(project, env.install_type)
        module = env.target

        # Update session state with new module and data directory paths
        session_state.module_rel = Path(module)
        session_state.datadir = env.AGILAB_EXPORT_ABS / module
        session_state.datadir_str = str(session_state.datadir)
        st.session_state.df_export_file = session_state.datadir / "export.csv"
        # Synchronize session state with the new project
        session_state.project = project

        # Optional: Set a flag to switch the sidebar tab if needed
        session_state.switch_to_select = switch_to_select

    except Exception as e:
        st.error(f"An error occurred while changing the project: {e}")


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
def find_files(directory, ext=".csv"):
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
    return list(directory.rglob(f"*{ext}"))


@st.cache_data
def get_custom_buttons():
    """
    Retrieve custom buttons data from a JSON file and cache the data.

    Returns:
        dict: Custom buttons data loaded from the JSON file.

    Notes:
        This function uses Streamlit's caching mechanism to avoid reloading the data each time it is called.
    """
    global env
    with open(env.resource_path / "custom_buttons.json") as file:
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
    global env
    with open(env.resource_path / "info_bar.json") as file:
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
    if st.session_state.get("loaded_df") is not None:
        st.session_state.loaded_df.to_csv(st.session_state.df_file_out)
        st.success("saved!")
    else:
        st.warning("DataFrame is empty. Nothing to export.")

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
    global env
    # Regular expression pattern to match the string between "await" and "("
    pattern = r"await\s+(?:Agi\.)?([^\(]+)\("

    # Find all matches in the code
    matches = re.findall(pattern, code)
    snippet_file = os.path.join(
        env.runenv, f"{matches[0]}-{env.target}.py"
    )
    with open(snippet_file, "w") as file:
        file.write(code)
    if (path == env.core_root) or (env.app_path / ".venv").exists():
        return run_with_output(env, f"uv run python {snippet_file}", path)
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
def load_df(path: Path, nrows=None, with_index=True):
    """
    Load data from a specified path. Supports loading from CSV and Parquet files.

    Args:
        path (Path): The path to the file or directory.
        nrows (int, optional): Number of rows to read from the file (for CSV files only).
        with_index (bool): Whether to set the first column as the index (creates an "index" column).

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
            # Concatenate all Parquet files
            df = pd.concat([pd.read_parquet(f) for f in parquet_files], ignore_index=True)
            # Convert binary columns to strings if needed
            binary_columns = [
                col for col in df.select_dtypes(include=["object"]).columns
                if df[col].apply(lambda x: isinstance(x, bytes)).any()
            ]
            for col in binary_columns:
                df[col] = df[col].apply(lambda x: x.decode("utf-8") if isinstance(x, bytes) else x)
        elif csv_files:
            # Concatenate all CSV files
            df = pd.concat([
                pd.read_csv(f, nrows=nrows, encoding="utf-8", index_col=0)
                for f in csv_files
            ], ignore_index=False)
    elif path.is_file():
        if path.suffix == ".csv":
            df = pd.read_csv(path, nrows=nrows, encoding="utf-8", index_col=0)
            if with_index:
                # Set the first column as the new index (if needed)
                df.set_index(df.columns[0], inplace=True)
        elif path.suffix == ".parquet":
            df = pd.read_parquet(path)
            # Convert binary columns to strings if needed
            binary_columns = [
                col for col in df.select_dtypes(include=["object"]).columns
                if df[col].apply(lambda x: isinstance(x, bytes)).any()
            ]
            for col in binary_columns:
                df[col] = df[col].apply(lambda x: x.decode("utf-8") if isinstance(x, bytes) else x)
        else:
            return None
    else:
        return None

    # Optionally add the first column as a new 'index' column
    # if with_index and not df.empty:
    #     # Create the extra "index" column using the first column of the DataFrame.
    #     df["index"] = df.iloc[:, 0]
    #     # Compare the "index" column with the DataFrame's actual index.
    #     if df["index"].equals(df.index.to_series()):
    #         # Drop the extra column if it is identical.
    #         df.drop("index", axis=1, inplace=True)

    return df


def save_csv(df, path: Path, sep=","):
    """
    Save a DataFrame to a CSV file.

    Args:
        df (DataFrame): The DataFrame to save.
        path (Path): The file path to save the CSV.
        sep (str): The separator to use in the CSV file.
    """
    path = Path(path)
    if path.is_dir():
        st.error(f"{path} is a directory instead of a filename.")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if df.shape[1] > 0:
        df.to_csv(path, sep=sep)


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
    List all view Python files in the views directory.

    Args:
        views_root (Path): The root directory of views.

    Returns:
        list: Sorted list of view file paths.
    """
    pattern = os.path.join(views_root, "**", "*.py")
    views = [
        py_file
        for py_file in glob.glob(pattern, recursive=True)
        if not py_file.endswith("__init__.py")
    ]
    return sorted(views)


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


def update_views(project, views):
    """
    Create and remove hard links according to views checkbox.

    Args:
        project (str): The project name.
        views (list): The currently selected views.

    Returns:
        bool: True if an update was required, False otherwise.
    """
    update_required = False
    st.session_state["project"] = project
    st.session_state.preview_tree = False

    pages_root = Path(os.getcwd()) / "src/gui/pages"
    existing_pages = set(os.listdir(pages_root))

    expected_pages = set()
    for view_abs in views:
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
    Render the project selection sidebar.

    :param projects: List of available projects.
    :type projects: list
    :param current_project: Currently selected project.
    :type current_project: str
    :return: Selected project name.
    :rtype: str
    """
    global  env
    st.sidebar.selectbox(
        "Project Name",
        projects,
        index=projects.index(current_project) if current_project in projects else 0,
        on_change=lambda: on_project_change(st.session_state["project_selectbox"]),
        key="project_selectbox",
    )
    return env


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
    global env
    Agi_export_abs = Path(env.AGILAB_EXPORT_ABS)
    modules = st.session_state.get(
        "modules", scan_dir(Agi_export_abs)
    )  # Use the target from Agienv
    # st.session_state.setdefault("index_page", str(module_path.relative_to(env.AGILAB_EXPORT_ABS)))
    # index_page = st.session_state.get("index_page", env.target)

    st.session_state["lab_dir"] = st.sidebar.selectbox(
        "Lab Directory",
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
        (i for i, f in enumerate(df_files_rel) if f.name == default_df),
        0,
    )
    module_path = lab_dir.relative_to(Agi_export_abs)
    st.session_state["module_path"] = module_path
    st.sidebar.selectbox(
        "DataFrame",
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


def activate_mlflow(env_):
    global env
    env = env_

    st.session_state["rapids_default"] = True
    os.makedirs(env.MLFLOW_TRACKING_DIR, exist_ok=True)

    port = get_random_port()
    while is_port_in_use(port):
        port = get_random_port()

    cmd = f"uv run mlflow ui --backend-store-uri file://{env.MLFLOW_TRACKING_DIR} --port {port}"
    try:
        res = subproc(cmd, os.getcwd())
        st.session_state.server_started = True
        st.session_state["mlflow_port"] = port
    except RuntimeError as e:
        st.error(f"Failed to start the server: {e}")
