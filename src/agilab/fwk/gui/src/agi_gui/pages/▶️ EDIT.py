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

import os
import shutil
import json
import time
import zipfile
from pathlib import Path
import ast
import re
import platform
import ctypes
from ctypes import wintypes

import streamlit as st
from agi_gui.pagelib import get_about_content, render_logo
from agi_gui.pagelib import (
    get_classes_name,
    get_fcts_and_attrs_name,
    get_templates,
    get_projects_zip,
    on_project_change,
    select_project,
    open_docs,
    render_logo,
    activate_mlflow
)
from pathspec import PathSpec
from streamlit_modal import Modal
from code_editor import code_editor
from agi_env import AgiEnv


# -------------------- Source Extractor Class -------------------- #


class SourceExtractor(ast.NodeTransformer):
    """
    A class representing a Source Extractor using AST NodeTransformer for Python code manipulation.

    Attributes:
        target_name (str): Name of the function/method to replace.
        class_name (str): Name of the class containing the target.
        new_ast (ast.AST): New AST node to replace the target.
        found (bool): Flag indicating if the target was found during traversal of the AST.
    """

    def __init__(self, target_name=None, class_name=None, new_ast=None):
        """
        Initializes the SourceExtractor.

        Args:
            target_name (str, optional): Name of the function/method to replace. Defaults to None.
            class_name (str, optional): Name of the class containing the target. Defaults to None.
            new_ast (ast.AST, optional): New AST node to replace the target. Defaults to None.
        """
        self.target_name = target_name
        self.class_name = class_name
        self.new_ast = new_ast
        self.found = False

    def visit_ClassDef(self, node):
        """
        Visit a ClassDef node in the AST.

        Args:
            node (ast.ClassDef): The ClassDef node to visit.

        Returns:
            ast.ClassDef: The visited ClassDef node.
        """
        if self.class_name and node.name == self.class_name:
            self.generic_visit(node)
        return node

    def visit_FunctionDef(self, node):
        """
        Visit and potentially modify a FunctionDef node.

        Args:
            self: The object instance.
            node (Node): The FunctionDef node to visit.

        Returns:
            Node: The original FunctionDef node if it does not match the target_name,
            or the modified node if it matches and self.new_ast is set, otherwise returns the original node.

        Raises:
            None.
        """
        if self.target_name and node.name == self.target_name:
            self.found = True
            return self.new_ast if self.new_ast else node
        return node

    def visit_AsyncFunctionDef(self, node):
        """
        Visit an AsyncFunctionDef node in an abstract syntax tree (AST).

        Args:
            self: An instance of a class that visits AST nodes.
            node: The AsyncFunctionDef node being visited.

        Returns:
            ast.AST: The original AsyncFunctionDef node unless a target name is found, in which case it returns a new AST node.
        """
        if self.target_name and node.name == self.target_name:
            self.found = True
            return self.new_ast if self.new_ast else node
        return node

    def visit_Assign(self, node):
        """
        Visit and modify an Assign node.

        Args:
            self: The instance of the class.
            node: The Assign node to be visited.

        Returns:
            ast.AST: The modified Assign node.

        Raises:
            None.
        """
        if not self.class_name:
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == self.target_name:
                    self.found = True
                    return self.new_ast if self.new_ast else node
        return node

    def visit_AnnAssign(self, node):
        """
        Visit an assignment node and potentially replace its target if it matches a specific condition.

        Args:
            node (ast.AnnAssign): The assignment node to visit.

        Returns:
            ast.AnnAssign: The original node if the conditions are not met, or a potentially modified node.
        """
        if not self.class_name:
            if isinstance(node.target, ast.Name) and node.target.id == self.target_name:
                self.found = True
                return self.new_ast if self.new_ast else node
        return node


# -------------------- File Processor -------------------- #

