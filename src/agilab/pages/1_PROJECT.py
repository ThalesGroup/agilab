# BSD 3-Clause License
#
# Copyright (c) 2025, Jean-Pierre Morard, THALES SIX GTS France SAS
# All rights reserved.
# Co-author: Codex cli
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
import html
from pathlib import Path
import ast
import re
import importlib.util
from types import SimpleNamespace

os.environ.setdefault("STREAMLIT_CONFIG_FILE", str(Path(__file__).resolve().parents[1] / "resources" / "config.toml"))

import streamlit as st
import tomli_w
_import_guard_path = Path(__file__).resolve().parents[1] / "import_guard.py"
_import_guard_spec = importlib.util.spec_from_file_location("agilab_import_guard_local", _import_guard_path)
if _import_guard_spec is None or _import_guard_spec.loader is None:
    raise ModuleNotFoundError(f"Unable to load import_guard.py from {_import_guard_path}")
_import_guard_module = importlib.util.module_from_spec(_import_guard_spec)
_import_guard_spec.loader.exec_module(_import_guard_module)
import_agilab_module = _import_guard_module.import_agilab_module

_page_docs_module = import_agilab_module(
    "agilab.page_docs",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "page_docs.py",
    fallback_name="agilab_page_docs_fallback",
)
get_docs_menu_items = _page_docs_module.get_docs_menu_items

from agi_gui.pagelib import render_logo, inject_theme
from agi_gui.pagelib import (
    background_services_enabled,
    get_classes_name,
    get_fcts_and_attrs_name,
    get_templates,
    get_projects_zip,
    on_project_change,
    render_logo,
    activate_mlflow
)
from agi_gui.ux_widgets import compact_choice
from pathspec import PathSpec
from pathspec.patterns import GitWildMatchPattern
from streamlit_modal import Modal
from code_editor import code_editor
from agi_env import AgiEnv, normalize_path

_code_editor_support_module = import_agilab_module(
    "agilab.code_editor_support",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "code_editor_support.py",
    fallback_name="agilab_code_editor_support_fallback",
)
normalize_custom_buttons = _code_editor_support_module.normalize_custom_buttons

_page_bootstrap_module = import_agilab_module(
    "agilab.page_bootstrap",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "page_bootstrap.py",
    fallback_name="agilab_page_bootstrap_fallback",
)
ensure_page_env = _page_bootstrap_module.ensure_page_env

_pinned_expander_module = import_agilab_module(
    "agilab.pinned_expander",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "pinned_expander.py",
    fallback_name="agilab_pinned_expander_fallback",
)
render_pinned_expanders = _pinned_expander_module.render_pinned_expanders
is_pinned_expander = _pinned_expander_module.is_pinned_expander
remove_pinned_expander = _pinned_expander_module.remove_pinned_expander
upsert_pinned_expander = _pinned_expander_module.upsert_pinned_expander

_workflow_ui_module = import_agilab_module(
    "agilab.workflow_ui",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "workflow_ui.py",
    fallback_name="agilab_workflow_ui_fallback",
)
render_page_context = _workflow_ui_module.render_page_context

_page_project_selector_module = import_agilab_module(
    "agilab.page_project_selector",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "page_project_selector.py",
    fallback_name="agilab_page_project_selector_fallback",
)
render_project_selector = _page_project_selector_module.render_project_selector

_action_execution_module = import_agilab_module(
    "agilab.action_execution",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "action_execution.py",
    fallback_name="agilab_action_execution_fallback",
)
ActionResult = _action_execution_module.ActionResult
ActionSpec = _action_execution_module.ActionSpec
render_action_result = _action_execution_module.render_action_result
run_streamlit_action = _action_execution_module.run_streamlit_action

_notebook_pipeline_import_module = import_agilab_module(
    "agilab.notebook_pipeline_import",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "notebook_pipeline_import.py",
    fallback_name="agilab_notebook_pipeline_import_fallback",
)
_build_lab_stages_preview = _notebook_pipeline_import_module.build_lab_stages_preview
_build_notebook_import_contract = _notebook_pipeline_import_module.build_notebook_import_contract
_build_notebook_import_pipeline_view = (
    _notebook_pipeline_import_module.build_notebook_import_pipeline_view
)
_build_notebook_import_preflight = _notebook_pipeline_import_module.build_notebook_import_preflight
_build_notebook_import_view_plan = _notebook_pipeline_import_module.build_notebook_import_view_plan
_build_notebook_pipeline_import = _notebook_pipeline_import_module.build_notebook_pipeline_import
_discover_notebook_import_view_manifest = (
    _notebook_pipeline_import_module.discover_notebook_import_view_manifest
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]

CREATE_MODE_TEMPLATE = "Template clone"
CREATE_MODE_NOTEBOOK = "From notebook"
NOTEBOOK_PROJECT_DEFAULT_TEMPLATE = "pandas_app_template"
NOTEBOOK_SOURCE_DIR = Path("notebooks") / "source"
NOTEBOOK_STEPS_FILE = "lab_stages.toml"

CLONE_ENV_STRATEGY_LABELS = {
    "share_source_venv": "Temporary clone (share source .venv)",
    "detach_venv": "Working clone (no shared .venv)",
}

CLONE_ENV_STRATEGY_CAPTIONS = {
    "share_source_venv": (
        "Fast and lightweight. The clone keeps the source .venv by symlink, "
        "so cleaning or deleting the source environment can break it."
    ),
    "detach_venv": (
        "Safer for real development. The clone is created without .venv, "
        "so run INSTALL before EXECUTE."
    ),
}
CLONE_ENV_STRATEGY_HELP = (
    f"{CLONE_ENV_STRATEGY_LABELS['share_source_venv']}: "
    f"{CLONE_ENV_STRATEGY_CAPTIONS['share_source_venv']}\n\n"
    f"{CLONE_ENV_STRATEGY_LABELS['detach_venv']}: "
    f"{CLONE_ENV_STRATEGY_CAPTIONS['detach_venv']}"
)
EDITOR_PIN_RESPONSE = "editor_pin"
EDITOR_UNPIN_RESPONSE = "editor_unpin"


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
                content = (Path(root) / file).read_text()
                for old, new in rename_map.items():
                    content = content.replace(old, new)
                new_path.write_text(content)
        except (OSError, UnicodeDecodeError) as e:
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
    boundary = r"(?<![0-9A-Za-z_]){token}(?![0-9A-Za-z_])"
    for old, new in sorted(rename_map.items(), key=lambda kv: len(kv[0]), reverse=True):
        pattern = re.compile(boundary.format(token=re.escape(old)))
        content = pattern.sub(new, content)
    return content


