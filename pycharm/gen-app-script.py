#!/usr/bin/env python3
import os
import sys
import xml.etree.ElementTree as ET
import filecmp
import tempfile
import glob
import platform
from pathlib import Path

# -----------------------------
# Helpers for paths / platform
# -----------------------------
def py_exe_from_venv(venv_dir: Path) -> Path:
    """Return python executable inside a venv."""
    if platform.system().lower().startswith("win"):
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"

def ensure_parent_dir(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)

# -----------------------------
# Run configuration utilities
# -----------------------------
def update_workspace_xml(config_name, config_type, folder_name, idea_dir: Path):
    workspace_path = idea_dir / "workspace.xml"
    if not workspace_path.exists():
        root = ET.Element('project', version="4")
        ET.SubElement(root, 'component', {'name': 'RunManager'})
        ET.ElementTree(root).write(workspace_path)
    tree = ET.parse(workspace_path)
    root = tree.getroot()
    runmanager = root.find("./component[@name='RunManager']")
    if runmanager is None:
        runmanager = ET.SubElement(root, 'component', {'name': 'RunManager'})

    config_el = None
    for conf in runmanager.findall('configuration'):
        if conf.attrib.get('name') == config_name and conf.attrib.get('type') == config_type:
            config_el = conf
            break

    if config_el is None:
        config_el = ET.SubElement(runmanager, 'configuration', {
            'name': config_name,
            'type': config_type,
            'folderName': folder_name,
            'factoryName': config_type.replace('ConfigurationType', ''),
        })
    else:
        config_el.attrib['folderName'] = folder_name

    tree.write(workspace_path, encoding="utf-8", xml_declaration=True)
    write_pretty_xml(tree, workspace_path)
    print(f"[workspace.xml] Set folder='{folder_name}' for config '{config_name}' (type={config_type}).")

def update_folders_xml(folder_name, idea_dir: Path):
    run_cfg_dir = idea_dir / 'runConfigurations'
    run_cfg_dir.mkdir(parents=True, exist_ok=True)
    folders_xml_path = run_cfg_dir / 'folders.xml'

    if folders_xml_path.exists():
        tree = ET.parse(folders_xml_path)
        root = tree.getroot()
    else:
        root = ET.Element('component', attrib={'name': 'RunManager'})
        tree = ET.ElementTree(root)

    existing = root.find(f"./folder[@name='{folder_name}']")
    if existing is None:
        ET.SubElement(root, 'folder', attrib={'name': folder_name})
        write_pretty_xml(tree, folders_xml_path)
        print(f"[folders.xml] Added folder '{folder_name}'.")
    else:
        print(f"[folders.xml] Folder '{folder_name}' already present.")

def add_folder_name_to_config(tree, folder_name):
    config_elem = next(tree.getroot().iter('configuration'), None)
    if config_elem is not None:
        config_elem.attrib['folderName'] = folder_name

def write_pretty_xml(tree: ET.ElementTree, path):
    """Write XML tree to file with indentation."""
    xml_bytes = ET.tostring(tree.getroot(), encoding="utf-8")
    parsed = minidom.parseString(xml_bytes)
    pretty_xml = parsed.toprettyxml(indent="  ", encoding="utf-8")
    with open(path, "wb") as f:
        f.write(pretty_xml)