def process_files(root, files, app_path, rename_map, spec):
    """
    Process and copy files, applying renaming and content replacements.

    Args:
        root (str): Root directory path.
        files (list): List of filenames in the root directory.
        app_path (Path): Path to the application directory.
        rename_map (dict): Mapping of old names to new names for renaming.
        spec (PathSpec): Compiled PathSpec object to filter files.
    """
    for file in files:
        relative_file_path = Path(root).joinpath(file).relative_to(app_path)
        if spec.match_file(str(relative_file_path)):
            continue

        new_path = Path(root) / file
        for old, new in rename_map.items():
            new_path = Path(str(new_path).replace(old, new))

        if new_path.exists():
            continue

        try:
            if relative_file_path.suffix == ".7z":
                shutil.copy(Path(root) / file, new_path)
            else:
                with open(Path(root) / file, "r") as f:
                    content = f.read()
                for old, new in rename_map.items():
                    content = content.replace(old, new)
                new_path.write_text(content)
        except Exception as e:
            st.warning(f"Error processing file '{file}': {e}")


def replace_content(content, rename_map):
    """
    Replace occurrences of old names with new names in the content using exact word matching.

    Args:
        content (str): Original file content.
        rename_map (dict): Mapping of old relative paths to new relative paths.

    Returns:
        str: Modified file content.
    """
    for old, new in rename_map.items():
        # Replace only whole word matches to avoid partial replacements
        pattern = re.compile(r"\b{}\b".format(re.escape(old)))
        content = pattern.sub(new, content)
    return content


# -------------------- Project Cleaner -------------------- #


def clean_project(project_path):
    """
    Clean a project directory by removing files and directories matching .gitignore patterns.

    Args:
        project_path (Path): Path to the project directory.
    """
    project_path = Path(project_path)
    gitignore_path = project_path / ".gitignore"

    if not gitignore_path.exists():
        st.warning(f"No .gitignore file found at '{gitignore_path}'.")
        return

    spec = read_gitignore(gitignore_path)

    for root, dirs, files in os.walk(project_path, topdown=False):
        for file in files:
            relative_file_path = Path(root).joinpath(file).relative_to(project_path)
            if spec.match_file(str(relative_file_path)):
                os.remove(Path(root) / file)
        for dir_name in dirs:
            relative_dir_path = Path(root).joinpath(dir_name).relative_to(project_path)
            if spec.match_file(str(relative_dir_path)):
                shutil.rmtree(Path(root) / dir_name, ignore_errors=True)


# -------------------- Project Export Handler -------------------- #


def handle_export_project():
    """
    Handle the export of a project to a zip file.
    """
    global env
    input_dir = env.app_path
    output_zip = (env.export_apps / env.app).with_suffix(".zip")
    gitignore_path = input_dir / ".gitignore"

    if not gitignore_path.exists():
        st.error(f"No .gitignore file found at '{gitignore_path}'.")
        return

    spec = read_gitignore(gitignore_path)

    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as out:
        for root, _, files in os.walk(input_dir):
            rel_root = os.path.relpath(root, input_dir)
            if spec.match_file(rel_root):
                continue
            for file in files:
                relative_file_path = os.path.relpath(
                    os.path.join(root, file), input_dir
                )
                if not spec.match_file(relative_file_path):
                    out.write(os.path.join(root, file), relative_file_path)

    st.session_state["export_message"] = "Export completed."
    time.sleep(1)
    st.session_state["archives"].append(st.session_state["project"] + ".zip")


def import_project(project_zip, ignore=False):
    """
    Import a project from a zip archive.

    Args:
        ignore (bool, optional): Whether to clean the project after import. Defaults to False.
    """
    global env
    zip_path = env.export_apps / project_zip
    project_name = Path(project_zip).stem
    target_dir = env.apps_dir / project_name
    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        zip_ref.extractall(target_dir)
    if ignore:
        clean_project(target_dir)

    st.session_state["project_imported"] = True


# -------------------- Project Name Normalizer -------------------- #


def normalize_project_name(dest):
    """
    Ensure the new project name ends with '_project'.
    """
    dest = dest.replace("_", "-")
    st.session_state.clone_dest = (
        dest + "_project" if not dest.endswith("_project") else dest
    )


# -------------------- Project Cloner (Recursive with .venv Symlink) -------------------- #