def _path_exists_or_symlink(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _remove_path_if_present(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.exists():
        shutil.rmtree(path)


def _read_python_source(path: Path) -> str:
    return path.read_text()


def _parse_python_file(path: Path) -> tuple[str, ast.AST]:
    source_code = _read_python_source(path)
    return source_code, ast.parse(source_code)


def _extract_attributes_code(parsed_code: ast.AST, selected_class: str) -> str:
    attributes_code = ""
    for node in ast.walk(parsed_code):
        if isinstance(node, ast.ClassDef) and node.name == selected_class:
            for item in node.body:
                if isinstance(item, (ast.Assign, ast.AnnAssign)):
                    attributes_code += astor.to_source(item)
        elif (
            isinstance(node, (ast.Assign, ast.AnnAssign))
            and selected_class == "module-level"
        ):
            attributes_code += astor.to_source(node)
    return attributes_code


def _extract_function_code(parsed_code: ast.AST, selected_item: str) -> str:
    for node in ast.walk(parsed_code):
        if isinstance(node, ast.FunctionDef) and node.name == selected_item:
            return astor.to_source(node)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == selected_item:
            return astor.to_source(node)
    return ""


def _replace_attribute_nodes(
    body: list[ast.stmt], new_attributes_ast: list[ast.stmt]
) -> list[ast.stmt]:
    kept_body = [node for node in body if not isinstance(node, (ast.Assign, ast.AnnAssign))]
    first_attribute_index = next(
        (index for index, node in enumerate(body) if isinstance(node, (ast.Assign, ast.AnnAssign))),
        None,
    )
    if first_attribute_index is None:
        return [*new_attributes_ast, *kept_body]

    kept_before = [
        node
        for node in body[:first_attribute_index]
        if not isinstance(node, (ast.Assign, ast.AnnAssign))
    ]
    kept_after = [
        node
        for node in body[first_attribute_index:]
        if not isinstance(node, (ast.Assign, ast.AnnAssign))
    ]
    return [*kept_before, *new_attributes_ast, *kept_after]


def _build_updated_attributes_source(
    original_source: str, updated_attributes_code: str, selected_class: str
) -> str:
    parsed_original = ast.parse(original_source)
    new_attributes_ast = ast.parse(updated_attributes_code).body
    if selected_class == "module-level":
        parsed_original.body = _replace_attribute_nodes(parsed_original.body, new_attributes_ast)
        return astor.to_source(parsed_original)

    for node in parsed_original.body:
        if isinstance(node, ast.ClassDef) and node.name == selected_class:
            node.body = _replace_attribute_nodes(node.body, new_attributes_ast)
            return astor.to_source(parsed_original)

    raise ValueError(f"Class '{selected_class}' not found.")


def _build_updated_function_source(
    original_source: str, updated_function_code: str, selected_item: str, selected_class: str
) -> str:
    parsed_original = ast.parse(original_source)
    new_function_body = ast.parse(updated_function_code).body
    if not new_function_body:
        raise ValueError("Updated function/method code is empty.")
    new_function_ast = new_function_body[0]
    if not isinstance(new_function_ast, (ast.FunctionDef, ast.AsyncFunctionDef)):
        raise ValueError("Updated code must define a function or method.")
    func_updater = SourceExtractor(
        target_name=selected_item,
        class_name=selected_class if selected_class != "module-level" else None,
        new_ast=new_function_ast,
    )
    updated_ast = func_updater.visit(parsed_original)
    if not func_updater.found:
        raise ValueError(f"Function/Method '{selected_item}' not found.")
    return astor.to_source(updated_ast)


def _write_python_source(path: Path, source_code: str) -> None:
    path.write_text(source_code)


def _save_code_editor_file_action(file: Path, updated_text: str, lang: str) -> ActionResult:
    path = Path(file)
    if lang == "json":
        try:
            json.loads(updated_text)
        except json.JSONDecodeError as exc:
            return ActionResult.error(
                f"Failed to save changes to '{path.name}'.",
                detail=f"Invalid JSON format. {exc}",
                next_action="Fix the JSON syntax and save again.",
                data={"file": path},
            )

    try:
        path.write_text(updated_text, encoding="utf-8")
    except OSError as exc:
        return ActionResult.error(
            f"Failed to save changes to '{path.name}'.",
            detail=str(exc),
            next_action="Check filesystem permissions and retry.",
            data={"file": path},
        )

    return ActionResult.success(
        f"Changes saved to '{path.name}'.",
        data={"file": path, "lang": lang},
    )


def _update_attributes_source_action(
    path: Path,
    updated_attributes_code: str,
    selected_class: str,
) -> ActionResult:
    try:
        original_source = _read_python_source(path)
        updated_source = _build_updated_attributes_source(
            original_source,
            updated_attributes_code,
            selected_class,
        )
        _write_python_source(path, updated_source)
    except (OSError, UnicodeDecodeError, SyntaxError, TypeError, ValueError) as exc:
        return ActionResult.error(
            "Error updating attributes.",
            detail=str(exc),
            next_action="Fix the attributes snippet and save again.",
            data={"file": path, "selected_class": selected_class},
        )

    return ActionResult.success(
        "Attributes updated successfully.",
        data={"file": path, "selected_class": selected_class},
    )


def _update_function_source_action(
    path: Path,
    updated_function_code: str,
    selected_item: str,
    selected_class: str,
) -> ActionResult:
    try:
        original_source = _read_python_source(path)
        updated_source = _build_updated_function_source(
            original_source,
            updated_function_code,
            selected_item,
            selected_class,
        )
        _write_python_source(path, updated_source)
    except (OSError, UnicodeDecodeError, SyntaxError, TypeError, ValueError) as exc:
        return ActionResult.error(
            f"Error updating function/method '{selected_item}'.",
            detail=str(exc),
            next_action="Fix the function snippet and save again.",
            data={
                "file": path,
                "selected_item": selected_item,
                "selected_class": selected_class,
            },
        )

    return ActionResult.success(
        f"Function/Method '{selected_item}' updated successfully.",
        data={
            "file": path,
            "selected_item": selected_item,
            "selected_class": selected_class,
        },
    )


def _resolve_clone_source_root(env: AgiEnv, target_project: Path) -> Path:
    source_project = target_project
    templates_root = env.apps_path / "templates"
    if not source_project.name.endswith("_project"):
        candidate = source_project.with_name(source_project.name + "_project")
        if (env.apps_path / candidate).exists() or (templates_root / candidate).exists():
            source_project = candidate

    source_root = env.apps_path / source_project
    if not source_root.exists() and templates_root.exists():
        source_root = templates_root / source_project
    return source_root


def _finalize_cloned_project_environment(
    source_root: Path,
    dest_root: Path,
    strategy: str,
) -> str | None:
    dest_venv = dest_root / ".venv"
    source_venv = source_root / ".venv"

    if strategy == "detach_venv":
        if _path_exists_or_symlink(dest_venv):
            _remove_path_if_present(dest_venv)
        return (
            f"Project '{dest_root.name}' was created without sharing the source .venv. "
            "Run INSTALL before EXECUTE."
        )

    if strategy == "share_source_venv":
        if _path_exists_or_symlink(dest_venv):
            if source_venv.exists():
                return (
                    f"Project '{dest_root.name}' shares the source .venv for fast local iteration."
                )
            return (
                f"Project '{dest_root.name}' shares the source .venv via symlink."
            )
        return (
            f"Project '{dest_root.name}' was created without a .venv because the source project "
            "did not expose one."
        )

    raise ValueError(f"Unknown clone environment strategy: {strategy}")


def _repair_renamed_project_environment(source_root: Path, dest_root: Path) -> str | None:
    source_venv = source_root / ".venv"
    dest_venv = dest_root / ".venv"

    if not _path_exists_or_symlink(source_venv):
        return None

    if _path_exists_or_symlink(dest_venv):
        _remove_path_if_present(dest_venv)

    shutil.move(str(source_venv), str(dest_venv))
    return f"Preserved the project .venv while renaming '{source_root.name}'."


# -------------------- Gitignore Reader -------------------- #


@st.cache_data
def read_gitignore(gitignore_path):
    """Return a :class:`PathSpec` built from ``gitignore_path``.

    When the project does not ship a ``.gitignore`` we still want to allow
    exports, so we fall back to an empty ignore list instead of raising.
    """

    try:
        with open(gitignore_path, "r") as f:
            patterns = f.read().splitlines()
    except FileNotFoundError:
        patterns = []

    return PathSpec.from_lines(GitWildMatchPattern, patterns)
# -------------------- Project Cleaner -------------------- #


def clean_project(project_path):
    """
    Clean a project directory by removing files and directories matching .gitignore patterns.

    Args:
        project_path (Path): Path to the project directory.
    """
    project_path = Path(project_path)
    gitignore_path = project_path / ".gitignore"

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


def _safe_remove_path(candidate, label, errors):
    """
    Remove a file or directory, capturing failures in ``errors``.
    """

    if not candidate:
        return
    path = Path(candidate)
    try:
        exists = path.exists() or path.is_symlink()
    except OSError as exc:
        errors.append(f"{label}: {exc}")
        return
    if not exists:
        return
    try:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        errors.append(f"{label}: {exc}")


def _regex_replace(path, regex, replacement, label, errors):
    if not path.exists():
        return
    try:
        text = path.read_text()
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(f"{label}: {exc}")
        return
    new_text = re.sub(regex, replacement, text)
    if new_text == text:
        return
    try:
        path.write_text(new_text)
    except OSError as exc:
        errors.append(f"{label}: {exc}")


def _cleanup_run_configuration_artifacts(app_name, target_name, errors):
    run_dir = PROJECT_ROOT / ".idea" / "runConfigurations"
    if not run_dir.exists():
        return

    to_delete = set()
    for pattern in {f"_{target_name}*.xml", f"_{app_name}*.xml"}:
        to_delete.update(run_dir.glob(pattern))

    for xml_path in run_dir.glob("*.xml"):
        if xml_path in to_delete:
            continue
        if xml_path.name == "folders.xml":
            continue
        try:
            text = xml_path.read_text()
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"Read {xml_path.name}: {exc}")
            continue
        if app_name in text or target_name in text:
            to_delete.add(xml_path)

    for xml_path in to_delete:
        try:
            xml_path.unlink()
        except FileNotFoundError:
            continue
        except OSError as exc:
            errors.append(f"Remove {xml_path.name}: {exc}")

    folders_xml = run_dir / "folders.xml"
    _regex_replace(
        folders_xml,
        rf'\s*<folder name="{re.escape(app_name)}"\s*/>\s*',
        "\n",
        "Update run configuration folders",
        errors,
    )


def _cleanup_module_artifacts(app_name, target_name, errors):
    modules_dir = PROJECT_ROOT / ".idea" / "modules"
    removed_files = set()
    if modules_dir.exists():
        for pattern in {f"{app_name}*.iml", f"{target_name}*.iml"}:
            for module_file in modules_dir.glob(pattern):
                removed_files.add(module_file.name)
                _safe_remove_path(module_file, f"IDE module {module_file.name}", errors)

    modules_xml = PROJECT_ROOT / ".idea" / "modules.xml"
    if removed_files:
        joined = "|".join(re.escape(name) for name in sorted(removed_files))
        _regex_replace(
            modules_xml,
            rf'\s*<module\b[^>]*?(?:modules/(?:{joined}))"[^>]*/>\s*',
            "\n",
            "Update modules.xml",
            errors,
        )


# -------------------- Project Export Handler -------------------- #


def _export_project_action(env: AgiEnv) -> ActionResult:
    input_dir = Path(env.active_app)
    if not input_dir.exists():
        return ActionResult.error(
            f"Project '{env.app}' does not exist.",
            next_action="Refresh the PROJECT page or select another project.",
            data={"app": env.app, "input_dir": input_dir},
        )

    output_zip = (env.export_apps / env.app).with_suffix(".zip")
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    gitignore_path = input_dir / ".gitignore"
    detail = None if gitignore_path.exists() else "No .gitignore found; exported all files."
    spec = read_gitignore(gitignore_path)

    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as out:
        for root, _, files in os.walk(input_dir):
            rel_root = os.path.relpath(root, input_dir)
            if spec.match_file(rel_root):
                continue
            for file in files:
                source_path = Path(root) / file
                relative_file_path = os.path.relpath(source_path, input_dir)
                if not spec.match_file(relative_file_path):
                    out.write(source_path, relative_file_path)

    app_zip = env.app + ".zip"
    return ActionResult.success(
        f"Project exported to {output_zip}",
        detail=detail,
        data={"app": env.app, "app_zip": app_zip, "output_zip": output_zip},
    )


def handle_export_project():
    """
    Handle the export of a project to a zip file.
    """
    env = st.session_state["env"]

    def _remember_export(result):
        app_zip = str(result.data["app_zip"])
        archives = st.session_state.setdefault("archives", ["-- Select a file --"])
        if app_zip not in archives:
            archives.append(app_zip)
        st.session_state["export_message"] = "Export completed."

    run_streamlit_action(
        st,
        ActionSpec(
            name="Export project",
            start_message=f"Exporting project '{env.app}'...",
            failure_title="Project export failed.",
            failure_next_action="Check the project path, export directory, and filesystem permissions.",
        ),
        lambda: _export_project_action(env),
        on_success=_remember_export,
    )


def _import_project_action(
    env: AgiEnv,
    *,
    project_zip: str,
    clean: bool = False,
    overwrite: bool = False,
) -> ActionResult:
    selected_archive = str(project_zip).strip()
    if not selected_archive or selected_archive == "-- Select a file --":
        return ActionResult.error(
            "Please select a project archive.",
            next_action="Choose an exported project zip from the sidebar.",
        )

    zip_path = env.export_apps / selected_archive
    if not zip_path.exists():
        return ActionResult.error(
            f"Project archive '{selected_archive}' does not exist.",
            next_action=f"Check {env.export_apps} or export the project again.",
            data={"project_zip": selected_archive, "zip_path": zip_path},
        )

    import_target = Path(selected_archive).stem
    target_dir = env.apps_path / import_target
    if target_dir.exists():
        if not overwrite:
            return ActionResult.warning(
                f"Project '{import_target}' already exists.",
                next_action="Confirm overwrite to replace the existing project.",
                data={
                    "project_zip": selected_archive,
                    "import_target": import_target,
                    "target_dir": target_dir,
                },
            )
        try:
            shutil.rmtree(target_dir)
        except OSError as exc:
            return ActionResult.error(
                f"Project '{import_target}' is not removable.",
                detail=str(exc),
                next_action="Check filesystem permissions, then retry the import.",
                data={
                    "project_zip": selected_archive,
                    "import_target": import_target,
                    "target_dir": target_dir,
                },
            )

    try:
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(target_dir)
        if clean:
            clean_project(target_dir)
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile) as exc:
        return ActionResult.error(
            f"Project archive '{selected_archive}' could not be imported.",
            detail=str(exc),
            next_action="Check that the archive is a valid exported project zip.",
            data={
                "project_zip": selected_archive,
                "import_target": import_target,
                "target_dir": target_dir,
                "zip_path": zip_path,
            },
        )

    if not target_dir.exists():
        return ActionResult.error(
            f"Error while importing '{import_target}'.",
            next_action="Check archive contents and filesystem permissions.",
            data={
                "project_zip": selected_archive,
                "import_target": import_target,
                "target_dir": target_dir,
            },
        )

    return ActionResult.success(
        f"Project '{import_target}' successfully imported.",
        data={
            "project_zip": selected_archive,
            "import_target": import_target,
            "target_dir": target_dir,
            "clean": clean,
            "overwrite": overwrite,
        },
    )