# -----------------------------
# PyCharm SDK / interpreter patcher
# -----------------------------
def ensure_jdk_table_sdk(sdk_name: str, home_path: Path, idea_dir: Path):
    """Create/update a Python SDK entry in .idea/jdk.table.xml."""
    jdk_table = idea_dir / "jdk.table.xml"
    if jdk_table.exists():
        tree = ET.parse(jdk_table)
        root = tree.getroot()
    else:
        root = ET.Element("application")
        tree = ET.ElementTree(root)

    comp = root.find("./component[@name='ProjectJdkTable']")
    if comp is None:
        comp = ET.SubElement(root, "component", {"name": "ProjectJdkTable"})

    # find sdk by name
    jdk = None
    for j in comp.findall("jdk"):
        if j.attrib.get("name") == sdk_name and j.attrib.get("type") == "Python SDK":
            jdk = j
            break

    if jdk is None:
        jdk = ET.SubElement(comp, "jdk", {"name": sdk_name, "type": "Python SDK", "version": ""})
        ET.SubElement(jdk, "homePath").text = str(home_path)
        ET.SubElement(jdk, "roots")
        ET.SubElement(jdk, "additional")
        print(f"[jdk.table.xml] Added SDK '{sdk_name}' -> {home_path}")
    else:
        hp = jdk.find("homePath")
        if hp is None:
            hp = ET.SubElement(jdk, "homePath")
        old = hp.text
        hp.text = str(home_path)
        print(f"[jdk.table.xml] Updated SDK '{sdk_name}' homePath: {old} -> {home_path}")

    ensure_parent_dir(jdk_table)
    write_pretty_xml(tree, jdk_table)

def set_project_interpreter(sdk_name: str, idea_dir: Path):
    """Set the project interpreter in .idea/misc.xml."""
    misc = idea_dir / "misc.xml"
    if misc.exists():
        tree = ET.parse(misc)
        root = tree.getroot()
    else:
        root = ET.Element("project", {"version": "4"})
        tree = ET.ElementTree(root)

    prm = root.find("./component[@name='ProjectRootManager']")
    if prm is None:
        prm = ET.SubElement(root, "component", {"name": "ProjectRootManager", "version": "2"})

    prm.set("project-jdk-name", sdk_name)
    prm.set("project-jdk-type", "Python SDK")

    ensure_parent_dir(misc)
    write_pretty_xml(tree, misc)
    print(f"[misc.xml] Project interpreter set to '{sdk_name}'.")

def patch_module_iml_to_sdk(iml_file: Path, sdk_name: str):
    """Ensure module uses given SDK."""
    try:
        tree = ET.parse(iml_file)
        root = tree.getroot()
    except ET.ParseError:
        print(f"[iml] Skip unparsable: {iml_file}")
        return

    comp = root.find("./component[@name='NewModuleRootManager']")
    if comp is None:
        return

    # remove existing jdk entries
    for oe in list(comp.findall("orderEntry")):
        if oe.attrib.get("type") in ("jdk", "inheritedJdk"):
            comp.remove(oe)

    # add our jdk
    ET.SubElement(comp, "orderEntry", {"type": "jdk", "jdkName": sdk_name, "jdkType": "Python SDK"})

    write_pretty_xml(tree, iml_file)
    print(f"[iml] {iml_file.name}: set SDK -> {sdk_name}")

def patch_everything_with_local_venvs(project_root: Path):
    """
    Treat every directory that contains a .venv as a 'project/app':
      - create SDK 'uv (<name>)' from that .venv
      - if it is the root .idea, point project interpreter to root's SDK
      - set each *.iml that belongs to that folder to use its SDK
    """
    idea_dir = project_root / ".idea"
    if not idea_dir.exists():
        print("[patch] No .idea directory at project root; skipping PyCharm patch.")
        return

    # 1) gather all folders that look like projects (= have .venv)
    candidates = []
    for d in [project_root] + [p for p in project_root.iterdir() if p.is_dir()]:
        venv = d / ".venv"
        if venv.exists() and venv.is_dir() and py_exe_from_venv(venv).exists():
            candidates.append(d)

    if not candidates:
        print("[patch] No local .venv found anywhere — nothing to patch.")
        return

    # 2) create/update SDK for each, name = uv (<foldername>)
    for d in candidates:
        name = d.name if d != project_root else project_root.name
        sdk_name = f"uv ({name})"
        py = py_exe_from_venv(d / ".venv")
        ensure_jdk_table_sdk(sdk_name, py, idea_dir)

    # 3) project-level interpreter = prefer root .venv if present; otherwise first candidate
    if (project_root / ".venv").exists():
        root_sdk = f"uv ({project_root.name})"
    else:
        cand = candidates[0]
        root_sdk = f"uv ({cand.name})" if cand != project_root else f"uv ({project_root.name})"
    set_project_interpreter(root_sdk, idea_dir)

    # 4) set module SDKs per folder .venv
    # Map folder -> sdk
    folder_to_sdk = {}
    for d in candidates:
        key = d.name if d != project_root else project_root.name
        folder_to_sdk[key] = f"uv ({key})"

    # Patch every *.iml that lives directly under project root (.idea lists modules there)
    for iml_path in project_root.glob("*.iml"):
        # Heuristic: match IML base name to folder name when possible
        base = iml_path.stem
        sdk = folder_to_sdk.get(base, root_sdk)
        patch_module_iml_to_sdk(iml_path, sdk)