def clone_project(target_project, dest_project):
    """
    Clone a project by recursively copying files and directories, applying renaming.
    For the .venv directory, create a symbolic link instead of copying if it's not ignored.

    Args:
        target_project (str): Name of the target project.
        dest_project (str): Name of the destination project.
    """
    global env
    res = env.clone_preject(target_project, dest_project)

    # After cloning, update the session state
    st.session_state["projects"] = env.projects
    st.session_state["project_created"] = True  # Set flag for successful creation
    st.session_state["project"] = dest_project  # Set the new project as current

    # Change the app to the new project
    env.change_active_app(dest_project, env.install_type)

    return res

import ast
import astor
import streamlit as st


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
            st.write(f"Renaming Name: {node.id} ➔ {self.rename_map[node.id]}")
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
            st.write(f"Renaming Attribute: {node.attr} ➔ {self.rename_map[node.attr]}")
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
            st.write(f"Renaming Function: {node.name} ➔ {self.rename_map[node.name]}")
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
            st.write(f"Renaming Class: {node.name} ➔ {self.rename_map[node.name]}")
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
            st.write(f"Renaming Argument: {node.arg} ➔ {self.rename_map[node.arg]}")
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
                st.write(f"Renaming Global Variable: {name} ➔ {self.rename_map[name]}")
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
                st.write(
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
            st.write(
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
                st.write(
                    f"Renaming Import Module: {original_name} ➔ {self.rename_map[original_name]}"
                )
                alias.name = self.rename_map[original_name]
            else:
                # Handle compound module names if necessary
                for old, new in self.rename_map.items():
                    if original_name.startswith(old):
                        st.write(
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
            st.write(
                f"Renaming ImportFrom Module: {node.module} ➔ {self.rename_map[node.module]}"
            )
            node.module = self.rename_map[node.module]
        else:
            for old, new in self.rename_map.items():
                if node.module and node.module.startswith(old):
                    new_module = node.module.replace(old, new, 1)
                    st.write(
                        f"Renaming ImportFrom Module: {node.module} ➔ {new_module}"
                    )
                    node.module = new_module
                    break

        # Rename the imported names
        for alias in node.names:
            if alias.name in self.rename_map:
                st.write(
                    f"Renaming Imported Name: {alias.name} ➔ {self.rename_map[alias.name]}"
                )
                alias.name = self.rename_map[alias.name]
            else:
                for old, new in self.rename_map.items():
                    if alias.name.startswith(old):
                        st.write(
                            f"Renaming Imported Name: {alias.name} ➔ {alias.name.replace(old, new, 1)}"
                        )
                        alias.name = alias.name.replace(old, new, 1)
                        break
        self.generic_visit(node)
        return node

# -------------------- Code Editor Display -------------------- #


def render_code_editor(file, code, lang, tab, comp_props, ace_props, fct=None):
    """
    Display a code editor component with the given code.

    Args:
        file (Path): Path to the file being edited.
        code (str): The code content to display in the editor.
        lang (str): Programming language of the code (for syntax highlighting).
        tab (str): Identifier for the tab in which the editor is placed.
        comp_props (dict): Component properties for the code editor.
        ace_props (dict): Ace editor properties.
        fct (str, optional): Function/method name or 'attributes'. Defaults to None.

    Returns:
        dict or None: The response from the code_editor component, if any.
    """
    target_class = st.session_state.get("selected_class", "module-level")
    if os.access(file, os.W_OK):
        info_bar = json.loads(json.dumps(INFO_BAR))
        info_bar["info"][0]["name"] = file.name
        # Incorporate the file name, class name, tab, and function/item name into the key to ensure uniqueness
        editor_key = f"{file}_{target_class}_{tab}_{fct}"
        response = code_editor(
            code,
            height=min(30, len(code)),
            theme="contrast",
            buttons=CUSTOM_BUTTONS,
            lang=lang,
            info=info_bar,
            component_props=comp_props,
            props=ace_props,
            key=editor_key,
        )
        # Ensure response has the expected structure
        if isinstance(response, dict):
            if response.get("type") == "save" and code != response.get("text", ""):
                updated_text = response["text"]
                if lang == "json":
                    try:
                        # Validate JSON before saving
                        json.loads(updated_text)
                        file.write_text(updated_text)
                        st.success(f"Changes saved to '{file.name}'.")
                        time.sleep(1)
                        if "app_settings" in st.session_state:
                            del st.session_state["app_settings"]
                    except json.JSONDecodeError as e:
                        st.error(f"Failed to save changes: Invalid JSON format. {e}")
                else:
                    # For non-JSON files, save directly
                    file.write_text(updated_text)
                    st.success(f"Changes saved to '{file.name}'.")
    else:
        # Case when the user doesn't have access to write to the file
        st.write(f"### {file.name}")
        st.code(code, lang)
        return None  # No response


# -------------------- Editing Handler -------------------- #


def handle_editing(path: Path, key_prefix: str, comp_props, ace_props):
    """
    Handle the editing of functions/methods and attributes for a given module path.

    Args:
        path (Path): Path to the Python file.
        key_prefix (str): Prefix for Streamlit keys to ensure uniqueness.
        comp_props (dict): Component properties for the code editor.
        ace_props (dict): Ace editor properties.
    """
    if not path.exists():
        st.warning(f"{path} not found.")
        return

    try:
        classes = get_classes_name(path) + ["module-level"]
    except Exception as e:
        st.error(f"Error retrieving classes: {e}")
        return

    # Initialize session_state variables for selected_class and selected_item if not present
    class_state_key = f"selected_class_{key_prefix}"
    item_state_key = f"selected_item_{key_prefix}"

    if class_state_key not in st.session_state:
        st.session_state[class_state_key] = classes[0] if classes else "module-level"
    if item_state_key not in st.session_state:
        st.session_state[item_state_key] = ""

    def update_selected_class():
        """Callback to update selected class and reset selected item."""
        st.session_state[class_state_key] = st.session_state[
            f"{key_prefix}_class_select"
        ]
        st.session_state[item_state_key] = ""

    selected_class = st.selectbox(
        "Select a class:",
        classes,
        key=f"{key_prefix}_class_select",
        index=(
            classes.index(st.session_state[class_state_key])
            if st.session_state[class_state_key] in classes
            else 0
        ),
        on_change=update_selected_class,
    )

    # Get functions and attributes based on the selected class
    try:
        if st.session_state[class_state_key] == "module-level":
            result = get_fcts_and_attrs_name(path)
        else:
            # result = get_fcts_and_attrs_name(path, st.session_state[env.worker_path])
            result = get_fcts_and_attrs_name(path, selected_class)
        functions = result["functions"]
        attributes = result["attributes"]
    except Exception as e:
        st.error(f"Error retrieving functions and attributes: {e}")
        return

    # Combine functions and add 'Attributes' as a single item if there are any attributes
    items = functions.copy()
    if attributes:
        items.append("Attributes")

    # Ensure selected_item is set correctly
    if st.session_state[item_state_key] not in items:
        st.session_state[item_state_key] = items[0] if items else ""

    def update_selected_item():
        """Callback to update selected item."""
        st.session_state[item_state_key] = st.session_state[f"{key_prefix}_item_select"]

    selected_item = st.selectbox(
        "Select a method or attribute:",
        items,
        key=f"{key_prefix}_item_select",
        index=(
            items.index(st.session_state[item_state_key])
            if st.session_state[item_state_key] in items
            else 0
        ),
        on_change=update_selected_item,
    )

    if selected_item:
        if selected_item == "Attributes":
            # Handle the case where 'Attributes' is selected using render_code_editor
            try:
                # Directly extract the attributes code from the AST
                with open(path, "r") as f:
                    source_code = f.read()
                parsed_code = ast.parse(source_code)
                attributes_code = ""
                for node in ast.walk(parsed_code):
                    if (
                            isinstance(node, ast.ClassDef)
                            and node.name == st.session_state[class_state_key]
                    ):
                        for item in node.body:
                            if isinstance(item, (ast.Assign, ast.AnnAssign)):
                                attributes_code += astor.to_source(item)
                    elif (
                            isinstance(node, (ast.Assign, ast.AnnAssign))
                            and st.session_state[class_state_key] == "module-level"
                    ):
                        attributes_code += astor.to_source(node)
            except Exception as ve:
                st.error(f"Error extracting attributes: {ve}")
                return

            # Display the attributes code using render_code_editor
            response = render_code_editor(
                path,
                attributes_code,
                "python",
                "attributes",
                comp_props,
                ace_props,
                fct="attributes",
            )

            # Check if a save action was triggered
            if isinstance(response, dict) and response.get("type") == "save":
                try:
                    updated_attributes_code = response.get("text", attributes_code)
                    # Update the attributes in the original file
                    with open(path, "r") as f:
                        original_source = f.read()
                    parsed_original = ast.parse(original_source)
                    # Create a new AST for the updated attributes
                    new_attributes_ast = ast.parse(updated_attributes_code).body
                    # Use SourceExtractor to inject the new attributes
                    class_updater = SourceExtractor(
                        target_name=None,
                        class_name=(
                            st.session_state[class_state_key]
                            if st.session_state[class_state_key] != "module-level"
                            else None
                        ),
                        new_ast=new_attributes_ast,
                    )
                    updated_ast = class_updater.visit(parsed_original)
                    updated_source = astor.to_source(updated_ast)
                    with open(path, "w") as f:
                        f.write(updated_source)
                    st.success("Attributes updated successfully.")
                except Exception as ve:
                    st.error(f"Error updating attributes: {ve}")
        else:
            # Handle the selected method or function
            try:
                # Extract the function/method code
                with open(path, "r") as f:
                    source_code = f.read()
                parsed_code = ast.parse(source_code)
                function_code = ""
                for node in ast.walk(parsed_code):
                    if isinstance(node, ast.FunctionDef) and node.name == selected_item:
                        function_code = astor.to_source(node)
                        break
                    elif (
                            isinstance(node, ast.AsyncFunctionDef)
                            and node.name == selected_item
                    ):
                        function_code = astor.to_source(node)
                        break
            except Exception as ve:
                st.error(f"Error extracting function/method: {ve}")
                return

            # Display the function/method code using render_code_editor
            response = render_code_editor(
                path,
                function_code,
                "python",
                "function_method",
                comp_props,
                ace_props,
                fct=selected_item,
            )

            # Check if a save action was triggered
            if isinstance(response, dict) and response.get("type") == "save":
                try:
                    updated_function_code = response.get("text", function_code)
                    # Update the function/method in the original file
                    with open(path, "r") as f:
                        original_source = f.read()
                    parsed_original = ast.parse(original_source)
                    # Create a new AST for the updated function/method
                    new_function_ast = ast.parse(updated_function_code).body[0]
                    # Use SourceExtractor to inject the new function/method
                    func_updater = SourceExtractor(
                        target_name=selected_item,
                        class_name=(
                            st.session_state[class_state_key]
                            if st.session_state[class_state_key] != "module-level"
                            else None
                        ),
                        new_ast=new_function_ast,
                    )
                    updated_ast = func_updater.visit(parsed_original)
                    updated_source = astor.to_source(updated_ast)
                    with open(path, "w") as f:
                        f.write(updated_source)
                    st.success(
                        f"Function/Method '{selected_item}' updated successfully."
                    )
                except Exception as ve:
                    st.error(f"Error updating function/method: {ve}")


# -------------------- Sidebar Handlers -------------------- #


def handle_project_selection():
    """
    Handle the 'Select' tab in the sidebar for project selection.
    """
    global env

    projects = st.session_state["projects"]
    current_project = st.session_state["project"]

    if not projects:
        st.warning("No projects available.")
        return

    # Ensure current_project is in projects list
    if current_project not in projects:
        current_project = projects[0]
        st.session_state["project"] = current_project
        # Optionally, trigger a rerun if necessary
        st.rerun()

    # Sidebar project selection
    #st.session_state["project"] = select_project(projects, current_project)
    env = select_project(projects, current_project)

    # Export Button
    side_cols = st.sidebar.columns(2)
    if side_cols[1].button(
            "Export",
            type="secondary",
            use_container_width=True,
            help="this will export your project under ~/Agi_EXPORT_DIR / <your input filename>",
    ):
        handle_export_project()

    # Render Tabs
    tabs = st.tabs(
        [
            "PYTHON-ENV",
            "MANAGER",
            "WORKER",
            "EXPORT-APP-FILTER",
            "APP-SETTINGS",
            "ARGS-UI",
            "PRE-PROMPT",
        ]
    )
    (
        tab_venv,
        tab_manager,
        tab_worker,
        tab_git,
        tab_settings,
        tab_streamlit,
        tab_pre_prompt,
    ) = tabs

    with tab_venv:
        app_venv_file = env.app_path / "pyproject.toml"
        if app_venv_file.exists():
            app_venv = app_venv_file.read_text()
            if "-cu12" in app_venv:
                st.session_state["rapids"] = True
            render_code_editor(
                app_venv_file, app_venv, "toml", "venv", comp_props, ace_props
            )
        else:
            st.warning("App settings file not found.")

    with tab_worker:
        st.header("Edit Worker Module")
        handle_editing(env.worker_path, "edit_tab_worker", comp_props, ace_props)

    with tab_manager:
        st.header("Edit AgiManager Module")
        handle_editing(env.module_path, "edit_tab_manager", comp_props, ace_props)

    with tab_git:
        gitignore_file = env.gitignore_file
        if gitignore_file.exists():
            render_code_editor(
                gitignore_file,
                gitignore_file.read_text(),
                "gitignore",
                "git",
                comp_props,
                ace_props,
            )
        else:
            st.warning("Gitignore file not found.")

    with tab_settings:
        app_settings_file = env.app_settings_file
        if app_settings_file.exists():
            render_code_editor(
                app_settings_file,
                app_settings_file.read_text(),
                "toml",
                "set",
                comp_props,
                ace_props,
            )
        else:
            st.warning("App settings file not found.")

    with tab_streamlit:
        args_ui_snippet = env.args_ui_snippet
        if args_ui_snippet.exists():
            render_code_editor(
                args_ui_snippet,
                args_ui_snippet.read_text(),
                "python",
                "st",
                comp_props,
                ace_props,
            )
        else:
            st.warning("Args UI snippet file not found.")

    with tab_pre_prompt:
        pre_prompt_file = env.app_src_path / "pre_prompt.json"
        if pre_prompt_file.exists():
            with open(pre_prompt_file, "r", encoding="utf-8") as f:
                pre_prompt_content = json.load(f)
                # Serialize the JSON content back to a string with indentation for readability
                pre_prompt_str = json.dumps(pre_prompt_content, indent=4)
                render_code_editor(
                    pre_prompt_file, pre_prompt_str, "json", "st", comp_props, ace_props
                )
        else:
            st.warning("pre_prompt file not found.")


def handle_project_creation():
    """
    Handle the 'Create' tab in the sidebar for project creation.
    """
    st.header("Create New Project")

    st.sidebar.selectbox(
        "From Template",
        st.session_state["templates"],
        key="clone_src",
        on_change=lambda: on_project_change(
            st.session_state["clone_src"], switch_to_select=False
        ),
        index=0,
    )

    clone_dest = st.sidebar.text_input(
        label="Project Name",
        key="clone_dest",
        on_change=lambda: normalize_project_name(st.session_state["clone_dest"]),
    )

    cols = st.sidebar.columns(3)
    if cols[2].button("Create", type="primary", use_container_width=True):
        if not clone_dest:
            st.error("Project name must not be empty.")
        elif (env.apps_dir / clone_dest).exists():
            st.warning(f"Project '{clone_dest}' already exists.")
        else:
            env.clone_project(env.apps_dir, st.session_state["clone_src"], env.apps_dir / clone_dest)
            project_path = env.apps_dir / clone_dest
            if project_path.exists():
                st.success(f"Project '{clone_dest}' successfully created.")
                on_project_change(clone_dest)  # Trigger rerun to apply the change
                # Trigger a sidebar tab switch to 'Select' to reflect the changes
                st.session_state["switch_to_select"] = True
                st.rerun()  #
            else:
                st.error(f"Error while creating '{clone_dest}'.")
    else:
        st.info("Please enter a project name and click 'Create'.")


def handle_project_rename():
    """
    Handle the 'Rename' tab in the sidebar for renaming projects.
    """
    st.header(f"Rename Project '{st.session_state['project']}'")

    # Input for the new project name
    clone_dest = st.sidebar.text_input(
        "New Project Name",
        key="clone_dest",
        on_change=lambda: normalize_project_name(st.session_state["clone_dest"]),
        help="Enter the new name for your project. It will be suffixed with '_project' if not already present.",
    )

    # Rename button
    cols = st.sidebar.columns(3)
    if cols[2].button("Rename", type="primary", use_container_width=True):
        if not clone_dest:
            st.error("Project name must not be empty.")
        elif (env.apps_dir / clone_dest).exists():
            st.warning(f"Project '{clone_dest}' already exists.")
        else:
            src_project = env.app
            clone_project(env.apps_dir, src_project, clone_dest)
            project_path = env.apps_dir / clone_dest
            if project_path.exists():
                st.success(f"Project '{clone_dest}' successfully created.")
                on_project_change(clone_dest)
                shutil.rmtree(src_project, ignore_errors=True)
                # Provide feedback to the user
                st.sidebar.success(
                    f"Project '{st.session_state['project']}' has been renamed to '{clone_dest}'."
                )
                st.session_state["project"] = clone_dest

                # Trigger a sidebar tab switch to 'Select' to reflect the changes
                st.session_state["switch_to_select"] = True
                st.rerun()  # Trigger rerun to apply the change
            else:
                st.error(f"Error: Project '{clone_dest}' was not found after renaming.")
    else:
        st.sidebar.info("Enter a new name for the selected project and click 'Rename'.")


def handle_project_delete():
    """
    Handle the 'Delete' tab in the sidebar for deleting projects.
    """
    st.header("Delete Project")

    # Confirmation checkbox
    confirm_delete = st.checkbox(
        f"I confirm that I want to delete {st.session_state['project']}.",
        key="confirm_delete",
    )

    cols = st.sidebar.columns(3)
    # Delete button
    if cols[2].button("Delete"):
        if not confirm_delete:
            st.error("Please confirm that you want to delete the project.")
        else:
            try:
                project_path = env.app_path
                if project_path.exists():
                    shutil.rmtree(project_path)
                    st.session_state["projects"] = [
                        p
                        for p in st.session_state["projects"]
                        if p != st.session_state["project"]
                    ]
                    if st.session_state["projects"]:
                        on_project_change(st.session_state["projects"][0])
                    st.success(f"Project '{env.app}' has been deleted.")

                    # If the deleted project was the current project, switch to another
                    del st.session_state["templates"]
                    st.session_state["switch_to_select"] = True
                    st.rerun()
                else:
                    st.error(f"Project '{st.session_state['project']}' does not exist.")
            except Exception as e:
                st.error(f"An error occurred while deleting the project: {e}")
    else:
        st.info("Select a project and confirm deletion to remove it.")


def handle_project_import():
    """
    Handle the 'Import' tab in the sidebar for project loading.
    """
    selected_archive = st.sidebar.selectbox(
        f"From {env.export_apps}",
        st.session_state["archives"],
        key="archive",
        help="Select one of the previously exported projects to load it.",
    )

    if selected_archive == "-- Select a file --":
        st.info("Please select a file from the sidebar to continue.")
        # Optionally, you can disable other parts of the app here
    else:
        import_target = selected_archive.replace(".zip", "")
        st.sidebar.checkbox(
            "Clean",
            key="clean_import",
            help="This will remove all the .gitignore file from the project.",
        )

        path = env.apps_dir / selected_archive
        overwrite_modal = Modal("Import project", key="import-modal", max_width=450)
        cols = st.sidebar.columns(3)
        if cols[2].button("Import", type="primary", use_container_width=True):
            if not path.exists():
                import_project(selected_archive, st.session_state["clean_import"])
                st.session_state["project"] = (
                    import_target  # Trigger rerun to apply the change
                )
            else:
                overwrite_modal.open()

        if overwrite_modal.is_open():
            with overwrite_modal.container():
                st.write(f"Project '{import_target}' already exists. Overwrite it?")
                cols = st.columns(2)
                if cols[0].button(
                        "Overwrite", type="primary", use_container_width=True
                ):
                    try:
                        shutil.rmtree(path)
                        import_project(import_target, st.session_state["clean_import"])
                        st.session_state["project"] = import_target
                        overwrite_modal.close()
                    except PermissionError:
                        st.error(f"Project '{import_target}' is not removable.")
                if cols[1].button("Cancel", type="secondary", use_container_width=True):
                    overwrite_modal.close()

        if st.session_state.get("project_imported"):
            project_path = env.apps_dir / import_target
            if project_path.exists():
                st.success(f"Project '{import_target}' successfully imported.")
                on_project_change(import_target)
                # Set the switch flag to switch the sidebar tab
                st.session_state["switch_to_select"] = True
                st.rerun()  # Trigger rerun to apply the change
            else:
                st.error(f"Error while importing '{import_target}'.")
            del st.session_state["project_imported"]


# -------------------- Streamlit Page Rendering -------------------- #


def page():
    """
    Main function to render the Streamlit page.
    """
    global CUSTOM_BUTTONS, INFO_BAR, CSS_TEXT, comp_props, ace_props, env

    env = st.session_state['env']

    render_logo("Edit your Project", env)

    if not st.session_state.get("server_started"):
        activate_mlflow(env)
        st.session_state["server_started"] = True

    # Check if we need to switch the sidebar tab to "Select"
    if st.session_state.get("switch_to_select", False):
        st.session_state["sidebar_selection"] = "Select"
        st.session_state["switch_to_select"] = False
        st.rerun()  # Reset the flag  # Trigger rerun to apply the change

    # Load .agi_resources

    try:
        with open(env.resource_path / "custom_buttons.json") as f:
            CUSTOM_BUTTONS = json.load(f)
        with open(env.resource_path / "info_bar.json") as f:
            INFO_BAR = json.load(f)
        with open(env.resource_path / "code_editor.scss") as f:
            CSS_TEXT = f.read()
    except FileNotFoundError as e:
        st.error(f"Resource file not found: {e}")
        return
    except json.JSONDecodeError as e:
        st.error(f"Error decoding JSON resource: {e}")
        return

    comp_props = {
        "css": CSS_TEXT,
        "globalCSS": ":root {--streamlit-dark-background-color: #111827;}",
    }
    ace_props = {"style": {"borderRadius": "0px 0px 8px 8px"}}

    # Initialize session state variables
    session_defaults = {
        "orchest_functions": ["build_distribution"],
        "project": env.app,
        "projects": env.projects,
        "templates": [env.app] + get_templates(),
        "archives": ["-- Select a file --"] + get_projects_zip(),
        "export_message": "",
        "project_imported": False,
        "project_created": False,
        "show_widgets": [True, False],
        "views": [],
        # Initialize the sidebar_selection with a default value if not set
        "sidebar_selection": (
            "Select"
            if "sidebar_selection" not in st.session_state
            else st.session_state["sidebar_selection"]
        ),
        # Initialize the switch_to_select flag
        "switch_to_select": (
            False
            if "switch_to_select" not in st.session_state
            else st.session_state["switch_to_select"]
        ),
    }

    for key, value in session_defaults.items():
        st.session_state.setdefault(key, value)

    # Sidebar: Project selection, creation, loading
    sidebar_selection = st.sidebar.radio(
        "PROJECT", ["Select", "Create", "Rename", "Delete", "Import"], key="sidebar_selection"
    )

    if sidebar_selection == "Select":
        handle_project_selection()
    elif sidebar_selection == "Create":
        handle_project_creation()
    elif sidebar_selection == "Rename":
        handle_project_rename()
    elif sidebar_selection == "Delete":
        handle_project_delete()
    elif sidebar_selection == "Import":
        handle_project_import()


# -------------------- Main Application Entry -------------------- #


def main():
    """
    Main function to run the application.
    """
    try:
        page()

    except Exception as e:
        st.error(f"An error occurred: {e}")
        import traceback

        st.error(traceback.format_exc())


# -------------------- Main Entry Point -------------------- #

if __name__ == "__main__":
    main()
