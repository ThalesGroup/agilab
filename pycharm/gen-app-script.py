import os
import sys
import xml.etree.ElementTree as ET
import filecmp
import tempfile

def update_workspace_xml(config_name, config_type, folder_name):
    workspace_path = os.path.join(os.getcwd(), '.idea', 'workspace.xml')
    # If file does not exist, create minimal skeleton
    if not os.path.exists(workspace_path):
        root = ET.Element('project', version="4")
        ET.SubElement(root, 'component', {'name': 'RunManager'})
        tree = ET.ElementTree(root)
        tree.write(workspace_path)
    tree = ET.parse(workspace_path)
    root = tree.getroot()
    runmanager = root.find("./component[@name='RunManager']")
    if runmanager is None:
        runmanager = ET.SubElement(root, 'component', {'name': 'RunManager'})
    # Check for existing configuration
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
            'factoryName': config_type.replace('ConfigurationType', ''),  # not always correct but safe
        })
    else:
        config_el.attrib['folderName'] = folder_name

    tree.write(workspace_path, encoding="utf-8", xml_declaration=True)
    print(f"Updated workspace.xml for config '{config_name}' in folder '{folder_name}'.")


def update_folders_xml(folder_name):
    output_dir = os.path.join(os.getcwd(), '.idea', 'runConfigurations')
    folders_xml_path = os.path.join(output_dir, 'folders.xml')

    if os.path.exists(folders_xml_path):
        tree = ET.parse(folders_xml_path)
        root = tree.getroot()
    else:
        root = ET.Element('component', attrib={'name': 'RunManager'})
        tree = ET.ElementTree(root)

    # Check if folder already exists
    existing = root.find(f"./folder[@name='{folder_name}']")
    if existing is None:
        ET.SubElement(root, 'folder', attrib={'name': folder_name})
        tree.write(folders_xml_path, encoding='utf-8', xml_declaration=True)
        print(f"Added folder '{folder_name}' to folders.xml")
    else:
        print(f"Folder '{folder_name}' already exists in folders.xml")


def add_folder_name_to_config(tree, folder_name):
    config_elem = next(tree.getroot().iter('configuration'), None)
    if config_elem is not None:
        config_elem.attrib['folderName'] = folder_name


if len(sys.argv) < 2:
    print("Usage: script.py <replacement_name>")
    sys.exit(1)

app = sys.argv[1]
if not app:
    print("No name entered. Exiting.")
    sys.exit(1)

print(f"Replacement name: {app}")

template_paths = [
    'pycharm/_template_app_egg_manager.xml',
    'pycharm/_template_app_lib_worker.xml',
    'pycharm/_template_app_preinstall_manager.xml',
    'pycharm/_template_app_postinstall_worker.xml',
    'pycharm/_template_app_run.xml',
    'pycharm/_template_app_distribute.xml',
    'pycharm/_template_app_test_manager.xml',
    'pycharm/_template_app_test_worker.xml',
    'pycharm/_template_app_test.xml',
]

output_dir = os.path.join(os.getcwd(), '.idea', 'runConfigurations')
os.makedirs(output_dir, exist_ok=True)

FOLDER_NAME = f"{app}"

for tpl in template_paths:
    tree = ET.parse(tpl)
    root = tree.getroot()

    # replace {APP} placeholders
    for el in root.iter():
        for k, v in el.attrib.items():
            if '{APP}' in v:
                el.attrib[k] = v.replace('{APP}', app)
        if el.text and '{APP}' in el.text:
            el.text = el.text.replace('{APP}', app)

    # Add folderName attribute to configuration element
    add_folder_name_to_config(tree, FOLDER_NAME)

    # derive output filename
    base = os.path.basename(tpl).replace('_template_app', f'_{app}')
    out_path = os.path.join(output_dir, base)

    # Get config name/type for workspace.xml
    config_elem = next(root.iter('configuration'))
    config_name = config_elem.attrib.get('name', base.rsplit('.', 1)[0])
    config_type = config_elem.attrib.get('type', 'PythonConfigurationType')

    # --- idempotency check ----------------
    if os.path.exists(out_path):
        fd, tmp_path = tempfile.mkstemp(suffix='.xml')
        os.close(fd)
        tree.write(tmp_path)
        if filecmp.cmp(tmp_path, out_path, shallow=False):
            print(f"Skipped (unchanged): {out_path}")
            os.remove(tmp_path)
        else:
            os.replace(tmp_path, out_path)
            print(f"Updated config (changed): {out_path}")
        update_workspace_xml(config_name, config_type, FOLDER_NAME)
        continue

    # first time write
    tree.write(out_path)
    print(f"Generated config: {out_path}")
    update_workspace_xml(config_name, config_type, FOLDER_NAME)

# Update folders.xml once after processing all templates
update_folders_xml(FOLDER_NAME)

print(f"All {app} configurations processed.")


# ======================
# Interpreter patching (auto-run, no CLI args; keeps your original functions)
# ======================
import time
import shutil
from pathlib import Path as _PathAlias  # avoid shadowing
import xml.etree.ElementTree as _ETAlias

def _pretty_write_xml(tree: _ETAlias.ElementTree, target: _PathAlias) -> None:
    tree.write(target, encoding="utf-8", xml_declaration=True)