# -----------------------------
# Main (your generator logic)
# -----------------------------
def main():
    if len(sys.argv) < 2:
        print("Usage: gen-app-script.py <app_name>")
        sys.exit(1)

    app = sys.argv[1].strip()
    if not app:
        print("No name entered. Exiting.")
        sys.exit(1)

    print(f"Replacement name: {app}")

    project_root = Path.cwd()
    idea_dir = project_root / ".idea"
    run_cfg_dir = idea_dir / "runConfigurations"
    run_cfg_dir.mkdir(parents=True, exist_ok=True)

    template_paths = [
        'pycharm/_template_app_modules.xml',
        'pycharm/_template_app_egg_manager.xml',
        'pycharm/_template_app_lib_worker.xml',
        'pycharm/_template_app_preinstall_manager.xml',
        'pycharm/_template_app_postinstall_worker.xml',
        'pycharm/_template_app_run.xml',
        'pycharm/_template_app_test_manager.xml',
        'pycharm/_template_app_test_worker.xml',
        'pycharm/_template_app_test.xml',
    ]

    FOLDER_NAME = f"{app}"

    for tpl in template_paths:
        tree = ET.parse(tpl)
        root = tree.getroot()

        # Replace {APP}
        for el in root.iter():
            for k, v in list(el.attrib.items()):
                if '{APP}' in v:
                    el.attrib[k] = v.replace('{APP}', app)
            if el.text and '{APP}' in el.text:
                el.text = el.text.replace('{APP}', app)

        if tpl.name.endswith("modules.iml"):
            base = os.path.basename(tpl).replace('_template_app_', '')
            out_path = idea_dir / base
            write_pretty_xml(tree, out_path)
            print(f"Generated config: {out_path}")
            continue

        # Add folder name
        add_folder_name_to_config(tree, FOLDER_NAME)
        base = os.path.basename(tpl).replace('_template_app', f'_{app}')
        # Extract config name/type for workspace.xml
        config_elem = next(root.iter('configuration'))
        config_name = config_elem.attrib.get('name', base.rsplit('.', 1)[0])
        config_type = config_elem.attrib.get('type', 'PythonConfigurationType')

        out_path = run_cfg_dir / base
        # idempotency
        if out_path.exists():
            fd, tmp_path = tempfile.mkstemp(suffix='.xml')
            os.close(fd)
            write_pretty_xml(tree, tmp_path)
            if filecmp.cmp(tmp_path, out_path, shallow=False):
                print(f"Skipped (unchanged): {out_path}")
                os.remove(tmp_path)
            else:
                os.replace(tmp_path, out_path)
                print(f"Updated config (changed): {out_path}")
                update_workspace_xml(config_name, config_type, FOLDER_NAME, idea_dir)
        else:
            write_pretty_xml(tree, out_path)
            print(f"Generated config: {out_path}")
            update_workspace_xml(config_name, config_type, FOLDER_NAME, idea_dir)

    # Once after all
    update_folders_xml(FOLDER_NAME, idea_dir)

    # NEW: Patch interpreters for all projects/modules that have .venv
    patch_everything_with_local_venvs(project_root)

    print(f"All {app} configurations processed.")

if __name__ == "__main__":
    main()