def import_project(project_zip, ignore=False):
    """
    Import a project from a zip archive.

    Args:
        ignore (bool, optional): Whether to clean the project after import. Defaults to False.
    """
    env = st.session_state["env"]
    result = _import_project_action(
        env,
        project_zip=project_zip,
        clean=ignore,
        overwrite=True,
    )
    st.session_state["project_imported"] = result.status == "success"
    return result


# -------------------- Project Cloner (Recursive with .venv Symlink) -------------------- #
    def clone_directory(self,
                        source_dir: Path,
                        dest_dir: Path,
                        rename_map: dict,
                        spec: PathSpec,
                        source_root: Path):
        """
        Recursively copy + rename directories, files, and contents.
        """
        import ast, astor

        for item in source_dir.iterdir():
            rel = item.relative_to(source_root).as_posix()
            # skip .gitignore’d files
            if spec.match_file(rel + ("/" if item.is_dir() else "")):
                continue

            # 1) Build a new relative path by applying map only to entire segments
            parts = rel.split("/")
            for i, seg in enumerate(parts):
                for old, new in sorted(rename_map.items(), key=lambda kv: -len(kv[0])):
                    if seg == old:
                        parts[i] = new
                        break
            new_rel = "/".join(parts)
            dst = dest_dir / new_rel
            dst.parent.mkdir(parents=True, exist_ok=True)

            # 2) Recurse / copy
            if item.is_dir():
                if item.name == ".venv":
                    os.symlink(item, dst, target_is_directory=True)
                else:
                    self.clone_directory(item, dest_dir, rename_map, spec, source_root)

            elif item.is_file():
                suf = item.suffix.lower()

                # Python → AST rename + whole‑word replace
                if suf == ".py":
                    src = item.read_text()
                    try:
                        tree = ast.parse(src)
                        tree = ContentRenamer(rename_map).visit(tree)
                        ast.fix_missing_locations(tree)
                        out = astor.to_source(tree)
                    except SyntaxError:
                        out = src
                    out = replace_content(out, rename_map)
                    dst.write_text(out, encoding="utf-8")

                # text files → whole‑word replace
                elif suf in (".toml", ".md", ".txt", ".json", ".yaml", ".yml"):
                    txt = item.read_text()
                    txt = replace_content(txt, rename_map)
                    dst.write_text(txt, encoding="utf-8")

                # archives or binaries
                else:
                    shutil.copy2(item, dst)

            elif item.is_symlink():
                target = os.readlink(item)
                os.symlink(target, dst, target_is_directory=item.is_dir())


def clone_directory(self,
                    source_dir: Path,
                    dest_dir: Path,
                    rename_map: dict,
                    spec: PathSpec,
                    source_root: Path):
    """
    Recursively copy + rename directories, files, and contents.
    """
    for item in source_dir.iterdir():
        rel = item.relative_to(source_root).as_posix()
        # skip .gitignore’d files
        if spec.match_file(rel + ("/" if item.is_dir() else "")):
            continue

        # 1) Build a new relative path by applying map only to entire segments
        parts = rel.split("/")
        for i, seg in enumerate(parts):
            for old, new in sorted(rename_map.items(), key=lambda kv: -len(kv[0])):
                if seg == old:
                    parts[i] = new
                    break
        new_rel = "/".join(parts)

        dst = dest_dir / new_rel
        dst.parent.mkdir(parents=True, exist_ok=True)

        # 2) Recurse / copy
        if item.is_dir():
            if item.name == ".venv":
                os.symlink(item, dst, target_is_directory=True)
            else:
                self.clone_directory(item, dest_dir, rename_map, spec, source_root)

        elif item.is_file():
            suf = item.suffix.lower()

            # First, if the **basename** matches an old→new, rename the file itself
            base = item.stem
            if base in rename_map:
                dst = dst.with_name(rename_map[base] + item.suffix)

            # Archives
            if suf in (".7z", ".zip"):
                shutil.copy2(item, dst)

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
                out = replace_content(out, rename_map)
                dst.write_text(out, encoding="utf-8")

            # Text files → whole‑word replace
            elif suf in (".toml", ".md", ".txt", ".json", ".yaml", ".yml"):
                txt = item.read_text(encoding="utf-8")
                txt = replace_content(txt, rename_map)
                dst.write_text(txt, encoding="utf-8")

            # Everything else
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
    # Build simple name→new map (no slashes)
    simple_map = {old: new for old, new in rename_map.items() if "/" not in old}
    # Sort longest first
    sorted_simple = sorted(simple_map.items(), key=lambda kv: len(kv[0]), reverse=True)

    # -- phase 1: rename basenames bottom-up --
    for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        old_name = path.name
        # exact matches
        for old, new in sorted_simple:
            if old_name == old:
                path.rename(path.with_name(new))
                break
            if old_name == f"{old}_worker" or old_name == f"{old}_project":
                path.rename(path.with_name(old_name.replace(old, new, 1)))
                break
            if path.is_file() and old_name.startswith(old + "."):
                # e.g. flight.py → truc.py
                new_name = new + old_name[len(old):]
                path.rename(path.with_name(new_name))
                break

    # -- phase 2: rewrite any lingering references in text files --
    exts = {".py", ".toml", ".md", ".json", ".yaml", ".yml", ".txt"}
    for file in root.rglob("*"):
        if not file.is_file() or file.suffix.lower() not in exts:
            continue
        txt = file.read_text(encoding="utf-8")
        new_txt = replace_content(txt, rename_map)
        if new_txt != txt:
            file.write_text(new_txt, encoding="utf-8")


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


def _project_editor_panel_id(
    file: Path,
    tab: str,
    fct: str | None = None,
    scope: str | None = None,
) -> str:
    path = Path(file).resolve()
    scope_part = str(scope or "default")
    fct_part = str(fct or "file")
    return f"project-editor:{scope_part}:{path}:{tab}:{fct_part}"


def _project_editor_pin_title(file: Path, fct: str | None = None) -> str:
    path = Path(file)
    parent = path.parent.name
    title = f"{parent}/{path.name}" if parent else path.name
    if fct:
        title = f"{title}:{fct}"
    return title


def _project_editor_body_format(lang: str) -> str:
    return "markdown" if str(lang).lower() in {"markdown", "md"} else "code"


def _project_editor_toolbar_buttons(base_buttons, *, pinned: bool):
    try:
        buttons_payload = json.loads(json.dumps(base_buttons or []))
    except (TypeError, ValueError):
        buttons_payload = []
    if isinstance(buttons_payload, dict):
        toolbar_buttons = buttons_payload.get("buttons", [])
        if not isinstance(toolbar_buttons, list):
            toolbar_buttons = []
    elif isinstance(buttons_payload, list):
        toolbar_buttons = buttons_payload
    else:
        toolbar_buttons = []
    response_type = EDITOR_UNPIN_RESPONSE if pinned else EDITOR_PIN_RESPONSE
    pin_button = {
        "name": "Unpin" if pinned else "Pin",
        "feather": "Bookmark",
        "hasText": True,
        "alwaysOn": True,
        "commands": [
            "save-state",
            [
                "response",
                response_type,
            ],
        ],
        "style": {
            "top": "-0.25rem",
            "right": "6.8rem",
            "backgroundColor": "#ffffff",
            "borderColor": "#4A90E2",
            "color": "#4A90E2",
        },
    }
    insert_at = 1 if toolbar_buttons else 0
    toolbar_buttons.insert(insert_at, pin_button)
    return toolbar_buttons


def _upsert_project_editor_pin(
    file: Path,
    body: str,
    lang: str,
    tab: str,
    fct: str | None = None,
    scope: str | None = None,
) -> None:
    path = Path(file)
    upsert_pinned_expander(
        st.session_state,
        _project_editor_panel_id(path, tab, fct, scope),
        title=_project_editor_pin_title(path, fct),
        body=body,
        body_format=_project_editor_body_format(lang),
        language="" if _project_editor_body_format(lang) == "markdown" else lang,
        source=str(path),
        caption="Pinned editor content.",
    )


def _pin_project_editor(
    file: Path,
    body: str,
    lang: str,
    tab: str,
    fct: str | None = None,
    scope: str | None = None,
) -> None:
    _upsert_project_editor_pin(file, body, lang, tab, fct, scope=scope)
    st.rerun()