def set_project_interpreter_in_workspace(project_root: str | os.PathLike) -> bool:
    """
    Patch .idea/workspace.xml AND .idea/misc.xml to set:
        project-jdk-type="Python SDK"
        project-jdk-name="uv (<folder-name>)"
    Only if .venv exists in project_root.
    Returns True if changed, False otherwise.
    """
    project_root = Path(project_root)
    idea_dir = project_root / ".idea"
    workspace_xml = idea_dir / "workspace.xml"
    misc_xml = idea_dir / "misc.xml"
    venv_dir = project_root / ".venv"

    if not idea_dir.is_dir() or not workspace_xml.is_file() or not venv_dir.exists():
        return False

    folder_name = project_root.name
    desired_name = f"uv ({folder_name})"

    # --- workspace.xml ---
    try:
        tree_ws = ET.parse(workspace_xml)
    except ET.ParseError as e:
        print(f"[workspace.xml] {folder_name}: XML parse error: {e}")
        return False

    root_ws = tree_ws.getroot()
    prm_ws = None
    for comp in root_ws.findall("component"):
        if comp.get("name") == "ProjectRootManager":
            prm_ws = comp
            break
    if prm_ws is None:
        prm_ws = ET.SubElement(root_ws, "component", {"name": "ProjectRootManager"})

    changed = False
    if prm_ws.get("project-jdk-type") != "Python SDK":
        prm_ws.set("project-jdk-type", "Python SDK")
        changed = True
    if prm_ws.get("project-jdk-name") != desired_name:
        prm_ws.set("project-jdk-name", desired_name)
        changed = True

    if changed:
        backup_path = workspace_xml.with_suffix(f".xml.bak-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(workspace_xml, backup_path)
        tree_ws.write(workspace_xml, encoding="utf-8", xml_declaration=True)
        print(f"[workspace.xml] {folder_name}: set interpreter -> '{desired_name}' (backup: {backup_path.name})")

    # --- misc.xml ---
    if misc_xml.exists():
        try:
            tree_misc = ET.parse(misc_xml)
            root_misc = tree_misc.getroot()
        except ET.ParseError as e:
            print(f"[misc.xml] {folder_name}: XML parse error: {e}")
            return changed
    else:
        root_misc = ET.Element("project", version="4")
        tree_misc = ET.ElementTree(root_misc)

    prm_misc = None
    for comp in root_misc.findall("component"):
        if comp.get("name") == "ProjectRootManager":
            prm_misc = comp
            break
    if prm_misc is None:
        prm_misc = ET.SubElement(root_misc, "component", {"name": "ProjectRootManager"})

    if prm_misc.get("project-jdk-type") != "Python SDK":
        prm_misc.set("project-jdk-type", "Python SDK")
        changed = True
    if prm_misc.get("project-jdk-name") != desired_name:
        prm_misc.set("project-jdk-name", desired_name)
        changed = True
    if prm_misc.get("version") != "2":
        prm_misc.set("version", "2")
        changed = True

    if changed:
        tree_misc.write(misc_xml, encoding="utf-8", xml_declaration=True)
        print(f"[misc.xml] {folder_name}: set interpreter declaration -> '{desired_name}'")

    return changed

def patch_apps_interpreters(apps_base: str | os.PathLike, suffix: str = "_project") -> int:
    """
    Scan only immediate subdirectories of apps_base whose names end with `suffix`.
    For each, if .venv and .idea/workspace.xml exist, set interpreter to 'uv (<folder-name>)'.
    """
    base = _PathAlias(apps_base).resolve()
    if not base.is_dir():
        return 0

    updated = 0
    for sub in sorted(p for p in base.iterdir() if p.is_dir() and p.name.endswith(suffix)):
        try:
            if set_project_interpreter_in_workspace(sub):
                updated += 1
            else:
                print(f"[patch-apps] {sub.name}: skipped (no .venv/.idea or no change)")
        except Exception as e:
            print(f"[patch-apps] {sub.name}: ERROR {e}")
    if updated:
        print(f"[patch-apps] Done. Updated {updated} project(s).")
    return updated

def patch_interpreters_recursively(base_dir: str | os.PathLike) -> int:
    """
    Recursively scan base_dir for directories that contain both .venv and .idea/workspace.xml
    and patch each one.
    """
    base_dir = _PathAlias(base_dir).resolve()
    if not base_dir.is_dir():
        return 0

    updated = 0
    for venv in base_dir.rglob(".venv"):
        project_root = venv.parent
        try:
            if set_project_interpreter_in_workspace(project_root):
                updated += 1
        except Exception as e:
            print(f"[workspace.xml] {project_root.name}: ERROR {e}")
    if updated:
        print(f"[patch-venvs] Done. Updated {updated} project(s).")
    return updated

# ----------------------
# AUTO-RUN (single recursive pass, no CLI args)
# ----------------------
try:
    from pathlib import Path as _PathAlias
    _script_dir = _PathAlias(__file__).resolve().parent

    # Deduplicate projects by folder containing a .venv
    projects = {venv.parent for venv in _script_dir.rglob(".venv")}

    updated = 0
    for proj in sorted(projects):
        try:
            if set_project_interpreter_in_workspace(proj):
                updated += 1
        except Exception as e:
            print(f"[workspace.xml] {proj.name}: ERROR {e}")

    if updated:
        print(f"[patch-venvs] Done. Updated {updated} project(s).")
    else:
        print("[patch-venvs] No interpreters updated (no .venv/.idea combos found).")
except Exception as _e:
    print(f"[patch-venvs] ERROR during interpreter patching: {_e}")
