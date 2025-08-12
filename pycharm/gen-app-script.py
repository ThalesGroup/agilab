#!/usr/bin/env python3
import os
import sys
import filecmp
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

# ---------- paths ----------
SCRIPT_DIR = Path(__file__).resolve().parent  # .../pycharm
TEMPLATES = [
    "_template_app_egg_manager.xml",
    "_template_app_lib_worker.xml",
    "_template_app_preinstall_manager.xml",
    "_template_app_postinstall_worker.xml",
    "_template_app_run.xml",
    "_template_app_distribute.xml",
    "_template_app_test_manager.xml",
    "_template_app_test_worker.xml",
    "_template_app_test.xml",
]

# ---------- helpers ----------
def venv_python_for(project_dir: Path) -> Optional[Path]:
    """Return the project's .venv python, if present."""
    candidates = [
        project_dir / ".venv" / "bin" / "python3",       # unix/mac
        project_dir / ".venv" / "bin" / "python",        # unix/mac alt
        project_dir / ".venv" / "Scripts" / "python.exe" # windows
    ]
    for p in candidates:
        if p.exists():
            return p.resolve()
    return None

def parse_template(name: str) -> ET.ElementTree:
    tpl_path = SCRIPT_DIR / name
    if not tpl_path.exists():
        raise FileNotFoundError(f"Template not found: {tpl_path}")
    return ET.parse(str(tpl_path))

def ensure_option(config_elem: ET.Element, name: str, value: str) -> None:
    """Ensure <option name=... value=.../> exists (create or update)."""
    for o in config_elem.iter("option"):
        if o.get("name") == name:
            o.set("value", value)
            return
    ET.SubElement(config_elem, "option", {"name": name, "value": value})

def add_folder_name_to_config(tree: ET.ElementTree, folder_name: str) -> None:
    config_elem = next(tree.getroot().iter("configuration"), None)
    if config_elem is not None:
        config_elem.attrib["folderName"] = folder_name

def patch_sdk_home(tree: ET.ElementTree, py: Path) -> None:
    """Set SDK_HOME to the provided interpreter and disable module SDK."""
    config_elem = next(tree.getroot().iter("configuration"), None)
    if config_elem is None:
        return
    ensure_option(config_elem, "SDK_HOME", str(py))
    ensure_option(config_elem, "IS_MODULE_SDK", "false")
    # SDK_NAME optional when SDK_HOME is set; leave as-is if present.

def update_workspace_xml(config_name: str, config_type: str, folder_name: str) -> None:
    """Ensure the run configuration entry appears in workspace.xml (RunManager component)."""
    idea = Path.cwd() / ".idea"
    idea.mkdir(exist_ok=True)
    workspace_path = idea / "workspace.xml"

    # Minimal skeleton if missing
    if not workspace_path.exists():
        root = ET.Element("project", {"version": "4"})
        ET.SubElement(root, "component", {"name": "RunManager"})
        ET.ElementTree(root).write(workspace_path, encoding="UTF-8", xml_declaration=True)

    tree = ET.parse(workspace_path)
    root = tree.getroot()
    runmanager = root.find("./component[@name='RunManager']")
    if runmanager is None:
        runmanager = ET.SubElement(root, "component", {"name": "RunManager"})

    # find existing
    config_el = None
    for conf in runmanager.findall("configuration"):
        if conf.attrib.get("name") == config_name and conf.attrib.get("type") == config_type:
            config_el = conf
            break

    if config_el is None:
        # factoryName isn't strictly needed; PyCharm fills it. Keep type only.
        config_el = ET.SubElement(runmanager, "configuration", {
            "name": config_name,
            "type": config_type,
            "folderName": folder_name
        })
    else:
        config_el.attrib["folderName"] = folder_name

    tree.write(workspace_path, encoding="UTF-8", xml_declaration=True)
    print(f"Updated workspace.xml for config '{config_name}' in folder '{folder_name}'.")

def update_folders_xml(folder_name: str) -> None:
    """Ensure the folder exists in .idea/runConfigurations/folders.xml."""
    output_dir = Path.cwd() / ".idea" / "runConfigurations"
    output_dir.mkdir(parents=True, exist_ok=True)
    folders_xml_path = output_dir / "folders.xml"

    if folders_xml_path.exists():
        tree = ET.parse(folders_xml_path)
        root = tree.getroot()
    else:
        root = ET.Element("component", {"name": "RunManager"})
        tree = ET.ElementTree(root)

    existing = root.find(f"./folder[@name='{folder_name}']")
    if existing is None:
        ET.SubElement(root, "folder", {"name": folder_name})
        tree.write(folders_xml_path, encoding="UTF-8", xml_declaration=True)
        print(f"Added folder '{folder_name}' to folders.xml")
    else:
        print(f"Folder '{folder_name}' already exists in folders.xml")

def replace_placeholders(tree: ET.ElementTree, app: str) -> None:
    """Replace {APP} placeholders in attributes and text."""
    for el in tree.getroot().iter():
        # attributes
        for k, v in list(el.attrib.items()):
            if v and "{APP}" in v:
                el.set(k, v.replace("{APP}", app))
        # text
        if el.text and "{APP}" in el.text:
            el.text = el.text.replace("{APP}", app)

# ---------- main ----------
def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: gen-app-script.py <module_name>")
        return 2

    app = sys.argv[1].strip()
    if not app:
        print("No module name provided.")
        return 2

    print(f"Replacement name: {app}")

    # Ensure .idea/runConfigurations exists under the *current* project dir
    output_dir = Path.cwd() / ".idea" / "runConfigurations"
    output_dir.mkdir(parents=True, exist_ok=True)
    folder_name = app

    # Try to locate the interpreter of this project's venv
    project_dir = Path.cwd()
    py = venv_python_for(project_dir)

    for tpl_name in TEMPLATES:
        tree = parse_template(tpl_name)

        # Replace APP placeholders + folderName
        replace_placeholders(tree, app)
        add_folder_name_to_config(tree, folder_name)

        # Always patch SDK_HOME (new or existing)
        if py:
            patch_sdk_home(tree, py)

        # Output file name: _template_app_X.xml -> _<app>_X.xml
        out_base = Path(tpl_name).name.replace("_template_app", f"_{app}")
        out_path = output_dir / out_base

        # Read config name/type for workspace.xml (after placeholder replacement)
        config_elem = next(tree.getroot().iter("configuration"))
        config_name = config_elem.attrib.get("name", out_base.rsplit(".", 1)[0])
        config_type = config_elem.attrib.get("type", "PythonConfigurationType")

        # Idempotent write (compare first)
        if out_path.exists():
            fd, tmp_path = tempfile.mkstemp(suffix=".xml")
            os.close(fd)
            tree.write(tmp_path, encoding="UTF-8", xml_declaration=True)
            if filecmp.cmp(tmp_path, out_path, shallow=False):
                print(f"Skipped (unchanged): {out_path}")
                os.remove(tmp_path)
            else:
                os.replace(tmp_path, out_path)
                print(f"Updated config (changed): {out_path}")
            update_workspace_xml(config_name, config_type, folder_name)
            continue

        # First time write
        tree.write(out_path, encoding="UTF-8", xml_declaration=True)
        print(f"Generated config: {out_path}")
        update_workspace_xml(config_name, config_type, folder_name)

    # One-time folders.xml update
    update_folders_xml(folder_name)
    print(f"All {app} configurations processed.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