def _unpin_project_editor(
    file: Path,
    tab: str,
    fct: str | None = None,
    scope: str | None = None,
) -> None:
    remove_pinned_expander(
        st.session_state,
        _project_editor_panel_id(Path(file), tab, fct, scope),
    )
    st.rerun()

def render_code_editor(file, code, lang, tab, comp_props, ace_props, fct=None, buttons=None, scope: str | None = None):
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
    path = Path(file)
    editor_scope = f"{scope}" if scope else str(tab)
    class_state_key = f"selected_class_{editor_scope}"
    target_class = st.session_state.get(class_state_key, "module-level")
    if os.access(path, os.W_OK):
        panel_id = _project_editor_panel_id(path, tab, fct, editor_scope)
        pinned = is_pinned_expander(st.session_state, panel_id)
        if pinned:
            _upsert_project_editor_pin(path, code, lang, tab, fct, scope=editor_scope)
        info_bar = json.loads(json.dumps(INFO_BAR))
        info_bar["info"][0]["name"] = path.name
        # Include a stable scope, file path, class name, tab and function/item name.
        editor_key = f"{editor_scope}:{path}:{target_class}:{tab}:{fct}"
        response = code_editor(
            code,
            height=min(30, len(code)),
            theme="contrast",
            buttons=_project_editor_toolbar_buttons(
                buttons if buttons is not None else CUSTOM_BUTTONS,
                pinned=pinned,
            ),
            lang=lang,
            info=info_bar,
            component_props=comp_props,
            props=ace_props,
            key=editor_key,
        )
        # Ensure response has the expected structure
        if isinstance(response, dict):
            response_type = response.get("type")
            if response_type == EDITOR_PIN_RESPONSE:
                _pin_project_editor(path, response.get("text", code), lang, tab, fct, scope=editor_scope)
            elif response_type == EDITOR_UNPIN_RESPONSE:
                _unpin_project_editor(path, tab, fct, scope=editor_scope)
            elif response_type == "save" and code != response.get("text", ""):
                updated_text = response["text"]
                if fct is not None:
                    return response
                result = _save_code_editor_file_action(path, updated_text, lang)
                render_action_result(st, result)
                if result.status == "success" and lang == "json":
                    time.sleep(1)
                    st.session_state.pop("app_settings", None)
        return response
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
    def update_selected_class():
        """Callback to update selected class and reset selected item."""
        st.session_state[class_state_key] = st.session_state[f"{key_prefix}_class_select"]
        st.session_state[item_state_key] = ""

    def update_selected_item():
        """Callback to update selected item."""
        st.session_state[item_state_key] = st.session_state[f"{key_prefix}_item_select"]

    if not path.exists():
        st.warning(f"{path} not found.")
        return

    try:
        classes = get_classes_name(path) + ["module-level"]
    except (OSError, UnicodeDecodeError) as e:
        st.error(f"Error retrieving classes: {e}")
        return

    # Initialize session_state variables for selected_class and selected_item if not present
    class_state_key = f"selected_class_{key_prefix}"
    item_state_key = f"selected_item_{key_prefix}"

    if class_state_key not in st.session_state:
        st.session_state[class_state_key] = classes[0] if classes else "module-level"
    if item_state_key not in st.session_state:
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
        cls = selected_class if selected_class != "module-level"  else None
        # result = get_fcts_and_attrs_name(path, st.session_state[env.worker_path])
        result = get_fcts_and_attrs_name(path, cls)
        functions = result["functions"]
        attributes = result["attributes"]
    except (FileNotFoundError, OSError, SyntaxError, ValueError) as e:
        st.error(f"Error retrieving functions and attributes: {e}")
        return

    # Combine functions and add 'Attributes' as a single item if there are any attributes
    items = functions.copy()
    if attributes:
        items.append("Attributes")

    # Ensure selected_item is set correctly
    if st.session_state[item_state_key] not in items:
        st.session_state[item_state_key] = items[0] if items else ""

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
                _, parsed_code = _parse_python_file(path)
                attributes_code = _extract_attributes_code(
                    parsed_code,
                    st.session_state[class_state_key],
                )
            except (OSError, UnicodeDecodeError, SyntaxError, TypeError) as ve:
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
                scope=key_prefix,
            )

            # Check if a save action was triggered
            if isinstance(response, dict) and response.get("type") == "save":
                result = _update_attributes_source_action(
                    path,
                    response.get("text", attributes_code),
                    st.session_state[class_state_key],
                )
                render_action_result(st, result)
        else:
            # Handle the selected method or function
            try:
                _, parsed_code = _parse_python_file(path)
                function_code = _extract_function_code(parsed_code, selected_item)
            except (OSError, UnicodeDecodeError, SyntaxError, TypeError) as ve:
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
                scope=key_prefix,
            )

            # Check if a save action was triggered
            if isinstance(response, dict) and response.get("type") == "save":
                result = _update_function_source_action(
                    path,
                    response.get("text", function_code),
                    selected_item,
                    st.session_state[class_state_key],
                )
                render_action_result(st, result)


# -------------------- Sidebar Handlers -------------------- #


def handle_project_selection():
    """
    Handle the 'Select' tab in the sidebar for project selection.
    Each section is presented inside an expander for easier navigation.
    """
    env = st.session_state["env"]
    projects = env.projects

    if not projects:
        st.warning("No projects available.")
        return

    _render_project_software_metrics(env)
    st.markdown("### Edit project files")

    # Keep all sections visible; each renderer handles its own absence checks.
    sections = [
        ("Documentation / README", lambda: _render_readme(env)),
        ("Configuration / app settings", lambda: _render_app_settings(env)),
        ("Configuration / arguments model", lambda: _render_app_args_module(env)),
        ("Configuration / arguments UI", lambda: _render_args_ui(env)),
        ("Runtime / manager environment", lambda: _render_python_env(env)),
        ("Runtime / worker environment", lambda: _render_worker_python_env(env)),
        ("Runtime / uv overrides", lambda: _render_uv_env(env)),
        ("Runtime / export filter", lambda: _render_gitignore(env)),
        ("AI / pre-prompt", lambda: _render_pre_prompt(env)),
        ("Code / manager", lambda: _render_manager(env)),
        ("Code / worker", lambda: _render_worker(env)),
    ]

    for label, render_fn in sections:
        icon = _expander_icon(label)
        title = f"{icon} {label}" if icon else label
        with st.expander(title, expanded=False):
            render_fn()





def _render_active_project_sidebar(env) -> None:
    projects = list(getattr(env, "projects", []) or [])
    if not projects:
        st.sidebar.info("No projects available.")
        return

    render_project_selector(
        st,
        projects,
        env.app,
        on_change=on_project_change,
        show_edit_button=False,
    )
    env = st.session_state["env"]
    st.session_state["_env"] = env


def _render_sidebar_export_action(env) -> None:
    if not getattr(env, "app", None):
        return
    if st.sidebar.button(
        "Export",
        type="secondary",
        width="stretch",
        help=f"Export to {(env.export_apps / env.app).with_suffix('.zip')}",
    ):
        handle_export_project()


def _safe_display_path(value) -> str:
    if value in (None, ""):
        return "not configured"
    try:
        return str(Path(value).expanduser())
    except (TypeError, ValueError, RuntimeError):
        return str(value)


_INCOMPLETE_HEADER_VALUE_TOKENS = (
    "incomplete",
    "missing",
    "not configured",
    "not selected",
    "not set",
    "unknown",
)


def _header_value_state(value: str, caption: str = "") -> str:
    normalized = f"{value or ''} {caption or ''}".strip().lower()
    if not normalized:
        return "incomplete"
    if any(token in normalized for token in _INCOMPLETE_HEADER_VALUE_TOKENS):
        return "incomplete"
    return "ready"


def _render_metric_card(container, label: str, value: str, caption: str) -> None:
    state = _header_value_state(value, caption)
    container.markdown(
        (
            f"<div class='agilab-header-card agilab-header-card--{state}'>"
            f"<div class='agilab-header-label'>{html.escape(label)}</div>"
            f"<div class='agilab-header-value agilab-header-value--{state}'>{html.escape(str(value))}</div>"
            f"<div class='agilab-header-caption'>{html.escape(caption)}</div>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def _render_project_metric(label: str, value: str, caption: str) -> None:
    _render_metric_card(st, label, value, caption)


_SOFTWARE_METRIC_EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "htmlcov",
    "venv",
}
_SOFTWARE_METRIC_DOC_SUFFIXES = {".md", ".rst"}
_SOFTWARE_METRIC_CONFIG_SUFFIXES = {".cfg", ".ini", ".json", ".toml", ".yaml", ".yml"}
_SOFTWARE_METRIC_CONFIG_NAMES = {".env", ".gitignore", "Dockerfile"}


def _iter_project_metric_files(project_root: Path):
    try:
        root = Path(project_root)
    except TypeError:
        return
    if not root.exists():
        return
    for current_root, dirs, files in os.walk(root):
        dirs[:] = sorted(
            dirname
            for dirname in dirs
            if dirname not in _SOFTWARE_METRIC_EXCLUDED_DIRS and not dirname.startswith(".")
        )
        for filename in sorted(files):
            yield Path(current_root) / filename


def _python_source_line_count(source: str) -> int:
    return sum(1 for line in source.splitlines() if line.strip() and not line.lstrip().startswith("#"))


def _is_test_file(path: Path, project_root: Path) -> bool:
    try:
        rel = path.relative_to(project_root)
    except ValueError:
        rel = path
    return path.name.startswith("test_") or "test" in rel.parts or "tests" in rel.parts


def _project_metric_tokens(project_root: Path) -> tuple[str, ...]:
    tokens = {project_root.name}
    if project_root.name.endswith("_project"):
        tokens.add(project_root.name.removesuffix("_project"))
    src_root = project_root / "src"
    if src_root.exists():
        for child in sorted(src_root.iterdir()):
            if child.is_dir() and (child / "__init__.py").exists():
                tokens.add(child.name)
    return tuple(sorted(token.lower().replace("-", "_") for token in tokens if len(token) >= 3))


def _test_filename_matches_project_token(path: Path, tokens: tuple[str, ...]) -> bool:
    stem_parts = path.stem.lower().replace("-", "_").split("_")
    for token in tokens:
        token_parts = token.split("_")
        token_len = len(token_parts)
        if any(stem_parts[index:index + token_len] == token_parts for index in range(len(stem_parts) - token_len + 1)):
            return True
    return False


def _iter_repo_project_test_files(project_root: Path):
    repo_root = Path(__file__).resolve().parents[3]
    repo_tests = repo_root / "test"
    if not repo_tests.exists():
        return
    try:
        project_root.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return
    tokens = _project_metric_tokens(project_root)
    if not tokens:
        return
    for path in sorted(repo_tests.glob("test_*.py")):
        if _test_filename_matches_project_token(path, tokens):
            yield path


def _project_software_metric_summary(project_root: Path | None) -> dict[str, int] | None:
    if project_root is None or not project_root.exists():
        return None
    summary = {
        "source_files": 0,
        "source_lines": 0,
        "test_files": 0,
        "functions": 0,
        "classes": 0,
        "docs_config": 0,
    }
    counted_tests: set[Path] = set()
    for path in _iter_project_metric_files(project_root):
        suffix = path.suffix.lower()
        if suffix in _SOFTWARE_METRIC_DOC_SUFFIXES:
            summary["docs_config"] += 1
        if suffix in _SOFTWARE_METRIC_CONFIG_SUFFIXES or path.name in _SOFTWARE_METRIC_CONFIG_NAMES:
            summary["docs_config"] += 1
        if suffix != ".py":
            continue
        is_test = _is_test_file(path, project_root)
        if is_test:
            summary["test_files"] += 1
            counted_tests.add(path.resolve())
        else:
            summary["source_files"] += 1
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if not is_test:
            summary["source_lines"] += _python_source_line_count(source)
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        summary["functions"] += sum(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) for node in ast.walk(tree))
        summary["classes"] += sum(isinstance(node, ast.ClassDef) for node in ast.walk(tree))
    for path in _iter_repo_project_test_files(project_root):
        resolved = path.resolve()
        if resolved in counted_tests:
            continue
        summary["test_files"] += 1
        counted_tests.add(resolved)
    return summary


def _ast_base_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _ast_base_name(node.value)
    if isinstance(node, ast.Call):
        return _ast_base_name(node.func)
    return ""


def _project_worker_class_summary(project_root: Path | None) -> tuple[str, str]:
    if project_root is None:
        return "unknown", "project root missing"

    candidate_roots = [project_root] if project_root.exists() else []
    builtin_root = project_root.parent / "builtin" / project_root.name
    if builtin_root.exists() and builtin_root not in candidate_roots:
        candidate_roots.append(builtin_root)
    if not candidate_roots:
        return "unknown", "project root missing"

    discovered: list[tuple[str, str, Path]] = []
    fallback_base_workers: list[tuple[str, str, Path]] = []
    for root in candidate_roots:
        for path in _iter_project_metric_files(root):
            if path.suffix.lower() != ".py" or _is_test_file(path, root):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            except (OSError, SyntaxError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                bases = [_ast_base_name(base) for base in node.bases]
                worker_bases = [base for base in bases if base.endswith("Worker") and base != "BaseWorker"]
                if node.name.endswith("Worker") or worker_bases:
                    base_name = next((base for base in worker_bases if base != node.name), None)
                    discovered.append((base_name or "Worker", node.name, path))
                elif "BaseWorker" in bases:
                    fallback_base_workers.append(("BaseWorker", node.name, path))
        if discovered:
            break

    if not discovered and fallback_base_workers:
        discovered = fallback_base_workers
    if not discovered:
        return "unknown", "no worker class found"

    discovered.sort(key=lambda item: (0 if item[1].endswith("Worker") else 1, str(item[2]), item[1]))
    base_name, class_name, _path = discovered[0]
    extra = len(discovered) - 1
    caption = class_name if extra == 0 else f"{class_name} + {extra} more"
    return base_name, caption


def _render_project_software_metrics(env) -> None:
    active_app = Path(getattr(env, "active_app", "")) if getattr(env, "active_app", None) else None
    summary = _project_software_metric_summary(active_app)
    if summary is None:
        _render_project_metric("Software metrics", "missing", _safe_display_path(active_app))
        return
    worker_class, worker_caption = _project_worker_class_summary(active_app)
    with st.container(border=True):
        top_cols = st.columns(3)
        with top_cols[0]:
            _render_project_metric("Worker class", worker_class, worker_caption)
        with top_cols[1]:
            _render_project_metric("Source LOC", str(summary["source_lines"]), "non-empty, non-comment Python lines")
        with top_cols[2]:
            _render_project_metric("Tests", str(summary["test_files"]), "test_*.py and test/ files")

        bottom_cols = st.columns(3)
        with bottom_cols[0]:
            _render_project_metric("Functions", str(summary["functions"]), "sync and async definitions")
        with bottom_cols[1]:
            _render_project_metric("Classes", str(summary["classes"]), "Python class definitions")
        with bottom_cols[2]:
            _render_project_metric("Docs/config", str(summary["docs_config"]), "docs, TOML, JSON, YAML")


def _expander_icon(label: str) -> str:
    """Return an emoji prefix based on the expander name."""
    mapping = {
        "README": "📘",
        "PYTHON-ENV": "⚙️",
        "PYTHON-ENV-EXTRA": "⚙️",
        "PYTHON-ENV-WORKER": "⚙️",
        "LOGS": "⚙️",
        "PRE-PROMPT": "️⚙️",
        "EXPORT-APP-FILTER": "⚙️",
        "APP-SETTINGS": "🔧",
        "APP-ARGS": "🔧",
        "APP-ARGS-FORM": "🔧",
        "MANAGER": "🐍",
        "WORKER": "🐍",
        "DOCUMENTATION": "📘",
        "CONFIGURATION": "🔧",
        "RUNTIME": "⚙️",
        "AI": "⚙️",
        "CODE": "🐍",
    }
    normalized = label.strip().upper().replace("‑", "-")
    for key, icon in mapping.items():
        if normalized.startswith(key):
            return icon
    return ""

# helper functions

def _render_python_env(env):
    app_venv_file = env.active_app / "pyproject.toml"
    if app_venv_file.exists():
        app_venv = app_venv_file.read_text()
        render_code_editor(
            app_venv_file,
            app_venv,
            "toml",
            "pyproject",
            comp_props,
            ace_props,
            scope="pyproject-manager",
        )
    else:
        st.warning("Manager pyproject.toml file not found.")

def _render_worker_python_env(env):
    worker_pyproject = getattr(env, "worker_pyproject", None)
    manager_pyproject = env.active_app / "pyproject.toml"
    if (
        isinstance(worker_pyproject, Path)
        and worker_pyproject.exists()
        and worker_pyproject != manager_pyproject
    ):
        render_code_editor(
            worker_pyproject,
            worker_pyproject.read_text(),
            "toml",
            "worker-pyproject",
            comp_props,
            ace_props,
            scope="pyproject-worker",
        )
    else:
        st.warning("No worker-specific pyproject.toml is defined for this project.")

def _render_uv_env(env):
    app_venv_file = getattr(env, "uvproject", env.active_app / "uv_config.toml")
    if app_venv_file.exists():
        app_venv = app_venv_file.read_text()
        if "-cu12" in app_venv:
            st.session_state["rapids"] = True
        render_code_editor(
            app_venv_file,
            app_venv,
            "toml",
            "uv",
            comp_props,
            ace_props,
            scope="uv-config",
        )
    else:
        st.warning("No uv_config.toml is defined for this project.")

def _render_manager(env):
    st.header("Edit Manager Module")
    handle_editing(env.manager_path, "edit_tab_manager", comp_props, ace_props)

def _render_worker(env):
    st.header("Edit Worker Module")
    handle_editing(env.worker_path, "edit_tab_worker", comp_props, ace_props)

def _render_gitignore(env):
    gitignore_file = env.gitignore_file
    if gitignore_file.exists():
        render_code_editor(
            gitignore_file,
            gitignore_file.read_text(),
            "gitignore",
            "git",
            comp_props,
            ace_props,
            scope="gitignore",
        )
    else:
        st.warning("Gitignore file not found.")

def _render_app_settings(env):
    app_settings_file = getattr(env, "app_settings_file", None)
    if app_settings_file is None:
        st.warning("App settings file is not configured for this project.")
        return

    try:
        app_settings_file = env.resolve_user_app_settings_file(ensure_exists=True)
    except (AttributeError, RuntimeError, OSError, TypeError, ValueError):
        # Keep backward-compatible behavior: fall back to the existing path.
        pass

    if app_settings_file.exists():
        env.app_settings_file = app_settings_file
        render_code_editor(
            app_settings_file,
            app_settings_file.read_text(),
            "toml",
            "set",
            comp_props,
            ace_props,
            scope="app-settings",
        )
    else:
        st.warning("App settings file not found.")

def _render_app_args_module(env):
    target = env.target
    if not target:
        st.warning("Runtime module not resolved; argument helpers unavailable.")
        return

    module_name = f"{target}_args.py"
    args_module_py = env.app_src / target / module_name
    if args_module_py.exists():
        render_code_editor(
            args_module_py,
            args_module_py.read_text(),
            "python",
            "st",
            comp_props,
            ace_props,
            scope="app-args-module",
        )
    else:
        st.warning(f"{module_name} file not found.")


def _render_readme(env):
    readme_file = env.active_app / "README.md"
    if readme_file.exists():
        readme_text = readme_file.read_text(encoding="utf-8")
        render_code_editor(
            readme_file,
            readme_text,
            "markdown",
            "readme",
            comp_props,
            ace_props,
            scope="readme",
        )
    else:
        st.warning("README.md file not found.")


def _render_args_ui(env):
    app_args_form = env.app_args_form
    if app_args_form.exists():
        render_code_editor(
            app_args_form,
            app_args_form.read_text(),
            "python",
            "st",
            comp_props,
            ace_props,
            scope="app-args-ui",
        )
    else:
        st.warning("Args UI snippet file not found.")

def _render_pre_prompt(env):
    global comp_props, ace_props
    candidates = [
        env.app_src / "pre_prompt.json",
        env.app_src / "app_arg_prompt.json",
        env.app_src / "app_args_prompt.json",
    ]
    target = next((p for p in candidates if p.exists()), None)
    if not target:
        st.warning("No pre_prompt/app_arg prompt file found.")
        return

    with open(target, "r", encoding="utf-8") as f:
        try:
            pre_prompt_content = json.load(f)
            pre_prompt_str = json.dumps(pre_prompt_content, indent=4)
            language = "json"
        except json.JSONDecodeError:
            f.seek(0)
            pre_prompt_str = f.read()
            language = "markdown"

    ace = {**ace_props, "language": language}

    render_code_editor(
        target,
        pre_prompt_str,
        language,
        "st",
        comp_props,
        ace,
        scope="pre-prompt",
    )


def _create_project_clone_action(
    env: AgiEnv,
    *,
    clone_source: str | Path,
    raw_project_name: str,
    clone_env_strategy: str,
) -> ActionResult:
    raw = raw_project_name.strip()
    if not raw:
        return ActionResult.error("Project name must not be empty.")

    new_name = normalize_project_name(raw)
    if not new_name:
        return ActionResult.error("Could not normalize project name.")

    dest_root = env.apps_path / new_name
    if dest_root.exists():
        return ActionResult.warning(
            f"Project '{new_name}' already exists.",
            next_action="Choose another project name or remove the existing project first.",
            data={"new_name": new_name, "dest_root": dest_root},
        )

    clone_source_path = Path(clone_source)
    clone_source_root = _resolve_clone_source_root(env, clone_source_path)
    try:
        env.clone_project(clone_source_path, Path(new_name))
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return ActionResult.error(
            f"Project '{new_name}' could not be cloned.",
            detail=str(exc),
            next_action="Check the clone source, destination path, and filesystem permissions.",
            data={
                "new_name": new_name,
                "dest_root": dest_root,
                "clone_source": clone_source_path,
            },
        )

    if not dest_root.exists():
        return ActionResult.error(
            f"Error while creating '{new_name}'.",
            next_action="Check the clone source, destination path, and filesystem permissions.",
            data={"new_name": new_name, "dest_root": dest_root},
        )

    try:
        status_message = _finalize_cloned_project_environment(
            clone_source_root,
            dest_root,
            clone_env_strategy,
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return ActionResult.error(
            f"Project '{new_name}' was created, but environment finalization failed.",
            detail=str(exc),
            next_action="Check the cloned .venv state, then rerun INSTALL before EXECUTE.",
            data={
                "new_name": new_name,
                "dest_root": dest_root,
                "clone_source": clone_source_path,
                "clone_env_strategy": clone_env_strategy,
            },
        )
    return ActionResult.success(
        f"Project '{new_name}' created.",
        detail=status_message,
        data={
            "new_name": new_name,
            "dest_root": dest_root,
            "clone_source": clone_source_path,
            "clone_env_strategy": clone_env_strategy,
        },
    )


def _safe_uploaded_notebook_name(uploaded_notebook) -> str:
    raw_name = str(getattr(uploaded_notebook, "name", "") or "source.ipynb")
    name = Path(raw_name).name
    if not name.lower().endswith(".ipynb"):
        stem = Path(name).stem or "source"
        name = f"{stem}.ipynb"
    name = re.sub(r"[^0-9A-Za-z._-]+", "_", name).strip("._")
    return name if name else "source.ipynb"


def _read_uploaded_notebook_bytes(uploaded_notebook) -> bytes:
    if uploaded_notebook is None:
        raise ValueError("No notebook file was uploaded.")

    getvalue = getattr(uploaded_notebook, "getvalue", None)
    if callable(getvalue):
        raw = getvalue()
    else:
        seek = getattr(uploaded_notebook, "seek", None)
        if callable(seek):
            try:
                seek(0)
            except (OSError, ValueError):
                pass
        raw = uploaded_notebook.read()
        if callable(seek):
            try:
                seek(0)
            except (OSError, ValueError):
                pass

    if isinstance(raw, bytes):
        return raw
    if isinstance(raw, str):
        return raw.encode("utf-8")
    if raw is None:
        return b""
    return bytes(raw)


def _decode_notebook_upload(uploaded_notebook) -> dict:
    raw = uploaded_notebook.read()
    if isinstance(raw, bytes):
        text = raw.decode("utf-8")
    else:
        text = str(raw)
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("Invalid notebook format: expected a JSON object.")
    return payload


def _build_project_notebook_import_preview(uploaded_notebook, module_dir: Path) -> dict:
    notebook_content = _decode_notebook_upload(uploaded_notebook)
    module = Path(module_dir).name or "notebook_import_project"
    source_name = str(getattr(uploaded_notebook, "name", "") or "uploaded.ipynb")
    notebook_import = _build_notebook_pipeline_import(
        notebook=notebook_content,
        source_notebook=source_name,
    )
    preflight = _build_notebook_import_preflight(notebook_import)
    return {
        "source_name": source_name,
        "module": module,
        "cell_count": int(notebook_import.get("summary", {}).get("pipeline_stage_count", 0) or 0),
        "toml_content": _build_lab_stages_preview(notebook_import, module_name=module),
        "notebook_import": notebook_import,
        "preflight": preflight,
        "contract": _build_notebook_import_contract(
            notebook_import,
            preflight=preflight,
            module_name=module,
        ),
    }


def _write_project_notebook_import_preview(
    preview: dict,
    module_dir: Path,
    stages_file: Path,
) -> int:
    module_dir = Path(module_dir)
    stages_file = Path(stages_file)
    module = str(preview.get("module", "") or module_dir.name or "notebook_import_project")
    preflight = preview.get("preflight", {})
    notebook_import = preview.get("notebook_import", {})

    stages_file.parent.mkdir(parents=True, exist_ok=True)
    with open(stages_file, "wb") as toml_file:
        tomli_w.dump(preview.get("toml_content", {}), toml_file)

    contract = _build_notebook_import_contract(
        notebook_import,
        preflight=preflight,
        module_name=module,
    )
    pipeline_view = _build_notebook_import_pipeline_view(
        notebook_import,
        preflight=preflight,
        module_name=module,
    )
    view_manifest_path = _discover_notebook_import_view_manifest(module_dir)
    view_plan = _build_notebook_import_view_plan(
        notebook_import,
        preflight=preflight,
        module_name=module,
        manifest_path=view_manifest_path,
    )

    (module_dir / "notebook_import_contract.json").write_text(
        json.dumps(contract, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (module_dir / "notebook_import_pipeline_view.json").write_text(
        json.dumps(pipeline_view, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (module_dir / "notebook_import_view_plan.json").write_text(
        json.dumps(view_plan, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return int(preview.get("cell_count", 0) or 0)


def _notebook_import_blocking_detail(preflight) -> str:
    if not isinstance(preflight, dict):
        return "Notebook preflight did not produce a valid report."
    summary = preflight.get("summary", {})
    risk_counts = preflight.get("risk_counts", {})
    details = [
        f"status={preflight.get('status', 'unknown')}",
        f"stages={int(summary.get('pipeline_stage_count', 0) or 0)}",
        f"errors={int(risk_counts.get('error', 0) or 0)}",
        f"warnings={int(risk_counts.get('warning', 0) or 0)}",
    ]
    errors = preflight.get("risks", [])
    first_error = next(
        (
            str(item.get("message", ""))
            for item in errors
            if isinstance(item, dict) and item.get("level") == "error"
        ),
        "",
    )
    if first_error:
        details.append(first_error)
    return "; ".join(details)


def _notebook_project_detail(clone_detail, preflight, cell_count: int) -> str:
    summary = preflight.get("summary", {}) if isinstance(preflight, dict) else {}
    risk_counts = preflight.get("risk_counts", {}) if isinstance(preflight, dict) else {}
    parts = [
        f"Imported {cell_count} notebook code cell(s).",
        (
            f"Artifact contract: {int(summary.get('input_count', 0) or 0)} input(s), "
            f"{int(summary.get('output_count', 0) or 0)} output(s), "
            f"{int(summary.get('unknown_artifact_count', 0) or 0)} unknown."
        ),
    ]
    warning_count = int(risk_counts.get("warning", 0) or 0)
    if warning_count:
        parts.append(f"Preflight warnings: {warning_count}.")
    if clone_detail:
        parts.append(str(clone_detail))
    return " ".join(parts)


def _create_project_from_notebook_action(
    env: AgiEnv,
    *,
    template_source: str | Path,
    raw_project_name: str,
    uploaded_notebook,
    clone_env_strategy: str,
) -> ActionResult:
    raw = raw_project_name.strip()
    if not raw:
        return ActionResult.error("Project name must not be empty.")

    new_name = normalize_project_name(raw)
    if not new_name:
        return ActionResult.error("Could not normalize project name.")

    dest_root = env.apps_path / new_name
    if dest_root.exists():
        return ActionResult.warning(
            f"Project '{new_name}' already exists.",
            next_action="Choose another project name or remove the existing project first.",
            data={"new_name": new_name, "dest_root": dest_root},
        )

    try:
        notebook_bytes = _read_uploaded_notebook_bytes(uploaded_notebook)
    except (OSError, TypeError, ValueError) as exc:
        return ActionResult.error(
            "Notebook upload could not be read.",
            detail=str(exc),
            next_action="Upload a valid .ipynb file and retry.",
            data={"new_name": new_name, "dest_root": dest_root},
        )
    if not notebook_bytes.strip():
        return ActionResult.error(
            "Notebook upload is empty.",
            next_action="Upload a valid .ipynb file and retry.",
            data={"new_name": new_name, "dest_root": dest_root},
        )

    notebook_name = _safe_uploaded_notebook_name(uploaded_notebook)
    notebook_relative_path = NOTEBOOK_SOURCE_DIR / notebook_name
    preview_upload = SimpleNamespace(
        name=notebook_relative_path.as_posix(),
        type=getattr(uploaded_notebook, "type", "application/x-ipynb+json"),
        read=lambda: notebook_bytes,
    )
    try:
        preview = _build_project_notebook_import_preview(preview_upload, dest_root)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return ActionResult.error(
            "Notebook import preview failed.",
            detail=str(exc),
            next_action="Check that the upload is a valid .ipynb notebook.",
            data={"new_name": new_name, "dest_root": dest_root},
        )

    preflight = preview.get("preflight", {})
    if not isinstance(preflight, dict) or not preflight.get("safe_to_import"):
        return ActionResult.error(
            "Notebook cannot create a project yet.",
            detail=_notebook_import_blocking_detail(preflight),
            next_action="Fix the notebook import errors, then retry project creation.",
            data={"new_name": new_name, "dest_root": dest_root, "preflight": preflight},
        )

    clone_result = _create_project_clone_action(
        env,
        clone_source=template_source,
        raw_project_name=new_name,
        clone_env_strategy=clone_env_strategy,
    )
    if clone_result.status != "success":
        return clone_result

    notebook_path = dest_root / notebook_relative_path
    stages_file = dest_root / NOTEBOOK_STEPS_FILE
    try:
        notebook_path.parent.mkdir(parents=True, exist_ok=True)
        notebook_path.write_bytes(notebook_bytes)
        cell_count = _write_project_notebook_import_preview(preview, dest_root, stages_file)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return ActionResult.error(
            f"Project '{new_name}' was created, but notebook import failed.",
            detail=str(exc),
            next_action="Open WORKFLOW for the project and retry notebook import.",
            data={
                **dict(clone_result.data),
                "new_name": new_name,
                "dest_root": dest_root,
                "source_notebook": notebook_relative_path.as_posix(),
                "notebook_path": notebook_path,
                "stages_file": stages_file,
                "preflight": preflight,
            },
        )

    return ActionResult.success(
        f"Project '{new_name}' created from notebook.",
        detail=_notebook_project_detail(clone_result.detail, preflight, cell_count),
        data={
            **dict(clone_result.data),
            "new_name": new_name,
            "dest_root": dest_root,
            "source_notebook": notebook_relative_path.as_posix(),
            "notebook_path": notebook_path,
            "stages_file": stages_file,
            "notebook_import_cell_count": cell_count,
            "notebook_import_preflight": preflight,
            "notebook_import_contract": preview.get("contract", {}),
        },
    )


def _rename_project_action(
    env: AgiEnv,
    *,
    raw_project_name: str,
) -> ActionResult:
    current = env.app
    raw = raw_project_name.strip()
    if not raw:
        return ActionResult.error("Project name must not be empty.")

    new_name = normalize_project_name(raw)
    if not new_name:
        return ActionResult.error("Could not normalize project name.")

    src_path = env.apps_path / current
    dest_path = env.apps_path / new_name
    if dest_path.exists():
        return ActionResult.warning(
            f"Project '{new_name}' already exists.",
            next_action="Choose another project name or remove the existing project first.",
            data={"current": current, "new_name": new_name, "dest_path": dest_path},
        )

    try:
        env.clone_project(Path(current), Path(new_name))
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return ActionResult.error(
            f"Project '{current}' could not be cloned to '{new_name}'.",
            detail=str(exc),
            next_action="Check the source project, destination path, and filesystem permissions.",
            data={
                "current": current,
                "new_name": new_name,
                "src_path": src_path,
                "dest_path": dest_path,
            },
        )

    if not dest_path.exists():
        return ActionResult.error(
            f"Error: Project '{new_name}' not found after renaming.",
            next_action="Check the source project, destination path, and filesystem permissions.",
            data={"current": current, "new_name": new_name, "dest_path": dest_path},
        )

    details: list[str] = []
    try:
        renamed_venv_message = _repair_renamed_project_environment(src_path, dest_path)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return ActionResult.error(
            f"Project '{new_name}' was cloned, but environment preservation failed.",
            detail=str(exc),
            next_action=(
                f"Inspect {src_path} and {dest_path}, then rerun INSTALL before EXECUTE."
            ),
            data={
                "current": current,
                "new_name": new_name,
                "src_path": src_path,
                "dest_path": dest_path,
            },
        )
    if renamed_venv_message:
        details.append(renamed_venv_message)
    if src_path.exists():
        try:
            shutil.rmtree(src_path)
        except OSError as exc:
            details.append(f"Project was renamed, but failed to remove {src_path}: {exc}")

    return ActionResult.success(
        f"Project renamed: '{current}' -> '{new_name}'",
        detail="\n\n".join(details) or None,
        next_action=(
            f"Remove the old project directory manually: {src_path}"
            if src_path.exists()
            else None
        ),
        data={
            "current": current,
            "new_name": new_name,
            "src_path": src_path,
            "dest_path": dest_path,
        },
    )


def _delete_project_action(
    env: AgiEnv,
    *,
    confirmed: bool,
) -> ActionResult:
    app_name = env.app
    if not confirmed:
        return ActionResult.error(
            "Please confirm that you want to delete the project.",
            next_action="Tick the confirmation checkbox before deleting.",
            data={"app": app_name},
        )

    project_path = Path(env.active_app)
    if not project_path.exists():
        return ActionResult.error(
            f"Project '{app_name}' does not exist.",
            next_action="Refresh the PROJECT page or select another project.",
            data={"app": app_name, "project_path": project_path},
        )

    cleanup_errors: list[str] = []
    target_name = env.target
    _cleanup_run_configuration_artifacts(app_name, target_name, cleanup_errors)
    _cleanup_module_artifacts(app_name, target_name, cleanup_errors)
    _safe_remove_path(
        env.wenv_abs,
        f"worker environment for {target_name}",
        cleanup_errors,
    )
    _safe_remove_path(
        Path.home() / "log" / "execute" / target_name,
        f"log/execute/{target_name}",
        cleanup_errors,
    )

    data_root = None
    if env.app_data_rel:
        try:
            data_root = Path(env.app_data_rel).expanduser()
        except (RuntimeError, TypeError, ValueError):
            data_root = None
    if data_root and data_root.name == target_name:
        _safe_remove_path(
            data_root,
            f"AGI share directory for {target_name}",
            cleanup_errors,
        )

    _safe_remove_path(project_path, f"Project '{app_name}'", cleanup_errors)
    if _path_exists_or_symlink(project_path):
        detail = "\n".join(f"Cleanup issue: {message}" for message in cleanup_errors) or None
        return ActionResult.error(
            f"Project '{app_name}' could not be removed.",
            detail=detail,
            next_action=f"Remove {project_path} manually, then refresh the PROJECT page.",
            data={
                "app": app_name,
                "project_path": project_path,
                "cleanup_errors": tuple(cleanup_errors),
            },
        )

    env.projects = [project for project in env.projects if project != app_name]
    next_app = env.projects[0] if env.projects else None
    detail = "\n".join(f"Cleanup issue: {message}" for message in cleanup_errors) or None
    return ActionResult.success(
        f"Project '{app_name}' has been deleted.",
        detail=detail,
        data={
            "app": app_name,
            "project_path": project_path,
            "cleanup_errors": tuple(cleanup_errors),
            "next_app": next_app,
        },
    )


def handle_project_creation():
    """
    Handle the 'Create' tab in the sidebar for project creation.
    """
    st.header("Create project")
    create_mode = compact_choice(
        st.sidebar,
        "Create mode",
        [CREATE_MODE_TEMPLATE, CREATE_MODE_NOTEBOOK],
        key="create_mode",
        inline_limit=2,
        fallback="radio",
    )
    env = st.session_state["env"]

    if create_mode == CREATE_MODE_NOTEBOOK:
        st.caption(
            "Create a project from a notebook by importing code cells into a template pipeline."
        )
        template_options = list(st.session_state["templates"]) or [env.app]
        default_template = (
            NOTEBOOK_PROJECT_DEFAULT_TEMPLATE
            if NOTEBOOK_PROJECT_DEFAULT_TEMPLATE in template_options
            else template_options[0]
        )
        compact_choice(
            st.sidebar,
            "Notebook template",
            template_options,
            key="notebook_clone_src",
            default=default_template,
            inline_limit=5,
        )
        st.sidebar.file_uploader(
            "Notebook",
            type="ipynb",
            key="create_notebook_upload",
        )
    else:
        st.caption(
            "Create a new project from an existing template. "
            "Use a working clone for real development."
        )
        # choose a template (relative project name, e.g. "flight_telemetry_project")
        compact_choice(
            st.sidebar,
            "Starting point",
            [env.app] + st.session_state["templates"],
            key="clone_src",
            on_change=lambda: on_project_change(
                st.session_state["clone_src"], switch_to_edit=True
            ),
            inline_limit=5,
        )

    clone_env_strategy = compact_choice(
        st.sidebar,
        "Environment strategy",
        list(CLONE_ENV_STRATEGY_LABELS),
        key="clone_env_strategy",
        format_func=CLONE_ENV_STRATEGY_LABELS.get,
        help=CLONE_ENV_STRATEGY_HELP,
        fallback="radio",
    )

    raw = st.sidebar.text_input(
        "New project base name",
        key="clone_dest",
        help="Enter the destination project name. AGILAB appends '_project' if it is missing.",
    ).strip()

    create_clicked = st.sidebar.button("Create", type="primary", width="stretch")
    if create_clicked:
        def _activate_clone(result):
            new_name = str(result.data["new_name"])
            env.change_app(new_name)
            st.session_state["switch_to_edit"] = True
            time.sleep(1.5)
            st.rerun()

        def _activate_notebook_project(result):
            new_name = str(result.data["new_name"])
            env.change_app(new_name)
            st.session_state["project_changed"] = True
            st.session_state["_requested_lab_dir"] = new_name
            st.session_state["lab_dir_selectbox"] = new_name
            st.session_state["project_selectbox"] = new_name
            st.query_params["active_app"] = new_name
            st.query_params["lab_dir_selectbox"] = new_name
            switch_page = getattr(st, "switch_page", None)
            if callable(switch_page):
                switch_page(Path("pages/3_WORKFLOW.py"))
                return
            st.session_state["switch_to_edit"] = True
            st.rerun()

        if create_mode == CREATE_MODE_NOTEBOOK:
            run_streamlit_action(
                st,
                ActionSpec(
                    name="Create project from notebook",
                    start_message=f"Creating project '{raw or '<empty>'}' from notebook...",
                    failure_title="Notebook project creation failed.",
                    failure_next_action=(
                        "Check the notebook upload, template source, destination path, "
                        "and filesystem permissions."
                    ),
                ),
                lambda: _create_project_from_notebook_action(
                    env,
                    template_source=st.session_state.get(
                        "notebook_clone_src",
                        NOTEBOOK_PROJECT_DEFAULT_TEMPLATE,
                    ),
                    raw_project_name=raw,
                    uploaded_notebook=st.session_state.get("create_notebook_upload"),
                    clone_env_strategy=clone_env_strategy,
                ),
                on_success=_activate_notebook_project,
            )
        else:
            run_streamlit_action(
                st,
                ActionSpec(
                    name="Create project",
                    start_message=f"Creating project '{raw or '<empty>'}'...",
                    failure_title="Project creation failed.",
                    failure_next_action="Check the clone source, destination path, and filesystem permissions.",
                ),
                lambda: _create_project_clone_action(
                    env,
                    clone_source=st.session_state["clone_src"],
                    raw_project_name=raw,
                    clone_env_strategy=clone_env_strategy,
                ),
                on_success=_activate_clone,
            )
    else:
        st.sidebar.info("Enter a project name and click 'Create'.")



def normalize_project_name(raw: str) -> str:
    """
    Given a raw string, return a cleaned-up project name:
      - strip whitespace
      - replace spaces or illegal chars with underscore
      - lowercase
      - append '_project' if missing
    """
    name = raw.strip().lower()
    # replace any non-alphanumeric/_ with underscore
    name = re.sub(r"[^0-9a-z_]+", "_", name)
    # collapse multiple underscores
    name = re.sub(r"_+", "_", name).strip("_")
    if not name:
        return ""
    return name if name.endswith("_project") else name + "_project"


def handle_project_rename():
    """
    Handle the 'Rename' tab in the sidebar for renaming projects.
    """
    env = st.session_state["env"]
    current = env.app
    st.header("Project maintenance")
    st.warning(
        f"Rename moves the active project '{current}' and updates AGILAB to the new name."
    )
    st.sidebar.caption("Maintenance action: rename the active project.")

    # — no on_change here —
    raw = st.sidebar.text_input(
        "Rename active project to",
        key="clone_dest",
        help="Enter the destination project name. AGILAB appends '_project' if it is missing.",
    ).strip()

    rename_clicked = st.sidebar.button("Rename", type="primary", width="stretch")
    if rename_clicked:
        def _activate_renamed_project(result):
            new_name = str(result.data["new_name"])
            env.change_app(new_name)
            st.session_state["switch_to_edit"] = True
            st.rerun()

        run_streamlit_action(
            st,
            ActionSpec(
                name="Rename project",
                start_message=f"Renaming project '{current}'...",
                failure_title="Project rename failed.",
                failure_next_action="Check the destination name, source project, and filesystem permissions.",
            ),
            lambda: _rename_project_action(env, raw_project_name=raw),
            on_success=_activate_renamed_project,
        )
    else:
        st.sidebar.info("Enter a base name above and click Rename.")


def handle_project_delete():
    """
    Handle the 'Delete' tab in the sidebar for deleting projects.
    """
    st.header("Danger zone")
    env = st.session_state["env"]
    st.warning(
        f"Deleting '{env.app}' removes the project directory, worker environment, logs, and generated data when AGILAB owns them."
    )
    st.sidebar.caption("Danger zone: destructive project removal.")

    # Confirmation checkbox
    confirm_delete = st.checkbox(
        f"I confirm that I want to delete {env.app}.",
        key="confirm_delete",
    )

    # Delete button
    delete_clicked = st.sidebar.button("Delete", type="primary", width="stretch")
    if delete_clicked:
        def _activate_after_delete(result):
            next_app = result.data.get("next_app")
            if next_app:
                on_project_change(str(next_app))
            st.session_state.pop("env", None)
            st.session_state.pop("templates", None)
            st.session_state["switch_to_edit"] = True
            st.rerun()

        run_streamlit_action(
            st,
            ActionSpec(
                name="Delete project",
                start_message=f"Deleting project '{env.app}'...",
                failure_title="Project deletion failed.",
                failure_next_action="Check filesystem permissions and project selection.",
            ),
            lambda: _delete_project_action(env, confirmed=confirm_delete),
            on_success=_activate_after_delete,
        )
    else:
        st.info("Select a project and confirm deletion to remove it.")


def handle_project_import():
    """
    Handle the 'Import' tab in the sidebar for project loading.
    """
    env = st.session_state["env"]
    st.header("Import project archive")
    st.caption("Restore a project from a previously exported AGILAB archive.")
    selected_archive = compact_choice(
        st.sidebar,
        "Archive to import",
        st.session_state["archives"],
        key="archive",
        help="Select one of the previously exported projects to load it.",
        inline_limit=5,
    )
    st.sidebar.caption(f"Export archive folder: {env.export_apps}")

    if selected_archive == "-- Select a file --":
        st.info("Please select a file from the sidebar to continue.")
        # Optionally, you can disable other parts of the app here
    else:
        import_target = selected_archive.replace(".zip", "")
        st.sidebar.caption(f"Will restore as project: {import_target}")
        st.sidebar.checkbox(
            "Clean",
            key="clean_import",
            help="This will remove all the .gitignore file from the project.",
        )

        target_dir = env.apps_path / import_target
        overwrite_modal = Modal("Import project", key="import-modal", max_width=450)

        def _activate_import(result):
            imported_project = str(result.data["import_target"])
            env.change_app(imported_project)
            on_project_change(imported_project)
            st.session_state["switch_to_edit"] = True
            st.rerun()

        def _run_import_action(*, overwrite: bool) -> None:
            run_streamlit_action(
                st,
                ActionSpec(
                    name="Import project",
                    start_message=f"Importing project '{import_target}'...",
                    failure_title="Project import failed.",
                    failure_next_action="Check the archive, destination path, and filesystem permissions.",
                ),
                lambda: _import_project_action(
                    env,
                    project_zip=selected_archive,
                    clean=st.session_state["clean_import"],
                    overwrite=overwrite,
                ),
                on_success=_activate_import,
            )

        import_clicked = st.sidebar.button(
            "Import", type="primary", width="stretch"
        )
        if import_clicked:
            if not target_dir.exists():
                _run_import_action(overwrite=False)
            else:
                overwrite_modal.open()

        if overwrite_modal.is_open():
            with overwrite_modal.container():
                st.write(f"Project '{import_target}' already exists. Overwrite it?")
                cols = st.columns(2)
                if cols[0].button(
                        "Overwrite", type="primary", width="stretch"
                ):
                    _run_import_action(overwrite=True)
                if cols[1].button("Cancel", type="primary", width="stretch"):
                    overwrite_modal.close()


# -------------------- Streamlit Page Rendering -------------------- #


def page():
    """
    Main function to render the Streamlit page.
    """
    global CUSTOM_BUTTONS, INFO_BAR, CSS_TEXT, comp_props, ace_props

    env = ensure_page_env(st, __file__)
    if env is None:
        return
    st.session_state['_env'] = env

    env = st.session_state['_env']
    st.set_page_config(
        page_title="AGILab PROJECT",
        layout="wide",
        menu_items=get_docs_menu_items(html_file="edit-help.html"),
    )
    inject_theme(env.st_resources)

    render_logo()
    render_pinned_expanders(st)
    render_page_context(st, page_label="PROJECT", env=env)

    if background_services_enabled() and not st.session_state.get("server_started"):
        activate_mlflow(env)

    # Check if we need to switch the sidebar tab to "Select"
    if st.session_state.get("switch_to_edit", False):
        st.session_state["sidebar_selection"] = "Edit"
        st.session_state["switch_to_edit"] = False
        st.rerun()  # Reset the flag  # Trigger rerun to apply the change

    # Load .agi_resources

    try:
        with open(env.st_resources / "custom_buttons.json") as f:
            CUSTOM_BUTTONS = normalize_custom_buttons(json.load(f))
        with open(env.st_resources / "info_bar.json") as f:
            INFO_BAR = json.load(f)
        with open(env.st_resources / "code_editor.scss") as f:
            CSS_TEXT = f.read()
    except FileNotFoundError as e:
        st.error(f"Resource file not found: {e}")
        return
    except json.JSONDecodeError as e:
        st.error(f"Error decoding JSON resource: {e}")
        return
    except TypeError as e:
        st.error(f"Invalid code editor resource: {e}")
        return

    comp_props = {
        "css": CSS_TEXT,
        "globalCSS": ":root {--streamlit-dark-background-color: #111827;}",
    }
    ace_props = {"style": {"borderRadius": "0px 0px 8px 8px"}}

    # Initialize session state variables
    session_defaults = {
        "env": env,
        "_env": env,
        "orchest_functions": ["build_distribution"],
        "templates": get_templates(),
        "archives": ["-- Select a file --"] + get_projects_zip(),
        "export_message": "",
        "project_imported": False,
        "project_created": False,
        "show_widgets": [True, False],
        "pages": [],
        # Initialize the sidebar_selection with a default value if not set
        "sidebar_selection": (
            "Edit"
            if "sidebar_selection" not in st.session_state
            else st.session_state["sidebar_selection"]
        ),
        # Initialize the switch_to_edit flag
        "switch_to_edit": (
            False
            if "switch_to_edit" not in st.session_state
            else st.session_state["switch_to_edit"]
        ),
    }

    for key, value in session_defaults.items():
        st.session_state.setdefault(key, value)

    if st.session_state.get("sidebar_selection") == "Clone":
        st.session_state["sidebar_selection"] = "Create"

    _render_active_project_sidebar(env)
    env = st.session_state["env"]
    _render_sidebar_export_action(env)

    # Sidebar: Project selection, creation, loading
    sidebar_selection = compact_choice(
        st.sidebar,
        "Project action",
        ["Edit", "Create", "Import", "Rename", "Delete"],
        key="sidebar_selection",
        label_visibility="collapsed",
        fallback="radio",
    )

    if sidebar_selection == "Edit":
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

    except (RuntimeError, OSError, TypeError, ValueError, AttributeError, KeyError) as e:
        st.error(f"An error occurred: {e}")
        import traceback

        st.caption("Full traceback")
        st.code(traceback.format_exc(), language="text")


# -------------------- Main Entry Point -------------------- #

if __name__ == "__main__":
    main()
